"""Ekrany obrony państwa i działań wojennych."""
import hmac
import secrets
from game.governance import army_for_country, controller_id, controlled_ids
from game.governance import controlled_ids, controller_id
from flask import Blueprint, abort, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import select,or_,and_
from sqlalchemy.orm import lazyload
from extensions import db
from game.forum import player
from game.country_summary import country_summary, metropolitan_region_ids
from game.finance_service import FinanceError,game_now
from game.military_models import MilitaryBase,MilitaryFlight,MilitaryVessel,MilitaryMaintenance,MissileDefense
from game.military_flights import complete_flights,flight_data,calibration,busy_fighters,MISSILE_FLIGHT,FIGHTER_SPEED,MAX_SALVO,FIGHTER_RANGE,CARRIER_FIGHTERS
from game.military_navy import carriers_at_sea
from game.military_geography import city_point,region_point
from game.military_navy import vessel_data,settle_vessels,busy_vessels,VESSEL_SPEED
from engine.clock import get_time_multiplier
from game.military_service import (BASES, RESOURCES, CAPACITIES, UPGRADE_COSTS, active_counts,
                                   enemies, military_budget, upkeep_cost, change_defense, reconcile_maintenance, MISSILES, land_targets, create_order)
from models import Region, Miasto, Panstwo, Wojsko

military_bp = Blueprint('game_military', __name__, url_prefix='/game')


def csrf_valid():
    expected = session.get('game_csrf_token','')
    supplied = request.headers.get('X-CSRF-Token','')
    return bool(expected) and hmac.compare_digest(expected.encode(),supplied.encode())


