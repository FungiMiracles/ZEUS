from game.paga_ai_actor import country_user_id
"""Trwałe loty, odległości i jednokrotne rozliczanie trafień miast."""
from game.governance import army_for_country, controller_id, controlled_ids
from datetime import timedelta
from math import hypot
from secrets import randbelow
from sqlalchemy import select,func,or_,and_
from sqlalchemy.orm import lazyload
from game.finance_service import FinanceError,game_now
from game.military_models import MilitaryBase,MilitaryFlight,MilitaryOrder,MapCalibration,MilitaryVessel,MissileDefense
from game.military_geography import city_point,region_point
from models import Miasto,Panstwo,MiastoStateHistory

# Prędkości rakiet (km/h, administrator 12 Nov 2026): krótkiego 1800, średniego 2400, dalekiego zasięgu 5200.
MISSILE_FLIGHT = {'short':(0,500,1800),'medium':(500,2000,2400),'long':(2000,10000,5200)}
FIGHTER_SPEED = 900
FIGHTER_RANGE = 1000     # 12 Nov 2026: myśliwiec atakuje każdy cel w promieniu 1000 km, niezależnie od rodzaju rakiet
CARRIER_FIGHTERS = 5     # pojemność lotniskowca
MAX_SALVO = 10000


def calibration(session):
    scale=session.get(MapCalibration,1)
    if scale is None or scale.km_per_unit<=0:
        raise FinanceError('Skala mapy nie została skonfigurowana.')
    return scale


def distance_km(session,a,b):
    return hypot(b[0]-a[0],b[1]-a[1])*calibration(session).km_per_unit


def busy_fighters(session,base_id,now=None):
    flying=session.scalar(select(func.count()).select_from(MilitaryFlight).where(
        MilitaryFlight.source_base_id==base_id,MilitaryFlight.kind=='air',MilitaryFlight.returned_at.is_(None),MilitaryFlight.returns_at>(now or game_now()),
    )) or 0
    return flying+carrier_fighters(session,base_id)


def carrier_fighters(session,base_id):
    """Myśliwce bazy powietrznej zaokrętowane na lotniskowcach będących na morzu."""
    return int(session.scalar(select(func.coalesce(func.sum(MilitaryVessel.fighters),0)).where(
        MilitaryVessel.air_base_id==base_id,MilitaryVessel.kind=='carriers',MilitaryVessel.status.in_(['sailing','stationed','returning']))) or 0)


def carrier_flights(session,vessel_id,now=None):
    return session.scalar(select(func.count()).select_from(MilitaryFlight).where(
        MilitaryFlight.source_vessel_id==vessel_id,MilitaryFlight.kind=='air',MilitaryFlight.returned_at.is_(None),MilitaryFlight.returns_at>(now or game_now()))) or 0


