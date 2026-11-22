"""Transport lotniczy (administrator, 20 Nov 2026).

- technologia „Transport lotniczy” (400 pkt, 28 dni Entendy; po „Transporcie kolejowym”) pozwala graczom i państwom PAGA2
  budować porty lotnicze z ekranu „Infrastruktura i energetyka” (kliknięcie miasta → „Zbuduj port lotniczy”);
- lotnisko można zbudować w mieście państwa powyżej 100 000 mieszkańców; państwo bez takich miast — tylko w swoim
  największym mieście; jedno lotnisko na miasto;
- koszt: 1400 kamienia, 200 żelaza, 5 prostych chipów (z magazynu; do 22 Nov 2026: 5 kerbitowych i 3 natsytowe) oraz ludność miasta × 100 ROI
  (z budżetu infrastruktury bieżącego okresu); budowa trwa 14 dni Entendy;
- nazwa: najwyżej 60 znaków; domyślnie (i zawsze dla PAGA2) „Port lotniczy {miasto} – {kod miasta}”;
- połączenia lotnicze tworzą się automatycznie między wszystkimi czynnymi lotniskami świata; właściciel lotniska może
  czasowo zawiesić połączenie z wybranym lotniskiem (odwracalne) — połączenie nie działa, gdy zawiesi je którakolwiek strona;
- bonus budżetowy (game.finance_service.calculate_budget, w każdym cyklu): dla każdego czynnego połączenia, w którym
  uczestniczy lotnisko państwa, (ludność miasta A + ludność miasta B) × 10 ROI; połączenia lotnisk innych państw nie
  zwiększają budżetu państwa (każde połączenie liczone raz, także gdy oba lotniska należą do państwa);
- handel: oferta „drogą lotniczą” wysyłana z lotniska sprzedającego do lotniska kupującego (samolot 1000 km/h, bez opłat);
- nazwę lotniska właściciel może zmienić najwyżej raz na rok Entendy (rok od poprzedniej zmiany; nadanie przy budowie
  się nie liczy) — przycisk „Zmień nazwę” w tooltipie lotniska;
- obrona i wojna: lotnisko można chronić obroną przeciwrakietową; państwa w stanie wojny widzą i atakują lotniska
  przeciwnika bez rozpoznania wywiadu; lotnisko z życiem 0 jest zniszczone (nowe można zbudować w tym samym mieście).
"""
from datetime import timedelta
from decimal import Decimal
from flask import Blueprint, jsonify, request
from sqlalchemy import select, func, or_, delete, update
from sqlalchemy.orm import Session
from extensions import db
from models import Miasto, Panstwo
from game.models import utc_now
from game.finance_service import FinanceError, FinanceConflict, _country_for_user, game_now
from game.budget_transfers import precise
from game.governance import controller_id, controlled_ids
from game.airport_models import Airport, AirportExpense, AirRouteSuspension

airports_bp = Blueprint('game_airports', __name__, url_prefix='/game/lotniska')

TECHNOLOGY = 'air_transport'
MIN_POPULATION = 100_000          # lotnisko w mieście powyżej 100 000 mieszkańców
BUILD_DAYS = 14
PRICE_PER_RESIDENT = Decimal('100')
INCOME_PER_RESIDENT = Decimal('10')
MATERIALS = {'kamien': 1400, 'zelazo': 200, 'chip_simple': 5}   # 22 Nov 2026: zamiast 5 chipów kerbitowych i 3 natsytowych
MATERIAL_LABELS = {'kamien': 'Kamień', 'zelazo': 'Żelazo', 'chip_simple': 'Prosty chip', 'chip_kerbit': 'Chip kerbitowy', 'chip_natsyt': 'Chip natsytowy'}
MATERIAL_ICONS = {'kamien': 'KAMIEŃ.svg', 'zelazo': 'ŻELAZO.svg', 'chip_simple': 'CHIP PROSTY.svg', 'chip_kerbit': 'CHIP KERBITOWY.svg', 'chip_natsyt': 'CHIP NATSYTOWY.svg'}
NAME_MAX = 60
AIR_SPEED = 1000                  # km/h czasu gry — samoloty towarowe (handel) i samoloty na mapie świata


def has_technology(session, country):
    from game.industry_service import researched
    return researched(session, country, TECHNOLOGY)


