"""PAGA2 — wywiad wojskowy: rekrutacja agentów (poziom wg skłonności do szpiegostwa i budżetu), kontrwywiad
oraz misje rozpoznawcze i hybrydowe w innych państwach.

Rozpoznanie dostarcza informacji niejawnych (położenie baz, obrony, elektrowni, kopalń, zasoby regionów) — bez niego
PAGA2 nie zna tych danych i nie może ich użyć (np. do ataku na bazę w etapie „Wojna”).
"""
from datetime import timedelta
from uuid import uuid5,NAMESPACE_URL
from sqlalchemy import select
from sqlalchemy.orm import Session
from extensions import db
from game.paga2.engine import Adapter,register
from game.paga2.scoring import Option
from game.paga2.finance import result

PATH='/game/wywiad-wojskowy/zmien'
REPEAT_DAYS=60
SCOUT_FOR_WAR=('bases','defenses','silos','power','mines','nuclear')
SCOUT_FOR_ECONOMY=('resources','infrastructure','warehouses')


def screen(ctx):return (ctx.screen('intelligence') or {}).get('data') or {}


def recent_missions(ctx):
    from game.intelligence_models import IntelligenceMission
    since=ctx.now-timedelta(days=REPEAT_DAYS)
    with Session(db.engine) as session:
        return {(m.target_country_id,m.kind) for m in session.scalars(select(IntelligenceMission).where(IntelligenceMission.panstwo_id==ctx.country_id,IntelligenceMission.starts_at>=since))}


def target_regions(ctx,other,*,coastal=False):
    """Regiony państwa docelowego od najbliższego naszym granicom (dane jawne z mapy)."""
    from game.paga2.defense import _world
    world=_world(ctx);own=world.regions_of(ctx.country_id)
    def distance(region):
        values=[d for mine in own if (d:=world.region_distance_km(region,mine)) is not None]
        return min(values) if values else 1e9
    regions=[r for r in world.regions_of(other) if not coastal or world.coastal(r)]
    return sorted(regions,key=distance)