def launch_flight(session,country_id,army,target,order,data):
    from game.military_service import MISSILES,natural
    now=game_now()
    vessel=None;carrier=None
    if order.kind=='naval' and data.get('vessel_id') is not None:
        from game.military_navy import attack_vessel
        vessel=attack_vessel(session,country_id,data.get('vessel_id'),now)
        if vessel.kind=='carriers':raise FinanceError('Z lotniskowca atakuje się z powietrza — wybierz „Bombarduj z powietrza”.')
    if order.kind=='air' and data.get('carrier_id') is not None:
        from game.military_navy import attack_vessel
        vessel=carrier=attack_vessel(session,country_id,data.get('carrier_id'),now)
        if carrier.kind!='carriers':raise FinanceError('Wybierz lotniskowiec.')
        if carrier.fighters-carrier_flights(session,carrier.id,now)<1:raise FinanceError('Wszystkie myśliwce lotniskowca wykonują misję.')
    base_id=None if carrier else vessel.base_id if vessel else natural(data.get('source_base_id'),'Baza startowa',1)
    base=session.scalar(select(MilitaryBase).where(MilitaryBase.id==base_id,MilitaryBase.panstwo_id==country_id).with_for_update()) if base_id else None
    if vessel is None and (base is None or base.map_x is None or base.map_y is None or base.health<=0):
        raise FinanceError('Wybierz własną, sprawną bazę ze wskazaną lokalizacją.')
    from game.land_war import require_usable_base
    require_usable_base(session,base_id)
    if data.get('silo_id'):require_usable_base(session,data.get('silo_id'))
    expected={'missile':('land','launchers'),'air':('air','fighters'),'naval':('naval','warships')}
    kind,resource=expected[order.kind]
    nuclear=data.get('is_nuclear',False)
    if not isinstance(nuclear,bool):raise FinanceError('Nieprawidłowy rodzaj głowicy.')
    if nuclear and order.kind!='missile':raise FinanceError('Uderzenie atomowe jest możliwe wyłącznie rakietą z głowicą nuklearną odpaloną z silosu na terytorium kraju.')
    if nuclear and order.kind=='missile':kind,resource='nuclear','warheads'
    if vessel is None:
        available=base.garrison.get(resource,0)-(busy_fighters(session,base.id,now) if order.kind=='air' else 0)
        if not base.operational or base.kind!=kind or available<1:
            raise FinanceError('Wybrana baza nie ma dostępnego sprzętu wymaganego do tego ataku.')
    city_id=data.get('city_id')
    city=None
    if city_id is not None:
        city=session.scalar(select(Miasto).options(lazyload('*')).where(Miasto.miasto_id==natural(city_id,'Miasto',1),Miasto.region_id==target.region_id,Miasto.panstwo_id==target.panstwo_id))
        if city is None:
            raise FinanceError('Miasto nie należy do atakowanego regionu i państwa.')
    from game.commerce_models import Mine,TradeShipment
    from game.mining_service import NAMES
    from game.research_models import AmmunitionFactory
    from game.industry_models import PowerPlant
    target_power=session.get(PowerPlant,data['target_power_id']) if data.get('target_power_id') is not None else None
    target_factory=session.get(AmmunitionFactory,data['target_factory_id']) if data.get('target_factory_id') is not None else None
    target_shipment=session.get(TradeShipment,data['target_shipment_id']) if data.get('target_shipment_id') is not None else None
    target_defense=session.get(MissileDefense,data['target_defense_id']) if data.get('target_defense_id') is not None else None
    target_mine=session.get(Mine,data['target_mine_id']) if data.get('target_mine_id') is not None else None
    target_base=session.get(MilitaryBase,data['target_base_id']) if data.get('target_base_id') is not None else None
    target_vessel=session.get(MilitaryVessel,data['target_vessel_id']) if data.get('target_vessel_id') is not None else None
    from game.radar_models import Radar
    target_radar=session.get(Radar,data['target_radar_id']) if data.get('target_radar_id') is not None else None
    from game.airport_models import Airport
    target_airport=session.get(Airport,data['target_airport_id']) if data.get('target_airport_id') is not None else None
    # 22 Nov 2026: wroga armia maszerująca po naszym terytorium
    from game.land_war_models import LandArmy
    target_army=session.get(LandArmy,data['target_army_id']) if data.get('target_army_id') is not None else None
    if target_army is not None:
        from game.land_war import army_position
        destination=list(army_position(target_army,now))
    elif target_airport is not None:
        destination=[target_airport.map_x,target_airport.map_y]
    elif target_radar is not None:
        destination=[target_radar.map_x,target_radar.map_y]
    elif target_power is not None:
        destination=[target_power.map_x,target_power.map_y]
    elif target_factory is not None:
        destination=[target_factory.map_x,target_factory.map_y]
    elif target_shipment is not None:
        from game.trade_navigation import shipment_position
        destination=shipment_position(target_shipment,now)
    elif target_defense is not None:
        from game.missile_defense import defense_data
        destination=defense_data(target_defense)['position']
    elif target_vessel is not None:
        from game.military_navy import vessel_position
        destination=vessel_position(target_vessel,now)
    else:destination=[target_mine.map_x,target_mine.map_y] if target_mine else [target_base.map_x,target_base.map_y] if target_base else city_point(city.miasto_id) if city else region_point(target.region_id)
    target_name=target_army_name(session,target_army) if target_army else target_airport.name if target_airport else f'Radar #{target_radar.id}' if target_radar else (__import__('game.industry_catalog',fromlist=['POWER_PLANTS']).POWER_PLANTS[target_power.kind]['label']+f' #{target_power.id}') if target_power else f'Fabryka amunicji #{target_factory.id}' if target_factory else f'Statek handlowy #{target_shipment.id}' if target_shipment else f'Obrona przeciwrakietowa #{target_defense.id}' if target_defense else (NAMES[target_mine.resource]+f' #{target_mine.id}') if target_mine else (target_base.name or f'Baza #{target_base.id}') if target_base else (target_vessel.name or f'Okręt #{target_vessel.id}') if target_vessel else city.miasto_nazwa if city else target.region_nazwa
    if destination is None:
        raise FinanceError('Brak współrzędnych celu na mapie.')
    source=[base.map_x,base.map_y] if base else None
    if vessel is not None:
        from game.military_navy import vessel_position
        source=vessel_position(vessel,now)
    low,high,speed=MISSILE_FLIGHT[order.payload['missile_type']]
    if nuclear:
        from game.nuclear import RANGE_KM,SPEED_KMH
        low,high,speed=0,RANGE_KM,SPEED_KMH   # 13 Nov 2026: rakieta z głowicą nuklearną — 3000 km od silosu
    if target_vessel is not None:
        from game.military_navy import vessel_position,VESSEL_SPEED
        attack_speed=FIGHTER_SPEED if order.kind=='air' else speed
        distance=distance_km(session,source,vessel_position(target_vessel,now))
        lo,hi=0,max(1,distance/(attack_speed-VESSEL_SPEED)*3600)
        for _ in range(45):
            middle=(lo+hi)/2;point=vessel_position(target_vessel,now+timedelta(seconds=middle))
            if distance_km(session,source,point)>middle*attack_speed/3600:lo=middle
            else:hi=middle
        destination=vessel_position(target_vessel,now+timedelta(seconds=hi))
    if target_army is not None:
        from game.land_war import catch_up
        meeting=catch_up(session,source,target_army,FIGHTER_SPEED if order.kind=='air' else speed,now)
        if meeting is None:raise FinanceError('Armia dotrze do celu, zanim atak będzie mógł ją dosięgnąć.')
        destination=list(meeting[1])
    if target_shipment is not None:
        from game.trade_navigation import shipment_position
        attack_speed=FIGHTER_SPEED if order.kind=='air' else speed
        remaining=(target_shipment.arrives_at-now).total_seconds();lo,hi=0.,remaining
        if distance_km(session,source,shipment_position(target_shipment,target_shipment.arrives_at))>=remaining*attack_speed/3600:raise FinanceError('Statek dotrze do portu, zanim pocisk będzie mógł go dosięgnąć.')
        for _ in range(45):
            middle=(lo+hi)/2;point=shipment_position(target_shipment,now+timedelta(seconds=middle))
            if distance_km(session,source,point)>middle*attack_speed/3600:lo=middle
            else:hi=middle
        destination=shipment_position(target_shipment,now+timedelta(seconds=hi))
    distance=distance_km(session,source,destination)
    if order.kind=='air':
        if distance>FIGHTER_RANGE+1e-6:raise FinanceError(f'Cel jest w odległości {distance:.1f} km. Zasięg myśliwca: {FIGHTER_RANGE} km.')
    elif not low-1e-6<=distance<=high+1e-6:
        raise FinanceError(f'Cel jest w odległości {distance:.1f} km. Zasięg wybranego rodzaju rakiety: {low}–{high} km.')
    count=order.payload['missiles']
    if count>MAX_SALVO:
        raise FinanceError(f'Jeden rozkaz może obejmować najwyżej {MAX_SALVO} rakiet.')
    if not nuclear:   # rakieta atomowa nie zużywa dodatkowej rakiety konwencjonalnej (13 Nov 2026)
        field=MISSILES[order.payload['missile_type']][0]
        if count>(getattr(army,field) or 0):
            raise FinanceError('Za mało rakiet wybranego rodzaju.')
        setattr(army,field,(getattr(army,field) or 0)-count)
    if nuclear:
        silo_id=base.id if order.kind=='missile' else natural(data.get('silo_id'),'Silos atomowy',1)
        silo=session.scalar(select(MilitaryBase).where(MilitaryBase.id==silo_id,MilitaryBase.panstwo_id==country_id,MilitaryBase.kind=='nuclear').with_for_update())
        from game.nuclear import total,change_total
        if silo is None or not silo.operational or silo.health<=0 or silo.map_x is None or silo.garrison.get('warheads',0)<count or total(session,country_id)<count:
            raise FinanceError('Za mało rakiet z głowicą nuklearną w sprawnym, rozmieszczonym silosie atomowym.')
        silo.garrison={**silo.garrison,'warheads':silo.garrison['warheads']-count}
        change_total(session,country_id,-count)
    duration=max(1,distance/(FIGHTER_SPEED if order.kind=='air' else speed)*3600)
    impact=now+timedelta(seconds=duration)
    if target_shipment is not None and impact>=target_shipment.arrives_at:raise FinanceError('Statek dotrze do portu przed trafieniem.')
    if target_army is not None and impact>=target_army.arrives_at:raise FinanceError('Armia dotrze do celu przed trafieniem.')
    fighter_seconds=max(1,distance/FIGHTER_SPEED*3600)
    order.payload={**order.payload,'source_base_id':base.id if base else None,'city_id':city.miasto_id if city else None,
                   'target_name':target_name,**({'target_army_id':target_army.id} if target_army is not None else {})}
    if target_army is not None:attacked_country=target_army.panstwo_id
    elif target_shipment is not None:
        from game.trade_navigation import target_country
        attacked_country=target_country(session,target_shipment,country_id)
    elif target_mine is not None:attacked_country=controller_id(session,target_mine.panstwo_id)
    else:attacked_country=controller_id(session,target.panstwo_id)
    flight=MilitaryFlight(target_airport_id=target_airport.id if target_airport else None,target_radar_id=target_radar.id if target_radar else None,target_power_id=target_power.id if target_power else None,target_factory_id=target_factory.id if target_factory else None,target_shipment_id=target_shipment.id if target_shipment else None,order_id=order.id,panstwo_id=country_id,target_country_id=attacked_country,
        source_base_id=base.id if base else None,source_vessel_id=vessel.id if vessel else None,is_nuclear=nuclear,city_id=city.miasto_id if city else None,target_defense_id=target_defense.id if target_defense else None,target_mine_id=target_mine.id if target_mine else None,target_kind='army' if target_army else 'airport' if target_airport else 'radar' if target_radar else 'power' if target_power else 'factory' if target_factory else 'shipment' if target_shipment else 'defense' if target_defense else 'mine' if target_mine else 'base' if target_base else 'vessel' if target_vessel else 'city' if city else 'region',target_name=target_name,target_base_id=target_base.id if target_base else None,target_vessel_id=target_vessel.id if target_vessel else None,kind=order.kind,
        missile_type=order.payload['missile_type'],missiles=count,
        source_x=source[0],source_y=source[1],target_x=destination[0],target_y=destination[1],distance_km=distance,
        starts_at=now,impact_at=impact,
        fighter_arrives_at=now+timedelta(seconds=fighter_seconds) if order.kind=='air' else None,
        returns_at=max(impact,now+timedelta(seconds=fighter_seconds))+timedelta(seconds=fighter_seconds) if order.kind=='air' else None)
    session.add(flight);session.flush()
    if nuclear and attacked_country!=country_id:
        # 13 Nov 2026: odpalenie rakiety z głowicą nuklearną w kierunku innego państwa — powiadomienie do wszystkich państw
        from game.nuclear import broadcast,country_name
        broadcast(session,f'Uderzenie atomowe: {country_name(session,country_id)} wystrzeliło {count} szt. rakiet z głowicą nuklearną w kierunku państwa {country_name(session,attacked_country)} (cel: {target_name}).',exclude=(country_id,))
    return flight.id


