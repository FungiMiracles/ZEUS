"""Planowanie wieloetapowe PAGA2.

Cel (np. „fabryka czołgów”) jest rozkładany na ścieżkę etapów wynikającą z reguł gry:
technologie (zakup punktów rozwoju → inwestycja, od korzenia drzewa) → surowce do produkcji (kopalnia, gdy jest złoże;
w przeciwnym razie zakup w handlu) → energia (elektrownia, gdy brakuje mocy) → budowa obiektu.
Ścieżka jest przeliczana przy każdym przebiegu z bieżącego stanu państwa, więc każdy etap jest ponownie sprawdzany
(czy nadal potrzebny, czy możliwy). Cel, którego nie da się osiągnąć (brak złoża, brak wybrzeża, technologia niedostępna),
jest rozpoznawany i zamykany z podanym powodem.
"""
import math
from uuid import uuid5,NAMESPACE_URL
from sqlalchemy import select
from sqlalchemy.orm import Session
from extensions import db
from game.industry_catalog import TECHNOLOGIES,FACTORIES,POWER_PLANTS,MINE_RULES,GOODS
from game.paga2.engine import Adapter,register
from game.paga2.scoring import Option
from game.paga2.models import Paga2Plan,utc_now

POINT_PRICE=400000000          # cena punktu rozwoju (game/research_service.POINT_PRICE)
MINE_COSTS={code:values[2][0]*1000000000 for code,values in MINE_RULES.items()}
ABANDON_AFTER=720              # przebiegów bez postępu (~30 dni przy cyklu co godzinę, ponad półrocze gry), po których plan jest porzucany
RESOURCE_LABELS={'wegiel_kamienny':'węgiel kamienny','ropa_naftowa':'ropa naftowa','zloto':'złoto','srebro':'srebro','kamien':'kamień','natsyt':'natsyt',
                 'kerbit':'kerbit','cemium':'cemium','zelazo':'żelazo','uran':'uran'}

# Cele służące priorytetom strategicznym (kolejność = preferencja w obrębie priorytetu).
PRIORITY_GOALS={
    'offensive_army':['factory:tanks','factory:missiles','factory:armored','factory:drones','factory:fighters'],
    'conquest':['factory:tanks','factory:armored','factory:missiles'],
    'defensive_army':['factory:interceptor_ammo','tech:radar','factory:missiles'],
    'production':['factory:chips','mine:zelazo','mine:ropa_naftowa','factory:interceptor_ammo'],
    'research':['tech:it_industry','tech:chip_simple','tech:energy_industry','tech:environment_tech','tech:mining_industry'],
    'infrastructure':['power:wind','power:solar','mine:kamien','mine:wegiel_kamienny'],
    'environment':['tech:air_filters','tech:waste_filters','power:solar','power:wind'],
    'trade':['mine:zloto','mine:srebro','mine:kerbit','mine:natsyt','mine:ropa_naftowa'],
}
# Powinowactwo cech do rodzajów celów (skala -1..1).
MILITARY_FACTORIES={'tanks','missiles','armored','drones','fighters','shipyard','interceptor_ammo'}


def goal_label(goal):
    kind,_,code=goal.partition(':')
    if kind=='tech':return 'Technologia: '+TECHNOLOGIES.get(code,{}).get('label',code)
    if kind=='factory':return FACTORIES.get(code,{}).get('label',code)
    if kind=='mine':return MINE_RULES.get(code,(code,))[0]
    if kind=='power':return POWER_PLANTS.get(code,{}).get('label',code)
    if kind in ('recapture','conquer'):
        target,_,id=code.partition(':')
        return ('Odbicie ' if kind=='recapture' else 'Zdobycie ')+('miasta' if target=='city' else 'bazy')+f' #{id}'
    return goal


PLANNER_KINDS=('tech','factory','mine','power')   # plany wojskowe (recapture/conquer) prowadzi moduł wojny


def goal_traits(goal):
    kind,_,code=goal.partition(':')
    if kind=='factory':return {'industrialism':.7,'militarism':.6 if code in MILITARY_FACTORIES else 0,'ecology':-.3}
    if kind=='mine':return {'industrialism':.6,'ecology':-.4,'trade_propensity':.3 if code in ('zloto','srebro','kerbit','natsyt') else 0}
    if kind=='power':return {'industrialism':.4,'ecology':.6 if code in ('wind','solar') else -.6}
    if code in ('air_filters','waste_filters','environment_tech'):return {'ecology':.8}
    if code=='radar':return {'militarism':.4,'secrecy':.3}
    return {'ambition':.3}


