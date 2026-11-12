"""Extensible, scored actions backed by the shared player transaction services."""
from dataclasses import dataclass,field
from hashlib import sha256
from random import Random
from uuid import uuid5,NAMESPACE_URL
from sqlalchemy import select
from models import Panstwo,Region,Wojsko,Stosunki,DictStosunkiRelacja
from game.paga import PagaConfiguration
from game.models import GamePlayerCountry
from game.intelligence_models import IntelligenceAgent,IntelligenceMission
from game.diplomacy_models import DiplomaticAction
from game.diplomacy_service import can_declare_war,is_pact,RELATION_ORDER,dictionaries,pair_state,create_action,decide_action,DiplomacyError
from game.intelligence_service import operate_in_transaction,MISSIONS,HYBRID,intelligence_budget
from game.autonomy_memory import assessment,link_source
from game.finance_service import FinanceError

@dataclass
class Candidate:
    action:str
    target:int|None
    payload:dict=field(default_factory=dict)
    score:float=0
    factors:dict=field(default_factory=dict)
    feasible:bool=False
    blocked:str|None=None

@dataclass(frozen=True)
class ActionAdapter:
    propose:object
    check:object
    execute:object

REGISTRY=[]
def register_adapter(adapter):
    if adapter not in REGISTRY:REGISTRY.append(adapter)


def build_context(session,country_id,config,now,focus_id=None):
    from game.road_projects import neighboring_countries
    from game.governance import controller_id
    from game.military_models import MilitaryBase
    from services.natural_resources import normalized
    public=list(session.execute(select(Panstwo.PANSTWO_ID,Panstwo.panstwo_nazwa,Panstwo.panstwo_populacja,Panstwo.panstwo_PKB).where(Panstwo.status=='aktywne',Panstwo.czy_suwerenny=='TAK')))
    neighbors=neighboring_countries(session,country_id)
    profiles={row.panstwo_id:row.approved_character for row in session.scalars(select(PagaConfiguration).where(PagaConfiguration.approved_at.is_not(None)))}
    regions={}
    for id,owner,coastal in session.execute(select(Region.region_id,Region.panstwo_id,Region.region_polozenie_id)):
        owner=controller_id(session,owner)
        regions.setdefault(owner,[]).append({'id':id,'coastal':coastal not in (None,1)})
    own_forces=sum(sum((base.garrison or {}).values()) for base in session.scalars(select(MilitaryBase).where(MilitaryBase.panstwo_id==country_id)))
    own_armies=session.execute(select(Wojsko.wojska_ladowe_ilosc,Wojsko.wojska_powietrzne_ilosc,Wojsko.wojska_morskie_ilosc).where(Wojsko.panstwo_id==country_id)).all()
    own_forces=max(own_forces,sum(sum(value or 0 for value in row) for row in own_armies))
    # Player reconnaissance currently reveals base locations and levels, not garrisons.
    # A known base ID grants no access to its live inventory or troop count.
    resources={}
    for target,report in session.execute(select(IntelligenceMission.target_country_id,IntelligenceMission.report).where(IntelligenceMission.panstwo_id==country_id,IntelligenceMission.kind=='resources',IntelligenceMission.success.is_(True),IntelligenceMission.completed_at.is_not(None))):resources[target]=report
    alliances={}
    for a,b,label in session.execute(select(Stosunki.PANSTWO_ID,Stosunki.PANSTWO_ID2,DictStosunkiRelacja.relacja_nazwa).join(DictStosunkiRelacja,DictStosunkiRelacja.relacja_id==Stosunki.relacja_id)):
        if normalized(label) in ('sojusznicze','partnerskie','partnerskiestrategiczne'):
            alliances.setdefault(a,set()).add(b);alliances.setdefault(b,set()).add(a)
    import re,math
    potentials={target:min(100,sum(math.log1p(float(match[1])) for entry in (report or {}).get('entries',[]) if (match:=re.match(r'^\s*(\d+(?:\.\d+)?)',str(entry.get('value','')))))) for target,report in resources.items()}
    targets=[]
    for id,name,population,gdp in public:
        if id==country_id:continue
        perception=assessment(session,country_id,id,now,profiles.get(id))
        targets.append({'id':id,'name':name,'neighbor':id in neighbors,'population':population,'gdp':gdp,'profile':profiles.get(id),'perception':perception,'strength':None,'known_resources':id in resources,'resource_potential':potentials.get(id,0),'allies':sorted(alliances.get(id,set())),'regions':sorted(regions.get(id,[]),key=lambda row:row['id'])})
    targets.sort(key=lambda row:(-int(row['neighbor']),-row['perception']['threat'],-int(row['known_resources']),row['id']))
    # Cover distant targets as well as neighbors, without inspecting private inventories.
    near=[row for row in targets if row['neighbor']][:8];far=[row for row in targets if not row['neighbor']][:8]
    mandatory=set(session.scalars(select(DiplomaticAction.source_country_id).where(DiplomaticAction.target_country_id==country_id,DiplomaticAction.recipient_user_id.is_(None),DiplomaticAction.status=='PENDING')))
    if focus_id is not None:mandatory.add(focus_id)
    chosen={row['id'] for row in near+far}
    additional=[row for row in targets if row['id'] in mandatory-chosen]
    return {'country_id':country_id,'config':config,'now':now,'traits':config.approved_character,'interests':config.approved_interests,'targets':near+far+additional,'own_strength':own_forces,'own_allies':sorted(alliances.get(country_id,set()))}