def target_army_name(session,army):
    name=session.scalar(select(Panstwo.panstwo_nazwa).where(Panstwo.PANSTWO_ID==army.panstwo_id)) or 'przeciwnika'
    return f'Armia państwa {name} (cel: {army.target_name})'[:255]


def sink_carrier(session,vessel,army):
    """Zatopiony lotniskowiec: tracony jest lotniskowiec i wszystkie zaokrętowane myśliwce."""
    if army:
        army.lotniskowce_ilosc=max(0,(army.lotniskowce_ilosc or 0)-1)
        army.mysliwce_ilosc=max(0,(army.mysliwce_ilosc or 0)-(vessel.fighters or 0))
    base=session.get(MilitaryBase,vessel.air_base_id) if vessel.air_base_id else None
    if base:base.garrison={**base.garrison,'fighters':max(0,base.garrison.get('fighters',0)-(vessel.fighters or 0))}
    vessel.fighters=0


def roll_casualties(missiles):
    return sum(randbelow(101) for _ in range(missiles))


def complete_flights(session,now,country_id=None,*,shipment_ids=None,factory_ids=None,lock_country_ids=(),army_strikes=False):
    query=select(MilitaryFlight).where(or_(and_(MilitaryFlight.impacted_at.is_(None),MilitaryFlight.impact_at<=now),
        and_(MilitaryFlight.kind=='air',MilitaryFlight.returned_at.is_(None),MilitaryFlight.returns_at<=now)))
    if army_strikes:query=query.where(MilitaryFlight.target_kind=='army',MilitaryFlight.impacted_at.is_(None))
    from game.commerce_models import TradeShipment
    if factory_ids is not None:query=query.where(MilitaryFlight.target_factory_id.in_(factory_ids))
    if shipment_ids is not None:query=query.where(MilitaryFlight.target_shipment_id.in_(shipment_ids))
    if country_id is not None:
        related=select(TradeShipment.id).where(or_(TradeShipment.seller_id==country_id,TradeShipment.buyer_id==country_id))
        query=query.where(or_(MilitaryFlight.panstwo_id==country_id,MilitaryFlight.target_country_id==country_id,MilitaryFlight.target_shipment_id.in_(related)))
    due=list(session.execute(query.with_only_columns(MilitaryFlight.id,MilitaryFlight.target_country_id,MilitaryFlight.panstwo_id)))
    if not due:return
    country_ids={row.target_country_id for row in due}|{row.panstwo_id for row in due}|set(lock_country_ids)
    for seller,buyer in session.execute(select(TradeShipment.seller_id,TradeShipment.buyer_id).join(MilitaryFlight,MilitaryFlight.target_shipment_id==TradeShipment.id).where(MilitaryFlight.id.in_([row.id for row in due]))):country_ids.update((seller,buyer))
    if country_id is not None:country_ids.add(country_id)
    list(session.scalars(select(Panstwo.PANSTWO_ID).where(Panstwo.PANSTWO_ID.in_(country_ids)).order_by(Panstwo.PANSTWO_ID).with_for_update()))
    for flight in session.scalars(query.where(MilitaryFlight.id.in_([row.id for row in due])).order_by(MilitaryFlight.impact_at,MilitaryFlight.id).with_for_update().execution_options(populate_existing=True)):
        if flight.impacted_at is None and flight.impact_at<=now:
            if flight.target_kind=='region':
                flight.target_kind='defense' if flight.target_defense_id else 'mine' if flight.target_mine_id else 'base' if flight.target_base_id else 'vessel' if flight.target_vessel_id else 'city' if flight.city_id else 'region'
            casualties=0
            order=session.get(MilitaryOrder,flight.order_id)
            region_id=order.region_id
            hits=flight.missiles
            damage={}
            from game.missile_defense import intercept
            if flight.target_kind not in ('vessel','shipment','army'):
                hits=intercept(session,flight,region_id,flight.target_kind,flight.target_airport_id or flight.target_radar_id or flight.target_power_id or flight.target_factory_id or flight.target_defense_id or flight.target_base_id or flight.target_mine_id or flight.city_id or region_id)
            flight.intercepted=flight.missiles-hits
            if flight.is_nuclear:
                from game.nuclear import detonate
                damage,casualties=detonate(session,flight,order,hits)   # 13 Nov 2026: skażenie 100 km, zniszczenia, skutki w regionie
            else:damage=apply_structural_damage(session,flight,order,hits)
            if flight.city_id is not None and not flight.is_nuclear:
                city=session.scalar(select(Miasto).options(lazyload('*')).where(Miasto.miasto_id==flight.city_id).with_for_update())
                country=session.scalar(select(Panstwo).options(lazyload('*')).where(Panstwo.PANSTWO_ID==city.panstwo_id).with_for_update()) if city is not None else None
                if city is not None:
                    before=max(0,city.miasto_populacja or 0)
                    casualties=min(before,roll_casualties(hits))
                    city.miasto_populacja=before-casualties
                    if country is not None and country.panstwo_populacja is not None:
                        country.panstwo_populacja=max(0,country.panstwo_populacja-casualties)
                    if casualties:
                        from game.models import utc_now
                        session.add(MiastoStateHistory(miasto_id=city.miasto_id,data_entenda=flight.impact_at.date(),
                            data_rzeczywista=utc_now(),source='MILITARY_STRIKE',event_id=None,
                            old_miasto_populacja=before,new_miasto_populacja=before-casualties,change_delta=-casualties))
            flight.damage=damage
            flight.casualties=casualties
            flight.impacted_at=now
            notify_impact(session,flight)
            if flight.kind!='air':flight.returned_at=now
        if flight.kind=='air' and flight.returns_at<=now:flight.returned_at=now
    session.flush()


