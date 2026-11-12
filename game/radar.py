"""Radary — technologia „Rozpoznanie radarowe” (UAT, 11 Nov 2026).

Zasady zatwierdzone przez administratora:
* technologia 'radar' (600 punktów rozwoju) wymaga chipu natsytowego;
* budowa w dowolnym miejscu własnego regionu (ekran „Obrona państwa”), lokalizacji nie można zmienić;
* koszt poziomu: I — 1 chip natsytowy, 100 żelaza, 11 MLD; II — 2 chipy, 150 żelaza, 18 MLD; III — 3 chipy, 200 żelaza, 24 MLD
  (kwoty z budżetu sił zbrojnych);
* zasięg wykrywania: 400 / 800 / 1200 km; radar pokazuje obce rakiety i samoloty tylko na odcinku lotu w zasięgu
  i raz na lot wysyła powiadomienie (liczba obiektów i cel);
* radar jest celem ataków (100 pkt życia, jak baza) i może mieć własną obronę przeciwrakietową; zniszczony radar nie wykrywa;
* likwidacja zwraca zawsze 1 chip natsytowy i 20 żelaza (0 ROI); radaru nie można sprzedać.
"""
import math
from datetime import timedelta
from decimal import Decimal
from sqlalchemy import select, func, or_, update, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from extensions import db
from game.finance_service import FinanceError, game_now
from game.radar_models import Radar, RadarExpense, RadarDetection

TECHNOLOGY = 'radar'
CHIP = 'chip_natsyt'
IRON = 'zelazo'
LEVELS = {1: {'chips': 1, 'iron': 100, 'cost': Decimal(11_000_000_000), 'range_km': 400},
          2: {'chips': 2, 'iron': 150, 'cost': Decimal(18_000_000_000), 'range_km': 800},
          3: {'chips': 3, 'iron': 200, 'cost': Decimal(24_000_000_000), 'range_km': 1200}}
MAX_LEVEL = 3
REFUND = {CHIP: 1, IRON: 20}
DETECTION_LOOKBACK = timedelta(hours=6)


def name(radar):
    return f'Radar #{radar.id}'


def spent(session, budget_id):
    return session.scalar(select(func.coalesce(func.sum(RadarExpense.amount), 0)).where(RadarExpense.budget_id == budget_id)) or Decimal(0)


def radar_data(radar):
    rule = LEVELS[radar.level]
    following = LEVELS.get(radar.level + 1)
    return {'id': radar.id, 'countryId': radar.panstwo_id, 'regionId': str(radar.region_id), 'name': name(radar),
            'position': [radar.map_x, radar.map_y], 'level': radar.level, 'maxLevel': MAX_LEVEL, 'health': radar.health,
            'rangeKm': rule['range_km'],
            'upgrade': {'level': radar.level + 1, 'chips': following['chips'], 'iron': following['iron'], 'cost': str(following['cost']),
                        'rangeKm': following['range_km']} if following else None}


def config(session, country_id):
    from game.industry_service import researched, available
    return {'researched': researched(session, country_id, TECHNOLOGY), 'chips': available(session, country_id, CHIP),
            'iron': available(session, country_id, IRON),
            'levels': {level: {'chips': rule['chips'], 'iron': rule['iron'], 'cost': str(rule['cost']), 'rangeKm': rule['range_km']} for level, rule in LEVELS.items()},
            'refund': REFUND}


def visible_radars(session, country_id, world=False):
    """Own radars; during a war every radar is visible on the war map (like factories)."""
    query = select(Radar).order_by(Radar.id)
    if not world:
        query = query.where(Radar.panstwo_id == country_id)
    return [radar_data(radar) for radar in session.scalars(query)]


# ---------------- player actions ----------------