def require_technology(session, country):
    if not has_technology(session, country):
        raise FinanceError('Najpierw opracuj technologię „Transport lotniczy”.')


def _tables_ready(session):
    from sqlalchemy import inspect
    return inspect(session.connection()).has_table(Airport.__tablename__)


def default_name(name, code):
    base = f'Port lotniczy {name or ""}'.strip()
    return (f'{base} – {code}' if code else base)[:NAME_MAX]


def _now_or(now):
    return now or game_now()


def operational(airport, now):
    return airport.removed_at is None and (airport.health or 0) > 0 and airport.ready_at <= now


# ---------- miasta ----------

def own_cities(session, country):
    """Miasta państwa (także kontrolowanych terytoriów) widoczne na mapie, z położeniem."""
    from game.military_geography import city_point
    rows = session.execute(select(Miasto.miasto_id, Miasto.miasto_nazwa, Miasto.miasto_kod, Miasto.miasto_populacja, Miasto.region_id)
                           .where(Miasto.panstwo_id.in_(list(controlled_ids(session, country)) or [country]), Miasto.czy_na_mapie == 'TAK')).all()
    result = []
    for row in rows:
        point = city_point(row.miasto_id)
        if point is None:
            continue
        result.append({'id': row.miasto_id, 'name': row.miasto_nazwa, 'code': row.miasto_kod, 'population': int(row.miasto_populacja or 0),
                       'regionId': row.region_id, 'point': [float(point[0]), float(point[1])]})
    return result


def eligible_ids(cities):
    """Miasta powyżej 100 000 mieszkańców; bez takich — tylko największe miasto państwa."""
    large = {c['id'] for c in cities if c['population'] > MIN_POPULATION}
    if large or not cities:
        return large
    return {max(cities, key=lambda c: (c['population'], -c['id']))['id']}


def _active_airport_in_city(session, city_id):
    return session.scalar(select(Airport).where(Airport.miasto_id == city_id, Airport.removed_at.is_(None)))


# ---------- wycena i budowa ----------

def materials_status(session, country):
    from game.industry_service import available
    return [{'code': code, 'label': MATERIAL_LABELS[code], 'need': need, 'have': available(session, country, code), 'icon': MATERIAL_ICONS[code]}
            for code, need in MATERIALS.items()]


def _city_id(value):
    from game.military_service import natural
    return natural(value, 'Miasto', 1)


def quote(session, country, data):
    require_technology(session, country)
    city_id = _city_id(data.get('city_id'))
    cities = own_cities(session, country)
    city = next((c for c in cities if c['id'] == city_id), None)
    if city is None:
        raise FinanceError('Lotnisko można zbudować tylko w mieście własnego państwa widocznym na mapie.')
    if city_id not in eligible_ids(cities):
        raise FinanceError(f'Port lotniczy można zbudować tylko w mieście powyżej {MIN_POPULATION:,} mieszkańców'.replace(',', ' ')
                           + ' (państwo bez takich miast — w swoim największym mieście).')
    if _active_airport_in_city(session, city_id) is not None:
        raise FinanceError(f'Miasto {city["name"]} ma już port lotniczy.')
    from game.land_war import require_buildable
    require_buildable(session, city['regionId'], country)
    from game.nuclear import require_clear
    require_clear(session, city['point'][0], city['point'][1])
    cost = (Decimal(city['population']) * PRICE_PER_RESIDENT).quantize(Decimal('.01'))
    return {'cityId': city_id, 'cityName': city['name'], 'cityCode': city['code'], 'population': city['population'], 'regionId': city['regionId'],
            'point': city['point'], 'cost': str(cost), 'buildDays': BUILD_DAYS, 'materials': materials_status(session, country),
            'defaultName': default_name(city['name'], city['code'])}


def _clean_name(value, fallback):
    if value is None or (isinstance(value, str) and not value.strip()):
        return fallback
    if not isinstance(value, str):
        raise FinanceError('Nieprawidłowa nazwa portu lotniczego.')
    name = ' '.join(value.split())
    if len(name) > NAME_MAX:
        raise FinanceError(f'Nazwa portu lotniczego może mieć najwyżej {NAME_MAX} znaków.')
    return name