def goal_categories(goal):
    kind,_,code=goal.partition(':')
    if kind=='factory' and code in MILITARY_FACTORIES:return {'imperialist':.6,'hegemonic':.4,'isolationist':.2}
    if kind in ('factory','mine'):return {'economic':.6}
    if kind=='power':return {'economic':.3,'welfare':.2}
    return {'economic':.2}


# ---------------- rozkład celu na etapy ----------------

def step(key,kind,label,status,params=None,reason=None,cost=0,sector=None):
    return {'key':key,'kind':kind,'label':label,'status':status,'params':params or {},'reason':reason,'cost':cost,'sector':sector}


class Plan:
    """Wynik rozkładu: lista etapów (statusy: done / ready / blocked / building / external) albo powód niemożliwości."""
    def __init__(self):self.steps=[];self.impossible=None;self._seen=set()
    def add(self,item):
        if item['key'] not in self._seen:self._seen.add(item['key']);self.steps.append(item)
    def blocked(self):return any(s['status'] in ('ready','blocked') for s in self.steps)
    def next(self):
        for s in self.steps:
            if s['status']=='ready':return s
            if s['status']=='blocked':return None
        return None
    def done(self):return self.impossible is None and all(s['status'] in ('done','building','external') for s in self.steps)


def research(plan,node,h,points):
    """Ścieżka technologii od korzenia. points: punkty rozwoju jeszcze nieprzydzielone w tym planie (słownik z kluczem 'left')."""
    rule=TECHNOLOGIES.get(node)
    if rule is None:plan.impossible=f'Technologia {node} jest niedostępna w grze.';return False
    if h.developed(node):plan.add(step(f'tech:{node}','research',f'Technologia: {rule["label"]}','done'));return True
    if getattr(h,'researching',None) and h.researching(node):
        # 13 Nov 2026: punkty zainwestowane, trwa czas rozwoju — czekamy (bez ponownej inwestycji)
        plan.add(step(f'tech:{node}','research',f'Technologia: {rule["label"]} — w trakcie rozwoju','blocked',reason='Trwa rozwój technologii.'));return False
    # Cała ścieżka od korzenia drzewa: technologie nadrzędne najpierw, potomne jako kolejne etapy.
    parent_ready=research(plan,rule['parent'],h,points) if rule['parent'] else True
    if plan.impossible:return False
    need=h.missing_points(node);use=min(points['left'],need);short=need-use;points['left']-=use
    if short>0:
        plan.add(step(f'buy:{node}','buy_points',f'Zakup {short} pkt rozwoju na „{rule["label"]}”','ready',{'node':node,'count':short},cost=short*POINT_PRICE,sector='research'))
    status='ready' if parent_ready and short==0 else 'blocked'
    reason=None if status=='ready' else ('Najpierw technologia nadrzędna.' if not parent_ready else 'Brakuje punktów rozwoju.')
    plan.add(step(f'invest:{node}','invest',f'Inwestycja {need} pkt w „{rule["label"]}”','ready' if status=='ready' else 'blocked',{'node':node,'count':need},reason))
    return False


def mine(plan,resource,h,*,required=True):
    rule=MINE_RULES.get(resource)
    if rule is None:plan.impossible=f'Nie ma kopalni surowca {resource}.';return False
    if h.has_mine(resource):
        plan.add(step(f'mine:{resource}','build_mine',rule[0],'done' if h.mine_ready(resource) else 'building'));return True
    if not h.deposit_regions(resource):
        if required:plan.impossible=f'Brak złóż surowca „{RESOURCE_LABELS.get(resource,resource)}” we własnych, nieokupowanych regionach.'
        return False
    tech_ready=research(plan,rule[1],h,plan.points)
    plan.add(step(f'mine:{resource}','build_mine',rule[0],'ready' if tech_ready else 'blocked',{'resource':resource,'regions':h.deposit_regions(resource)},
                  None if tech_ready else 'Wymagana technologia wydobycia.',cost=MINE_COSTS[resource],sector='infrastructure'))
    return False


def supply(plan,resource,h):
    """Surowiec/towar do produkcji: zapas, kopalnia (jeśli jest złoże), fabryka chipów albo zakup w handlu (etap nieblokujący)."""
    if h.stock.get(resource,0)>0 or h.mine_ready(resource):return
    if resource in MINE_RULES:
        if h.deposit_regions(resource):mine(plan,resource,h);return
        plan.add(step(f'buy:{resource}','acquire',f'Zakup surowca „{RESOURCE_LABELS.get(resource,resource)}” w handlu (brak własnych złóż)','external',{'resource':resource}))
        return
    if resource.startswith('chip_') and resource!='chip_simple' and not h.has_factory('chips'):
        plan.add(step(f'buy:{resource}','acquire',f'Zakup towaru „{GOODS.get(resource,(resource,))[0]}” w handlu','external',{'resource':resource}));return
    if resource.startswith('chip_'):
        if not h.has_factory('chips'):factory(plan,'chips',h,top=False)
        return


