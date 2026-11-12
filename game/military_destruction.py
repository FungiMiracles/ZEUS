from game.paga_ai_actor import country_user_id
"""Usunięcie zniszczonej bazy z zachowaniem historii i jednostek na morzu."""
from game.governance import army_for_country, controller_id, controlled_ids
from sqlalchemy import select,update,delete,func
from sqlalchemy.orm import lazyload
from game.military_models import MilitaryBase,MilitaryExpense,MilitaryFlight,MilitaryVessel,MissileDefense,MissileDefenseExpense
from game.forum_models import GameNotification
from game.models import GamePlayerCountry,utc_now
from models import Wojsko


def destroy_base(session,base,now):
    from game.military_service import BASES,RESOURCES
    from game.military_navy import vessel_position
    afloat=list(session.scalars(select(MilitaryVessel).where(MilitaryVessel.base_id==base.id,MilitaryVessel.status.in_(['sailing','stationed','returning'])).order_by(MilitaryVessel.id).with_for_update()))
    spared={kind:sum(v.kind==kind for v in afloat) for kind in ('warships','submarines')}
    # Myśliwce zaokrętowane na lotniskowcach przetrwają zniszczenie bazy powietrznej (12 Nov 2026).
    carriers=list(session.scalars(select(MilitaryVessel).where(MilitaryVessel.air_base_id==base.id,MilitaryVessel.kind=='carriers',MilitaryVessel.status.in_(['sailing','stationed','returning'])).with_for_update()))
    spared['fighters']=sum(v.fighters or 0 for v in carriers)
    for carrier in carriers:carrier.air_base_id=None
    army=army_for_country(session, base.panstwo_id, lock=True)
    if army is not None:
        for resource,count in base.garrison.items():
            lost=max(0,count-spared.get(resource,0));field=BASES[base.kind][2] if resource=='soldiers' else RESOURCES[resource][1]
            setattr(army,field,max(0,(getattr(army,field) or 0)-lost))
        field=BASES[base.kind][1]
        if field:setattr(army,field,max(0,(getattr(army,field) or 0)-1))
    for vessel in afloat:vessel.region_id=base.region_id;vessel.base_id=None
    for vessel in session.scalars(select(MilitaryVessel).where(MilitaryVessel.return_base_id==base.id,MilitaryVessel.status=='returning').with_for_update()):
        point=vessel_position(vessel,now);vessel.source_x,vessel.source_y=point;vessel.target_x,vessel.target_y=point
        vessel.starts_at=now;vessel.arrives_at=now;vessel.return_base_id=None;vessel.status='stationed'
    # Docked records refer to the garrison destroyed in the port.
    session.execute(update(MilitaryVessel).where(MilitaryVessel.base_id==base.id,MilitaryVessel.status=='docked').values(status='sunk',health=0))
    detach_base(session,base)
    owner=country_user_id(session,base.panstwo_id)
    if owner is not None:session.add(GameNotification(user_id=owner,notification_type='SYSTEM',system_text=f'Twoja baza {base.name or "#"+str(base.id)} została zniszczona. Garnizon został utracony. Okręty na morzu mogą wrócić do innej bazy morskiej.',created_at=utc_now()))
    session.delete(base);session.flush()


def detach_base(session,base):
    """References to a base that is about to disappear (destroyed or liquidated); history rows are kept."""
    session.execute(update(MilitaryVessel).where(MilitaryVessel.base_id==base.id).values(base_id=None,region_id=base.region_id))
    session.execute(update(MilitaryVessel).where(MilitaryVessel.return_base_id==base.id).values(return_base_id=None))
    session.execute(update(MilitaryVessel).where(MilitaryVessel.air_base_id==base.id).values(air_base_id=None))
    session.execute(update(MilitaryExpense).where(MilitaryExpense.base_id==base.id).values(base_id=None))
    session.execute(update(MilitaryFlight).where(MilitaryFlight.source_base_id==base.id).values(source_base_id=None))
    session.execute(update(MilitaryFlight).where(MilitaryFlight.target_base_id==base.id).values(target_base_id=None,target_kind='base'))
    defense_ids=list(session.scalars(select(MissileDefense.id).where(MissileDefense.target_kind=='base',MissileDefense.target_id==base.id)))
    if defense_ids:
        session.execute(update(MilitaryFlight).where(MilitaryFlight.target_defense_id.in_(defense_ids)).values(target_defense_id=None))
        session.execute(update(MissileDefenseExpense).where(MissileDefenseExpense.defense_id.in_(defense_ids)).values(defense_id=None))
        session.execute(delete(MissileDefense).where(MissileDefense.id.in_(defense_ids)))
    # Land armies and occupations keep their history without the vanished base.
    from game.land_war_models import LandArmy,Occupation
    session.execute(update(LandArmy).where(LandArmy.source_base_id==base.id).values(source_base_id=None))
    session.execute(update(LandArmy).where(LandArmy.target_base_id==base.id).values(target_base_id=None))
    session.execute(update(Occupation).where(Occupation.base_id==base.id).values(base_id=None))
