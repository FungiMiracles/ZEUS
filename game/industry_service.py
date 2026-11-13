from game.paga_ai_actor import country_user_id
"""Transactional industry. Inputs and work are settled chronologically in Entenda days."""
from datetime import timedelta
from calendar import monthrange
from decimal import Decimal
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from extensions import db
from models import Panstwo,Region,Wojsko
from game.industry_catalog import TECHNOLOGIES,FACTORIES,POWER_PLANTS,MINE_RULES,ARMY_GOODS,COAL_POLLUTION,FILTER_TECHNOLOGY,FILTER_COSTS,FACTORY_DEGRADATION,WASTE_FILTER_TECHNOLOGY,WASTE_FILTER_COSTS,FILTER_SECTOR
from game.industry_models import PowerPlant,IndustryClock,IndustryMovement
from game.research_models import AmmunitionFactory,ResearchAccount
from game.commerce_models import Mine,ResourceStock
from game.finance_service import FinanceError,FinanceConflict,_country_for_user,game_now,period_key
from game.finance_models import StateBudget
from game.governance import economy,controlled_ids,army_for_country
from game.mining_service import stock,request_key

DAY=timedelta(days=1)
def month_after(moment):
    year=moment.year+(moment.month==12);month=moment.month%12+1
    return moment.replace(year=year,month=month,day=min(moment.day,monthrange(year,month)[1]))
def ready_at(moment,duration):return month_after(moment) if duration=='month' else moment+timedelta(days=duration)
def researched(session,country,key):
    row=session.get(ResearchAccount,country)
    if row is None or key not in TECHNOLOGIES:return False
    from game.research_timing import developed
    return developed(row.nodes,getattr(row,'timers',None),key,game_now())   # 13 Nov 2026: także po zakończeniu czasu rozwoju

def require_technologies(session,country,keys):
    missing=[TECHNOLOGIES[key]['label'] for key in keys if not researched(session,country,key)]
    if missing:raise FinanceError('Wymagane technologie: '+', '.join(missing)+'.')

def notify(session,country,text):
    from game.models import GamePlayerCountry,utc_now
    from game.forum_models import GameNotification
    owner=country_user_id(session,country)
    if owner is not None:session.add(GameNotification(user_id=owner,notification_type='SYSTEM',system_text=text,created_at=utc_now()))

def change_indicator(session,region_id,field,delta):
    """Environmental indicator of a region (0–100; missing data counts as 0) changed by plants or factories."""
    if not delta:return
    region=session.scalar(select(Region).where(Region.region_id==region_id).with_for_update())
    if region is not None:setattr(region,field,max(0,min(100,int(getattr(region,field) or 0)+delta)))

def change_pollution(session,region_id,delta):change_indicator(session,region_id,'region_zanieczyszczenie_powietrza',delta)
def change_degradation(session,region_id,delta):change_indicator(session,region_id,'region_degradacja_srodowiska',delta)

def available(session,country,code):
    row=session.get(ResourceStock,(country,code));return int(row.quantity) if row else 0

def has_inputs(session,country,inputs,count=1):return all(available(session,country,code)>=amount*count for code,amount in inputs.items())
def consume(session,country,inputs,count=1):
    for code,amount in inputs.items():stock(session,country,code).quantity-=amount*count

def add_output(session,country,code,count):
    if code=='interceptor_ammunition':
        from game.research_service import account_for
        row=account_for(session,country)
        if row.ammunition+count>9223372036854775807:raise FinanceError('Magazyn amunicji jest pełny.')
        row.ammunition+=count
    elif code in ARMY_GOODS:
        row=army_for_country(session,country,lock=True)
        if row is None:row=Wojsko(panstwo_id=country);session.add(row)
        field=ARMY_GOODS[code];value=(getattr(row,field) or 0)+count
        if value>2147483647:raise FinanceError('Przekroczony limit zasobów wojskowych.')
        setattr(row,field,value)
    else:stock(session,country,code).quantity+=count

