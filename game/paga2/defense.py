"""PAGA2 — obrona państwa i siły zbrojne.

- bazy lądowe, powietrzne, morskie i silosy atomowe: rozmieszczenie z garnizonem i lokalizacją, uzupełnienie garnizonu
  (reorganizacja), rozbudowa, wycofanie garnizonu (gdy brakuje środków na utrzymanie), likwidacja baz zniszczonych,
- obrona przeciwrakietowa regionów, stolicy, baz i obiektów: budowa, rozbudowa, uzupełnienie amunicji, naprawa,
- radary: budowa, rozbudowa, likwidacja zniszczonych,
- szkolenie sił lądowych, morskich i powietrznych.

Lokalizacja: bazy lądowe i powietrzne bliżej zagrożenia (regiony najbliższe wrogom), silosy atomowe jak najdalej
od wroga, bazy morskie na wybrzeżu; przy braku zagrożenia — region z najmniejszą liczbą obiektów (losowo przy remisie).
"""
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import Session
from extensions import db
from game.paga2.engine import Adapter,register
from game.paga2.scoring import Option,clip
from game.paga2.finance import request_id,result

DEFENSE='/game/obrona-panstwa/zmien'
RADAR='/game/obrona-panstwa/radar'
TRAIN='/game/sily-zbrojne/wyszkol'
RECRUIT='/game/sily-zbrojne/rekrutacja'
KIND_LABELS={'land':'Baza lądowa','air':'Baza powietrzna','naval':'Baza morska','nuclear':'Silos atomowy'}


class Forces:
    """Własne siły i obiekty obronne (dane własnego państwa, jak na ekranach „Obrona państwa” i „Siły zbrojne”)."""
    def __init__(self,session,country_id):
        from game.military_models import MilitaryBase,MissileDefense
        from game.military_service import BASES,RESOURCES,active_counts,military_budget
        from game.governance import army_for_country,controlled_ids
        from game.radar_models import Radar
        from models import Miasto
        self.bases=list(session.scalars(select(MilitaryBase).where(MilitaryBase.panstwo_id==country_id).order_by(MilitaryBase.id)))
        army=army_for_country(session,country_id)
        self.army={c.key:getattr(army,c.key) or 0 for c in army.__table__.columns} if army else {}
        active=active_counts(self.bases,session,country_id) if army else {}
        self.free={}
        from game.military_service import owned
        for resource,(label,field,icon) in RESOURCES.items():
            if field:self.free[resource]=max(0,owned(session,army,country_id,field)-active.get(field,0))   # głowice: rzeczywisty licznik (13 Nov 2026)
        self.free_soldiers={kind:max(0,self.army.get(BASES[kind][2],0)-active.get(BASES[kind][2],0)) for kind in ('land','air','naval')}
        # 13 Nov 2026: liczba baz nie jest ograniczona tabelą „wojsko” — „wolne miejsca” to bazy, które da się zbudować
        # z kamienia i żelaza w magazynie (te same reguły co dla gracza: game.military_service.BASE_MATERIALS).
        from game.military_service import buildable_bases
        self.slots=buildable_bases(session,country_id)
        self.defenses=list(session.scalars(select(MissileDefense).where(MissileDefense.panstwo_id==country_id)))
        # 22 Nov 2026: obiekty z jakąkolwiek obroną (także pozostawioną przez poprzedniego właściciela regionu) — gra odrzuca drugą
        self.all_defended=set(session.execute(select(MissileDefense.target_kind,MissileDefense.target_id)).all())
        self.radars=list(session.scalars(select(Radar).where(Radar.panstwo_id==country_id)))
        scope=controlled_ids(session,country_id) or [country_id]
        self.capital=session.scalar(select(Miasto.miasto_id).where(Miasto.panstwo_id.in_(scope),Miasto.miasto_typ_id==1).limit(1))
        budget,total,available=military_budget(session,country_id)
        self.budget_available=float(available);self.budget_total=float(total);self.has_budget=budget is not None
        # 16 Nov 2026: służba czynna — rezerwa, limit 30% ludności 18–64, stawka i opłata za żołnierzy.
        try:
            from game.military_recruitment import summary as recruitment_summary
            self.recruitment=recruitment_summary(session,country_id,army,self.bases) if army else None
        except Exception:self.recruitment=None
        self.ammunition=0
        from game.research_models import ResearchAccount
        account=session.get(ResearchAccount,country_id)
        if account:self.ammunition=int(account.ammunition or 0)