def options_for(ctx,data):
    t=ctx.traits;s=ctx.situation;options=[]
    available=float(data.get('budgetAvailable') or 0);ctx._sectors['security_services']=available
    agents=[a for a in data.get('agents',[]) if not a.get('captured')]
    free=[a for a in agents if not a.get('busy')]
    from game.intelligence_service import AGENT_COSTS,MISSION_COSTS,COUNTER_COSTS
    # Rekrutacja: brak wolnych agentów; poziom rośnie ze skłonnością do szpiegostwa (w granicach budżetu).
    if not free:
        level=max(1,min(7,1+int(t.get('espionage',50)//17)))
        while level>1 and AGENT_COSTS[level-1]*2>available*ctx.limits['per_action']:level-=1
        count=1+(1 if t.get('espionage',50)>=70 else 0)
        options.append(Option(key=f'intel:recruit:{level}',domain='intelligence',action='RECRUIT_AGENT',label=f'Rekrutacja {count} agent(ów) poziomu {level}',
                              cost=float(AGENT_COSTS[level-1]*count),sector='security_services',effects={'intelligence':1.0,'defensive_army':.2},
                              traits={'espionage':.9,'secrecy':.4},categories={'terrorist':.4,'hegemonic':.3},base=4.0,payload={'action':'recruit','level':level,'count':count}))
    # Kontrwywiad: po wykrytych działaniach hybrydowych lub przy wysokiej skrytości.
    level=int(data.get('counterLevel') or 1)
    attacked=any(e['kind'] in ('HYBRID_DETECTED','UNATTRIBUTED_DAMAGE') for e in ctx.memory.get('actions_against_us',[]))
    if level<7 and (attacked or t.get('secrecy',50)>=70 or s.get('level')=='war'):
        options.append(Option(key=f'intel:counter:{level}',domain='intelligence',action='COUNTER_UPGRADE',label=f'Kontrwywiad: poziom {level} → {level+1}',
                              cost=float(COUNTER_COSTS[level]),sector='security_services',effects={'intelligence':.8,'defensive_army':.5},
                              traits={'secrecy':.8,'loss_tolerance':-.3},base=3.0+(6.0 if attacked else 0),payload={'action':'counter_upgrade','expected_level':level}))
    if not free:return options
    agent=max(free,key=lambda a:a['level'])
    done=recent_missions(ctx)
    enemies=list(s.get('at_war',[]))+[x for x in s.get('threats',[]) if x not in s.get('at_war',[])]
    neighbors=ctx.world_summary().get('neighbor_countries',[])
    targets=[(other,SCOUT_FOR_WAR,'war') for other in enemies]+[(other,SCOUT_FOR_ECONOMY,'economy') for other in neighbors[:4]]
    for other,kinds,purpose in targets:
        for kind in kinds:
            if (other,kind) in done:continue
            regions=target_regions(ctx,other) if kind!='warehouses' else []
            if not regions and kind!='warehouses':continue
            friendly=other in s.get('allies',[])
            options.append(Option(key=f'intel:scout:{kind}:{other}',domain='intelligence',action='SCOUT_'+kind,label=f'Rozpoznanie ({kind}) w państwie {other}'+(f', region {regions[0]}' if kind!='warehouses' else ''),
                                  target=other,stance='neutral',cost=float(MISSION_COSTS[agent['level']-1]),sector='security_services',
                                  effects={'intelligence':1.0,'offensive_army':.5 if purpose=='war' else 0,'defensive_army':.4 if purpose=='war' else 0,'trade':.3 if purpose=='economy' else 0,'conquest':.3 if purpose=='war' else 0},
                                  traits={'espionage':.8,'secrecy':.2},base=(6.0 if purpose=='war' else 0)-(15.0 if friendly else 0),
                                  payload={'action':'mission','kind':kind,'agent_id':agent['id'],**({'country_id':other} if kind=='warehouses' else {'region_id':regions[0]}),'group':'intel:mission'}))
            break  # jedna misja na państwo w przebiegu
    # Misje hybrydowe: dywersja wobec wrogów (państwa o dużej dywersyjności, terrorystyczne).
    if t.get('subversion',50)>=50 or 'terrorist' in ctx.categories:
        from game.intelligence_service import HYBRID
        for other in enemies+[x for x in s.get('hostile',[]) if x not in enemies]:
            for kind in HYBRID:
                if (other,kind) in done:continue
                regions=target_regions(ctx,other,coastal=kind=='cyber_port')
                if not regions:continue
                options.append(Option(key=f'intel:hybrid:{kind}:{other}',domain='intelligence',action='HYBRID_'+kind,label=f'Działanie hybrydowe ({kind}) w państwie {other}, region {regions[0]}',
                                      target=other,stance='hostile',cost=float(MISSION_COSTS[agent['level']-1]),sector='security_services',effects={'intelligence':.5,'conquest':.4,'offensive_army':.3},
                                      traits={'subversion':1.0,'secrecy':.4,'agreeableness':-.6,'provocation':.4},categories={'terrorist':1.0,'imperialist':.3},base=-4.0,
                                      payload={'action':'mission','kind':kind,'agent_id':agent['id'],'region_id':regions[0],'group':'intel:mission'}))
                break
    return options


def propose(ctx):
    data=screen(ctx)
    if not data:return []
    return options_for(ctx,data)


def execute(ctx,option):
    body={k:v for k,v in option.payload.items() if k!='group'}
    status,data=ctx.call(PATH,json={**body,'request_id':str(uuid5(NAMESPACE_URL,f'paga2:{ctx.request_key}:{option.key}'))})
    return result(status,data)


ADAPTER=register(Adapter(name='intelligence',modes=('CYCLIC','IMMEDIATE'),propose=propose,execute=execute))