def _budget(session, country, amount):
    from game.road_projects import current_budget
    try:
        return current_budget(session, country, amount)
    except FinanceError:
        raise FinanceError('Za mało niewydanych środków w budżecie infrastruktury bieżącego okresu.')


@precise
def build(user_id, data):
    """Budowa lotniska: surowce z magazynu, koszt pieniężny z budżetu infrastruktury, 14 dni Entendy."""
    from game.mining_service import request_key
    key = request_key(data.get('request_id'))
    with Session(db.engine) as session, session.begin():
        country = _country_for_user(session, user_id, lock=True).PANSTWO_ID
        existing = session.scalar(select(Airport).where(Airport.panstwo_id == country, Airport.request_id == key))
        if existing:
            return airport_data(session, existing, country)
        current = quote(session, country, data)
        if data.get('expected_cost') is not None and str(data.get('expected_cost')) != current['cost']:
            raise FinanceConflict('Koszt budowy lotniska zmienił się. Sprawdź wycenę ponownie.')
        name = _clean_name(data.get('name'), current['defaultName'])   # PAGA2 nie podaje nazwy — nazwa domyślna
        from game.industry_service import settle_industry, available, consume
        now = game_now()
        settle_industry(session, country, now)
        missing = [f'{MATERIAL_LABELS[code]} (potrzeba {need}, w magazynie {available(session, country, code)})'
                   for code, need in MATERIALS.items() if available(session, country, code) < need]
        if missing:
            raise FinanceError('Za mało surowców w magazynie: ' + ', '.join(missing) + '.')
        cost = Decimal(current['cost'])
        budget = _budget(session, country, cost)
        consume(session, country, MATERIALS)
        airport = Airport(panstwo_id=country, miasto_id=current['cityId'], region_id=current['regionId'], name=name,
                          map_x=current['point'][0], map_y=current['point'][1], cost=cost, materials=dict(MATERIALS), health=100,
                          starts_at=now, ready_at=now + timedelta(days=BUILD_DAYS), user_id=user_id, request_id=key)
        session.add(airport)
        session.flush()
        session.add(AirportExpense(airport_id=airport.id, panstwo_id=country, budget_id=budget.id, amount=cost))
        session.flush()
        return airport_data(session, airport, country)


def rename_available_at(airport):
    """Najwcześniejszy czas gry kolejnej zmiany nazwy: rok Entendy po poprzedniej zmianie (None — można od razu)."""
    last = airport.renamed_at
    if last is None:
        return None
    try:
        return last.replace(year=last.year + 1)
    except ValueError:                       # 29 lutego → 28 lutego następnego roku
        return last.replace(year=last.year + 1, day=28)


@precise
def rename(user_id, data):
    """Zmiana nazwy własnego lotniska — najwyżej raz na rok Entendy."""
    from game.military_service import natural
    airport_id = natural(data.get('airport_id'), 'Lotnisko', 1)
    with Session(db.engine) as session, session.begin():
        country = _country_for_user(session, user_id, lock=True).PANSTWO_ID
        airport = session.scalar(select(Airport).where(Airport.id == airport_id).with_for_update())
        if airport is None or airport.removed_at is not None or controller_id(session, airport.panstwo_id) != country:
            raise FinanceError('Lotnisko nie należy do państwa gracza.')
        name = _clean_name(data.get('name'), '')
        if not name:
            raise FinanceError('Podaj nową nazwę portu lotniczego.')
        if name == airport.name:
            raise FinanceError('Nowa nazwa jest taka sama jak obecna.')
        now = game_now()
        available = rename_available_at(airport)
        if available is not None and now < available:
            raise FinanceError(f'Nazwę lotniska można zmienić raz na rok Entendy. Następna zmiana: {available.strftime("%d.%m.%Y")} (Entenda).')
        airport.name, airport.renamed_at = name, now
        session.flush()
        return airport_data(session, airport, country, now)


