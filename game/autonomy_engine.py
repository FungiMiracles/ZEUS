"""Transactional scoring/execution, durable daily schedule and independent reactions."""
from datetime import timedelta
from hashlib import sha256
from math import ceil
from random import Random
from dataclasses import asdict
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from extensions import db
from flask import current_app
from models import Panstwo
from game.models import GamePlayerCountry
from game.paga import PagaConfiguration
from game.autonomy_models import AutonomyControl as Control,AutonomySchedule as Schedule,AutonomyAnalysis as Analysis,AutonomyReaction as Reaction,AutonomyEvent as Event
from game.autonomy_memory import ingest_sources,observe
from game.autonomy_actions import REGISTRY,build_context,score
from game.diplomacy_service import npc_eligible,DiplomacyError
from game.finance_service import FinanceError

THRESHOLD=55
PERIOD=timedelta(days=1)


def control_row(session,now,*,lock=True):
    query=select(Control).where(Control.id==1)
    if lock:query=query.with_for_update()
    row=session.scalar(query.execution_options(populate_existing=True))
    if row is None:raise RuntimeError('Brak konfiguracji silnika autonomii. Wykonaj migrację UAT.')
    return row


def eligible_ids(session):
    """Państwa bez gracza z włączoną autonomią: profil PAGA2 (źródło flagi) albo — bez profilu — dawna konfiguracja PAGA."""
    legacy=set(session.scalars(select(PagaConfiguration.panstwo_id).join(Panstwo,Panstwo.PANSTWO_ID==PagaConfiguration.panstwo_id).where(PagaConfiguration.approved_at.is_not(None),PagaConfiguration.autonomy_enabled.is_(True),Panstwo.status=='aktywne',Panstwo.czy_suwerenny=='TAK',~Panstwo.PANSTWO_ID.in_(select(GamePlayerCountry.panstwo_id)))))
    from game.paga2.models import Paga2Profile,table_ready
    if not table_ready(session,Paga2Profile):return sorted(legacy)
    profiles={row.panstwo_id:row.autonomy_enabled for row in session.scalars(select(Paga2Profile))}
    candidates={id for id in legacy if id not in profiles}|{id for id,enabled in profiles.items() if enabled}
    return sorted(id for id in candidates if npc_eligible(session,id))


class _MemoryProfile:
    """Cechy i interesy do ważenia pamięci: profil PAGA2 (gdy istnieje) albo dotychczasowa konfiguracja PAGA."""
    def __init__(self,traits,interests):self.approved_character=traits;self.approved_interests=interests


def memory_profiles(session):
    from game.paga2.models import Paga2Profile,table_ready
    profiles={}
    for config in session.scalars(select(PagaConfiguration).where(PagaConfiguration.approved_at.is_not(None))):
        profiles[config.panstwo_id]=_MemoryProfile(config.approved_character,config.approved_interests or [])
    if table_ready(session,Paga2Profile):
        for row in session.scalars(select(Paga2Profile)):
            profiles[row.panstwo_id]=_MemoryProfile(row.traits,profiles[row.panstwo_id].approved_interests if row.panstwo_id in profiles else [])
    return profiles


def collect_and_schedule(session,now):
    """Pamięć zdarzeń (fakty, ocena zaufania i zagrożenia) dla państw z profilem PAGA/PAGA2.
    Dotychczasowy silnik regułowy nie planuje już analiz — decyzje podejmuje PAGA2 (decyzja administratora 11 Nov 2026)."""
    if not current_app.config.get('AUTONOMY_ENABLED') or current_app.config.get('ENV_NAME')!='UAT':return
    control=control_row(session,now)
    ingest_sources(session,control,now)
    from game.paga_ai_tasks import legacy_engines
    if legacy_engines():return _legacy_collect(session,now,control)
    from game.diplomacy_service import expire_unanswerable
    expire_unanswerable(session)
    humans=set(session.scalars(select(GamePlayerCountry.panstwo_id)))
    for country_id,profile in sorted(memory_profiles(session).items()):
        if country_id in humans:continue
        observe(session,country_id,profile,now,control,eligible=False)
    session.flush()


