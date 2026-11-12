"""Visibility-scoped event ingestion, durable reactions and decaying assessments."""
from datetime import timedelta
from hashlib import sha256
from sqlalchemy import select,exists,and_,or_
from game.autonomy_models import AutonomyEvent as Event,AutonomyMemory as Memory,AutonomyReaction as Reaction,AutonomySourceReceipt as Receipt,AutonomyAssessment as Assessment
from game.paga import PagaConfiguration
from services.natural_resources import normalized


def link_source(session,source,id,actor,target,context=None):
    row=session.get(Receipt,(source+'_context',id))
    if row is None:row=Receipt(source=source+'_context',source_id=id);session.add(row)
    row.context={'actor':actor,'target':target,**(row.context or {}),**(context or {})}


def record_event(session,key,kind,actor,target,at,*,public=True,audience=(),payload=None,depth=0,root_id=None):
    existing=session.scalar(select(Event).where(Event.source_key==key))
    if existing:return existing
    if not public and len(audience)!=1:raise ValueError('A private event must have exactly one recipient.')
    event=Event(private_country_id=audience[0] if not public else None,source_key=key,kind=kind,actor_id=actor,target_id=target,occurred_at=at,public=public,audience=list(audience),payload=payload or {},depth=depth,root_id=root_id)
    session.add(event);session.flush();return event


def unconsumed(model,source):
    return ~exists(select(Receipt.source_id).where(Receipt.source==source,Receipt.source_id==model.id))


