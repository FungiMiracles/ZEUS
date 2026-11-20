"""Kolej (administrator, 19 Nov 2026).

- technologie: „Krajowe węzły komunikacyjne” (50 pkt, 14 dni) → „Transport kolejowy” (200 pkt, 21 dni); po opracowaniu
  kolei na ekranie „Infrastruktura i energetyka” pojawia się zakładka „Komunikacja”;
- gracz łączy dwa miasta (widoczne na mapie) torami; koszt 6 mln ROI za km trasy, pobierany z budżetu infrastruktury;
- budowa trwa 1 dzień Entendy na każde pełne 50 km trasy (230 km → 4 dni), najmniej 1 dzień;
- trasa biegnie wewnątrz terytorium państwa (bez terytoriów zamorskich); linia do miasta bezpośredniego sąsiada biegnie
  przez oba państwa — sąsiad musi zaakceptować współfinansowanie proporcjonalne do długości trasy po jego stronie granicy;
  budowa rusza po akceptacji (jak dawne wspólne drogi);
- bonus budżetowy (game.finance_service.calculate_budget): PKB per capita × 0,01 × ludność miast państwa w spójnej sieci
  kolejowej (każde miasto liczone raz), w każdym cyklu budżetowym. 20 Nov 2026: liczy się tylko jedna sieć — największa
  (wg ludności własnych miast) spójna składowa ukończonych linii; osobne odcinki A–B, C–D, E–F się nie sumują.
  Miasta sąsiadów mogą być węzłami sieci (linie międzynarodowe), ale ich ludność się nie liczy.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from math import hypot
from flask import Blueprint, jsonify, request
from sqlalchemy import select, or_, func
from sqlalchemy.orm import Session
from extensions import db
from models import Miasto, Panstwo
from game.models import utc_now
from game.finance_service import FinanceError, FinanceConflict, _country_for_user, game_now
from game.budget_transfers import precise
from game.governance import controller_id, controlled_ids
from game.rail_models import RailLine, RailExpense

rail_bp = Blueprint('game_rail', __name__, url_prefix='/game/kolej')

TECHNOLOGY = 'rail_transport'
HUBS_TECHNOLOGY = 'national_hubs'
PRICE_PER_KM = Decimal('6000000')
KM_PER_DAY = 50
BONUS_RATE = Decimal('0.01')
ENDPOINT_SNAP_KM = 25        # miasto portowe leżące tuż poza wielokątem regionu: tor zaczyna się w najbliższym punkcie lądu
TRAIN_SPEED = 120            # km/h czasu gry (animacja pociągów)
OPEN = ('PENDING', 'ACTIVE')


def build_days(distance_km):
    """1 dzień Entendy na każde pełne 50 km (końcówki ucinane), najmniej 1 dzień."""
    return max(1, int(Decimal(distance_km) // KM_PER_DAY))


def has_technology(session, country):
    from game.industry_service import researched
    return researched(session, country, TECHNOLOGY)


def require_technology(session, country):
    if not has_technology(session, country):
        raise FinanceError('Najpierw opracuj technologię „Transport kolejowy”.')


# ---------- miasta i geometria ----------

def city_rows(session, country_ids):
    from game.military_geography import city_point
    rows = session.execute(select(Miasto.miasto_id, Miasto.miasto_nazwa, Miasto.panstwo_id, Miasto.miasto_populacja, Miasto.region_id)
                           .where(Miasto.panstwo_id.in_(list(country_ids)), Miasto.czy_na_mapie == 'TAK')).all()
    result = {}
    for row in rows:
        point = city_point(row.miasto_id)
        if point is None:
            continue
        result[row.miasto_id] = {'id': row.miasto_id, 'name': row.miasto_nazwa, 'countryId': controller_id(session, row.panstwo_id) or row.panstwo_id,
                                 'population': int(row.miasto_populacja or 0), 'regionId': row.region_id, 'point': [float(point[0]), float(point[1])]}
    return result


def neighbors(session, country):
    from game.road_projects import neighboring_countries
    return neighboring_countries(session, country)


def _all_features(session, owners):
    """Regiony obu państw (bez terytoriów zamorskich) z właścicielem — do trasy międzynarodowej i podziału kosztów."""
    from models import Region
    from game.road_geometry import prepare_features
    from game.military_geography import MAP_PATH
    from game import roads as road_source
    rows = session.execute(select(Region.region_id, Region.panstwo_id, Region.terytorium_zamorskie)).all()
    mapping = {}
    for id, owner, overseas in rows:
        root = controller_id(session, owner)
        if root in owners and not overseas:
            mapping[id] = root
    return prepare_features(road_source.map_features(MAP_PATH), mapping)


def _covered(features, point):
    from game.military_geography import contains_point
    return any(contains_point(f['geometry'], point) for f in features)


def _anchor(features, city, other, km_per_unit):
    """Punkt startu toru: miasto, a gdy leży tuż poza lądem (port) — najbliższy punkt lądu (do 25 km), lekko w głąb lądu."""
    start = city['point']
    if _covered(features, start):
        return start
    from shapely.geometry import Point
    from shapely.ops import nearest_points
    land = _land(features)
    target = nearest_points(land, Point(start))[0]
    gap = hypot(target.x - start[0], target.y - start[1])
    if gap * km_per_unit <= ENDPOINT_SNAP_KM:
        dx, dy = (target.x - start[0]) / (gap or 1), (target.y - start[1]) / (gap or 1)
        for extra_km in (0.05, 0.2, 0.5, 1, 2, 4):
            candidate = [target.x + dx * extra_km / km_per_unit, target.y + dy * extra_km / km_per_unit]
            if _covered(features, candidate):
                return [round(candidate[0], 6), round(candidate[1], 6)]
    raise FinanceError(f'Miasto {city["name"]} nie ma dostępu lądowego do trasy. Wybierz inne miasto.')


def _route(features, a, b, km_per_unit):
    """Trasa po lądzie: najpierw łagodny łuk (jak drogi); gdy przecina wodę (krzywizna wybrzeża, zatoka) — najkrótsza
    droga po lądzie wzdłuż wybrzeża (19 Nov 2026), wyznaczana na siatce i wyprostowana tam, gdzie odcinek leży na lądzie."""
    from game.roads import curved_path
    start, end = _anchor(features, a, b, km_per_unit), _anchor(features, b, a, km_per_unit)
    try:
        path = curved_path(features, start, end)
    except FinanceError:
        path = land_path(features, start, end)
    if path[0] != a['point']:
        path = [a['point']] + path
    if path[-1] != b['point']:
        path = path + [b['point']]
    return path


import threading
_LOCAL = threading.local()   # przygotowane geometrie GEOS nie są współdzielone między wątkami (gunicorn --threads)


def _land(features):
    """Suma wielokątów regionów (shapely), przygotowana do szybkich testów; pamięć podręczna wg zestawu regionów."""
    import shapely
    from shapely.geometry import shape
    from shapely.ops import unary_union
    cache = getattr(_LOCAL, 'land', None)
    if cache is None:
        cache = _LOCAL.land = {}
    key = tuple(sorted((round(f['bounds'][0], 4), round(f['bounds'][1], 4), f['owner']) for f in features))
    land = cache.get(key)
    if land is None:
        land = unary_union([shape(f['geometry']).buffer(0) for f in features])
        shapely.prepare(land)
        if len(cache) > 16:
            cache.clear()
        cache[key] = land
    return land


GRID_CELLS = 220          # komórek siatki wzdłuż dłuższego boku okna wyszukiwania


def land_path(features, start, end):
    import heapq
    import numpy as np
    import shapely
    from shapely.geometry import LineString
    land = _land(features)
    if land.is_empty:
        raise FinanceError('Brak lądowego połączenia między miastami. Wybierz inne miasta.')
    bx0, by0, bx1, by1 = land.bounds
    distance = hypot(end[0] - start[0], end[1] - start[1])
    for spread in (0.6, 1.5, 4.0):
        margin = distance * spread
        x0, y0 = max(bx0, min(start[0], end[0]) - margin), max(by0, min(start[1], end[1]) - margin)
        x1, y1 = min(bx1, max(start[0], end[0]) + margin), min(by1, max(start[1], end[1]) + margin)
        cell = max(x1 - x0, y1 - y0) / GRID_CELLS
        nx, ny = max(2, int((x1 - x0) / cell) + 1), max(2, int((y1 - y0) / cell) + 1)
        xs, ys = x0 + (np.arange(nx) + .5) * cell, y0 + (np.arange(ny) + .5) * cell
        grid_x, grid_y = np.meshgrid(xs, ys)
        mask = shapely.contains_xy(land, grid_x, grid_y)

        def nearest(point):
            j, i = int((point[0] - x0) / cell), int((point[1] - y0) / cell)
            best = None
            for radius in range(0, 6):
                for di in range(-radius, radius + 1):
                    for dj in range(-radius, radius + 1):
                        y, x = i + di, j + dj
                        if 0 <= y < ny and 0 <= x < nx and mask[y, x]:
                            d = (xs[x] - point[0]) ** 2 + (ys[y] - point[1]) ** 2
                            if best is None or d < best[0]:
                                best = (d, (y, x))
                if best:
                    return best[1]
            return None

        source, target = nearest(start), nearest(end)
        if source is None or target is None:
            continue
        steps = [(-1, -1, 1.4142), (-1, 0, 1), (-1, 1, 1.4142), (0, -1, 1), (0, 1, 1), (1, -1, 1.4142), (1, 0, 1), (1, 1, 1.4142)]
        heuristic = lambda node: hypot(node[0] - target[0], node[1] - target[1])
        queue, cost, parent = [(heuristic(source), 0.0, source)], {source: 0.0}, {}
        while queue:
            _, spent, node = heapq.heappop(queue)
            if node == target:
                break
            if spent > cost.get(node, float('inf')):
                continue
            for dy, dx, weight in steps:
                y, x = node[0] + dy, node[1] + dx
                if not (0 <= y < ny and 0 <= x < nx) or not mask[y, x]:
                    continue
                if dy and dx and not (mask[node[0] + dy, node[1]] and mask[node[0], node[1] + dx]):
                    continue                     # bez przeskoku po skosie przez wodę
                value = spent + weight
                if value < cost.get((y, x), float('inf')):
                    cost[(y, x)] = value
                    parent[(y, x)] = node
                    heapq.heappush(queue, (value + heuristic((y, x)), value, (y, x)))
        if target not in cost:
            continue
        cells, node = [target], target
        while node != source:
            node = parent[node]
            cells.append(node)
        points = [list(start)] + [[float(xs[x]), float(ys[y])] for y, x in reversed(cells)] + [list(end)]
        tolerant = land.buffer(cell * .25)
        shapely.prepare(tolerant)
        straight = []
        i = 0
        while i < len(points) - 1:
            chosen = i + 1
            for jump in (len(points) - 1 - i, 256, 128, 64, 32, 16, 8, 4, 2):
                j = i + jump
                if j <= i + 1 or j >= len(points):
                    continue
                if tolerant.covers(LineString([points[i], points[j]])):
                    chosen = j
                    break
            straight.append(points[i])
            i = chosen
        straight.append(points[-1])
        return [[round(p[0], 6), round(p[1], 6)] for p in straight]
    raise FinanceError('Brak lądowego połączenia między miastami (morze lub terytorium państwa trzeciego). Wybierz inne miasta.')


def path_length(path):
    return sum(hypot(q[0] - p[0], q[1] - p[1]) for p, q in zip(path, path[1:]))


# ---------- wycena ----------

def _city_id(value, label):
    from game.military_service import natural
    return natural(value, label, 1)


@precise
def quote(session, country, data, lock=False):
    """Wycena linii z miasta własnego (city_a) do miasta własnego albo bezpośredniego sąsiada (city_b)."""
    require_technology(session, country)
    a_id, b_id = _city_id(data.get('city_a'), 'Miasto początkowe'), _city_id(data.get('city_b'), 'Miasto docelowe')
    if a_id == b_id:
        raise FinanceError('Wybierz dwa różne miasta.')
    near = neighbors(session, country)
    cities = city_rows(session, set(controlled_ids(session, country)) | _all_country_ids(session, near))
    a, b = cities.get(a_id), cities.get(b_id)
    if a is None or a['countryId'] != country:
        raise FinanceError('Linia musi zaczynać się w mieście własnego państwa widocznym na mapie.')
    if b is None:
        raise FinanceError('Miasto docelowe musi leżeć we własnym państwie albo u bezpośredniego sąsiada.')
    partner = None if b['countryId'] == country else b['countryId']
    if partner is not None and partner not in near:
        raise FinanceError('Linia międzynarodowa może prowadzić tylko do bezpośredniego sąsiada.')
    pair = or_((RailLine.city_a_id == a_id) & (RailLine.city_b_id == b_id), (RailLine.city_a_id == b_id) & (RailLine.city_b_id == a_id))
    if session.scalar(select(RailLine.id).where(pair, RailLine.status.in_(OPEN))):
        raise FinanceError('Te miasta są już połączone albo czekają na decyzję o połączeniu.')
    from game.military_flights import calibration
    km_per_unit = calibration(session).km_per_unit
    owners = {country} | ({partner} if partner else set())
    features = _all_features(session, owners)
    path = _route(features, a, b, km_per_unit)
    from game.nuclear import require_clear_path
    require_clear_path(session, path)
    from game.land_war import require_buildable, region_at
    for city in (a, b):
        if city['countryId'] == country:
            require_buildable(session, region_at(city['point'][0], city['point'][1]), country)
    distance = (Decimal(str(path_length(path) * km_per_unit))).quantize(Decimal('.001'), rounding=ROUND_HALF_UP)
    if distance <= 0:
        raise FinanceError('Trasa jest zbyt krótka.')
    total = (distance * PRICE_PER_KM).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
    shares = _shares(path, features, owners, country, distance, total)
    return {'cityA': a_id, 'cityB': b_id, 'cityAName': a['name'], 'cityBName': b['name'], 'countryId': country, 'partnerId': partner,
            'path': path, 'distanceKm': str(distance), 'cost': str(total), 'buildDays': build_days(distance), 'shares': shares,
            'pricePerKm': str(PRICE_PER_KM)}


def _all_country_ids(session, roots):
    """Wszystkie państwa kontrolowane przez podane państwa (aneksje)."""
    result = set()
    for root in roots:
        result |= set(controlled_ids(session, root))
    return result


def partition(path, features):
    """Podział trasy na odcinki według właściciela terenu (jak game.road_geometry.partition_path), ale odcinki poza lądem
    (dojazd do miasta portowego, wyprostowanie przy wybrzeżu) są pomijane zamiast przerywać wycenę — 19 Nov 2026."""
    from game.military_geography import contains_point, polygons
    chunks = []
    for start, end in zip(path, path[1:]):
        dx, dy = end[0] - start[0], end[1] - start[1]
        if hypot(dx, dy) < 1e-12:
            continue
        lowx, highx = sorted([start[0], end[0]]); lowy, highy = sorted([start[1], end[1]])
        nearby = [f for f in features if f['bounds'][0] <= highx + 1e-8 and f['bounds'][2] >= lowx - 1e-8 and f['bounds'][1] <= highy + 1e-8 and f['bounds'][3] >= lowy - 1e-8]
        cuts = {0., 1.}
        for feature in nearby:
            for rings in polygons(feature['geometry']):
                for ring in rings:
                    for a, b in zip(ring, ring[1:]):
                        ex, ey = b[0] - a[0], b[1] - a[1]; den = dx * ey - dy * ex
                        if abs(den) < 1e-12:
                            continue
                        ax, ay = a[0] - start[0], a[1] - start[1]
                        t = (ax * ey - ay * ex) / den; u = (ax * dy - ay * dx) / den
                        if 1e-10 < t < 1 - 1e-10 and -1e-9 <= u <= 1 + 1e-9:
                            cuts.add(t)
        points = sorted(cuts)
        for a, b in zip(points, points[1:]):
            if b - a < 1e-9:
                continue
            middle = [start[0] + dx * (a + b) / 2, start[1] + dy * (a + b) / 2]
            owner = next((f['owner'] for f in nearby if contains_point(f['geometry'], middle)), None)
            if owner is None:
                continue
            left = [start[0] + dx * a, start[1] + dy * a]; right = [start[0] + dx * b, start[1] + dy * b]
            if chunks and chunks[-1]['countryId'] == owner and chunks[-1]['path'][-1] == left:
                chunks[-1]['path'].append(right)
            else:
                chunks.append({'countryId': owner, 'path': [left, right]})
    return chunks


def _shares(path, features, owners, country, distance, total):
    """Koszt dzielony proporcjonalnie do długości trasy po każdej stronie granicy (krótkie odcinki poza lądem — inicjatora)."""
    if len(owners) == 1:
        return {str(country): {'countryId': country, 'distanceKm': str(distance), 'cost': str(total)}}
    parts = partition(path, features)
    raw = {owner: sum(path_length(part['path']) for part in parts if part['countryId'] == owner) for owner in owners}
    length = sum(raw.values()) or 1
    shares = {}
    for owner in sorted(owners):
        fraction = Decimal(str(raw[owner] / length))
        shares[str(owner)] = {'countryId': owner, 'distanceKm': str((distance * fraction).quantize(Decimal('.001'), rounding=ROUND_HALF_UP)),
                              'cost': str((total * fraction).quantize(Decimal('.01'), rounding=ROUND_HALF_UP))}
    partner = next(owner for owner in owners if owner != country)
    if Decimal(shares[str(partner)]['cost']) <= 0:
        raise FinanceError('Trasa nie przebiega przez terytorium sąsiada. Wybierz miasto we własnym państwie.')
    shares[str(country)]['cost'] = str(total - Decimal(shares[str(partner)]['cost']))
    return shares


# ---------- budowa, zgoda sąsiada ----------

def _budget(session, country, amount):
    from game.road_projects import current_budget
    try:
        return current_budget(session, country, amount)
    except FinanceError:
        raise FinanceError('Za mało niewydanych środków w budżecie infrastruktury bieżącego okresu.')


def _notify(session, country, text):
    from game.paga_ai_actor import country_user_id
    from game.forum_models import GameNotification
    owner = country_user_id(session, country)
    if owner is not None:
        session.add(GameNotification(user_id=owner, notification_type='SYSTEM', system_text='Kolej: ' + text, created_at=utc_now()))


def _start(session, line, now):
    for key, share in line.shares.items():
        country, amount = int(key), Decimal(share['cost'])
        budget = _budget(session, country, amount)
        session.add(RailExpense(line_id=line.id, panstwo_id=country, budget_id=budget.id, amount=amount))
    line.status = 'ACTIVE'
    line.starts_at = now
    line.ready_at = now + timedelta(days=line.build_days)


def _lock(session, ids):
    list(session.scalars(select(Panstwo.PANSTWO_ID).where(Panstwo.PANSTWO_ID.in_(sorted(set(ids)))).order_by(Panstwo.PANSTWO_ID).with_for_update()))


@precise
def build(user_id, data):
    """Linia krajowa — budowa rusza od razu; międzynarodowa — wniosek o współfinansowanie do sąsiada."""
    from game.mining_service import request_key
    key = request_key(data.get('request_id'))
    with Session(db.engine) as session, session.begin():
        country = _country_for_user(session, user_id).PANSTWO_ID
        existing = session.scalar(select(RailLine).where(RailLine.initiator_id == country, RailLine.request_id == key))
        if existing:
            return line_data(session, existing, country, {})
        preview = quote(session, country, data)
        _lock(session, [country] + ([preview['partnerId']] if preview['partnerId'] else []))
        current = quote(session, country, data, lock=True)
        if data.get('expected_cost') != current['cost']:
            raise FinanceConflict('Wycena trasy zmieniła się. Sprawdź ją ponownie.')
        partner = current['partnerId']
        if partner is not None:
            from game.paga_ai_actor import country_user_id
            if country_user_id(session, partner) is None:
                raise FinanceError('Sąsiad nie ma gracza, który mógłby zaakceptować współfinansowanie.')
        _budget(session, country, Decimal(current['shares'][str(country)]['cost']))
        line = RailLine(initiator_id=country, partner_id=partner, city_a_id=current['cityA'], city_b_id=current['cityB'], path=current['path'],
                        distance_km=Decimal(current['distanceKm']), cost=Decimal(current['cost']), shares=current['shares'],
                        build_days=current['buildDays'], status='PENDING', user_id=user_id, request_id=key)
        session.add(line)
        session.flush()
        name = session.scalar(select(Panstwo.panstwo_nazwa).where(Panstwo.PANSTWO_ID == country))
        if partner is None:
            _start(session, line, game_now())
        else:
            share = current['shares'][str(partner)]
            _notify(session, partner, f'{name} proponuje wspólną budowę linii {current["cityAName"]} – {current["cityBName"]}. '
                                      f'Twój odcinek: {share["distanceKm"]} km, koszt {share["cost"]} ROI. Zaakceptuj lub odrzuć w zakładce „Komunikacja”.')
        session.flush()
        return line_data(session, line, country, {})


@precise
def decide(user_id, data):
    """accept / reject — sąsiad; cancel — inicjator (tylko wniosek oczekujący)."""
    from game.military_service import natural
    id = natural(data.get('line_id'), 'Linia kolejowa', 1)
    action = data.get('action')
    if action not in ('accept', 'reject', 'cancel'):
        raise FinanceError('Nieprawidłowa decyzja.')
    with Session(db.engine) as session, session.begin():
        own = _country_for_user(session, user_id).PANSTWO_ID
        initial = session.get(RailLine, id)
        if initial is None or own not in (initial.initiator_id, initial.partner_id):
            raise FinanceError('Nie znaleziono linii kolejowej.')
        _lock(session, [initial.initiator_id] + ([initial.partner_id] if initial.partner_id else []))
        line = session.scalar(select(RailLine).where(RailLine.id == id).with_for_update().execution_options(populate_existing=True))
        if own != (line.partner_id if action in ('accept', 'reject') else line.initiator_id):
            raise FinanceError('Ta decyzja należy do drugiej strony.')
        target = {'accept': 'ACTIVE', 'reject': 'REJECTED', 'cancel': 'CANCELLED'}[action]
        if line.status == target:
            return line.id
        if line.status != 'PENDING':
            raise FinanceConflict('Stan linii zmienił się. Odśwież listę.')
        names = dict(session.execute(select(Miasto.miasto_id, Miasto.miasto_nazwa).where(Miasto.miasto_id.in_([line.city_a_id, line.city_b_id]))).all())
        label = f'{names.get(line.city_a_id, "")} – {names.get(line.city_b_id, "")}'
        if action in ('reject', 'cancel'):
            line.status = target
            line.resolved_at = utc_now()
            _notify(session, line.initiator_id if action == 'reject' else line.partner_id,
                    f'Linia {label}: ' + ('sąsiad odrzucił współfinansowanie.' if action == 'reject' else 'wniosek o współfinansowanie wycofano.'))
            return line.id
        current = _requote(session, line)
        if current['shares'] != line.shares or Decimal(current['cost']) != line.cost:
            raise FinanceConflict('Granice lub koszt trasy zmieniły się. Inicjator musi złożyć nowy wniosek.')
        _start(session, line, game_now())
        line.resolved_at = utc_now()
        for country in (line.initiator_id, line.partner_id):
            _notify(session, country, f'Linia {label}: współfinansowanie zaakceptowane, budowa trwa {line.build_days} dni Entendy.')
        return line.id


def _requote(session, line):
    """Ponowna wycena wniosku (pomija blokadę „para już ma otwartą linię” — dotyczy samego wniosku)."""
    line_status, line.status = line.status, 'CANCELLED'
    session.flush()
    try:
        return quote(session, line.initiator_id, {'city_a': line.city_a_id, 'city_b': line.city_b_id})
    finally:
        line.status = line_status
        session.flush()


# ---------- bonus budżetowy ----------

def main_network(edges, population):
    """20 Nov 2026: największa spójna sieć kolejowa. edges — pary (miasto, miasto) ukończonych linii; population — ludność
    miast liczonych do bonusu (miasta spoza słownika, np. sąsiadów, są tylko węzłami przesiadkowymi). Zwraca
    (zbiór miast sieci, ludność sieci); przy remisie wygrywa sieć z najmniejszym identyfikatorem miasta."""
    parent = {}

    def root(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        ra, rb = root(a), root(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    groups = {}
    for city in list(parent):
        groups.setdefault(root(city), set()).add(city)
    best, best_key = set(), None
    for members in groups.values():
        total = sum(int(population.get(city) or 0) for city in members)
        key = (total, -min(members))
        if total > 0 and (best_key is None or key > best_key):
            best, best_key = members, key
    return best, (best_key[0] if best_key else 0)


def completed_edges(session, now=None):
    now = now or game_now()
    return session.execute(select(RailLine.city_a_id, RailLine.city_b_id).where(RailLine.status == 'ACTIVE', RailLine.ready_at <= now)).all()


def network(session, country, now=None):
    """Miasta i ludność największej spójnej sieci kolejowej państwa (ukończone linie)."""
    from sqlalchemy import inspect
    if not inspect(session.connection()).has_table(RailLine.__tablename__):
        return set(), 0
    edges = completed_edges(session, now)
    ids = {city for edge in edges for city in edge}
    if not ids:
        return set(), 0
    population = dict(session.execute(select(Miasto.miasto_id, func.coalesce(Miasto.miasto_populacja, 0)).where(
        Miasto.miasto_id.in_(ids), Miasto.panstwo_id.in_(list(controlled_ids(session, country))))).all())
    members, total = main_network(edges, population)
    return {city for city in members if city in population}, int(total)


def connected_population(session, country, now=None):
    """Ludność własnych miast w największej spójnej sieci kolejowej (każde miasto raz) — 20 Nov 2026."""
    return network(session, country, now)[1]


def rail_infrastructure(session, country):
    """Średnia infrastruktura kolejowa regionów państwa (0–100); brak danych — 0."""
    from models import Region
    value = session.scalar(select(func.avg(Region.region_stan_infra_kolejowej)).where(
        Region.panstwo_id.in_(list(controlled_ids(session, country)) or [country]), Region.region_stan_infra_kolejowej.is_not(None)))
    return Decimal(str(round(float(value), 2))) if value is not None else Decimal('0')


def bonus(gdp, population, connected, infrastructure=100):
    """PKB per capita × 0,01 × ludność spójnej sieci kolejowej × (średnia infrastruktura kolejowa / 100) — 19 Nov 2026."""
    if not gdp or not population or not connected or not infrastructure:
        return Decimal('0.00')
    factor = max(Decimal('0'), min(Decimal('100'), Decimal(str(infrastructure)))) / 100
    return (Decimal(gdp) / Decimal(population) * BONUS_RATE * Decimal(connected) * factor).quantize(Decimal('.01'))


# ---------- stan ekranu ----------

def line_data(session, line, country, names):
    if not names:
        names = dict(session.execute(select(Miasto.miasto_id, Miasto.miasto_nazwa).where(Miasto.miasto_id.in_([line.city_a_id, line.city_b_id]))).all())
    countries = dict(session.execute(select(Panstwo.PANSTWO_ID, Panstwo.panstwo_nazwa).where(
        Panstwo.PANSTWO_ID.in_([line.initiator_id] + ([line.partner_id] if line.partner_id else [])))).all())
    now = game_now()
    done = line.status == 'ACTIVE' and line.ready_at is not None and line.ready_at <= now
    progress = 100 if done else 0
    if line.status == 'ACTIVE' and not done and line.starts_at and line.ready_at:
        progress = max(0, min(99, int((now - line.starts_at).total_seconds() / max(1, (line.ready_at - line.starts_at).total_seconds()) * 100)))
    return {'id': line.id, 'cityA': line.city_a_id, 'cityB': line.city_b_id, 'cityAName': names.get(line.city_a_id, ''), 'cityBName': names.get(line.city_b_id, ''),
            'initiatorId': line.initiator_id, 'partnerId': line.partner_id, 'initiator': countries.get(line.initiator_id, ''), 'partner': countries.get(line.partner_id, ''),
            'path': line.path, 'distanceKm': str(line.distance_km), 'cost': str(line.cost), 'shares': line.shares, 'buildDays': line.build_days,
            'status': line.status, 'completed': done, 'progress': progress,
            'startsAt': line.starts_at.isoformat() + 'Z' if line.starts_at else None, 'readyAt': line.ready_at.isoformat() + 'Z' if line.ready_at else None,
            'own': line.initiator_id == country, 'awaitingMe': line.status == 'PENDING' and line.partner_id == country}


def state(session, country):
    from game.governance import economy
    from game.budget_transfers import infrastructure_balance
    from game.finance_models import StateBudget
    from game.finance_service import period_key
    now = game_now()
    available = has_technology(session, country)
    near = neighbors(session, country)
    own_ids = set(controlled_ids(session, country))
    cities = city_rows(session, own_ids | _all_country_ids(session, near))
    lines = list(session.scalars(select(RailLine).where(or_(RailLine.initiator_id == country, RailLine.partner_id == country),
                                                       RailLine.status.in_(['PENDING', 'ACTIVE', 'REJECTED'])).order_by(RailLine.id.desc()).limit(300)))
    names = {id: city['name'] for id, city in cities.items()}
    missing = {id for line in lines for id in (line.city_a_id, line.city_b_id) if id not in names}
    if missing:
        names.update(dict(session.execute(select(Miasto.miasto_id, Miasto.miasto_nazwa).where(Miasto.miasto_id.in_(missing))).all()))
    data = economy(session, country)
    network_cities, connected = network(session, country, now)
    infrastructure = rail_infrastructure(session, country)
    year, period = period_key(now)
    budget = session.scalar(select(StateBudget).where(StateBudget.panstwo_id == country, StateBudget.game_year == year, StateBudget.period == period))
    funds = str(infrastructure_balance(session, budget)[1]) if budget else '0'
    countries = dict(session.execute(select(Panstwo.PANSTWO_ID, Panstwo.panstwo_nazwa).where(Panstwo.PANSTWO_ID.in_(list(near | {country})))).all())
    return {'available': available, 'countryId': country, 'pricePerKm': str(PRICE_PER_KM), 'kmPerDay': KM_PER_DAY,
            'cities': [{**city, 'own': city['countryId'] == country} for city in cities.values()],
            'countries': {str(k): v for k, v in countries.items()}, 'neighbors': sorted(near),
            'lines': [line_data(session, line, country, names) for line in lines],
            'connectedPopulation': connected, 'networkCities': sorted(network_cities), 'railInfrastructure': str(infrastructure),
            'bonus': str(bonus(data['gdp'], data['population'], connected, infrastructure)),
            'gdpPerCapita': str((Decimal(data['gdp']) / Decimal(data['population'])).quantize(Decimal('.01'))) if data['gdp'] and data['population'] else None,
            'funds': funds, 'gameNow': now.isoformat() + 'Z', 'kmPerUnit': _km_per_unit(session),
            'timeMultiplier': _multiplier(), 'trainSpeed': TRAIN_SPEED,
            'incomingRequests': sum(1 for line in lines if line.status == 'PENDING' and line.partner_id == country)}


def _multiplier():
    from engine.clock import get_time_multiplier
    return get_time_multiplier()


def pending_requests(session, country):
    """Wnioski sąsiadów o współfinansowanie czekające na decyzję tego państwa (zakładka widoczna także bez technologii)."""
    from sqlalchemy import inspect
    if not inspect(session.connection()).has_table(RailLine.__tablename__):
        return 0
    return session.scalar(select(func.count()).select_from(RailLine).where(RailLine.partner_id == country, RailLine.status == 'PENDING')) or 0


def world_lines(session):
    """Linie kolejowe wszystkich państw (budowane i ukończone) — mapa świata, 19 Nov 2026."""
    from sqlalchemy import inspect
    if not inspect(session.connection()).has_table(RailLine.__tablename__):
        return []
    rows = list(session.scalars(select(RailLine).where(RailLine.status == 'ACTIVE').order_by(RailLine.id)))
    ids = {i for row in rows for i in (row.city_a_id, row.city_b_id)}
    names = dict(session.execute(select(Miasto.miasto_id, Miasto.miasto_nazwa).where(Miasto.miasto_id.in_(ids or {0}))).all())
    countries = dict(session.execute(select(Panstwo.PANSTWO_ID, Panstwo.panstwo_nazwa)).all())
    now = game_now()
    result = []
    for row in rows:
        done = row.ready_at is not None and row.ready_at <= now
        progress = 100 if done else max(0, min(99, int((now - row.starts_at).total_seconds() / max(1, (row.ready_at - row.starts_at).total_seconds()) * 100))) if row.starts_at and row.ready_at else 0
        result.append({'id': row.id, 'cityAName': names.get(row.city_a_id, ''), 'cityBName': names.get(row.city_b_id, ''), 'path': row.path,
                       'distanceKm': str(row.distance_km), 'completed': done, 'progress': progress, 'status': row.status,
                       'readyAt': row.ready_at.isoformat() + 'Z' if row.ready_at else None,
                       'countries': [countries.get(row.initiator_id, '')] + ([countries.get(row.partner_id, '')] if row.partner_id else [])})
    return result


def wiki_network(session, country):
    """20 Nov 2026: sieć kolejowa państwa na jego stronie w WIKI (/panstwo/<id>) — linie ukończone i w budowie, w których
    państwo uczestniczy (własne i współfinansowane), miasta, największa spójna sieć liczona do dochodów z kolei.
    None, gdy w bazie nie ma tabel kolei albo państwo nie ma żadnej linii."""
    from sqlalchemy import inspect
    if not inspect(session.connection()).has_table(RailLine.__tablename__):
        return None
    own_ids = set(controlled_ids(session, country)) or {country}
    own_city_ids = set(session.scalars(select(Miasto.miasto_id).where(Miasto.panstwo_id.in_(list(own_ids)))))
    rows = [row for row in session.scalars(select(RailLine).where(RailLine.status == 'ACTIVE').order_by(RailLine.id))
            if row.initiator_id in own_ids or row.partner_id in own_ids or {row.city_a_id, row.city_b_id} & own_city_ids]
    if not rows:
        return None
    endpoint_ids = {i for row in rows for i in (row.city_a_id, row.city_b_id)}
    foreign = set(session.scalars(select(Miasto.panstwo_id).where(Miasto.miasto_id.in_(endpoint_ids), Miasto.panstwo_id.is_not(None))))
    cities = city_rows(session, own_ids | foreign)
    cities = {id: city for id, city in cities.items() if city['countryId'] == country or id in endpoint_ids}
    names = {id: city['name'] for id, city in cities.items()}
    missing = endpoint_ids - set(names)
    if missing:
        names.update(dict(session.execute(select(Miasto.miasto_id, Miasto.miasto_nazwa).where(Miasto.miasto_id.in_(missing))).all()))
    now = game_now()
    members, population = network(session, country, now)
    lines = [line_data(session, row, country, names) for row in rows]
    done = [line for line in lines if line['completed']]
    countries = dict(session.execute(select(Panstwo.PANSTWO_ID, Panstwo.panstwo_nazwa).where(
        Panstwo.PANSTWO_ID.in_(list({c['countryId'] for c in cities.values()} | {country})))).all())
    return {'countryId': country, 'gameNow': now.isoformat() + 'Z', 'timeMultiplier': _multiplier(), 'trainSpeed': TRAIN_SPEED,
            'cities': [{**city, 'own': city['countryId'] == country, 'inNetwork': id in members} for id, city in cities.items()],
            'countries': {str(k): v for k, v in countries.items()},
            'lines': [{key: line[key] for key in ('id', 'cityAName', 'cityBName', 'initiator', 'partner', 'path', 'distanceKm',
                                                   'status', 'completed', 'progress', 'readyAt')} for line in lines],
            'summary': {'lines': len(lines), 'completed': len(done), 'building': len(lines) - len(done),
                        'completedKm': round(sum(float(line['distanceKm']) for line in done)),
                        'buildingKm': round(sum(float(line['distanceKm']) for line in lines if not line['completed'])),
                        'international': sum(1 for row in rows if row.partner_id),
                        'networkCities': sum(1 for id in members if id in own_city_ids), 'networkPopulation': population,
                        'railInfrastructure': str(rail_infrastructure(session, country))}}


def _km_per_unit(session):
    from game.military_flights import calibration
    return calibration(session).km_per_unit


# ---------- trasy HTTP ----------

def _player():
    from game.forum import player
    from game.military import csrf_valid
    user, country = player()
    if user is None:
        return None, None, (jsonify(error='Zaloguj się ponownie.'), 401)
    if request.method == 'POST' and not csrf_valid():
        return None, None, (jsonify(error='Sesja formularza wygasła. Odśwież stronę.'), 403)
    return user, country, None


@rail_bp.get('/stan')
def state_view():
    user, country, error = _player()
    if error:
        return error
    with Session(db.engine) as session:
        return jsonify(state(session, country.PANSTWO_ID))


@rail_bp.post('/wycena')
def quote_view():
    user, country, error = _player()
    if error:
        return error
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error='Nieprawidłowe dane.'), 400
    try:
        with Session(db.engine) as session:
            return jsonify(quote(session, country.PANSTWO_ID, data))
    except FinanceError as exc:
        return jsonify(error=str(exc)), 400


@rail_bp.post('/zmien')
def change_view():
    user, country, error = _player()
    if error:
        return error
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error='Nieprawidłowe dane.'), 400
    try:
        if data.get('action') == 'build':
            return jsonify(ok=True, line=build(user.id, data))
        return jsonify(ok=True, id=decide(user.id, data))
    except FinanceConflict as exc:
        return jsonify(error=str(exc)), 409
    except FinanceError as exc:
        return jsonify(error=str(exc)), 400
