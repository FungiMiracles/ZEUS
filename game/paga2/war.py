"""PAGA2 — panel wojenny: wypowiedzenie wojny (wyłącznie tryb doraźny), uderzenia rakietowe i lotnicze na regiony,
miasta i obiekty, najazdy lądowe na miasta i bazy, decyzje o okupacji, aneksja oraz odbijanie własnych miast i baz.

Cele wroga pochodzą wyłącznie z ekranu wojennego gracza (obiekty znane z wywiadu, jawne miasta i regiony).
Wykonalność sprawdzana przed decyzją: sprawna baza z odpowiednim sprzętem, zasięg rakiet, zapas rakiet, budżet wojska,
szacowana przewaga w bitwie. Uderzenie jądrowe (13 Nov 2026) — wyłącznie w stanie wojny i w ostateczności (przegrywana
wojna: wróg okupuje nasze regiony albo użył broni atomowej przeciw nam), rakietą z głowicą nuklearną z silosu (zasięg 3000 km).
"""
import math
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
TARGET_FIELD={'airport':'target_airport_id','base':'target_base_id','defense':'target_defense_id','power':'target_power_id','factory':'target_factory_id','mine':'target_mine_id','radar':'target_radar_id','city':'city_id','shipment':'target_shipment_id'}
TARGET_VALUE={'airport':6.0,'base':10.0,'defense':8.0,'power':7.0,'factory':6.0,'radar':5.0,'mine':4.0,'city':2.0,'shipment':6.5}


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


OVERLAND_CANDIDATES=5   # ile najbliższych baz sprawdzać pod kątem trasy lądowej do celu


def overland_ok(ctx,source,target,holder=None):
    """26 Nov 2026: czy armia dojdzie lądem z punktu source do target — ta sama reguła co gra (game.land_routes: droga
    okrężna po lądzie, omija akweny, tylko przez terytoria stron wojny z państwem `holder`, które trzyma cel).
    Wynik zapamiętywany w przebiegu; błąd geometrii = brak wiedzy (decyzję zostawiamy grze)."""
    cache=getattr(ctx,'_overland',None)
    if cache is None:cache=ctx._overland={}
    key=(round(source[0],4),round(source[1],4),round(target[0],4),round(target[1],4),holder)
    if key not in cache:
        try:
            from game.land_routes import participants,route
            with Session(db.engine) as session:
                sides=participants(session,ctx.country_id,holder) if holder is not None else {ctx.country_id}
                cache[key]=route(session,source,target,sides) is not None
        except Exception:
            cache[key]=True
    return cache[key]


