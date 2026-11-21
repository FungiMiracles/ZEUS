"""Rakiety z głowicą nuklearną (13 Nov 2026).

Jedno źródło reguł: technologia, fabryka, produkcja na zamówienie, licznik rzeczywistych głowic, utrzymanie w silosie,
zasięg i skutki uderzenia (strefa skażenia) oraz powiadomienia do wszystkich państw (gracze ludzcy i PAGA2).
"""
from datetime import timedelta
from decimal import Decimal
from sqlalchemy import select
from game import nuclear_models  # noqa: F401 — rejestracja tabel w metadanych

TECHNOLOGY = 'nuclear_missiles'
TECH_REQUIREMENTS = ('long_missiles', 'mine_uranium', 'chip_cemium_i')
STOCK_CODE = 'nuclear_missiles'            # game_resource_stocks: wszystkie posiadane rakiety (w magazynie + w silosach)
FACTORY_COST = Decimal('37400000000')       # 37,4 mld ROI (budżet sił zbrojnych)
FACTORY_BUILD_DAYS = 31
MISSILE_DAYS = 14                           # produkcja jednej rakiety (dni Entendy)
MISSILE_INPUTS = {'uran': 7, 'zelazo': 37, 'chip_cemium_i': 1}
INPUT_LABELS = {'uran': 'uran', 'zelazo': 'żelazo', 'chip_cemium_i': 'chip cemium I'}
SILO_UPKEEP = Decimal('650000000')          # za głowicę w silosie na okres (półrocze; kwartał — połowa)
RANGE_KM = 3000
SPEED_KMH = 5200                            # jak rakiety dalekiego zasięgu
RADIUS_KM = 100                             # promień skażenia
CONTAMINATION_YEARS = 3
ENVIRONMENT_DELTA = 50                      # degradacja środowiska i zanieczyszczenie powietrza regionu
INFRASTRUCTURE_LOSS = (40, 70)              # każdy rodzaj infrastruktury regionu (losowo w przedziale)
MISSILE_LABEL = 'Rakieta z głowicą nuklearną'
FACTORY_LABEL = 'Fabryka rakiet z głowicą nuklearną'


# ---------------- licznik głowic ----------------

def total(session, country_id):
    """Rzeczywista liczba rakiet z głowicą nuklearną państwa (w magazynie i w silosach)."""
    from game.commerce_models import ResourceStock
    row = session.get(ResourceStock, (country_id, STOCK_CODE))
    return int(row.quantity) if row else 0


def loaded(session, country_id):
    from game.military_models import MilitaryBase
    return sum(int((base.garrison or {}).get('warheads', 0)) for base in
               session.scalars(select(MilitaryBase).where(MilitaryBase.panstwo_id == country_id, MilitaryBase.kind == 'nuclear')))


def change_total(session, country_id, delta):
    from game.mining_service import stock
    row = stock(session, country_id, STOCK_CODE)
    row.quantity = max(0, int(row.quantity) + int(delta))
    return int(row.quantity)


# ---------------- powiadomienia do wszystkich państw ----------------

def broadcast(session, text, exclude=()):
    """Powiadomienie systemowe do skrzynek wszystkich aktywnych państw — graczy ludzkich i PAGA2 (ta sama skrzynka co wyzwalacze PAGA2)."""
    from models import Panstwo
    from game.forum_models import GameNotification
    from game.paga_ai_actor import country_user_id
    from game.models import utc_now
    sent = set()
    for country_id in session.scalars(select(Panstwo.PANSTWO_ID).where(Panstwo.status == 'aktywne').order_by(Panstwo.PANSTWO_ID)):
        if country_id in exclude:
            continue
        try:
            user_id = country_user_id(session, country_id)
        except Exception:
            user_id = None
        if user_id is None or user_id in sent:
            continue
        sent.add(user_id)
        session.add(GameNotification(user_id=user_id, notification_type='SYSTEM', system_text=text, created_at=utc_now()))
    return len(sent)


def country_name(session, country_id):
    from models import Panstwo
    return session.scalar(select(Panstwo.panstwo_nazwa).where(Panstwo.PANSTWO_ID == country_id)) or f'Państwo #{country_id}'


def contamination_until(moment):
    return moment + timedelta(days=365 * CONTAMINATION_YEARS)


# ---------------- fabryka i produkcja na zamówienie ----------------

def factory_ready_at(factory):
    return factory.created_game_at + timedelta(days=FACTORY_BUILD_DAYS)


def _active_order(session, factory_id, lock=False):
    from game.nuclear_models import NuclearOrder
    query = select(NuclearOrder).where(NuclearOrder.factory_id == factory_id, NuclearOrder.status == 'active')
    return session.scalar(query.with_for_update() if lock else query)