def threat_map(ctx,world):
    """Odległość (km) od środka każdego własnego regionu do najbliższego regionu państwa zagrażającego."""
    enemies=set(ctx.situation.get('at_war',[]))|set(ctx.situation.get('threats',[]))|(set(ctx.situation.get('hostile',[]))&set(world.neighbors(ctx.country_id)))
    own=world.regions_of(ctx.country_id);result={}
    if not enemies:return {},enemies
    enemy_regions=[r for e in enemies for r in world.regions_of(e)]
    for region in own:
        values=[d for other in enemy_regions if (d:=world.region_distance_km(region,other)) is not None]
        result[region]=min(values) if values else None
    return result,enemies


def _world(ctx):
    if getattr(ctx,'_geo',None) is None:
        from game.paga2.geography import World
        with Session(db.engine) as session:ctx._geo=World(session)
    return ctx._geo


def _forces(ctx):
    if getattr(ctx,'_forces',None) is None:
        with Session(db.engine) as session:ctx._forces=Forces(session,ctx.country_id)
        ctx._sectors['armed_forces']=ctx._forces.budget_available  # dokładnie: przydział − wydatki − utrzymanie
    return ctx._forces


def threat_bonus(ctx):return {'war':12.0,'threat':6.0}.get(ctx.situation.get('level'),0.0)


def garrison_for(kind,forces,level=1):
    from game.military_service import CAPACITIES
    capacity=CAPACITIES[kind][level-1];garrison={}
    for resource,limit in capacity.items():
        available=forces.free_soldiers.get(kind,0) if resource=='soldiers' else forces.free.get(resource,0)
        garrison[resource]=int(min(limit,available))
    if kind=='nuclear':return garrison if garrison.get('warheads') else None
    if not garrison.get('soldiers') or not any(v for r,v in garrison.items() if r!='soldiers'):return None
    return garrison


def upkeep(garrison):
    """Utrzymanie w bieżącym okresie budżetowym (stawki półroczne; w kwartale połowa — 13 Nov 2026)."""
    from game.military_service import UPKEEP_RATES
    try:
        from game.finance_service import current_period_months
        scale=current_period_months()/6
    except Exception:scale=1.0
    return float(sum(n*UPKEEP_RATES[r] for r,n in garrison.items()))*scale