def land_base_for(ctx,bases,point,holder=None):
    """Najbliższa baza lądowa, z której cel jest osiągalny drogą lądową (spośród OVERLAND_CANDIDATES najbliższych), albo None."""
    for base in sorted(bases,key=lambda b:km(ctx,[b.map_x,b.map_y],point) or 1e9)[:OVERLAND_CANDIDATES]:
        if overland_ok(ctx,[base.map_x,base.map_y],point,holder):return base
    return None


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
    for kind,key in (('base','bases'),('defense','defenses'),('power','power'),('factory','factories'),('mine','mines'),('radar','radars'),('airport','airports')):
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
                # 12 Nov 2026: myśliwiec — zasięg 1000 km; 23 Nov 2026: wyłącznie rakiety krótkiego zasięgu.
                from game.military_flights import FIGHTER_RANGE,FIGHTER_MISSILE_TYPE
                missile=FIGHTER_MISSILE_TYPE if distance<=FIGHTER_RANGE and stock.get(FIGHTER_MISSILE_TYPE,0)>0 else None
            else:missile=missile_for(distance,stock)
            if missile and (best is None or distance<best[1]):best=(base,distance,missile)
        if best is None:continue
        base,distance,missile=best
        # 23 Nov 2026: limit salwy — myśliwiec 10 rakiet, baza lądowa 10 × wyrzutnie, okręty w porcie 20 × okręty
        from game.military_flights import salvo_limit
        garrison=base.garrison or {}
        limit=salvo_limit({'land':'missile','air':'air','naval':'naval'}[base.kind],launchers=garrison.get('launchers',0),warships=garrison.get('warships',0))
        count=max(1,min(salvo(ctx,stock[missile],defended),limit))
        order={'land':'missile','air':'air','naval':'naval'}[base.kind]
        value=TARGET_VALUE[kind]+(4.0 if kind=='base' and distance<800 else 0)
        options.append(Option(key=f'war:strike:{kind}:{id}',domain='war',action='STRIKE_'+kind.upper(),label=f'Uderzenie ({order}, {count}× {missile}) na {kind} #{id} państwa {owner}',
                              target=owner,stance='hostile',effects={'offensive_army':1.0,'conquest':.6,'defensive_army':.4 if kind in ('base','radar','defense') else .1},
                              traits={'militarism':.7,'provocation':.3,'loss_tolerance':.3,'agreeableness':-.4 if kind=='city' else -.1,'prosociality':-.6 if kind=='city' else 0},
                              categories={'imperialist':.6,'terrorist':.8 if kind=='city' else .2},base=value-6.0,risk=.2 if defended else .05,
                              notes=[f'Źródło: baza #{base.id} ({base.kind}), odległość {distance:.0f} km; cel {"chroniony obroną" if defended else "bez znanej obrony"}.'],
                              payload={'kind':order,'region_id':int(region),'source_base_id':base.id,'missile_type':missile,'missiles':count,TARGET_FIELD[kind]:id,'group':f'war:strike:{owner}'}))
    return sorted(options,key=lambda o:-o.base)[:6]


def losing_war(ctx,enemies):
    """Ostateczność: wróg okupuje nasze regiony albo w ostatnich zdarzeniach uderzył w nas bronią atomową."""
    occupied=ctx.situation.get('occupied_regions') or {}
    for value in (occupied.values() if isinstance(occupied,dict) else occupied):
        occupier=value.get('occupier') if isinstance(value,dict) else value
        if occupier in enemies or occupier is None:return True
    for trigger in getattr(ctx,'triggers',None) or []:
        if isinstance(trigger,dict) and trigger.get('kind')=='nuclear_strike':return True
    return False


def nuclear_strike_options(ctx,forces,screen,config,enemies):
    """13 Nov 2026: jedna rakieta z głowicą nuklearną z silosu na najcenniejszy znany cel wroga w zasięgu 3000 km."""
    from game.nuclear import RANGE_KM
    if ctx.situation.get('level')!='war' or not losing_war(ctx,enemies):return []
    silos=[b for b in forces.bases if b.kind=='nuclear' and b.health>0 and b.operational and b.map_x is not None and (b.garrison or {}).get('warheads',0)>0]
    if not silos:return []
    best=None
    for kind,id,region,point,owner,defended in enemy_targets(ctx,screen,config,enemies):
        if kind=='shipment':continue
        for silo in silos:
            distance=km(ctx,[silo.map_x,silo.map_y],point)
            if distance is None or distance>RANGE_KM:continue
            value=TARGET_VALUE[kind]+(3.0 if not defended else 0)
            if best is None or value>best[0]:best=(value,kind,id,region,owner,silo,distance)
    if best is None:return []
    value,kind,id,region,owner,silo,distance=best
    return [Option(key=f'war:nuclear:{kind}:{id}',domain='war',action='NUCLEAR_STRIKE',label=f'Uderzenie atomowe (1 rakieta z głowicą nuklearną) na {kind} #{id} państwa {owner}',
                   target=owner,stance='hostile',effects={'offensive_army':1.0,'defensive_army':.6,'conquest':.4},
                   traits={'militarism':.9,'provocation':.8,'loss_tolerance':.5,'agreeableness':-.8,'prosociality':-.9},categories={'terrorist':1.0,'imperialist':.5},
                   base=value-2.0,risk=.6,notes=[f'Ostateczność: przegrywana wojna. Silos #{silo.id}, odległość {distance:.0f} km. Skażenie 100 km na 3 lata — powiadomienie do wszystkich państw.'],
                   payload={'kind':'missile','region_id':int(region),'source_base_id':silo.id,'missile_type':'long','missiles':1,'is_nuclear':True,TARGET_FIELD[kind]:id,'group':f'war:nuclear:{owner}'})]