def render_military(mode):
    user,country = player()
    if user is None:
        return redirect(url_for('wejscie'))
    enemy_ids = enemies(db.session,country.PANSTWO_ID)
    if mode == 'war' and not enemy_ids:
        abort(403,description='Panel wojenny jest dostępny wyłącznie podczas wojny.')
    session.setdefault('game_csrf_token',secrets.token_urlsafe(32))
    complete_flights(db.session,game_now(),country.PANSTWO_ID)
    from game.land_war import complete_marches
    complete_marches(db.session,game_now())
    from game.radar import detect as radar_detect,visible_radars,config as radar_config
    radar_detect(db.session,game_now())
    reconcile_maintenance(db.session,country.PANSTWO_ID)
    army = army_for_country(db.session, country.PANSTWO_ID, lock=False)
    regions = db.session.execute(select(Region.region_id,Region.panstwo_id,Region.region_nazwa,Region.region_polozenie_id)).all()
    cities = db.session.execute(select(Miasto.miasto_id,Miasto.miasto_nazwa,Miasto.panstwo_id,Miasto.region_id).where(Miasto.czy_na_mapie == 'TAK')).all()
    bases = list(db.session.scalars(select(MilitaryBase).where(MilitaryBase.panstwo_id == country.PANSTWO_ID).order_by(MilitaryBase.id)))
    budget,total,available = military_budget(db.session,country.PANSTWO_ID)
    from game.finance_service import period_key
    year,period=period_key(game_now())
    current_upkeep=db.session.scalar(select(MilitaryMaintenance.amount).where(MilitaryMaintenance.panstwo_id==country.PANSTWO_ID,MilitaryMaintenance.game_year==year,MilitaryMaintenance.period==period)) or 0
    active = active_counts(bases,db.session,country.PANSTWO_ID)
    from game.base_permits import own_region_ids,ally_regions
    own_regions=own_region_ids(db.session,country.PANSTWO_ID)
    inventory = {}
    for kind,(label,base_field,soldier_field) in BASES.items():
        if kind=='nuclear':
            inventory[kind]={'total':0,'available':100,'label':label+' — budowa: 25 mld ROI'}
            continue
        inventory[kind] = {'total':getattr(army,base_field) or 0 if army else 0,
                           'available':max(0,(getattr(army,base_field) or 0)-active.get(base_field,0)) if army else 0,
                           'label':label}
    from game.trade_navigation import visible_shipments
    response = render_template('game/military.html', game_user=user,game_country=country_summary(country),
        game_home_url=url_for('game_main_page'),game_logout_url=url_for('game_logout'),
        game_active_page='war' if mode == 'war' else 'defense',mode=mode,
        military_config={
            'landTargets':land_targets(db.session,country.PANSTWO_ID) if mode == 'war' else [],
            'missiles':{code:{'label':label,'count':getattr(army,field) or 0 if army else 0} for code,(field,label) in MISSILES.items()},
            'groundInventory':{resource:getattr(army,field) or 0 if army else 0 for resource,field in [('soldiers','wojska_ladowe_ilosc'),('tanks','czolgi_ilosc'),('armored','wozy_opancerzone_ilosc')]},
            'hasWarships':bool(army and (army.okrety_wojenne_ilosc or 0)>0),
            'orderUrl':url_for('game_military.war_order'),'defenseUrl':url_for('game_military.defense_page'),'warUrl':url_for('game_military.war_page'),
            'mode':mode,'countryId':country.PANSTWO_ID,'controlledCountryIds':controlled_ids(db.session,country.PANSTWO_ID),'enemyIds':enemy_ids,
            'metropolitanRegionIds':metropolitan_region_ids(country.PANSTWO_ID),
            'regions':{str(r.region_id):{'name':r.region_nazwa,'countryId':controller_id(db.session,r.panstwo_id),'coastal':r.region_polozenie_id not in (None,1),'point':region_point(r.region_id)} for r in regions},
            'countries':{str(id):name for id,name in db.session.execute(select(Panstwo.PANSTWO_ID,Panstwo.panstwo_nazwa))},
            'cities':{str(c.miasto_id):{'name':c.miasto_nazwa,'countryId':controller_id(db.session,c.panstwo_id),'regionId':str(c.region_id),'point':city_point(c.miasto_id)} for c in cities},
            'bases':[base_data(b,own_regions) for b in bases],
            'allyRegions':ally_regions(db.session,country.PANSTWO_ID) if mode=='defense' else {},
            'diplomacyActionUrl':url_for('game_diplomacy.create_action'),
            'visiblePower':visible_power(country.PANSTWO_ID,mode=='war'),
            'visibleFactories':visible_factories(country.PANSTWO_ID,mode=='war'),'factoryIcon':url_for('static',filename='icons/FABRYKA.svg'),
            'visibleMines':visible_mines(country.PANSTWO_ID,mode=='war'),
            'ammunitionStockUrl':'/game/badania/stan',
            'mineIcon':url_for('static',filename='icons/KOPALNIA.svg'),
            'mineralIcons':__import__('game.commerce',fromlist=['resource_catalog']).resource_catalog(),
            'visibleBases':visible_base_data(country.PANSTWO_ID,mode=='war'),
            'flights':visible_flights(country.PANSTWO_ID),
            'defenses':visible_defenses(country.PANSTWO_ID,mode=='war'),
            'defenseIcon':url_for('static',filename='icons/OBRONA PRZECIWRAKIETOWA.svg'),
            'coastUrl':url_for('game_military.coastline',region_id=0),
            'flags':{str(id):url_for('static',filename='flags/'+(name or '').replace(' ','_')+'.jpg') for id,name in db.session.execute(select(Panstwo.PANSTWO_ID,Panstwo.panstwo_nazwa))},
            'cargoShipIcon':url_for('static',filename='icons/CARGO SHIP.svg'),'tradeShips':visible_shipments(db.session,country.PANSTWO_ID),
            'vessels':visible_vessels(country.PANSTWO_ID,mode=='war'),'vesselSpeed':VESSEL_SPEED,
            'vesselIcons':{kind:url_for('static',filename='icons/'+name) for kind,name in [('warships','OKRĘT WOJENNY.svg'),('submarines','SUBMARINE.svg'),('carriers','LOTNISKOWIEC.svg')]},
            'fighterRange':FIGHTER_RANGE,'carrierCapacity':CARRIER_FIGHTERS,
            'carriersAvailable':max(0,((army.lotniskowce_ilosc or 0) if army else 0)-carriers_at_sea(db.session,country.PANSTWO_ID)),
            'siloIcon':url_for('static',filename='icons/SILOS ATOMOWY.svg'),
            'gameNow':game_now().isoformat()+'Z','timeMultiplier':get_time_multiplier(),
            'kmPerUnit':calibration(db.session).km_per_unit,
            'stateUrl':url_for('game_military.map_state'),
            'missileRules':{code:{'min':low,'max':high,'speed':speed} for code,(low,high,speed) in MISSILE_FLIGHT.items()},
            'fighterSpeed':FIGHTER_SPEED,'maxSalvo':MAX_SALVO,
            'fighterIcon':url_for('static',filename='icons/MYŚLIWIEC.svg'),
            'baseCapacities':{kind:values[0] for kind,values in CAPACITIES.items()},
            'availableGarrison':{kind:{resource:max(0,(getattr(army,BASES[kind][2] if resource=='soldiers' else RESOURCES[resource][1]) or 0)-active.get(BASES[kind][2] if resource=='soldiers' else RESOURCES[resource][1],0)) if army else 0 for resource in CAPACITIES[kind][0]} for kind in BASES},
            'inventory':inventory,'budgetTotal':str(total),'budgetAvailable':str(available),'upkeep':str(current_upkeep),
            'resources':{code:{'label':label,'icon':url_for('static',filename='icons/'+icon)} for code,(label,field,icon) in RESOURCES.items()},
            'csrf':session['game_csrf_token'],'changeUrl':url_for('game_military.defense_change'),
            'regionsUrl':url_for('static',filename='maps/entenda_regiony.geojson'),
            'countriesUrl':url_for('region_sovereignty.country_boundaries'),
            'citiesUrl':url_for('static',filename='maps/entenda_miasta.geojson'),
            'baseIcon':url_for('static',filename='icons/BAZA.svg'),
            'landWar':land_war_config(country.PANSTWO_ID,mode),
            'radars':visible_radars(db.session,country.PANSTWO_ID,mode=='war'),'radarIcon':url_for('static',filename='icons/RADAR.svg'),
            'radar':{**radar_config(db.session,country.PANSTWO_ID),'url':url_for('game_military.radar_change'),
                     'chipIcon':url_for('static',filename='icons/CHIP NATSYTOWY.svg'),'ironIcon':url_for('static',filename='icons/ŻELAZO.svg')},
            'attackIcons':{code:url_for('static',filename='icons/'+name+'.svg') for code,name in
                           [('air','BOMBARDUJ'),('missile','WYSTRZEL Z TERYTORIUM'),('naval','WYSTRZEL Z OKRĘTU'),('land','WPROWADŹ ARMIĘ LĄDOWĄ')]},
        })

    db.session.commit()
    return response


