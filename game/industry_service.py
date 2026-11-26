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
    if FACTORIES[f.kind].get('on_demand'):return False   # 13 Nov 2026: fabryka rakiet atomowych produkuje tylko na zamówienie (game.nuclear)
    return f.removed_at is None and f.health>0 and not f.paused and (FACTORIES[f.kind].get('on_demand') or (f.production_target or 0)>0) and (f.production_progress>0 or has_inputs(session,f.panstwo_id,FACTORIES[f.kind]['levels'][f.level-1]['inputs']))
def idle_energy(f):
    """22 Nov 2026: wstrzymana (sprawna) fabryka pobiera połowę energii z czasu pracy; fabryki na zamówienie — bez zmian."""
    if f.removed_at is not None or f.health<=0 or not f.paused or FACTORIES[f.kind].get('on_demand'):return Decimal(0)
    return Decimal(str(FACTORIES[f.kind]['levels'][f.level-1]['energy']))/2
def finish_order(session,country,f,rule):
    f.paused=True;f.production_target=None;f.running=False
    notify(session,country,FACTORIES[f.kind]['label']+f' #{f.id}: zlecenie produkcji zrealizowane — fabryka przeszła w stan wstrzymania.')
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
    factories=[f for f in session.scalars(select(AmmunitionFactory).where(AmmunitionFactory.panstwo_id==country,AmmunitionFactory.removed_at.is_(None)).order_by(AmmunitionFactory.id).with_for_update())
               if not FACTORIES[f.kind].get('on_demand')]   # produkcja na zamówienie rozliczana w game.nuclear.settle_orders
    # Event times are anchored to each object's own commissioning time.
    from game.mining_service import extract_country
    resident=base_demand(session,country)
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
        powered=powered_factories(session,factories,sum(plant_output(session,p) for p in plants if p.running),resident+sum((idle_energy(f) for f in factories),Decimal(0)))
        for f in factories:
            if f.produced_at+DAY>moment:continue
            workable=factory_can_work(session,f);active=workable and f.id in powered;rule=FACTORIES[f.kind]['levels'][f.level-1]
            if active:
                if rule['days']==1:
                    count=min([rule['quantity'],int(f.production_target or 0)]+[available(session,country,code)//amount for code,amount in rule['inputs'].items()])
                    consume(session,country,rule['inputs'],count);add_output(session,country,rule['product'],count)
                    f.production_target=int(f.production_target or 0)-count
                else:
                    if f.production_progress==0:
                        consume(session,country,rule['inputs'])
                        f.cycle_days=(month_after(f.produced_at)-f.produced_at).days if rule['days']=='month' else rule['days']
                    f.production_progress+=1
                    if f.production_progress>=f.cycle_days:
                        add_output(session,country,rule['product'],1);f.production_progress=0
                        f.production_target=int(f.production_target or 0)-1
                f.ever_worked=True
                if f.production_target<=0:finish_order(session,country,f,rule);f.produced_at+=DAY;continue
            elif f.running and f.ever_worked and not f.paused:
                notify(session,country,FACTORIES[f.kind]['label']+f' #{f.id}: produkcja została wstrzymana — '+('brak energii w sieci (deficyt energii).' if workable else 'brak surowców lub uszkodzenie.'))
            f.running=active;f.produced_at+=DAY
        session.flush()
    extract_country(session,country,now)
    from game.nuclear import settle_orders
    settle_orders(session,country,now)
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

def on_demand_energy(session,country):
    """18 Nov 2026: fabryki produkujące na zamówienie (rakiety nuklearne) pobierają energię tylko w trakcie realizacji
    zamówienia (zbudowana, sprawna fabryka z aktywnym zamówieniem). Pobór ma pierwszeństwo przed pozostałymi fabrykami."""
    from game.nuclear_models import NuclearOrder
    from game.nuclear import factory_ready_at
    now=game_now();total=Decimal(0)
    for f in session.scalars(select(AmmunitionFactory).where(AmmunitionFactory.panstwo_id==country,AmmunitionFactory.removed_at.is_(None),AmmunitionFactory.health>0)):
        if not FACTORIES[f.kind].get('on_demand') or factory_ready_at(f)>now:continue
        if session.scalar(select(NuclearOrder.id).where(NuclearOrder.factory_id==f.id,NuclearOrder.status=='active').limit(1)) is not None:
            total+=Decimal(str(FACTORIES[f.kind]['levels'][f.level-1]['energy']))
    return total

def base_demand(session,country):
    """Zużycie mieszkańców i fabryk na zamówienie — odejmowane od produkcji przed rozdziałem energii na fabryki."""
    return resident_demand(session,country)+on_demand_energy(session,country)

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
    special=on_demand_energy(session,country)
    idle=sum((idle_energy(f) for f in factories),Decimal(0))
    powered=powered_factories(session,factories,production,resident+special+idle)
    demand=resident+special+idle+sum(FACTORIES[f.kind]['levels'][f.level-1]['energy'] for f in factories if factory_can_work(session,f))
    consumption=resident+special+idle+sum(FACTORIES[f.kind]['levels'][f.level-1]['energy'] for f in factories if f.id in powered)
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
    return dict(consumption=str(consumption),production=str(production),residents=str(resident),idleFactories=str(idle),sufficient=production>=demand,sources=sources,
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
            from game.nuclear import require_clear
            require_clear(session,x,y)   # 13 Nov 2026: strefa skażenia po uderzeniu atomowym
            if category=='factory' and kind=='shipyard':
                from game.military_geography import naval_location_allowed
                from game.military_flights import calibration
                coastal=session.scalar(select(Region.region_polozenie_id).where(Region.region_id==region))
                if coastal in (None,1) or not naval_location_allowed(region,x,y,calibration(session).km_per_unit):
                    raise FinanceError('Stocznia musi leżeć we własnym regionie nadmorskim, w pasie do 3 km od wybrzeża, tak jak baza morska.')
            military_cost=None
            if category=='factory' and FACTORIES[kind].get('budget_sector')=='armed_forces':
                # 13 Nov 2026: fabryka rakiet z głowicą nuklearną — płatna z budżetu sił zbrojnych (wydatek wojskowy)
                from game.military_service import military_budget
                military,_,free=military_budget(session,country)
                if military is None or free<cost:raise FinanceError('Za mało środków w budżecie sił zbrojnych na bieżący okres budżetowy.')
                military_cost,cost=cost,Decimal(0)
            budget=current_budget(session,country,cost)
            if military_cost is not None:
                from game.military_models import MilitaryExpense
                session.add(MilitaryExpense(panstwo_id=country,budget_id=budget.id,base_id=None,level=1,amount=military_cost))
            if category=='factory':
                obj=AmmunitionFactory(panstwo_id=country,region_id=region,budget_id=budget.id,map_x=x,map_y=y,level=level,kind=kind,cost=0,created_game_at=now,produced_at=now,request_id=key,
                                      waste_filter=False,degradation_points=FACTORY_DEGRADATION,paused=not FACTORIES[kind].get('on_demand'))   # 22 Nov 2026: nowa fabryka czeka na zlecenie
                change_degradation(session,region,obj.degradation_points)
            else:
                obj=PowerPlant(panstwo_id=country,region_id=region,map_x=x,map_y=y,level=1,kind=kind,investment=cost,created_game_at=now,checked_at=now,
                               air_filter=False,pollution_points=COAL_POLLUTION if kind=='coal' else 0)
                change_pollution(session,region,obj.pollution_points)
            session.add(obj);session.flush()
        else:
            object_id=data.get('object_id')
            if type(object_id) is not int:raise FinanceError('Wybierz obiekt.')
            obj=session.scalar(select(models[category]).where(models[category].id==object_id).with_for_update())
            if obj is None or obj.removed_at is not None:raise FinanceError('Nie znaleziono własnego aktywnego obiektu.')
            host_removal=False
            if obj.panstwo_id!=country:
                from game.foreign_mining import host_may_remove
                if category!='mine' or action!='remove' or not host_may_remove(session,obj,country,now):raise FinanceError('Obcy obiekt można zlikwidować na własnym terytorium po 180 dniach od ukończenia budowy.')
                host_removal=True
            if action!='remove':
                # Upgrades, filters and repairs are construction too; liquidation stays possible.
                from game.land_war import require_buildable
                require_buildable(session,obj.region_id,country)
            on_demand=category=='factory' and FACTORIES[obj.kind].get('on_demand')
            if on_demand and action in ('order','cancel_order'):
                from game.nuclear import order_missiles,cancel_order
                if action=='order':order_missiles(session,country,obj,data.get('count'),key,now)
                else:cancel_order(session,country,obj,now)
                budget=current_budget(session,country,Decimal(0))
                session.add(IndustryMovement(panstwo_id=country,budget_id=budget.id,amount=0,request_id=key,payload=data,sector='armed_forces'))
                return obj.id
            if on_demand and action in ('pause','resume','upgrade'):raise FinanceError(FACTORIES[obj.kind]['label']+' produkuje wyłącznie na zamówienie.')
            if action=='remove':
                if on_demand and FACTORIES[obj.kind].get('budget_sector')=='armed_forces':value=0   # koszt budowy pokryty z budżetu sił zbrojnych — likwidacja bez zwrotu (fabryka satelitów: zwrot jak zwykła fabryka, 26 Nov 2026)
                elif category=='factory':value=FACTORIES[obj.kind]['levels'][obj.level-1]['cost']
                elif category=='power':value=min(Decimal(POWER_PLANTS[obj.kind]['costs'][obj.level-1]),Decimal(obj.investment))   # 21 Nov 2026: nie więcej niż faktyczny nakład (podwyżka cen elektrowni)
                else:value=MINE_RULES[obj.resource][2][obj.level-1]*1000000000
                cost=0 if host_removal else -Decimal(value)/4;obj.removed_at=now
                if category in ('factory','power'):obj.running=False
                # Liquidation removes the pollution the plant added; filter costs are not refunded.
                if category in ('power','mine') and obj.pollution_points:change_pollution(session,obj.region_id,-obj.pollution_points);obj.pollution_points=0
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
            elif action=='pause' and category=='factory':obj.paused=True;obj.production_target=None;obj.running=False
            elif action=='resume' and category=='factory':
                # 22 Nov 2026: wznowienie = zlecenie produkcji określonej liczby sztuk (po realizacji fabryka sama się wstrzymuje)
                if FACTORIES[obj.kind].get('on_demand'):raise FinanceError('Ta fabryka produkuje na zamówienie.')
                if obj.health<=0:raise FinanceError('Zniszczona fabryka nie może produkować.')
                quantity=data.get('quantity')
                if type(quantity) is not int or not 1<=quantity<=1000000000:raise FinanceError('Podaj liczbę sztuk do wyprodukowania (co najmniej 1).')
                obj.paused=False;obj.production_target=quantity;obj.running=False
            else:raise FinanceError('Nieprawidłowa operacja obiektu.')
            if host_removal:
                budget=session.scalar(select(StateBudget).where(StateBudget.panstwo_id==country).order_by(StateBudget.id.desc()).limit(1))
                if budget is None:return obj.id
            else:budget=current_budget(session,country,cost,environment)
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
                   wasteFilterCost=WASTE_FILTER_COSTS[obj.level-1] if not obj.waste_filter else None,paused=obj.paused,target=obj.production_target,idleEnergy=float(idle_energy(obj)),energy=spec['energy'],product=spec['product'],quantity=spec['quantity'],days=spec['days'],missingInputs=missing,ready=True,progress=100,effectiveQuantity=spec['quantity'] if status=='pracuje' else 0)
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
    refund=Decimal(FACTORIES[obj.kind]['levels'][obj.level-1]['cost'] if category=='factory' else min(Decimal(POWER_PLANTS[obj.kind]['costs'][obj.level-1]),Decimal(obj.investment)))/4
    if category=='factory' and FACTORIES[obj.kind].get('on_demand'):
        # 13 Nov 2026: fabryka rakiet z głowicą nuklearną — budowa 31 dni, produkcja na zamówienie
        from sqlalchemy.orm import object_session
        from game.nuclear import factory_info
        info=factory_info(object_session(obj),obj,game_now());extra.update(info)
        if rule.get('budget_sector')=='armed_forces':refund=Decimal(0)
        status='zniszczona' if obj.health<=0 else 'w budowie' if not info['ready'] else 'produkuje' if info['order'] else 'czeka na zamówienie'
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
    powered=powered_factories(session,factories,sum(plant_output(session,p) for p in plants if power_can_work(session,p)),base_demand(session,country))
    objects=[object_data(row,category,powered) for category,model in [('factory',AmmunitionFactory),('power',PowerPlant),('mine',Mine)] for row in session.scalars(select(model).where(model.panstwo_id==country,model.removed_at.is_(None)).order_by(model.id))]
    from game.foreign_mining import map_regions
    foreign=map_regions(session,country)
    known=set(foreign_id for foreign_id,r in foreign.items() if r['permit'])
    for rid,resource,amount in session.execute(select(RegionZasob.region_id,RegionZasob.zasob_id,RegionZasob.zloze_ilosc).where(RegionZasob.region_id.in_([int(r) for r in known] or [0]),RegionZasob.zasob_id.in_(codes))):
        deposits.setdefault(str(rid),{})[codes[resource]]=int(amount or 0)
    from game.foreign_mining import host_may_remove
    for mine in session.scalars(select(Mine).join(Region,Region.region_id==Mine.region_id).where(Region.panstwo_id.in_(controlled_ids(session,country)),Mine.panstwo_id!=country,Mine.removed_at.is_(None))):
        obj=object_data(mine,'mine',powered);obj['hostManaged']=True;obj['canHostRemove']=host_may_remove(session,mine,country,game_now());objects.append(obj)
    remaining={region:dict(values) for region,values in deposits.items()}
    from game.infrastructure_effects import extraction_time_factor
    from services.natural_resources import RESOURCES as _resources
    RESOURCE_LABELS=dict(_resources)
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
        # 23 Nov 2026: status mówi, którego surowca brakuje (np. wyczerpana ropa w regionie z węglem — inny surowiec nie pomaga)
        if active:obj['status']=('pracuje' if deposit else f'złoże wyczerpane — w regionie nie ma już surowca: {RESOURCE_LABELS.get(obj["kind"],obj["kind"]).lower()}') if factor is not None else 'brak infrastruktury'
        region[obj['kind']]=deposit-obj['effectiveDailyExtraction']
    return dict(foreignRegions=foreign,deposits=deposits,energy=energy_balance(session,country),budget=str(sector_balances(session,budget)['infrastructure']['remaining']) if budget else '0',
        technologies={key:researched(session,country,key) for key in TECHNOLOGIES},technologyLabels={key:rule['label'] for key,rule in TECHNOLOGIES.items()},
        factories=FACTORIES,powerPlants=POWER_PLANTS,mines={key:dict(label=rule[0],technology=rule[1],costs=[cost*1000000000 for cost in rule[2]],extraction=rule[3],days=rule[4]) for key,rule in MINE_RULES.items()},goods=goods_catalog(),
        objects=objects)