DEFEAT_MARGIN=.3        # o tyle rośnie wymagana przewaga po każdej porażce o ten sam cel
MAX_MARGIN=3.0
MIN_LAND_FORCE=500       # 22 Nov 2026: najmniejsza wysyłana siła (żołnierze + 3×wozy + 5×czołgi), gdy cel jest prawie bez obrony
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
    # 14 Nov 2026: obiekty wroga, które już okupujemy, nie są celem ataku (gra odrzuca: „Ten obiekt jest już pod kontrolą naszego państwa.”).
    held={(o['kind'],o.get('baseId') if o['kind']=='base' else o.get('cityId')) for o in (screen.get('occupations') or [])+((config or {}).get('occupations') or [])
          if o.get('status')=='ACTIVE' and o.get('occupierId')==ctx.country_id and o.get('kind') in ('base','city')}
    targets=[]
    for item in screen.get('bases',[]):
        if ('base',item.get('id')) in held:continue
        if item.get('countryId') in enemies&neighbors and item.get('position') and (item.get('health') or 100)>0:
            targets.append(('base',item['id'],item['position'],item['countryId'],item.get('level'),False))
    for id,city in (config.get('cities') or {}).items():
        if ('city',int(id)) in held:continue
        if city.get('countryId') in enemies&neighbors and city.get('point'):targets.append(('city',int(id),city['point'],city['countryId'],None,False))
    targets+=recapture_targets
    # 26 Nov 2026: cele bez trasy lądowej z żadnej bliskiej bazy (np. za morzem) są pomijane — wcześniej PAGA2 setki razy
    # ponawiała najazd, który gra odrzucała („trasa przemarszu przecina morze lub ocean”), a plany takich celów są zamykane.
    reach={(kind,id):land_base_for(ctx,bases,point,owner) for kind,id,point,owner,*_ in targets}
    targets=[item for item in targets if reach[(item[0],item[1])] is not None]
    live={(kind,id) for kind,id,*_ in targets}
    # Plany, których cel przestał istnieć (odzyskany, poza wojną), są zamykane.
    for key,(plan_id,goal) in plans.items():
        if key not in live:update_plan(plan_id,[],status='DONE' if goal.startswith('recapture') else 'ABANDONED',reason='Cel nie jest już aktualny (odzyskany, poza wojną albo nieosiągalny drogą lądową).')
    for kind,id,point,owner,level,recapture in targets:
        if (kind,id) in intel['marching']:continue          # nasza armia już maszeruje na ten cel — czekamy na wynik bitwy
        defeats=(intel['targets'].get((kind,id)) or {}).get('defeats',0)
        base=reach[(kind,id)]
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
        # 22 Nov 2026: cel prawie bez obrony dawał skalę ~0 i armię bez jednostek (gra: „Wybierz żołnierzy lub sprzęt”,
        # opcja wracała w każdym przebiegu). Najmniejsza wysyłana siła: MIN_LAND_FORCE (ważona), zaokrąglenie w górę.
        scale=min(1.0,max(required*1.15,MIN_LAND_FORCE)/ours) if ours else 1.0
        units={u:min(garrison[u],math.ceil(garrison[u]*scale)) for u in WEIGHTS}
        if not any(units.values()):continue
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


MIN_DEFENSE_RATIO=.6   # 16 Nov 2026: siła własna poniżej 60% siły sąsiada — obrona własnego terytorium niepewna, brak wojny


def _ready(b):return b.health>0 and getattr(b,'operational',True) and bool(b.garrison)


def _stock(screen):return {code:int((value or {}).get('count') or 0) for code,value in ((screen or {}).get('missiles') or {}).items()}