def factory_can_work(session,f):
    return f.removed_at is None and f.health>0 and not f.paused and (f.production_progress>0 or has_inputs(session,f.panstwo_id,FACTORIES[f.kind]['levels'][f.level-1]['inputs']))
def power_can_work(session,p):
    rule=POWER_PLANTS[p.kind]
    return p.removed_at is None and p.health==3 and (rule['fuel'] is None or available(session,p.panstwo_id,rule['fuel'])>=rule['amounts'][p.level-1])

def settle_industry(session,country,now=None):
    now=now or game_now()
    session.scalar(select(Panstwo.PANSTWO_ID).where(Panstwo.PANSTWO_ID==country).with_for_update())
    clock=session.get(IndustryClock,country)
    if clock is None:
        clock=IndustryClock(panstwo_id=country,settled_at=now);session.add(clock)
    plants=list(session.scalars(select(PowerPlant).where(PowerPlant.panstwo_id==country,PowerPlant.removed_at.is_(None)).order_by(PowerPlant.id).with_for_update()))
    factories=list(session.scalars(select(AmmunitionFactory).where(AmmunitionFactory.panstwo_id==country,AmmunitionFactory.removed_at.is_(None)).order_by(AmmunitionFactory.id).with_for_update()))
    # Event times are anchored to each object's own commissioning time.
    from game.mining_service import extract_country
    resident=resident_demand(session,country)
    while True:
        times=[f.produced_at+DAY for f in factories]+[p.checked_at+DAY for p in plants]
        moment=min(times) if times else now+DAY
        if moment>now:break
        extract_country(session,country,moment)
        for p in plants:
            if p.checked_at+DAY>moment:continue
            active=power_can_work(session,p)
            if not active and p.running and p.ever_worked:notify(session,country,POWER_PLANTS[p.kind]['label']+f' #{p.id}: produkcja energii została wstrzymana — brak paliwa lub uszkodzenie.')
            if active:
                rule=POWER_PLANTS[p.kind]
                if rule['fuel']:consume(session,country,{rule['fuel']:rule['amounts'][p.level-1]})
                p.ever_worked=True
            p.running=active;p.checked_at+=DAY
        powered=powered_factories(session,factories,sum(plant_output(session,p) for p in plants if p.running),resident)
        for f in factories:
            if f.produced_at+DAY>moment:continue
            workable=factory_can_work(session,f);active=workable and f.id in powered;rule=FACTORIES[f.kind]['levels'][f.level-1]
            if active:
                if rule['days']==1:
                    count=min([rule['quantity']]+[available(session,country,code)//amount for code,amount in rule['inputs'].items()])
                    consume(session,country,rule['inputs'],count);add_output(session,country,rule['product'],count)
                else:
                    if f.production_progress==0:
                        consume(session,country,rule['inputs'])
                        f.cycle_days=(month_after(f.produced_at)-f.produced_at).days if rule['days']=='month' else rule['days']
                    f.production_progress+=1
                    if f.production_progress>=f.cycle_days:
                        add_output(session,country,rule['product'],1);f.production_progress=0
                f.ever_worked=True
            elif f.running and f.ever_worked and not f.paused:
                notify(session,country,FACTORIES[f.kind]['label']+f' #{f.id}: produkcja została wstrzymana — '+('brak energii w sieci (deficyt energii).' if workable else 'brak surowców lub uszkodzenie.'))
            f.running=active;f.produced_at+=DAY
        session.flush()
    extract_country(session,country,now)
    clock.settled_at=max(clock.settled_at,now);session.flush()
    return session.get(ResearchAccount,country)

def plant_output(session,plant):
    """Daily output of a working plant scaled by the energy infrastructure of its region (rounded up; 0 below 10)."""
    from game.infrastructure_effects import power_output
    region=session.get(Region,plant.region_id)
    return power_output(POWER_PLANTS[plant.kind]['production'][plant.level-1],region.region_stan_infra_energetycznej if region else 0)

def resident_demand(session,country):
    population=economy(session,country)['population'] or 0
    return Decimal(population)/100000

def powered_factories(session,factories,production,resident):
    """Energy deficit rule: factories able to work stop from the largest energy consumer until the grid balances."""
    candidates=[f for f in factories if factory_can_work(session,f)]
    energy=lambda f:Decimal(str(FACTORIES[f.kind]['levels'][f.level-1]['energy']))
    available=Decimal(str(production))-resident;total=sum((energy(f) for f in candidates),Decimal(0))
    powered={f.id for f in candidates}
    for f in sorted(candidates,key=lambda f:(-energy(f),-f.id)):
        if total<=available:break
        powered.discard(f.id);total-=energy(f)
    return powered

def energy_balance(session,country):
    population=economy(session,country)['population'] or 0
    resident=Decimal(population)/100000
    factories=list(session.scalars(select(AmmunitionFactory).where(AmmunitionFactory.panstwo_id==country,AmmunitionFactory.removed_at.is_(None))))
    plants=list(session.scalars(select(PowerPlant).where(PowerPlant.panstwo_id==country,PowerPlant.removed_at.is_(None))))
    production=sum(plant_output(session,p) for p in plants if power_can_work(session,p))
    powered=powered_factories(session,factories,production,resident)
    demand=resident+sum(FACTORIES[f.kind]['levels'][f.level-1]['energy'] for f in factories if factory_can_work(session,f))
    consumption=resident+sum(FACTORIES[f.kind]['levels'][f.level-1]['energy'] for f in factories if f.id in powered)
    stopped=sum(1 for f in factories if factory_can_work(session,f) and f.id not in powered)
    sources={kind:dict(production=0,consumption=0,extraction=0) for kind in POWER_PLANTS}
    for plant in plants:
        if power_can_work(session,plant):
            rule=POWER_PLANTS[plant.kind];source=sources[plant.kind]
            source['production']+=plant_output(session,plant)
            source['consumption']+=rule['amounts'][plant.level-1]
    from game.mining_service import resource_ids
    from models import RegionZasob
    dictionary=resource_ids(session)
    for kind,code in [('coal','wegiel_kamienny'),('nuclear','uran')]:
        rates={}
        for mine in session.scalars(select(Mine).where(Mine.panstwo_id==country,Mine.resource==code,Mine.removed_at.is_(None),Mine.health>0,Mine.ready_at<=game_now())):
            rates[mine.region_id]=rates.get(mine.region_id,0)+MINE_RULES[code][3][mine.level-1]
        controlled=controlled_ids(session,country)
        for region,rate in rates.items():
            if session.scalar(select(Region.panstwo_id).where(Region.region_id==region)) not in controlled:continue
            deposit=session.scalar(select(RegionZasob.zloze_ilosc).where(RegionZasob.region_id==region,RegionZasob.zasob_id==dictionary.get(code))) or 0
            from game.infrastructure_effects import extraction_time_factor
            factor=extraction_time_factor(session.scalar(select(Region.region_stan_infra_kolejowej).where(Region.region_id==region)))
            effective=0 if factor is None else float((Decimal(rate)/factor).quantize(Decimal('0.01')))
            sources[kind]['extraction']+=min(effective,max(0,int(deposit)))
    return dict(consumption=str(consumption),production=str(production),residents=str(resident),sufficient=production>=demand,sources=sources,
                demand=str(demand),stoppedFactories=stopped)

def current_budget(session,country,cost,environment=Decimal(0)):
    from game.budget_transfers import sector_balances
    year,half=period_key(game_now());budget=session.scalar(select(StateBudget).where(StateBudget.panstwo_id==country,StateBudget.game_year==year,StateBudget.period==half).with_for_update())
    if budget is None:raise FinanceError('Najpierw zatwierdź bieżący budżet.')
    if cost>0 or environment>0:
        balances=sector_balances(session,budget)
        if cost>0 and balances['infrastructure']['remaining']<cost:raise FinanceError('Za mało środków w budżecie infrastruktury.')
        if environment>0 and balances[FILTER_SECTOR]['remaining']<environment:raise FinanceError('Za mało środków w budżecie ochrony środowiska.')
    return budget

def change_industry(user_id,data):
    key=request_key(data.get('request_id'));action=data.get('action');category=data.get('category')
    if category not in ('factory','power','mine'):raise FinanceError('Wybierz rodzaj obiektu.')
    models={'factory':AmmunitionFactory,'power':PowerPlant,'mine':Mine}
    with Session(db.engine) as session,session.begin():
        country=_country_for_user(session,user_id,lock=True).PANSTWO_ID
        previous=session.scalar(select(IndustryMovement).where(IndustryMovement.panstwo_id==country,IndustryMovement.request_id==key))
        if previous:
            if previous.payload!=data:raise FinanceConflict('Identyfikator operacji został już użyty.')
            return previous.payload.get('object_id')
        from game.research_service import settle_production
        settle_production(session,country)
        now=game_now();cost=Decimal(0);environment=Decimal(0)
        if action=='build':
            if category=='mine':raise FinanceError('Kopalnię buduje się wyłącznie na poziomie 1 w panelu surowców.')
            kind=data.get('kind');level=data.get('level',1)
            if type(level) is not int:raise FinanceError('Nieprawidłowy poziom.')
            if category=='factory':
                if not isinstance(kind,str) or kind not in FACTORIES or not 1<=level<=len(FACTORIES[kind]['levels']):raise FinanceError('Wybierz fabrykę i prawidłowy poziom.')
                rule=FACTORIES[kind]['levels'][level-1];require_technologies(session,country,rule['technologies']);cost=Decimal(rule['cost'])
            else:
                if not isinstance(kind,str) or kind not in POWER_PLANTS or level!=1:raise FinanceError('Elektrownię można budować tylko na poziomie 1.')
                rule=POWER_PLANTS[kind];require_technologies(session,country,[rule['technology']]);cost=Decimal(rule['costs'][0])
            from game.roads import point
            from game.military_geography import region_contains
            x,y=point([data.get('x'),data.get('y')]);region=data.get('region_id')
            if type(region) is not int or session.scalar(select(Region.region_id).where(Region.region_id==region,Region.panstwo_id.in_(controlled_ids(session,country)))) is None or not region_contains(region,x,y):raise FinanceError('Wskaż punkt we własnym regionie.')
            from game.land_war import require_buildable
            require_buildable(session,region,country)
            if category=='factory' and kind=='shipyard':
                from game.military_geography import naval_location_allowed
                from game.military_flights import calibration
                coastal=session.scalar(select(Region.region_polozenie_id).where(Region.region_id==region))
                if coastal in (None,1) or not naval_location_allowed(region,x,y,calibration(session).km_per_unit):
                    raise FinanceError('Stocznia musi leżeć we własnym regionie nadmorskim, w pasie do 3 km od wybrzeża, tak jak baza morska.')
            budget=current_budget(session,country,cost)
            if category=='factory':
                obj=AmmunitionFactory(panstwo_id=country,region_id=region,budget_id=budget.id,map_x=x,map_y=y,level=level,kind=kind,cost=0,created_game_at=now,produced_at=now,request_id=key,
                                      waste_filter=False,degradation_points=FACTORY_DEGRADATION)
                change_degradation(session,region,obj.degradation_points)
            else:
                obj=PowerPlant(panstwo_id=country,region_id=region,map_x=x,map_y=y,level=1,kind=kind,investment=cost,created_game_at=now,checked_at=now,
                               air_filter=False,pollution_points=COAL_POLLUTION if kind=='coal' else 0)
                change_pollution(session,region,obj.pollution_points)
            session.add(obj);session.flush()
        else:
            object_id=data.get('object_id')
            if type(object_id) is not int:raise FinanceError('Wybierz obiekt.')
            obj=session.scalar(select(models[category]).where(models[category].id==object_id,models[category].panstwo_id==country).with_for_update())
            if obj is None or obj.removed_at is not None:raise FinanceError('Nie znaleziono własnego aktywnego obiektu.')
            if action!='remove':
                # Upgrades, filters and repairs are construction too; liquidation stays possible.
                from game.land_war import require_buildable
                require_buildable(session,obj.region_id,country)
            if action=='remove':
                if category=='factory':value=FACTORIES[obj.kind]['levels'][obj.level-1]['cost']
                elif category=='power':value=POWER_PLANTS[obj.kind]['costs'][obj.level-1]
                else:value=MINE_RULES[obj.resource][2][obj.level-1]*1000000000
                cost=-Decimal(value)/4;obj.removed_at=now
                if category in ('factory','power'):obj.running=False
                # Liquidation removes the pollution the plant added; filter costs are not refunded.
                if category=='power' and obj.pollution_points:change_pollution(session,obj.region_id,-obj.pollution_points);obj.pollution_points=0
                if category=='factory' and obj.degradation_points:change_degradation(session,obj.region_id,-obj.degradation_points);obj.degradation_points=0
                from game.military_models import MissileDefense
                defense=session.scalar(select(MissileDefense).where(MissileDefense.target_kind==category,MissileDefense.target_id==obj.id))
                if defense:defense.health=0;defense.ammunition=0
            elif action=='upgrade' and category in ('mine','power'):
                if obj.level>=3:raise FinanceError('Maksymalny poziom wynosi 3.')
                if obj.health<=0:raise FinanceError('Zniszczonego obiektu nie można rozbudować.')
                if category=='mine':
                    if obj.ready_at>now:raise FinanceError('Kopalnia jest jeszcze w budowie.')
                    rule=MINE_RULES[obj.resource];require_technologies(session,country,[rule[1]]);cost=Decimal(rule[2][obj.level]*1000000000)
                else:
                    if obj.health!=3:raise FinanceError('Najpierw napraw elektrownię.')
                    rule=POWER_PLANTS[obj.kind];require_technologies(session,country,[rule['technology']]);cost=Decimal(rule['costs'][obj.level])
                    # A filter follows the plant to the next level; the price difference of the filter is added.
                    if obj.air_filter:environment=Decimal(FILTER_COSTS[obj.level]-FILTER_COSTS[obj.level-1])
                obj.level+=1;obj.investment+=cost
                if category=='mine':obj.extracted_at=max(obj.extracted_at,now)
            elif action=='filter' and category=='power':
                if obj.kind!='coal':raise FinanceError('Filtr zanieczyszczeń można zamontować tylko na elektrowni węglowej.')
                if obj.air_filter:raise FinanceError('Ta elektrownia ma już filtr zanieczyszczeń.')
                if obj.health<=0:raise FinanceError('Na zniszczonej elektrowni nie można zamontować filtra.')
                require_technologies(session,country,[FILTER_TECHNOLOGY])
                environment=Decimal(FILTER_COSTS[obj.level-1]);obj.air_filter=True
                if obj.pollution_points:change_pollution(session,obj.region_id,-obj.pollution_points);obj.pollution_points=0
            elif action=='waste_filter' and category=='factory':
                if obj.waste_filter:raise FinanceError('Ta fabryka ma już filtr odpadów fabrycznych.')
                if obj.health<=0:raise FinanceError('Na zniszczonej fabryce nie można zamontować filtra.')
                require_technologies(session,country,[WASTE_FILTER_TECHNOLOGY])
                environment=Decimal(WASTE_FILTER_COSTS[obj.level-1]);obj.waste_filter=True
                if obj.degradation_points:change_degradation(session,obj.region_id,-obj.degradation_points);obj.degradation_points=0
            elif action=='repair' and category=='power':
                if obj.health==3:raise FinanceError('Elektrownia jest sprawna.')
                cost=(obj.investment*Decimal(3-obj.health)/3).quantize(Decimal('.01'));obj.health=3
            elif action in ('pause','resume') and category=='factory':obj.paused=action=='pause';obj.running=False
            else:raise FinanceError('Nieprawidłowa operacja obiektu.')
            budget=current_budget(session,country,cost,environment)
        # Filters are charged to the environmental protection budget; an upgrade with a filter charges both sectors
        # (the second movement gets a request id derived from the operation, so a retry stays idempotent).
        if environment and not cost:
            session.add(IndustryMovement(panstwo_id=country,budget_id=budget.id,amount=environment,request_id=key,payload=data,sector=FILTER_SECTOR))
        else:
            session.add(IndustryMovement(panstwo_id=country,budget_id=budget.id,amount=cost,request_id=key,payload=data,sector='infrastructure'))
            if environment:
                from uuid import uuid5,NAMESPACE_URL
                session.add(IndustryMovement(panstwo_id=country,budget_id=budget.id,amount=environment,request_id=str(uuid5(NAMESPACE_URL,'industry-filter:'+key)),payload=data,sector=FILTER_SECTOR))
        return obj.id

def object_data(obj,category,powered=None):
    if category=='factory':
        rule=FACTORIES[obj.kind];spec=rule['levels'][obj.level-1];label=rule['label'];icon=rule['icon'];health=obj.health
        workable=factory_can_work(__import__('sqlalchemy.orm',fromlist=['object_session']).object_session(obj),obj)
        status='wstrzymana' if obj.paused else 'zniszczona' if obj.health<=0 else ('brak energii' if powered is not None and obj.id not in powered else 'pracuje') if workable else 'brak surowców'
        from sqlalchemy.orm import object_session
        session=object_session(obj)
        missing={code:amount-available(session,obj.panstwo_id,code) for code,amount in spec['inputs'].items() if available(session,obj.panstwo_id,code)<amount} if obj.production_progress==0 else {}
        extra=dict(wasteFilter=bool(obj.waste_filter),degradation=int(obj.degradation_points or 0),
                   wasteFilterCost=WASTE_FILTER_COSTS[obj.level-1] if not obj.waste_filter else None,paused=obj.paused,energy=spec['energy'],product=spec['product'],quantity=spec['quantity'],days=spec['days'],missingInputs=missing,ready=True,progress=100,effectiveQuantity=spec['quantity'] if status=='pracuje' else 0)
    elif category=='power':
        rule=POWER_PLANTS[obj.kind];label=rule['label'];icon=rule['icon'];health=obj.health*100/3
        status='zniszczona' if obj.health==0 else 'uszkodzona' if obj.health<3 else 'pracuje' if power_can_work(__import__('sqlalchemy.orm',fromlist=['object_session']).object_session(obj),obj) else 'brak paliwa'
        from sqlalchemy.orm import object_session
        from game.infrastructure_effects import energy_factor
        region=object_session(obj).get(Region,obj.region_id)
        output=plant_output(object_session(obj),obj)
        if status=='pracuje' and output==0:status='brak infrastruktury'
        extra=dict(ready=True,progress=100,effectiveDailyProduction=output if status=='pracuje' else 0,dailyProduction=rule['production'][obj.level-1],
                   efficiencyPercent=int(energy_factor(region.region_stan_infra_energetycznej if region else 0)*100),repairCost=str((obj.investment*Decimal(3-obj.health)/3).quantize(Decimal('.01'))),
                   upgradeCost=rule['costs'][obj.level]+(FILTER_COSTS[obj.level]-FILTER_COSTS[obj.level-1] if obj.air_filter else 0) if obj.level<3 else None,
                   upgradeFilterCost=FILTER_COSTS[obj.level]-FILTER_COSTS[obj.level-1] if obj.air_filter and obj.level<3 else None,
                   airFilter=bool(obj.air_filter),pollution=int(obj.pollution_points or 0),
                   filterCost=FILTER_COSTS[obj.level-1] if obj.kind=='coal' and not obj.air_filter else None)
    else:
        from game.mining_service import mine_data
        return {**mine_data(obj,game_now()),'category':'mine','kind':obj.resource,'icon':'KOPALNIA.svg','status':'w budowie' if obj.ready_at>game_now() else 'zniszczona' if obj.health<=0 else 'gotowa','refund':str(Decimal(MINE_RULES[obj.resource][2][obj.level-1]*1000000000)/4)}
    refund=Decimal(FACTORIES[obj.kind]['levels'][obj.level-1]['cost'] if category=='factory' else POWER_PLANTS[obj.kind]['costs'][obj.level-1])/4
    return dict(refund=str(refund),id=obj.id,category=category,kind=obj.kind,countryId=obj.panstwo_id,regionId=str(obj.region_id),name=label+f' #{obj.id}',icon=icon,level=obj.level,position=[obj.map_x,obj.map_y],health=health,status=status,**extra)

def industry_state(session,country):
    from game.commerce import goods_catalog
    from flask import url_for
    from game.budget_transfers import sector_balances
    from game.industry_catalog import GOODS
    year,half=period_key(game_now());budget=session.scalar(select(StateBudget).where(StateBudget.panstwo_id==country,StateBudget.game_year==year,StateBudget.period==half))
    from game.mining_service import resource_ids
    from models import RegionZasob
    dictionary=resource_ids(session);codes={id:code for code,id in dictionary.items()}
    deposits={}
    for region,resource,amount in session.execute(select(RegionZasob.region_id,RegionZasob.zasob_id,RegionZasob.zloze_ilosc).join(Region,Region.region_id==RegionZasob.region_id).where(Region.panstwo_id.in_(controlled_ids(session,country)),RegionZasob.zasob_id.in_(codes))):
        deposits.setdefault(str(region),{})[codes[resource]]=int(amount or 0)
    plants=list(session.scalars(select(PowerPlant).where(PowerPlant.panstwo_id==country,PowerPlant.removed_at.is_(None))))
    factories=list(session.scalars(select(AmmunitionFactory).where(AmmunitionFactory.panstwo_id==country,AmmunitionFactory.removed_at.is_(None))))
    powered=powered_factories(session,factories,sum(plant_output(session,p) for p in plants if power_can_work(session,p)),resident_demand(session,country))
    objects=[object_data(row,category,powered) for category,model in [('factory',AmmunitionFactory),('power',PowerPlant),('mine',Mine)] for row in session.scalars(select(model).where(model.panstwo_id==country,model.removed_at.is_(None)).order_by(model.id))]
    remaining={region:dict(values) for region,values in deposits.items()}
    from game.infrastructure_effects import extraction_time_factor
    rail={str(id):level for id,level in session.execute(select(Region.region_id,Region.region_stan_infra_kolejowej).where(Region.region_id.in_({int(obj['regionId']) for obj in objects if obj['category']=='mine'} or {0})))}
    for obj in objects:
        if obj['category']!='mine':continue
        region=remaining.get(obj['regionId'],{})
        deposit=max(0,region.get(obj['kind'],0))
        active=obj['ready'] and obj['health']>0
        factor=extraction_time_factor(rail.get(obj['regionId']))
        obj['extractionTimePercent']=int(factor*100) if factor is not None else None
        daily=0 if factor is None else float((Decimal(str(obj['dailyExtraction']))/factor).quantize(Decimal('0.01')))
        obj['effectiveDailyExtraction']=min(daily,deposit) if active else 0
        if active:obj['status']=('pracuje' if deposit else 'brak złoża') if factor is not None else 'brak infrastruktury'
        region[obj['kind']]=deposit-obj['effectiveDailyExtraction']
    return dict(deposits=deposits,energy=energy_balance(session,country),budget=str(sector_balances(session,budget)['infrastructure']['remaining']) if budget else '0',
        technologies={key:researched(session,country,key) for key in TECHNOLOGIES},technologyLabels={key:rule['label'] for key,rule in TECHNOLOGIES.items()},
        factories=FACTORIES,powerPlants=POWER_PLANTS,mines={key:dict(label=rule[0],technology=rule[1],costs=[cost*1000000000 for cost in rule[2]],extraction=rule[3],days=rule[4]) for key,rule in MINE_RULES.items()},goods=goods_catalog(),
        objects=objects)
