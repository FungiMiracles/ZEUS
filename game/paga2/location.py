"""Wybór lokalizacji obiektów PAGA2.

- kopalnie: wyłącznie regiony ze złożem danego surowca,
- stocznie (i w przyszłości bazy morskie): pas do 3 km od wybrzeża regionu nadmorskiego,
- pozostałe obiekty: region z najmniejszą liczbą własnych obiektów (lub wskazany), punkt losowy w jego granicach,
- unikanie kolizji: minimalny odstęp od wszystkich własnych obiektów na mapie.
"""
from hashlib import sha256
from random import Random
from game.military_geography import MAP_PATH,map_features,polygons,contains_point,coastline_segments,segment_distance

MIN_DISTANCE_KM=15.0
ATTEMPTS=400


def _geometry(region):
    for feature in map_features(MAP_PATH):
        if feature.get('properties',{}).get('region_id')==region:return feature.get('geometry') or {}
    return None


def _bounds(geometry):
    xs=[p[0] for rings in polygons(geometry) for p in rings[0]];ys=[p[1] for rings in polygons(geometry) for p in rings[0]]
    return (min(xs),min(ys),max(xs),max(ys)) if xs else None


def far_enough(point,occupied,km_per_unit,minimum=MIN_DISTANCE_KM):
    return all(((point[0]-x)**2+(point[1]-y)**2)**.5*km_per_unit>=minimum for x,y in occupied)


def pick_point(region,occupied,km_per_unit,*,seed,coastal=False,minimum=MIN_DISTANCE_KM):
    """Punkt wewnątrz regionu, z dala od innych obiektów; dla coastal=True w pasie 3 km od wybrzeża. None, gdy brak miejsca."""
    geometry=_geometry(region)
    if not geometry or not km_per_unit:return None
    rng=Random(int(sha256(str(seed).encode()).hexdigest()[:16],16))
    if coastal:
        segments=coastline_segments(region)
        if not segments:return None
        for _ in range(ATTEMPTS):
            a,b=rng.choice(segments);t=rng.random()
            base=(a[0]+t*(b[0]-a[0]),a[1]+t*(b[1]-a[1]))
            # odsunięcie w głąb lądu o najwyżej ~2 km
            offset=2.0/km_per_unit
            for dx,dy in ((0,0),(offset,0),(-offset,0),(0,offset),(0,-offset),(offset/2,offset/2),(-offset/2,-offset/2)):
                point=(base[0]+dx,base[1]+dy)
                if contains_point(geometry,point) and min(segment_distance(point,p,q) for p,q in segments)*km_per_unit<=3.0 and far_enough(point,occupied,km_per_unit,minimum):
                    return [point[0],point[1]]
        return None
    bounds=_bounds(geometry)
    if bounds is None:return None
    x0,y0,x1,y1=bounds
    for attempt in range(ATTEMPTS):
        point=(rng.uniform(x0,x1),rng.uniform(y0,y1))
        # przy braku miejsca stopniowo zmniejszamy wymagany odstęp
        need=minimum if attempt<ATTEMPTS*3//4 else minimum/3
        if contains_point(geometry,point) and far_enough(point,occupied,km_per_unit,need):return [point[0],point[1]]
    return None


def choose_region(holdings,candidates,*,seed):
    """Region o najmniejszej liczbie własnych obiektów (równomierne rozmieszczenie); remis rozstrzyga stałe ziarno."""
    candidates=[r for r in candidates if any(own['id']==r for own in holdings.regions)]
    if not candidates:return None
    rng=Random(int(sha256(str(seed).encode()).hexdigest()[:16],16))
    order={r:rng.random() for r in candidates}
    return min(candidates,key=lambda r:(holdings.objects_in(r),order[r]))


def site(holdings,km_per_unit,*,seed,regions=None,coastal=False):
    """(region, [x, y]) albo (None, powód)."""
    pool=list(regions) if regions is not None else [r['id'] for r in holdings.regions]
    if coastal:pool=[r for r in pool if r in holdings.coastal_regions()]
    if not pool:return None,'Brak odpowiedniego własnego regionu (nadmorskiego lub ze złożem, nieokupowanego).'
    tried=set()
    while len(tried)<len(pool):
        region=choose_region(holdings,[r for r in pool if r not in tried],seed=f'{seed}:{len(tried)}')
        tried.add(region)
        point=pick_point(region,holdings.objects,km_per_unit,seed=f'{seed}:{region}',coastal=coastal)
        if point:return region,point
    return None,'Nie znaleziono wolnego miejsca w odpowiednich regionach (kolizje z innymi obiektami).'
