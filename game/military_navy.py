"""Trwałe rejsy okrętów w czasie Entendy i rezerwacja jednostek w bazach."""
from datetime import timedelta
from math import isfinite
from sqlalchemy import select,func
from game.finance_service import FinanceError
from game.military_models import MilitaryVessel,MilitaryBase
from game.military_flights import distance_km

VESSEL_SPEED=100


def navigation_route(session,source,target):
    from game.sea_routes import naval_sea_route
    from game.military_flights import calibration
    return naval_sea_route(tuple(source),tuple(target),calibration(session).km_per_unit)

def vessel_route(vessel):
    from sqlalchemy.orm import object_session
    from game.sea_routes import _navy_router,MAP_PATH
    from game.military_flights import calibration
    session=object_session(vessel)
    scale=calibration(session).km_per_unit
    target=_navy_router(MAP_PATH.stat().st_mtime_ns,scale).offshore([vessel.target_x,vessel.target_y])
    return navigation_route(session,[vessel.source_x,vessel.source_y],target)


def vessel_position(vessel,now):
    seconds=(vessel.arrives_at-vessel.starts_at).total_seconds()
    t=min(1,max(0,(now-vessel.starts_at).total_seconds()/max(1,seconds)))
    from game.sea_routes import path_position
    return path_position(vessel_route(vessel),t)


def busy_vessels(session,base_id,kind):
    return session.scalar(select(func.count()).select_from(MilitaryVessel).where(MilitaryVessel.base_id==base_id,MilitaryVessel.kind==kind,MilitaryVessel.status.in_(['sailing','stationed','returning']))) or 0


def settle_vessels(session,now,country_id):
    # All callers acquire the country lock before this function.
    vessels=list(session.scalars(select(MilitaryVessel).where(MilitaryVessel.panstwo_id==country_id,MilitaryVessel.status.in_(['sailing','returning']),MilitaryVessel.arrives_at<=now).order_by(MilitaryVessel.id).with_for_update()))
    for vessel in vessels:
        if vessel.kind=='carriers':
            # Lotniskowiec nie należy do garnizonu bazy morskiej; po powrocie myśliwce wracają do swojej bazy powietrznej.
            if vessel.status=='returning':vessel.status='docked';vessel.fighters=0;vessel.base_id=None;vessel.region_id=None
            else:vessel.status='stationed'
            continue
        if vessel.status=='returning':
            origin=session.get(MilitaryBase,vessel.base_id) if vessel.base_id else None
            destination=session.get(MilitaryBase,vessel.return_base_id)
            if destination is None or destination.health<=0:continue
            if origin is None or origin.id!=destination.id:
                # Capacity was reserved when the return was ordered.
                if origin:origin.garrison={**origin.garrison,vessel.kind:max(0,origin.garrison.get(vessel.kind,0)-1)}
                destination.garrison={**destination.garrison,vessel.kind:destination.garrison.get(vessel.kind,0)+1}
                vessel.base_id=destination.id;vessel.region_id=destination.region_id
            vessel.status='docked'
        else:vessel.status='stationed'
    session.flush()


def carriers_at_sea(session,country_id):
    return session.scalar(select(func.count()).select_from(MilitaryVessel).where(MilitaryVessel.panstwo_id==country_id,MilitaryVessel.kind=='carriers',MilitaryVessel.status.in_(['sailing','stationed','returning']))) or 0


def returning_reservations(session,base_id,kind):
    return session.scalar(select(func.count()).select_from(MilitaryVessel).where(MilitaryVessel.return_base_id==base_id,MilitaryVessel.base_id!=base_id,MilitaryVessel.kind==kind,MilitaryVessel.status=='returning')) or 0


