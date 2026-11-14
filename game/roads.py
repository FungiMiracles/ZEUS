"""Natychmiastowe drogi z wyceną, kontrolą terytorium i wspólnym budżetem."""
from decimal import Decimal, ROUND_HALF_UP
from math import isfinite,hypot
from sqlalchemy import select, or_, and_
from sqlalchemy.orm import Session
from extensions import db
from models import Region, Panstwo
from game.civic_models import Road
from game.finance_models import StateBudget
from game.finance_service import FinanceError, FinanceConflict, _country_for_user, game_now, period_key
from game.budget_transfers import precise, infrastructure_balance
from game.mining_service import request_key
from game.military_flights import distance_km
from game.military_geography import MAP_PATH, map_features, contains_point, polygons

PRICES={'motorway':10000000,'national':250000}


def point(value):
    if not isinstance(value,list) or len(value)!=2 or any(type(v) not in (int,float) or not isfinite(v) or abs(v)>1000000 for v in value):raise FinanceError('Wybierz dwa poprawne punkty na mapie.')
    return [round(float(v),6) for v in value]


def segment_inside(features,start,end):
    """Split at every border crossing; test each interval, including polygon holes."""
    geometries=[f.get('geometry') or {} for f in features]
    covered=lambda p:any(contains_point(g,p) for g in geometries)
    if not covered(start) or not covered(end):return False
    dx,dy=end[0]-start[0],end[1]-start[1];cuts={0.,1.}
    for geometry in geometries:
        for rings in polygons(geometry):
            for ring in rings:
                for a,b in zip(ring,ring[1:]):
                    ex,ey=b[0]-a[0],b[1]-a[1];den=dx*ey-dy*ex
                    if abs(den)<1e-12:continue
                    ax,ay=a[0]-start[0],a[1]-start[1]
                    t=(ax*ey-ay*ex)/den;u=(ax*dy-ay*dx)/den
                    if 0<=t<=1 and 0<=u<=1:cuts.add(t)
    ordered=sorted(cuts)
    return all(covered([start[0]+dx*((a+b)/2),start[1]+dy*((a+b)/2)]) for a,b in zip(ordered,ordered[1:]) if b-a>1e-10)


def curved_path(features,start,end):
    dx,dy=end[0]-start[0],end[1]-start[1]
    for bend in (.08,-.08,.04,-.04,.02,-.02,0):
        control=[(start[0]+end[0])/2-dy*bend,(start[1]+end[1])/2+dx*bend]
        path=[[round((1-t)**2*start[0]+2*(1-t)*t*control[0]+t*t*end[0],6),
               round((1-t)**2*start[1]+2*(1-t)*t*control[1]+t*t*end[1],6)] for t in [i/24 for i in range(25)]]
        path[0]=start;path[-1]=end
        if all(segment_inside(features,a,b) for a,b in zip(path,path[1:])):return path
    raise FinanceError('Droga przecina morze lub obce terytorium. Wybierz inny odcinek.')


@precise
def quote_road(session,country_id,data,admin=False,lock_regions=True):
    kind=data.get('kind')
    if not isinstance(kind,str) or kind not in PRICES:raise FinanceError('Wybierz autostradę lub drogę krajową.')
    start,end=point(data.get('start')),point(data.get('end'))
    if start==end:raise FinanceError('Początek i koniec drogi muszą być różne.')
    query=select(Region.region_id).where(Region.panstwo_id==country_id)
    if not admin:query=query.where(Region.terytorium_zamorskie.is_(False))
    ids=set(session.scalars(query.with_for_update() if lock_regions else query))
    features=[f for f in map_features(MAP_PATH) if admin or f.get('properties',{}).get('region_id') in ids]
    from game.road_geometry import interpolate
    controls=data.get('control_points')
    if controls is not None:
        if not isinstance(controls,list) or len(controls)!=2:raise FinanceError('Ustaw dwa punkty krzywizny.')
        controls=[point(p) for p in controls];path=interpolate(start,controls,end)
        if not all(segment_inside(features,a,b) for a,b in zip(path,path[1:])):raise FinanceError('Krzywizna wyprowadza drogę poza dozwolony teren.')
    else:
        path=curved_path(features,start,end);controls=[path[8],path[16]]
        path=interpolate(start,controls,end)
        if not all(segment_inside(features,a,b) for a,b in zip(path,path[1:])):raise FinanceError('Dopasuj punkty krzywizny do granic kraju.')
    from game.nuclear import require_clear_path
    require_clear_path(session,path)   # 13 Nov 2026: droga nie może przebiegać przez strefę skażenia
    ratio=sum(hypot(b[0]-a[0],b[1]-a[1]) for a,b in zip(path,path[1:]))/hypot(end[0]-start[0],end[1]-start[1])
    distance=Decimal(str(distance_km(session,start,end)*ratio)).quantize(Decimal('.001'),rounding=ROUND_HALF_UP)
    if distance<=0:raise FinanceError('Odcinek jest zbyt krótki.')
    cost=Decimal(0) if admin else (distance*PRICES[kind]).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
    return {'kind':kind,'start':start,'end':end,'distanceKm':str(distance),'cost':str(cost),'countryId':country_id,'path':path,'control_points':controls}


