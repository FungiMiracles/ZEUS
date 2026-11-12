"""PAGA MULTI-AI lanes (Gemini, Groq, local Qwen), one task per lane and per country at a time. ZEUS manages the decision process; PAGA AI manages the country.

    detect (cheap, no LLM) -> task queue (dedup, priority+ageing, guaranteed reviews) -> runner (context ->
    model decision -> player operations) -> results, journal, metrics.
Every mutation uses ordinary player operations and validations.
"""
import fcntl,time
from pathlib import Path
from datetime import datetime,timedelta,timezone
from sqlalchemy import select
from sqlalchemy.orm import Session,lazyload
from extensions import db
from game.paga_ai_models import PagaAiControl,PagaAiIdentity,PagaAiJob,PagaAiPlan
from game.paga_ai_actor import AiActor,configured,ensure_identity,authorized
from game.autonomy_engine import eligible_ids
from game.paga import PagaConfiguration,TRAITS,INTERESTS
from game.models import GamePlayerCountry
from game.finance_service import game_now
from game.paga_ai_tasks import housekeeping,pick,enqueue as enqueue_task,finish
from models import Panstwo

# One tick may process several tasks back to back (the lock keeps a single model instance), but never longer than this.
TICK_BUDGET_SECONDS=20*60


def now():return datetime.now(timezone.utc).replace(tzinfo=None)

def toggle(session,enabled,revision):
    control=session.scalar(select(PagaAiControl).where(PagaAiControl.id==1).with_for_update().execution_options(populate_existing=True))
    if control is None:raise ValueError('Brak konfiguracji AI; wykonaj migrację UAT.')
    if control.revision!=revision:raise ValueError('Stan przełącznika zmienił się. Odśwież panel.')
    control.enabled=enabled;control.revision+=1;control.updated_at=now()
    # Earlier generations, queued tasks and pre-authorised plans are permanently invalidated on every toggle.
    for job in session.scalars(select(PagaAiJob).where(PagaAiJob.status.in_(['QUEUED','PENDING','RUNNING','BLOCKED']))):
        job.status='CANCELLED';job.finished_at=now();job.error='Zmieniono globalny stan autonomicznego zarządzania AI.'
    for plan in session.scalars(select(PagaAiPlan).where(PagaAiPlan.status.in_(['ACTIVE','TRIGGERED']))):
        plan.status='CANCELLED'
    return control

def enqueue(session,country_id,trigger,revision,priority=None,kind='legacy'):
    """Compatibility wrapper (semantic key = trigger)."""
    return enqueue_task(session,country_id,kind,trigger,revision,source='legacy')

def collect(session):
    from game.paga_ai_detector import detect
    control=session.scalar(select(PagaAiControl).where(PagaAiControl.id==1).with_for_update().execution_options(populate_existing=True))
    if not control or not control.enabled:return
    candidates=eligible_ids(session)
    identities={id:ensure_identity(session,id) for id in candidates}
    detect(session,control,candidates,identities)

