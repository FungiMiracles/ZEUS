"""Sąsiedztwo regionów z dodatniej długości wspólnej granicy mapy."""
import json
import math
from functools import lru_cache
from pathlib import Path

MAP_PATH = Path(__file__).resolve().parents[1] / 'static/maps/entenda_regiony.geojson'


def adjacency(features):
    lines = {}
    neighbors = {}
    for feature in features:
        region_id = feature.get('properties',{}).get('region_id')
        if region_id is None:
            continue
        region_id = int(region_id)
        neighbors.setdefault(region_id,set())
        geometry = feature.get('geometry') or {}
        polygons = [geometry['coordinates']] if geometry.get('type') == 'Polygon' else geometry.get('coordinates',[]) if geometry.get('type') == 'MultiPolygon' else []
        for polygon in polygons:
            for ring in polygon:
                for a,b in zip(ring,ring[1:]):
                    dx,dy = b[0]-a[0],b[1]-a[1]
                    length = math.hypot(dx,dy)
                    if length < 1e-8:
                        continue
                    nx,ny = dy/length,-dx/length
                    if nx < -1e-9 or abs(nx) < 1e-9 and ny < 0:
                        nx,ny = -nx,-ny
                    key = (round(nx,7),round(ny,7),round(nx*a[0]+ny*a[1],5))
                    axis = 0 if abs(dx) >= abs(dy) else 1
                    low,high = sorted((a[axis],b[axis]))
                    lines.setdefault((key,axis),[]).append((low,high,region_id))
    for segments in lines.values():
        segments.sort()
        active = []
        for low,high,region in segments:
            active = [segment for segment in active if segment[1] > low + 1e-6]
            for old_low,old_high,other in active:
                if other != region and min(high,old_high)-max(low,old_low) > 1e-6:
                    neighbors[region].add(other)
                    neighbors[other].add(region)
            active.append((low,high,region))
    return neighbors


@lru_cache(maxsize=2)
def _cached_adjacency(modified):
    return adjacency(json.loads(MAP_PATH.read_text())['features'])


def region_adjacency():
    return _cached_adjacency(MAP_PATH.stat().st_mtime_ns)


CITIES_PATH = MAP_PATH.with_name('entenda_miasta.geojson')


@lru_cache(maxsize=4)
def _map_data(path,modified):
    return json.loads(Path(path).read_text())['features']


def map_features(path):
    return _map_data(str(path),path.stat().st_mtime_ns)


@lru_cache(maxsize=2)
def _city_points(modified):
    return {int(feature['properties']['miasto_id']):feature['geometry']['coordinates'][:2]
            for feature in map_features(CITIES_PATH) if (feature.get('geometry') or {}).get('type')=='Point' and feature.get('properties',{}).get('miasto_id') is not None}


def city_point(city_id):
    return _city_points(CITIES_PATH.stat().st_mtime_ns).get(city_id)


def _ring_position(point,ring):
    x,y = point
    inside = False
    for a,b in zip(ring,ring[1:]):
        dx,dy=b[0]-a[0],b[1]-a[1]
        cross=(x-a[0])*dy-(y-a[1])*dx
        if abs(cross) <= 1e-7*max(1,math.hypot(dx,dy)) and min(a[0],b[0])-1e-8<=x<=max(a[0],b[0])+1e-8 and min(a[1],b[1])-1e-8<=y<=max(a[1],b[1])+1e-8:
            return 2
        if (a[1]>y)!=(b[1]>y) and x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]:
            inside=not inside
    return int(inside)


def polygons(geometry):
    if geometry.get('type')=='Polygon':return [geometry['coordinates']]
    if geometry.get('type')=='MultiPolygon':return geometry['coordinates']
    return []


def contains_point(geometry,point):
    return any(_ring_position(point,rings[0]) and not any(_ring_position(point,hole) for hole in rings[1:]) for rings in polygons(geometry) if rings)


def region_contains(region_id,x,y):
    return any(feature.get('properties',{}).get('region_id')==region_id and contains_point(feature.get('geometry') or {},(x,y)) for feature in map_features(MAP_PATH))