def diplomacy_candidates(session,ctx):
    country=ctx['country_id'];relations,states,neutral=dictionaries(session)
    from services.natural_resources import normalized
    order=RELATION_ORDER
    ranking=sorted(relations,key=lambda id:order.index(normalized(relations[id])) if normalized(relations[id]) in order else 5)
    for target in ctx['targets']:
        id=target['id'];_,relation,state,_=pair_state(session,country,id,neutral,states['pokoj'])
        index=ranking.index(relation) if relation in ranking else ranking.index(neutral)
        if index<len(ranking)-1:yield Candidate('RELATION_IMPROVE',id,{'kind':'RELATION','relation_id':ranking[index+1]})
        if index>0:yield Candidate('RELATION_WORSEN',id,{'kind':'RELATION','relation_id':ranking[index-1]})
        for label,action in [('partnerskie','PARTNERSHIP'),('sojusznicze','ALLIANCE')]:
            proposed=next((key for key,name in relations.items() if normalized(name)==label),None)
            if proposed is not None:yield Candidate(action,id,{'kind':'RELATION','relation_id':proposed})
        if is_pact(relations.get(relation)):
            for proposed,label in relations.items():
                if not is_pact(label):yield Candidate('RELATION_WORSEN',id,{'kind':'RELATION','relation_id':proposed})
        if can_declare_war(relations.get(relation),state,states['wojnakinetyczna']):yield Candidate('WAR',id,{'kind':'WAR'})
        if state==states['wojnakinetyczna']:
            yield Candidate('PEACE',id,{'kind':'PEACE'});yield Candidate('CEASEFIRE',id,{'kind':'CEASEFIRE'})
    for proposal in session.scalars(select(DiplomaticAction).where(DiplomaticAction.target_country_id==country,DiplomaticAction.recipient_user_id.is_(None),DiplomaticAction.status=='PENDING').order_by(DiplomaticAction.id)):
        for accept in (True,False):yield Candidate('ACCEPT' if accept else 'REJECT',proposal.source_country_id,{'proposal_id':proposal.id,'accept':accept,'proposal_kind':proposal.kind,'relation_id':proposal.proposed_relation_id})