def base_site(ctx,kind,threats):
    """Region i punkt nowej bazy."""
    from game.paga2.planner import _holdings,_km
    from game.paga2.location import site
    h=_holdings(ctx)
    regions=[r['id'] for r in h.regions]
    if threats and kind in ('land','air'):
        ranked=sorted((r for r in regions if threats.get(r) is not None),key=lambda r:threats[r])
        regions=ranked[:max(1,len(ranked)//3)] or regions        # trzecia część regionów najbliższych wrogom
    elif threats and kind=='nuclear':
        ranked=sorted((r for r in regions if threats.get(r) is not None),key=lambda r:-threats[r])
        regions=ranked[:max(1,len(ranked)//3)] or regions        # najdalej od wroga
    return site(h,_km(ctx),seed=f'{ctx.request_key}:base:{kind}',regions=regions,coastal=kind=='naval')


UPKEEP_CAP=.5   # 13 Nov 2026: utrzymanie wszystkich baz najwyżej 50% budżetu sił zbrojnych


def total_upkeep(forces):
    return sum(upkeep(b.garrison or {}) for b in forces.bases if b.health>0)


def upkeep_room(forces):
    """Ile utrzymania można jeszcze dodać w granicy UPKEEP_CAP budżetu wojska (bez budżetu — brak limitu)."""
    if not forces.has_budget or forces.budget_total<=0:return float('inf')
    return UPKEEP_CAP*forces.budget_total-total_upkeep(forces)


def crowding(forces,kind=None):
    """Kara za liczbę istniejących baz: priorytet nowej bazy maleje wraz z liczbą baz (danego rodzaju i łącznie)."""
    same=sum(1 for b in forces.bases if kind is None or b.kind==kind);total=len(forces.bases)
    return min(30.0,.6*same+.25*total)


def base_options(ctx,forces,threats):
    from game.military_service import CAPACITIES,UPGRADE_COSTS
    options=[];t=ctx.traits;bonus=threat_bonus(ctx)
    peace=ctx.situation.get('level')=='peace';share=.3+.7*t.get('militarism',50)/100
    room=upkeep_room(forces)
    for kind in ('land','air','naval','nuclear'):
        slots=forces.slots.get(kind)
        if kind!='nuclear' and not slots:continue
        if peace and kind!='nuclear':
            # 12 Nov 2026: w czasie pokoju państwo nie obsadza od razu wszystkich miejsc na bazy (30–100% wg militaryzmu).
            existing=sum(1 for b in forces.bases if b.kind==kind)
            if existing>=share*(existing+slots):continue
        if kind=='nuclear' and not forces.free.get('warheads'):continue
        garrison=garrison_for(kind,forces)
        if garrison is None:continue
        if kind!='nuclear' and upkeep(garrison)>room:continue   # limit utrzymania baz (50% budżetu wojska)
        cost=upkeep(garrison)+(25.5e9 if kind=='nuclear' else 0)
        effects={'defensive_army':1.0,'offensive_army':.5 if kind!='nuclear' else .8,'conquest':.3 if kind=='land' else 0}
        options.append(Option(key=f'base:deploy:{kind}',domain='defense',action='BASE_DEPLOY',label=f'{KIND_LABELS[kind]}: rozmieszczenie z garnizonem',cost=cost,sector='armed_forces',
                              effects=effects,traits={'militarism':.8,'provocation':.4 if kind=='nuclear' else 0,'agreeableness':-.3 if kind=='nuclear' else 0},
                              categories={'imperialist':.5,'hegemonic':.4,'isolationist':.3},base=4.0+bonus-crowding(forces,kind),
                              notes=[f'Garnizon: {garrison}. Koszt utrzymania w okresie: {upkeep(garrison)/1e9:.2f} MLD.',
                                     f'Istniejące bazy: {len(forces.bases)} (kara za liczebność {crowding(forces,kind):.1f}).'],
                              payload={'kind':kind,'garrison':garrison,'group':'base:deploy'}))
    for base in forces.bases:
        if base.health<=0:
            options.append(Option(key=f'base:liquidate:{base.id}',domain='defense',action='BASE_LIQUIDATE',label=f'Likwidacja zniszczonej bazy #{base.id}',
                                  effects={'financial_stability':.3},base=2.0,payload={'action':'liquidate','base_id':base.id}))
            continue
        if base.map_x is None:
            options.append(Option(key=f'base:locate:{base.id}',domain='defense',action='BASE_LOCATE',label=f'Wyznaczenie położenia bazy #{base.id}',
                                  effects={'defensive_army':.6},base=10.0,payload={'base_id':base.id,'kind':base.kind,'region_id':base.region_id}))
        capacity=CAPACITIES[base.kind][base.level-1];garrison=base.garrison or {}
        wanted={}
        for resource,limit in capacity.items():
            extra=forces.free_soldiers.get(base.kind,0) if resource=='soldiers' else forces.free.get(resource,0)
            wanted[resource]=int(min(limit,garrison.get(resource,0)+extra))
        added={r:wanted[r]-garrison.get(r,0) for r in wanted if wanted[r]>garrison.get(r,0)}
        if added and upkeep(added)<=room:   # 13 Nov 2026: także ładowanie silosów rakietami z głowicą nuklearną
            near=threats.get(base.region_id)
            options.append(Option(key=f'base:garrison:{base.id}',domain='defense',action='BASE_REINFORCE',label=f'Uzupełnienie garnizonu bazy #{base.id} ({KIND_LABELS[base.kind]})',
                                  cost=upkeep(added),sector='armed_forces',effects={'defensive_army':.8,'offensive_army':.3},traits={'militarism':.5},
                                  base=3.0+bonus+(4.0 if near is not None and near<500 else 0),notes=[f'Dodane: {added}.'],
                                  payload={'action':'garrison','base_id':base.id,'garrison':wanted,'group':f'base:{base.id}'}))
        full=all(garrison.get(r,0)>=.8*v for r,v in capacity.items() if v)
        if base.level<7 and full and (ctx.situation.get('level')!='peace' or t.get('militarism',50)>=60):
            cost=float(UPGRADE_COSTS[base.level+1])*(2 if base.kind=='nuclear' else 1)
            options.append(Option(key=f'base:upgrade:{base.id}',domain='defense',action='BASE_UPGRADE',label=f'Rozbudowa bazy #{base.id} do poziomu {base.level+1}',
                                  cost=cost,sector='armed_forces',effects={'defensive_army':.8,'offensive_army':.4},traits={'militarism':.6,'ambition':.3},base=bonus/2,
                                  payload={'action':'upgrade','base_id':base.id,'group':f'base:{base.id}'}))
    # Wycofanie garnizonu: brakuje środków na utrzymanie — z bazy najdalej od zagrożenia.
    if forces.has_budget and forces.budget_available<=0 and forces.bases:
        staffed=[b for b in forces.bases if b.garrison and b.health>0 and b.kind!='nuclear']
        if staffed:
            base=max(staffed,key=lambda b:threats.get(b.region_id) or 1e9)
            options.append(Option(key=f'base:withdraw:{base.id}',domain='defense',action='BASE_WITHDRAW',label=f'Wycofanie garnizonu z bazy #{base.id} (brak środków na utrzymanie)',
                                  effects={'financial_stability':1.0,'defensive_army':-.4},traits={'fiscal_conservatism':.6,'militarism':-.4},base=8.0,
                                  payload={'action':'withdraw','base_id':base.id,'group':f'base:{base.id}'}))
    return options


def defense_targets(ctx,forces,threats):
    """Obiekty warte obrony przeciwrakietowej, od najważniejszych (bez regionów okupowanych — gra zabrania tam budowy)."""
    covered={(d.target_kind,d.target_id) for d in forces.defenses}
    # 22 Nov 2026: gra odrzuca obronę obiektu, który ma już jakąkolwiek obronę — także pozostawioną przez poprzedniego
    # właściciela regionu (Rannisjaon proponował w kółko region 249). Liczymy wszystkie istniejące obrony.
    covered|=getattr(forces,'all_defended',set())
    occupied={int(r) for r in ctx.situation.get('occupied_regions',{})}
    targets=[]
    if forces.capital and ('city',forces.capital) not in covered:targets.append(('city',forces.capital,'stolica',8.0))
    for base in forces.bases:
        if base.health>0 and base.map_x is not None and ('base',base.id) not in covered:
            near=threats.get(base.region_id);targets.append(('base',base.id,f'baza #{base.id}',6.0 if base.kind=='nuclear' else 4.0+(3.0 if near is not None and near<800 else 0)))
    for region,distance in sorted(threats.items(),key=lambda item:item[1] if item[1] is not None else 1e9)[:3]:
        if ('region',region) not in covered and distance is not None and distance<1500:targets.append(('region',region,f'region {region} (przygraniczny)',5.0))
    from game.paga2.planner import _holdings
    h=_holdings(ctx)
    for group,kind in ((h.factories,'factory'),(h.plants,'power')):
        for item in group:
            if item.get('id') and item.get('health',0)>0 and (kind,item['id']) not in covered:targets.append((kind,item['id'],f'{kind} #{item["id"]}',2.0))
    if occupied:targets=[t for t in targets if region_of(ctx,forces,t) not in occupied]
    return sorted(targets,key=lambda item:-item[3])


def region_of(ctx,forces,target):
    kind,id=target[0],target[1]
    if kind=='region':return id
    if kind=='base':return next((b.region_id for b in forces.bases if b.id==id),None)
    if kind=='city':
        from models import Miasto
        with Session(db.engine) as session:return session.scalar(select(Miasto.region_id).where(Miasto.miasto_id==id))
    from game.paga2.planner import _holdings
    h=_holdings(ctx)
    return next((o.get('region') for o in (h.factories if kind=='factory' else h.plants) if o.get('id')==id),None)


def missile_defense_options(ctx,forces,threats):
    from game.missile_defense import COSTS,CAPACITIES,AMMUNITION_PRICE
    options=[];bonus=threat_bonus(ctx)
    for kind,target,label,importance in defense_targets(ctx,forces,threats)[:3]:
        options.append(Option(key=f'defense:place:{kind}:{target}',domain='defense',action='DEFENSE_PLACE',label=f'Obrona przeciwrakietowa: {label}',cost=float(COSTS[1]),sector='armed_forces',
                              effects={'defensive_army':1.0},traits={'militarism':.3,'loss_tolerance':-.4},base=importance+bonus-4,
                              payload={'action':'defense_place','target_kind':kind,'target_id':target,'group':'defense:place'}))
    for d in forces.defenses:
        capacity=CAPACITIES[d.level-1]
        if d.health<100:
            count=100-d.health
            options.append(Option(key=f'defense:repair:{d.id}',domain='defense',action='DEFENSE_REPAIR',label=f'Naprawa obrony #{d.id}',cost=count*10000.0,sector='armed_forces',
                                  effects={'defensive_army':.8},base=6.0+bonus,payload={'action':'defense_repair','defense_id':d.id,'count':count,'group':f'defense:{d.id}'}))
            continue
        if d.ammunition<capacity*.5:
            count=capacity-d.ammunition;stock=min(count,forces.ammunition)
            source='stock' if stock>=count else 'purchase'
            options.append(Option(key=f'defense:refill:{d.id}',domain='defense',action='DEFENSE_REFILL',label=f'Uzupełnienie amunicji obrony #{d.id} ({count} pocisków)',
                                  cost=0.0 if source=='stock' else float(count*AMMUNITION_PRICE),sector='armed_forces',effects={'defensive_army':1.0},base=5.0+bonus,
                                  payload={'action':'defense_refill','defense_id':d.id,'count':count,'source':source,'group':f'defense:{d.id}'}))
        elif d.level<7 and ctx.situation.get('level')!='peace':
            options.append(Option(key=f'defense:upgrade:{d.id}',domain='defense',action='DEFENSE_UPGRADE',label=f'Rozbudowa obrony #{d.id} do poziomu {d.level+1}',
                                  cost=float(COSTS[d.level+1]),sector='armed_forces',effects={'defensive_army':.9},traits={'loss_tolerance':-.4},base=bonus/2,
                                  payload={'action':'defense_upgrade','defense_id':d.id,'group':f'defense:{d.id}'}))
    return options


def radar_options(ctx,forces,threats):
    from game.radar import LEVELS,CHIP,IRON
    from game.paga2.planner import _holdings
    h=_holdings(ctx);options=[]
    if not h.developed('radar'):return options
    working=[r for r in forces.radars if r.health>0]
    for radar in forces.radars:
        if radar.health<=0:
            options.append(Option(key=f'radar:liquidate:{radar.id}',domain='defense',action='RADAR_LIQUIDATE',label=f'Likwidacja zniszczonego radaru #{radar.id}',
                                  effects={'financial_stability':.3},base=4.0,payload={'action':'liquidate','radar_id':radar.id}))
        elif radar.level<3:
            rule=LEVELS[radar.level+1]
            if h.stock.get(CHIP,0)>=rule['chips'] and h.stock.get(IRON,0)>=rule['iron']:
                options.append(Option(key=f'radar:upgrade:{radar.id}',domain='defense',action='RADAR_UPGRADE',label=f'Rozbudowa radaru #{radar.id} do poziomu {radar.level+1}',
                                      cost=float(rule['cost']),sector='armed_forces',resources={CHIP:rule['chips'],IRON:rule['iron']},effects={'defensive_army':.7,'intelligence':.6},
                                      traits={'secrecy':.3},base=threat_bonus(ctx)/2,payload={'action':'upgrade','radar_id':radar.id}))
    rule=LEVELS[1]
    if len(working)<1+(1 if ctx.situation.get('level')=='war' else 0) and h.stock.get(CHIP,0)>=rule['chips'] and h.stock.get(IRON,0)>=rule['iron']:
        options.append(Option(key='radar:build',domain='defense',action='RADAR_BUILD',label='Budowa radaru (poziom I, zasięg 400 km)',cost=float(rule['cost']),sector='armed_forces',
                              resources={CHIP:rule['chips'],IRON:rule['iron']},effects={'defensive_army':.9,'intelligence':.8},traits={'secrecy':.4,'militarism':.3},
                              base=2.0+threat_bonus(ctx),payload={'action':'build'}))
    return options


def training_options(ctx,forces):
    from game.military_training import BRANCHES,MAX_LEVEL
    if not forces.has_budget:return []
    t=ctx.traits
    if ctx.situation.get('level')=='peace' and t.get('militarism',50)<60:return []
    levels={branch:forces.army.get(field) if forces.army.get(field) is not None else 100 for branch,(field,_,_) in BRANCHES.items()}
    war=ctx.situation.get('level')=='war'
    # 17 Nov 2026: w czasie wojny priorytetem jest wyszkolenie wojsk lądowych (mnoży siłę w bitwach lądowych),
    # na szkolenie można przeznaczyć większą część limitu jednej akcji, a opcja ma wyższą wagę bazową.
    branch='land' if war and levels['land']<MAX_LEVEL else min(levels,key=levels.get)
    if levels[branch]>=MAX_LEVEL:return []
    price=float(BRANCHES[branch][2])
    count=int(min(MAX_LEVEL-levels[branch],max(0,(.9 if war else .4)*ctx.limits['per_action']*forces.budget_available//price)))
    if count<1:return []
    return [Option(key=f'train:{branch}',domain='army',action='TRAINING',label=f'Szkolenie: {BRANCHES[branch][1]} +{count} (poziom {levels[branch]})',cost=count*price,sector='armed_forces',
                   effects={'defensive_army':1.0 if war else .7,'offensive_army':.7},traits={'militarism':.7,'loss_tolerance':-.3},
                   base=threat_bonus(ctx)+(2.0 if war else 0) if war else threat_bonus(ctx)/2,
                   notes=[f'Siła w bitwie lądowej rośnie proporcjonalnie do wyszkolenia (obecnie {levels[branch]}); koszt {price/1e9:.1f} MLD za poziom.'] if war else [],
                   payload={'branch':branch,'levels':count,'group':'train'})]


def soldier_budget_share(ctx):
    """Część budżetu sił zbrojnych, którą państwo przeznacza na opłatę za żołnierzy (militaryzm, zagrożenie, wojna)."""
    return .2+.25*ctx.traits.get('militarism',50)/100+{'war':.2,'threat':.1}.get(ctx.situation.get('level'),0.0)


def recruitment_options(ctx,forces):
    """16 Nov 2026: rekrutacja żołnierzy do rezerwy służby czynnej (pod nowe garnizony) albo zwolnienie nadmiaru rezerwy,
    gdy opłata za żołnierzy w następnym okresie przekroczyłaby część budżetu sił zbrojnych przeznaczoną na żołnierzy."""
    from game.military_service import CAPACITIES
    r=getattr(forces,'recruitment',None)
    if not r or not forces.has_budget or forces.budget_total<=0:return []
    rate=float(r['rate']);total=int(r['total']);limit=r['limit']
    cap=soldier_budget_share(ctx)*forces.budget_total;fee=total*rate;options=[]
    if rate>0 and fee>cap*1.15:
        excess=int((fee-cap)/rate)+1
        branch=max(r['branches'],key=lambda b:r['branches'][b]['reserve'])
        count=min(excess,r['branches'][branch]['reserve'])
        if count>=1:
            options.append(Option(key=f'army:dismiss:{branch}',domain='army',action='DISMISS',label=f'Zwolnienie {count} żołnierzy z rezerwy ({r["branches"][branch]["label"]})',
                                  effects={'financial_stability':.6,'defensive_army':-.3},traits={'militarism':-.4,'strategic_patience':.2},base=2.0,
                                  notes=[f'Opłata za żołnierzy w następnym okresie {fee:,.0f} ROI przekracza zakładane {cap:,.0f} ROI budżetu sił zbrojnych.'],
                                  payload={'action':'dismiss','branch':branch,'count':count,'group':'army:soldiers'}))
        return options
    if limit is None:return []
    level=ctx.situation.get('level');multiplier={'war':3,'threat':2}.get(level,1)*(.5+ctx.traits.get('militarism',50)/100)
    money_room=(cap-fee)/rate if rate>0 else float('inf')
    room=min(limit-total,money_room)
    for branch in sorted(r['branches'],key=lambda b:r['branches'][b]['reserve']):
        target=int(CAPACITIES[branch][0]['soldiers']*multiplier);reserve=r['branches'][branch]['reserve']
        count=int(min(target-reserve,room))
        if count<min(1000,max(1,target-reserve)):continue
        options.append(Option(key=f'army:recruit:{branch}',domain='army',action='RECRUIT',label=f'Rekrutacja {count} żołnierzy ({r["branches"][branch]["label"]})',
                              effects={'defensive_army':.9,'offensive_army':.5,'financial_stability':-.2},traits={'militarism':.6},base=1.0+threat_bonus(ctx)/2,
                              notes=[f'Rezerwa {reserve} wobec docelowej {target}; opłata od następnego okresu: {count*rate:,.0f} ROI.'],
                              payload={'action':'recruit','branch':branch,'count':count,'group':'army:soldiers'}))
        break
    return options


def propose(ctx):
    forces=_forces(ctx)
    if not forces.army:return []
    threats,_=threat_map(ctx,_world(ctx))
    ctx._threats=threats
    return base_options(ctx,forces,threats)+missile_defense_options(ctx,forces,threats)+radar_options(ctx,forces,threats)+training_options(ctx,forces)+recruitment_options(ctx,forces)+nuclear_production_options(ctx)


def nuclear_production_options(ctx):
    """13 Nov 2026: zamówienie rakiet z głowicą nuklearną w gotowej fabryce (bez aktywnego zamówienia), z surowców w magazynie."""
    from game.research_models import AmmunitionFactory
    from game.nuclear import TECHNOLOGY,MISSILE_INPUTS,factory_ready_at,_active_order,total
    from game.industry_service import available
    options=[]
    with Session(db.engine) as session:
        stock_now=total(session,ctx.country_id)
        for factory in session.scalars(select(AmmunitionFactory).where(AmmunitionFactory.panstwo_id==ctx.country_id,AmmunitionFactory.kind==TECHNOLOGY,
                                                                        AmmunitionFactory.removed_at.is_(None),AmmunitionFactory.health>0)):
            if ctx.now is not None and ctx.now<factory_ready_at(factory):continue
            if _active_order(session,factory.id) is not None:continue
            affordable=min(available(session,ctx.country_id,code)//need for code,need in MISSILE_INPUTS.items())
            war=ctx.situation.get('level')=='war'
            count=int(min(affordable,(6 if war else 3)))
            if count<1:continue
            options.append(Option(key=f'nuclear:order:{factory.id}',domain='defense',action='NUCLEAR_ORDER',label=f'Produkcja {count} szt. rakiet z głowicą nuklearną (fabryka #{factory.id})',
                                  cost=0.0,sector='armed_forces',effects={'defensive_army':.7,'offensive_army':.6},traits={'militarism':.8,'provocation':.3},
                                  categories={'hegemonic':.8,'imperialist':.6},base=2.0+(4.0 if war else 0)-min(4.0,stock_now*.5),
                                  notes=[f'Zapas rakiet atomowych: {stock_now}. Produkcja: 14 dni Entendy na sztukę.'],
                                  payload={'factory_id':factory.id,'count':count,'group':'nuclear:order'}))
    return options


def check(ctx,option):
    if option.action=='BASE_DEPLOY' or option.action=='BASE_LOCATE' or option.action=='RADAR_BUILD':
        kind=option.payload.get('kind','radar')
        if option.action=='BASE_LOCATE':
            from game.paga2.planner import _holdings,_km
            from game.paga2.location import site
            region,point=site(_holdings(ctx),_km(ctx),seed=f'{ctx.request_key}:{option.key}',regions=[option.payload['region_id']],coastal=kind=='naval')
        else:
            region,point=base_site(ctx,'land' if kind=='radar' else kind,getattr(ctx,'_threats',{}))
        if region is None:return point
        option.payload['site']={'region_id':region,'x':point[0],'y':point[1]}
        option.notes.append(f'Lokalizacja: region {region}.')
    return None


def execute(ctx,option):
    p=option.payload;rid=request_id(ctx,option)
    if option.action=='BASE_DEPLOY':
        site=p['site']
        status,data=ctx.call(DEFENSE,json={'action':'deploy','kind':p['kind'],'region_id':site['region_id'],'garrison':p['garrison'],'request_id':rid})
        data=data if isinstance(data,dict) else {}
        if status<400 and data.get('base_id'):
            located,info=ctx.call(DEFENSE,json={'action':'location','base_id':data['base_id'],'x':site['x'],'y':site['y']})
            ctx._forces=None;ctx._holdings=None
            return {'status':status,'base_id':data['base_id'],'location_status':located,'location_error':(info or {}).get('error') if isinstance(info,dict) else None}
        return result(status,data)
    if option.action=='BASE_LOCATE':
        status,data=ctx.call(DEFENSE,json={'action':'location','base_id':p['base_id'],'x':p['site']['x'],'y':p['site']['y']})
    elif option.action.startswith('BASE_') or option.action.startswith('DEFENSE_'):
        body={k:v for k,v in p.items() if k not in ('group',)}
        status,data=ctx.call(DEFENSE,json=body)
    elif option.action.startswith('RADAR_'):
        body={'action':p['action'],**({'radar_id':p['radar_id']} if 'radar_id' in p else {}),**(p.get('site') or {})}
        if p['action']=='build':body['request_id']=rid
        status,data=ctx.call(RADAR,json=body)
    elif option.action=='NUCLEAR_ORDER':
        from game.paga2.industry import PATH as INDUSTRY
        status,data=ctx.call(INDUSTRY,json={'action':'order','category':'factory','object_id':p['factory_id'],'count':p['count'],'request_id':rid})
    elif option.action=='TRAINING':
        status,data=ctx.call(TRAIN,json={'branch':p['branch'],'levels':p['levels'],'request_id':rid})
    elif option.action in ('RECRUIT','DISMISS'):
        status,data=ctx.call(RECRUIT,json={'action':p['action'],'branch':p['branch'],'count':p['count']})
    else:return {'status':400,'error':'Nieznana operacja obronna.'}
    if status<400:ctx._forces=None;ctx._holdings=None
    return result(status,data)


ADAPTER=register(Adapter(name='defense',modes=('CYCLIC','IMMEDIATE'),propose=propose,execute=execute,check=check))