def _legacy_collect(session,now,control):
    """Wycofany harmonogram silnika regułowego (tylko testy z flagą PAGA_LEGACY_ENGINES)."""
    for config in session.scalars(select(PagaConfiguration).where(PagaConfiguration.approved_at.is_not(None)).order_by(PagaConfiguration.panstwo_id)):
        if session.scalar(select(GamePlayerCountry.id).where(GamePlayerCountry.panstwo_id==config.panstwo_id)) is not None:continue
        active=npc_eligible(session,config.panstwo_id)
        observe(session,config.panstwo_id,config,now,control,eligible=active)
        if active:
            schedule=session.get(Schedule,config.panstwo_id)
            if schedule is None or schedule.next_at>now+PERIOD:
                offset=int(sha256(f'autonomy:{config.panstwo_id}'.encode()).hexdigest()[:12],16)%int(PERIOD.total_seconds())
                if schedule is None:session.add(Schedule(country_id=config.panstwo_id,next_at=now+timedelta(seconds=offset)))
                else:schedule.next_at=now+timedelta(seconds=offset)
    session.flush()


def analyze(session,country_id,now,*,event_id=None):
    """Wyłączone na stałe (decyzja administratora 11 Nov 2026): decyzje państw podejmuje algorytm PAGA2."""
    from game.paga_ai_tasks import legacy_engines
    if not legacy_engines():return None
    from game.paga_ai_actor import configured
    if configured():return None  # Qwen owns decisions; its OFF switch must not start another provider.
    if not current_app.config.get('AUTONOMY_ENABLED') or current_app.config.get('ENV_NAME')!='UAT':return None
    control=control_row(session,now)
    if not control.enabled:return None
    # Canonical country locking also serializes player assignment and PAGA changes with execution.
    list(session.scalars(select(Panstwo.PANSTWO_ID).where(Panstwo.status=='aktywne').order_by(Panstwo.PANSTWO_ID).with_for_update()))
    config=session.scalar(select(PagaConfiguration).where(PagaConfiguration.panstwo_id==country_id).with_for_update().execution_options(populate_existing=True))
    if not npc_eligible(session,country_id):return None
    event=None;reaction=None;schedule=None
    if event_id is not None:
        reaction=session.scalar(select(Reaction).where(Reaction.country_id==country_id,Reaction.event_id==event_id).with_for_update().execution_options(populate_existing=True))
        if reaction is None or reaction.status!='READY' or reaction.ready_at>now:return None
        event=session.get(Event,event_id)
        if not event.public and event.private_country_id!=country_id:raise RuntimeError('Niedozwolona widoczność zdarzenia.')
        key=f'reaction:{country_id}:{event_id}'
    else:
        schedule=session.scalar(select(Schedule).where(Schedule.country_id==country_id).with_for_update().execution_options(populate_existing=True))
        if schedule is None or schedule.next_at>now:return None
        key=f'periodic:{country_id}:{schedule.next_at.isoformat()}'
    existing=session.scalar(select(Analysis).where(Analysis.request_key==key))
    if existing:return existing.id
    trigger='REACTION' if event else 'PERIODIC'
    log=Analysis(request_key=key,country_id=country_id,game_at=now,trigger=trigger,event_id=event_id,action='PASSIVE',status='PASSIVE',factors={},candidates=[])
    session.add(log);session.flush()
    used=session.scalar(select(func.count(Analysis.id)).where(Analysis.country_id==country_id,Analysis.status=='EXECUTED',Analysis.game_at>=now-timedelta(days=control.window_days)))
    t=config.approved_character
    cap=max(1,min(control.max_actions,ceil(control.max_actions*(.5+.25*t['provocation']/100+.25*t['militarism']/100-.25*t['isolationism']/100))))
    reason='Żadne wykonalne działanie nie osiągnęło progu oceny.'
    if event and (event.depth>=control.max_chain_depth or now-event.occurred_at>timedelta(days=90)):
        reason='Przekroczona głębokość łańcucha reakcji lub zdarzenie starsze niż 90 dni Entendy.'
    elif used>=cap:reason=f'Limit aktywności: {used}/{cap} działań w {control.window_days} dniach Entendy.'
    else:
        ctx=build_context(session,country_id,config,now,focus_id=event.actor_id if event else None)
        rng=Random(int(sha256(key.encode()).hexdigest(),16))
        candidates=[]
        for adapter in REGISTRY:
            candidates.extend((score(candidate,ctx,rng),adapter) for candidate in adapter.propose(session,ctx))
        candidates.sort(key=lambda item:(-item[0].score,item[0].action,item[0].target or 0))
        executed=False
        for candidate,adapter in candidates:
            if executed:candidate.feasible=None;candidate.blocked='Niższa ocena niż wybranego działania.';continue
            if candidate.score<THRESHOLD:candidate.blocked='Ocena poniżej progu 55.';continue
            previous=session.scalar(select(Analysis.id).where(Analysis.country_id==country_id,Analysis.action==candidate.action,Analysis.target_id==candidate.target,Analysis.status=='EXECUTED',Analysis.game_at>=now-timedelta(days=control.cooldown_days)).limit(1))
            if previous:candidate.blocked=f'Okres oczekiwania: {control.cooldown_days} dni Entendy.';continue
            try:
                adapter.check(session,ctx,candidate);candidate.feasible=True
                if not npc_eligible(session,country_id) or not control.enabled:raise FinanceError('Autonomia wyłączona lub państwo przejęte przez gracza.')
                causes={'root_id':(event.root_id or event.id) if event else None,'depth':event.depth+1 if event else 0}
                with session.begin_nested():result=adapter.execute(session,ctx,candidate,key,causes)
                log.action=candidate.action;log.target_id=candidate.target;log.score=candidate.score;log.factors=candidate.factors;log.result=result
                log.status='EXPIRED' if result.get('status')=='EXPIRED' else 'EXECUTED';executed=True
            except (FinanceError,DiplomacyError) as error:candidate.feasible=False;candidate.blocked=str(error)
        log.candidates=[asdict(candidate) for candidate,adapter in candidates]
    if log.status=='PASSIVE':log.factors={'reason':reason,'actions_used':used,'activity_cap':cap,'threshold':THRESHOLD}
    if reaction:reaction.status='DONE';reaction.error=None
    if schedule:
        # Coalesce missed intervals into one analysis; never replay years of aggressive decisions after downtime.
        missed=max(1,(now-schedule.next_at)//PERIOD+1)
        schedule.next_at+=missed*PERIOD;schedule.last_at=now;schedule.last_error=None
    session.flush();return log.id


def record_failure(country_id,now,error,event_id=None):
    # Error recording is isolated from the failed action transaction and other countries.
    with Session(db.engine) as session,session.begin():
        control_row(session,now)
        schedule=session.get(Schedule,country_id)
        reaction=session.get(Reaction,(country_id,event_id)) if event_id is not None else None
        key=f'error:{country_id}:{event_id}:{now.isoformat()}'
        session.add(Analysis(request_key=key,country_id=country_id,game_at=now,trigger='REACTION' if event_id else 'PERIODIC',event_id=event_id,action='ERROR',status='ERROR',factors={},candidates=[],error=f'{type(error).__name__}: {error}'[:3000]))
        if reaction:reaction.ready_at=now+timedelta(days=1);reaction.error=str(error)[:2000]
        elif schedule:schedule.next_at=now+timedelta(days=1);schedule.last_error=str(error)[:2000]