def claim(session,lane=None):
    """Claim the next task for one model lane (None = any lane). PAGA MULTI-AI: the task kind decides the model,
    Gemini<->Groq hand over when one is unavailable (recorded in the task journal and the PAGA audit log),
    loans go to Qwen only; a task nobody can take stays queued. One running task per country at a time."""
    from game.paga_ai_providers import route,lane as lane_of
    control=session.scalar(select(PagaAiControl).where(PagaAiControl.id==1).with_for_update().execution_options(populate_existing=True))
    if not control or not control.enabled:return None
    moment=now();housekeeping(session,moment)
    eligible=eligible_ids(session)
    busy=set(session.scalars(select(PagaAiJob.country_id).where(PagaAiJob.status=='RUNNING')))
    cache={};routes={}
    def accept(task):
        if task.country_id in busy:return False
        if task.id not in routes:routes[task.id]=route(session,task.kind,moment,cache)
        provider=routes[task.id][0]
        return provider is not None and (lane is None or lane_of(provider)==lane)
    for _ in range(20):
        task=pick(session,control,moment,eligible,accept=accept)
        if task is None:return None
        session.refresh(task,with_for_update=True)
        if task.status not in ('PENDING','QUEUED','BLOCKED') or task.country_id in busy:routes.pop(task.id,None);continue
        identity=session.get(PagaAiIdentity,task.country_id)
        actor=AiActor(task.country_id,identity.user_id,control.revision,task.id) if identity else None
        try:
            if actor is None or task.revision!=control.revision:raise ValueError('Zmieniono uprawnienia.')
            authorized(session,actor)
        except ValueError:
            finish(task,'CANCELLED',error='Zmieniono uprawnienia lub państwo nie jest już zarządzane przez AI.');continue
        provider,handover,_=routes[task.id]
        if handover:record_handover(session,task,handover,moment)
        task.status='RUNNING';task.claimed_at=moment;task.provider=provider
        return actor,task.id,model_label(provider,control),provider
    return None


def model_label(provider,control):
    from game.paga_ai_providers import model_name
    if provider in ('qwen','zeus'):return control.model_id
    return f'{provider}:{model_name(provider)}'[:100]


def record_handover(session,task,handover,moment):
    """Task passed to another model (e.g. Gemini unavailable -> Groq): journal + PAGA audit history."""
    from game.paga_ai_providers import PROVIDERS
    from game.paga_ai_models import PagaAiLog
    from game.paga_ai_tasks import note
    text=f"Przekazano zadanie z {PROVIDERS[handover['from']]['label']} do {PROVIDERS[handover['to']]['label']}: {handover['reason']}"
    note(task,{'krok':'ZEUS','operacja':'przekazanie','wynik':text})
    session.add(PagaAiLog(job_id=task.id,country_id=task.country_id,game_at=game_now(),real_at=moment,operation='paga.handover',
                          parameters={'from':handover['from'],'to':handover['to']},validation='HANDOVER',result=None,reason=text[:500],model_id=handover['to']))

def context(session,actor,trigger):
    """Compact own-country identity (kept for compatibility; the Context Builder builds decision contexts)."""
    config=session.get(PagaConfiguration,actor.country_id) or PagaConfiguration(approved_character={},approved_interests=[]);country=session.get(Panstwo,actor.country_id,options=[lazyload('*')]);identity=session.get(PagaAiIdentity,actor.country_id)
    from game.paga_relationships import country_preferences
    return {'państwo':country.panstwo_nazwa,'id_państwa':actor.country_id,'data_Entendy':str(game_now()),'charakter':{TRAITS[key]:value for key,value in (config.approved_character or {}).items()},'interesy_od_najważniejszego':[INTERESTS[row['key']] for row in config.approved_interests or [] if row['active']],'pamięć_strategiczna':identity.memory[:700],'powód_analizy':reason_text(trigger),'powiązania_historyczne_PAGA':country_preferences(session,actor.country_id)}

def reason_text(trigger):
    """Periodic triggers carry an internal time bucket that the model confused with an audit_id."""
    kind,_,rest=str(trigger).partition(':')
    if kind in ('periodic','review'):return 'okresowa analiza sytuacji państwa'
    return f'{kind}:{rest}' if kind in ('forum','private','event') else str(trigger)

def cancellation_check(engine,actor):
    def cancelled():
        with Session(engine) as session:
            control=session.get(PagaAiControl,1)
            human=session.scalar(select(GamePlayerCountry.id).where(GamePlayerCountry.panstwo_id==actor.country_id))
            from game.diplomacy_service import npc_eligible
            return not control or not control.enabled or control.revision!=actor.revision or human is not None or not npc_eligible(session,actor.country_id)
    return cancelled

