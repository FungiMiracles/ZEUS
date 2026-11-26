"""Satelity szpiegowskie (administrator, 26 Nov 2026).

Jedno źródło reguł:
- technologia „Satelita szpiegowski” (900 pkt, 60 dni) → fabryka satelitów (game.industry_catalog, produkcja na zamówienie
  w game.nuclear — 1 satelita / 90 dni) → magazyn państwa (game_resource_stocks: spy_satellites);
- wyniesienie na orbitę z własnej bazy lotniczej w kraju (ekran „Obrona państwa”): 1 satelita z magazynu, 1 rakieta dalekiego
  zasięgu i 300 ropy naftowej; wynoszenie trwa minutę czasu rzeczywistego;
- satelita na orbicie dryfuje w losowych kierunkach (100 km/h Entendy); na rozkaz z ekranu „Wywiad wojskowy” leci nad wybrane
  państwo (600 km/h Entendy; po rozbudowie do poziomów 2–4: 900, 1200, 1500 km/h) i rozpoznaje obiekty wybranego rodzaju na całym jego terytorium — zawsze skutecznie
  (kontrwywiad działa tylko na agentów); każde użycie kosztuje 120 mln ROI z budżetu służb specjalnych i porządkowych;
- wyniki misji zasilają game.intelligence_service.known_ids (cele w panelu wojennym) i warstwę „Rozpoznanie satelitarne”
  na ekranach „Obrona państwa”, „Świat” i „Wywiad wojskowy”;
- satelity innych państw widzi tylko państwo, które ma własnego satelitę na orbicie.
"""
from datetime import timedelta
from decimal import Decimal
from functools import lru_cache
from math import cos, sin, pi, hypot
from secrets import randbelow
from uuid import UUID
from sqlalchemy import select, inspect, func
from sqlalchemy.orm import Session
from extensions import db
from game import satellite_models  # noqa: F401 — rejestracja tabel w metadanych
from game.satellite_models import SpySatellite, SatelliteMission
from game.finance_service import FinanceError, FinanceConflict, _country_for_user, game_now

TECHNOLOGY = 'spy_satellite'
STOCK_CODE = 'spy_satellites'
FACTORY_KIND = 'satellites'
LAUNCH_INPUTS = {'ropa_naftowa': 300}           # z magazynu
LAUNCH_MISSILE_FIELD = 'rakiety_dalekiego_zasiegu'
LAUNCH_MISSILES = 1
LAUNCH_SECONDS = 60                              # czas rzeczywisty wynoszenia (pasek postępu w oknie)
DRIFT_KMH = 100
# 26 Nov 2026: poziomy satelity — prędkość przelotu nad państwo celu (km/h Entendy) i koszt rozbudowy do poziomu (ROI,
# budżet służb specjalnych i porządkowych). Rozbudowa tylko wtedy, gdy satelita nie wykonuje misji.
LEVELS = {1: (600, Decimal(0)), 2: (900, Decimal('17500000000')), 3: (1200, Decimal('29000000000')), 4: (1500, Decimal('36200000000'))}
MAX_LEVEL = max(LEVELS)
MISSION_KMH = LEVELS[1][0]


def mission_speed(level):
    return LEVELS.get(int(level or 1), LEVELS[1])[0]
MISSION_COST = Decimal('120000000')              # 120 mln ROI za każde użycie (budżet służb)
DRIFT_HOURS = (8, 36)                            # długość jednego odcinka dryfu (godziny Entendy)
LABEL = 'Satelita szpiegowski'
ICON = 'SATELITA SZPIEGOWSKI.svg'
FLIGHT_ICON = 'SATELITA SZPIEGOWSKI LOT.svg'
LAUNCH_ICON = 'LAUNCH.svg'
# Kolejność opcji w kole wokół satelity (ekran „Wywiad wojskowy”).
MISSIONS = {'bases': 'Położenie baz wojskowych', 'defenses': 'Obrona przeciwrakietowa', 'mines': 'Położenie kopalń',
            'power': 'Położenie elektrowni', 'silos': 'Rozmieszczenie silosów atomowych'}
MISSION_ICONS = {'bases': 'BAZA.svg', 'defenses': 'OBRONA PRZECIWRAKIETOWA.svg', 'mines': 'KOPALNIA.svg',
                 'power': 'ELEKTROWNIA WĘGLOWA.svg', 'silos': 'SILOS ATOMOWY.svg'}