@military_bp.get('/obrona-panstwa')
def defense_page():
    return render_military('defense')


@military_bp.get('/panel-wojenny')
def war_page():
    return render_military('war')


@military_bp.post('/obrona-panstwa/zmien')
def defense_change():
    user,country = player()
    if user is None:
        return jsonify(error='Zaloguj się ponownie.'),401
    if not csrf_valid():
        return jsonify(error='Nieprawidłowy token formularza. Odśwież stronę.'),403
    data = request.get_json(silent=True)
    if not isinstance(data,dict):
        return jsonify(error='Nieprawidłowe dane formularza.'),400
    try:
        base_id=change_defense(user.id,data.get('action'),data)
    except FinanceError as exc:
        return jsonify(error=str(exc)),400
    return jsonify(ok=True,base_id=base_id)


@military_bp.post('/panel-wojenny/rozkaz')
def war_order():
    user,country = player()
    if user is None:
        return jsonify(error='Zaloguj się ponownie.'),401
    if not csrf_valid():
        return jsonify(error='Nieprawidłowy token formularza.'),403
    data = request.get_json(silent=True)
    if not isinstance(data,dict):
        return jsonify(error='Nieprawidłowe dane formularza.'),400
    try:
        flight_id=create_order(user.id,data)
    except FinanceError as exc:
        return jsonify(error=str(exc)),400
    message='Wysłano myśliwiec. Bombardowanie nastąpi po dotarciu do celu.' if data.get('kind')=='air' else 'Wystrzelono rakiety. Trafienie zostanie rozliczone po zakończeniu lotu.'
    if data.get('is_nuclear'):message+=' Pocisk atomowy nie powoduje jeszcze ofiar ani zniszczeń.'
    if not flight_id:message='Przyjęto rozkaz przemarszu. Zmiana kontroli regionu nie jest jeszcze rozstrzygana.'
    return jsonify(ok=True,flight_id=flight_id,message=message)



