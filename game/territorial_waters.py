"""Wody terytorialne (UAT, 15 Nov 2026).

* Każde państwo ma wody terytorialne: pas wody o szerokości 100 km od wybrzeża.
* Pas dzielony jest między regiony linią środkową (każdy punkt wody należy do regionu o najbliższym brzegu),
  więc wody sąsiadów nie nakładają się, a po aneksji regionu jego wody przechodzą razem z nim.
* Wody państwa = wody regionów, które kontroluje (państwo zależne liczy się do zwierzchnika, jak na mapie świata).
* Wejście okrętu obcego państwa w wody terytorialne daje jedno powiadomienie dla państwa wód na rejs (na razie bez konsekwencji);
  kolejny rejs przez te same wody to nowe powiadomienie.
  Momenty wejść liczone są z trasy rejsu, więc szybki przelot między odczytami harmonogramu nie umyka.
"""
import json
from functools import lru_cache
from hashlib import sha1
from pathlib import Path
import numpy as np
import shapely
from shapely.geometry import Polygon, shape, mapping
from sqlalchemy import select
from game.military_geography import MAP_PATH

WATERS_KM = 100
CACHE_DIR = Path(__file__).resolve().parents[1] / 'runtime' / 'territorial_waters'
SAMPLE_UNITS = 2.0                     # gęstość punktów brzegu do podziału linią środkową (jednostki mapy)
DISPLAY_TOLERANCE = 0.3                # uproszczenie geometrii wysyłanej na mapę (jednostki mapy)
VESSEL_LABELS = {'warships': 'Okręt wojenny', 'submarines': 'Okręt podwodny', 'carriers': 'Lotniskowiec'}
UNKNOWN_REGION = -1


def _filled(geometry):
    """Ląd bez dziur (jeziora śródlądowe nie są dostępne dla okrętów, jak w nawigacji morskiej)."""
    polygons = []
    for part in shapely.get_parts(geometry):
        if part.geom_type == 'Polygon':
            polygons.append(Polygon(part.exterior))
        elif hasattr(part, 'geoms'):
            polygons.extend(Polygon(child.exterior) for child in part.geoms if child.geom_type == 'Polygon')
    return shapely.union_all(polygons)


def compute_region_waters(features, distance):
    """{region_id: wody regionu} dla pasa `distance` jednostek mapy od lądu, podzielonego linią środkową."""
    regions = {}
    for feature in features:
        if not feature.get('geometry'):
            continue
        region_id = (feature.get('properties') or {}).get('region_id')
        regions.setdefault(UNKNOWN_REGION if region_id is None else int(region_id), []).append(shapely.make_valid(shape(feature['geometry'])))
    regions = {id: shapely.union_all(parts) for id, parts in regions.items()}
    land = _filled(shapely.union_all(list(regions.values())))
    water = shapely.difference(shapely.buffer(land, distance), land)
    points, labels = [], []
    for id, geometry in regions.items():
        coordinates = shapely.get_coordinates(shapely.segmentize(shapely.boundary(geometry), SAMPLE_UNITS))
        points.append(coordinates)
        labels.extend([id] * len(coordinates))
    points = np.vstack(points)
    labels = np.array(labels)
    _, keep = np.unique(np.round(points, 6), axis=0, return_index=True)   # wspólne granice regionów dają powtórzone punkty
    keep.sort()
    points, labels = points[keep], labels[keep]
    cells = shapely.get_parts(shapely.voronoi_polygons(shapely.MultiPoint(points), extend_to=shapely.buffer(land, distance * 2).envelope, ordered=True))
    result = {}
    for id in regions:
        if id == UNKNOWN_REGION:
            continue                    # ląd bez regionu nie ma właściciela; jego wody zostają niczyje
        zone = shapely.intersection(shapely.union_all(cells[labels == id]), water)
        if not zone.is_empty:
            result[id] = zone
    return result


@lru_cache(maxsize=2)
def _region_waters(modified, km_per_unit):
    """Wody regionów z pamięci podręcznej na dysku (liczenie trwa kilka sekund), unieważnianej zmianą mapy lub skali."""
    key = sha1(f'{modified}:{km_per_unit:.12f}:{WATERS_KM}:{SAMPLE_UNITS}'.encode()).hexdigest()[:16]
    path = CACHE_DIR / f'regions-{key}.json'
    if path.is_file():
        try:
            return {int(id): shapely.from_wkb(bytes.fromhex(value)) for id, value in json.loads(path.read_text()).items()}
        except (ValueError, OSError, shapely.errors.GEOSException):
            pass
    waters = compute_region_waters(json.loads(MAP_PATH.read_text())['features'], WATERS_KM / km_per_unit)
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps({str(id): shapely.to_wkb(geometry, hex=True) for id, geometry in waters.items()}))
        temporary.replace(path)
    except OSError:
        pass
    return waters


def region_waters(session):
    from game.military_flights import calibration
    return _region_waters(MAP_PATH.stat().st_mtime_ns, float(calibration(session).km_per_unit))


def region_owners(session):
    """{region_id: państwo kontrolujące} — właściciel regionu albo jego zwierzchnik."""
    from game.governance import controllers
    from models import Region
    mapping_ = controllers(session)
    return {region_id: mapping_.get(country_id) for region_id, country_id in session.execute(select(Region.region_id, Region.panstwo_id))
            if country_id is not None and mapping_.get(country_id) is not None}


@lru_cache(maxsize=4)
def _country_waters(regions_key, owners):
    regions = _region_waters(*regions_key)
    groups = {}
    for region_id, country_id in owners:
        if region_id in regions:
            groups.setdefault(country_id, []).append(regions[region_id])
    zones = {country_id: shapely.union_all(parts) for country_id, parts in groups.items()}
    for zone in zones.values():
        shapely.prepare(zone)
    return zones