def _production_end(factory, now):
    end = now
    if factory.removed_at is not None:
        end = min(end, factory.removed_at)
    if factory.health <= 0 and getattr(factory, 'destroyed_at', None) is not None:
        end = min(end, factory.destroyed_at)
    return end


def settle_orders(session, country_id, now):
    """Dolicza rakiety ukończone do chwili `now` (kolejno po 14 dni od startu zamówienia; po budowie fabryki)."""
    from game.nuclear_models import NuclearOrder
    from game.research_models import AmmunitionFactory
    from game.industry_service import notify
    for order in session.scalars(select(NuclearOrder).where(NuclearOrder.panstwo_id == country_id, NuclearOrder.status == 'active').with_for_update()):
        factory = session.get(AmmunitionFactory, order.factory_id) if order.factory_id else None
        end = _production_end(factory, now) if factory is not None else order.started_at
        start = max(order.started_at, factory_ready_at(factory)) if factory is not None else order.started_at
        finished = min(order.quantity, max(0, int((end - start) / timedelta(days=MISSILE_DAYS)))) if end > start else 0
        if finished > order.produced:
            change_total(session, country_id, finished - order.produced)
            order.produced = finished
        if order.produced >= order.quantity:
            order.status = 'done'
            notify(session, country_id, f'{FACTORY_LABEL} #{order.factory_id}: zakończono produkcję {order.quantity} szt. rakiet z głowicą nuklearną.')
        elif factory is None or factory.removed_at is not None or factory.health <= 0:
            order.status = 'stopped'
            notify(session, country_id, f'{FACTORY_LABEL} #{order.factory_id}: produkcja przerwana (fabryka zniszczona lub zlikwidowana). Wyprodukowano {order.produced} z {order.quantity} szt.')


def order_missiles(session, country_id, factory, count, key, now):
    from game.nuclear_models import NuclearOrder
    from game.industry_service import available, consume
    from game.finance_service import FinanceError
    if factory.kind != TECHNOLOGY:
        raise FinanceError('Ta fabryka nie produkuje rakiet z głowicą nuklearną.')
    if factory.health <= 0:
        raise FinanceError('Zniszczona fabryka nie może produkować.')
    if now < factory_ready_at(factory):
        raise FinanceError('Fabryka jest jeszcze w budowie.')
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 1000:
        raise FinanceError('Podaj liczbę rakiet od 1 do 1000.')
    existing = session.scalar(select(NuclearOrder).where(NuclearOrder.panstwo_id == country_id, NuclearOrder.request_id == key))
    if existing is not None:
        return existing.id
    if _active_order(session, factory.id, lock=True) is not None:
        raise FinanceError('Fabryka realizuje już zamówienie. Poczekaj na jego zakończenie albo je anuluj.')
    missing = [f'{INPUT_LABELS.get(code, code)} (potrzeba {need * count}, w magazynie {available(session, country_id, code)})'
               for code, need in MISSILE_INPUTS.items() if available(session, country_id, code) < need * count]
    if missing:
        raise FinanceError('Za mało surowców w magazynie: ' + ', '.join(missing) + '.')
    consume(session, country_id, MISSILE_INPUTS, count)
    order = NuclearOrder(panstwo_id=country_id, factory_id=factory.id, quantity=count, produced=0, started_at=now, status='active',
                         materials=dict(MISSILE_INPUTS), request_id=key)
    session.add(order)
    session.flush()
    return order.id


def cancel_order(session, country_id, factory, now):
    """Anulowanie: rakiety ukończone zostają, rozpoczęta sztuka przepada, surowce niezaczętych sztuk wracają do magazynu."""
    from game.mining_service import stock
    from game.finance_service import FinanceError
    settle_orders(session, country_id, now)
    order = _active_order(session, factory.id, lock=True)
    if order is None:
        raise FinanceError('Fabryka nie realizuje żadnego zamówienia.')
    in_progress = 1 if now >= factory_ready_at(factory) and order.produced < order.quantity else 0
    unstarted = max(0, order.quantity - order.produced - in_progress)
    for code, amount in (order.materials or {}).items():
        if unstarted:
            stock(session, country_id, code).quantity += int(amount) * unstarted
    order.status = 'cancelled'
    return unstarted