def ingest_sources(session,control,now):
    from models import AudytStosunki,DictStosunkiRelacja,DictStosunkiStan
    from game.military_models import MilitaryFlight
    from game.intelligence_models import IntelligenceMission
    from game.intelligence_service import HYBRID
    names=dict(session.execute(select(DictStosunkiRelacja.relacja_id,DictStosunkiRelacja.relacja_nazwa)).all())
    states=dict(session.execute(select(DictStosunkiStan.stan_id,DictStosunkiStan.stan_nazwa)).all())
    def context(source,id):
        row=session.get(Receipt,(source+'_context',id));return row.context if row and row.context else {}
    for audit in session.scalars(select(AudytStosunki).where(AudytStosunki.data_zmiany_entenda>=control.started_at,unconsumed(AudytStosunki,'audit')).order_by(AudytStosunki.id).limit(200)):
        previous=session.execute(select(AudytStosunki.relacja_id,AudytStosunki.stan_id).where(AudytStosunki.panstwo_id==audit.panstwo_id,AudytStosunki.panstwo_id2==audit.panstwo_id2,AudytStosunki.id<audit.id).order_by(AudytStosunki.id.desc()).limit(1)).first()
        meta=context('audit',audit.id)
        previous_relation=meta.get('previous_relation',previous.relacja_id if previous else None)
        previous_state=meta.get('previous_state',previous.stan_id if previous else None)
        ally=lambda relation:normalized(names.get(relation,'')) in ('sojusznicze','partnerskie','partnerskiestrategiczne')
        state=normalized(states.get(audit.stan_id,''));old_state=normalized(states.get(previous_state,'')) if previous_state is not None else 'pokoj'
        kind='WAR' if state=='wojnakinetyczna' and old_state!='wojnakinetyczna' else 'ALLIANCE_FORMED' if ally(audit.relacja_id) and not ally(previous_relation) else 'ALLIANCE_BROKEN' if ally(previous_relation) and not ally(audit.relacja_id) else 'RELATION_CHANGED'
        record_event(session,f'audit:{audit.id}',kind,meta.get('actor'),meta.get('target',audit.panstwo_id2),audit.data_zmiany_entenda,payload={'parties':[audit.panstwo_id,audit.panstwo_id2],'relation':names.get(audit.relacja_id,''),'state':states.get(audit.stan_id,'')},depth=meta.get('depth',0),root_id=meta.get('root_id'))
        session.add(Receipt(source='audit',source_id=audit.id))
    for flight in session.scalars(select(MilitaryFlight).where(MilitaryFlight.impacted_at.is_not(None),MilitaryFlight.impacted_at>=control.started_at,unconsumed(MilitaryFlight,'flight')).order_by(MilitaryFlight.id).limit(200)):
        record_event(session,f'flight:{flight.id}','BOMBARDMENT',flight.panstwo_id,flight.target_country_id,flight.impacted_at,payload={'target_kind':flight.target_kind})
        session.add(Receipt(source='flight',source_id=flight.id))
    for mission in session.scalars(select(IntelligenceMission).where(IntelligenceMission.completed_at.is_not(None),IntelligenceMission.completed_at>=control.started_at,unconsumed(IntelligenceMission,'mission')).order_by(IntelligenceMission.id).limit(200)):
        meta=context('mission',mission.id)
        record_event(session,f'mission:{mission.id}:report','INTELLIGENCE_REPORT',mission.panstwo_id,mission.target_country_id,mission.completed_at,public=False,audience=[mission.panstwo_id],payload={'kind':mission.kind,'success':bool(mission.success),'report':mission.report or {},'region_id':mission.region_id},depth=meta.get('depth',0),root_id=meta.get('root_id'))
        if (mission.report or {}).get('captured'):
            record_event(session,f'mission:{mission.id}:detected','HYBRID_DETECTED',mission.panstwo_id,mission.target_country_id,mission.completed_at,public=False,audience=[mission.target_country_id],payload={'kind':mission.kind},depth=meta.get('depth',0),root_id=meta.get('root_id'))
        elif mission.kind in HYBRID and (mission.report or {}).get('damage'):
            record_event(session,f'mission:{mission.id}:effect','UNATTRIBUTED_DAMAGE',None,mission.target_country_id,mission.completed_at,public=False,audience=[mission.target_country_id],payload={'damage':mission.report['damage']},depth=meta.get('depth',0),root_id=meta.get('root_id'))
        session.add(Receipt(source='mission',source_id=mission.id))
    # 12 Nov 2026: bitwy lądowe (jawne). RECAPTURE_ATTACK = państwo odbija własne terytorium z rąk okupanta.
    from game.land_war_models import LandArmy,Occupation
    for army in session.scalars(select(LandArmy).where(LandArmy.resolved_at.is_not(None),LandArmy.resolved_at>=control.started_at,unconsumed(LandArmy,'battle')).order_by(LandArmy.id).limit(200)):
        record=army.battle or {}
        session.add(Receipt(source='battle',source_id=army.id))
        if record.get('result') not in ('ATTACKER_WON','DEFENDER_WON'):continue
        defender=(record.get('defender') or {}).get('country')
        if defender is None or defender==army.panstwo_id:continue
        column=Occupation.base_id if army.target_kind=='base' else Occupation.city_id
        object_id=army.target_base_id if army.target_kind=='base' else army.target_city_id
        recapture=session.scalar(select(Occupation.id).where(Occupation.kind==army.target_kind,column==object_id,Occupation.owner_id==army.panstwo_id,Occupation.occupier_id==defender).limit(1)) is not None
        record_event(session,f'battle:{army.id}','RECAPTURE_ATTACK' if recapture else 'LAND_ATTACK',army.panstwo_id,defender,army.resolved_at,
                     payload={'parties':[army.panstwo_id,defender],'target':army.target_name,'target_kind':army.target_kind,'won':record['result']=='ATTACKER_WON'})
    from game.diplomacy_models import DiplomaticAction
    for action in session.scalars(select(DiplomaticAction).where(DiplomaticAction.status=='PENDING',DiplomaticAction.recipient_user_id.is_(None),unconsumed(DiplomaticAction,'proposal')).order_by(DiplomaticAction.id).limit(200)):
        meta=context('proposal',action.id)
        record_event(session,f'proposal:{action.id}','DIPLOMATIC_PROPOSAL',action.source_country_id,action.target_country_id,now,public=False,audience=[action.target_country_id],payload={'action_id':action.id,'kind':action.kind},depth=meta.get('depth',0),root_id=meta.get('root_id'))
        session.add(Receipt(source='proposal',source_id=action.id))
    session.flush()


