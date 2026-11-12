"""Safe execution of state-changing player operations for one task.

* Write-ahead ledger: a row is committed BEFORE the player route is called. The same decision in the same task
  can never be executed twice; an unknown outcome is never replayed automatically (state is checked first).
* request_id derives from (task, decision), so game services with request idempotency also deduplicate.
* Outcomes are classified: OK, ALREADY_DONE, TECHNICAL, DECISION, SITUATION_CHANGED, PERMISSION, UNKNOWN.
* Technical prerequisites (reads/quotes needed for server-owned fields) are performed by ZEUS, not the model.
"""
import hashlib,json,re,unicodedata
from decimal import Decimal
from uuid import uuid5,NAMESPACE_URL
from sqlalchemy import select,true,delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from extensions import db
from game.paga_ai_models import PagaAiWrite,PagaAiIdentity
from game.paga_ai_tasks import now

CONTENT_OPERATIONS={'game_forum.page:POST','game_messages.send:POST','game_forum.edit:POST'}
TECHNICAL=re.compile(r'Najpierw odczytaj|Najpierw przelicz|wykonaj wycenę|Odczytaj formularz|Nie znaleziono wersji|tokenu|Brak aktualnego podglądu',re.I)
CHANGED=re.compile(r'zmienił|zmieniła|zmieniło|zmieniły|nieaktualn|Odśwież|wersj|już zakończon|nie istnieje|zniszczon|cena',re.I)


def canonical(value):
    if type(value) in (int,float):return {'n':str(Decimal(str(value)).normalize())}
    if isinstance(value,dict):return {key:canonical(item) for key,item in sorted(value.items()) if key!='rationale'}
    if isinstance(value,list):return [canonical(item) for item in value]
    return value