def base_data(base,own=None):
    from game.base_permits import own_region_ids,ABROAD_UPKEEP
    from game.military_service import UPKEEP_RATES
    own=own if own is not None else own_region_ids(db.session,base.panstwo_id)
    abroad=base.region_id is not None and base.region_id not in own
    upkeep=sum(n*UPKEEP_RATES[r] for r,n in (base.garrison or {}).items() if r!='warheads')*(ABROAD_UPKEEP if abroad else 1)
    return {'abroad':abroad,'upkeep':str(upkeep),'id':base.id,'name':base.name,'operational':base.operational,'busyVessels':{kind:busy_vessels(db.session,base.id,kind) for kind in ('warships','submarines')} if base.kind=='naval' else {},'countryId':base.panstwo_id,'regionId':str(base.region_id),'kind':base.kind,
        'label':BASES[base.kind][0],'level':base.level,'garrison':base.garrison,'capacity':CAPACITIES[base.kind][base.level-1],
        'upgradeCost':str(UPGRADE_COSTS.get(base.level+1,0)*(2 if base.kind=='nuclear' else 1)),'position':[base.map_x,base.map_y] if base.map_x is not None and base.map_y is not None else None,
        'health':base.health,'busyFighters':busy_fighters(db.session,base.id) if base.kind=='air' else 0}


def visible_flights(country_id):
    participant=or_(MilitaryFlight.panstwo_id==country_id,MilitaryFlight.target_country_id==country_id)
    active=list(db.session.scalars(select(MilitaryFlight).where(participant,MilitaryFlight.returned_at.is_(None)).order_by(MilitaryFlight.id)))
    recent=list(db.session.scalars(select(MilitaryFlight).where(participant,MilitaryFlight.returned_at.is_not(None)).order_by(MilitaryFlight.id.desc()).limit(20)))
    from game.intelligence_service import known_ids
    allowed=known_ids(db.session,country_id,'bases')
    items=[]
    for flight in active+recent:
        if flight.panstwo_id!=country_id and flight.source_vessel_id is None and flight.source_base_id not in allowed:
            if flight.returned_at is None:continue
            item=flight_data(flight);item['source']=item['target'];item['sourceBaseId']=None
        else:item=flight_data(flight)
        items.append(item)
    from game.radar import radar_flights
    # Flights already shown in full are skipped; radar adds only the tracked pieces of the others.
    items.extend(radar_flights(db.session,country_id,{item['id'] for item in items}))
    return items


@military_bp.get('/panel-wojenny/stan')
def map_state():
    user,country=player()
    if user is None:return jsonify(error='Zaloguj się ponownie.'),401
    complete_flights(db.session,game_now(),country.PANSTWO_ID)
    from game.land_war import complete_marches,visible_armies,visible_occupations
    complete_marches(db.session,game_now())
    from game.radar import detect as radar_detect,visible_radars
    radar_detect(db.session,game_now())
    db.session.scalar(select(Panstwo.PANSTWO_ID).where(Panstwo.PANSTWO_ID==country.PANSTWO_ID).with_for_update())
    settle_vessels(db.session,game_now(),country.PANSTWO_ID)
    army=army_for_country(db.session, country.PANSTWO_ID, lock=False)
    world=bool(enemies(db.session,country.PANSTWO_ID))
    from game.trade_navigation import visible_shipments
    response=jsonify(power=visible_power(country.PANSTWO_ID,world),factories=visible_factories(country.PANSTWO_ID,world),tradeShips=visible_shipments(db.session,country.PANSTWO_ID),gameNow=game_now().isoformat()+'Z',timeMultiplier=get_time_multiplier(),flights=visible_flights(country.PANSTWO_ID),
        defenses=visible_defenses(country.PANSTWO_ID,bool(enemies(db.session,country.PANSTWO_ID))),vessels=visible_vessels(country.PANSTWO_ID,bool(enemies(db.session,country.PANSTWO_ID))),bases=visible_base_data(country.PANSTWO_ID,world),mines=visible_mines(country.PANSTWO_ID,world),
        missiles={code:{'label':label,'count':getattr(army,field) or 0 if army else 0} for code,(field,label) in MISSILES.items()},
        armies=visible_armies(db.session,country.PANSTWO_ID),occupations=visible_occupations(db.session),
        radars=visible_radars(db.session,country.PANSTWO_ID,world))
    db.session.commit()
    response.headers['Cache-Control']='no-store'
    return response