def enemy_geography(ctx,other):
    """Środki regionów państwa i czy ma wybrzeże (dla oceny zasięgu rakiet, myśliwców i okrętów)."""
    cache=getattr(ctx,'_enemy_geo',None)
    if cache is None:cache=ctx._enemy_geo={}
    if other not in cache:
        try:
            from game.paga2.defense import _world
            world=_world(ctx);regions=world.regions_of(other)
            cache[other]=([c for r in regions if (c:=world.center(r))],any(world.coastal(r) for r in regions))
        except Exception:cache[other]=([],True)
    return cache[other]


def strength(ctx,other):
    """Siła zbrojna własna i przeciwnika (ważona liczba sprzętu); (None, None) gdy brak danych."""
    cache=getattr(ctx,'_strength',None)
    if cache is None:cache=ctx._strength={}
    if other not in cache:
        try:
            from game.paga2.diplomacy import powers
            own,_,foe=powers(ctx,other);cache[other]=(float(own),float(foe))
        except Exception:cache[other]=(None,None)
    return cache[other]


def reach_means(ctx,forces,screen,other):
    """16 Nov 2026: środki ataku na odległe państwo — rakiety o zasięgu obejmującym jego terytorium (z baz lądowych
    z wyrzutniami lub morskich z okrętami), myśliwce w zasięgu 1000 km, a przy państwie z wybrzeżem: okręty wojenne
    i podwodne oraz lotniskowce (z myśliwcami w bazach powietrznych)."""
    from game.military_flights import FIGHTER_RANGE
    stock=_stock(screen);centers,coastal=enemy_geography(ctx,other);means={}
    fallback=(ctx.world_summary().get('country_distances_km') or {}).get(other)
    for b in forces.bases:
        if not _ready(b) or b.map_x is None:continue
        g=b.garrison;origin=[b.map_x,b.map_y]
        distances=[d for c in centers if (d:=km(ctx,origin,c)) is not None] or ([fallback] if fallback is not None else [])
        if (b.kind=='land' and g.get('launchers',0)>0) or (b.kind=='naval' and g.get('warships',0)>0):
            for d in distances:
                if (kind:=missile_for(d,stock)):means[kind]=stock[kind]
        if b.kind=='air' and g.get('fighters',0)>0 and any(stock.values()) and any(d<=FIGHTER_RANGE for d in distances):
            means['fighters']=means.get('fighters',0)+int(g['fighters'])
    if coastal:
        for kind in ('warships','submarines'):
            count=sum(int(b.garrison.get(kind,0)) for b in forces.bases if _ready(b) and b.kind=='naval')
            if count:means[kind]=count
        try:
            for v in own_vessels(ctx):
                if v.kind in ('warships','submarines') and v.base_id is None:means[v.kind]=means.get(v.kind,0)+1
        except Exception:pass
        carriers=int((forces.army or {}).get('lotniskowce_ilosc',0) or 0)
        fighters=sum(int(b.garrison.get('fighters',0)) for b in forces.bases if _ready(b) and b.kind=='air')
        if carriers and fighters and any(_ready(b) and b.kind=='naval' for b in forces.bases):means['carriers']=carriers
    return {k:v for k,v in means.items() if v>0}


def offense_means(forces,screen):
    """Środki ataku na sąsiada: czołgi i wozy opancerzone (z żołnierzami) w bazach lądowych, wyrzutnie i myśliwce (z rakietami)."""
    missiles=any(_stock(screen).values());means={}
    for b in forces.bases:
        if not _ready(b):continue
        g=b.garrison
        if b.kind=='land' and g.get('soldiers',0)>0:
            for kind in ('tanks','armored'):means[kind]=means.get(kind,0)+int(g.get(kind,0))
        if missiles and b.kind=='land':means['launchers']=means.get('launchers',0)+int(g.get('launchers',0))
        if missiles and b.kind=='air':means['fighters']=means.get('fighters',0)+int(g.get('fighters',0))
    return {k:v for k,v in means.items() if v>0}


