"""Shared transactional diplomacy for players and autonomous governments."""
from sqlalchemy import select,or_
from sqlalchemy.orm import lazyload
from extensions import db
from models import Panstwo,Stosunki,AudytStosunki,DictStosunkiRelacja,DictStosunkiStan
from game.models import GamePlayerCountry,GameUser,utc_now
from game.diplomacy_models import DiplomaticAction
from game.forum_models import GameNotification
from game.governance import controller_id
from services.natural_resources import normalized

class DiplomacyError(ValueError):
    def __init__(self,message,status=409):super().__init__(message);self.status=status

WAR_RELATIONS={'zle','napiete','wrogie','egzystencjalniewrogie'}
PACT_RELATIONS={'sojusznicze','partnerskiestrategiczne','partnerskie'}
# From worst to best; names, rather than database IDs, define quality.
RELATION_ORDER=('egzystencjalniewrogie','wrogie','napiete','zle','chlodne','neutralne','dobre','przyjazne','partnerskie','partnerskiestrategiczne','sojusznicze')

def relation_rank(relation):
    name=normalized(relation or '')
    if name not in RELATION_ORDER:raise DiplomacyError('Nieznany poziom relacji.',400)
    return RELATION_ORDER.index(name)

def is_worsening(current,proposed):
    return relation_rank(proposed)<relation_rank(current)


def can_declare_war(relation,state,kinetic_state):
    return normalized(relation or '') in WAR_RELATIONS and state!=kinetic_state


def is_pact(relation):
    return normalized(relation or '') in PACT_RELATIONS


def npc_eligible(session,country_id):
    from flask import current_app
    if not current_app.config.get("PAGA_ENABLED",False):return False
    from game.paga import PagaConfiguration
    country=session.execute(select(Panstwo.status,Panstwo.czy_suwerenny).where(Panstwo.PANSTWO_ID==country_id)).first()
    if country is None or country.status!='aktywne' or country.czy_suwerenny!='TAK':return False
    if session.scalar(select(GamePlayerCountry.id).where(GamePlayerCountry.panstwo_id==country_id)) is not None:return False
    # PAGA2: profil państwa jest źródłem flagi autonomii; bez profilu obowiązuje dotychczasowa konfiguracja PAGA.
    from game.paga2.models import Paga2Profile,table_ready
    if table_ready(session,Paga2Profile):
        profile=session.get(Paga2Profile,country_id)
        if profile is not None:return bool(profile.autonomy_enabled)
    config=session.get(PagaConfiguration,country_id)
    return bool(config and config.approved_at and config.autonomy_enabled)


def party_valid(session,country_id,user_id):
    if user_id is None:return npc_eligible(session,country_id)
    from game.paga_ai_actor import identity_country
    if identity_country(session,user_id)==country_id:return True
    return session.scalar(select(GamePlayerCountry.id).join(GameUser,GameUser.id==GamePlayerCountry.user_id).where(GamePlayerCountry.panstwo_id==country_id,GamePlayerCountry.user_id==user_id,GameUser.is_active.is_(True))) is not None


def dictionaries(session):
    relations=dict(session.execute(select(DictStosunkiRelacja.relacja_id,DictStosunkiRelacja.relacja_nazwa)).all())
    states={normalized(name):id for id,name in session.execute(select(DictStosunkiStan.stan_id,DictStosunkiStan.stan_nazwa))}
    neutral=next((id for id,name in relations.items() if normalized(name)=='neutralne'),None)
    if neutral is None or not all(states.get(key) for key in ('pokoj','wojnakinetyczna','zawieszeniebroni')):raise DiplomacyError('Brak wymaganych słowników dyplomacji.')
    return relations,states,neutral


def lock_pair(session,a,b):
    list(session.scalars(select(Panstwo.PANSTWO_ID).where(Panstwo.PANSTWO_ID.in_([a,b])).order_by(Panstwo.PANSTWO_ID).with_for_update()))