def run_tick(app,lane=None):
    """One scheduler tick. lane=None processes every lane in turn (tests, manual runs); the scheduler runs one
    job per lane so an unavailable or slow provider never blocks the others. Each lane has its own lock:
    at most one concurrent request per provider."""
    if not app.config.get('PAGA_AI_CONFIGURED') or app.config.get('ENV_NAME')!='UAT':return
    from game.paga_ai_providers import LANES
    for name in ([lane] if lane else LANES):_run_lane(app,name)


def _collect(app):
    root=Path(app.root_path)/'runtime/qwen'
    with (root/'collect.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return True
        try:
            with Session(db.engine) as session,session.begin():collect(session)
            return True
        except Exception as exc:
            app.logger.warning('PAGA AI: wykrywanie zdarzeń przerwane: %s',f'{type(exc).__name__}: {exc}'[:300]);return False


def _run_lane(app,lane):
    root=Path(app.root_path)/'runtime/qwen';root.mkdir(parents=True,exist_ok=True)
    # The local model keeps its historical lock name (deployment watchers look for it).
    with (root/('worker.lock' if lane=='qwen' else f'worker-{lane}.lock')).open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        with app.app_context():
            started=time.monotonic()
            from game import qwen_runtime
            from game.paga_ai_runner import run_task
            if not _collect(app):return
            # Several tasks per tick pay off with a warm, persistent local model process; API lanes are paced by the limiter.
            limit=max(1,int(app.config.get('PAGA_AI_TASKS_PER_TICK',1)))
            session_model=qwen_runtime.ModelSession() if lane=='qwen' and app.config.get('PAGA_AI_PERSISTENT_MODEL') else None
            try:_process(app,started,limit,session_model,run_task,qwen_runtime,lane)
            finally:
                if session_model is not None:session_model.close()


def _process(app,started,limit,session_model,run_task,qwen_runtime,lane='qwen'):
    """Claim and run up to `limit` tasks of one lane. With a persistent session the local model starts lazily
    (only when a decision is really needed) and is reused; it is closed by the caller."""
    from game.paga_ai_providers import generator
    for _ in range(limit):
        if time.monotonic()-started>=TICK_BUDGET_SECONDS:return
        with Session(db.engine) as session,session.begin():claimed=claim(session,lane)
        if not claimed:return
        actor,task_id,model_id,provider=claimed
        try:
            qwen=(session_model.generate if session_model is not None else qwen_runtime.generate) if provider=='qwen' else None
            generate=generator(provider,qwen) if provider!='zeus' else None
            run_task(app,actor,task_id,model_id=model_id,generate=generate,cancelled=cancellation_check(db.engine,actor),provider=provider)
        except Exception as exc:
            from game.paga_ai_providers import scrub
            error=scrub(f'{type(exc).__name__}: {exc}')[:500]
            app.logger.warning('PAGA AI: zadanie przerwane: %s',error)
            with Session(db.engine) as session,session.begin():
                task=session.get(PagaAiJob,task_id)
                if task and task.status=='RUNNING':
                    # Unknown outcome: the task is verified before any further step; writes are never replayed blindly.
                    task.status='BLOCKED';task.not_before=now()+timedelta(minutes=5);task.error=error
                    if (task.attempts or 0)>=3:finish(task,'FAILED',error=error)

def start_paga_ai_scheduler(app):
    if not app.config.get('PAGA_AI_CONFIGURED') or app.config.get('ENV_NAME')!='UAT':return None
    if app.extensions.get('paga_ai_scheduler'):return app.extensions['paga_ai_scheduler']
    from apscheduler.schedulers.background import BackgroundScheduler
    from game.paga_ai_providers import LANES
    scheduler=BackgroundScheduler(timezone='UTC')
    # One job per model lane (PAGA MULTI-AI): Gemini, Groq and the local Qwen work independently.
    for lane in LANES:scheduler.add_job(run_tick,'interval',seconds=30,args=[app,lane],id=f'paga_ai_{lane}',max_instances=1,coalesce=True,misfire_grace_time=20)
    app.extensions['paga_ai_scheduler']=scheduler;scheduler.start();return scheduler