def diplomacy_check(session,ctx,candidate):
    if 'proposal_id' in candidate.payload:
        decide_action(session,candidate.payload['proposal_id'],ctx['country_id'],candidate.payload['accept'],ctx['now'],dry_run=True)
    else:create_action(session,ctx['country_id'],candidate.target,candidate.payload['kind'],candidate.payload.get('relation_id'),ctx['now'],npc=True,dry_run=True)


def diplomacy_execute(session,ctx,candidate,key,causes):
    if 'proposal_id' in candidate.payload:
        result=decide_action(session,candidate.payload['proposal_id'],ctx['country_id'],candidate.payload['accept'],ctx['now'])
        action=session.get(DiplomaticAction,candidate.payload['proposal_id'])
    else:
        action=create_action(session,ctx['country_id'],candidate.target,candidate.payload['kind'],candidate.payload.get('relation_id'),ctx['now'],npc=True)
        result=action.status
    audit=getattr(action,'autonomy_audit_id',None)
    if audit:link_source(session,'audit',audit,action.source_country_id,action.target_country_id,causes)
    if action.status=='PENDING':link_source(session,'proposal',action.id,action.source_country_id,action.target_country_id,causes)
    return {'diplomatic_action_id':action.id,'status':result}


def intelligence_candidates(session,ctx):
    country=ctx['country_id']
    busy=select(IntelligenceMission.agent_id).where(IntelligenceMission.completed_at.is_(None))
    agents=list(session.scalars(select(IntelligenceAgent).where(IntelligenceAgent.panstwo_id==country,IntelligenceAgent.captured_at.is_(None),~IntelligenceAgent.id.in_(busy)).order_by(IntelligenceAgent.level.desc(),IntelligenceAgent.id)))
    if not agents:yield Candidate('RECRUIT_AGENT',None,{'action':'recruit','level':1,'count':1})
    else:
        agent=agents[0]
        for target in ctx['targets']:
            for region in target['regions'][:2]:
                for kind in MISSIONS:
                    if kind=='cyber_port' and not region['coastal']:continue
                    yield Candidate(('HYBRID_' if kind in HYBRID else 'SCOUT_')+kind,target['id'],{'action':'mission','kind':kind,'agent_id':agent.id,'region_id':region['id']})


def intelligence_check(session,ctx,candidate):
    payload={**candidate.payload,'request_id':str(uuid5(NAMESPACE_URL,'autonomy-check:'+str(ctx['country_id'])+':'+candidate.action+':'+str(candidate.target)+':'+str(candidate.payload.get('region_id'))))}
    operate_in_transaction(session,ctx['country_id'],payload,ctx['now'],dry_run=True)


def intelligence_execute(session,ctx,candidate,key,causes):
    id=operate_in_transaction(session,ctx['country_id'],{**candidate.payload,'request_id':str(uuid5(NAMESPACE_URL,key))},ctx['now'])
    if id:link_source(session,'mission',id,ctx['country_id'],candidate.target,causes)
    return {'mission_id':id,'operation':candidate.payload['action']}