def factory_info(session, factory, now):
    """Dane fabryki dla interfejsu: stan budowy i bieżącego zamówienia."""
    ready = factory_ready_at(factory)
    built = now >= ready
    total_days = FACTORY_BUILD_DAYS
    progress = 100 if built else max(0, min(99, int((now - factory.created_game_at) / timedelta(days=total_days) * 100)))
    order = _active_order(session, factory.id)
    data = dict(onDemand=True, ready=built, readyAt=ready.isoformat() + 'Z', progress=progress, missileDays=MISSILE_DAYS,
                missileInputs=dict(MISSILE_INPUTS), order=None)
    if order is not None:
        start = max(order.started_at, ready)
        next_at = start + timedelta(days=MISSILE_DAYS * (order.produced + 1))
        done_at = start + timedelta(days=MISSILE_DAYS * order.quantity)
        data['order'] = dict(id=order.id, quantity=order.quantity, produced=order.produced, nextAt=next_at.isoformat() + 'Z', doneAt=done_at.isoformat() + 'Z')
    return data


# ---------------- strefy skażenia ----------------

def _km_per_unit(session):
    from game.military_flights import calibration
    return calibration(session).km_per_unit


def active_zones(session, now=None):
    from game.nuclear_models import NuclearZone
    from game.finance_service import game_now
    moment = now or game_now()
    return list(session.scalars(select(NuclearZone).where(NuclearZone.until > moment).order_by(NuclearZone.id)))


def zone_at(session, x, y, now=None):
    """Aktywna strefa skażenia obejmująca punkt mapy (x, y) albo None."""
    from math import hypot
    zones = active_zones(session, now)
    if not zones:
        return None
    scale = _km_per_unit(session)
    for zone in zones:
        if hypot(x - zone.x, y - zone.y) * scale <= zone.radius_km:
            return zone
    return None


def require_clear(session, x, y, now=None):
    """Zakaz budowy w strefie skażenia (3 lata Entendy od uderzenia)."""
    from game.finance_service import FinanceError
    zone = zone_at(session, x, y, now)
    if zone is not None:
        raise FinanceError(f'Obszar jest skażony po uderzeniu atomowym — budowa możliwa od {zone.until:%d.%m.%Y} (czas Entendy).')


def require_clear_path(session, points, now=None):
    if not active_zones(session, now):
        return
    for x, y in points:
        require_clear(session, x, y, now)


def zones_data(session, now=None):
    return [{'id': zone.id, 'x': zone.x, 'y': zone.y, 'radiusKm': zone.radius_km, 'until': zone.until.isoformat() + 'Z'} for zone in active_zones(session, now)]


# ---------------- uderzenie ----------------

def _within(scale, x, y, cx, cy):
    from math import hypot
    return x is not None and y is not None and hypot(x - cx, y - cy) * scale <= RADIUS_KM