# Klucze raportu zgodne z misjami agentów (game.intelligence_service.known_ids).
REPORT_KEYS = {'bases': 'base_ids', 'silos': 'base_ids', 'defenses': 'defense_ids', 'mines': 'mine_ids', 'power': 'power_ids'}

_READY = set()


def tables_ready(session):
    """Bez migracji (np. PROD) moduł jest wyłączony, a reszta gry działa jak wcześniej."""
    bind = session.get_bind()
    key = str(bind.url)
    if key in _READY:
        return True
    try:
        names = set(inspect(session.connection()).get_table_names())
    except Exception:
        return False
    if {SpySatellite.__tablename__, SatelliteMission.__tablename__} <= names:
        _READY.add(key)
        return True
    return False


# ---------------- geometria i ruch ----------------

@lru_cache(maxsize=1)
def _bounds_cached(mtime):
    from game.military_geography import MAP_PATH, map_features, polygons
    xs, ys = [], []
    for feature in map_features(MAP_PATH):
        for rings in polygons(feature.get('geometry') or {}):
            for point in (rings[0] if rings else []):
                xs.append(point[0]); ys.append(point[1])
    if not xs:
        return (0.0, 0.0, 1.0, 1.0)
    pad_x, pad_y = (max(xs) - min(xs)) * .02, (max(ys) - min(ys)) * .02
    return (min(xs) - pad_x, min(ys) - pad_y, max(xs) + pad_x, max(ys) + pad_y)


def map_bounds():
    from game.military_geography import MAP_PATH
    return _bounds_cached(MAP_PATH.stat().st_mtime_ns)


def km_per_unit(session):
    from game.military_flights import calibration
    return calibration(session).km_per_unit


def position(sat, now):
    """Bieżący punkt satelity (x, y) na mapie."""
    if sat.status == 'launching' or now >= sat.seg_end or sat.seg_end <= sat.seg_start:
        return (sat.to_x, sat.to_y) if sat.status != 'launching' and now >= sat.seg_end else (sat.from_x, sat.from_y)
    if now <= sat.seg_start:
        return (sat.from_x, sat.from_y)
    share = (now - sat.seg_start) / (sat.seg_end - sat.seg_start)
    return (sat.from_x + (sat.to_x - sat.from_x) * share, sat.from_y + (sat.to_y - sat.from_y) * share)


def _drift(sat, start, moment, scale):
    """Nowy odcinek dryfu z punktu `start` od chwili `moment` w losowym kierunku, wewnątrz mapy świata."""
    low_x, low_y, high_x, high_y = map_bounds()
    hours = DRIFT_HOURS[0] + randbelow((DRIFT_HOURS[1] - DRIFT_HOURS[0]) * 10 + 1) / 10
    length = DRIFT_KMH * hours / max(scale, 1e-9)
    target = None
    for _ in range(12):
        angle = randbelow(3600) / 3600 * 2 * pi
        x, y = start[0] + cos(angle) * length, start[1] + sin(angle) * length
        if low_x <= x <= high_x and low_y <= y <= high_y:
            target = (x, y); break
    if target is None:   # przy krawędzi mapy — w stronę środka
        cx, cy = (low_x + high_x) / 2, (low_y + high_y) / 2
        dx, dy = cx - start[0], cy - start[1]
        distance = hypot(dx, dy) or 1
        target = (start[0] + dx / distance * length, start[1] + dy / distance * length)
    sat.from_x, sat.from_y = start
    sat.to_x, sat.to_y = target
    sat.seg_start = moment
    sat.seg_end = moment + timedelta(hours=hours)
    sat.mode = 'drift'
    sat.mission_id = None


def target_point(session, country_id):
    """Punkt nad państwem celu: stolica, a bez niej środek regionów państwa."""
    from models import Miasto, Region
    from game.military_geography import city_point, region_point
    from game.governance import controlled_ids
    for city_id in session.scalars(select(Miasto.miasto_id).where(Miasto.panstwo_id == country_id, Miasto.miasto_typ_id == 1).order_by(Miasto.miasto_id)):
        point = city_point(city_id)
        if point:
            return tuple(point)
    owners = controlled_ids(session, country_id) or [country_id]
    points = [region_point(region_id) for region_id in session.scalars(select(Region.region_id).where(Region.panstwo_id.in_(owners)))]
    points = [p for p in points if p]
    if not points:
        return None
    return (sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))


# ---------------- magazyn i liczniki ----------------

def in_stock(session, country_id):
    from game.commerce_models import ResourceStock
    row = session.get(ResourceStock, (country_id, STOCK_CODE))
    return int(row.quantity) if row else 0