def decision_hash(operation,path,data):
    return hashlib.sha256(json.dumps(canonical([operation,path or {},data or {}]),sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def classify(response):
    """Map an executor response to the kind of follow-up it needs."""
    status=response.get('status',500);validation=response.get('validation','')
    reason=str(response.get('reason') or response.get('summary') or '')
    if validation=='ALREADY_DONE':return 'ALREADY_DONE'
    if status<400:return 'OK'
    if status==403:return 'PERMISSION'
    if status>=500 or validation=='UNCERTAIN':return 'UNKNOWN'
    if TECHNICAL.search(reason):return 'TECHNICAL'
    if status==409 and validation!='BLOCKED' and CHANGED.search(reason):return 'SITUATION_CHANGED'
    return 'DECISION'


def normalized_text(text):
    text=unicodedata.normalize('NFKC',str(text or '')).casefold()
    return re.sub(r'[^\w]+',' ',text).strip()


def duplicate_content(session,actor,operation,data,*,last=20):
    """Identical public or private text already sent by this country (any earlier task)."""
    if operation not in CONTENT_OPERATIONS:return None
    text=normalized_text(data.get('content'))
    if not text:return None
    from game.forum_models import ForumMessage
    from game.communication_models import PrivateMessage
    identity=session.get(PagaAiIdentity,actor.country_id)
    if identity is None:return None
    if operation=='game_messages.send:POST':
        recipient=PrivateMessage.recipient_user_id==data['recipient_id'] if type(data.get('recipient_id')) is int else true()
        rows=session.scalars(select(PrivateMessage.content).where(PrivateMessage.sender_user_id==identity.user_id,recipient).order_by(PrivateMessage.id.desc()).limit(last))
    else:
        rows=session.scalars(select(ForumMessage.content).where(ForumMessage.user_id==identity.user_id).order_by(ForumMessage.id.desc()).limit(last))
    return 'Ta sama treść została już wysłana przez nasze państwo. Napisz nową treść albo zrezygnuj z wiadomości.' if any(normalized_text(row)==text for row in rows) else None


def answered(session,actor,operation,data):
    """One reply per received message: a second reply to the same message needs a new cause (a new message)."""
    reply=data.get('reply_to_id')
    if not isinstance(reply,int) or operation not in ('game_messages.send:POST','game_forum.page:POST'):return None
    identity=session.get(PagaAiIdentity,actor.country_id)
    if identity is None:return None
    if operation=='game_messages.send:POST':
        from game.communication_models import PrivateMessage
        found=session.scalar(select(PrivateMessage.id).where(PrivateMessage.sender_user_id==identity.user_id,PrivateMessage.reply_to_id==reply))
    else:
        from game.forum_models import ForumMessage
        found=session.scalar(select(ForumMessage.id).where(ForumMessage.user_id==identity.user_id,ForumMessage.reply_to_id==reply))
    return f'Na wiadomość {reply} już odpowiedzieliśmy (#{found}). Nie odpowiadaj ponownie bez nowej wiadomości.' if found else None


# Reads/quotes ZEUS performs itself so that server-owned fields (price, version, level, quote) are available.
def prerequisites(operation,path,data):
    if operation=='game_finance.transfer:POST':return [('game_finance.page:GET',{}, {})]
    if operation=='game_research.change:POST' and data.get('action')=='buy':return [('game_research.state:GET',{},{})]
    if operation=='game_intelligence.change:POST' and data.get('action')=='counter_upgrade':return [('game_intelligence.state:GET',{},{})]
    if operation=='game_forum.edit:POST':return [('game_forum.edit:GET',path,{})]
    if operation=='game_infrastructure.roads_change:POST':
        kind=(path or {}).get('operation')
        quote={'buduj':'wycena','ulepsz':'ulepsz-wycena'}.get(kind)
        if kind=='decyzja' and data.get('decision')=='border':quote='granica-wycena'
        if quote:return [(operation,{'operation':quote},{k:v for k,v in data.items() if k not in ('rationale','decision')})]
    return []


WRITES_OFF_REASON='Wykonywanie operacji zmieniających stan gry przez AI jest wyłączone (PAGA_AUTONOMOUS_WRITES_ENABLED=false). Decyzja została zapisana, ale nie wykonana.'


def writes_refusal(actor,task_id,operation,model_id,parameters=None):
    """PAGA_AUTONOMOUS_WRITES_ENABLED gate for every model. Returns a refusal response (and records it in the PAGA
    audit history) when state-changing operations are switched off, otherwise None."""
    from game.paga_ai_providers import writes_enabled
    if writes_enabled():return None
    from game.paga_ai_models import PagaAiLog
    try:
        import game.finance_service as finance
        game_at=finance.game_now()
    except Exception:game_at=now()
    with Session(db.engine) as session,session.begin():
        session.add(PagaAiLog(job_id=task_id,country_id=actor.country_id,game_at=game_at,real_at=now(),operation=str(operation)[:150],parameters=parameters or {},
                              validation='WRITES_OFF',result=None,reason=WRITES_OFF_REASON,model_id=str(model_id or '')[:100]))
    return {'status':423,'validation':'WRITES_OFF','outcome':'WRITES_OFF','reason':WRITES_OFF_REASON,'summary':'Nie wykonano: '+WRITES_OFF_REASON,
            'observation':{'text':json.dumps({'error':WRITES_OFF_REASON},ensure_ascii=False)}}


def guarded_write(app,actor,task_id,operation,path,data,*,step,model_id,hash_extra=None):
    """Execute one state-changing player operation at most once per (task, decision).
    hash_extra binds a decision to what it confirms (e.g. the exact reviewed budget preview)."""
    from game.paga_ai_executor import execute
    refusal=writes_refusal(actor,task_id,operation,model_id,{'path':path or {},'data':data or {}})
    if refusal:return refusal
    digest=decision_hash(operation,path,{**(data or {}),**({'_bound_to':hash_extra} if hash_extra is not None else {})})
    with Session(db.engine) as session:
        known=session.scalar(select(PagaAiWrite.status).where(PagaAiWrite.job_id==task_id,PagaAiWrite.decision_hash==digest))
        # The ledger answers first: an already executed decision is 'done', not a 'duplicate text'.
        problem=None if known is not None else (answered(session,actor,operation,data) or duplicate_content(session,actor,operation,data))
    if problem:
        return {'status':409,'validation':'DUPLICATE','reason':problem,'summary':'Odrzucono: '+problem,'observation':{'text':json.dumps({'error':problem},ensure_ascii=False)}}
    request_id=str(uuid5(NAMESPACE_URL,f'paga-ai:{task_id}:{digest}'))
    try:
        with Session(db.engine) as session,session.begin():
            session.add(PagaAiWrite(job_id=task_id,country_id=actor.country_id,operation=operation[:150],decision_hash=digest,request_id=request_id,status='PENDING',created_at=now()))
    except IntegrityError:
        with Session(db.engine) as session,session.begin():
            row=session.scalar(select(PagaAiWrite).where(PagaAiWrite.job_id==task_id,PagaAiWrite.decision_hash==digest).with_for_update())
            previous=row.status if row is not None else None
            if previous=='REJECTED' and row.log_id is not None:
                # A rejected call made no game write. Only a newly observed state can reopen it;
                # UNKNOWN/PENDING and DONE remain strictly protected, with the original request_id.
                from game.paga_ai_models import PagaAiLog
                from game.paga_ai_retry import retry_state
                failed=session.get(PagaAiLog,row.log_id)
                before=(failed.result or {}).get('_retry_state') if failed is not None else None
                current,_,_=retry_state(actor,operation,{'path':path or {},'data':data or {}})
                if before and current!=before:previous='VERIFIED'
            if previous=='VERIFIED':
                # The model saw the fresh game state after an unknown outcome and decided again: same request_id,
                # so services with request idempotency still cannot apply it twice.
                row.status='PENDING';request_id=row.request_id
        if previous=='DONE':
            reason='Ta sama operacja została już wykonana w tym zadaniu. Nie powtarzaj jej.'
            return {'status':409,'validation':'ALREADY_DONE','reason':reason,'summary':'Cel już zrealizowany: '+reason,'observation':{'text':json.dumps({'error':reason},ensure_ascii=False)}}
        if previous=='REJECTED':
            reason='Ta sama decyzja została już odrzucona przy niezmienionym stanie. Zmień decyzję.'
            return {'status':409,'validation':'BLOCKED','reason':reason,'summary':'Odrzucono: '+reason,'observation':{'text':json.dumps({'error':reason},ensure_ascii=False)}}
        if previous!='VERIFIED':
            reason='Wynik wcześniejszego wykonania tej operacji jest nieznany. ZEUS nie powtarza zapisu: sprawdź aktualny stan gry i zdecyduj ponownie.'
            return {'status':409,'validation':'UNCERTAIN','reason':reason,'summary':'Wynik nieznany: '+reason,'observation':{'text':json.dumps({'error':reason},ensure_ascii=False)}}
    for index,(read_operation,read_path,read_data) in enumerate(prerequisites(operation,path,data)):
        execute(app,actor,{'operation_id':read_operation,'path':read_path,'data':read_data},step=step*10+index+1,model_id=model_id)
    response=execute(app,actor,{'operation_id':operation,'path':path,'data':data},step=step,model_id=model_id,request_id=request_id)
    outcome=classify(response)
    with Session(db.engine) as session,session.begin():
        if outcome in ('TECHNICAL','SITUATION_CHANGED','PERMISSION'):
            # Nothing was written by the game; the same decision may be tried again once conditions are fresh.
            session.execute(delete(PagaAiWrite).where(PagaAiWrite.request_id==request_id))
        else:
            row=session.scalar(select(PagaAiWrite).where(PagaAiWrite.request_id==request_id))
            row.status={'OK':'DONE','ALREADY_DONE':'DONE','UNKNOWN':'UNKNOWN'}.get(outcome,'REJECTED');row.finished_at=now();row.log_id=response.get('audit_id')
    response['outcome']=outcome
    return response


def unresolved_writes(session,task_id):
    return list(session.scalars(select(PagaAiWrite).where(PagaAiWrite.job_id==task_id,PagaAiWrite.status.in_(['PENDING','UNKNOWN']))))


def mark_verified(session,rows):
    """Called only after fresh game state is shown to the model together with the unknown outcome."""
    for row in rows:row.status='VERIFIED'
