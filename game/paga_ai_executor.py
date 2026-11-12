"""Execute catalogue operations through the actual human-player Flask handlers."""
import json,math,secrets
from uuid import uuid5,NAMESPACE_URL
from flask import current_app,template_rendered
from sqlalchemy import select
from sqlalchemy.orm import Session
from extensions import db
from game.paga_ai_actor import acting,authorized,AiPermissionError
from game.paga_ai_models import PagaAiLog
from game.paga_ai_observation import observe_response,scrub,window
from game.player_operations import catalogue,FORBIDDEN_KEYS
from game.finance_service import game_now

def check_schema(value,schema,path='parametry',depth=0):
    if depth>15:raise ValueError('Zbyt głębokie parametry.')
    types=schema.get('type',[]);types=[types] if isinstance(types,str) else types
    actual='null' if value is None else 'boolean' if type(value) is bool else 'integer' if type(value) is int else 'number' if type(value) is float and math.isfinite(value) else 'string' if type(value) is str else 'array' if isinstance(value,list) else 'object' if isinstance(value,dict) else 'invalid'
    if types and actual not in types and not(actual=='integer' and 'number' in types):raise ValueError(f'{path}: nieprawidłowy typ danych.')
    if 'enum' in schema and value not in schema['enum']:raise ValueError(f'{path}: niedozwolona wartość.')
    if isinstance(value,dict):
        if len(value)>100:raise ValueError('Za dużo pól.')
        for key in schema.get('required',[]):
            if key not in value:raise ValueError(f'{path}: wymagane pole {key}.')
        for key,item in value.items():
            if key in FORBIDDEN_KEYS:raise ValueError('Niedozwolone pole tożsamości lub uprawnień.')
            if schema.get('additionalProperties') is False and key not in schema.get('properties',{}):raise ValueError('Nieznany parametr ścieżki.')
            child=schema.get('properties',{}).get(key,schema.get('additionalProperties',{}));check_schema(item,child if isinstance(child,dict) else {},path+'.'+key,depth+1)
    if isinstance(value,list):
        if len(value)>1000:raise ValueError('Za długa lista.')
        for item in value:check_schema(item,schema.get('items',{}),path,depth+1)
    if isinstance(value,str) and len(value)>10000:raise ValueError('Za długi parametr.')

class GoalCompleted(Exception):
    """The requested goal is already achieved in the visible game state; nothing is executed."""
    def __init__(self,goal):super().__init__(goal['message']);self.goal=goal

def player_budget_state(app,actor):
    """Read the current half-year exactly as a player does (read-only preview of the default plan)."""
    token=secrets.token_urlsafe(32)
    with acting(actor),app.test_client() as client:
        with client.session_transaction() as browser:
            browser['game_user_id']=actor.user_id;browser['game_csrf_token']=token
        response=client.post('/game/finanse/podglad',json={},headers={'X-CSRF-Token':token})
    return response.get_json().get('state') if response.status_code==200 and response.is_json else None

def brief(operation,status,validation,result,reason):
    """One line for the in-job journal: what happened, never technical fields."""
    if validation=='ALREADY_DONE' or (isinstance(result,dict) and result.get('completed_goal')):
        goal=result.get('completed_goal') or {}
        return f"Cel już zrealizowany: budżet {goal.get('year')}/{goal.get('period')} zatwierdzony (budget_id {goal.get('budget_id')})."
    if status>=400:return 'Odrzucono: '+str(reason or '')[:160]
    if operation=='game_finance.approve:POST' and isinstance(result,dict) and result.get('budget_id'):
        return f"Zatwierdzono budżet (budget_id {result['budget_id']}). Cel budżetu półrocza zrealizowany."
    if operation=='game_finance.preview:POST':return 'Przeliczono podgląd planu; oceń go i zatwierdź albo popraw.'
    if operation=='finish':return 'Zakończono analizę.'
    if operation.endswith(':GET') or operation.startswith('operations.'):return 'Odczytano dane.'
    return 'Wykonano operację gracza.'