def summary(session, country_id):
    """Liczby do ekranu „Siły zbrojne”: w magazynie, na orbicie i w trakcie wynoszenia."""
    data = {'stock': in_stock(session, country_id), 'orbit': 0, 'launching': 0}
    if tables_ready(session):
        for status, count in session.execute(select(SpySatellite.status, func.count()).where(SpySatellite.panstwo_id == country_id,
                                             SpySatellite.status.in_(['orbit', 'launching'])).group_by(SpySatellite.status)):
            data[status] = int(count)
    data['total'] = data['stock'] + data['orbit'] + data['launching']
    return data


def has_orbit(session, country_id, now=None):
    if not tables_ready(session):
        return False
    return session.scalar(select(SpySatellite.id).where(SpySatellite.panstwo_id == country_id, SpySatellite.status == 'orbit').limit(1)) is not None


# ---------------- rozliczenie ruchu i misji ----------------

def _notify(session, country_id, text):
    from game.paga_ai_actor import country_user_id
    from game.forum_models import GameNotification
    from game.models import utc_now
    user_id = country_user_id(session, country_id)
    if user_id is None:
        return None
    notice = GameNotification(user_id=user_id, notification_type='SYSTEM', system_text=text, created_at=utc_now())
    session.add(notice)
    session.flush()
    return notice


def settle(session, now=None, country_id=None):
    """Osiągnięcie orbity, kolejne odcinki dryfu i zakończone przeloty misji do chwili `now`."""
    if not tables_ready(session):
        return
    now = now or game_now()
    query = select(SpySatellite).where(SpySatellite.status.in_(['launching', 'orbit']))
    query = query.where(SpySatellite.seg_end <= now) if country_id is None else query.where(SpySatellite.panstwo_id == country_id)
    due = [sat for sat in session.scalars(query.order_by(SpySatellite.id).with_for_update()) if sat.seg_end <= now or sat.status == 'launching']
    if not due:
        return
    scale = km_per_unit(session)
    for sat in due:
        if sat.status == 'launching':
            if sat.orbit_at > now:
                continue
            sat.status = 'orbit'
            _drift(sat, (sat.from_x, sat.from_y), sat.orbit_at, scale)
            _notify(session, sat.panstwo_id, f'{LABEL} #{sat.id} osiągnął orbitę. Kliknij go na mapie ekranu „Wywiad wojskowy”, aby wysłać go na misję.')
        for _ in range(500):
            if sat.seg_end > now:
                break
            if sat.mode == 'mission':
                mission = session.get(SatelliteMission, sat.mission_id) if sat.mission_id else None
                if mission is not None and mission.completed_at is None:
                    complete_mission(session, mission, sat.seg_end)
            start_at = sat.seg_end if now - sat.seg_end <= timedelta(days=3) else now   # długa przerwa — dryf od teraz
            _drift(sat, (sat.to_x, sat.to_y), start_at, scale)
    session.flush()