def flight_data(flight):
    stamp=lambda value:value.isoformat()+'Z' if value else None
    return {'id':flight.id,'kind':flight.kind,'isNuclear':flight.is_nuclear,'intercepted':flight.intercepted,'damage':flight.damage,'sourceBaseId':flight.source_base_id,'countryId':flight.panstwo_id,
        'targetName':flight.target_name,'targetCountryId':flight.target_country_id,'cityId':flight.city_id,'missileType':flight.missile_type,'missiles':flight.missiles,
        'source':[flight.source_x,flight.source_y],'target':[flight.target_x,flight.target_y],'distanceKm':flight.distance_km,
        'startsAt':stamp(flight.starts_at),'impactAt':stamp(flight.impact_at),'fighterArrivesAt':stamp(flight.fighter_arrives_at),
        'returnsAt':stamp(flight.returns_at),'impactedAt':stamp(flight.impacted_at),'returnedAt':stamp(flight.returned_at),'casualties':flight.casualties}


def notify_impact(session,flight):
    from game.models import GamePlayerCountry,utc_now
    from game.forum_models import GameNotification
    names=dict(session.execute(select(Panstwo.PANSTWO_ID,Panstwo.panstwo_nazwa).where(Panstwo.PANSTWO_ID.in_([flight.panstwo_id,flight.target_country_id]))).all())
    effect=nuclear_summary(flight) if flight.is_nuclear else impact_summary(flight)
    for country_id,prefix in [(flight.panstwo_id,f'Zakończono nasz atak na cel: {flight.target_name} ({names.get(flight.target_country_id,"państwo przeciwnika")}).'),
                              (flight.target_country_id,f'Państwo {names.get(flight.panstwo_id,"przeciwnika")} przeprowadziło atak na cel: {flight.target_name}.')]:
        owner=country_user_id(session,country_id)
        if owner is not None:
            session.add(GameNotification(user_id=owner,notification_type='SYSTEM',system_text=f'{prefix} Liczba pocisków: {flight.missiles}. {effect}',created_at=utc_now()))