def pair_state(session,a,b,neutral,peace):
    a,b=sorted((a,b))
    row=session.scalar(select(Stosunki).where(Stosunki.PANSTWO_ID==a,Stosunki.PANSTWO_ID2==b).options(lazyload('*')).with_for_update().execution_options(populate_existing=True))
    revision=session.scalar(select(AudytStosunki.id).where(AudytStosunki.panstwo_id==a,AudytStosunki.panstwo_id2==b).order_by(AudytStosunki.id.desc()).limit(1).with_for_update()) or 0
    return row,row.relacja_id if row and row.relacja_id is not None else neutral,row.stan_id if row and row.stan_id is not None else peace,revision


def apply_change(session,row,a,b,relation,state,now):
    if row is not None:old_relation,old_state=row.relacja_id,row.stan_id
    else:
        _,states,neutral=dictionaries(session);old_relation,old_state=neutral,states['pokoj']
    if row is None:row=Stosunki(PANSTWO_ID=a,PANSTWO_ID2=b);session.add(row)
    row.relacja_id,row.stan_id=relation,state
    audit=AudytStosunki(panstwo_id=a,panstwo_id2=b,relacja_id=relation,stan_id=state,data_zmiany_entenda=now,data_zmiany_rzeczywista=utc_now())
    session.add(audit);session.flush()
    from game.diplomacy_news import record_change
    record_change(session,audit,old_relation,old_state)
    if relation!=old_relation:
        from game.base_permits import on_relation_change
        on_relation_change(session,a,b,session.scalar(select(DictStosunkiRelacja.relacja_nazwa).where(DictStosunkiRelacja.relacja_id==relation)))
    return audit.id


JOIN_RELATIONS={'sojusznicze','partnerskiestrategiczne'}   # prośba o dołączenie do wojny: sojusznik lub partner strategiczny


def lock_countries(session,ids):
    list(session.scalars(select(Panstwo.PANSTWO_ID).where(Panstwo.PANSTWO_ID.in_(sorted(set(ids)))).order_by(Panstwo.PANSTWO_ID).with_for_update()))


def at_war(session,a,b,states=None,neutral=None):
    if states is None:_,states,neutral=dictionaries(session)
    a,b=sorted((a,b))
    row=session.scalar(select(Stosunki).where(Stosunki.PANSTWO_ID==a,Stosunki.PANSTWO_ID2==b).options(lazyload('*')).execution_options(populate_existing=True))
    return row is not None and row.stan_id==states['wojnakinetyczna']


def joinable_wars(session,source,ally):
    """Wrogowie państwa source, z którymi sojusznik jeszcze nie walczy."""
    _,states,neutral=dictionaries(session);war=states['wojnakinetyczna']
    rows=session.execute(select(Stosunki.PANSTWO_ID,Stosunki.PANSTWO_ID2).where(or_(Stosunki.PANSTWO_ID==source,Stosunki.PANSTWO_ID2==source),Stosunki.stan_id==war)).all()
    enemies={b if a==source else a for a,b in rows}-{ally}
    return sorted(e for e in enemies if not at_war(session,ally,e,states,neutral))


def join_war_params(session,source,target,params):
    try:enemy=int((params or {}).get('enemy_id'))
    except (TypeError,ValueError):raise DiplomacyError('Wybierz wojnę, do której ma dołączyć sojusznik.',400)
    if enemy not in joinable_wars(session,source,target):raise DiplomacyError('Wybrana wojna nie trwa albo sojusznik już w niej walczy.')
    name=session.scalar(select(Panstwo.panstwo_nazwa).where(Panstwo.PANSTWO_ID==enemy))
    return {'enemy_id':enemy,'enemy_name':name}


