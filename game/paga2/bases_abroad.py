"""PAGA2 — bazy wojskowe w krajach sojuszniczych (12 Nov 2026).

Jako gość: w czasie wojny lub zagrożenia państwo prosi sojusznika o pozwolenie na bazę w regionie graniczącym
z wrogiem, a po zgodzie rozmieszcza tam bazę (utrzymanie 2×).
Jako gospodarz: ocena prośby (permit_terms) w diplomacy.proposal_options.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session
from extensions import db
from game.paga2.engine import Adapter,register
from game.paga2.scoring import Option
from game.paga2.finance import request_id,result

ACTION='/game/dyplomacja/akcje'
DEFENSE='/game/obrona-panstwa/zmien'


def permit_terms(ctx,row):
    """Gospodarz: lojalność sojusznicza, zaufanie do gościa, wspólny wróg; izolacjonizm i nacjonalizm działają przeciw."""
    t=ctx.traits;guest=row.source_country_id
    trust=(ctx.perception(guest) or {}).get('trust',50) if hasattr(ctx,'perception') else 50
    threats=set(ctx.situation.get('at_war',[]))|set(ctx.situation.get('threats',[]))
    base=(4*(t.get('alliance_loyalty',50)-50)/50+3*(trust-50)/50-3*(t.get('isolationism',50)-50)/50-2*(t.get('nationalism',50)-50)/50
          +(3.0 if threats else 0)+1.0)
    return {'base':base,'notes':[f'Zaufanie do państwa {guest}: {trust:.0f}; zagrożenie własne: {"tak" if threats else "nie"}.']}


def _state(ctx):
    """Aktywne pozwolenia i regiony sojuszników graniczące z wrogami."""
    from game.base_permits import permits
    from game.military_geography import region_adjacency
    from game.governance import controller_id
    from models import Region
    hostile=set(ctx.situation.get('at_war',[]))|set(ctx.situation.get('threats',[]))
    allies=[o for o,row in ctx.situation.get('relations',{}).items() if row.get('relation')=='sojusznicze']
    with Session(db.engine) as session:
        active={p.region_id:p.host_country_id for p in permits(session,ctx.country_id)}
        held={p.region_id for p in permits(session,ctx.country_id,('ACTIVE','FROZEN'))}
        rows=session.execute(select(Region.region_id,Region.panstwo_id,Region.region_polozenie_id)).all()
        owner={r.region_id:controller_id(session,r.panstwo_id) for r in rows}
    adjacency=region_adjacency()
    frontier={}
    for region,country in owner.items():
        if country in allies and region not in held and any(owner.get(n) in hostile for n in adjacency.get(region,set())):
            frontier.setdefault(country,[]).append(region)
    if 'hegemonic' in ctx.categories:
        # Hegemon buduje obecność wojskową u sojuszników także bez wroga u granic: region sąsiadujący z najwięcej obcymi państwami.
        for ally in allies:
            if ally in frontier:continue
            regions=[r for r,c in owner.items() if c==ally and r not in held]
            if regions:
                frontier[ally]=[max(regions,key=lambda r:(len({owner.get(n) for n in adjacency.get(r,set())}-{ally,None}),-r))]
    return active,frontier


def propose(ctx):
    # 12 Nov 2026: państwo hegemonistyczne buduje bazy u sojuszników także w czasie pokoju i przy niższym militaryzmie.
    hegemon='hegemonic' in ctx.categories
    if ctx.situation.get('level')=='peace' and not hegemon:return []
    from game.paga2.defense import _forces,garrison_for,upkeep
    from game.paga2.diplomacy import addressable,pending_pairs,recently
    t=ctx.traits
    if t.get('militarism',50)<(20 if hegemon else 35):return []
    forces=_forces(ctx);options=[]
    active,frontier=_state(ctx)
    possible=addressable(ctx);pending={target for target,kind in pending_pairs(ctx) if kind=='BASE_PERMIT'}
    for ally,regions in frontier.items():
        if ally not in possible or ally in pending or recently(ctx,'BASE_PERMIT',ally) or ally in active.values():continue
        region=sorted(regions)[0]
        options.append(Option(key=f'abroad:permit:{ally}',domain='diplomacy',action='BASE_PERMIT',label=f'Prośba do państwa {ally} o pozwolenie na bazę w regionie {region}',
                              target=ally,stance='friendly',effects={'defensive_army':.6,'offensive_army':.6,'alliances':.4},
                              traits={'militarism':.6,'alliance_loyalty':.3,'expansionism':.3},categories={'hegemonic':1.0,'imperialist':.3},base=-1.0+(3.0 if ctx.situation.get('level')=='war' else 0)+(2.0 if hegemon else 0),
                              payload={'kind':'BASE_PERMIT','target_id':ally,'region_id':region,'group':f'abroad:{ally}'}))
    used={b.region_id for b in forces.bases}
    for region,host in active.items():
        if region in used:continue      # jedna baza na region z pozwoleniem
        for kind in ('land','air'):
            if not forces.slots.get(kind):continue
            garrison=garrison_for(kind,forces)
            if garrison is None:continue
            cost=2*upkeep(garrison)
            options.append(Option(key=f'abroad:deploy:{region}:{kind}',domain='defense',action='BASE_DEPLOY_ABROAD',label=f'Baza ({kind}) na terytorium sojusznika {host}, region {region}',
                                  cost=cost,sector='armed_forces',effects={'defensive_army':.8,'offensive_army':1.0,'conquest':.4},traits={'militarism':.8,'expansionism':.3},
                                  categories={'hegemonic':1.0,'imperialist':.5},base=3.0+(3.0 if ctx.situation.get('level')=='war' else 0)+(2.0 if hegemon else 0),
                                  notes=[f'Utrzymanie za granicą (2×): {cost/1e9:.2f} MLD na okres budżetowy.'],
                                  payload={'kind':kind,'region_id':region,'garrison':garrison,'group':f'abroad:deploy:{region}'}))
            break
    return options


def check(ctx,option):
    if option.action!='BASE_DEPLOY_ABROAD':return None
    from game.paga2.planner import _holdings,_km
    from game.paga2.location import pick_point
    point=pick_point(option.payload['region_id'],_holdings(ctx).objects,_km(ctx),seed=f'{ctx.request_key}:{option.key}')
    if not point:return 'Brak wolnego miejsca na bazę w regionie sojusznika.'
    option.payload['site']={'x':point[0],'y':point[1]}
    return None


def execute(ctx,option):
    p=option.payload
    if option.action=='BASE_PERMIT':
        status,data=ctx.call(ACTION,form={'kind':'BASE_PERMIT','target_id':str(p['target_id']),'region_id':str(p['region_id'])})
        return result(status,data)
    status,data=ctx.call(DEFENSE,json={'action':'deploy','kind':p['kind'],'region_id':p['region_id'],'garrison':p['garrison'],'request_id':request_id(ctx,option)})
    data=data if isinstance(data,dict) else {}
    if status<400 and data.get('base_id'):
        located,info=ctx.call(DEFENSE,json={'action':'location','base_id':data['base_id'],'x':p['site']['x'],'y':p['site']['y']})
        ctx._forces=None;ctx._holdings=None
        return {'status':status,'base_id':data['base_id'],'location_status':located}
    return result(status,data)


ADAPTER=register(Adapter(name='bases_abroad',modes=('CYCLIC','IMMEDIATE'),propose=propose,execute=execute,check=check))