def score(candidate,ctx,rng):
    t=ctx['traits'];active=[item['key'] for item in ctx['interests'] if item['active']];n=len(active)
    weights={key:2*(n-rank)/(n*(n+1)) for rank,key in enumerate(active)}
    target=next((item for item in ctx['targets'] if item['id']==candidate.target),None)
    perception=target['perception'] if target else {'trust':50,'threat':20,'confidence':20}
    hostile=candidate.action in ('WAR','RELATION_WORSEN') or candidate.action.startswith('HYBRID_')
    peaceful=candidate.action in ('RELATION_IMPROVE','PARTNERSHIP','ALLIANCE','PEACE','CEASEFIRE','ACCEPT')
    scout=candidate.action.startswith('SCOUT_');hybrid=candidate.action.startswith('HYBRID_')
    effects={'world_hegemony':.8 if hostile or candidate.action=='ALLIANCE' else .4,'conquer_neighbors':1 if hostile and target and target['neighbor'] else -.2 if peaceful else .3 if scout else 0,'resources_economy':1 if candidate.action=='SCOUT_resources' else .6 if peaceful else -.4 if hostile else .2,'prosperity':.9 if peaceful else -.8 if hostile else .2,'internal_stability':.6 if peaceful else -.3 if hostile else .3,'survival':.8 if peaceful or scout else -.3 if hostile else .4,'regional_hegemony':1 if target and target['neighbor'] and (hostile or candidate.action in ('ALLIANCE','PARTNERSHIP')) else .3,'world_chaos':1 if hostile else -.5 if peaceful else .3,'terrorism':1 if hybrid else .3 if hostile or scout else -.6 if peaceful else 0}
    strategic=45*sum(weights[key]*effects[key] for key in active)
    grievance=(100-perception['trust'])/100
    personality=.18*t['ambition']-.45*t['isolationism']
    if hostile:personality+=.25*t['militarism']+.25*t['provocation']+.18*t['revenge']*grievance-.32*t['agreeableness']+.15*t['militarism']*t['provocation']/100
    elif peaceful:personality+=.35*t['agreeableness']-.15*t['provocation']-.12*t['revenge']*grievance
    elif scout:personality+=.15*t['provocation']+.12*t['militarism']-.08*t['agreeableness']
    situation=(perception['trust']-50)/5 if peaceful else perception['threat']/8 if scout or hybrid else 0
    if target and target['neighbor']:situation+=6
    if target and peaceful:situation+=3*len(set(target.get('allies',[]))&set(ctx.get('own_allies',[])))
    if candidate.action=='SCOUT_resources' and target and not target['known_resources']:situation+=10
    if target and (hostile or candidate.action=='SCOUT_resources'):situation+=weights.get('resources_economy',0)*target.get('resource_potential',0)/5
    if target and scout:situation-=max(0,perception['trust']-50)/5+(20 if target['id'] in ctx.get('own_allies',[]) else 0)
    if candidate.action=='RECRUIT_AGENT':situation+=10
    if candidate.action=='WAR':situation+=20*weights.get('conquer_neighbors',0)+15*weights.get('world_hegemony',0)+10*weights.get('regional_hegemony',0)-10
    if candidate.action=='RELATION_WORSEN':situation-=8
    if candidate.action in ('PEACE','CEASEFIRE'):situation+=15
    if candidate.action in ('ACCEPT','REJECT'):
        proposal=candidate.payload.get('proposal_kind')
        desirability=(t['agreeableness']-t['provocation'])/3+(perception['trust']-50)/3+15
        if proposal in ('PEACE','CEASEFIRE'):desirability+=10
        situation+=desirability if candidate.action=='ACCEPT' else -desirability
    risk=0
    if hostile:
        risk=(100-perception['confidence'])/4
        if target:risk+=5*len(set(target.get('allies',[]))-set(ctx.get('own_allies',[]))-{ctx['country_id']})
        if target and target['strength'] is not None:risk+=min(60,30*target['strength']/max(1,ctx['own_strength']))
    randomness=rng.uniform(-20,20)*(1-t['predictability']/100)
    total=35+strategic+personality+situation-risk+randomness
    candidate.score=round(total,4)
    candidate.factors={'traits':dict(t),'configuration_revision':ctx['config'].revision,'interests':round(strategic,3),'interest_weights':weights,'personality':round(personality,3),'situation':round(situation,3),'risk':round(risk,3),'randomness':round(randomness,3),'perception':perception,'neighbor':target['neighbor'] if target else None,'opponent_character':target['profile'] if target else None,'opponent_strength_known':bool(target and target['strength'] is not None)}
    return candidate

register_adapter(ActionAdapter(diplomacy_candidates,diplomacy_check,diplomacy_execute))
register_adapter(ActionAdapter(intelligence_candidates,intelligence_check,intelligence_execute))