def change_vessel(session,country_id,action,data,now):
    from game.military_service import natural,capacities
    settle_vessels(session,now,country_id)
    if action=='rename_vessel':
        vessel=attack_vessel(session,country_id,data.get('vessel_id'),now,allow_returning=True)
        name=data.get('name')
        if not isinstance(name,str) or not 1<=len(name.strip())<=120 or any(ord(c)<32 for c in name):raise FinanceError('Nazwa okrętu musi mieć od 1 do 120 znaków.')
        vessel.name=name.strip()
    elif action=='sail':
        base=session.scalar(select(MilitaryBase).where(MilitaryBase.id==natural(data.get('base_id'),'Baza morska',1),MilitaryBase.panstwo_id==country_id,MilitaryBase.kind=='naval').with_for_update())
        kind=data.get('vessel_kind')
        if kind not in ('warships','submarines') or base is None or base.map_x is None or base.health<=0:
            raise FinanceError('Wybierz sprawną bazę morską na mapie i rodzaj okrętu.')
        from game.land_war import require_usable_base
        require_usable_base(session,base.id)
        if base.garrison.get(kind,0)<=busy_vessels(session,base.id,kind):raise FinanceError('Brak wolnego okrętu tego rodzaju w bazie.')
        x,y=data.get('x'),data.get('y')
        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not isfinite(v) or abs(v)>10000000 for v in (x,y)):
            raise FinanceError('Nieprawidłowa lokalizacja docelowa okrętu.')
        source=[base.map_x,base.map_y];target=[x,y]
        from game.sea_routes import path_length
        from game.military_flights import calibration
        route=navigation_route(session,source,target);source,target=route[0],route[-1]
        arrival=now+timedelta(seconds=max(1,path_length(route)*calibration(session).km_per_unit/VESSEL_SPEED*3600))
        vessel=session.scalar(select(MilitaryVessel).where(MilitaryVessel.panstwo_id==country_id,MilitaryVessel.base_id==base.id,MilitaryVessel.kind==kind,MilitaryVessel.status=='docked',MilitaryVessel.health>0).order_by(MilitaryVessel.id).with_for_update().limit(1))
        if vessel is None:
            vessel=MilitaryVessel(panstwo_id=country_id,base_id=base.id,kind=kind);session.add(vessel)
        vessel.region_id=base.region_id
        vessel.status='sailing';vessel.source_x,vessel.source_y=source;vessel.target_x,vessel.target_y=target
        vessel.starts_at=now;vessel.arrives_at=arrival;vessel.return_base_id=None
    elif action=='sail_carrier':
        # 12 Nov 2026: lotniskowiec wypływa z bazy morskiej z myśliwcami (1–5) z wybranej bazy powietrznej.
        from game.military_flights import busy_fighters,CARRIER_FIGHTERS
        from game.governance import army_for_country
        from game.land_war import require_usable_base
        port=session.scalar(select(MilitaryBase).where(MilitaryBase.id==natural(data.get('base_id'),'Baza morska',1),MilitaryBase.panstwo_id==country_id,MilitaryBase.kind=='naval').with_for_update())
        if port is None or port.map_x is None or port.health<=0:raise FinanceError('Wybierz sprawną bazę morską na mapie.')
        airbase=session.scalar(select(MilitaryBase).where(MilitaryBase.id==natural(data.get('air_base_id'),'Baza powietrzna',1),MilitaryBase.panstwo_id==country_id,MilitaryBase.kind=='air').with_for_update())
        if airbase is None or airbase.health<=0 or not airbase.operational:raise FinanceError('Wybierz sprawną własną bazę powietrzną.')
        require_usable_base(session,port.id);require_usable_base(session,airbase.id)
        fighters=natural(data.get('fighters'),'Liczba myśliwców',1)
        if fighters>CARRIER_FIGHTERS:raise FinanceError(f'Lotniskowiec zabiera najwyżej {CARRIER_FIGHTERS} myśliwców.')
        if fighters>airbase.garrison.get('fighters',0)-busy_fighters(session,airbase.id,now):raise FinanceError('Za mało wolnych myśliwców w wybranej bazie powietrznej.')
        army=army_for_country(session,country_id,lock=True)
        if ((army.lotniskowce_ilosc or 0) if army else 0)<=carriers_at_sea(session,country_id):raise FinanceError('Brak wolnego lotniskowca.')
        x,y=data.get('x'),data.get('y')
        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not isfinite(v) or abs(v)>10000000 for v in (x,y)):
            raise FinanceError('Nieprawidłowa lokalizacja docelowa lotniskowca.')
        from game.sea_routes import path_length
        from game.military_flights import calibration
        route=navigation_route(session,[port.map_x,port.map_y],[x,y]);source,target=route[0],route[-1]
        arrival=now+timedelta(seconds=max(1,path_length(route)*calibration(session).km_per_unit/VESSEL_SPEED*3600))
        vessel=session.scalar(select(MilitaryVessel).where(MilitaryVessel.panstwo_id==country_id,MilitaryVessel.kind=='carriers',MilitaryVessel.status=='docked',MilitaryVessel.health>0).order_by(MilitaryVessel.id).with_for_update().limit(1))
        new=vessel is None
        if new:vessel=MilitaryVessel(panstwo_id=country_id,kind='carriers')
        vessel.base_id=None;vessel.region_id=port.region_id;vessel.fighters=fighters;vessel.air_base_id=airbase.id
        vessel.status='sailing';vessel.source_x,vessel.source_y=source;vessel.target_x,vessel.target_y=target
        vessel.starts_at=now;vessel.arrives_at=arrival;vessel.return_base_id=None
        if new:session.add(vessel)
    elif action=='redirect_vessel':
        # 12 Nov 2026: okręt na morzu (w rejsie, na pozycji lub w drodze powrotnej) płynie do nowego punktu.
        vessel=attack_vessel(session,country_id,data.get('vessel_id'),now,allow_returning=True)
        x,y=data.get('x'),data.get('y')
        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not isfinite(v) or abs(v)>10000000 for v in (x,y)):
            raise FinanceError('Nieprawidłowa lokalizacja docelowa okrętu.')
        from game.sea_routes import path_length
        from game.military_flights import calibration
        source=vessel_position(vessel,now)
        route=navigation_route(session,source,[x,y]);source,target=route[0],route[-1]
        vessel.source_x,vessel.source_y=source;vessel.target_x,vessel.target_y=target
        vessel.starts_at=now;vessel.arrives_at=now+timedelta(seconds=max(1,path_length(route)*calibration(session).km_per_unit/VESSEL_SPEED*3600))
        vessel.return_base_id=None;vessel.status='sailing'
    elif action=='return_vessel':
        vessel=attack_vessel(session,country_id,data.get('vessel_id'),now,allow_returning=True)
        base=session.scalar(select(MilitaryBase).where(MilitaryBase.id==natural(data.get('base_id'),'Baza docelowa',1),MilitaryBase.panstwo_id==country_id,MilitaryBase.kind=='naval').with_for_update())
        if base is None or base.map_x is None or base.health<=0:raise FinanceError('Wybierz własną, sprawną bazę morską na mapie.')
        if vessel.kind!='carriers' and base.id!=vessel.base_id and base.garrison.get(vessel.kind,0)+returning_reservations(session,base.id,vessel.kind)>=capacities(base)[vessel.kind]:
            raise FinanceError('Brak wolnego miejsca w docelowej bazie morskiej.')
        source=vessel_position(vessel,now)
        from game.sea_routes import _navy_router,MAP_PATH,path_length
        from game.military_flights import calibration
        scale=calibration(session).km_per_unit
        target=_navy_router(MAP_PATH.stat().st_mtime_ns,scale).offshore([base.map_x,base.map_y])
        route=navigation_route(session,source,target);source,target=route[0],route[-1]
        vessel.source_x,vessel.source_y=source;vessel.target_x,vessel.target_y=target
        vessel.starts_at=now;vessel.arrives_at=now+timedelta(seconds=max(1,path_length(route)*scale/VESSEL_SPEED*3600))
        vessel.return_base_id=base.id;vessel.status='returning'
    session.flush()