def collect(session, mission):
    """Raport misji: obiekty wybranego rodzaju na całym terytorium państwa celu (oraz obiekty tego państwa poza nim)."""
    from models import Region, Panstwo
    from game.governance import controlled_ids
    from game.military_models import MilitaryBase, MissileDefense
    target, spy = mission.target_country_id, mission.panstwo_id
    owners = controlled_ids(session, target) or [target]
    regions = set(session.scalars(select(Region.region_id).where(Region.panstwo_id.in_(owners))))
    names = dict(session.execute(select(Panstwo.PANSTWO_ID, Panstwo.panstwo_nazwa)).all())
    key = REPORT_KEYS[mission.kind]
    report = {key: [], 'objects': [], 'entries': [], 'scope': 'country', 'country_id': target}
    ids, objects, entries = report[key], report['objects'], report['entries']

    def add(kind, obj_id, name, owner, x, y, detail, icon):
        if x is None or y is None:
            return
        ids.append(obj_id)
        suffix = '' if owner == target else f' — państwo {names.get(owner, owner)}'
        objects.append({'kind': kind, 'id': obj_id, 'name': name, 'countryId': owner, 'position': [x, y], 'detail': detail, 'icon': icon})
        entries.append({'label': name + suffix, 'value': f'{detail} Lokalizacja mapy: {x:.3f}, {y:.3f}.'})

    if mission.kind in ('bases', 'silos'):
        from game.military_service import BASES
        query = select(MilitaryBase).where((MilitaryBase.panstwo_id == target) | (MilitaryBase.region_id.in_(regions or {0})), MilitaryBase.panstwo_id != spy, MilitaryBase.health > 0)
        query = query.where(MilitaryBase.kind == 'nuclear' if mission.kind == 'silos' else MilitaryBase.kind != 'nuclear')
        icons = {'land': 'BAZA.svg', 'air': 'MYŚLIWIEC.svg', 'naval': 'OKRĘT WOJENNY.svg', 'nuclear': 'SILOS ATOMOWY.svg'}
        for base in session.scalars(query.order_by(MilitaryBase.id)):
            add('base', base.id, base.name or f'{BASES[base.kind][0]} #{base.id}', base.panstwo_id, base.map_x, base.map_y,
                f'{BASES[base.kind][0]}, poziom {base.level}.', icons.get(base.kind, 'BAZA.svg'))
    elif mission.kind == 'defenses':
        from game.missile_defense import defense_data
        query = select(MissileDefense).where((MissileDefense.panstwo_id == target) | (MissileDefense.region_id.in_(regions or {0})), MissileDefense.panstwo_id != spy, MissileDefense.health > 0)
        for defense in session.scalars(query.order_by(MissileDefense.id)):
            data = defense_data(defense)
            point = data.get('position') or [None, None]
            add('defense', defense.id, {'base': 'Obrona bazy', 'city': 'Obrona miasta', 'region': 'Obrona regionu'}.get(defense.target_kind, 'Obrona przeciwrakietowa') + f' #{defense.id}',
                defense.panstwo_id, point[0], point[1], f'Poziom {defense.level}, skuteczność {data.get("efficiency", 0)}%.', 'OBRONA PRZECIWRAKIETOWA.svg')
    elif mission.kind == 'mines':
        from game.commerce_models import Mine
        from game.mining_service import NAMES
        query = select(Mine).where((Mine.panstwo_id == target) | (Mine.region_id.in_(regions or {0})), Mine.panstwo_id != spy, Mine.removed_at.is_(None), Mine.health > 0)
        for mine in session.scalars(query.order_by(Mine.id)):
            add('mine', mine.id, f'{NAMES.get(mine.resource, "Kopalnia")} #{mine.id}', mine.panstwo_id, mine.map_x, mine.map_y, f'Poziom {mine.level}.', 'KOPALNIA.svg')
    elif mission.kind == 'power':
        from game.industry_models import PowerPlant
        from game.industry_catalog import POWER_PLANTS
        query = select(PowerPlant).where((PowerPlant.panstwo_id == target) | (PowerPlant.region_id.in_(regions or {0})), PowerPlant.panstwo_id != spy, PowerPlant.removed_at.is_(None), PowerPlant.health > 0)
        for plant in session.scalars(query.order_by(PowerPlant.id)):
            rule = POWER_PLANTS[plant.kind]
            add('power', plant.id, f'{rule["label"]} #{plant.id}', plant.panstwo_id, plant.map_x, plant.map_y, f'Poziom {plant.level}.', rule['icon'])
    if not entries:
        entries.append({'label': 'Wynik', 'value': 'Na terytorium państwa nie wykryto obiektów tego rodzaju.'})
    return report


def complete_mission(session, mission, moment):
    mission.report = collect(session, mission)
    mission.completed_at = moment
    found = len(mission.report.get('objects') or [])
    notice = _notify(session, mission.panstwo_id,
                     f'{LABEL}: {MISSIONS[mission.kind]} — państwo {mission.target_name}. Misja zakończona: wykryto {found} obiektów. '
                     'Raport jest dostępny na ekranie „Wywiad wojskowy”, a obiekty na mapach obrony, panelu wojennego i świata.')
    if notice is not None:
        mission.notification_id = notice.id


# ---------------- operacje gracza ----------------

def _request_id(data):
    try:
        return str(UUID(str(data.get('request_id'))))
    except (ValueError, TypeError, AttributeError):
        raise FinanceError('Nieprawidłowy identyfikator operacji.') from None


def launch(user_id, data):
    """Wyniesienie satelity z własnej bazy lotniczej w kraju. Zwraca (id satelity, sekundy wynoszenia)."""
    with Session(db.engine) as session, session.begin():
        country = _country_for_user(session, user_id, lock=True).PANSTWO_ID
        return launch_in_transaction(session, country, data)