def war_capability(ctx,forces,screen,other):
    """16 Nov 2026: czy państwo jest zdolne do wojny z `other` (wypowiedzenie lub dołączenie do wojny).
    Państwo odległe: potrzebne środki ataku na odległość. Sąsiad: środki ataku oraz obrona własnego terytorium
    (garnizon lądowy i siła zbrojna co najmniej MIN_DEFENSE_RATIO siły sąsiada). Zwraca able, distant, bonus, notes."""
    cache=getattr(ctx,'_capability',None)
    if cache is None:cache=ctx._capability={}
    if other in cache:return cache[other]
    neighbors=set(ctx.world_summary().get('neighbor_countries',[]))
    distant=other not in neighbors;notes=[];able=True;bonus=0.0
    staffed=[b for b in forces.bases if _ready(b)]
    own,foe=strength(ctx,other)
    ratio=own/max(1.0,foe) if own is not None else None
    if not staffed or not forces.has_budget or forces.budget_available<=0:
        able=False;notes.append('Brak zdolności do prowadzenia wojny (obsadzone bazy, budżet wojska).')
    elif distant:
        reach=reach_means(ctx,forces,screen,other)
        if not reach:
            able=False;notes.append('Państwo nie jest sąsiadem, a brak środków ataku na odległość (okręty wojenne, lotniskowce, rakiety o odpowiednim zasięgu, myśliwce w zasięgu).')
        else:
            notes.append('Cel odległy; środki ataku na odległość: '+', '.join(f'{REACH_LABELS[k]} {v}' for k,v in reach.items())+'.')
            bonus+=min(3,len(reach))-1.0
    else:
        offense=offense_means(forces,screen)
        defenders=sum(int(b.garrison.get('soldiers',0)) for b in staffed if b.kind=='land')
        if not offense:
            able=False;notes.append('Brak środków ataku na sąsiada (czołgi lub wozy opancerzone w obsadzonych bazach lądowych, wyrzutnie lub myśliwce z rakietami).')
        if not defenders:
            able=False;notes.append('Brak obsadzonej bazy lądowej do obrony własnego terytorium.')
        if ratio is not None and ratio<MIN_DEFENSE_RATIO:
            able=False;notes.append(f'Siły zbyt słabe do obrony własnego terytorium przed sąsiadem (×{ratio:.2f}, wymagane ×{MIN_DEFENSE_RATIO:.2f}).')
        if able:
            notes.append('Zdolność do ataku na sąsiada i obrony terytorium potwierdzona: '+', '.join(f'{REACH_LABELS[k]} {v}' for k,v in offense.items())+'.')
    if ratio is not None:
        bonus+=3*(min(2.0,ratio)-1)
        notes.append(f'Siły własne {own:.0f} wobec {foe:.0f} przeciwnika (×{ratio:.2f}).')
    cache[other]={'able':able,'distant':distant,'bonus':bonus,'notes':notes}
    return cache[other]


REACH_LABELS={'short':'rakiety krótkiego zasięgu','medium':'rakiety średniego zasięgu','long':'rakiety dalekiego zasięgu','fighters':'myśliwce',
              'warships':'okręty wojenne','submarines':'okręty podwodne','carriers':'lotniskowce','tanks':'czołgi','armored':'wozy opancerzone','launchers':'wyrzutnie rakiet'}


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