def _pay(session, country_id, rule):
    from game.industry_service import available, consume
    from game.military_service import military_budget
    missing = [label for code, amount, label in ((CHIP, rule['chips'], 'chipów natsytowych'), (IRON, rule['iron'], 'żelaza'))
               if available(session, country_id, code) < amount]
    if missing:
        raise FinanceError('Za mało surowców w magazynie: ' + ', '.join(missing) + f' (potrzeba: {rule["chips"]} chip natsytowy, {rule["iron"]} żelaza).')
    budget, _, free = military_budget(session, country_id)
    if budget is None or free < rule['cost']:
        raise FinanceError('Za mało środków w budżecie sił zbrojnych na bieżące półrocze.')
    consume(session, country_id, {CHIP: rule['chips'], IRON: rule['iron']})
    return budget


def _own_radar(session, country_id, radar_id):
    from game.military_service import natural
    radar = session.scalar(select(Radar).where(Radar.id == natural(radar_id, 'Radar', 1), Radar.panstwo_id == country_id).with_for_update())
    if radar is None:
        raise FinanceError('Radar nie należy do państwa gracza.')
    return radar


def change_radar(user_id, data):
    from game.finance_service import _country_for_user
    from game.governance import controlled_ids
    from game.industry_service import require_technologies
    from game.land_war import require_buildable
    from models import Region
    action = data.get('action')
    with Session(db.engine) as session, session.begin():
        country = _country_for_user(session, user_id, lock=True)
        own = country.PANSTWO_ID
        if action == 'build':
            from game.mining_service import request_key
            key = request_key(data.get('request_id'))
            existing = session.scalar(select(Radar).where(Radar.panstwo_id == own, Radar.request_id == key))
            if existing is not None:
                return existing.id, 'Radar już zbudowano.'
            require_technologies(session, own, [TECHNOLOGY])
            from game.roads import point
            from game.military_geography import region_contains
            x, y = point([data.get('x'), data.get('y')])
            region = data.get('region_id')
            if type(region) is not int or session.scalar(select(Region.region_id).where(Region.region_id == region, Region.panstwo_id.in_(controlled_ids(session, own)))) is None \
                    or not region_contains(region, x, y):
                raise FinanceError('Wskaż punkt we własnym regionie.')
            require_buildable(session, region, own)
            budget = _pay(session, own, LEVELS[1])
            radar = Radar(panstwo_id=own, region_id=region, map_x=x, map_y=y, level=1, health=100, request_id=key, created_game_at=game_now())
            session.add(radar)
            session.flush()
            session.add(RadarExpense(panstwo_id=own, budget_id=budget.id, radar_id=radar.id, level=1, amount=LEVELS[1]['cost']))
            return radar.id, f'Zbudowano {name(radar)} (poziom I, zasięg {LEVELS[1]["range_km"]} km).'
        radar = _own_radar(session, own, data.get('radar_id'))
        if action == 'upgrade':
            if radar.level >= MAX_LEVEL:
                raise FinanceError('Radar osiągnął maksymalny poziom III.')
            if radar.health <= 0:
                raise FinanceError('Zniszczonego radaru nie można rozbudować.')
            require_buildable(session, radar.region_id, own)
            rule = LEVELS[radar.level + 1]
            budget = _pay(session, own, rule)
            radar.level += 1
            session.add(RadarExpense(panstwo_id=own, budget_id=budget.id, radar_id=radar.id, level=radar.level, amount=rule['cost']))
            return radar.id, f'Rozbudowano {name(radar)} do poziomu {radar.level} (zasięg {rule["range_km"]} km).'
        if action == 'liquidate':
            liquidate(session, radar)
            from game.mining_service import stock
            for code, amount in REFUND.items():
                stock(session, own, code).quantity += amount
            return None, 'Zlikwidowano radar. Do magazynu wróciły: 1 chip natsytowy i 20 żelaza.'
        raise FinanceError('Nieznana operacja radaru.')


def detach(session, radar_id):
    """Removes everything that points at the radar (its missile defence goes with it)."""
    from game.military_models import MissileDefense, MissileDefenseExpense, MilitaryFlight
    ids = list(session.scalars(select(MissileDefense.id).where(MissileDefense.target_kind == 'radar', MissileDefense.target_id == radar_id)))
    if ids:
        session.execute(update(MilitaryFlight).where(MilitaryFlight.target_defense_id.in_(ids)).values(target_defense_id=None))
        session.execute(update(MissileDefenseExpense).where(MissileDefenseExpense.defense_id.in_(ids)).values(defense_id=None))
        session.execute(delete(MissileDefense).where(MissileDefense.id.in_(ids)))
    session.execute(update(MilitaryFlight).where(MilitaryFlight.target_radar_id == radar_id).values(target_radar_id=None))
    session.execute(update(RadarExpense).where(RadarExpense.radar_id == radar_id).values(radar_id=None))
    session.execute(update(RadarDetection).where(RadarDetection.radar_id == radar_id).values(radar_id=None))


