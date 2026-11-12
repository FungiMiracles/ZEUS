"""Krzywa przez cztery punkty i dokładny podział odcinka na państwa."""
from math import hypot
from game.finance_service import FinanceError
from game.military_geography import polygons,contains_point


def interpolate(start,controls,end):
    knots=[start,*controls,end];times=[0,1/3,2/3,1];result=[]
    for step in range(25):
        t=step/24;weights=[]
        for i,ti in enumerate(times):
            w=1.
            for j,tj in enumerate(times):
                if i!=j:w*= (t-tj)/(ti-tj)
            weights.append(w)
        result.append([round(sum(w*knots[i][axis] for i,w in enumerate(weights)),6) for axis in (0,1)])
    result[0]=start;result[-1]=end;result[8]=controls[0];result[16]=controls[1]
    return result


def partition_path(path,features):
    """Features contain an owner ID. Split at every polygon border, not sample intervals."""
    chunks=[]
    for start,end in zip(path,path[1:]):
        dx,dy=end[0]-start[0],end[1]-start[1]
        if hypot(dx,dy)<1e-12:continue
        lowx,highx=sorted([start[0],end[0]]);lowy,highy=sorted([start[1],end[1]])
        nearby=[f for f in features if f['bounds'][0]<=highx+1e-8 and f['bounds'][2]>=lowx-1e-8 and f['bounds'][1]<=highy+1e-8 and f['bounds'][3]>=lowy-1e-8]
        cuts={0.,1.}
        for feature in nearby:
            for rings in polygons(feature['geometry']):
                for ring in rings:
                    for a,b in zip(ring,ring[1:]):
                        ex,ey=b[0]-a[0],b[1]-a[1];den=dx*ey-dy*ex
                        if abs(den)<1e-12:continue
                        ax,ay=a[0]-start[0],a[1]-start[1];t=(ax*ey-ay*ex)/den;u=(ax*dy-ay*dx)/den
                        if 1e-10<t<1-1e-10 and -1e-9<=u<=1+1e-9:cuts.add(t)
        points=sorted(cuts)
        for a,b in zip(points,points[1:]):
            if b-a<1e-9:continue
            middle=[start[0]+dx*(a+b)/2,start[1]+dy*(a+b)/2]
            owner=next((f['owner'] for f in nearby if contains_point(f['geometry'],middle)),None)
            if owner is None:raise FinanceError('Droga przebiega przez morze lub teren bez państwa.')
            left=[start[0]+dx*a,start[1]+dy*a];right=[start[0]+dx*b,start[1]+dy*b]
            if chunks and chunks[-1]['countryId']==owner:chunks[-1]['path'].append(right)
            else:chunks.append({'countryId':owner,'path':[left,right]})
    return chunks


def prepare_features(raw,owners):
    result=[]
    for feature in raw:
        id=feature.get('properties',{}).get('region_id');geometry=feature.get('geometry') or {}
        if id not in owners:continue
        coords=[p for rings in polygons(geometry) for ring in rings for p in ring]
        if not coords:continue
        result.append({'owner':owners[id],'geometry':geometry,'bounds':(min(p[0] for p in coords),min(p[1] for p in coords),max(p[0] for p in coords),max(p[1] for p in coords))})
    return result
