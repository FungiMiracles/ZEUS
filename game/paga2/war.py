"""PAGA2 — panel wojenny: wypowiedzenie wojny (wyłącznie tryb doraźny), uderzenia rakietowe i lotnicze na regiony,
miasta i obiekty, najazdy lądowe na miasta i bazy, decyzje o okupacji, aneksja oraz odbijanie własnych miast i baz.

Cele wroga pochodzą wyłącznie z ekranu wojennego gracza (obiekty znane z wywiadu, jawne miasta i regiony).
Wykonalność sprawdzana przed decyzją: sprawna baza z odpowiednim sprzętem, zasięg rakiet, zapas rakiet, budżet wojska,
szacowana przewaga w bitwie. Uderzenia jądrowe nie są wykonywane.
"""
from decimal import Decimal
from uuid import uuid5,NAMESPACE_URL
from sqlalchemy import select
from sqlalchemy.orm import Session
from extensions import db
from game.paga2.engine import Adapter,register
from game.paga2.scoring import Option,clip
from game.paga2.finance import result

ORDER='/game/panel-wojenny/rozkaz'
INVASION='/game/panel-wojenny/armia-ladowa'
OCCUPATION='/game/panel-wojenny/okupacja'
DECLARE='/game/dyplomacja/akcje'
RANGES={'short':(0,500),'medium':(500,2000),'long':(2000,10000)}
WAR_RELATIONS=('zle','napiete','wrogie','egzystencjalniewrogie')
TARGET_FIELD={'base':'target_base_id','defense':'target_defense_id','power':'target_power_id','factory':'target_factory_id','mine':'target_mine_id','radar':'target_radar_id','city':'city_id','shipment':'target_shipment_id'}
TARGET_VALUE={'base':10.0,'defense':8.0,'power':7.0,'factory':6.0,'radar':5.0,'mine':4.0,'city':2.0,'shipment':6.5}


def rid(ctx,option):return str(uuid5(NAMESPACE_URL,f'paga2:{ctx.request_key}:{option.key}'))


def war_screen(ctx):return (ctx.screen('military') or {}).get('data') or {}


def war_config(ctx):
    """Konfiguracja panelu wojennego gracza (regiony, miasta, wrogowie, cele lądowe) — czytana raz na przebieg."""
    if getattr(ctx,'_war_config',None) is None:
        from game.paga2.gateway import call
        status,data=call(ctx.app,ctx.actor,'/game/panel-wojenny',keep=('military_config',))
        ctx._war_config=(data or {}).get('military_config') or {} if status<400 else {}
    return ctx._war_config


def km(ctx,a,b):
    from game.paga2.defense import _world
    return _world(ctx).distance_km(a,b)


def missile_for(distance,stock):
    """Rodzaj rakiety o zasięgu obejmującym cel i dostępnym zapasie."""
    for kind,(low,high) in RANGES.items():
        if low<=distance<=high and stock.get(kind,0)>0:return kind
    return None


def salvo(ctx,stock,defended):
    """Wielkość salwy: więcej przy obronie przeciwrakietowej celu; najwyżej część zapasu (tolerancja strat, militaryzm)."""
    share=.1+.25*ctx.traits.get('militarism',50)/100+.15*ctx.traits.get('loss_tolerance',50)/100
    wanted=12+(60 if defended else 0)
    return max(1,int(min(wanted,stock*share)))


def ship_point(ctx,ship):
    """Bieżąca pozycja statku handlowego na trasie (czas gry PAGA2)."""
    from datetime import datetime
    from game.sea_routes import path_position
    try:
        start=datetime.fromisoformat(ship['startsAt'].rstrip('Z'));end=datetime.fromisoformat(ship['arrivesAt'].rstrip('Z'))
        if ctx.now>=end:return None
        return path_position(ship.get('route') or [],(ctx.now-start).total_seconds()/max(1,(end-start).total_seconds()))
    except Exception:return None


def enemy_targets(ctx,screen,config,enemies):
    """Znane obiekty i miasta państw, z którymi trwa wojna: (rodzaj, id, region, punkt, państwo, chroniony)."""
    defended={(d.get('targetKind'),d.get('targetId')) for d in screen.get('defenses',[]) if d.get('countryId') in enemies}
    defended_regions={str(d.get('targetId')) for d in screen.get('defenses',[]) if d.get('countryId') in enemies and d.get('targetKind')=='region'}
    targets=[]
    for kind,key in (('base','bases'),('defense','defenses'),('power','power'),('factory','factories'),('mine','mines'),('radar','radars')):
        for item in screen.get(key,[]):
            if item.get('countryId') not in enemies or not item.get('position') or (item.get('health') is not None and item.get('health')<=0):continue
            region=str(item.get('regionId') or '')
            targets.append((kind,item['id'],region,item['position'],item['countryId'],(kind,item['id']) in defended or region in defended_regions))
    # 12 Nov 2026: ładunki handlowe państw wrogich (gra oznacza je jako możliwe do ataku).
    for ship in screen.get('tradeShips') or []:
        if not ship.get('canAttack') or (ship.get('health') or 0)<=0:continue
        point=ship_point(ctx,ship)
        if point:targets.append(('shipment',ship['id'],str(ship.get('regionId') or ''),point,ship.get('countryId'),False))
    for id,city in (config.get('cities') or {}).items():
        if city.get('countryId') in enemies and city.get('point'):
            targets.append(('city',int(id),str(city.get('regionId')),city['point'],city['countryId'],('city',int(id)) in defended or str(city.get('regionId')) in defended_regions))
    return targets


