"""Pamięć państwa PAGA2: własne decyzje, zmiany relacji i działania innych państw wobec niego.

Źródłem zdarzeń jest wspólny dziennik game_autonomy_events z zachowaniem widoczności:
państwo widzi zdarzenia jawne i wyłącznie własne zdarzenia niejawne.
"""
from datetime import timedelta
from sqlalchemy import select,or_
from game.autonomy_models import AutonomyEvent as Event,AutonomyAssessment as Assessment
from game.paga2.models import Paga2Decision

RELATION_KINDS=('RELATION_CHANGED','ALLIANCE_FORMED','ALLIANCE_BROKEN','WAR')
HOSTILE_KINDS=('WAR','BOMBARDMENT','HYBRID_DETECTED','UNATTRIBUTED_DAMAGE','LAND_ATTACK','RECAPTURE_ATTACK','OCCUPATION','ANNEXATION')


def visible_events(session,country_id,*,since=None,limit=200):
    query=select(Event).where(or_(Event.public.is_(True),Event.private_country_id==country_id))
    if since is not None:query=query.where(Event.occurred_at>=since)
    return list(session.scalars(query.order_by(Event.id.desc()).limit(limit)))


def _event(event):
    return {'id':event.id,'kind':event.kind,'actor':event.actor_id,'target':event.target_id,'at':event.occurred_at.isoformat() if event.occurred_at else None,
            'parties':event.payload.get('parties'),'relation':event.payload.get('relation'),'state':event.payload.get('state'),
            'object':event.payload.get('target'),'won':event.payload.get('won')}


def recall(session,country_id,now,*,days=365,decisions=50):
    since=now-timedelta(days=days) if now else None
    events=visible_events(session,country_id,since=since)
    involved=lambda e:country_id in (e.payload.get('parties') or [e.actor_id,e.target_id])
    own=list(session.scalars(select(Paga2Decision).where(Paga2Decision.country_id==country_id,Paga2Decision.status=='EXECUTED').order_by(Paga2Decision.id.desc()).limit(decisions)))
    perception={other:{'trust':row.trust,'threat':row.threat,'confidence':row.confidence} for other,row in
                ((row.other_id,row) for row in session.scalars(select(Assessment).where(Assessment.country_id==country_id)))}
    return {
        'own_decisions':[{'id':d.id,'domain':d.domain,'action':d.action,'target':d.target_id,'at':d.game_at.isoformat() if d.game_at else None,'score':d.score} for d in own],
        'relation_changes':[_event(e) for e in events if e.kind in RELATION_KINDS and involved(e)],
        'actions_against_us':[_event(e) for e in events if e.target_id==country_id and e.actor_id not in (None,country_id) and e.kind in HOSTILE_KINDS+('DIPLOMATIC_PROPOSAL',)],
        'world_conflicts':[_event(e) for e in events if e.kind in ('WAR','BOMBARDMENT','LAND_ATTACK','RECAPTURE_ATTACK') and not involved(e)][:30],
        'perception':perception,
    }


def history_with(session,country_id,other_id,now,*,days=365):
    """Historia działań wobec konkretnego państwa (do punktacji decyzji)."""
    since=now-timedelta(days=days) if now else None
    events=[e for e in visible_events(session,country_id,since=since,limit=500) if {e.actor_id,e.target_id}=={country_id,other_id}]
    hostile_from=sum(1 for e in events if e.actor_id==other_id and e.kind in HOSTILE_KINDS)
    hostile_to=sum(1 for e in events if e.actor_id==country_id and e.kind in HOSTILE_KINDS)
    friendly=sum(1 for e in events if e.kind=='ALLIANCE_FORMED')
    return {'hostile_from':hostile_from,'hostile_to':hostile_to,'friendly':friendly,'events':[_event(e) for e in events[:20]]}


def executed_actions(session,country_id,since=None,limit=300):
    """Wszystkie wykonane działania (także kilka w jednym przebiegu): [(akcja, cel, data gry)]."""
    query=select(Paga2Decision).where(Paga2Decision.country_id==country_id,Paga2Decision.status=='EXECUTED')
    if since is not None:query=query.where(Paga2Decision.game_at>=since)
    result=[]
    for row in session.scalars(query.order_by(Paga2Decision.id.desc()).limit(limit)):
        for item in (row.result or {}).get('wykonane',[]):
            result.append((item.get('action'),item.get('target'),row.game_at))
    return result