def create_action(session,source,target,kind,proposed,now,*,sender_user_id=None,npc=False,dry_run=False,params=None):
    if kind not in ('WAR','PEACE','CEASEFIRE','RELATION','JOIN_WAR','BASE_PERMIT') or source==target or controller_id(session,target)!=target:raise DiplomacyError('Nieprawidłowa akcja lub państwo.',400)
    if kind=='BASE_PERMIT':
        from game.base_permits import permit_params
        params=permit_params(session,source,target,params)
    a,b=sorted((source,target))
    if kind=='JOIN_WAR':
        try:enemy=int((params or {}).get('enemy_id'))
        except (TypeError,ValueError):raise DiplomacyError('Wybierz wojnę, do której ma dołączyć sojusznik.',400)
        lock_countries(session,[a,b,enemy])
    else:lock_pair(session,a,b)
    if not party_valid(session,source,sender_user_id) or (npc and sender_user_id is not None):raise DiplomacyError('Przypisanie państwa uległo zmianie. Odśwież stronę.')
    recipient=session.scalar(select(GameUser.id).join(GamePlayerCountry,GamePlayerCountry.user_id==GameUser.id).where(GamePlayerCountry.panstwo_id==target,GameUser.is_active.is_(True)))
    from game.paga_ai_actor import configured
    if recipient is None and configured() and npc_eligible(session,target):
        from game.paga_ai_actor import ensure_identity
        recipient=ensure_identity(session,target).user_id
    relations,states,neutral=dictionaries(session)
    row,relation,state,revision=pair_state(session,a,b,neutral,states['pokoj'])
    if kind=='WAR' and not can_declare_war(relations.get(relation),state,states['wojnakinetyczna']):raise DiplomacyError('Wojnę można wypowiedzieć tylko przy relacjach: złe, napięte, wrogie lub egzystencjalnie wrogie, jeśli wojna kinetyczna jeszcze nie trwa.')
    if kind in ('PEACE','CEASEFIRE') and state!=states['wojnakinetyczna']:raise DiplomacyError('Ta propozycja wymaga trwającej wojny kinetycznej.')
    if kind=='RELATION' and (proposed not in relations or proposed==relation):raise DiplomacyError('Wybierz inną, prawidłową relację.',400)
    if kind=='JOIN_WAR':
        if normalized(relations.get(relation) or '') not in JOIN_RELATIONS:raise DiplomacyError('O dołączenie do wojny można prosić tylko sojusznika lub partnera strategicznego.')
        params=join_war_params(session,source,target,params)
    if kind=='BASE_PERMIT':
        from game.base_permits import PERMIT_RELATIONS
        if normalized(relations.get(relation) or '') not in PERMIT_RELATIONS:raise DiplomacyError('O pozwolenie na bazę można prosić tylko sojusznika.')
    if kind not in ('JOIN_WAR','BASE_PERMIT'):params=None
    breaking=kind=='RELATION' and is_worsening(relations.get(relation),relations.get(proposed))
    immediate=kind=='WAR' or breaking
    if session.scalar(select(Panstwo.status).where(Panstwo.PANSTWO_ID==target))!='aktywne':raise DiplomacyError('Państwo docelowe nie jest aktywne.',400)
    if not immediate and recipient is None and not npc_eligible(session,target):raise DiplomacyError('Państwo nie ma aktywnego gracza ani aktywnej autonomii.',400)
    pair=or_((DiplomaticAction.source_country_id==a)&(DiplomaticAction.target_country_id==b),(DiplomaticAction.source_country_id==b)&(DiplomaticAction.target_country_id==a))
    pending=[row for row in session.scalars(select(DiplomaticAction).where(DiplomaticAction.kind==kind,DiplomaticAction.status=='PENDING',pair))
             if kind not in ('JOIN_WAR','BASE_PERMIT') or row.source_country_id==source and (row.params or {})==(params or {})]
    if pending and not immediate:raise DiplomacyError('Taka propozycja już oczekuje na rozpatrzenie.')
    if dry_run:return None
    names=dict(session.execute(select(Panstwo.PANSTWO_ID,Panstwo.panstwo_nazwa).where(Panstwo.PANSTWO_ID.in_([source,target]))).all())
    if immediate:
        for old in session.scalars(select(DiplomaticAction).where(pair,DiplomaticAction.status=='PENDING').with_for_update()):old.status='EXPIRED';old.decided_at=utc_now()
    action=DiplomaticAction(sender_user_id=sender_user_id,recipient_user_id=recipient,source_country_id=source,target_country_id=target,source_country_name=names[source],target_country_name=names[target],kind=kind,status='APPLIED' if immediate else 'PENDING',proposed_relation_id=proposed if kind=='RELATION' else None,params=params,expected_relation_id=relation,expected_state_id=state,expected_audit_id=revision,decided_at=utc_now() if immediate else None)
    session.add(action)
    action.autonomy_audit_id=apply_change(session,row,a,b,proposed if breaking else relation,states['wojnakinetyczna'] if kind=='WAR' else state,now) if immediate else None
    session.flush()
    from flask import current_app
    if action.autonomy_audit_id and current_app.config.get('AUTONOMY_ENABLED'):
        from game.autonomy_memory import link_source
        link_source(session,'audit',action.autonomy_audit_id,source,target,{'previous_relation':relation,'previous_state':state})
    if recipient is not None:session.add(GameNotification(user_id=recipient,diplomatic_action_id=action.id,notification_type='DIPLOMACY',created_at=action.created_at))
    return action