def region_point(region_id):
    best=None
    for feature in map_features(MAP_PATH):
        if feature.get('properties',{}).get('region_id')!=region_id:continue
        for rings in polygons(feature.get('geometry') or {}):
            if not rings or not rings[0]:continue
            ys=[p[1] for p in rings[0]];low,high=min(ys),max(ys)
            for fraction in (.5,.25,.75):
                y=low+(high-low)*fraction;intersections=[]
                for ring in rings:
                    for a,b in zip(ring,ring[1:]):
                        if (a[1]>y)!=(b[1]>y):intersections.append(a[0]+(y-a[1])*(b[0]-a[0])/(b[1]-a[1]))
                intersections.sort()
                for left,right in zip(intersections[::2],intersections[1::2]):
                    score=(right-left)*(high-low)
                    if best is None or score>best[0]:best=(score,[(left+right)/2,y])
    return best[1] if best else None


def exposed_coastlines(features):
    """Subtract edges with land on both sides, retaining split coastal edges."""
    lines={}
    for feature in features:
        region=feature.get('properties',{}).get('region_id')
        for rings in polygons(feature.get('geometry') or {}):
            if not rings:continue
            ring=rings[0]
            area=sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(ring,ring[1:]))
            # Interior holes are lakes, not sea. Ring orientation identifies
            # which side is land, including adjacent parts of the same region.
            for a,b in zip(ring,ring[1:]):
                dx,dy=b[0]-a[0],b[1]-a[1];length=math.hypot(dx,dy)
                if length<1e-8:continue
                nx,ny=dy/length,-dx/length;flip=1
                if nx < -1e-9 or abs(nx)<1e-9 and ny<0:nx,ny=-nx,-ny;flip=-1
                side=(-1 if area>0 else 1)*flip
                axis=0 if abs(dx)>=abs(dy) else 1
                key=(round(nx,7),round(ny,7),round(nx*a[0]+ny*a[1],5),axis)
                low,high=sorted((a[axis],b[axis]))
                lines.setdefault(key,[]).append((low,high,region,a[:2],b[:2],side))
    coast={};seen=set()
    for segments in lines.values():
        segments.sort(key=lambda s:s[0])
        for low,high,region,a,b,side in segments:
            if region is None:continue
            pieces=[(low,high)]
            for otherlow,otherhigh,_,_,_,other_side in segments:
                if other_side==side or otherhigh<=low+1e-7 or otherlow>=high-1e-7:continue
                pieces=[part for left,right in pieces for part in ((left,min(right,otherlow)),(max(left,otherhigh),right)) if part[1]-part[0]>1e-7]
            axis=0 if abs(b[0]-a[0])>=abs(b[1]-a[1]) else 1
            def point(value):
                t=(value-a[axis])/(b[axis]-a[axis])
                return [a[0]+t*(b[0]-a[0]),a[1]+t*(b[1]-a[1])]
            for left,right in pieces:
                segment=[point(left),point(right)]
                key=(int(region),tuple(round(v,7) for p in segment for v in p))
                if key not in seen:coast.setdefault(int(region),[]).append(segment);seen.add(key)
    return coast


@lru_cache(maxsize=2)
def _coastlines(modified):
    return exposed_coastlines(map_features(MAP_PATH))


def coastline_segments(region_id):
    return _coastlines(MAP_PATH.stat().st_mtime_ns).get(region_id,[])


def segment_distance(point,a,b):
    dx,dy=b[0]-a[0],b[1]-a[1]
    t=max(0,min(1,((point[0]-a[0])*dx+(point[1]-a[1])*dy)/(dx*dx+dy*dy))) if dx or dy else 0
    return math.hypot(point[0]-a[0]-t*dx,point[1]-a[1]-t*dy)


def naval_location_allowed(region_id,x,y,km_per_unit):
    return region_contains(region_id,x,y) and any(segment_distance((x,y),a,b)*km_per_unit<=3+1e-7 for a,b in coastline_segments(region_id))