def visible_vessels(country_id,world=False):
    query=select(MilitaryVessel).where(MilitaryVessel.status.in_(['sailing','stationed','returning']))
    if not world:query=query.where(MilitaryVessel.panstwo_id==country_id)
    items=[]
    for vessel in db.session.scalars(query.order_by(MilitaryVessel.id)):
        item=vessel_data(vessel,game_now())
        if vessel.panstwo_id!=country_id:
            # A return route must not disclose an undiscovered naval base.
            item['baseId']=None;item['regionId']=None;item['source']=item['position'];item['target']=item['position']
            item['startsAt']=game_now().isoformat()+'Z';item['arrivesAt']=item['startsAt']
        items.append(item)
    return items


def visible_defenses(country_id,world=False):
    from game.missile_defense import defense_data
    query=select(MissileDefense)
    from game.intelligence_service import known_ids
    allowed=known_ids(db.session,country_id,'defenses') if world else set()
    query=query.where(or_(MissileDefense.panstwo_id==country_id,MissileDefense.id.in_(allowed)))
    return [defense_data(d) for d in db.session.scalars(query.order_by(MissileDefense.id))]


@military_bp.get('/obrona-panstwa/wybrzeze/<int:region_id>')
def coastline(region_id):
    user,country=player()
    if user is None:return jsonify(error='Zaloguj się ponownie.'),401
    region=db.session.scalar(select(Region).options(lazyload('*')).where(Region.region_id==region_id,Region.panstwo_id.in_(controlled_ids(db.session, country.PANSTWO_ID))))
    if region is None:return jsonify(error='Region nie należy do gracza.'),403
    from game.military_geography import coastline_segments
    return jsonify(segments=coastline_segments(region_id) if region.region_polozenie_id not in (None,1) else [],widthKm=3)



def visible_base_data(country_id,world=False):
    from game.intelligence_service import known_ids
    allowed=known_ids(db.session,country_id,'bases') if world else set()
    items=[];owns={}
    from game.base_permits import own_region_ids
    for base in db.session.scalars(select(MilitaryBase).where(or_(MilitaryBase.panstwo_id==country_id,MilitaryBase.id.in_(allowed))).order_by(MilitaryBase.id)):
        if base.panstwo_id not in owns:owns[base.panstwo_id]=own_region_ids(db.session,base.panstwo_id)
        item=base_data(base,owns[base.panstwo_id])
        if base.panstwo_id!=country_id:
            item['garrison']={};item['capacity']={};item['busyFighters']=0;item['busyVessels']={};item['intelligenceOnly']=True;item['upkeep']=None
        items.append(item)
    return items


def visible_mines(country_id,world=False):
    from game.commerce_models import Mine
    from game.mining_service import mine_data
    from game.intelligence_service import known_ids
    allowed=known_ids(db.session,country_id,'mines') if world else set()
    return [mine_data(mine,game_now()) for mine in db.session.scalars(select(Mine).where(or_(Mine.panstwo_id==country_id,Mine.id.in_(allowed)),Mine.removed_at.is_(None)).order_by(Mine.id))]


def visible_factories(country_id,world=False):
    from game.research_models import AmmunitionFactory
    from game.industry_catalog import FACTORIES
    from game.commerce import goods_catalog
    products=goods_catalog()
    for code,label,file in [('warships','Okręty wojenne','OKRĘT WOJENNY.svg'),('submarines','Okręty podwodne','SUBMARINE.svg'),('carriers','Lotniskowce','LOTNISKOWIEC.svg')]:
        products[code]={'label':label,'icon':url_for('static',filename='icons/'+file)}
    query=select(AmmunitionFactory).where(AmmunitionFactory.removed_at.is_(None)).order_by(AmmunitionFactory.id)
    if not world:query=query.where(AmmunitionFactory.panstwo_id==country_id)
    factories=[]
    for factory in db.session.scalars(query):
        rule=FACTORIES[factory.kind];recipe=rule['levels'][factory.level-1];product=products[recipe['product']]
        factories.append({'id':factory.id,'countryId':factory.panstwo_id,'regionId':str(factory.region_id),'name':rule['label']+f' #{factory.id}','position':[factory.map_x,factory.map_y],'health':factory.health,'level':factory.level,'dailyProduction':recipe['quantity'] if factory.health>0 and not factory.paused else 0,'product':recipe['product'],'productName':product['label'],'productIcon':product['icon']})
    return factories