def sea_point(ctx,point):
    """14 Nov 2026: cel rejsu przy celu lądowym (miasto, baza) — najbliższa woda poza pasem 2 km od brzegu, jak wymaga gra
    (wcześniej PAGA2 wysyłała współrzędne lądu i gra odrzucała każdy rejs)."""
    cache=getattr(ctx,'_sea_points',None)
    if cache is None:cache=ctx._sea_points={}
    key=(float(point[0]),float(point[1]))
    if key not in cache:
        try:
            from game.sea_routes import _navy_router,MAP_PATH
            from game.military_flights import calibration
            with Session(db.engine) as session:scale=calibration(session).km_per_unit
            cache[key]=_navy_router(MAP_PATH.stat().st_mtime_ns,scale).offshore(list(key))
        except Exception:cache[key]=list(key)
    return cache[key]


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
                              payload={'action':'redirect_vessel','vessel_id':v.id,**dict(zip(('x','y'),sea_point(ctx,here[1]))),'group':f'vessel:{v.id}'}))
    if True:
        for b in forces.bases:
            if b.kind!='naval' or b.health<=0 or b.map_x is None:continue
            for kind in ('warships','submarines'):
                if (b.garrison or {}).get(kind,0)<=busy(b.id,kind):continue
                goal=nearest([b.map_x,b.map_y])
                if goal is None:continue
                options.append(Option(key=f'war:vessel:sail:{b.id}:{kind}',domain='war',action='VESSEL_SAIL',label=f'Rejs ({"okręt podwodny" if kind=="submarines" else "okręt wojenny"}) z bazy #{b.id} ku państwu {goal[2]}',
                                      target=goal[2],stance='hostile',effects={'offensive_army':.9,'conquest':.4},traits={'militarism':.6,'loss_tolerance':.2},base=1.0,
                                      notes=[f'Odległość do celu: {goal[0]:.0f} km.'],payload={'action':'sail','base_id':b.id,'vessel_kind':kind,**dict(zip(('x','y'),sea_point(ctx,goal[1]))),'group':f'sail:{b.id}'}))
    return options


def peace_grace(ctx):
    """16 Nov 2026: państwa objęte karencją po zawarciu pokoju (30 dni Entendy) — {państwo: koniec karencji}."""
    if getattr(ctx,'_peace_grace',None) is None:
        try:
            from game.diplomacy_service import war_lock_map   # 17 Nov 2026: także trwające zawieszenie broni
            with Session(db.engine) as session:ctx._peace_grace=war_lock_map(session,ctx.country_id,ctx.now)
        except Exception:ctx._peace_grace={}
    return ctx._peace_grace


def declare_options(ctx,forces,screen=None):
    """21 Nov 2026 (reforma wojny PAGA2): wypowiedzenie wojny ofensywnej wyłącznie z planu wojennego w etapie READY
    (game.paga2.war_plans) — twarde warunki: gotowość ≥ 80% w każdym obszarze, aktualne rozpoznanie, istniejący cel,
    złe lub gorsze stosunki, brak okresu ochronnego po pokoju (30 dni gry, 180 dni Entendy dla PAGA2). Spełnienie warunków
    nie oznacza wypowiedzenia — dalej decyduje ocena opłacalności i ryzyka (dotychczasowe składniki oceny)."""
    from game.paga2 import war_plans
    options=[]
    triggers={item.get('from') for item in ctx.triggers if item.get('from')}
    if screen is None:screen=war_screen(ctx)
    from game.paga2.war_losses import deterrence_map
    deterred=deterrence_map(ctx)   # 13 Nov 2026: pokój po ciężkiej wojnie — mniejsza skłonność do ataku
    grace=peace_grace(ctx)
    for plan_id,info in war_plans.plan_state(ctx).items():
        plan=info['plan']
        if info['stage']!='READY' or plan.kind!='OFFENSIVE':continue
        other=plan.enemy_id;row=ctx.situation.get('relations',{}).get(other) or {}
        if row.get('state')=='wojnakinetyczna':continue
        until=war_plans.offensive_grace(ctx,other)
        if other in grace:until=max(until or grace[other],grace[other])
        blockers=war_plans.declare_blockers(info['areas'],targets=info['targets'],intel_fresh=info['intel_fresh'],relation=row.get('relation','neutralne'),grace_until=until,now=ctx.now)
        provoked=ctx.history(other)['hostile_from']
        cap=war_capability(ctx,forces,screen,other);distant=cap['distant']
        goal=(plan.goal or {}).get('label') or 'cel planu'
        options.append(Option(key=f'war:declare:{other}',domain='war',action='WAR',label=f'Wypowiedzenie wojny państwu {other} (plan #{plan.id}: {goal})',target=other,stance='hostile',
                              effects={'conquest':1.0,'offensive_army':.7,'welfare':-.6,'financial_stability':-.5,'trade':-.4},
                              traits={'militarism':.8,'expansionism':.8,'provocation':.6,'ambition':.4,'agreeableness':-.8,'strategic_patience':-.3,'predictability':-.2},
                              categories={'imperialist':1.0,'terrorist':.4,'hegemonic':.3,'isolationist':-.5,'welfare':-.6,'economic':-.3},
                              base=-10.0+(0 if distant else 5.0)+4*min(3,provoked)+(6.0 if other in triggers else 0)-min(12.0,deterred.get(other,0.0))+cap['bonus']+6.0*info['areas'].get('combat',{}).get('ratio',0),
                              risk=.4+(.2 if distant else 0),
                              notes=[f'Plan wojenny #{plan.id}: {plan.reason}',f'Cel główny: {goal}.',f'Gotowość: {round(100*(plan.readiness or 0))}% (najsłabszy obszar).']+list(cap['notes'])
                                    +([f'Odstraszenie: pokój po ciężkiej wojnie z tym państwem lub jego sojusznikiem (−{min(12.0,deterred[other]):.1f}).'] if deterred.get(other) else []),
                              payload={'kind':'WAR','target_id':other,'group':'war:declare','plan_id':plan.id,'blockers':blockers}))
    return options


