"""Wyzwalacze trybu doraźnego PAGA2: powiadomienia gracza i wiadomości prywatne państwa (od ostatniego kursora)."""
import re
from sqlalchemy import select,func
from game.forum_models import GameNotification
from game.communication_models import PrivateMessage

SECURITY=('nuclear_strike','war_declared','land_invasion','under_attack','military_loss','occupation','annexation','hybrid_detected')
ORDER=SECURITY+('nuclear_research','diplomatic_proposal','private_message','forum_message','intelligence_report','military_report','loan_event','social_unrest',
                'energy_shortage','production_stopped','resource_event','trade_event','construction_completed','generated_event','system_notice')
LAND=[(re.compile(r'^Uderzenie atomowe:'),'nuclear_strike'),(re.compile(r'^Badania atomowe:'),'nuclear_research'),
      (re.compile(r'^Wtargnięcie:'),'land_invasion'),(re.compile(r'jest okupowany przez'),'occupation'),(re.compile(r'został anektowany przez'),'annexation'),
      (re.compile(r'^Okupacja regionu .* zakończona'),'military_report'),(re.compile(r'^Odbiliśmy|^Odzyskaliśmy'),'military_report')]
LABELS={'nuclear_strike':'uderzenie atomowe','nuclear_research':'badania nad bronią atomową','war_declared':'wypowiedzenie wojny','land_invasion':'najazd wojsk lądowych','under_attack':'atak zbrojny','military_loss':'straty wojskowe',
        'occupation':'okupacja regionu','annexation':'aneksja regionu','hybrid_detected':'działania hybrydowe','diplomatic_proposal':'propozycja dyplomatyczna',
        'private_message':'wiadomość prywatna','forum_message':'wpis na forum skierowany do państwa','generated_event':'wydarzenie z generatora zdarzeń'}


def classify(session,row):
    text=row.system_text or row.infrastructure_text or ''
    if row.notification_type=='FORUM_MESSAGE':return 'forum_message',text
    if row.notification_type=='DIPLOMACY':
        from game.diplomacy_models import DiplomaticAction
        action=session.get(DiplomaticAction,row.diplomatic_action_id) if row.diplomatic_action_id else None
        if action is None:return 'diplomatic_proposal',text
        if action.sender_user_id==row.user_id:return 'system_notice',f'{action.target_country_name}: odpowiedź na naszą propozycję {action.kind} — {action.status}'   # 14 Nov 2026: odpowiedź na własną propozycję
        return ('war_declared' if action.kind=='WAR' else 'diplomatic_proposal'),f'{action.source_country_name}: {action.kind}'
    if row.notification_type=='GENERATED_EVENT':return 'generated_event',text
    if row.notification_type=='INFRASTRUCTURE_COMPLETED':return 'construction_completed',text
    if row.notification_type=='SYSTEM':
        for pattern,kind in LAND:
            if pattern.search(text):return kind,text
        from game.paga_ai_detector import classify_text
        return classify_text(text) or 'system_notice',text
    return 'system_notice',text


def initial_cursors(session,country_id,user_id):
    """Nowe państwo PAGA2 zaczyna od bieżącego stanu skrzynki — bez odtwarzania historii."""
    return (session.scalar(select(func.max(GameNotification.id)).where(GameNotification.user_id==user_id)) or 0,
            session.scalar(select(func.max(PrivateMessage.id)).where(PrivateMessage.recipient_country_id==country_id)) or 0)


def collect(session,country_id,state,user_id,limit=100):
    triggers=[]
    for row in session.scalars(select(GameNotification).where(GameNotification.user_id==user_id,GameNotification.id>state.notification_cursor).order_by(GameNotification.id).limit(limit)):
        state.notification_cursor=row.id
        kind,text=classify(session,row)
        triggers.append({'kind':kind,'label':LABELS.get(kind,kind),'source':'powiadomienie','id':row.id,'text':(text or '')[:300]})
    for row in session.scalars(select(PrivateMessage).where(PrivateMessage.recipient_country_id==country_id,PrivateMessage.id>state.message_cursor).order_by(PrivateMessage.id).limit(limit)):
        state.message_cursor=row.id
        triggers.append({'kind':'private_message','label':LABELS['private_message'],'source':'wiadomość','id':row.id,'from':row.sender_country_id,'text':row.content[:300]})
    triggers.sort(key=lambda item:(ORDER.index(item['kind']) if item['kind'] in ORDER else len(ORDER),item['id']))
    return triggers


def security(triggers):return [item for item in triggers if item['kind'] in SECURITY]