def attack_vessel(session,country_id,vessel_id,now,allow_returning=False):
    from game.military_service import natural
    vessel=session.scalar(select(MilitaryVessel).where(MilitaryVessel.id==natural(vessel_id,'Okręt',1),MilitaryVessel.panstwo_id==country_id).with_for_update())
    if vessel is None or vessel.status in ('docked','sunk') or vessel.health<=0 or (not allow_returning and vessel.status=='returning'):
        raise FinanceError('Wybierz własny okręt będący w rejsie lub na pozycji.')
    return vessel


def _busy_carrier(vessel,now):
    if vessel.kind!='carriers':return 0
    from sqlalchemy.orm import object_session
    from game.military_flights import carrier_flights
    return carrier_flights(object_session(vessel),vessel.id,now)


def vessel_data(vessel,now):
    return {'id':vessel.id,'name':vessel.name,'health':vessel.health,'countryId':vessel.panstwo_id,'baseId':vessel.base_id,'regionId':str(vessel.region_id) if vessel.region_id else None,'kind':vessel.kind,'status':vessel.status,
        'route':vessel_route(vessel),'source':[vessel.source_x,vessel.source_y],'target':[vessel.target_x,vessel.target_y],
        'position':vessel_position(vessel,now),'fighters':vessel.fighters or 0,'airBaseId':vessel.air_base_id,'busyFighters':_busy_carrier(vessel,now),'startsAt':vessel.starts_at.isoformat()+'Z','arrivesAt':vessel.arrives_at.isoformat()+'Z'}