def launch_in_transaction(session, country, data, now=None):
    from game.military_models import MilitaryBase
    from game.industry_service import researched, available
    from game.mining_service import stock
    from game.governance import army_for_country
    from game.base_permits import own_region_ids
    from engine.clock import get_time_multiplier
    if not tables_ready(session):
        raise FinanceError('Satelity nie są jeszcze dostępne na tym serwerze.')
    key = _request_id(data)
    existing = session.scalar(select(SpySatellite).where(SpySatellite.panstwo_id == country, SpySatellite.request_id == key))
    if existing is not None:
        return existing.id, LAUNCH_SECONDS
    from game.research_service import settle_production
    settle_production(session, country)   # satelity ukończone w fabryce do tej chwili trafiają do magazynu
    now = now or game_now()
    if not researched(session, country, TECHNOLOGY):
        raise FinanceError('Wymagana technologia: „Satelita szpiegowski”.')
    base_id = data.get('base_id')
    if type(base_id) is not int:
        raise FinanceError('Wybierz bazę lotniczą.')
    base = session.scalar(select(MilitaryBase).where(MilitaryBase.id == base_id, MilitaryBase.panstwo_id == country).with_for_update())
    if base is None or base.kind != 'air':
        raise FinanceError('Satelitę można wynieść tylko z własnej bazy lotniczej.')
    if base.map_x is None or base.health <= 0 or not base.operational:
        raise FinanceError('Baza lotnicza musi być sprawna i rozmieszczona na mapie.')
    if base.region_id not in own_region_ids(session, country):
        raise FinanceError('Satelitę można wynieść tylko z bazy lotniczej na terytorium kraju.')
    from game.land_war import require_buildable
    require_buildable(session, base.region_id, country)   # region pod okupacją — brak startów
    if in_stock(session, country) < 1:
        raise FinanceError('W magazynie nie ma satelity szpiegowskiego. Zamów jego produkcję w fabryce satelitów.')
    army = army_for_country(session, country, lock=True)
    if army is None or (getattr(army, LAUNCH_MISSILE_FIELD) or 0) < LAUNCH_MISSILES:
        raise FinanceError('Do wyniesienia satelity potrzebna jest 1 rakieta dalekiego zasięgu.')
    missing = [f'ropa naftowa (potrzeba {need}, w magazynie {available(session, country, code)})' for code, need in LAUNCH_INPUTS.items() if available(session, country, code) < need]
    if missing:
        raise FinanceError('Za mało surowców w magazynie: ' + ', '.join(missing) + '.')
    stock(session, country, STOCK_CODE).quantity -= 1
    for code, need in LAUNCH_INPUTS.items():
        stock(session, country, code).quantity -= need
    setattr(army, LAUNCH_MISSILE_FIELD, (getattr(army, LAUNCH_MISSILE_FIELD) or 0) - LAUNCH_MISSILES)
    orbit_at = now + timedelta(seconds=LAUNCH_SECONDS * max(1.0, float(get_time_multiplier() or 1)))
    sat = SpySatellite(panstwo_id=country, base_id=base.id, status='launching', mode='drift', launched_at=now, orbit_at=orbit_at,
                       from_x=base.map_x, from_y=base.map_y, to_x=base.map_x, to_y=base.map_y, seg_start=orbit_at, seg_end=orbit_at, request_id=key)
    session.add(sat)
    session.flush()
    return sat.id, LAUNCH_SECONDS


def order_mission(user_id, data):
    with Session(db.engine) as session, session.begin():
        country = _country_for_user(session, user_id, lock=True).PANSTWO_ID
        return order_mission_in_transaction(session, country, data)


