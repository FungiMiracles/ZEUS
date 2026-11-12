"""PAGA Event Detector: notices situations that need a decision. No language model is used here.

Cheap by construction: incremental cursors over existing game event sources (the AI identity's own notification
inbox, autonomy events, forum, private messages) and per-country probes at most every PROBE_MINUTES, only for
AI-controlled countries. The detector may read the database to *notice* something; what the model later sees
comes from player routes (see paga_ai_context).
"""
import re
from datetime import timedelta
from sqlalchemy import select,func
from game.paga_ai_models import PagaAiIdentity,PagaAiJob,PagaAiPlan,ACTIVE_STATUSES
from game.paga_ai_tasks import enqueue,supersede,finish,review_due,now,open_task,KINDS,budget_period

PROBE_MINUTES=5
MERGE_LIMIT=6
# Situations that accumulate into one open task per country instead of a task per notification.
MERGEABLE={'under_attack','military_loss','military_report','military_funding','relation_change','alliance_change','hybrid_detected','intelligence_report',
           'production_stopped','energy_shortage','construction_completed','resource_event','trade_event','loan_event','social_unrest','domestic_event',
           'infrastructure_event','system_notice','world_event'}
# Pinned to the texts of the game's notification producers (tests keep this list honest).
SYSTEM_PATTERNS=[
    (re.compile(r'przeprowadziło atak na cel'),'under_attack'),
    (re.compile(r'^Twoja baza .* została zniszczona'),'military_loss'),
    (re.compile(r'^Atak na statek handlowy'),'military_loss'),
    (re.compile(r'^Zakończono nasz atak'),'military_report'),
    (re.compile(r'^Działania hybrydowe:'),'hybrid_detected'),
    (re.compile(r'^Wywiad wojskowy:'),'intelligence_report'),
    (re.compile(r'Brakuje pieniędzy na utrzymanie wojska|brak środków na utrzymanie'),'military_funding'),
    (re.compile(r'produkcja energii została wstrzymana'),'energy_shortage'),
    (re.compile(r'produkcja została wstrzymana'),'production_stopped'),
    (re.compile(r'wydobycie zatrzymane'),'resource_event'),
    (re.compile(r'^Pożyczka:'),'loan_event'),
    (re.compile(r'^Droga:'),'infrastructure_event'),
    (re.compile(r'nie są zadowoleni z wysokiej stawki podatku'),'social_unrest'),
    (re.compile(r' zakupił/a '),'trade_event'),
]
NOTIFICATION_KIND={'INFRASTRUCTURE_COMPLETED':'construction_completed'}
# Administrator decision (10 Nov 2026): Event Generator news and road matters never create PAGA AI tasks.
IGNORED_NOTIFICATIONS={'GENERATED_EVENT'}
IGNORED_KINDS={'infrastructure_event'}


def classify_text(text):
    for pattern,kind in SYSTEM_PATTERNS:
        if pattern.search(text or ''):return kind
    return 'system_notice'


def raise_task(session,country_id,kind,key,revision,*,source,object_ref=None,context=None,merge_item=None):
    """Create a task, or merge the new fact into the open task of the same kind (no duplicate questions)."""
    if kind in MERGEABLE:
        current=session.scalar(select(PagaAiJob).where(PagaAiJob.country_id==country_id,PagaAiJob.kind==kind,PagaAiJob.status.in_(['PENDING','BLOCKED','QUEUED'])).limit(1))
        if current is not None:
            details=dict(current.context or {});items=list(details.get('zdarzenia') or [])
            if merge_item and merge_item not in items:items.append(merge_item)
            details['zdarzenia']=items[-MERGE_LIMIT:];current.context=details
            if KINDS[kind]['priority']=='CRITICAL':current.priority=0
            return current
    context=dict(context or {})
    if merge_item:context.setdefault('zdarzenia',[merge_item])
    return enqueue(session,country_id,kind,key,revision,source=source,object_ref=object_ref,context=context)


def names(session,ids):
    from models import Panstwo
    ids=[value for value in ids if value]
    return dict(session.execute(select(Panstwo.PANSTWO_ID,Panstwo.panstwo_nazwa).where(Panstwo.PANSTWO_ID.in_(ids))).all()) if ids else {}


def fire_conditional(session,country_id,condition,other_id,revision,cause):
    """A model-authorised conditional plan met its condition: queue its one-time execution (CRITICAL)."""
    from game.paga_ai_strategy import conditional_plans
    for plan in conditional_plans(session,country_id,condition,other_id):
        plan.status='TRIGGERED'
        enqueue(session,country_id,'conditional_plan',f'plan:{plan.id}',revision,source='plan',object_ref=plan.id,goal_id=plan.goal_id,context={'przyczyna':cause})