def liquidate(session, radar):
    detach(session, radar.id)
    session.delete(radar)
    session.flush()


# ---------------- detection geometry ----------------

def _km_per_unit(session):
    from game.military_flights import calibration
    return calibration(session).km_per_unit


def coverage(session, country_id, scale=None):
    """[(radar, x, y, radius in map units)] of operational radars."""
    scale = scale or _km_per_unit(session)
    return [(radar, radar.map_x, radar.map_y, LEVELS[radar.level]['range_km'] / scale)
            for radar in session.scalars(select(Radar).where(Radar.panstwo_id == country_id, Radar.health > 0).order_by(Radar.id))]


def segments(flight):
    """Straight legs of a flight: (from, to, start, end). Missiles fly to the target; fighters fly there, wait and come back."""
    source = (flight.source_x, flight.source_y)
    target = (flight.target_x, flight.target_y)
    if flight.kind != 'air':
        return [(source, target, flight.starts_at, flight.impact_at)]
    arrival = flight.fighter_arrives_at or flight.impact_at
    back = max(flight.impact_at, arrival)
    legs = [(source, target, flight.starts_at, arrival)]
    if back > arrival:
        legs.append((target, target, arrival, back))
    legs.append((target, source, back, flight.returns_at or back))
    return legs


def _inside(start, end, centre, radius):
    """Fractions [s0, s1] of the segment lying inside the circle, or None."""
    dx, dy = end[0] - start[0], end[1] - start[1]
    fx, fy = start[0] - centre[0], start[1] - centre[1]
    a = dx * dx + dy * dy
    c = fx * fx + fy * fy - radius * radius
    if a == 0:
        return (0.0, 1.0) if c <= 0 else None
    b = 2 * (fx * dx + fy * dy)
    disc = b * b - 4 * a * c
    if disc < 0:
        return None
    root = math.sqrt(disc)
    s0, s1 = max(0.0, (-b - root) / (2 * a)), min(1.0, (-b + root) / (2 * a))
    return (s0, s1) if s0 <= s1 else None


def track(flight, circles):
    """Pieces of the flight inside any circle: [{'from','to','fromAt','toAt','radarId','since'}] (game time)."""
    pieces = []
    for start, end, t0, t1 in segments(flight):
        if t1 is None or t0 is None or t1 < t0:
            continue
        spans = []
        for radar, x, y, radius in circles:
            span = _inside(start, end, (x, y), radius)
            if span is None:
                continue
            enter = t0 + (t1 - t0) * span[0]
            since = getattr(radar, 'created_game_at', None)
            if since is not None and since > enter:
                # The radar was built later: it sees only the remaining part of the leg.
                if since >= t0 + (t1 - t0) * span[1]:
                    continue
                total = (t1 - t0).total_seconds() or 1
                span = ((since - t0).total_seconds() / total, span[1])
            spans.append((span[0], span[1], radar.id))
        spans.sort()
        merged = []
        for s0, s1, radar_id in spans:
            if merged and s0 <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], s1)
            else:
                merged.append([s0, s1, radar_id])
        for s0, s1, radar_id in merged:
            at = lambda s: t0 + (t1 - t0) * s
            point = lambda s: [start[0] + (end[0] - start[0]) * s, start[1] + (end[1] - start[1]) * s]
            pieces.append({'from': point(s0), 'to': point(s1), 'fromAt': at(s0), 'toAt': at(s1), 'radarId': radar_id})
    return pieces


def _stamp(value):
    return value.isoformat() + 'Z' if value else None