def order_mission_in_transaction(session, country, data, now=None):
    from models import Panstwo
    from game.intelligence_models import IntelligenceExpense
    from game.intelligence_service import intelligence_budget
    if not tables_ready(session):
        raise FinanceError('Satelity nie są jeszcze dostępne na tym serwerze.')
    key = _request_id(data)
    payload = {k: v for k, v in data.items() if k != 'request_id'}
    payload['action'] = 'satellite_mission'
    previous = session.scalar(select(SatelliteMission).where(SatelliteMission.panstwo_id == country, SatelliteMission.request_id == key))
    if previous is not None:
        if (previous.satellite_id, previous.kind, previous.target_country_id) != (data.get('satellite_id'), data.get('kind'), data.get('country_id')):
            raise FinanceConflict('Identyfikator operacji został już użyty.')
        return previous.id
    now = now or game_now()
    settle(session, now, country)
    kind = data.get('kind')
    if kind not in MISSIONS:
        raise FinanceError('Wybierz rodzaj rozpoznania.')
    sat_id, target_id = data.get('satellite_id'), data.get('country_id')
    if type(sat_id) is not int or type(target_id) is not int:
        raise FinanceError('Wybierz satelitę i państwo.')
    sat = session.scalar(select(SpySatellite).where(SpySatellite.id == sat_id, SpySatellite.panstwo_id == country).with_for_update())
    if sat is None or sat.status != 'orbit':
        raise FinanceError('Satelita nie należy do Twojego państwa albo nie jest jeszcze na orbicie.')
    if sat.mode == 'mission':
        raise FinanceError('Satelita wykonuje już misję. Poczekaj na raport.')
    target = session.execute(select(Panstwo.PANSTWO_ID, Panstwo.panstwo_nazwa).where(Panstwo.PANSTWO_ID == target_id, Panstwo.status == 'aktywne')).first()
    if target is None or target_id == country:
        raise FinanceError('Wybierz inne istniejące państwo.')
    point = target_point(session, target_id)
    if point is None:
        raise FinanceError('Państwo nie ma terytorium na mapie.')
    budget, _total, free = intelligence_budget(session, country, now)
    if budget is None or free < MISSION_COST:
        raise FinanceError('Za mało środków w budżecie służb specjalnych i porządkowych na bieżący okres budżetowy (potrzeba 120 mln ROI).')
    if session.scalar(select(IntelligenceExpense.id).where(IntelligenceExpense.panstwo_id == country, IntelligenceExpense.request_id == key)) is not None:
        raise FinanceConflict('Identyfikator operacji został już użyty.')
    start = position(sat, now)
    hours = hypot(point[0] - start[0], point[1] - start[1]) * km_per_unit(session) / mission_speed(sat.level)
    arrives = now + timedelta(hours=max(hours, 1 / 60))
    mission = SatelliteMission(panstwo_id=country, satellite_id=sat.id, kind=kind, target_country_id=target_id, target_name=target.panstwo_nazwa,
                               cost=MISSION_COST, starts_at=now, arrives_at=arrives, request_id=key)
    session.add(mission)
    session.add(IntelligenceExpense(panstwo_id=country, budget_id=budget.id, amount=MISSION_COST, request_id=key, payload=payload))
    session.flush()
    sat.from_x, sat.from_y = start
    sat.to_x, sat.to_y = point
    sat.seg_start, sat.seg_end = now, arrives
    sat.mode, sat.mission_id = 'mission', mission.id
    session.flush()
    return mission.id


def _own_satellite(session, country, data):
    sat_id = data.get('satellite_id')
    if type(sat_id) is not int:
        raise FinanceError('Wybierz satelitę.')
    sat = session.scalar(select(SpySatellite).where(SpySatellite.id == sat_id, SpySatellite.panstwo_id == country).with_for_update())
    if sat is None or sat.status != 'orbit':
        raise FinanceError('Satelita nie należy do Twojego państwa albo nie jest jeszcze na orbicie.')
    return sat


def upgrade(user_id, data):
    with Session(db.engine) as session, session.begin():
        country = _country_for_user(session, user_id, lock=True).PANSTWO_ID
        return upgrade_in_transaction(session, country, data)


def upgrade_in_transaction(session, country, data, now=None):
    """Rozbudowa satelity o jeden poziom (szybszy przelot w misji); koszt z budżetu służb specjalnych i porządkowych."""
    from game.intelligence_models import IntelligenceExpense
    from game.intelligence_service import intelligence_budget
    if not tables_ready(session):
        raise FinanceError('Satelity nie są jeszcze dostępne na tym serwerze.')
    key = _request_id(data)
    payload = {k: v for k, v in data.items() if k != 'request_id'}
    payload['action'] = 'satellite_upgrade'
    previous = session.scalar(select(IntelligenceExpense).where(IntelligenceExpense.panstwo_id == country, IntelligenceExpense.request_id == key))
    if previous is not None:
        if previous.payload != payload:
            raise FinanceConflict('Identyfikator operacji został już użyty.')
        return session.get(SpySatellite, data.get('satellite_id')).level
    now = now or game_now()
    settle(session, now, country)
    sat = _own_satellite(session, country, data)
    if sat.mode == 'mission':
        raise FinanceError('Satelitę można rozbudować tylko wtedy, gdy nie wykonuje misji.')
    if sat.level >= MAX_LEVEL:
        raise FinanceError(f'Satelita ma już najwyższy poziom ({MAX_LEVEL}).')
    if data.get('expected_level') != sat.level:
        raise FinanceConflict('Poziom satelity zmienił się. Odśwież ekran.')
    cost = LEVELS[sat.level + 1][1]
    budget, _total, free = intelligence_budget(session, country, now)
    if budget is None or free < cost:
        raise FinanceError(f'Za mało środków w budżecie służb specjalnych i porządkowych (potrzeba {cost / Decimal(1000000000):.1f} mld ROI).'.replace('.', ','))
    session.add(IntelligenceExpense(panstwo_id=country, budget_id=budget.id, amount=cost, request_id=key, payload=payload))
    sat.level += 1
    session.flush()
    return sat.level