def nuclear_summary(flight):
    damage=flight.damage or {}
    if not damage.get('nuclear'):return f'Przechwycono: {flight.intercepted or 0} z {flight.missiles}. Rakieta nie dotarła do celu — brak skażenia.'
    destroyed=damage.get('destroyed') or {}
    lost=', '.join(f'{label}: {destroyed[key]}' for key,label in [('bases','bazy'),('factories','fabryki'),('power','elektrownie'),('airports','lotniska'),('mines','kopalnie'),('radars','radary'),('defenses','obrona przeciwrakietowa'),('vessels','okręty')] if destroyed.get(key))
    return (f'Przechwycono: {flight.intercepted or 0} z {flight.missiles}. Wybuch jądrowy: skażenie w promieniu {damage.get("zoneRadiusKm",100)} km na 3 lata Entendy, '
            f'zginęło {flight.casualties or 0:,} mieszkańców miast'.replace(',',' ')+(f'; zniszczone obiekty — {lost}' if lost else '')+'.')


def apply_structural_damage(session,flight,order,hits):
    from game.infrastructure_service import FIELDS
    from models import Region,Wojsko
    damage={}
    if not hits:return damage
    if flight.target_kind=='defense':
        defense=session.scalar(select(MissileDefense).where(MissileDefense.id==flight.target_defense_id,MissileDefense.panstwo_id==flight.target_country_id).with_for_update())
        if defense is not None:
            loss=min(defense.health,sum(3+randbelow(7) for _ in range(hits)))
            defense.health-=loss
            damage={'defenseHealthLost':loss,'remainingHealth':defense.health,'defenseDestroyed':defense.health==0}
    elif flight.target_kind=='base':
        base=session.scalar(select(MilitaryBase).where(MilitaryBase.id==flight.target_base_id,MilitaryBase.panstwo_id==flight.target_country_id).with_for_update())
        if base is not None:
            loss=min(base.health,sum(4+randbelow(12) for _ in range(hits)));base.health-=loss
            damage={'baseHealthLost':loss,'remainingHealth':base.health,'baseDestroyed':base.health==0}
            if base.health==0:
                from game.military_destruction import destroy_base
                destroy_base(session,base,game_now())
    elif flight.target_kind=='mine':
        from game.commerce_models import Mine,MiningExpense
        from sqlalchemy import update
        mine=session.scalar(select(Mine).where(Mine.id==flight.target_mine_id,Mine.panstwo_id==flight.target_country_id).with_for_update())
        if mine is not None:
            loss=min(mine.health,sum(4+randbelow(12) for _ in range(hits)));mine.health-=loss
            damage={'mineHealthLost':loss,'remainingHealth':mine.health,'mineDestroyed':mine.health==0}
            if mine.health==0:
                from sqlalchemy import delete
                from game.military_models import MissileDefenseExpense
                defense_ids=list(session.scalars(select(MissileDefense.id).where(MissileDefense.target_kind=='mine',MissileDefense.target_id==mine.id)))
                if defense_ids:
                    session.execute(update(MilitaryFlight).where(MilitaryFlight.target_defense_id.in_(defense_ids)).values(target_defense_id=None))
                    session.execute(update(MissileDefenseExpense).where(MissileDefenseExpense.defense_id.in_(defense_ids)).values(defense_id=None))
                    session.execute(delete(MissileDefense).where(MissileDefense.id.in_(defense_ids)))
                session.execute(update(MiningExpense).where(MiningExpense.mine_id==mine.id).values(mine_id=None))
                session.execute(update(MilitaryFlight).where(MilitaryFlight.target_mine_id==mine.id).values(target_mine_id=None))
                from game.industry_service import change_pollution
                if mine.pollution_points:change_pollution(session,mine.region_id,-mine.pollution_points)
                session.delete(mine);session.flush()
    elif flight.target_kind=='radar':
        from game.radar_models import Radar
        radar=session.scalar(select(Radar).where(Radar.id==flight.target_radar_id,Radar.panstwo_id==flight.target_country_id).with_for_update()) if flight.target_radar_id else None
        if radar is not None and radar.health>0:
            loss=min(radar.health,sum(4+randbelow(12) for _ in range(hits)));radar.health-=loss
            damage={'radarHealthLost':loss,'remainingHealth':radar.health,'radarDestroyed':radar.health==0}
            if radar.health==0:
                # A destroyed radar stops detecting; its missile defence is lost with it (as with a destroyed factory).
                from sqlalchemy import update,delete
                from game.military_models import MissileDefenseExpense
                ids=list(session.scalars(select(MissileDefense.id).where(MissileDefense.target_kind=='radar',MissileDefense.target_id==radar.id)))
                if ids:
                    session.execute(update(MilitaryFlight).where(MilitaryFlight.target_defense_id.in_(ids)).values(target_defense_id=None))
                    session.execute(update(MissileDefenseExpense).where(MissileDefenseExpense.defense_id.in_(ids)).values(defense_id=None))
                    session.execute(delete(MissileDefense).where(MissileDefense.id.in_(ids)))
        else:damage={'targetUnavailable':True}
    elif flight.target_kind=='airport':
        # 20 Nov 2026: lotnisko — 4–15 pkt życia na trafienie; życie 0 = zniszczone (połączenia i handel lotniczy ustają)
        from game.airport_models import Airport
        airport=session.scalar(select(Airport).where(Airport.id==getattr(flight,'target_airport_id',None)).with_for_update()) if getattr(flight,'target_airport_id',None) else None
        if airport is not None and airport.health>0 and airport.removed_at is None and controller_id(session,airport.panstwo_id)==flight.target_country_id:
            loss=min(airport.health,sum(4+randbelow(12) for _ in range(hits)));airport.health-=loss
            damage={'airportHealthLost':loss,'remainingHealth':airport.health,'airportDestroyed':airport.health==0}
            if airport.health==0:
                from game.airports import destroy,notify as airport_notify
                destroy(session,airport,flight.impact_at)
                airport_notify(session,airport.panstwo_id,f'{airport.name} zostało zniszczone w ataku. Połączenia lotnicze z tego lotniska ustały.')
        else:damage={'targetUnavailable':True}
    elif flight.target_kind=='power':
        from game.industry_models import PowerPlant
        from game.industry_service import settle_industry,notify
        plant=session.scalar(select(PowerPlant).where(PowerPlant.id==flight.target_power_id,PowerPlant.panstwo_id==flight.target_country_id).with_for_update())
        if plant is not None and plant.health>0 and plant.removed_at is None:
            settle_industry(session,plant.panstwo_id,flight.impact_at)
            loss=min(plant.health,hits);plant.health-=loss;plant.running=False
            if plant.ever_worked:notify(session,plant.panstwo_id,f'Elektrownia #{plant.id}: produkcja energii wstrzymana po trafieniu.')
            damage={'powerHealthLost':loss*100/3,'remainingHealth':plant.health*100/3,'powerDestroyed':plant.health==0}
        else:damage={'targetUnavailable':True}
    elif flight.target_kind=='factory':
        from game.research_models import AmmunitionFactory
        factory=session.scalar(select(AmmunitionFactory).where(AmmunitionFactory.id==flight.target_factory_id,AmmunitionFactory.panstwo_id==flight.target_country_id).with_for_update())
        if factory is not None and factory.health>0 and factory.removed_at is None:
            from game.research_service import settle_production
            settle_production(session,factory.panstwo_id,flight.impact_at,resolve_attacks=False)
            loss=min(factory.health,hits*11);factory.health-=loss
            damage={'factoryHealthLost':loss,'remainingHealth':factory.health,'factoryDestroyed':factory.health==0}
            if factory.health==0:
                factory.destroyed_at=flight.impact_at
                from sqlalchemy import update,delete
                from game.military_models import MissileDefenseExpense
                ids=list(session.scalars(select(MissileDefense.id).where(MissileDefense.target_kind=='factory',MissileDefense.target_id==factory.id)))
                if ids:
                    session.execute(update(MilitaryFlight).where(MilitaryFlight.target_defense_id.in_(ids)).values(target_defense_id=None))
                    session.execute(update(MissileDefenseExpense).where(MissileDefenseExpense.defense_id.in_(ids)).values(defense_id=None))
                    session.execute(delete(MissileDefense).where(MissileDefense.id.in_(ids)))
        else:damage={'targetUnavailable':True}
    elif flight.target_kind=='shipment':
        from game.commerce_models import TradeShipment
        ship=session.scalar(select(TradeShipment).where(TradeShipment.id==flight.target_shipment_id).with_for_update())
        from game.trade_routes import mode_at   # 22 Nov 2026: trafienie tylko statku na morzu (nie pociągu ani samolotu)
        if ship is not None and ship.health>0 and ship.sunk_at is None and ship.delivered_at is None and flight.impact_at<ship.arrives_at and mode_at(ship,flight.impact_at)=='sea':
            loss=min(ship.health,sum(4+randbelow(12) for _ in range(hits)));ship.health-=loss
            if ship.health==0:ship.sunk_at=flight.impact_at
            damage={'shipmentHealthLost':loss,'remainingHealth':ship.health,'sunk':ship.health==0}
            from game.forum_models import GameNotification
            from game.models import GamePlayerCountry,utc_now
            for country in {ship.seller_id,ship.buyer_id}-{flight.target_country_id,flight.panstwo_id}:
                user=country_user_id(session,country)
                if user is not None:session.add(GameNotification(user_id=user,notification_type='SYSTEM',system_text=f'Atak na statek handlowy #{ship.id}: utracono {loss} pkt życia. '+('Statek zatonął, ładunek został utracony.' if ship.health==0 else f'Pozostało {ship.health}% życia.'),created_at=utc_now()))
        else:damage={'targetUnavailable':True}
    elif flight.target_kind=='vessel':
        vessel=session.scalar(select(MilitaryVessel).where(MilitaryVessel.id==flight.target_vessel_id,MilitaryVessel.panstwo_id==flight.target_country_id).with_for_update())
        if vessel is not None and vessel.status in ('sailing','stationed','returning'):
            loss=min(vessel.health,sum(4+randbelow(12) for _ in range(hits)));vessel.health-=loss
            damage={'vesselHealthLost':loss,'remainingHealth':vessel.health,'sunk':vessel.health==0}
            if vessel.health==0:
                army=army_for_country(session, vessel.panstwo_id, lock=True)
                if vessel.kind=='carriers':sink_carrier(session,vessel,army)
                else:
                    base=session.get(MilitaryBase,vessel.base_id)
                    if base:base.garrison={**base.garrison,vessel.kind:max(0,base.garrison.get(vessel.kind,0)-1)}
                    if army:
                        field='okrety_wojenne_ilosc' if vessel.kind=='warships' else 'okrety_podwodne_ilosc'
                        setattr(army,field,max(0,(getattr(army,field) or 0)-1))
                vessel.status='sunk'
        else:damage={'targetUnavailable':True}
    elif flight.target_kind=='army':
        from game.land_war import strike_army
        from game.land_war_models import LandArmy
        army_id=(order.payload or {}).get('target_army_id')
        army=session.scalar(select(LandArmy).where(LandArmy.id==army_id).with_for_update()) if army_id else None
        damage=strike_army(session,army,hits,flight.impact_at)
        if damage.get('targetUnavailable'):damage['armyGone']=True
    elif flight.target_kind=='region':
        metric=order.payload.get('infrastructure');field=FIELDS.get(metric)
        region=session.scalar(select(Region).options(lazyload('*')).where(Region.region_id==order.region_id,Region.panstwo_id.in_(controlled_ids(session,flight.target_country_id))).with_for_update())
        if field and region is not None:
            before=max(0,getattr(region,field) or 0);after=max(0,before-hits);setattr(region,field,after)
            damage={'infrastructure':metric,'infrastructurePoints':before-after,'before':before,'after':after}
    return damage