def strike_options(ctx,forces,screen,config,enemies):
    t=ctx.traits;stock={code:int((value or {}).get('count') or 0) for code,value in (screen.get('missiles') or {}).items()}
    if not any(stock.values()):return []
    sources=[b for b in forces.bases if b.health>0 and b.map_x is not None and b.operational and
             ((b.kind=='land' and (b.garrison or {}).get('launchers',0)>0) or (b.kind=='air' and (b.garrison or {}).get('fighters',0)>0) or (b.kind=='naval' and (b.garrison or {}).get('warships',0)>0))]
    if not sources:return []
    civilian=(100-t.get('agreeableness',50))/100*.5+t.get('provocation',50)/100*.3+('terrorist' in ctx.categories)*.5
    options=[]
    for kind,id,region,point,owner,defended in enemy_targets(ctx,screen,config,enemies):
        if kind=='city' and civilian<.45:continue  # miasta atakują tylko państwa bezwzględne
        best=None
        for base in sources:
            distance=km(ctx,[base.map_x,base.map_y],point)
            if distance is None:continue
            if base.kind=='air':
                # 12 Nov 2026: myśliwiec — zasięg 1000 km, dowolna rakieta z zapasu (najliczniejsza).
                from game.military_flights import FIGHTER_RANGE
                missile=max((k for k,v in stock.items() if v>0),key=lambda k:stock[k],default=None) if distance<=FIGHTER_RANGE else None
            else:missile=missile_for(distance,stock)
            if missile and (best is None or distance<best[1]):best=(base,distance,missile)
        if best is None:continue
        base,distance,missile=best
        count=salvo(ctx,stock[missile],defended)
        order={'land':'missile','air':'air','naval':'naval'}[base.kind]
        value=TARGET_VALUE[kind]+(4.0 if kind=='base' and distance<800 else 0)
        options.append(Option(key=f'war:strike:{kind}:{id}',domain='war',action='STRIKE_'+kind.upper(),label=f'Uderzenie ({order}, {count}× {missile}) na {kind} #{id} państwa {owner}',
                              target=owner,stance='hostile',effects={'offensive_army':1.0,'conquest':.6,'defensive_army':.4 if kind in ('base','radar','defense') else .1},
                              traits={'militarism':.7,'provocation':.3,'loss_tolerance':.3,'agreeableness':-.4 if kind=='city' else -.1,'prosociality':-.6 if kind=='city' else 0},
                              categories={'imperialist':.6,'terrorist':.8 if kind=='city' else .2},base=value-6.0,risk=.2 if defended else .05,
                              notes=[f'Źródło: baza #{base.id} ({base.kind}), odległość {distance:.0f} km; cel {"chroniony obroną" if defended else "bez znanej obrony"}.'],
                              payload={'kind':order,'region_id':int(region),'source_base_id':base.id,'missile_type':missile,'missiles':count,TARGET_FIELD[kind]:id,'group':f'war:strike:{owner}'}))
    return sorted(options,key=lambda o:-o.base)[:6]


DEFEAT_MARGIN=.3        # o tyle rośnie wymagana przewaga po każdej porażce o ten sam cel
MAX_MARGIN=3.0
BATTLE_MEMORY_DAYS=90


def battle_intel(ctx):
    """Wiedza z własnych bitew (raporty bitew są jawne dla atakującego): porażki od ostatniego zwycięstwa o każdy cel,
    ostatnia zmierzona siła obrony, wyszkolenie obrońców każdego państwa oraz cele, na które nasze armie już maszerują."""
    if getattr(ctx,'_battles',None) is not None:return ctx._battles
    from datetime import timedelta
    from game.land_war_models import LandArmy
    since=ctx.now-timedelta(days=BATTLE_MEMORY_DAYS) if ctx.now else None
    targets={};training={};marching=set()
    with Session(db.engine) as session:
        query=select(LandArmy).where(LandArmy.panstwo_id==ctx.country_id).order_by(LandArmy.id)
        for army in session.scalars(query):
            key=('city',army.target_city_id) if army.target_kind=='city' else ('base',army.target_base_id)
            if army.status=='MARCHING':marching.add(key);continue
            record=army.battle or {}
            if record.get('result') not in ('ATTACKER_WON','DEFENDER_WON') or (since and army.resolved_at and army.resolved_at<since):continue
            defender=record.get('defender') or {}
            if defender.get('country') in (None,ctx.country_id):continue  # bitwy bez wroga nie mówią nic o przeciwniku
            if defender.get('training') is not None and defender.get('country') is not None:training[defender['country']]=defender['training']
            info=targets.setdefault(key,{'defeats':0,'last':None})
            info['last']=defender
            info['defeats']=info['defeats']+1 if record['result']=='DEFENDER_WON' else 0
    ctx._battles={'targets':targets,'training':training,'marching':marching}
    return ctx._battles