def country_waters(session):
    """{państwo: wody terytorialne} według bieżącej własności regionów."""
    from game.military_flights import calibration
    regions_key = (MAP_PATH.stat().st_mtime_ns, float(calibration(session).km_per_unit))
    return _country_waters(regions_key, tuple(sorted(region_owners(session).items())))


def waters_geojson(session):
    """Wody terytorialne państw do mapy świata (uproszczone)."""
    features = []
    for country_id, zone in sorted(country_waters(session).items()):
        simple = shapely.set_precision(shapely.simplify(zone, DISPLAY_TOLERANCE), 0.01)
        if not simple.is_empty:
            features.append({'type': 'Feature', 'properties': {'panstwo_id': country_id}, 'geometry': mapping(simple)})
    return {'type': 'FeatureCollection', 'features': features}


def waters_owner_at(session, point):
    """Państwo, do którego wód terytorialnych należy punkt (albo None: morze otwarte lub ląd)."""
    p = shapely.Point(point)
    for country_id, zone in country_waters(session).items():
        if zone.covers(p):
            return country_id
    return None


# ---------------- wejścia obcych okrętów ----------------

def entries(route, zones, skip_country=None):
    """Wejścia trasy w strefy: [(country_id, entry_no, fraction, point)] w kolejności trasy.
    Trasa zaczynająca się w strefie nie jest wejściem (okręt już tam był, np. po zmianie kursu)."""
    if not route or len(route) < 2:
        return []
    line = shapely.LineString(route)
    length = line.length
    if length <= 0:
        return []
    found = []
    for country_id, zone in zones.items():
        if country_id == skip_country or not shapely.intersects(zone, line):
            continue
        pieces = [piece for piece in shapely.get_parts(shapely.intersection(line, zone)) if piece.geom_type in ('LineString', 'Point') and not piece.is_empty]
        starts = sorted({round(line.project(shapely.Point(piece.coords[0])), 9) for piece in pieces})
        number = 0
        for distance in starts:
            if distance <= 1e-6:
                continue
            number += 1
            point = line.interpolate(distance)
            found.append((country_id, number, distance / length, [point.x, point.y]))
    return sorted(found, key=lambda item: item[2])


def detect_incursions(session, now=None, docked_lookback=None):
    """Jedno powiadomienie dla państwa wód przy każdym wejściu obcego okrętu (wywoływane przez harmonogram)."""
    from datetime import timedelta
    from game.finance_service import game_now, FinanceError
    from game.governance import controllers
    from game.land_war import notify, names
    from game.military_models import MilitaryVessel
    from game.military_navy import vessel_route
    from game.territorial_waters_models import TerritorialIncursion
    now = now or game_now()
    docked_since = now - (docked_lookback or timedelta(days=2))   # rejsy zakończone w porcie tuż przed odczytem
    vessels = list(session.scalars(select(MilitaryVessel).where(MilitaryVessel.health > 0, MilitaryVessel.starts_at <= now,
                   (MilitaryVessel.status.in_(['sailing', 'returning', 'stationed'])) |
                   ((MilitaryVessel.status == 'docked') & (MilitaryVessel.arrives_at >= docked_since)))))
    if not vessels:
        return 0
    try:
        zones = country_waters(session)
    except FinanceError:
        return 0                        # skala mapy nie jest skonfigurowana
    owners = controllers(session)
    # Harmonogram działa w każdym workerze aplikacji: blokada wiersza skali mapy szereguje wykrywanie,
    # więc drugi worker widzi wejścia zapisane przez pierwszy (bez powtórnych powiadomień).
    from game.military_models import MapCalibration
    session.execute(select(MapCalibration.id).where(MapCalibration.id == 1).with_for_update())
    done = set(session.execute(select(TerritorialIncursion.vessel_id, TerritorialIncursion.voyage_started_at, TerritorialIncursion.waters_country_id,
                                      TerritorialIncursion.entry_no).where(TerritorialIncursion.vessel_id.in_([v.id for v in vessels]))).tuples())
    created = 0
    for vessel in vessels:
        own = owners.get(vessel.panstwo_id, vessel.panstwo_id)
        try:
            route = vessel_route(vessel)
        except FinanceError:
            continue
        span = (vessel.arrives_at - vessel.starts_at).total_seconds()
        for country_id, number, fraction, point in entries(route, zones, skip_country=own):
            if number > 1:
                continue                # jedno powiadomienie na rejs i państwo (trasa wzdłuż wybrzeża wchodzi w wody wiele razy)
            moment = vessel.starts_at + timedelta(seconds=span * fraction)
            if moment > now or (vessel.id, vessel.starts_at, country_id, number) in done:
                continue
            session.add(TerritorialIncursion(vessel_id=vessel.id, vessel_country_id=vessel.panstwo_id, waters_country_id=country_id,
                                             voyage_started_at=vessel.starts_at, entry_no=number, entered_at=moment, point_x=point[0], point_y=point[1]))
            who = names(session, vessel.panstwo_id).get(vessel.panstwo_id, 'obcego państwa')
            label = VESSEL_LABELS.get(vessel.kind, 'Okręt')
            notify(session, country_id, f'Wody terytorialne: {label} państwa {who} wpłynął na nasze wody terytorialne '
                                        f'({moment:%Y-%m-%d %H:%M} czasu Entendy). Na razie bez konsekwencji.')
            done.add((vessel.id, vessel.starts_at, country_id, number))
            created += 1
    session.flush()
    return created
