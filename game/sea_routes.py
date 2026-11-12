"""Water-only navigation: shortest grid search, visibility shortcuts and coastal tightening."""
from functools import lru_cache
from heapq import heappop,heappush
from math import hypot,ceil
import numpy as np
import shapely
from shapely.geometry import shape,Polygon,Point,LineString
from shapely.ops import unary_union,nearest_points
from game.finance_service import FinanceError
from game.military_geography import MAP_PATH,map_features


def path_length(path):return sum(hypot(b[0]-a[0],b[1]-a[1]) for a,b in zip(path,path[1:]))


def path_position(path,fraction):
    if not path:return None
    remaining=max(0,min(1,fraction))*path_length(path)
    for a,b in zip(path,path[1:]):
        length=hypot(b[0]-a[0],b[1]-a[1])
        if length and remaining<=length:return [a[i]+(b[i]-a[i])*remaining/length for i in (0,1)]
        remaining-=length
    return list(path[-1])


class SeaRouter:
    def __init__(self,land,resolution=1800):
        land=shapely.make_valid(land)
        polygons=[]
        def collect(geometry):
            if geometry.geom_type=='Polygon':polygons.append(Polygon(geometry.exterior))
            elif hasattr(geometry,'geoms'):
                for part in geometry.geoms:collect(part)
        collect(land)
        self.land=unary_union(polygons).buffer(.02)
        self.resolution=resolution;self.grids={};shapely.prepare(self.land)

    def clear(self,a,b):return not shapely.intersects(self.land,LineString([a,b]))

    def offshore(self,point):
        p=Point(point)
        if self.land.covers(p):return list(nearest_points(self.land.buffer(.15).boundary,p)[0].coords[0])
        return list(point)

    def grid(self,step,points):
        x0,y0,x1,y1=self.land.bounds
        x0=min(x0,*(p[0] for p in points));y0=min(y0,*(p[1] for p in points));x1=max(x1,*(p[0] for p in points));y1=max(y1,*(p[1] for p in points))
        key=(step,x0,y0,x1,y1)
        if key in self.grids:return self.grids[key]
        margin=max(step*8,(x1-x0+y1-y0)*.025)
        x0-=margin;y0-=margin;x1+=margin;y1+=margin
        width=ceil((x1-x0)/step)+1;height=ceil((y1-y0)/step)+1
        xs=x0+np.arange(width)*step;ys=y0+np.arange(height)*step
        # The clearance radius also prevents diagonal grid edges clipping an island.
        expanded=self.land.buffer(step*.76);shapely.prepare(expanded)
        blocked=shapely.contains_xy(expanded,xs[None,:],ys[:,None])
        data=(x0,y0,width,height,blocked)
        if len(self.grids)>=3:self.grids.pop(next(iter(self.grids)))
        self.grids[key]=data;return data

    def search(self,start,end,step):
        x0,y0,width,height,blocked=self.grid(step,(start,end))
        def point(cell):return [x0+(cell%width)*step,y0+(cell//width)*step]
        def anchor(p):
            x=round((p[0]-x0)/step);y=round((p[1]-y0)/step);choices=[]
            for radius in (4,12,30):
                for j in range(max(0,y-radius),min(height,y+radius+1)):
                    for i in range(max(0,x-radius),min(width,x+radius+1)):
                        if not blocked[j,i]:choices.append((hypot(x0+i*step-p[0],y0+j*step-p[1]),j*width+i))
                for _,cell in sorted(choices):
                    if self.clear(p,point(cell)):return cell
            raise FinanceError('Nie można połączyć portu z dostępnym szlakiem morskim.')
        first,last=anchor(start),anchor(end);gx,gy=last%width,last//width
        queue=[(hypot(first%width-gx,first//width-gy),0,first)];cost={first:0};parents={}
        while queue:
            _,distance,cell=heappop(queue)
            if distance!=cost[cell]:continue
            if cell==last:
                cells=[cell]
                while cells[-1]!=first:cells.append(parents[cells[-1]])
                return [start]+[point(c) for c in reversed(cells)]+[end]
            x,y=cell%width,cell//width
            for dx,dy in ((-1,0),(1,0),(0,-1),(0,1),(-1,-1),(-1,1),(1,-1),(1,1)):
                nx,ny=x+dx,y+dy
                if not (0<=nx<width and 0<=ny<height) or blocked[ny,nx]:continue
                if dx and dy and (blocked[y,nx] or blocked[ny,x]):continue
                neighbor=ny*width+nx;new=distance+(1.4142135623730951 if dx and dy else 1)
                if new<cost.get(neighbor,float('inf')):
                    cost[neighbor]=new;parents[neighbor]=cell
                    heappush(queue,(new+hypot(nx-gx,ny-gy),new,neighbor))
        raise FinanceError('Brak bezpiecznej trasy morskiej między portami.')

    def route(self,source,target):
        start,end=self.offshore(source),self.offshore(target)
        if hypot(end[0]-start[0],end[1]-start[1])<1e-8:return [start,end]
        if self.clear(start,end):return [start,end]
        bounds=self.land.bounds;step=max(bounds[2]-bounds[0],bounds[3]-bounds[1])/self.resolution
        try:path=self.search(start,end,step)
        except FinanceError:path=self.search(start,end,step/2)
        # Greedy visibility removes grid staircases; every shortcut is tested against land.
        result=[path[0]];i=0
        while i<len(path)-1:
            j=len(path)-1
            while j>i+1 and not self.clear(path[i],path[j]):j-=1
            if not self.clear(path[i],path[j]):raise FinanceError('Nie można wyznaczyć trasy omijającej ląd.')
            result.append(path[j]);i=j
        for _ in range(3):
            for i in range(1,len(result)-1):
                a,p,b=result[i-1:i+2];dx=b[0]-a[0];dy=b[1]-a[1];den=dx*dx+dy*dy
                if not den:continue
                t=max(0,min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/den));goal=[a[0]+t*dx,a[1]+t*dy]
                lo,hi=0.,1.
                for _ in range(30):
                    mid=(lo+hi)/2;q=[p[k]+(goal[k]-p[k])*mid for k in (0,1)]
                    if self.clear(a,q) and self.clear(q,b):lo=mid
                    else:hi=mid
                result[i]=[p[k]+(goal[k]-p[k])*lo*.999999 for k in (0,1)]
        if any(not self.clear(a,b) for a,b in zip(result,result[1:])):raise FinanceError('Trasa morska przecina ląd.')
        return result


@lru_cache(maxsize=1)
def _world_router(modified):return SeaRouter(unary_union([shapely.make_valid(shape(f['geometry'])) for f in map_features(MAP_PATH) if f.get('geometry')]))


@lru_cache(maxsize=512)
def _route(source,target,modified):return _world_router(modified).route(source,target)


def shortest_sea_route(source,target):
    if source is None or target is None:raise FinanceError('Brak współrzędnych portów.')
    return [list(point) for point in _route(tuple(source),tuple(target),MAP_PATH.stat().st_mtime_ns)]


@lru_cache(maxsize=4)
def _navy_router(modified,km_per_unit):
    router=_world_router(modified)
    return SeaRouter(router.land.buffer(2/km_per_unit),resolution=router.resolution)

@lru_cache(maxsize=512)
def naval_sea_route(source,target,km_per_unit):
    router=_navy_router(MAP_PATH.stat().st_mtime_ns,km_per_unit)
    if router.land.covers(Point(target)):
        raise FinanceError('Cel rejsu musi znajdować się na wodzie co najmniej 2 km od wybrzeża.')
    return router.route(source,target)