def radar_flights(session, country_id, exclude_ids, now=None):
    """Foreign flights seen only by our radars: just the tracked pieces, never the hidden launch site."""
    from game.military_models import MilitaryFlight
    now = now or game_now()
    try:
        circles = coverage(session, country_id)
    except FinanceError:
        return []
    if not circles:
        return []
    items = []
    query = select(MilitaryFlight).where(MilitaryFlight.panstwo_id != country_id, MilitaryFlight.returned_at.is_(None),
                                         MilitaryFlight.starts_at <= now).order_by(MilitaryFlight.id)
    for flight in session.scalars(query):
        if flight.id in exclude_ids:
            continue
        pieces = [piece for piece in track(flight, circles) if piece['toAt'] > now]
        if flight.kind != 'air':
            pieces = [piece for piece in pieces if piece['fromAt'] < flight.impact_at]
        if not pieces:
            continue
        items.append({'id': flight.id, 'kind': flight.kind, 'radarOnly': True, 'countryId': flight.panstwo_id, 'targetName': flight.target_name,
                      'targetCountryId': flight.target_country_id, 'missiles': flight.missiles, 'missileType': flight.missile_type,
                      'isNuclear': flight.is_nuclear, 'impactAt': _stamp(flight.impact_at), 'returnsAt': _stamp(flight.returns_at),
                      'startsAt': _stamp(flight.starts_at), 'sourceBaseId': None,
                      'radarTrack': [{'from': p['from'], 'to': p['to'], 'fromAt': _stamp(p['fromAt']), 'toAt': _stamp(p['toAt'])} for p in pieces]})
    return items


def _objects_text(flight):
    from game.military_service import MISSILES
    label = MISSILES.get(flight.missile_type, (None, 'rakiety'))[1].lower()
    if flight.kind == 'air':
        return f'1 myśliwiec (uzbrojenie: {flight.missiles} — {label})'
    return f'{flight.missiles} — {label}' + (' z głowicami atomowymi' if flight.is_nuclear else '')


def detect(session, now=None):
    """One notification per country and flight when the flight first enters the range of the country's operational radar."""
    from game.military_models import MilitaryFlight
    from game.land_war import notify, names
    now = now or game_now()
    radars = list(session.scalars(select(Radar).where(Radar.health > 0)))
    if not radars:
        return 0
    try:
        scale = _km_per_unit(session)
    except FinanceError:
        return 0
    circles = {}
    for radar in radars:
        circles.setdefault(radar.panstwo_id, []).append((radar, radar.map_x, radar.map_y, LEVELS[radar.level]['range_km'] / scale))
    flights = list(session.scalars(select(MilitaryFlight).where(MilitaryFlight.starts_at <= now,
                   or_(MilitaryFlight.returned_at.is_(None), MilitaryFlight.returned_at >= now - DETECTION_LOOKBACK))))
    if not flights:
        return 0
    done = set(session.execute(select(RadarDetection.panstwo_id, RadarDetection.flight_id)
                               .where(RadarDetection.flight_id.in_([flight.id for flight in flights]))).tuples())
    created = 0
    for country_id, own in circles.items():
        for flight in flights:
            if flight.panstwo_id == country_id or (country_id, flight.id) in done:
                continue
            pieces = [piece for piece in track(flight, own) if piece['fromAt'] <= now]
            if flight.kind != 'air':
                pieces = [piece for piece in pieces if piece['fromAt'] < flight.impact_at]
            if not pieces:
                continue
            first = min(pieces, key=lambda piece: piece['fromAt'])
            try:
                with session.begin_nested():
                    session.add(RadarDetection(panstwo_id=country_id, flight_id=flight.id, radar_id=first['radarId'], detected_at=first['fromAt']))
            except IntegrityError:
                continue
            created += 1
            who = names(session, flight.panstwo_id, flight.target_country_id)
            notify(session, country_id, f'Radar #{first["radarId"]} wykrył lecące obiekty państwa {who.get(flight.panstwo_id, "obcego")}: '
                                        f'{_objects_text(flight)}. Cel: {flight.target_name} ({who.get(flight.target_country_id, "nieznane państwo")}).')
    session.flush()
    return created