@precise
def set_suspension(user_id, data):
    """suspend / resume — zawieszenie połączenia własnego lotniska z innym lotniskiem (odwracalne)."""
    from game.military_service import natural
    action = data.get('action')
    if action not in ('suspend', 'resume'):
        raise FinanceError('Nieprawidłowa operacja.')
    airport_id, other_id = natural(data.get('airport_id'), 'Lotnisko', 1), natural(data.get('other_id'), 'Lotnisko docelowe', 1)
    if airport_id == other_id:
        raise FinanceError('Wybierz inne lotnisko.')
    with Session(db.engine) as session, session.begin():
        country = _country_for_user(session, user_id, lock=True).PANSTWO_ID
        airport = session.get(Airport, airport_id)
        if airport is None or airport.removed_at is not None or controller_id(session, airport.panstwo_id) != country:
            raise FinanceError('Lotnisko nie należy do państwa gracza.')
        other = session.get(Airport, other_id)
        if other is None or other.removed_at is not None:
            raise FinanceError('Nie znaleziono lotniska docelowego.')
        row = session.get(AirRouteSuspension, (airport_id, other_id))
        if action == 'suspend' and row is None:
            session.add(AirRouteSuspension(airport_id=airport_id, other_id=other_id, created_at=utc_now()))
        elif action == 'resume' and row is not None:
            session.delete(row)
        return {'airportId': airport_id, 'otherId': other_id, 'suspended': action == 'suspend'}


# ---------- połączenia i dochody ----------

def active_airports(session, now=None):
    if not _tables_ready(session):
        return []
    now = _now_or(now)
    return list(session.scalars(select(Airport).where(Airport.removed_at.is_(None), Airport.health > 0, Airport.ready_at <= now).order_by(Airport.id)))


def suspended_pairs(session):
    return {frozenset(pair) for pair in session.execute(select(AirRouteSuspension.airport_id, AirRouteSuspension.other_id)).all()}


def connections(session, now=None, airports=None):
    """Czynne połączenia (pary lotnisk) — wszystkie pary czynnych lotnisk bez zawieszonych."""
    airports = active_airports(session, now) if airports is None else airports
    if len(airports) < 2:
        return []
    blocked = suspended_pairs(session)
    return [(a, b) for i, a in enumerate(airports) for b in airports[i + 1:] if frozenset((a.id, b.id)) not in blocked]


def _populations(session, city_ids):
    if not city_ids:
        return {}
    return {id: int(value or 0) for id, value in session.execute(select(Miasto.miasto_id, Miasto.miasto_populacja).where(Miasto.miasto_id.in_(list(city_ids))))}


def route_bonus(population_a, population_b):
    """(ludność A + ludność B) × 10 ROI za jedno czynne połączenie."""
    return (Decimal(int(population_a or 0) + int(population_b or 0)) * INCOME_PER_RESIDENT).quantize(Decimal('.01'))


def income(session, country, now=None):
    """Dochody z połączeń lotniczych państwa na cykl budżetowy (połączenia, w których uczestniczy jego lotnisko)."""
    if not _tables_ready(session):
        return Decimal('0.00')
    pairs = connections(session, now)
    if not pairs:
        return Decimal('0.00')
    own = set(controlled_ids(session, country)) or {country}
    population = _populations(session, {a.miasto_id for pair in pairs for a in pair})
    total = Decimal('0.00')
    for a, b in pairs:
        if a.panstwo_id in own or b.panstwo_id in own:
            total += route_bonus(population.get(a.miasto_id), population.get(b.miasto_id))
    return total


# ---------- dane ekranów ----------

def _names(session, city_ids=(), country_ids=()):
    cities = dict(session.execute(select(Miasto.miasto_id, Miasto.miasto_nazwa).where(Miasto.miasto_id.in_(list(city_ids) or [0]))).all())
    countries = dict(session.execute(select(Panstwo.PANSTWO_ID, Panstwo.panstwo_nazwa).where(Panstwo.PANSTWO_ID.in_(list(country_ids) or [0]))).all())
    return cities, countries


def airport_data(session, airport, country=None, now=None, names=None):
    now = _now_or(now)
    cities, countries = names or _names(session, [airport.miasto_id], [airport.panstwo_id])
    done = airport.ready_at <= now
    span = max(1, (airport.ready_at - airport.starts_at).total_seconds())
    progress = 100 if done else max(0, min(99, int((now - airport.starts_at).total_seconds() / span * 100)))
    stamp = lambda value: value.isoformat() + 'Z' if value else None
    return {'id': airport.id, 'countryId': airport.panstwo_id, 'country': countries.get(airport.panstwo_id, ''), 'regionId': str(airport.region_id),
            'cityId': airport.miasto_id, 'cityName': cities.get(airport.miasto_id, ''), 'name': airport.name,
            'position': [airport.map_x, airport.map_y], 'health': airport.health, 'completed': done, 'progress': progress,
            'operational': operational(airport, now), 'startsAt': stamp(airport.starts_at), 'readyAt': stamp(airport.ready_at),
            'renamedAt': stamp(airport.renamed_at), 'renameAvailableAt': stamp(rename_available_at(airport)),
            'canRename': airport.removed_at is None and (rename_available_at(airport) is None or rename_available_at(airport) <= now),
            'own': country is not None and controller_id(session, airport.panstwo_id) == country}