def detect(session,control,eligible,identities):
    """One incremental pass. `identities` maps country_id -> PagaAiIdentity for eligible AI countries."""
    from game.paga_ai_strategy import due_intents,expire_plans
    import game.finance_service as finance
    moment=now();revision=control.revision
    by_user={row.user_id:country for country,row in identities.items()}
    country_names=names(session,list(identities))
    # Human takeover or PAGA disabled: open questions and plans of that country end immediately.
    for task in session.scalars(select(PagaAiJob).where(PagaAiJob.status.in_(['PENDING','BLOCKED','QUEUED']),PagaAiJob.country_id.notin_(eligible) if eligible else PagaAiJob.id>0)):
        finish(task,'CANCELLED',error='Państwo przejął gracz albo wyłączono jego autonomię.')
    for plan in session.scalars(select(PagaAiPlan).where(PagaAiPlan.status.in_(['ACTIVE','TRIGGERED']),PagaAiPlan.country_id.notin_(eligible) if eligible else PagaAiPlan.id>0)):
        plan.status='CANCELLED'
    try:game_moment=finance.game_now()
    except Exception:game_moment=None
    if game_moment is not None:expire_plans(session,game_moment)

    # 1. Own notification inbox of each AI identity (exactly what a human player of that country would see).
    from game.forum_models import GameNotification
    for country_id,identity in identities.items():
        rows=list(session.scalars(select(GameNotification).where(GameNotification.user_id==identity.user_id,GameNotification.id>identity.notification_cursor).order_by(GameNotification.id).limit(100)))
        for row in rows:
            identity.notification_cursor=row.id
            if row.notification_type in IGNORED_NOTIFICATIONS:continue
            kind=None;key=f'note:{row.id}';ref=None;text=row.system_text or row.infrastructure_text or ''
            if row.notification_type=='FORUM_MESSAGE':kind,key,ref='forum_reply',f'forum:{row.message_id}',row.message_id
            elif row.notification_type=='DIPLOMACY':
                from game.diplomacy_models import DiplomaticAction
                action=session.get(DiplomaticAction,row.diplomatic_action_id)
                if action is None:continue
                kind='war_declared' if action.kind=='WAR' else 'diplomatic_proposal'
                key,ref=f'proposal:{action.id}',action.id
                text=f'{action.source_country_name}: {action.kind}'
            elif row.notification_type in NOTIFICATION_KIND:kind=NOTIFICATION_KIND[row.notification_type]
            elif row.notification_type=='SYSTEM':kind=classify_text(text)
            else:kind='system_notice'
            if kind in IGNORED_KINDS:continue
            raise_task(session,country_id,kind,key,revision,source='notification',object_ref=ref,merge_item=text[:300] if text else None)
            if game_moment is not None:due_intents(session,country_id,revision,game_moment,category=kind)

    # 2. Autonomy event bus (wars, attacks, alliances, intelligence, proposals) — already deduplicated by source key.
    from game.autonomy_models import AutonomyEvent
    for event in session.scalars(select(AutonomyEvent).where(AutonomyEvent.id>control.event_cursor).order_by(AutonomyEvent.id).limit(100)):
        control.event_cursor=event.id
        parties=set((event.payload or {}).get('parties') or [])|{event.actor_id,event.target_id}
        audience={event.private_country_id} if not event.public else parties
        other_names=names(session,[event.actor_id,event.target_id])
        for country_id in audience&set(identities):
            other=event.actor_id if event.actor_id!=country_id else event.target_id
            label=f"{event.kind}: {other_names.get(other,'państwo nieustalone') if other else 'sprawca nieustalony'}"
            if event.kind=='WAR':
                if event.actor_id==country_id:continue
                raise_task(session,country_id,'war_declared',f'event:{event.id}',revision,source='event',object_ref=event.id,context={'przeciwnik_id':other},merge_item=label)
                fire_conditional(session,country_id,'war_declared_by',other,revision,label)
            elif event.kind=='BOMBARDMENT' and event.target_id==country_id:
                raise_task(session,country_id,'under_attack',f'event:{event.id}',revision,source='event',object_ref=event.id,context={'napastnik_id':event.actor_id},merge_item=label)
                fire_conditional(session,country_id,'attacked_by',event.actor_id,revision,label)
            elif event.kind in ('ALLIANCE_FORMED','ALLIANCE_BROKEN'):raise_task(session,country_id,'alliance_change',f'event:{event.id}',revision,source='event',merge_item=label)
            elif event.kind=='RELATION_CHANGED' and event.actor_id!=country_id:raise_task(session,country_id,'relation_change',f'event:{event.id}',revision,source='event',merge_item=label)
            elif event.kind in ('HYBRID_DETECTED','UNATTRIBUTED_DAMAGE'):raise_task(session,country_id,'hybrid_detected',f'event:{event.id}',revision,source='event',merge_item=event.kind)
            elif event.kind=='INTELLIGENCE_REPORT':raise_task(session,country_id,'intelligence_report',f'event:{event.id}',revision,source='event',merge_item=label)
            elif event.kind=='DIPLOMATIC_PROPOSAL':
                action_id=(event.payload or {}).get('action_id')
                raise_task(session,country_id,'diplomatic_proposal',f'proposal:{action_id}',revision,source='event',object_ref=action_id,merge_item=label)

    # 3. Forum: addressed to us / replies to our posts / mentions of our name. AI-to-AI chains stay bounded.
    from game.forum_models import ForumMessage
    for message in session.scalars(select(ForumMessage).where(ForumMessage.id>control.forum_cursor).order_by(ForumMessage.id).limit(100)):
        control.forum_cursor=message.id
        targets={by_user[item.user_id] for item in message.addressees if item.user_id in by_user}
        parent=session.get(ForumMessage,message.reply_to_id) if message.reply_to_id else None
        if parent and parent.user_id in by_user:targets.add(by_user[parent.user_id])
        ai_parent=session.get(ForumMessage,parent.reply_to_id) if parent and parent.reply_to_id else None
        if message.user_id in by_user and parent and parent.user_id in by_user and ai_parent and ai_parent.user_id in by_user:continue
        for country_id in targets:
            if country_id!=message.panstwo_id:raise_task(session,country_id,'forum_reply',f'forum:{message.id}',revision,source='forum',object_ref=message.id)
        if message.user_id in by_user:continue  # AI posts never trigger mentions of other AI countries (no endless chains)
        lowered=(message.content or '').casefold()
        for country_id,name in country_names.items():
            if country_id in targets or country_id==message.panstwo_id or not name:continue
            if re.search(r'(?<!\w)'+re.escape(name.casefold())+r'(?!\w)',lowered):
                raise_task(session,country_id,'forum_mention',f'mention:{message.id}',revision,source='forum',object_ref=message.id)

    # 4. Private messages addressed to an AI identity.
    from game.communication_models import PrivateMessage
    for message in session.scalars(select(PrivateMessage).where(PrivateMessage.id>control.private_cursor).order_by(PrivateMessage.id).limit(100)):
        control.private_cursor=message.id
        if message.recipient_user_id not in by_user:continue
        if message.sender_user_id in by_user and message.reply_to_id:
            # AI-to-AI correspondence stays bounded: a reply to a reply between AI countries does not trigger another.
            parent=session.get(PrivateMessage,message.reply_to_id)
            if parent is not None and parent.reply_to_id is not None:continue
        raise_task(session,by_user[message.recipient_user_id],'private_message',f'private:{message.id}',revision,source='message',object_ref=message.id)

    # 5. Cheap periodic probes and the guaranteed strategic review cadence.
    for country_id,identity in identities.items():
        if review_due(identity,control,moment) and open_task(session,country_id,'strategic_review') is None:
            enqueue(session,country_id,'strategic_review',f'review:{moment:%Y-%m-%dT%H:%M}',revision,source='schedule')
        if identity.last_probe_at is not None and moment-identity.last_probe_at<timedelta(minutes=PROBE_MINUTES):continue
        identity.last_probe_at=moment
        probe(session,country_id,revision,game_moment)