def energy(plan,needed,h,key):
    """Wystarczająca moc dla nowego odbiorcy; elektrownia bez paliwa (wiatr/słońce), węglowa przy dużym zapotrzebowaniu i złożu węgla."""
    if h.energy_surplus()>=needed:return True
    deficit=needed-h.energy_surplus()
    idle=h.idle_capacity() if hasattr(h,'idle_capacity') else 0
    if idle>0:
        # 12 Nov 2026: elektrownie stoją z braku paliwa — kolejne by nie pomogły (pętla budowy). Najpierw paliwo (wydobycie lub zakup).
        supply(plan,'wegiel_kamienny',h);supply(plan,'uran',h)
        plan.add(step(f'fuel:{key}','acquire','Paliwo dla nieczynnych elektrowni (zakup w handlu lub wydobycie)','blocked',{'resource':'wegiel_kamienny'},
                      f'{idle:.0f} jedn. mocy stoi bez paliwa.'))
        return False
    kind='coal' if deficit>24 and (h.deposit_regions('wegiel_kamienny') or h.stock.get('wegiel_kamienny',0)>0) else 'solar' if h.developed('power_solar') else 'wind'
    rule=POWER_PLANTS[kind]
    tech_ready=research(plan,rule['technology'],h,plan.points)
    if kind=='coal':supply(plan,'wegiel_kamienny',h)
    count=math.ceil(deficit/rule['production'][0])
    plan.add(step(f'power:{kind}:{key}','build_power',f'{rule["label"]} (brakuje {deficit:.0f} jedn. energii; potrzeba ok. {count})','ready' if tech_ready else 'blocked',
                  {'kind':kind},None if tech_ready else 'Wymagana technologia energetyczna.',cost=rule['costs'][0],sector='infrastructure'))
    return False


def factory(plan,kind,h,*,top=True):
    rule=FACTORIES.get(kind)
    if rule is None:plan.impossible=f'Nie ma fabryki {kind}.';return False
    if h.has_factory(kind):plan.add(step(f'factory:{kind}','build_factory',rule['label'],'done'));return True
    if kind=='shipyard' and not h.coastal_regions():plan.impossible='Stocznia wymaga własnego, nieokupowanego regionu nadmorskiego.';return False
    level=rule['levels'][0]
    techs=all([research(plan,t,h,plan.points) for t in level['technologies']])
    if plan.impossible:return False
    for resource in level['inputs']:supply(plan,resource,h)
    if plan.impossible:return False
    powered=energy(plan,level['energy'],h,kind)
    ready=techs and powered
    plan.add(step(f'factory:{kind}','build_factory',rule['label'],'ready' if ready else 'blocked',{'kind':kind,'coastal':kind=='shipyard'},
                  None if ready else 'Najpierw technologie i energia.',cost=level['cost'],sector='infrastructure'))
    return ready


def decompose(goal,h):
    plan=Plan();plan.points={'left':h.points}
    kind,_,code=goal.partition(':')
    if kind=='tech':research(plan,code,h,plan.points)
    elif kind=='factory':factory(plan,code,h)
    elif kind=='mine':mine(plan,code,h)
    elif kind=='power':
        rule=POWER_PLANTS.get(code)
        if rule is None:plan.impossible=f'Nie ma elektrowni {code}.'
        elif h.has_plant(code):plan.add(step(f'power:{code}','build_power',rule['label'],'done'))
        else:
            ready=research(plan,rule['technology'],h,plan.points)
            if rule['fuel']:
                if not h.deposit_regions(rule['fuel']) and not h.stock.get(rule['fuel'],0):plan.impossible=f'Brak paliwa dla elektrowni: {RESOURCE_LABELS.get(rule["fuel"])}.'
                else:supply(plan,rule['fuel'],h)
            plan.add(step(f'power:{code}','build_power',rule['label'],'ready' if ready else 'blocked',{'kind':code},cost=rule['costs'][0],sector='infrastructure'))
    else:plan.impossible=f'Nieznany rodzaj celu: {goal}.'
    return plan


# ---------------- adapter silnika ----------------

def _holdings(ctx):
    if getattr(ctx,'_holdings',None) is None:
        from game.paga2.holdings import Holdings
        with Session(db.engine) as session:ctx._holdings=Holdings(session,ctx.country_id,ctx.now)
    return ctx._holdings