def plan_start_options(ctx,forces):
    """21 Nov 2026: rozpoczęcie przygotowań wojennych (plan wojenny) wobec państwa wrogiego lub zagrażającego — tylko w
    przeglądzie cyklicznym, najwyżej jeden plan ofensywny naraz, bez okresu ochronnego po pokoju. Skłonność wynika
    z profilu (charakter, priorytety, cechy) przez zwykłą punktację; sam plan nie oznacza wojny."""
    from game.paga2 import war_plans
    if ctx.mode!='CYCLIC' or ctx.situation.get('level')=='war':return []
    if any(p.kind=='OFFENSIVE' for p in war_plans.active_plans(ctx)):return []
    options=[];s=ctx.situation;allies=set(s.get('allies',[]))
    from game.sovereignty import lost
    with Session(db.engine) as session:
        gone={other for other in s.get('relations',{}) if lost(session,other) is not None}
    for other,row in s.get('relations',{}).items():
        if other in allies or other in gone or row.get('state')=='wojnakinetyczna':continue
        p=ctx.perception(other);history=ctx.history(other)
        hostile=row.get('relation') in WAR_RELATIONS
        if not (hostile or p.get('threat',20)>=60 or history['hostile_from']>=2):continue
        if war_plans.offensive_grace(ctx,other) is not None or other in peace_grace(ctx):continue
        goal=war_plans.choose_goal(ctx,other,forces)
        motive=[]
        if hostile:motive.append(f'stosunki „{row.get("relation")}”')
        if p.get('threat',20)>=60:motive.append(f'zagrożenie {p.get("threat")}')
        if history['hostile_from']:motive.append(f'wrogie działania wobec nas: {history["hostile_from"]}')
        reason='Uzasadnienie: '+', '.join(motive)+f'. Korzyść: {goal["label"].lower()}.'
        options.append(Option(key=f'war:plan:start:{other}',domain='war',action='WAR_PLAN_START',label=f'Rozpoczęcie przygotowań wojennych wobec państwa {other}: {goal["label"]}',
                              target=other,stance='hostile',effects={'conquest':.8,'offensive_army':.6,'defensive_army':.2},
                              traits={'militarism':.8,'expansionism':.7,'ambition':.5,'revenge':.4,'agreeableness':-.6,'isolationism':-.5},
                              categories={'imperialist':1.0,'hegemonic':.5,'terrorist':.2,'isolationist':-1.0,'economic':-.6,'welfare':-.5},
                              base=-12.0+3*min(3,history['hostile_from'])+(p.get('threat',20)-50)/10,
                              notes=[reason,'Plan nie oznacza wojny: wymaga rozpoznania, przygotowania i gotowości ≥ 80% w każdym obszarze.'],
                              payload={'goal':goal,'reason':reason,'group':'war:plan:start'}))
    return options