def airport_routes(session, airport, now=None, airports=None):
    """Lista połączeń lotniska z pozostałymi czynnymi lotniskami (okno „Zarządzaj”)."""
    now = _now_or(now)
    airports = active_airports(session, now) if airports is None else airports
    rows = {pair for pair in session.execute(select(AirRouteSuspension.airport_id, AirRouteSuspension.other_id)).all()}
    others = [a for a in airports if a.id != airport.id]
    population = _populations(session, {a.miasto_id for a in others} | {airport.miasto_id})
    cities, countries = _names(session, {a.miasto_id for a in others}, {a.panstwo_id for a in others})
    from game.military_flights import calibration
    from math import hypot
    km = calibration(session).km_per_unit
    working = operational(airport, now)
    result = []
    for other in others:
        by_me, by_other = (airport.id, other.id) in rows, (other.id, airport.id) in rows
        result.append({'otherId': other.id, 'name': other.name, 'cityName': cities.get(other.miasto_id, ''), 'country': countries.get(other.panstwo_id, ''),
                       'countryId': other.panstwo_id, 'distanceKm': round(hypot(other.map_x - airport.map_x, other.map_y - airport.map_y) * km),
                       'suspendedByMe': by_me, 'suspendedByOther': by_other, 'active': working and not by_me and not by_other,
                       'bonus': str(route_bonus(population.get(airport.miasto_id), population.get(other.miasto_id)))})
    return sorted(result, key=lambda r: (not r['active'], r['distanceKm']))


def state(session, country):
    from game.budget_transfers import infrastructure_balance
    from game.finance_models import StateBudget
    from game.finance_service import period_key
    now = game_now()
    available = has_technology(session, country)
    ready = _tables_ready(session)
    cities = own_cities(session, country)
    eligible = eligible_ids(cities)
    own_ids = set(controlled_ids(session, country)) or {country}
    rows = list(session.scalars(select(Airport).where(Airport.panstwo_id.in_(list(own_ids)), Airport.removed_at.is_(None)).order_by(Airport.id))) if ready else []
    working = active_airports(session, now) if ready else []
    taken = {a.miasto_id for a in session.scalars(select(Airport).where(Airport.removed_at.is_(None)))} if ready else set()
    names = _names(session, {a.miasto_id for a in rows}, {a.panstwo_id for a in rows})
    own = []
    for airport in rows:
        item = airport_data(session, airport, country, now, names)
        if item['operational']:
            item['routes'] = airport_routes(session, airport, now, working)
        own.append(item)
    year, period = period_key(now)
    budget = session.scalar(select(StateBudget).where(StateBudget.panstwo_id == country, StateBudget.game_year == year, StateBudget.period == period))
    funds = str(infrastructure_balance(session, budget)[1]) if budget else '0'
    return {'available': available, 'countryId': country, 'minPopulation': MIN_POPULATION, 'buildDays': BUILD_DAYS,
            'pricePerResident': str(PRICE_PER_RESIDENT), 'incomePerResident': str(INCOME_PER_RESIDENT), 'nameMax': NAME_MAX,
            'materials': materials_status(session, country), 'funds': funds, 'gameNow': now.isoformat() + 'Z',
            'cities': [{'id': c['id'], 'name': c['name'], 'population': c['population'], 'regionId': str(c['regionId']), 'point': c['point'],
                        'eligible': c['id'] in eligible, 'hasAirport': c['id'] in taken,
                        'cost': str((Decimal(c['population']) * PRICE_PER_RESIDENT).quantize(Decimal('.01'))),
                        'defaultName': default_name(c['name'], c['code'])} for c in cities],
            'airports': own, 'worldAirports': len(working), 'income': str(income(session, country, now)) if ready else '0.00'}