def visible_power(country_id,world=False):
    from game.industry_models import PowerPlant
    from game.industry_service import object_data
    from game.intelligence_service import known_ids
    allowed=known_ids(db.session,country_id,'power') if world else set()
    return [object_data(row,'power') for row in db.session.scalars(select(PowerPlant).where(or_(PowerPlant.panstwo_id==country_id,PowerPlant.id.in_(allowed)),PowerPlant.removed_at.is_(None)).order_by(PowerPlant.id))]



# ---------------- Wojska lądowe: obrona miast, inwazja, okupacja (11 Nov 2026) ----------------

def land_war_config(country_id,mode):
    from game.land_war import (UNIT_COST,WEIGHTS,SPEED_FOOT,SPEED_ARMORED,ANNEX_DAYS,gdp_per_capita,training,visible_armies,visible_occupations)
    from game.road_projects import neighboring_countries
    from game.military_service import CAPACITIES
    icon=lambda name:url_for('static',filename='icons/'+name)
    return {'unitCosts':{unit:str(cost) for unit,cost in UNIT_COST.items()},'gdpPerCapita':str(gdp_per_capita(db.session,country_id)),
            'weights':WEIGHTS,'speeds':{'foot':SPEED_FOOT,'armored':SPEED_ARMORED},'annexDays':ANNEX_DAYS,'training':training(db.session,country_id),
            'neighbors':sorted(neighboring_countries(db.session,country_id)) if mode=='war' else [],
            'armies':visible_armies(db.session,country_id),'occupations':visible_occupations(db.session),
            'icons':{'city':icon('MIASTO.svg'),'invasion':icon('INWAZJA.svg'),'soldiers':icon('CZŁOWIEK.svg'),'armored':icon('WÓZ OPANCERZONY.svg'),'tanks':icon('CZOŁG.svg')},
            'invasionUrl':url_for('game_military.land_invasion'),'cityDefenseUrl':url_for('game_military.city_defense'),'occupationUrl':url_for('game_military.occupation_decision'),
            'capacities':{kind:[{unit:row.get(unit,0) for unit in ('soldiers','armored','tanks')} for row in rows] for kind,rows in CAPACITIES.items() if kind!='nuclear'}}


def _land_action(handler):
    user,country=player()
    if user is None:return jsonify(error='Zaloguj się ponownie.'),401
    if not csrf_valid():return jsonify(error='Nieprawidłowy token formularza.'),403
    data=request.get_json(silent=True)
    if not isinstance(data,dict):return jsonify(error='Nieprawidłowe dane formularza.'),400
    db.session.rollback()
    try:return jsonify(ok=True,**handler(user.id,data))
    except FinanceError as exc:return jsonify(error=str(exc)),400


@military_bp.post('/panel-wojenny/armia-ladowa')
def land_invasion():
    from game.land_war import launch_invasion
    return _land_action(lambda user_id,data:{'id':launch_invasion(user_id,data),'message':'Armia wyruszyła. Bitwa odbędzie się po dotarciu do celu.'})


@military_bp.post('/obrona-panstwa/obrona-miasta')
def city_defense():
    from game.land_war import add_city_defense,withdraw_city_defense
    def handler(user_id,data):
        if data.get('action')=='withdraw':return {'id':withdraw_city_defense(user_id,data),'message':'Oddział wrócił do bazy.'}
        return {'id':add_city_defense(user_id,data),'message':'Przydzielono obronę miasta.'}
    return _land_action(handler)


@military_bp.post('/obrona-panstwa/radar')
def radar_change():
    from game.radar import change_radar
    def handler(user_id,data):
        radar_id,message=change_radar(user_id,data)
        return {'radar_id':radar_id,'message':message}
    return _land_action(handler)


@military_bp.post('/panel-wojenny/okupacja')
def occupation_decision():
    from game.land_war import decide_region,annex_region
    def handler(user_id,data):
        if data.get('action')=='annex':return {'id':annex_region(user_id,data),'message':'Region został anektowany.'}
        if data.get('action')=='withdraw':
            from game.land_war import withdraw_occupation
            return withdraw_occupation(user_id,data)
        return {'id':decide_region(user_id,data),'message':'Zapisano decyzję o okupacji regionu.'}
    return _land_action(handler)