def plan_operation_bonus(ctx,options):
    """Operacje na cele planu: premia; po wypowiedzeniu wojny pierwsza operacja jest decyzją wymaganą."""
    from game.paga2 import war_plans
    state=war_plans.plan_state(ctx)
    for info in state.values():
        plan=info['plan']
        if info['stage'] not in ('ACTIVE','NEGOTIATION'):continue
        wanted={(t['kind'],t['id']) for t in info['targets']}
        for option in options:
            if option.target!=plan.enemy_id or not (option.action.startswith('STRIKE_') or option.action in ('LAND_ATTACK','NUCLEAR_STRIKE')):continue
            target=(option.payload.get('target_kind'),option.payload.get('target_id')) if option.action=='LAND_ATTACK' else next(((k,option.payload.get(f)) for k,f in TARGET_FIELD.items() if f in option.payload),(None,None))
            if target in wanted:option.base+=6.0;option.notes=list(option.notes)+[f'Cel planu wojennego #{plan.id}.']
            if plan.first_operation_pending and info['stage']=='ACTIVE' and option.action!='NUCLEAR_STRIKE':
                option.payload=dict(option.payload,required=True,group=f'war:first:{plan.id}')
                option.notes=list(option.notes)+[f'Pierwsza operacja po wypowiedzeniu wojny (plan #{plan.id}) — decyzja wymagana.']
    return options


def propose(ctx):
    from game.paga2.defense import _forces
    from game.paga2 import war_plans
    forces=_forces(ctx)
    options,recapture=occupation_options(ctx)
    enemies=set(ctx.situation.get('at_war',[]))
    screen=war_screen(ctx)
    # 21 Nov 2026: plany wojenne — przegląd etapów i gotowości przed wszystkimi decyzjami wojennymi
    if war_plans.active_plans(ctx):
        try:war_plans.review(ctx,forces,screen,war_config(ctx))
        except Exception as error:ctx.errors.append(f'plany wojenne: {type(error).__name__}: {error}'[:300])
    options+=plan_start_options(ctx,forces)
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
    if enemies:options+=nuclear_strike_options(ctx,forces,screen,config,enemies)
    options+=land_options(ctx,forces,screen,config,enemies,recapture)
    return plan_operation_bonus(ctx,options)


def check(ctx,option):
    if option.action=='WAR' and option.payload.get('blockers'):
        return 'Wojna ofensywna niedozwolona (plan wojenny): '+' '.join(option.payload['blockers'])
    return None


def execute(ctx,option):
    p={k:v for k,v in option.payload.items() if k not in ('group','required','capable','plan_id','distant','reason','blockers','goal')}
    from game.paga2 import war_plans
    if option.action=='WAR_PLAN_START':
        plan=war_plans.create(ctx,option.target,kind='OFFENSIVE',reason=option.payload['reason'],goal=option.payload['goal'],stage='INTELLIGENCE')
        return {'status':200,'war_plan_id':plan} if plan else {'status':409,'error':'Plan wojenny wobec tego państwa już istnieje.'}
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
    elif option.action.startswith('STRIKE_') or option.action=='NUCLEAR_STRIKE':
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
    if status<400:
        ctx._forces=None;ctx._screens.clear()
        if option.action=='WAR' and option.payload.get('plan_id'):
            own,_=strength(ctx,option.target)
            plan=war_plans.plan_for(ctx,option.target)
            war_plans.save(option.payload['plan_id'],stage='ACTIVE',declared_at=ctx.now,first_operation_pending=True,first_operation_attempts=0,power_at_start=own,
                           assessment={**((plan.assessment if plan else None) or {}),'ops_seen':plan.operations if plan else 0},
                           note='Wypowiedzenie wojny — pierwsza operacja przy najbliższej reakcji doraźnej.',now=ctx.now)
            ctx._war_plans=None
        elif option.action.startswith('STRIKE_') or option.action in ('NUCLEAR_STRIKE','LAND_ATTACK','RECAPTURE'):
            war_plans.register_operation(ctx,option.target,option.label)
    return result(status,data)


ADAPTER=register(Adapter(name='war',modes=('CYCLIC','IMMEDIATE'),propose=propose,execute=execute,check=check))