def impact_summary(flight):
    damage=flight.damage or {}
    text=f'Przechwycono: {flight.intercepted or 0} z {flight.missiles}. Ofiary: {flight.casualties or 0}. '
    if damage.get('armyGone'):return text+'Armia nie była już w marszu — brak strat.'
    if 'armyLosses' in damage:
        from game.land_war import units_text
        text+=f'Straty armii w marszu: {units_text(damage["armyLosses"])}. '
        return text+('Armia została rozbita.' if damage.get('armyDestroyed') else f'Pozostało: {units_text(damage["remaining"])}.')
    if 'powerHealthLost' in damage:
        text+=f'Uszkodzenie elektrowni: {damage["powerHealthLost"]:.2f}%. Pozostało: {damage["remainingHealth"]:.2f}% życia.'
    if 'radarHealthLost' in damage:
        text+=f'Uszkodzenie radaru: {damage["radarHealthLost"]} pkt życia. Pozostało: {damage["remainingHealth"]}/100.'
        if damage.get('radarDestroyed'):text+=' Radar został zniszczony i nie wykrywa obiektów.'
    elif 'airportHealthLost' in damage:
        text+=f'Uszkodzenie lotniska: {damage["airportHealthLost"]} pkt życia. Pozostało: {damage["remainingHealth"]}/100.'
        if damage.get('airportDestroyed'):text+=' Lotnisko zostało zniszczone.'
    elif 'factoryHealthLost' in damage:
        text+=f'Uszkodzenie fabryki: {damage["factoryHealthLost"]}% życia. Pozostało: {damage["remainingHealth"]}%.'
        if damage.get('factoryDestroyed'):text+=' Fabryka została zniszczona i nie produkuje amunicji.'
    elif 'shipmentHealthLost' in damage:
        text+=f'Uszkodzenie statku handlowego: {damage["shipmentHealthLost"]} pkt życia. Pozostało: {damage["remainingHealth"]}/100.'
        if damage.get('sunk'):text+=' Statek zatonął wraz z ładunkiem.'
    elif 'mineHealthLost' in damage:
        text+=f'Uszkodzenie kopalni: {damage["mineHealthLost"]} pkt życia. Pozostało: {damage["remainingHealth"]}/100.'
        if damage.get('mineDestroyed'):text+=' Kopalnia została zniszczona.'
    elif 'defenseHealthLost' in damage:
        text+=f'Uszkodzenie obrony przeciwrakietowej: {damage["defenseHealthLost"]}% życia. Pozostało: {damage["remainingHealth"]}%.'
        if damage.get('defenseDestroyed'):text+=' Obrona jest niesprawna i wymaga naprawy.'
    elif 'baseHealthLost' in damage:
        text+=f'Uszkodzenie bazy: {damage["baseHealthLost"]} pkt życia. Pozostało: {damage["remainingHealth"]}/100.'
        if damage.get('baseDestroyed'):text+=' Baza została zniszczona.'
    elif 'vesselHealthLost' in damage:
        text+=f'Uszkodzenie okrętu: {damage["vesselHealthLost"]} pkt życia. Pozostało: {damage["remainingHealth"]}/100.'
        if damage.get('sunk'):text+=' Okręt zatopiony.'
    elif 'infrastructure' in damage:
        from game.infrastructure_service import INFRASTRUCTURE_NAMES
        text+=f'Zniszczenia infrastruktury: {damage["infrastructurePoints"]} pkt ({INFRASTRUCTURE_NAMES.get(damage["infrastructure"],damage["infrastructure"])}). Poziom: {damage["before"]} → {damage["after"]}.'
    elif damage.get('targetUnavailable'):text+='Cel nie znajduje się już na morzu.'
    else:text+='Zniszczenia infrastruktury: 0.'
    return text