def detonate(session, flight, order, hits):
    """Skutki trafienia rakietą z głowicą nuklearną: strefa 100 km (ludzie w miastach giną, obiekty zniszczone,
    zakaz budowy 3 lata), region uderzenia: degradacja +50, zanieczyszczenie +50, każda infrastruktura −40…−70."""
    from secrets import randbelow
    from types import SimpleNamespace
    from sqlalchemy.orm import lazyload
    from models import Region, Miasto, Panstwo
    from game.nuclear_models import NuclearZone
    from game.infrastructure_service import FIELDS
    from game.industry_service import change_indicator
    from game.military_flights import apply_structural_damage
    from game.military_models import MilitaryBase, MilitaryVessel, MissileDefense
    from game.military_geography import city_point
    if not hits:
        return {}, 0
    cx, cy = flight.target_x, flight.target_y
    scale = _km_per_unit(session)
    moment = flight.impact_at
    if session.scalar(select(NuclearZone.id).where(NuclearZone.flight_id == flight.id)) is None:
        session.add(NuclearZone(attacker_id=flight.panstwo_id, target_country_id=flight.target_country_id, region_id=order.region_id, flight_id=flight.id,
                                x=cx, y=cy, radius_km=RADIUS_KM, created_game_at=moment, until=contamination_until(moment)))
    destroyed = {'bases': 0, 'factories': 0, 'power': 0, 'airports': 0, 'mines': 0, 'radars': 0, 'defenses': 0, 'vessels': 0}

    def strike(kind, owner, **ids):
        fields = dict(target_defense_id=None, target_base_id=None, target_mine_id=None, target_radar_id=None, target_power_id=None, target_airport_id=None,
                      target_factory_id=None, target_shipment_id=None, target_vessel_id=None)
        fields.update(ids)
        fake = SimpleNamespace(target_kind=kind, target_country_id=owner, panstwo_id=flight.panstwo_id, impact_at=moment, id=flight.id, **fields)
        return apply_structural_damage(session, fake, order, 100)

    # obiekty w promieniu — także w regionach sąsiednich i u innych państw
    for base in list(session.scalars(select(MilitaryBase).where(MilitaryBase.map_x.is_not(None)))):
        if _within(scale, base.map_x, base.map_y, cx, cy) and base.health > 0:
            strike('base', base.panstwo_id, target_base_id=base.id); destroyed['bases'] += 1
    from game.research_models import AmmunitionFactory
    for factory in list(session.scalars(select(AmmunitionFactory).where(AmmunitionFactory.removed_at.is_(None), AmmunitionFactory.health > 0))):
        if _within(scale, factory.map_x, factory.map_y, cx, cy):
            strike('factory', factory.panstwo_id, target_factory_id=factory.id); destroyed['factories'] += 1
    from game.industry_models import PowerPlant
    for plant in list(session.scalars(select(PowerPlant).where(PowerPlant.removed_at.is_(None), PowerPlant.health > 0))):
        if _within(scale, plant.map_x, plant.map_y, cx, cy):
            strike('power', plant.panstwo_id, target_power_id=plant.id); destroyed['power'] += 1
    # 20 Nov 2026: porty lotnicze w promieniu wybuchu
    from game.airport_models import Airport
    from sqlalchemy import inspect as _inspect
    from game.governance import controller_id as _controller
    if _inspect(session.connection()).has_table(Airport.__tablename__):
        for airport in list(session.scalars(select(Airport).where(Airport.removed_at.is_(None), Airport.health > 0))):
            if _within(scale, airport.map_x, airport.map_y, cx, cy):
                strike('airport', _controller(session, airport.panstwo_id) or airport.panstwo_id, target_airport_id=airport.id); destroyed['airports'] += 1
    from game.commerce_models import Mine
    for mine in list(session.scalars(select(Mine).where(Mine.removed_at.is_(None), Mine.health > 0))):
        if _within(scale, mine.map_x, mine.map_y, cx, cy):
            strike('mine', mine.panstwo_id, target_mine_id=mine.id); destroyed['mines'] += 1
    from game.radar_models import Radar
    for radar in list(session.scalars(select(Radar).where(Radar.health > 0))):
        if _within(scale, radar.map_x, radar.map_y, cx, cy):
            strike('radar', radar.panstwo_id, target_radar_id=radar.id); destroyed['radars'] += 1
    from game.missile_defense import defense_data
    for defense in list(session.scalars(select(MissileDefense).where(MissileDefense.health > 0))):
        position = (defense_data(defense) or {}).get('position')
        if position and _within(scale, position[0], position[1], cx, cy):
            strike('defense', defense.panstwo_id, target_defense_id=defense.id); destroyed['defenses'] += 1
    from game.military_navy import vessel_position
    for vessel in list(session.scalars(select(MilitaryVessel).where(MilitaryVessel.status.in_(['sailing', 'stationed', 'returning'])))):
        position = vessel_position(vessel, moment)
        if position and _within(scale, position[0], position[1], cx, cy):
            strike('vessel', vessel.panstwo_id, target_vessel_id=vessel.id); destroyed['vessels'] += 1

    # ludność miast w promieniu ginie
    casualties = 0
    from game.models import utc_now
    from models import MiastoStateHistory
    for city in session.scalars(select(Miasto).options(lazyload('*')).where(Miasto.miasto_populacja > 0).with_for_update()):
        point = city_point(city.miasto_id)
        if not point or not _within(scale, point[0], point[1], cx, cy):
            continue
        before = int(city.miasto_populacja or 0)
        city.miasto_populacja = 0
        casualties += before
        country = session.scalar(select(Panstwo).options(lazyload('*')).where(Panstwo.PANSTWO_ID == city.panstwo_id).with_for_update())
        if country is not None and country.panstwo_populacja is not None:
            country.panstwo_populacja = max(0, country.panstwo_populacja - before)
        session.add(MiastoStateHistory(miasto_id=city.miasto_id, data_entenda=moment.date(), data_rzeczywista=utc_now(), source='NUCLEAR_STRIKE', event_id=None,
                                       old_miasto_populacja=before, new_miasto_populacja=0, change_delta=-before))

    # region uderzenia: środowisko i infrastruktura
    infrastructure = {}
    region = session.scalar(select(Region).options(lazyload('*')).where(Region.region_id == order.region_id).with_for_update())
    if region is not None:
        change_indicator(session, region.region_id, 'region_degradacja_srodowiska', ENVIRONMENT_DELTA)
        change_indicator(session, region.region_id, 'region_zanieczyszczenie_powietrza', ENVIRONMENT_DELTA)
        low, high = INFRASTRUCTURE_LOSS
        for metric, field in FIELDS.items():
            loss = low + randbelow(high - low + 1)
            before = getattr(region, field)
            if before is None:
                continue
            setattr(region, field, max(0, before - loss))
            infrastructure[metric] = loss
    session.flush()
    return {'nuclear': True, 'zoneRadiusKm': RADIUS_KM, 'destroyed': destroyed, 'infrastructureLoss': infrastructure,
            'environment': ENVIRONMENT_DELTA}, casualties