def own_operational(session, country, now=None):
    """Czynne lotniska państwa — porty handlu lotniczego."""
    if not _tables_ready(session):
        return []
    own = set(controlled_ids(session, country)) or {country}
    return [a for a in active_airports(session, now) if a.panstwo_id in own]


def world_data(session):
    """Mapa świata: czynne lotniska i czynne połączenia (animacja samolotów)."""
    if not _tables_ready(session):
        return {'airports': [], 'routes': []}
    now = game_now()
    airports = active_airports(session, now)
    names = _names(session, {a.miasto_id for a in airports}, {a.panstwo_id for a in airports})
    from game.military_flights import calibration
    from math import hypot
    km = calibration(session).km_per_unit
    routes = [{'a': a.id, 'b': b.id, 'distanceKm': round(hypot(b.map_x - a.map_x, b.map_y - a.map_y) * km, 1)} for a, b in connections(session, now, airports)]
    return {'airports': [{key: value for key, value in airport_data(session, a, None, now, names).items() if key in ('id', 'name', 'cityName', 'country', 'position')}
                         for a in airports], 'routes': routes, 'speed': AIR_SPEED}


def military_airports(session, country, war=False):
    """Panel obrony: własne lotniska; panel wojenny: także wszystkie lotniska państw, z którymi trwa wojna (bez wywiadu)."""
    if not _tables_ready(session):
        return []
    own = set(controlled_ids(session, country)) or {country}
    ids = set(own)
    if war:
        from game.military_service import enemies
        for enemy in enemies(session, country):
            ids |= set(controlled_ids(session, enemy)) or {enemy}
    rows = list(session.scalars(select(Airport).where(Airport.panstwo_id.in_(list(ids)), Airport.removed_at.is_(None)).order_by(Airport.id)))
    now = game_now()
    names = _names(session, {a.miasto_id for a in rows}, {a.panstwo_id for a in rows})
    result = []
    for airport in rows:
        item = airport_data(session, airport, country, now, names)
        item['countryId'] = controller_id(session, airport.panstwo_id) or airport.panstwo_id
        result.append(item)
    return result


def destroy(session, airport, moment):
    """Lotnisko z życiem 0: znika z mapy (nowe można zbudować w tym mieście); traci obronę i zawieszenia połączeń."""
    from game.military_models import MissileDefense, MissileDefenseExpense, MilitaryFlight
    airport.removed_at = moment
    ids = list(session.scalars(select(MissileDefense.id).where(MissileDefense.target_kind == 'airport', MissileDefense.target_id == airport.id)))
    if ids:
        session.execute(update(MilitaryFlight).where(MilitaryFlight.target_defense_id.in_(ids)).values(target_defense_id=None))
        session.execute(update(MissileDefenseExpense).where(MissileDefenseExpense.defense_id.in_(ids)).values(defense_id=None))
        session.execute(delete(MissileDefense).where(MissileDefense.id.in_(ids)))
    session.execute(delete(AirRouteSuspension).where(or_(AirRouteSuspension.airport_id == airport.id, AirRouteSuspension.other_id == airport.id)))


def notify(session, country, text):
    from game.paga_ai_actor import country_user_id
    from game.forum_models import GameNotification
    owner = country_user_id(session, country)
    if owner is not None:
        session.add(GameNotification(user_id=owner, notification_type='SYSTEM', system_text='Lotnisko: ' + text, created_at=utc_now()))


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


@airports_bp.get('/stan')
def state_view():
    user, country, error = _player()
    if error:
        return error
    with Session(db.engine) as session:
        response = jsonify(state(session, country.PANSTWO_ID))
    response.headers['Cache-Control'] = 'no-store'
    return response


@airports_bp.post('/wycena')
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


@airports_bp.post('/zmien')
def change_view():
    user, country, error = _player()
    if error:
        return error
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error='Nieprawidłowe dane.'), 400
    db.session.rollback()
    try:
        if data.get('action') == 'build':
            return jsonify(ok=True, airport=build(user.id, data))
        if data.get('action') == 'rename':
            return jsonify(ok=True, airport=rename(user.id, data))
        return jsonify(ok=True, route=set_suspension(user.id, data))
    except FinanceConflict as exc:
        return jsonify(error=str(exc)), 409
    except FinanceError as exc:
        return jsonify(error=str(exc)), 400
