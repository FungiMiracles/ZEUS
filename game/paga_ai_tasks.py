"""PAGA Task Manager: semantic deduplication, priorities with ageing, guaranteed strategic reviews,
expiry, completion detection and a compact operational journal.

ZEUS manages the *process* here. It never chooses what a country does: every task that needs a decision
is decided by the model; ZEUS only decides *when* to ask and whether the question is still open.
"""
from datetime import datetime,timedelta,timezone
from sqlalchemy import select,update
from game.paga_ai_models import PagaAiJob,PagaAiIdentity,PagaAiControl,ACTIVE_STATUSES

PRIORITY={'CRITICAL':0,'HIGH':10,'MEDIUM':20,'NORMAL':30,'LOW':40}
PRIORITY_NAME={value:key for key,value in PRIORITY.items()}
# Every AGEING_MINUTES of waiting a task gains one priority level, so nothing starves permanently.
AGEING_MINUTES=30
MAX_ATTEMPTS=3
JOURNAL_LIMIT=12
STALE_RUNNING=timedelta(minutes=40)

# kind -> domain used by the Context Builder, default priority, lifetime (real hours; None = until done/superseded).
KINDS={
    'strategic_review':{'domain':'strategy','priority':'LOW','ttl':None},
    'budget':{'domain':'finance','priority':'MEDIUM','ttl':None},
    'private_message':{'domain':'communication','priority':'HIGH','ttl':48},
    'forum_reply':{'domain':'communication','priority':'MEDIUM','ttl':48},
    'forum_mention':{'domain':'communication','priority':'NORMAL','ttl':24},
    'diplomatic_proposal':{'domain':'diplomacy','priority':'HIGH','ttl':72},
    'war_declared':{'domain':'military','priority':'CRITICAL','ttl':24},
    'under_attack':{'domain':'military','priority':'CRITICAL','ttl':12},
    'military_loss':{'domain':'military','priority':'CRITICAL','ttl':12},
    'military_funding':{'domain':'finance','priority':'MEDIUM','ttl':48},
    'military_report':{'domain':'military','priority':'NORMAL','ttl':24},
    'relation_change':{'domain':'diplomacy','priority':'NORMAL','ttl':48},
    'alliance_change':{'domain':'diplomacy','priority':'MEDIUM','ttl':48},
    'hybrid_detected':{'domain':'intelligence','priority':'HIGH','ttl':48},
    'intelligence_report':{'domain':'intelligence','priority':'NORMAL','ttl':48},
    'production_stopped':{'domain':'economy','priority':'MEDIUM','ttl':48},
    'energy_shortage':{'domain':'economy','priority':'MEDIUM','ttl':48},
    'construction_completed':{'domain':'economy','priority':'NORMAL','ttl':48},
    'resource_event':{'domain':'economy','priority':'NORMAL','ttl':48},
    'research_available':{'domain':'economy','priority':'NORMAL','ttl':48},
    'trade_event':{'domain':'economy','priority':'LOW','ttl':48},
    'loan_event':{'domain':'finance','priority':'NORMAL','ttl':48},
    'social_unrest':{'domain':'finance','priority':'MEDIUM','ttl':48},
    'domestic_event':{'domain':'strategy','priority':'NORMAL','ttl':48},
    'intent':{'domain':'strategy','priority':'NORMAL','ttl':72},
    'plan_result':{'domain':'military','priority':'HIGH','ttl':24},
    'conditional_plan':{'domain':'military','priority':'CRITICAL','ttl':6},
    'infrastructure_event':{'domain':'economy','priority':'NORMAL','ttl':48},
    'system_notice':{'domain':'strategy','priority':'LOW','ttl':48},
    'world_event':{'domain':'diplomacy','priority':'LOW','ttl':48},
    'legacy':{'domain':'strategy','priority':'LOW','ttl':None},
    # PAGA2 (11 Nov 2026): algorytm wybiera okazję i adresata, model pisze treść wpisu lub wiadomości.
    'forum_announcement':{'domain':'communication','priority':'NORMAL','ttl':24},
    'private_initiative':{'domain':'communication','priority':'NORMAL','ttl':24},
}


def now():return datetime.now(timezone.utc).replace(tzinfo=None)