def require_loan_capacity(actor,loan_id):
    """PAGA2 liczy, czy państwo stać na udzielenie pożyczki; model decyduje wyłącznie w tych granicach (11 Nov 2026)."""
    from game.paga_ai_tasks import legacy_engines
    if legacy_engines() or type(loan_id) is not int:return
    from game.loan_models import StateLoan
    from game.paga2.models import Paga2Profile,table_ready
    from game.paga2.finance import loan_capacity
    from game.finance_service import game_now
    with Session(db.engine) as session:
        if not table_ready(session,Paga2Profile) or session.get(Paga2Profile,actor.country_id) is None:return
        loan=session.get(StateLoan,loan_id)
        if loan is None or loan.lender_id!=actor.country_id:return  # zwykła walidacja gry obsłuży błędny numer
        capacity=loan_capacity(session,actor.country_id,game_now())
    if float(loan.amount)>capacity['max_loan']:
        raise ValueError(f'Kwota pożyczki {float(loan.amount):,.0f} ROI przekracza zdolność pożyczkową państwa wyliczoną przez PAGA2 '
                         f'({capacity["max_loan"]:,.0f} ROI). Odrzuć wniosek albo nie podejmuj działania.'.replace(',',' '))


def execute(app,actor,command,*,step=0,model_id='Qwen3.5-4B-Q4_K_M',audit=True,request_id=None):
    operation=command.get('operation_id','') if isinstance(command,dict) else '';parameters={};result=None;status=400;validation='REJECTED';reason=None;budget_plan=None;retry_fingerprint=None;retry_command=None
    completed=False
    try:
        if not isinstance(command,dict) or set(command)-{'operation_id','path','data','offset'}:raise ValueError('Nieprawidłowa struktura dyspozycji.')
        if not isinstance(operation,str) or len(operation)>150:raise ValueError('Nieprawidłowy identyfikator operacji.')
        with Session(db.engine) as session:authorized(session,actor)
        operations=catalogue(app)
        data=command.get('data',{});path=command.get('path',{})
        check_schema(data,{'type':'object'});check_schema(path,{'type':'object'})
        parameters={'path':path,'data':data}
        if operation=='operations.list':
            module=data.get('module','');page=data.get('page',1)
            if not isinstance(module,str) or type(page) is not int or page<1:raise ValueError('Nieprawidłowy filtr katalogu.')
            items=[{'id':op.id,'description':op.description} for op in operations.values() if not module or op.endpoint.split('.')[0]==module]
            result={'items':items[(page-1)*6:page*6],'page':page,'next_page':page+1 if len(items)>page*6 else None};status=200
        elif operation=='operations.result':
            if type(data.get('id')) is not int:raise ValueError('Podaj identyfikator wyniku.')
            with Session(db.engine) as session:
                row=session.scalar(select(PagaAiLog).where(PagaAiLog.id==data['id'],PagaAiLog.country_id==actor.country_id))
                if row is None:raise ValueError('Nie znaleziono własnego wyniku.')
                result=row.result;status=200
        elif operation=='operations.describe':
            target=operations.get(data.get('id'))
            if target is None:raise ValueError('Nieznana operacja.')
            result=target.public();status=200
        else:
            op=operations.get(operation)
            if op is None:raise ValueError('Operacja niedostępna graczowi.')
            if op.method!='GET' and command.get('offset',0):raise ValueError('Do dalszych stron wyniku zapisu użyj operations.result z identyfikatorem audit_id. Nie ponawiaj zapisu.')
            from game.paga_ai_retry import retry_state
            from game.paga_ai_budget import APPROVE as _APPROVE,completed_budget
            if operation==_APPROVE:
                # Checked before the duplicate guard: a finished goal is reported as finished, not as an error to retry.
                goal=completed_budget(player_budget_state(app,actor))
                if goal:raise GoalCompleted(goal)
            if op.method!='GET':
                retry_fingerprint,retry_command,previous_error=retry_state(actor,operation,parameters)
                if previous_error:
                    validation='BLOCKED';status=409
                    raise ValueError('Powtórzona odrzucona decyzja bez zmiany danych lub zaobserwowanego stanu. Popraw parametry albo odczytaj zmieniony stan. Poprzedni błąd: '+previous_error)
            check_schema(path,op.path_schema);check_schema(data,op.input_schema)
            if operation=='game_loans.change:POST' and data.get('action')=='accept':require_loan_capacity(actor,data.get('loan_id'))
            from game.paga_ai_budget import PREVIEW,APPROVE,approval_payload,comparison,summary,prepare_intent
            payload=approval_payload(actor,data) if operation==APPROVE else prepare_intent(data) if operation==PREVIEW else {k:v for k,v in data.items() if k!='rationale'}
            from game.paga_ai_quotes import prepare
            payload=prepare(actor,operation,path,payload)
            if op.method!='GET':payload['request_id']=request_id or str(uuid5(NAMESPACE_URL,f'paga-ai:{actor.job_id}:{step}:{operation}'))
            endpoint=app.url_map.bind('').build(op.endpoint,path,method=op.method)
            if not endpoint.startswith('/game/'):raise ValueError('Operacja poza grą.')
            token=secrets.token_urlsafe(32)
            with acting(actor),app.test_client() as client:
                with client.session_transaction() as browser:
                    browser['game_user_id']=actor.user_id;browser['game_csrf_token']=token
                kwargs={'headers':{'X-CSRF-Token':token}}
                if op.method=='GET':kwargs['query_string']=payload
                elif op.encoding=='form':kwargs['data']={**payload,'csrf_token':token}
                else:kwargs['json']=payload
                baseline=None
                if operation==PREVIEW:
                    baseline_response=client.post('/game/finanse/podglad',json={},headers=kwargs['headers'])
                    if baseline_response.is_json and baseline_response.status_code==200:
                        baseline=baseline_response.get_json().get('state')
                captured={}
                def rendered(sender,template,context,**extra):
                    from game.paga_ai_actor import current_actor
                    if current_actor()==actor and isinstance(context.get('error'),str):captured['form_error']=context['error']
                    if current_actor()==actor and 'finance_state' in context:
                        captured.update(state=context['finance_state'],categories=context.get('finance_categories',[]),error=context.get('finance_error'),history=context.get('finance_history',[]))
                with template_rendered.connected_to(rendered,app):
                    response=client.open(endpoint,method=op.method,follow_redirects=False,**kwargs)
                status=response.status_code;result=observe_response(response)
                if status>=400 and captured.get('form_error'):result={**result,'error':captured['form_error']}
                if operation=='game_finance.page:GET' and captured:
                    result={'state':summary(captured['state'] or {}),'categories':captured['categories'],'error':captured['error'],
                            'guidance':'Stawki i udziały w procentach. Najpierw preview z planem i uzasadnieniem, potem approve z uzasadnieniem; ZEUS dobiera okres i token.'}
                    goal=completed_budget(captured['state'])
                    if goal:result['completed_goal']=goal;result['guidance']='Budżet tego półrocza jest zatwierdzony. Możesz analizować dane lub przesuwać środki zwykłymi operacjami, ale nie zatwierdzaj budżetu ponownie.'
                if operation==PREVIEW and status==200:
                    state=response.get_json().get('state',{})
                    goal=completed_budget(state)
                    if goal:result={'completed_goal':goal,'state':{key:state.get(key) for key in ('approved','budget_id','year','period')}}
                    if not state.get('approved'):
                        payments=payload.get('benefits',{})
                        if 'benefit_policy' in data:
                            from game.paga_ai_budget import policy_payments
                            payments=policy_payments(state,data['benefit_policy'])
                        repeat=bool(data.get('repeat_previous',False))
                        if repeat:
                            # Read the same previous-budget details a human can open; do not infer payments from allocations.
                            with template_rendered.connected_to(rendered,app):
                                previous_page=client.get('/game/finanse')
                            if previous_page.status_code!=200:raise ValueError('Nie udało się odczytać historii wypłat. Wybierz jawny nowy plan.')
                            previous=next((row for row in captured.get('history',[]) if row.get('budget_id') and (row['year'],row['period'])<(state['year'],state['period'])),None)
                            if previous is None:raise ValueError('Brak zatwierdzonego poprzedniego planu. Wybierz nowy budżet.')
                            with template_rendered.connected_to(rendered,app):
                                previous_response=client.get('/game/finanse/historia/'+str(previous['budget_id']))
                            if previous_response.status_code!=200:raise ValueError('Nie udało się odczytać poprzednich wypłat. Wybierz jawny nowy plan.')
                            previous_state=previous_response.get_json().get('state',{}) if previous_response.is_json else captured.get('state') or {}
                            payments=previous_state.get('benefits',{}).get('paid',{})
                        budget_plan={'state':state,'baseline':baseline,'payments':payments,'repeat_previous':repeat}
                        result=comparison(state,baseline,payments,repeat)
                        if 'benefit_policy' in data:result['chosen_benefit_policy']=data['benefit_policy']

            validation='EXECUTED' if status<400 else 'REJECTED'
            if status>=400:
                if status==404 and not (isinstance(result,dict) and result.get('error')):
                    # An HTML 404 carries no game message: tell the model the referenced object does not exist.
                    reason='Nie znaleziono wskazanego obiektu. Sprawdź identyfikator (np. reply_to_id, message_id, loan_id, base_id) w danych zadania.'
                    result={'error':reason}
                else:reason=str(result.get('error','Odrzucono przez standardową walidację ZEUS.'))[:500] if isinstance(result,dict) else 'Odrzucono przez standardową walidację ZEUS.'
        if operation.startswith('operations.'):validation='ACCEPTED'
    except GoalCompleted as done:
        completed=True;validation='ALREADY_DONE';status=409;reason=str(done)[:500]
        result={'error':reason,'completed_goal':done.goal}
    except (ValueError,TypeError,KeyError,AiPermissionError) as error:
        reason=str(error)[:500];result={'error':reason};status=403 if isinstance(error,AiPermissionError) else 409 if validation=='BLOCKED' else 400
    except Exception:
        current_app.logger.exception('PAGA AI: błąd operacji państwa %s',actor.country_id)
        reason='Operacja przerwana. Odczytaj stan gry przed nową dyspozycją.';result={'error':reason};status=503;validation='UNCERTAIN'
    summary_line=brief(operation,status,validation,result,reason)
    if status>=400 and isinstance(result,dict) and not completed:
        if operation=='game_finance.approve:POST' and status!=403:
            try:
                from game.paga_ai_budget import latest_plan,comparison
                reviewed_plan=latest_plan(actor)
                result={**result,'reviewed_plan':comparison(reviewed_plan['state'],reviewed_plan.get('baseline'),reviewed_plan.get('payments'),reviewed_plan.get('repeat_previous',False))}
            except (ValueError,KeyError):pass
        if operation=='game_finance.preview:POST' and isinstance(parameters.get('data',{}).get('shares'),dict):
            from decimal import Decimal,InvalidOperation
            try:
                total=sum((Decimal(str(v)) for v in parameters['data']['shares'].values()),Decimal(0))
                result={**result,'allocation_total_percent':str(total),'over_limit_percent':str(max(Decimal(0),total-100)),
                        'allocation_hint':'Suma udziałów może wynosić najwyżej 100%. Nie musisz wpisywać wszystkich kategorii. Niewykorzystaną część ZEUS doda do rezerwy; o priorytetach decydujesz sam.'}
            except (InvalidOperation,ValueError,TypeError):pass
        result={**result,'correction':'Popraw decyzję zgodnie z błędem. Dla budżetu użyj preview, sprawdź dochody i wydatki, potem approve z rationale. Nie zgaduj tokenów ani okresu.'}
    result={'status':status,'operation_id':operation,'result':result}

    audit_id=None
    if audit:
        with Session(db.engine) as session,session.begin():
            stored=scrub(result)
            if budget_plan:stored['_budget_plan']=budget_plan
            if retry_fingerprint:stored['_retry_state']=retry_fingerprint
            if retry_command:stored['_retry_command']=retry_command
            log=PagaAiLog(job_id=actor.job_id,country_id=actor.country_id,game_at=game_now(),operation=operation[:150],parameters=scrub(parameters),validation=validation,result=stored,reason=reason,model_id=model_id)
            session.add(log);session.flush();audit_id=log.id
    offset=command.get('offset',0) if isinstance(command,dict) else 0
    if type(offset) is not int or offset<0:offset=0
    return {'status':status,'audit_id':audit_id,'validation':validation,'reason':reason,'summary':summary_line,'observation':window(scrub(result),offset,6200 if operation.startswith('game_finance.') else 3200)}