def battle_estimate(ctx,kind,target_level,target_id=None,screen=None,owner=None):
    """Szacowana siła obrońców (bez losowego czynnika bitwy, który obie strony mają taki sam):
    widoczne armie okupujące × wyszkolenie obrońców znane z naszych bitew (bez tej wiedzy zapas ×1,2);
    bez widocznych jednostek — siła zmierzona w ostatniej bitwie o cel; w ostateczności poziom bazy albo mały oddział."""
    from game.military_service import CAPACITIES
    from game.land_war import WEIGHTS
    intel=battle_intel(ctx)
    level=intel['training'].get(owner)
    factor=level/100 if level else 1.2
    key='targetCityId' if kind=='city' else 'targetBaseId'
    visible=[a for a in (screen or {}).get('armies',[]) if a.get('status')=='OCCUPYING' and a.get(key)==target_id]
    if visible:return sum(int((a.get('units') or {}).get(u,0))*WEIGHTS[u] for a in visible for u in WEIGHTS)*factor
    last=(intel['targets'].get((kind,target_id)) or {}).get('last')
    if last and last.get('strength'):return float(last['strength'])
    if kind=='base':
        capacity=CAPACITIES['land'][max(1,min(7,target_level or 1))-1]
        return sum(capacity.get(u,0)*WEIGHTS[u] for u in WEIGHTS)*.7*factor
    return 2500.0*factor


def war_plans(ctx):
    """Aktywne plany przygotowania ataku (odbicie / zdobycie celu po porażkach): {(rodzaj, id): plan}."""
    from game.paga2.models import Paga2Plan,table_ready
    plans={}
    with Session(db.engine) as session:
        if not table_ready(session,Paga2Plan):return plans
        for row in session.scalars(select(Paga2Plan).where(Paga2Plan.country_id==ctx.country_id,Paga2Plan.status=='ACTIVE')):
            kind,_,rest=row.goal.partition(':')
            if kind in ('recapture','conquer'):
                target,_,id=rest.partition(':');plans[(target,int(id))]=(row.id,row.goal)
    return plans


def update_plan(plan_id,steps,*,status=None,reason=None):
    from game.paga2.models import Paga2Plan,utc_now
    with Session(db.engine) as session,session.begin():
        row=session.get(Paga2Plan,plan_id,with_for_update=True)
        if row is None or row.status!='ACTIVE':return
        row.steps=steps;row.updated_at=utc_now()
        if reason:row.reason=reason
        if status:row.status=status;row.finished_at=utc_now()