# Decyzja administratora (11 Nov 2026, PAGA2): modele językowe odpowiadają wyłącznie za forum i wiadomości prywatne.
# Pozostałe decyzje państwa podejmuje algorytm PAGA2 (game/paga2) — od 19 Nov 2026 także decyzje o udzieleniu pożyczki.
LLM_KINDS=frozenset({'private_message','forum_reply','forum_mention','forum_announcement','private_initiative'})


def legacy_engines():
    """Wycofane mechanizmy (pełny zakres modeli AI, silnik regułowy) — wyłącznie dla zestawów testów, które je nadal
    weryfikują. Flagi nie ustawia aplikacja ZEUS ani panel administratora."""
    from flask import current_app,has_app_context
    return has_app_context() and bool(current_app.config.get('PAGA_LEGACY_ENGINES',False))


def llm_allowed(kind):return kind in LLM_KINDS or legacy_engines()


def enqueue(session,country_id,kind,key,revision,*,source='detector',object_ref=None,context=None,priority=None,not_before=None,goal_id=None):
    """Create a task unless the same meaning already has one (in any status). Returns the new task or None.
    Tasks outside the LLM scope (LLM_KINDS) are never created: PAGA2 handles them."""
    if not llm_allowed(kind):return None
    key=str(key)[:100]
    if session.scalar(select(PagaAiJob.id).where(PagaAiJob.country_id==country_id,PagaAiJob.trigger==key)) is not None:return None
    spec=KINDS.get(kind,KINDS['legacy'])
    ttl=spec['ttl']
    task=PagaAiJob(country_id=country_id,trigger=key,revision=revision,status='PENDING',kind=kind,source=source,
                   priority=PRIORITY[priority or spec['priority']],object_ref=(str(object_ref)[:100] if object_ref is not None else None),
                   context=context or {},journal=[],created_at=now(),not_before=not_before,goal_id=goal_id,
                   expires_at=now()+timedelta(hours=ttl) if ttl else None)
    session.add(task);session.flush()
    return task


def supersede(session,country_id,kind,keep_key):
    """An older open task about the same subject is replaced by a newer state (e.g. a new half-year)."""
    for task in session.scalars(select(PagaAiJob).where(PagaAiJob.country_id==country_id,PagaAiJob.kind==kind,
            PagaAiJob.status.in_(['PENDING','BLOCKED','QUEUED']),PagaAiJob.trigger!=keep_key)):
        finish(task,'SUPERSEDED',error='Zastąpione nowszym stanem gry.')


def finish(task,status,*,result=None,error=None):
    task.status=status;task.finished_at=now()
    if result is not None:task.result=result
    if error is not None:task.error=str(error)[:500]


def note(task,entry):
    """Operational memory of one task: short, newest last, bounded."""
    journal=list(task.journal or [])
    journal.append({key:(str(value)[:200] if isinstance(value,str) else value) for key,value in entry.items()})
    task.journal=journal[-JOURNAL_LIMIT:]