def decide_action(session,action_id,country_id,accept,now,*,user_id=None,dry_run=False):
    action=session.get(DiplomaticAction,action_id)
    from game.paga_ai_actor import identity_country
    if action and action.recipient_user_id is None and identity_country(session,user_id)==country_id:user_id=None
    if action is None or action.target_country_id!=country_id or action.recipient_user_id!=user_id:raise DiplomacyError('Nie znaleziono propozycji.',404)
    a,b=sorted((action.source_country_id,action.target_country_id))
    if action.kind=='JOIN_WAR':lock_countries(session,[a,b,(action.params or {}).get('enemy_id') or a])
    else:lock_pair(session,a,b)
    session.refresh(action,with_for_update=True)
    if action.status!='PENDING':raise DiplomacyError('Propozycja została już rozpatrzona lub jest nieaktualna.')
    _,states,neutral=dictionaries(session);row,relation,state,revision=pair_state(session,a,b,neutral,states['pokoj'])
    valid=party_valid(session,action.source_country_id,action.sender_user_id) and party_valid(session,action.target_country_id,action.recipient_user_id)
    if not valid or (relation,state,revision)!=(action.expected_relation_id,action.expected_state_id,action.expected_audit_id):
        if not dry_run:action.status='EXPIRED';action.decided_at=utc_now()
        return 'EXPIRED'
    if action.kind=='JOIN_WAR' and (action.params or {}).get('enemy_id') not in joinable_wars(session,action.source_country_id,action.target_country_id):
        if not dry_run:action.status='EXPIRED';action.decided_at=utc_now()
        return 'EXPIRED'
    if action.kind=='BASE_PERMIT':
        from game.base_permits import permit_valid
        if not permit_valid(session,action):
            if not dry_run:action.status='EXPIRED';action.decided_at=utc_now()
            return 'EXPIRED'
    if dry_run:return 'VALID'
    action.autonomy_audit_id=None
    if accept and action.kind=='JOIN_WAR':action.autonomy_audit_id=join_war(session,action,relations_by_name(session),states,neutral,now)
    elif accept and action.kind=='BASE_PERMIT':
        from game.base_permits import grant
        grant(session,action,now)
    elif accept:action.autonomy_audit_id=apply_change(session,row,a,b,action.proposed_relation_id if action.kind=='RELATION' else relation,states['pokoj'] if action.kind=='PEACE' else states['zawieszeniebroni'] if action.kind=='CEASEFIRE' else state,now)
    from flask import current_app
    if action.autonomy_audit_id and current_app.config.get('AUTONOMY_ENABLED'):
        from game.autonomy_memory import link_source
        link_source(session,'audit',action.autonomy_audit_id,action.source_country_id,action.target_country_id,{'previous_relation':relation,'previous_state':state})
    action.status='ACCEPTED' if accept else 'REJECTED';action.decided_at=utc_now()
    if not accept:
        from game.diplomacy_news import record_rejection
        record_rejection(session,action,now)
    if action.sender_user_id is not None and (user_id is None or action.kind in ('JOIN_WAR','BASE_PERMIT')):session.add(GameNotification(user_id=action.sender_user_id,diplomatic_action_id=action.id,notification_type='DIPLOMACY',created_at=utc_now()))
    return action.status


