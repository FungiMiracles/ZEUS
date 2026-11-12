"""Server-only actor context. No browser header/cookie can create an AI principal."""
from contextvars import ContextVar
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime,timezone
from sqlalchemy import select,event
from sqlalchemy.orm import Session,lazyload
from flask import current_app
from game.paga_ai_models import PagaAiControl,PagaAiIdentity
from game.models import GameUser,GamePlayerCountry
from models import Panstwo

class AiPermissionError(ValueError):pass
@dataclass(frozen=True)
class AiActor:
    country_id:int
    user_id:int
    revision:int
    job_id:int|None=None
    engine:str='llm'   # 'paga2' = algorytm PAGA2 (bez LLM), autoryzowany własnym wyłącznikiem
_actor=ContextVar('paga_ai_actor',default=None)
def current_actor():return _actor.get()

def configured():return current_app.config.get('ENV_NAME')=='UAT' and current_app.config.get('PAGA_AI_CONFIGURED',False)

def authorized(session,actor,*,lock=False):
    if not configured():raise AiPermissionError('AI jest dostępna wyłącznie w ZEUS_UAT.')
    if actor.engine=='paga2_view':
        pass  # Podgląd: tylko odczyty ekranów gracza (bramka PAGA2 blokuje operacje), bez wymogu włączonego PAGA2.
    elif actor.engine=='paga2':
        from game.paga2.models import Paga2Control
        query=select(Paga2Control).where(Paga2Control.id==1).execution_options(populate_existing=True)
        if lock:query=query.with_for_update()
        control=session.scalar(query)
        if control is None or not control.enabled or control.revision!=actor.revision:raise AiPermissionError('PAGA2 wyłączono albo zmieniono jego konfigurację.')
    else:
        query=select(PagaAiControl).where(PagaAiControl.id==1).execution_options(populate_existing=True)
        if lock:query=query.with_for_update()
        control=session.scalar(query)
        if control is None or not control.enabled or control.revision!=actor.revision:raise AiPermissionError('Autonomiczne zarządzanie AI wyłączono albo zmieniono jego uprawnienia.')
    if lock:session.scalar(select(Panstwo.PANSTWO_ID).where(Panstwo.PANSTWO_ID==actor.country_id).with_for_update())
    identity=session.get(PagaAiIdentity,actor.country_id,populate_existing=True)
    from game.diplomacy_service import npc_eligible
    from game.paga import PagaConfiguration
    if lock:session.scalar(select(PagaConfiguration).where(PagaConfiguration.panstwo_id==actor.country_id).with_for_update().execution_options(populate_existing=True))
    if identity is None or identity.user_id!=actor.user_id or not npc_eligible(session,actor.country_id):raise AiPermissionError('Państwo ma gracza albo wyłączono jego PAGA.')
    from game.sovereignty import lost
    if lost(session,actor.country_id) is not None:raise AiPermissionError('Państwo utraciło suwerenność po aneksji zbrojnej.')
    user=session.get(GameUser,actor.user_id,populate_existing=True)
    if user is None or not user.is_active or user.password_hash is not None or user.email is not None:raise AiPermissionError('Nieprawidłowa tożsamość techniczna AI.')
    return session.scalar(select(Panstwo).options(lazyload('*')).where(Panstwo.PANSTWO_ID==actor.country_id))

def assigned_country(session,user_id,*,lock=False):
    actor=current_actor()
    if actor is None:return None
    if actor.user_id!=user_id:raise AiPermissionError('AI nie może podszyć się pod innego gracza.')
    return authorized(session,actor,lock=lock)

@contextmanager
def acting(actor):
    token=_actor.set(actor)
    try:yield
    finally:_actor.reset(token)

@event.listens_for(Session,'before_commit')
def guard_commit(session):
    actor=current_actor()
    if actor is not None:authorized(session,actor,lock=True)

def ensure_identity(session,country_id):
    identity=session.get(PagaAiIdentity,country_id)
    if identity:return identity
    # This is a non-login author identity; NEVER create GamePlayerCountry for it.
    country=session.scalar(select(Panstwo).options(lazyload('*')).where(Panstwo.PANSTWO_ID==country_id).with_for_update())
    from game.diplomacy_service import npc_eligible
    if not country or not npc_eligible(session,country_id):raise AiPermissionError('Państwo nie jest dostępne dla AI.')
    user=GameUser(username=country.panstwo_nazwa[:43]+' (PAGA)',username_normalized=f'__paga_ai_{country_id}_'+__import__('secrets').token_hex(6),email=None,email_normalized=None,password_hash=None,is_active=True)
    session.add(user);session.flush()
    identity=PagaAiIdentity(country_id=country_id,user_id=user.id,memory='',next_at=datetime.now(timezone.utc).replace(tzinfo=None));session.add(identity);session.flush();return identity

def identity_country(session,user_id):
    if not configured():return None
    identity=session.scalar(select(PagaAiIdentity).where(PagaAiIdentity.user_id==user_id))
    if identity is None:return None
    from game.diplomacy_service import npc_eligible
    return identity.country_id if npc_eligible(session,identity.country_id) else None

def country_user_id(session,country_id):
    """Resolve the same country inbox for human players and non-login AI identities."""
    human=session.scalar(select(GamePlayerCountry.user_id).join(GameUser,GameUser.id==GamePlayerCountry.user_id).where(GamePlayerCountry.panstwo_id==country_id,GameUser.is_active.is_(True)))
    if human is not None or not configured():return human
    from game.diplomacy_service import npc_eligible
    if not npc_eligible(session,country_id):return None
    identity=session.get(PagaAiIdentity,country_id)
    return identity.user_id if identity else None