def _km(ctx):
    if getattr(ctx,'_km',None) is None:
        from game.military_models import MapCalibration
        with Session(db.engine) as session:
            scale=session.get(MapCalibration,1);ctx._km=scale.km_per_unit if scale else None
    return ctx._km


def max_plans(ctx):return 1+int(ctx.traits.get('ambition',50)//50)


def step_option(ctx,plan_row,item,weight_key):
    params=item['params'];kind=item['kind']
    option=Option(key=f'plan:{plan_row.id}:{item["key"]}',domain='planning' if kind in ('buy_points','invest') else 'economy',action=kind.upper(),
                  label=f'{goal_label(plan_row.goal)} — {item["label"]}',effects={weight_key:1.0} if weight_key else {},traits=goal_traits(plan_row.goal),
                  categories=goal_categories(plan_row.goal),cost=float(item['cost'] or 0),sector=item['sector'],base=6.0,
                  notes=[f'Etap planu #{plan_row.id}: {goal_label(plan_row.goal)}.'],payload={'plan_id':plan_row.id,'step':item,'group':f'plan:{plan_row.id}'})
    if kind=='buy_points':
        # Zakup w granicach rozwagi finansowej: tylu punktów, ile pozwala limit jednej akcji w sektorze badań.
        affordable=int(.6*ctx.limits['per_action']*ctx.sector_start('research')//POINT_PRICE)
        # 13 Nov 2026: co najmniej 1 punkt, jeśli sektor badań ma na niego środki — mały budżet nie blokuje rozwoju na zawsze
        if affordable<1 and ctx.sector_start('research')>=POINT_PRICE:affordable=1
        count=min(params['count'],affordable)
        if count<1:option.cost=float(POINT_PRICE);option.notes.append('Budżet badań nie wystarcza nawet na 1 punkt w granicach rozwagi.')
        else:
            option.cost=float(count*POINT_PRICE);option.payload['count']=count
            if count==1 and int(.6*ctx.limits['per_action']*ctx.sector_start('research')//POINT_PRICE)<1:option.payload['minimal_purchase']=True
        if count<params['count']:option.notes.append(f'Zakup częściowy: {count} z {params["count"]} pkt (limit wydatku jednej akcji).')
    return option


def propose(ctx):
    h=_holdings(ctx);options=[]
    from game.paga2.catalog import priority_weights
    weights=priority_weights(ctx.priorities)
    with Session(db.engine) as session,session.begin():
        plans=[row for row in session.scalars(select(Paga2Plan).where(Paga2Plan.country_id==ctx.country_id,Paga2Plan.status=='ACTIVE').order_by(Paga2Plan.id).with_for_update())
               if row.goal.partition(':')[0] in PLANNER_KINDS]
        now=utc_now()
        for row in plans:
            if row.priority and row.priority not in ctx.priorities:
                row.status='ABANDONED';row.reason='Priorytet, któremu służył plan, nie należy już do priorytetów państwa.';row.finished_at=now;continue
            evaluation=decompose(row.goal,h)
            row.steps=evaluation.steps;row.updated_at=now
            if evaluation.impossible:row.status='IMPOSSIBLE';row.reason=evaluation.impossible;row.finished_at=now;continue
            if evaluation.done():row.status='DONE';row.reason='Cel osiągnięty.';row.finished_at=now;continue
            item=evaluation.next()
            row.idle_cycles+=1  # zerowane po wykonaniu etapu (execute)
            if item is None:
                row.reason='Oczekiwanie: '+'; '.join(s['reason'] or s['label'] for s in evaluation.steps if s['status']=='blocked')[:500]
            else:options.append(step_option(ctx,row,item,row.priority))
            if row.idle_cycles>ABANDON_AFTER:row.status='ABANDONED';row.reason=f'Brak postępu przez {ABANDON_AFTER} przebiegów.';row.finished_at=now
        active=[row for row in plans if row.status=='ACTIVE']
        goals={row.goal for row in active}
        if len(active)<max_plans(ctx):
            closed=set(session.scalars(select(Paga2Plan.goal).where(Paga2Plan.country_id==ctx.country_id,Paga2Plan.status.in_(['DONE','IMPOSSIBLE']))))
            candidates={}
            for priority,weight in weights.items():
                for rank,goal in enumerate(PRIORITY_GOALS.get(priority,[])):
                    if goal in goals or goal in closed:continue
                    candidates.setdefault(goal,{'effects':{},'priority':priority})
                    candidates[goal]['effects'][priority]=max(candidates[goal]['effects'].get(priority,0),1.0-.15*rank)
            for goal,info in sorted(candidates.items(),key=lambda item:-sum(weights[p]*v for p,v in item[1]['effects'].items()))[:6]:
                evaluation=decompose(goal,h)
                if evaluation.impossible or evaluation.done():continue
                cost=sum(s['cost'] for s in evaluation.steps if s['status'] in ('ready','blocked'))
                options.append(Option(key=f'plan:new:{goal}',domain='planning',action='PLAN_START',label=f'Nowy plan: {goal_label(goal)}',
                                      effects=info['effects'],traits=goal_traits(goal),categories=goal_categories(goal),
                                      base=-2.0-min(6.0,cost/3e10),  # rozpoczęcie zobowiązuje do kosztów kolejnych etapów
                                      notes=[f'Etapy: {len(evaluation.steps)}; szacowany koszt pozostałych etapów: {cost/1e9:.1f} MLD ROI.']+[s['label'] for s in evaluation.steps][:8],
                                      payload={'goal':goal,'priority':info['priority'],'steps':evaluation.steps,'group':'plan:new'}))
    # 13 Nov 2026: plan rozwoju zawsze aktywny — bez aktywnego planu rozpoczęcie najlepszego jest decyzją wymaganą,
    # a jeden etap najstarszego aktywnego planu na przebieg wykonuje się poza limitem działań (rozwój nie przegrywa z obroną).
    starts=[o for o in options if o.action=='PLAN_START']
    if starts and not active:
        for option in starts:option.payload['required']=True
    steps=[o for o in options if o.action!='PLAN_START']
    if steps:steps[0].payload['required']=True
    return options


def check(ctx,option):
    if option.action=='PLAN_START':return None
    item=option.payload['step']
    if item['kind'] in ('build_factory','build_mine','build_power'):
        h=_holdings(ctx);km=_km(ctx)
        regions=item['params'].get('regions')
        from game.paga2.location import site,MIN_DISTANCE_KM
        region,point=site(h,km,seed=option.key,regions=regions,coastal=bool(item['params'].get('coastal')))
        if region is None:return point
        option.payload['site']={'region_id':region,'x':point[0],'y':point[1]}
        option.notes.append(f'Lokalizacja: region {region} (zwykle min. {MIN_DISTANCE_KM:.0f} km od innych własnych obiektów).')
    if item['kind']=='buy_points' and 'count' not in option.payload:return 'Za mało środków w budżecie badań na zakup punktów w granicach rozwagi.'
    return None


def execute(ctx,option):
    if option.action=='PLAN_START':
        with Session(db.engine) as session,session.begin():
            row=Paga2Plan(country_id=ctx.country_id,goal=option.payload['goal'],priority=option.payload['priority'],status='ACTIVE',
                          steps=option.payload['steps'],reason='Rozpoczęty.',game_created_at=ctx.now)
            session.add(row);session.flush();plan_id=row.id
        return {'status':200,'plan_id':plan_id}
    item=option.payload['step'];params=item['params'];kind=item['kind']
    request_id=str(uuid5(NAMESPACE_URL,f'paga2:{ctx.request_key}:{option.key}'))
    if kind=='buy_points':
        status,data=ctx.call('/game/badania/zmien',json={'action':'buy','count':option.payload['count'],'expected_point_price':POINT_PRICE,'request_id':request_id})
    elif kind=='invest':
        status,data=ctx.call('/game/badania/zmien',json={'action':'invest','node':params['node'],'count':params['count'],'request_id':request_id})
    elif kind=='build_mine':
        site=option.payload['site']
        status,data=ctx.call('/game/handel/wydobycie/buduj',json={'resource':params['resource'],'level':1,'request_id':request_id,**site})
    elif kind in ('build_factory','build_power'):
        site=option.payload['site']
        status,data=ctx.call('/game/infrastruktura/obiekty/zmien',json={'action':'build','category':'factory' if kind=='build_factory' else 'power','kind':params['kind'],'level':1,'request_id':request_id,**site})
    else:return {'status':400,'error':'Nieobsługiwany etap planu.'}
    data=data if isinstance(data,dict) else {}
    if status<400:
        ctx._holdings=None  # stan się zmienił
        with Session(db.engine) as session,session.begin():
            row=session.get(Paga2Plan,option.payload['plan_id'],with_for_update=True)
            if row is not None:row.idle_cycles=0;row.updated_at=utc_now();row.reason=f'Wykonano etap: {item["label"]}.'
    return {'status':status,'error':data.get('error'),'site':option.payload.get('site')}


ADAPTER=register(Adapter(name='planner',modes=('CYCLIC',),propose=propose,execute=execute,check=check))