def relations_by_name(session):
    return {normalized(name):id for id,name in session.execute(select(DictStosunkiRelacja.relacja_id,DictStosunkiRelacja.relacja_nazwa))}


def join_war(session,action,by_name,states,neutral,now):
    """Zgoda sojusznika: stan wojny kinetycznej z wrogiem proszącego (relacja co najmniej wroga)."""
    ally,enemy=action.target_country_id,action.params['enemy_id']
    relations=dict(session.execute(select(DictStosunkiRelacja.relacja_id,DictStosunkiRelacja.relacja_nazwa)).all())
    a,b=sorted((ally,enemy));row,relation,state,_=pair_state(session,a,b,neutral,states['pokoj'])
    if normalized(relations.get(relation) or '') not in WAR_RELATIONS:relation=by_name['wrogie']
    audit=apply_change(session,row,a,b,relation,states['wojnakinetyczna'],now)
    from flask import current_app
    if current_app.config.get('AUTONOMY_ENABLED'):
        from game.autonomy_memory import link_source
        link_source(session,'audit',audit,ally,enemy,{'previous_relation':relation,'previous_state':state})
    enemy_user=session.scalar(select(GameUser.id).join(GamePlayerCountry,GamePlayerCountry.user_id==GameUser.id).where(GamePlayerCountry.panstwo_id==enemy,GameUser.is_active.is_(True)))
    if enemy_user is not None:
        session.add(GameNotification(user_id=enemy_user,notification_type='SYSTEM',created_at=utc_now(),
            system_text=f'Państwo {action.target_country_name} dołączyło do wojny po stronie państwa {action.source_country_name} i jest z Tobą w stanie wojny.'))
    return audit


def expire_unanswerable(session,now=None):
    """Propozycje do państw bez aktywnego gracza i bez autonomii (np. autonomię wyłączono po wysłaniu) nie mogą zostać
    rozpatrzone — wygasają, a nadawca dostaje powiadomienie (12 Nov 2026)."""
    from game.models import utc_now
    from game.diplomacy_models import DiplomaticAction
    rows=list(session.scalars(select(DiplomaticAction).where(DiplomaticAction.status=='PENDING',DiplomaticAction.kind.in_(['RELATION','PEACE','CEASEFIRE','JOIN_WAR','BASE_PERMIT'])).with_for_update()))
    expired=0
    for action in rows:
        human=session.scalar(select(GameUser.id).join(GamePlayerCountry,GamePlayerCountry.user_id==GameUser.id).where(GamePlayerCountry.panstwo_id==action.target_country_id,GameUser.is_active.is_(True)))
        if human is not None or npc_eligible(session,action.target_country_id):continue
        action.status='EXPIRED';action.decided_at=utc_now();expired+=1
        if action.sender_user_id:
            session.add(GameNotification(user_id=action.sender_user_id,notification_type='SYSTEM',created_at=utc_now(),
                system_text=f'Propozycja dla państwa {action.target_country_name} wygasła: państwo nie ma aktywnego gracza ani autonomicznego zarządzania.'))
    return expired