def road_data(road):
    return {'id':road.id,'countryId':road.panstwo_id,'kind':road.kind,'start':[road.start_x,road.start_y],'end':[road.end_x,road.end_y],'distanceKm':str(road.distance_km),'cost':str(road.cost),'path':road.path or [[road.start_x,road.start_y],[road.end_x,road.end_y]]}


@precise
def build_road(user_id,data,*,admin_country_id=None,admin_actor=None):
    key=request_key(data.get('request_id'));admin=admin_country_id is not None
    with Session(db.engine) as session,session.begin():
        country=session.scalar(select(Panstwo.PANSTWO_ID).where(Panstwo.PANSTWO_ID==admin_country_id).with_for_update()) if admin else _country_for_user(session,user_id,lock=True).PANSTWO_ID
        if country is None:raise FinanceError('Nie znaleziono państwa.')
        existing=session.scalar(select(Road).where(Road.panstwo_id==country,Road.request_id==key))
        if existing:
            if (existing.kind,[existing.start_x,existing.start_y],[existing.end_x,existing.end_y],bool(existing.admin_actor))!=(data.get('kind'),point(data.get('start')),point(data.get('end')),admin):raise FinanceConflict('Identyfikator budowy został już użyty.')
            return road_data(existing)
        quote=quote_road(session,country,data,admin)
        if not admin:
            from game.land_war import require_buildable,region_at
            for end in (quote['start'],quote['end']):require_buildable(session,region_at(end[0],end[1]),country)
        if data.get('path') is not None and data['path']!=quote['path']:raise FinanceConflict('Przebieg drogi zmienił się. Ponownie sprawdź wycenę.')
        if data.get('expected_cost')!=quote['cost']:raise FinanceConflict('Wycena zmieniła się. Ponownie sprawdź odcinek.')
        forward=and_(Road.start_x==quote['start'][0],Road.start_y==quote['start'][1],Road.end_x==quote['end'][0],Road.end_y==quote['end'][1])
        reverse=and_(Road.start_x==quote['end'][0],Road.start_y==quote['end'][1],Road.end_x==quote['start'][0],Road.end_y==quote['start'][1])
        if session.scalar(select(Road.id).where(Road.panstwo_id==country,Road.kind==quote['kind'],or_(forward,reverse))):
            raise FinanceError('Taki odcinek drogi już istnieje.')
        budget=None
        if not admin:
            year,period=period_key(game_now())
            budget=session.scalar(select(StateBudget).where(StateBudget.panstwo_id==country,StateBudget.game_year==year,StateBudget.period==period).with_for_update())
            if budget is None or infrastructure_balance(session,budget)[1]<Decimal(quote['cost']):raise FinanceError('Za mało środków we wspólnym budżecie infrastruktury. Możesz przesunąć środki w panelu finansów.')
        road=Road(panstwo_id=country,kind=quote['kind'],start_x=quote['start'][0],start_y=quote['start'][1],end_x=quote['end'][0],end_y=quote['end'][1],path=quote['path'],distance_km=Decimal(quote['distanceKm']),cost=Decimal(quote['cost']),budget_id=budget.id if budget else None,user_id=None if admin else user_id,admin_actor=admin_actor if admin else None,request_id=key)
        session.add(road);session.flush();return road_data(road)