def cancel_mission(user_id, data):
    with Session(db.engine) as session, session.begin():
        country = _country_for_user(session, user_id, lock=True).PANSTWO_ID
        return cancel_mission_in_transaction(session, country, data)


def cancel_mission_in_transaction(session, country, data, now=None):
    """Anulowanie misji: koszt nie jest zwracany, satelita wraca do swobodnego dryfu z bieżącego miejsca."""
    if not tables_ready(session):
        raise FinanceError('Satelity nie są jeszcze dostępne na tym serwerze.')
    now = now or game_now()
    settle(session, now, country)
    sat = _own_satellite(session, country, data)
    if sat.mode != 'mission':
        raise FinanceError('Satelita nie wykonuje misji.')
    mission = session.get(SatelliteMission, sat.mission_id) if sat.mission_id else None
    if mission is not None and mission.completed_at is None:
        mission.completed_at = now
        mission.report = {'cancelled': True, 'entries': [{'label': 'Wynik', 'value': 'Misja anulowana przed dotarciem nad cel. Koszt użycia satelity nie jest zwracany.'}]}
    _drift(sat, position(sat, now), now, km_per_unit(session))
    session.flush()
    return sat.id


# ---------------- dane dla map i ekranów ----------------

def _iso(moment):
    return moment.isoformat() + 'Z' if moment else None


def visible(session, viewer, now=None):
    """Satelity na mapach: własne zawsze; obce tylko dla państwa z własnym satelitą na orbicie."""
    if not tables_ready(session) or viewer is None:
        return []
    from flask import url_for
    from models import Panstwo
    now = now or game_now()
    query = select(SpySatellite).where(SpySatellite.status.in_(['orbit', 'launching']))
    if not has_orbit(session, viewer):
        query = query.where(SpySatellite.panstwo_id == viewer)
    rows = list(session.scalars(query.order_by(SpySatellite.id)))
    names = dict(session.execute(select(Panstwo.PANSTWO_ID, Panstwo.panstwo_nazwa)).all())
    missions = {m.id: m for m in session.scalars(select(SatelliteMission).where(SatelliteMission.id.in_([r.mission_id for r in rows if r.mission_id] or [0])))}
    items = []
    for sat in rows:
        own = sat.panstwo_id == viewer
        if not own and sat.status != 'orbit':
            continue
        name = names.get(sat.panstwo_id) or ''
        item = {'id': sat.id, 'countryId': sat.panstwo_id, 'country': name, 'own': own, 'status': sat.status, 'mode': sat.mode,
                'name': f'{LABEL} #{sat.id}', 'flag': url_for('static', filename='flags/' + name.replace(' ', '_') + '.jpg'),
                'from': [sat.from_x, sat.from_y], 'to': [sat.to_x, sat.to_y], 'segStart': _iso(sat.seg_start), 'segEnd': _iso(sat.seg_end),
                'orbitAt': _iso(sat.orbit_at), 'position': list(position(sat, now)), 'level': sat.level, 'speed': mission_speed(sat.level)}
        mission = missions.get(sat.mission_id)
        if own and mission is not None:
            item['mission'] = {'id': mission.id, 'kind': mission.kind, 'label': MISSIONS[mission.kind], 'target': mission.target_name, 'arrivesAt': _iso(mission.arrives_at)}
        items.append(item)
    return items