def observe(session,country_id,config,now,control,eligible=True):
    traits=config.approved_character;active={i['key'] for i in config.approved_interests if i['active']}
    query=select(Event).where(or_(Event.public.is_(True),Event.private_country_id==country_id),Event.occurred_at<=now,~exists(select(Memory.event_id).where(Memory.country_id==country_id,Memory.event_id==Event.id))).order_by(Event.id).limit(300)
    for event in session.scalars(query):
        if not event.public and country_id not in event.audience:continue
        parties=event.payload.get('parties',[event.actor_id,event.target_id]);involved=country_id in parties
        other=event.target_id if event.actor_id==country_id else event.actor_id
        if other is None and involved:other=next((id for id in parties if id is not None and id!=country_id),None)
        trust=threat=0;confidence=15;importance=10
        if event.kind in ('WAR','BOMBARDMENT','HYBRID_DETECTED','LAND_ATTACK'):
            if involved and event.actor_id!=country_id:trust=-25*(.5+traits['revenge']/100);threat=35;importance=85;confidence=90 if event.actor_id else 35
            elif event.actor_id!=country_id:trust=-5;threat=8;importance=20
        elif event.kind=='RECAPTURE_ATTACK':
            # Odbijanie własnego terytorium: dla okupanta realne zagrożenie, ale mniejsza utrata zaufania niż przy agresji.
            if involved and event.actor_id!=country_id:trust=-10*(.5+traits['revenge']/100);threat=25;importance=75;confidence=90
            elif event.actor_id!=country_id:importance=25
        elif event.kind=='ALLIANCE_FORMED':trust=20 if involved else 2;importance=50 if involved else 10
        elif event.kind=='ALLIANCE_BROKEN':trust=-30 if involved else -4;threat=12;importance=65 if involved else 10
        elif event.kind=='RELATION_CHANGED':
            relation=normalized(event.payload.get('relation',''));trust=(10 if relation in ('dobre','przyjazne','partnerskie','sojusznicze','partnerskiestrategiczne') else -10 if relation in ('zle','wrogie','egzystencjalniewrogie') else 0);importance=40 if involved else 10
        elif event.kind=='INTELLIGENCE_REPORT':confidence=65 if event.payload.get('success') else 10;importance=45
        elif event.kind=='DIPLOMATIC_PROPOSAL':importance=70;confidence=90
        elif event.kind=='UNATTRIBUTED_DAMAGE':importance=60;confidence=20;other=None
        if not involved and active & {'world_hegemony','world_chaos','terrorism','regional_hegemony'}:importance+=traits['ambition']/5
        importance*=.5+traits['ambition']/200+traits['revenge']/200
        session.add(Memory(country_id=country_id,event_id=event.id,other_id=other,importance=importance,trust_delta=trust,threat_delta=threat,confidence=confidence))
        if eligible:
            jitter=6+int(sha256(f'{country_id}:{event.id}'.encode()).hexdigest()[:8],16)%13
            allowed=importance>=25 and event.depth<control.max_chain_depth and now-event.occurred_at<=timedelta(days=90)
            session.add(Reaction(country_id=country_id,event_id=event.id,ready_at=event.occurred_at+timedelta(hours=jitter),status='READY' if allowed else 'IGNORED'))
    session.flush()


def assessment(session,country_id,other_id,now,profile=None):
    memories=list(session.execute(select(Memory,Event.occurred_at).join(Event,Event.id==Memory.event_id).where(Memory.country_id==country_id,Memory.other_id==other_id)))
    trust=50.;threat=20.;confidence=20.
    if profile:
        trust+=(profile['agreeableness']-profile['provocation'])/10+(profile['predictability']-50)/25
        threat+=(profile['militarism']+profile['provocation']+profile['ambition'])/15+profile['revenge']/20-profile['isolationism']/10
        confidence+=profile['predictability']/10
    for memory,at in memories:
        decay=2**(-max(0,(now-at).total_seconds())/(120*86400))
        trust+=memory.trust_delta*decay;threat+=memory.threat_delta*decay;confidence=max(confidence,memory.confidence*decay)
    values={key:round(max(0,min(100,value)),3) for key,value in [('trust',trust),('threat',threat),('confidence',confidence)]}
    row=session.get(Assessment,(country_id,other_id))
    if row is None:row=Assessment(country_id=country_id,other_id=other_id);session.add(row)
    row.trust=values['trust'];row.threat=values['threat'];row.confidence=values['confidence'];row.updated_at=now
    return values