def effective_priority(task,moment):
    waited=max(0,(moment-(task.created_at or moment)).total_seconds()/60)
    return task.priority-10*int(waited//AGEING_MINUTES)


def review_due(identity,control,moment):
    last=identity.last_review_at
    return last is None or moment-last>=timedelta(minutes=max(5,control.review_interval_minutes or 180))


def housekeeping(session,moment):
    """Expire stale questions; a task interrupted mid-run has an UNKNOWN outcome and is verified, never replayed."""
    for task in session.scalars(select(PagaAiJob).where(PagaAiJob.status.in_(['PENDING','QUEUED','BLOCKED']),PagaAiJob.expires_at.is_not(None),PagaAiJob.expires_at<moment)):
        finish(task,'CANCELLED',error='Zadanie wygasło: sytuacja nie wymaga już decyzji.')
    for task in session.scalars(select(PagaAiJob).where(PagaAiJob.status=='RUNNING',PagaAiJob.claimed_at<moment-STALE_RUNNING)):
        if (task.attempts or 0)>=MAX_ATTEMPTS:
            finish(task,'FAILED',error='Przekroczono limit prób po przerwaniu procesu.')
        else:
            task.status='BLOCKED';task.not_before=moment;task.error='Proces przerwano. Przed kolejnym krokiem ZEUS sprawdzi stan gry; zapisów nie odtwarza się automatycznie.'


def pick(session,control,moment,eligible,accept=None):
    """Choose the next task: CRITICAL first, then an overdue strategic review (guaranteed cadence),
    then the best effective priority (base priority improved by waiting time).
    accept(task) limits the choice to tasks the calling model lane may take (PAGA MULTI-AI routing)."""
    rows=list(session.scalars(select(PagaAiJob).where(PagaAiJob.status.in_(['PENDING','QUEUED','BLOCKED']),
        PagaAiJob.country_id.in_(eligible) if eligible else PagaAiJob.id<0).order_by(PagaAiJob.id).limit(500)))
    for task in rows:
        if not llm_allowed(task.kind):finish(task,'CANCELLED',error='Poza zakresem modeli AI: decyzję podejmuje PAGA2.')
    rows=[task for task in rows if llm_allowed(task.kind) and (task.not_before is None or task.not_before<=moment) and (accept is None or accept(task))]
    if not rows:return None
    critical=[task for task in rows if task.priority<=PRIORITY['CRITICAL']]
    # A plan the model already authorised runs first: it needs no model call and answers the emergency fastest.
    if critical:return min(critical,key=lambda task:(task.kind!='conditional_plan',task.id))
    identities={row.country_id:row for row in session.scalars(select(PagaAiIdentity).where(PagaAiIdentity.country_id.in_({task.country_id for task in rows})))}
    reviews=[task for task in rows if task.kind=='strategic_review' and identities.get(task.country_id) is not None and review_due(identities[task.country_id],control,moment)]
    if reviews:return min(reviews,key=lambda task:(identities[task.country_id].last_review_at or datetime.min,task.id))
    return min(rows,key=lambda task:(effective_priority(task,moment),task.id))


def open_task(session,country_id,kind):
    return session.scalar(select(PagaAiJob).where(PagaAiJob.country_id==country_id,PagaAiJob.kind==kind,PagaAiJob.status.in_(ACTIVE_STATUSES)).limit(1))


# ---------- completion detection: is the question still open? (read own state only) ----------

def budget_period(session):
    import game.finance_service as finance
    return finance.period_key(finance.game_now())

def _budget_done(session,task):
    from game.finance_models import StateBudget
    year,period=(task.context or {}).get('year'),(task.context or {}).get('period')
    if year is None:year,period=budget_period(session)
    budget=session.scalar(select(StateBudget.id).where(StateBudget.panstwo_id==task.country_id,StateBudget.game_year==year,StateBudget.period==period))
    return {'reason':f'Budżet {year}/{period} jest już zatwierdzony.','budget_id':budget} if budget else None

def _private_done(session,task):
    from game.communication_models import PrivateMessage
    message_id=int(task.object_ref or 0)
    identity=session.get(PagaAiIdentity,task.country_id)
    if identity is None:return None
    reply=session.scalar(select(PrivateMessage.id).where(PrivateMessage.sender_user_id==identity.user_id,PrivateMessage.reply_to_id==message_id))
    return {'reason':'Na tę wiadomość już odpowiedziano.','message_id':reply} if reply else None

def _forum_done(session,task):
    from game.forum_models import ForumMessage
    message_id=int(task.object_ref or 0)
    identity=session.get(PagaAiIdentity,task.country_id)
    if identity is None:return None
    reply=session.scalar(select(ForumMessage.id).where(ForumMessage.user_id==identity.user_id,ForumMessage.reply_to_id==message_id))
    return {'reason':'Na ten wpis już odpowiedziano.','message_id':reply} if reply else None

def _proposal_done(session,task):
    from game.diplomacy_models import DiplomaticAction
    action=session.get(DiplomaticAction,int(task.object_ref or 0))
    return {'reason':f'Propozycja ma już status {action.status}.'} if action is not None and action.status!='PENDING' else None

DONE={'budget':_budget_done,'private_message':_private_done,'forum_reply':_forum_done,'forum_mention':_forum_done,'diplomatic_proposal':_proposal_done}


def already_done(session,task):
    check=DONE.get(task.kind)
    return check(session,task) if check else None