def probe(session,country_id,revision,game_moment):
    """Selective own-country checks; each failure is isolated (a missing module never stops detection)."""
    from flask import current_app
    from game.paga_ai_strategy import due_intents
    def budget():
        from game.finance_models import StateBudget
        year,period=budget_period(session)
        if session.scalar(select(StateBudget.id).where(StateBudget.panstwo_id==country_id,StateBudget.game_year==year,StateBudget.period==period)) is None:
            key=f'budget:{year}/{period}'
            supersede(session,country_id,'budget',key)
            enqueue(session,country_id,'budget',key,revision,source='probe',context={'year':year,'period':period})
    def research():
        from game.research_models import ResearchAccount
        account=session.get(ResearchAccount,country_id)
        if account is not None and (account.points or 0)>0:
            year,period=budget_period(session)
            enqueue(session,country_id,'research_available',f'research:{year}/{period}',revision,source='probe',context={'punkty_badawcze':account.points})
    def intents():
        if game_moment is not None:due_intents(session,country_id,revision,game_moment)
    for name,check in (('budżet',budget),('badania',research),('zamiary',intents)):
        try:
            with session.begin_nested():check()
        except Exception as error:
            current_app.logger.debug('PAGA AI: sonda %s państwa %s: %s',name,country_id,error)
