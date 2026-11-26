"""Droga przemarszu wojsk lądowych (26 Nov 2026).

Armia nie idzie w linii prostej: maszeruje po lądzie i omija akweny (zatoki, jeziora, cieśniny), wybierając najkrótszą
drogę lądową (wyszukiwanie A* na siatce, jak tory kolejowe — game.rail.land_path). Wolno jej iść wyłącznie przez terytoria
stron wojny: własne, państwa trzymającego cel, właściciela celu (odbicie, wyzwolenie), państw, z którymi trwa nasza wojna,
oraz sojuszników walczących z państwem trzymającym cel; a także przez ziemie niczyje. Terytorium państwa, które nie bierze
czynnego udziału w wojnie, jest dla armii zamknięte. Region okupowany należy do okupanta.

Najpierw sprawdzany jest odcinek prosty (szybko); dopiero gdy przecina wodę albo zamknięte terytorium — szukana jest droga
okrężna. Trasa jest zapisywana w armii (LandArmy.route): po niej liczone są pozycja, czas marszu i wejście na terytorium celu.
"""
import threading
from math import hypot
from sqlalchemy import select
from game.finance_service import FinanceError

ENDPOINT_KM = 4      # bazy morskie i miasta portowe leżą w pasie przybrzeżnym (do 4 km od lądu)
SEAM_KM = .5         # domknięcie szczelin między wielokątami sąsiednich regionów
NO_ROUTE = ('Armia lądowa nie dotrze do celu: brak drogi lądowej — na drodze jest morze albo terytorium państwa, '
            'które nie bierze udziału w wojnie. Wybierz cel osiągalny drogą lądową.')
_LOCAL = threading.local()   # przygotowane geometrie GEOS nie są współdzielone między wątkami


def participants(session, own, holder, owner=None):
    """Państwa, przez których terytorium może przejść armia `own` maszerująca na obiekt trzymany przez `holder`."""
    from game.military_service import enemies
    from game.trade_diplomacy import allied_country_ids
    from game.governance import controller_id
    sides = {own, holder, owner} | set(enemies(session, own))
    for ally in allied_country_ids(session, own):
        root = controller_id(session, ally)
        if root is not None and root not in sides and holder in enemies(session, root):
            sides.add(root)
    sides.discard(None)
    return sides


def holders(session):
    """region_id → państwo, które faktycznie trzyma region (okupant albo suweren właściciela); None — ziemia niczyja."""
    from models import Region
    from game.governance import controllers
    from game.land_war_models import Occupation
    mapping = controllers(session)
    result = {rid: (mapping.get(owner) if owner is not None else None)
              for rid, owner in session.execute(select(Region.region_id, Region.panstwo_id))}
    for rid, occupier in session.execute(select(Occupation.region_id, Occupation.occupier_id).where(
            Occupation.kind == 'region', Occupation.status == 'ACTIVE').order_by(Occupation.id)):
        result[rid] = occupier
    return result


def territory(session, sides, km_per_unit, points=()):
    """Ląd dostępny dla armii: regiony trzymane przez strony wojny, ziemie niczyje oraz regiony punktów `points`
    (baza startowa i cel zawsze należą do trasy). Geometria w pamięci podręcznej wątku wg zestawu regionów."""
    import shapely
    from shapely.geometry import shape
    from shapely.ops import unary_union
    from game.military_geography import MAP_PATH, map_features
    from game.land_war import region_at
    allowed = {rid for rid, holder in holders(session).items() if holder is None or holder in sides}
    for point in points:
        region = region_at(point[0], point[1])
        if region is not None:
            allowed.add(region)
    key = (MAP_PATH.stat().st_mtime_ns, round(km_per_unit, 9), frozenset(allowed))
    cache = getattr(_LOCAL, 'land', None)
    if cache is None:
        cache = _LOCAL.land = {}
    land = cache.get(key)
    if land is None:
        parts = []
        for feature in map_features(MAP_PATH):
            region = (feature.get('properties') or {}).get('region_id')
            if feature.get('geometry') and (region is None or region in allowed):
                parts.append(shape(feature['geometry']).buffer(0))
        land = unary_union(parts).buffer(SEAM_KM / km_per_unit) if parts else unary_union([])
        shapely.prepare(land)
        if len(cache) > 12:
            cache.clear()
        cache[key] = land
    return land


def straight(land, source, target, km_per_unit):
    """Czy odcinek prosty biegnie wyłącznie po dostępnym lądzie (końce mogą leżeć w pasie przybrzeżnym)."""
    from shapely.geometry import LineString, Point
    line = LineString([tuple(source), tuple(target)])
    radius = ENDPOINT_KM / km_per_unit
    line = line.difference(Point(tuple(source)).buffer(radius)).difference(Point(tuple(target)).buffer(radius))
    return line.is_empty or bool(land.covers(line))


def route(session, source, target, sides, km_per_unit=None):
    """Droga przemarszu [[x, y], …] z `source` do `target` przez terytoria `sides`; None — cel nieosiągalny lądem."""
    from game.military_flights import calibration
    from game.rail import land_path
    source, target = [float(source[0]), float(source[1])], [float(target[0]), float(target[1])]
    if hypot(target[0] - source[0], target[1] - source[1]) < 1e-9:
        return [source, target]
    km_per_unit = km_per_unit or calibration(session).km_per_unit
    land = territory(session, sides, km_per_unit, (source, target))
    if land.is_empty:
        return None
    if straight(land, source, target, km_per_unit):
        return [source, target]
    # Końce poza lądem (pas przybrzeżny): wyszukiwanie zaczyna się od najbliższego punktu lądu.
    a, b = ashore(land, source, km_per_unit), ashore(land, target, km_per_unit)
    if a is None or b is None:
        return None
    try:
        path = land_path([], a, b, land=land)
    except FinanceError:
        return None
    path = [list(p) for p in path]
    path[0], path[-1] = a, b
    if a != source:
        path.insert(0, source)
    if b != target:
        path.append(target)
    return path


def ashore(land, point, km_per_unit):
    """Punkt na lądzie dla końca trasy: on sam albo najbliższy punkt lądu w pasie przybrzeżnym; None — za daleko od lądu."""
    from shapely.geometry import Point
    from shapely.ops import nearest_points
    if land.covers(Point(point)):
        return list(point)
    near = nearest_points(land, Point(point))[0]
    if hypot(near.x - point[0], near.y - point[1]) * km_per_unit > ENDPOINT_KM:
        return None
    return [near.x, near.y]


def require_route(session, source, target, sides):
    path = route(session, source, target, sides)
    if path is None:
        raise FinanceError(NO_ROUTE)
    return path


def length(path):
    return sum(hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(path, path[1:]))