def readiness_options(ctx,forces,base,kind,id,owner,recapture,required,ours,plan):
    """Przygotowanie armii do ponownego ataku: szkolenie wojsk lądowych, uzupełnienie i rozbudowa bazy wyjściowej."""
    from game.land_war import WEIGHTS
    from game.military_service import CAPACITIES,UPGRADE_COSTS,UPKEEP_RATES
    from game.military_training import BRANCHES,MAX_LEVEL
    options=[];effects={'defensive_army':1.0,'offensive_army':.4} if recapture else {'conquest':1.0,'offensive_army':.8}
    label=('odbicia' if recapture else 'zdobycia')+(' miasta' if kind=='city' else ' bazy')+f' #{id}'
    garrison={u:int((base.garrison or {}).get(u,0)) for u in WEIGHTS}
    weighted=sum(garrison[u]*WEIGHTS[u] for u in WEIGHTS)
    level=forces.army.get('wyszkolenie_ladowe') or 100
    capacity=CAPACITIES['land'][base.level-1]
    wanted={r:int(min(limit,(base.garrison or {}).get(r,0)+(forces.free_soldiers.get('land',0) if r=='soldiers' else forces.free.get(r,0)))) for r,limit in capacity.items()}
    added={r:wanted[r]-(base.garrison or {}).get(r,0) for r in wanted if wanted[r]>(base.garrison or {}).get(r,0)}
    common=dict(target=owner,stance='hostile',effects=effects,traits={'strategic_patience':.6,'revenge':.4 if recapture else 0,'militarism':.4})
    if added:
        options.append(Option(key=f'war:prepare:reinforce:{base.id}',domain='war',action='PREPARE_REINFORCE',label=f'Przygotowanie {label}: uzupełnienie garnizonu bazy #{base.id}',
                              cost=float(sum(n*UPKEEP_RATES[r] for r,n in added.items())),sector='armed_forces',base=8.0,
                              notes=[f'Siła {ours:,.0f} / wymagana {required:,.0f}. Dodane: {added}.'.replace(',',' ')],
                              payload={'action':'garrison','base_id':base.id,'garrison':wanted,'group':f'base:{base.id}','plan_id':plan},**common))
    elif base.level<7:
        options.append(Option(key=f'war:prepare:upgrade:{base.id}',domain='war',action='PREPARE_UPGRADE',label=f'Przygotowanie {label}: rozbudowa bazy #{base.id} do poziomu {base.level+1}',
                              cost=float(UPGRADE_COSTS[base.level+1]),sector='armed_forces',base=6.0,notes=['Garnizon bazy jest pełny — większa baza pomieści więcej wojsk.'],
                              payload={'action':'upgrade','base_id':base.id,'group':f'base:{base.id}','plan_id':plan},**common))
    if weighted and level<MAX_LEVEL:
        needed=int(-(-required*100//weighted))-level
        price=float(BRANCHES['land'][2])
        count=int(min(max(0,needed),MAX_LEVEL-level,.4*ctx.limits['per_action']*forces.budget_available//price))
        if count>=1:
            options.append(Option(key='war:prepare:training',domain='army',action='PREPARE_TRAINING',label=f'Przygotowanie {label}: szkolenie sił lądowych +{count} (poziom {level})',
                                  cost=count*price,sector='armed_forces',base=8.0,notes=[f'Do wymaganej siły brakuje {max(0,needed)} poziomów wyszkolenia przy obecnym garnizonie.'],
                                  payload={'branch':'land','levels':count,'plan_id':plan,'group':'train'},**common))
    return options


def readiness_steps(base,ours,required,margin,defeats,label):
    ready=ours>=required
    return [{'key':'readiness','kind':'readiness','label':f'Siła wojsk bazy #{base.id}: {ours:,.0f} / wymagana {required:,.0f} (przewaga ×{margin:.2f} po {defeats} porażkach)'.replace(',',' '),
             'status':'done' if ready else 'blocked','reason':None if ready else 'Szkolenie, uzupełnienie garnizonu, rozbudowa bazy.','params':{'base_id':base.id},'cost':0,'sector':None},
            {'key':'attack','kind':'attack','label':label,'status':'ready' if ready else 'blocked','reason':None if ready else 'Po osiągnięciu wymaganej siły.','params':{},'cost':0,'sector':None}]


def land_options(ctx,forces,screen,config,enemies,recapture_targets):
    from game.land_war import WEIGHTS,UNIT_COST
    t=ctx.traits;options=[]
    training=forces.army.get('wyszkolenie_ladowe') or 100
    bases=[b for b in forces.bases if b.kind=='land' and b.health>0 and b.operational and b.map_x is not None and any((b.garrison or {}).get(u,0) for u in WEIGHTS)]
    if not bases:return []
    intel=battle_intel(ctx);plans=war_plans(ctx)
    neighbors=set(ctx.world_summary().get('neighbor_countries',[]))
    targets=[]
    for item in screen.get('bases',[]):
        if item.get('countryId') in enemies&neighbors and item.get('position') and (item.get('health') or 100)>0:
            targets.append(('base',item['id'],item['position'],item['countryId'],item.get('level'),False))
    for id,city in (config.get('cities') or {}).items():
        if city.get('countryId') in enemies&neighbors and city.get('point'):targets.append(('city',int(id),city['point'],city['countryId'],None,False))
    targets+=recapture_targets
    live={(kind,id) for kind,id,*_ in targets}
    # Plany, których cel przestał istnieć (odzyskany, poza wojną), są zamykane.
    for key,(plan_id,goal) in plans.items():
        if key not in live:update_plan(plan_id,[],status='DONE' if goal.startswith('recapture') else 'ABANDONED',reason='Cel nie jest już aktualny (odzyskany lub poza wojną).')
    for kind,id,point,owner,level,recapture in targets:
        if (kind,id) in intel['marching']:continue          # nasza armia już maszeruje na ten cel — czekamy na wynik bitwy
        defeats=(intel['targets'].get((kind,id)) or {}).get('defeats',0)
        base=min(bases,key=lambda b:km(ctx,[b.map_x,b.map_y],point) or 1e9)
        defense=battle_estimate(ctx,kind,level,id,screen,owner)
        garrison={u:int((base.garrison or {}).get(u,0)) for u in WEIGHTS}
        ours=sum(garrison[u]*WEIGHTS[u] for u in WEIGHTS)*training/100
        margin=min(MAX_MARGIN,1.2+.6*(100-t.get('loss_tolerance',50))/100+DEFEAT_MARGIN*defeats)
        required=defense*margin
        label=f'{"Odbicie" if recapture else "Najazd na"} {kind} #{id}'+('' if recapture else f' państwa {owner}')+f' z bazy #{base.id}'
        plan=plans.get((kind,id),(None,None))[0]
        if ours<required:
            # Za słabo: zamiast ponawiać atak — przygotowanie armii i powrót do celu, gdy będzie gotowa.
            if not (recapture or defeats):continue
            if plan is None:
                options.append(Option(key=f'war:plan:{kind}:{id}',domain='war',action='WAR_PREPARE',label=f'Odłożenie: {label} — przygotowanie armii (siła {ours:,.0f} / wymagana {required:,.0f})'.replace(',',' '),
                                      target=owner,stance='hostile',effects={'defensive_army':1.0} if recapture else {'conquest':.8,'offensive_army':.6},
                                      traits={'strategic_patience':.8,'revenge':.4,'loss_tolerance':-.3},base=8.0 if recapture else 2.0,
                                      notes=[f'Porażki od ostatniego zwycięstwa: {defeats}. Wymagana przewaga ×{margin:.2f}.'],
                                      payload={'goal':f'{"recapture" if recapture else "conquer"}:{kind}:{id}','priority':'defensive_army' if recapture else 'conquest',
                                               'steps':readiness_steps(base,ours,required,margin,defeats,label),'group':'war:plan'}))
            else:
                update_plan(plan,readiness_steps(base,ours,required,margin,defeats,label),reason='Przygotowanie armii do ataku.')
                options+=readiness_options(ctx,forces,base,kind,id,owner,recapture,required,ours,plan)
            continue
        if plan is not None:update_plan(plan,readiness_steps(base,ours,required,margin,defeats,label),reason='Armia gotowa — atak.')
        scale=min(1.0,required*1.15/ours) if ours else 1.0
        units={u:int(garrison[u]*scale) for u in WEIGHTS}
        cost=float(sum(UNIT_COST[u]*units[u] for u in WEIGHTS))
        distance=km(ctx,[base.map_x,base.map_y],point) or 0
        options.append(Option(key=f'war:land:{kind}:{id}',domain='war',action='RECAPTURE' if recapture else 'LAND_ATTACK',label=f'{label} ({distance:.0f} km)',
                              target=owner,stance='hostile',cost=cost,sector='armed_forces',
                              effects={'defensive_army':1.0,'conquest':.3} if recapture else {'conquest':1.0,'offensive_army':.8},
                              traits={'revenge':.6,'militarism':.4} if recapture else {'expansionism':.9,'militarism':.6,'loss_tolerance':.4,'agreeableness':-.4},
                              categories={'imperialist':1.0,'hegemonic':.3} if not recapture else {},
                              base=(14.0 if recapture else 0.0)+min(8.0,4*(ours/max(1,required)-1))+(6.0 if plan else 0),risk=.15 if not recapture else .1,
                              notes=[f'Siła własna {ours:,.0f} wobec szacowanej obrony {defense:,.0f} (wymagany margines ×{margin:.2f}, porażki: {defeats}).'.replace(',',' ')],
                              payload={'target_kind':kind,'target_id':id,'source_base_id':base.id,**units,'group':'war:land','plan_id':plan}))
    return options


def occupation_options(ctx):
    from game.land_war_models import Occupation
    from game.land_war import ANNEX_DAYS
    from datetime import timedelta
    t=ctx.traits;options=[]
    with Session(db.engine) as session:
        rows=list(session.scalars(select(Occupation).where(Occupation.status.in_(['PENDING','ACTIVE','DECLINED']))));[session.expunge(r) for r in rows]
    recapture=[]
    for row in rows:
        if row.occupier_id==ctx.country_id and row.kind=='region':
            if row.status=='PENDING':
                for occupy in (True,False):
                    options.append(Option(key=f'war:occupy:{row.id}:{occupy}',domain='war',action='OCCUPY' if occupy else 'OCCUPY_DECLINE',
                                          label=f'{"Okupacja" if occupy else "Rezygnacja z okupacji"} regionu {row.region_id} państwa {row.owner_id}',target=row.owner_id,stance='hostile' if occupy else 'friendly',
                                          effects={'conquest':1.0,'offensive_army':.4} if occupy else {'welfare':.3,'financial_stability':.3},
                                          traits={'expansionism':.9,'ambition':.5,'agreeableness':-.4} if occupy else {'agreeableness':.6,'expansionism':-.6},
                                          categories={'imperialist':1.0,'hegemonic':.4} if occupy else {'isolationist':.5},base=2.0 if occupy else 0.0,
                                          payload={'occupation_id':row.id,'occupy':occupy,'group':f'occupation:{row.id}','required':True}))
            elif row.status=='ACTIVE' and row.started_at and ctx.now>=row.started_at+timedelta(days=ANNEX_DAYS):
                options.append(Option(key=f'war:annex:{row.id}',domain='war',action='ANNEX',label=f'Aneksja regionu {row.region_id} państwa {row.owner_id}',target=row.owner_id,stance='hostile',
                                      effects={'conquest':1.0},traits={'expansionism':1.0,'ambition':.6,'agreeableness':-.5},categories={'imperialist':1.0,'hegemonic':.4},base=6.0,
                                      payload={'action':'annex','occupation_id':row.id,'group':f'occupation:{row.id}'}))
        elif row.owner_id==ctx.country_id and row.kind in ('city','base') and row.status in ('ACTIVE','PENDING'):
            point=None
            from game.military_geography import city_point
            if row.kind=='city':point=city_point(row.city_id)
            else:
                from game.military_models import MilitaryBase
                with Session(db.engine) as session:
                    base=session.get(MilitaryBase,row.base_id);point=[base.map_x,base.map_y] if base and base.map_x is not None else None
            if point:recapture.append((row.kind,row.city_id if row.kind=='city' else row.base_id,point,row.occupier_id,None,True))
    return options,recapture


def preparation_bases(ctx):
    """Bazy wyjściowe aktywnych planów przygotowania ataku: {base_id: plan_id}."""
    from game.paga2.models import Paga2Plan
    result={}
    plans=war_plans(ctx)
    if not plans:return result
    with Session(db.engine) as session:
        for plan_id,goal in plans.values():
            row=session.get(Paga2Plan,plan_id)
            base=next((step.get('params',{}).get('base_id') for step in (row.steps or []) if step.get('kind')=='readiness'),None) if row else None
            if base:result[base]=plan_id
    return result


def withdraw_options(ctx,forces,screen):
    """Wycofanie własnych wojsk okupacyjnych do własnej bazy (tylko tyle, ile baza pomieści):
    po zakończeniu wojny z właścicielem, po rezygnacji z okupacji regionu (państwa nieimperialistyczne)
    albo na potrzeby planu odbicia własnego terytorium (wojska wracają do bazy, z której ruszy odbicie)."""
    from game.land_war_models import Occupation
    from game.land_war import free_capacity,UNITS
    t=ctx.traits;options=[];enemies=set(ctx.situation.get('at_war',[]))
    with Session(db.engine) as session:
        rows=list(session.scalars(select(Occupation).where(Occupation.occupier_id==ctx.country_id,Occupation.status.in_(['ACTIVE','DECLINED']))));[session.expunge(r) for r in rows]
    declined={r.region_id for r in rows if r.kind=='region' and r.status=='DECLINED'}
    prepare_bases=preparation_bases(ctx)
    bases=[b for b in forces.bases if b.kind in ('land','air','naval') and b.health>0 and b.operational and b.map_x is not None]
    for row in rows:
        if row.kind not in ('city','base') or row.status!='ACTIVE':continue
        key='targetCityId' if row.kind=='city' else 'targetBaseId';object_id=row.city_id if row.kind=='city' else row.base_id
        present={u:sum(int((a.get('units') or {}).get(u,0)) for a in screen.get('armies',[]) if a.get('status')=='OCCUPYING' and a.get('countryId')==ctx.country_id and a.get(key)==object_id) for u in UNITS}
        if not any(present.values()):continue
        reason=None;base_value=0.0;effects={}
        if row.owner_id not in enemies:reason='Wojna z właścicielem zakończona — wojska wracają do kraju.';base_value=10.0;effects={'welfare':.4,'financial_stability':.4,'defensive_army':.3}
        elif row.region_id in declined and 'imperialist' not in ctx.categories and t.get('expansionism',50)<60:
            reason='Zrezygnowaliśmy z okupacji regionu — utrzymywanie obiektu nie służy celom państwa.';base_value=4.0;effects={'defensive_army':.5,'financial_stability':.3}
        elif prepare_bases:reason='Wojska potrzebne do odbicia własnego terytorium.';base_value=6.0;effects={'defensive_army':1.0}
        if reason is None:continue
        candidates=[b for b in bases if b.id in prepare_bases] if prepare_bases and row.owner_id in enemies else []
        candidates=candidates or bases
        destination=max(candidates,key=lambda b:sum(min(present[u],free_capacity(b)[u]) for u in UNITS),default=None)
        if destination is None:continue
        free=free_capacity(destination);units={u:min(present[u],free[u]) for u in UNITS}
        if not any(units.values()):continue
        options.append(Option(key=f'war:withdraw:{row.id}',domain='war',action='OCCUPATION_WITHDRAW',label=f'Wycofanie wojsk okupacyjnych z {row.kind} #{object_id} do bazy #{destination.id}',
                              target=row.owner_id,stance='friendly' if row.owner_id not in enemies else 'neutral',effects=effects,
                              traits={'agreeableness':.4,'expansionism':-.6,'strategic_flexibility':.4},base=base_value,
                              notes=[reason,f'Przenoszone: {units} (wolne miejsca bazy: {free}).'],
                              payload={'action':'withdraw','occupation_id':row.id,'base_id':destination.id,**units,'group':f'occupation:{row.id}'}))
    return options


def reach_means(forces,screen):
    """Środki ataku na odległość: rakiety średniego i dalekiego zasięgu oraz obsadzone myśliwce, okręty wojenne i podwodne."""
    missiles={code:int((value or {}).get('count') or 0) for code,value in ((screen or {}).get('missiles') or {}).items()}
    means={'medium':missiles.get('medium',0),'long':missiles.get('long',0)}
    for resource in ('fighters','warships','submarines'):
        means[resource]=sum(int((b.garrison or {}).get(resource,0)) for b in forces.bases if b.health>0 and b.garrison)
    return {k:v for k,v in means.items() if v>0}


REACH_LABELS={'medium':'rakiety średniego zasięgu','long':'rakiety dalekiego zasięgu','fighters':'myśliwce','warships':'okręty wojenne','submarines':'okręty podwodne'}


def own_vessels(ctx):
    """Własne okręty na morzu: (id, rodzaj, status, baza, bieżąca pozycja, punkt docelowy)."""
    if getattr(ctx,'_vessels',None) is None:
        from game.military_models import MilitaryVessel
        from game.military_navy import vessel_position
        rows=[]
        with Session(db.engine) as session:
            for v in session.scalars(select(MilitaryVessel).where(MilitaryVessel.panstwo_id==ctx.country_id,MilitaryVessel.status.in_(['sailing','stationed','returning']),MilitaryVessel.health>0)):
                try:position=vessel_position(v,ctx.now)
                except Exception:position=[v.target_x,v.target_y]
                rows.append(NSV(v.id,v.kind,v.status,v.base_id,position,[v.target_x,v.target_y]))
        ctx._vessels=rows
    return ctx._vessels


class NSV:
    def __init__(self,id,kind,status,base_id,position,target):self.id,self.kind,self.status,self.base_id,self.position,self.target=id,kind,status,base_id,position,target


NAVAL_REACH_KM=1500    # okręt dalej od celów wroga dostaje nowy kierunek


def busy(base_id,kind):
    from game.military_navy import busy_vessels
    with Session(db.engine) as session:return busy_vessels(session,base_id,kind)


def naval_options(ctx,forces,targets,enemies):
    """Okręty: rejs ku wrogowi, nowy kierunek dla okrętu daleko od wroga, powrót do bazy po wojnie."""
    vessels=own_vessels(ctx);options=[]
    points=[(point,owner) for kind,id,region,point,owner,defended in targets if kind in ('city','base')]
    def nearest(position):
        best=None
        for point,owner in points:
            d=km(ctx,position,point)
            if d is not None and (best is None or d<best[0]):best=(d,point,owner)
        return best
    if not enemies:
        home=next((b for b in forces.bases if b.kind=='naval' and b.health>0 and b.map_x is not None),None)
        for v in vessels:
            if v.status=='returning':continue
            target=next((b for b in forces.bases if b.id==v.base_id and b.health>0 and b.map_x is not None),home)
            if target is None:continue
            options.append(Option(key=f'war:vessel:return:{v.id}',domain='war',action='VESSEL_RETURN',label=f'Powrót okrętu #{v.id} do bazy #{target.id} (pokój)',
                                  effects={'financial_stability':.3,'defensive_army':.3},base=3.0,payload={'action':'return_vessel','vessel_id':v.id,'base_id':target.id,'group':f'vessel:{v.id}'}))
        return options
    if not points:return options
    for v in vessels:
        here=nearest(v.position);goal=nearest(v.target)
        if here is None or goal is None or goal[0]<=NAVAL_REACH_KM:continue
        options.append(Option(key=f'war:vessel:redirect:{v.id}',domain='war',action='VESSEL_REDIRECT',label=f'Nowy kierunek okrętu #{v.id}: wody państwa {here[2]}',target=here[2],stance='hostile',
                              effects={'offensive_army':.8,'conquest':.3},traits={'militarism':.5},base=2.0,notes=[f'Obecny cel rejsu {goal[0]:.0f} km od celów wroga.'],
                              payload={'action':'redirect_vessel','vessel_id':v.id,'x':here[1][0],'y':here[1][1],'group':f'vessel:{v.id}'}))
    if True:
        for b in forces.bases:
            if b.kind!='naval' or b.health<=0 or b.map_x is None:continue
            for kind in ('warships','submarines'):
                if (b.garrison or {}).get(kind,0)<=busy(b.id,kind):continue
                goal=nearest([b.map_x,b.map_y])
                if goal is None:continue
                options.append(Option(key=f'war:vessel:sail:{b.id}:{kind}',domain='war',action='VESSEL_SAIL',label=f'Rejs ({"okręt podwodny" if kind=="submarines" else "okręt wojenny"}) z bazy #{b.id} ku państwu {goal[2]}',
                                      target=goal[2],stance='hostile',effects={'offensive_army':.9,'conquest':.4},traits={'militarism':.6,'loss_tolerance':.2},base=1.0,
                                      notes=[f'Odległość do celu: {goal[0]:.0f} km.'],payload={'action':'sail','base_id':b.id,'vessel_kind':kind,'x':goal[1][0],'y':goal[1][1],'group':f'sail:{b.id}'}))
    return options


def declare_options(ctx,forces,screen=None):
    """Wypowiedzenie wojny — tylko w trybie doraźnym, wobec państw o złych lub wrogich relacjach (warunek gry)."""
    if ctx.mode!='IMMEDIATE':return []
    t=ctx.traits;options=[]
    staffed=[b for b in forces.bases if b.health>0 and b.garrison]
    capable=staffed and forces.has_budget and forces.budget_available>0
    triggers={item.get('from') for item in ctx.triggers if item.get('from')}
    neighbors=set(ctx.world_summary().get('neighbor_countries',[]))
    reach=None
    for other,row in ctx.situation.get('relations',{}).items():
        if row.get('relation') not in WAR_RELATIONS or row.get('state')=='wojnakinetyczna':continue
        provoked=ctx.history(other)['hostile_from']
        distant=other not in neighbors;able=bool(capable)
        if distant:
            if reach is None:reach=reach_means(forces,screen if screen is not None else war_screen(ctx))
            able=able and bool(reach)
        if not capable:note='Brak zdolności do prowadzenia wojny (obsadzone bazy, budżet wojska).'
        elif distant and not reach:note='Państwo nie jest sąsiadem, a brak środków ataku na odległość (rakiety średniego/dalekiego zasięgu, okręty, myśliwce).'
        elif distant:note='Cel odległy; środki ataku na odległość: '+', '.join(f'{REACH_LABELS[k]} {v}' for k,v in reach.items())+'.'
        else:note='Zdolność wojskowa potwierdzona.'
        options.append(Option(key=f'war:declare:{other}',domain='war',action='WAR',label=f'Wypowiedzenie wojny państwu {other}',target=other,stance='hostile',
                              effects={'conquest':1.0,'offensive_army':.7,'welfare':-.6,'financial_stability':-.5,'trade':-.4},
                              traits={'militarism':.8,'expansionism':.8,'provocation':.6,'ambition':.4,'agreeableness':-.8,'strategic_patience':-.3,'predictability':-.2},
                              categories={'imperialist':1.0,'terrorist':.4,'hegemonic':.3,'isolationist':-.5,'welfare':-.6},
                              base=-16.0+(5.0 if other in neighbors else 0)+4*min(3,provoked)+(6.0 if other in triggers else 0),risk=.4+(.2 if distant else 0),
                              notes=[note],payload={'kind':'WAR','target_id':other,'group':'war:declare','capable':able,**({'distant':True} if distant else {})}))
    return options


def propose(ctx):
    from game.paga2.defense import _forces
    forces=_forces(ctx)
    options,recapture=occupation_options(ctx)
    enemies=set(ctx.situation.get('at_war',[]))
    screen=war_screen(ctx)
    options+=declare_options(ctx,forces,screen)
    options+=withdraw_options(ctx,forces,screen)
    if not enemies and not recapture:
        try:options+=naval_options(ctx,forces,[],enemies)
        except Exception:pass
        return options
    config=war_config(ctx)
    if enemies:
        try:options+=naval_options(ctx,forces,enemy_targets(ctx,screen,config,enemies),enemies)
        except Exception:pass
    if enemies:options+=strike_options(ctx,forces,screen,config,enemies)
    options+=land_options(ctx,forces,screen,config,enemies,recapture)
    return options


def check(ctx,option):
    if option.action=='WAR' and not option.payload.get('capable'):
        if option.payload.get('distant'):return 'Brak zdolności do wojny z odległym państwem: potrzebne obsadzone bazy, budżet wojska oraz środki ataku na odległość (rakiety średniego/dalekiego zasięgu, okręty wojenne lub podwodne, myśliwce).'
        return 'Brak zdolności do prowadzenia wojny: brak obsadzonych baz lub środków w budżecie wojska.'
    return None


def execute(ctx,option):
    p={k:v for k,v in option.payload.items() if k not in ('group','required','capable','plan_id','distant')}
    if option.action=='WAR_PREPARE':
        from game.paga2.models import Paga2Plan
        with Session(db.engine) as session,session.begin():
            row=Paga2Plan(country_id=ctx.country_id,goal=option.payload['goal'],priority=option.payload['priority'],status='ACTIVE',steps=option.payload['steps'],
                          reason='Atak odłożony — przygotowanie armii.',game_created_at=ctx.now)
            session.add(row);session.flush();return {'status':200,'plan_id':row.id}
    if option.action in ('VESSEL_SAIL','VESSEL_REDIRECT','VESSEL_RETURN'):
        from game.paga2.defense import DEFENSE
        status,data=ctx.call(DEFENSE,json=p)
        if status<400:ctx._forces=None;ctx._vessels=None
        return result(status,data)
    if option.action in ('PREPARE_REINFORCE','PREPARE_UPGRADE'):
        from game.paga2.defense import DEFENSE
        status,data=ctx.call(DEFENSE,json=p)
        if status<400:ctx._forces=None
        return result(status,data)
    if option.action=='PREPARE_TRAINING':
        from game.paga2.defense import TRAIN
        status,data=ctx.call(TRAIN,json={'branch':p['branch'],'levels':p['levels'],'request_id':rid(ctx,option)})
        if status<400:ctx._forces=None
        return result(status,data)
    if option.action=='WAR':
        status,data=ctx.call(DECLARE,form={'kind':'WAR','target_id':str(p['target_id'])})
    elif option.action.startswith('STRIKE_'):
        status,data=ctx.call(ORDER,json=p)
    elif option.action in ('LAND_ATTACK','RECAPTURE'):
        status,data=ctx.call(INVASION,json={**p,'request_id':rid(ctx,option)})
        if status<400 and option.payload.get('plan_id'):update_plan(option.payload['plan_id'],[],status='DONE',reason='Armia gotowa — atak wysłany.')
        if status<400:ctx._battles=None
    elif option.action in ('OCCUPY','OCCUPY_DECLINE'):
        status,data=ctx.call(OCCUPATION,json={'occupation_id':p['occupation_id'],'occupy':p['occupy']})
    elif option.action=='OCCUPATION_WITHDRAW':
        status,data=ctx.call(OCCUPATION,json=p)
    elif option.action=='ANNEX':
        status,data=ctx.call(OCCUPATION,json={'action':'annex','occupation_id':p['occupation_id']})
    else:return {'status':400,'error':'Nieznana operacja wojenna.'}
    if status<400:ctx._forces=None;ctx._screens.clear()
    return result(status,data)


ADAPTER=register(Adapter(name='war',modes=('CYCLIC','IMMEDIATE'),propose=propose,execute=execute,check=check))