def intel_objects(session, viewer):
    """Obiekty rozpoznane przez satelity państwa (najnowsza obserwacja każdego obiektu)."""
    if not tables_ready(session) or viewer is None:
        return []
    from flask import url_for
    from models import Panstwo
    names = dict(session.execute(select(Panstwo.PANSTWO_ID, Panstwo.panstwo_nazwa)).all())
    latest = {}
    for mission in session.scalars(select(SatelliteMission).where(SatelliteMission.panstwo_id == viewer, SatelliteMission.completed_at.is_not(None)).order_by(SatelliteMission.completed_at)):
        for obj in (mission.report or {}).get('objects') or []:
            name = names.get(obj.get('countryId')) or ''
            latest[(obj['kind'], obj['id'])] = {**obj, 'icon': url_for('static', filename='icons/' + obj.get('icon', 'BAZA.svg')),
                                                'country': name, 'flag': url_for('static', filename='flags/' + name.replace(' ', '_') + '.jpg'),
                                                'observedAt': mission.completed_at.strftime('%d.%m.%Y'), 'mission': MISSIONS[mission.kind]}
    return list(latest.values())


def mission_list(session, viewer, limit=50):
    if not tables_ready(session) or viewer is None:
        return []
    rows = session.scalars(select(SatelliteMission).where(SatelliteMission.panstwo_id == viewer).order_by(SatelliteMission.id.desc()).limit(limit))
    return [{'id': m.id, 'satelliteId': m.satellite_id, 'kind': m.kind, 'label': MISSIONS[m.kind], 'country': m.target_name, 'countryId': m.target_country_id,
             'startsAt': _iso(m.starts_at), 'arrivesAt': _iso(m.arrives_at), 'completed': m.completed_at is not None,
             'cancelled': bool((m.report or {}).get('cancelled')), 'endedAt': _iso(m.completed_at),
             'entries': (m.report or {}).get('entries', []) if m.completed_at else []} for m in rows]


def known_report_ids(session, country_id, kinds, key):
    """Identyfikatory obiektów z raportów satelitarnych (dla game.intelligence_service.known_ids)."""
    if not tables_ready(session):
        return set()
    return {int(i) for report in session.scalars(select(SatelliteMission.report).where(SatelliteMission.panstwo_id == country_id, SatelliteMission.kind.in_(kinds),
                                                                                       SatelliteMission.completed_at.is_not(None)))
            for i in (report or {}).get(key, [])}


def target_countries(session, viewer):
    """Państwa, które można szpiegować (aktywne, inne niż własne), z punktem nad ich terytorium."""
    from models import Panstwo
    if viewer is None:
        return []
    rows = session.execute(select(Panstwo.PANSTWO_ID, Panstwo.panstwo_nazwa).where(Panstwo.status == 'aktywne', Panstwo.PANSTWO_ID != viewer).order_by(Panstwo.panstwo_nazwa))
    items = []
    for country_id, name in rows:
        point = target_point(session, country_id)
        if point is not None:
            items.append({'id': country_id, 'name': name, 'point': list(point)})
    return items


def screen_config(session, viewer, now=None):
    """Wspólna konfiguracja warstwy satelitów (game_satellites.js)."""
    from flask import url_for
    from engine.clock import get_time_multiplier
    now = now or game_now()
    icon = lambda name: url_for('static', filename='icons/' + name)
    try:
        scale = km_per_unit(session)
    except FinanceError:
        scale = 1
    return {'enabled': tables_ready(session), 'countryId': viewer, 'satellites': visible(session, viewer, now), 'intel': intel_objects(session, viewer),
            'hasOrbit': has_orbit(session, viewer) if viewer else False, 'gameNow': _iso(now), 'timeMultiplier': get_time_multiplier(), 'kmPerUnit': scale,
            'icon': icon(ICON), 'flightIcon': icon(FLIGHT_ICON), 'launchIcon': icon(LAUNCH_ICON),
            'missions': [{'code': code, 'label': label, 'icon': icon(MISSION_ICONS[code])} for code, label in MISSIONS.items()],
            'missionCost': str(MISSION_COST), 'speeds': {'drift': DRIFT_KMH, 'mission': MISSION_KMH}, 'launchSeconds': LAUNCH_SECONDS,
            'levels': {str(level): {'speed': speed, 'cost': str(cost)} for level, (speed, cost) in LEVELS.items()}, 'maxLevel': MAX_LEVEL,
            'upgradeIcon': icon('ROZBUDUJ.svg'), 'cancelIcon': icon('WYCOFAJ.svg'),
            'upgradeUrl': url_for('game_satellites.upgrade_view'), 'cancelUrl': url_for('game_satellites.cancel_view'),
            'countries': target_countries(session, viewer),
            'stateUrl': url_for('game_satellites.state'), 'launchUrl': url_for('game_satellites.launch_view'), 'missionUrl': url_for('game_satellites.mission_view')}
