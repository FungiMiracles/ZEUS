"""PAGA decision monitor (UAT, read-only). Never calls the model, never changes tasks, decisions or goals.

Sources (no second registry):
* model decisions  = PagaAiMetric rows with is_call=True (one row per model call; detail holds the decision,
                     its action outcomes, Entenda time and the range of audit rows it caused);
* ZEUS-only work    = PagaAiJob rows without any model call (queued, superseded, cancelled, already-done, conditional plans);
* operations        = PagaAiLog audit rows of the task (scrubbed parameters/results);
* goals             = PagaAiGoal; goal history is reconstructed from the model's own goal.create / goal.update decisions.
"""
import re,json
from datetime import datetime,timedelta
from sqlalchemy import select,func,exists,and_
from game.paga_ai_models import PagaAiJob,PagaAiLog,PagaAiMetric,PagaAiGoal,PagaAiPlan,PagaAiIdentity
from game.paga_ai_observation import scrub
from game.paga_ai_tasks import KINDS,PRIORITY_NAME,now

PAGE=25
WINDOW=600           # newest rows per source examined for one page (bounds DB work at every 15 s refresh)

CATEGORIES={'finanse':'Finanse','gospodarka':'Gospodarka','infrastruktura':'Infrastruktura','badania':'Badania','handel':'Handel','dyplomacja':'Dyplomacja',
            'komunikacja':'Komunikacja','wywiad':'Wywiad','wojsko':'Wojsko','strategia':'Strategia'}
DOMAIN_CATEGORY={'finance':'finanse','economy':'gospodarka','communication':'komunikacja','diplomacy':'dyplomacja','military':'wojsko','intelligence':'wywiad','strategy':'strategia'}
STATUSES={'PENDING':'Oczekuje','RUNNING':'W trakcie','EXECUTED':'Wykonana','PARTIAL':'Wykonana częściowo','REJECTED':'Odrzucona przez walidację','ERROR':'Błąd wykonania',
          'CANCELLED':'Anulowana','SUPERSEDED':'Zastąpiona nowszą','NO_ACTION':'Świadomie bez działania','ALREADY_DONE':'Już zrealizowana','DATA':'Zebranie danych'}
OPERATIONS={
    'budget.plan':('finanse','Plan budżetu półrocza'),'game_finance.transfer:POST':('finanse','Przesunięcie środków budżetu'),'game_loans.change:POST':('finanse','Pożyczka'),
    'game_infrastructure.expand:POST':('infrastruktura','Rozbudowa infrastruktury regionu'),'game_infrastructure.roads_change:POST':('infrastruktura','Drogi'),
    'game_infrastructure.industry_change:POST':('gospodarka','Przemysł'),'game_trade.mining_build:POST':('gospodarka','Uruchomienie wydobycia'),
    'game_research.change:POST':('badania','Badania'),'game_trade.change:POST':('handel','Handel'),
    'game_diplomacy.create_action:POST':('dyplomacja','Akcja dyplomatyczna'),'game_diplomacy.decide:POST':('dyplomacja','Decyzja w sprawie propozycji'),
    'game_forum.page:POST':('komunikacja','Wpis na forum'),'game_forum.edit:POST':('komunikacja','Edycja wpisu na forum'),'game_messages.send:POST':('komunikacja','Wiadomość prywatna'),
    'game_intelligence.change:POST':('wywiad','Wywiad'),'game_military.defense_change:POST':('wojsko','Obrona i bazy'),'game_military.war_order:POST':('wojsko','Rozkaz bojowy'),
    'plan.conditional':('wojsko','Plan warunkowy'),'plan.cancel':('wojsko','Anulowanie planu'),
    'goal.create':('strategia','Nowy cel strategiczny'),'goal.update':('strategia','Zmiana celu strategicznego'),'intent.create':('strategia','Zamiar na później'),'no_action':('strategia','Świadoma bezczynność'),
}
ACTIONS={'deploy':'rozmieszczenie bazy','place':'budowa baz','garrison':'zmiana garnizonu','location':'przeniesienie bazy','rename':'zmiana nazwy','upgrade':'modernizacja','withdraw':'wycofanie',
         'sail':'wypłynięcie okrętów','return_vessel':'powrót okrętu','rename_vessel':'zmiana nazwy okrętu','defense_place':'rozmieszczenie obrony przeciwrakietowej','defense_upgrade':'modernizacja obrony',
         'defense_refill':'uzupełnienie amunicji obrony','defense_repair':'naprawa obrony','build':'budowa','filter':'montaż filtra zanieczyszczeń','waste_filter':'montaż filtra odpadów fabrycznych','repair':'naprawa','pause':'wstrzymanie','resume':'wznowienie','remove':'likwidacja',
         'buy':'zakup','invest':'inwestycja','factory':'fabryka','offer':'oferta','cancel':'anulowanie','tariff':'cła','port_access':'dostęp do portów','request':'wniosek','accept':'przyjęcie',
         'reject':'odrzucenie','repay':'spłata','recruit':'rekrutacja agentów','mission':'misja','counter_upgrade':'rozbudowa kontrwywiadu',
         'WAR':'wypowiedzenie wojny','PEACE':'propozycja pokoju','CEASEFIRE':'zawieszenie broni','RELATION':'zmiana relacji',
         'land':'atak lądowy','air':'atak lotniczy','missile':'uderzenie rakietowe','naval':'atak morski'}
TASK_LABELS={'strategic_review':'Przegląd strategiczny','budget':'Budżet półrocza','private_message':'Reakcja na wiadomość prywatną','forum_reply':'Reakcja na wpis na forum',
             'forum_mention':'Reakcja na wzmiankę na forum','diplomatic_proposal':'Propozycja dyplomatyczna','war_declared':'Wypowiedzenie wojny wobec państwa','under_attack':'Reakcja na atak',
             'military_loss':'Straty wojskowe','conditional_plan':'Wykonanie planu warunkowego','plan_result':'Ocena wykonanego planu','intent':'Zapisany zamiar','research_available':'Dostępne punkty badań',
             'production_stopped':'Wstrzymana produkcja','energy_shortage':'Niedobór energii','legacy':'Analiza (poprzednia architektura)'}


# ---------------- classification (from real outcomes, never from the bare model answer) ----------------

def action_label(action):
    operation=str(action.get('operation') or action.get('operation_id') or '');data=action.get('data') or {}
    if operation.endswith(':GET'):return 'Odczyt: '+operation.split(':')[0].replace('game_','').replace('.',' / ')
    category,label=OPERATIONS.get(operation,(None,operation))
    detail=ACTIONS.get(str(data.get('action') or data.get('kind') or ''))
    if operation=='game_infrastructure.industry_change:POST' and data.get('category')=='power':label='Energetyka'
    if operation=='goal.create' and data.get('title'):detail=str(data['title'])[:60]
    return label+(f': {detail}' if detail else '')


def action_category(operation,data,domain):
    if operation=='game_infrastructure.industry_change:POST' and (data or {}).get('category')=='power':return 'infrastruktura'
    return OPERATIONS.get(operation,(DOMAIN_CATEGORY.get(domain,'strategia'),None))[0]


LEGACY_STATUS={'PENDING':'PENDING','QUEUED':'PENDING','BLOCKED':'PENDING','RUNNING':'RUNNING','COMPLETED':'EXECUTED','FINISHED':'EXECUTED','FAILED':'ERROR',
               'INTERRUPTED':'ERROR','CANCELLED':'CANCELLED','SUPERSEDED':'SUPERSEDED'}

def decision_status(metric,task_status):
    detail=metric.detail or {}
    if metric.outcome!='OK':return 'ERROR'
    if 'decision' not in detail:return LEGACY_STATUS.get(task_status,'ERROR')  # recorded before the monitor existed
    if not detail.get('finished'):
        return 'RUNNING' if task_status=='RUNNING' else 'CANCELLED' if task_status in ('CANCELLED','SUPERSEDED') else 'ERROR'
    actions=(detail.get('decision') or {}).get('actions') or []
    outcomes=detail.get('outcomes') or []
    if not actions or all(action.get('operation_id')=='no_action' for action in actions):return 'NO_ACTION'
    if not outcomes:return 'CANCELLED' if task_status in ('CANCELLED','SUPERSEDED') else 'ERROR'
    kinds=[row.get('outcome') for row in outcomes]
    writes=[kind for kind,row in zip(kinds,outcomes) if kind!='READ']
    ok=[kind for kind in writes if kind=='OK']
    if any(kind in ('UNKNOWN','PERMISSION') for kind in kinds):return 'ERROR'
    rejected=any(kind in ('DECISION','BLOCKED','DUPLICATE','SITUATION_CHANGED','TECHNICAL') for kind in kinds)
    if rejected:return 'PARTIAL' if ok else 'REJECTED'
    if writes and all(kind=='ALREADY_DONE' for kind in writes):return 'ALREADY_DONE'
    if ok:return 'EXECUTED'
    return 'DATA'


def task_status(task):
    status=task.status
    if status in ('PENDING','QUEUED','BLOCKED'):return 'PENDING'
    if status=='RUNNING':return 'RUNNING'
    if status in ('COMPLETED','FINISHED'):return 'ALREADY_DONE' if (task.result or {}).get('already_done') else 'EXECUTED'
    if status in ('FAILED','INTERRUPTED'):return 'ERROR'
    return status if status in STATUSES else 'ERROR'


# ---------------- registry ----------------

def countries(session,query=''):
    """Every country that has (or had) an AI identity; searchable by name."""
    from models import Panstwo
    statement=select(Panstwo.PANSTWO_ID,Panstwo.panstwo_nazwa).join(PagaAiIdentity,PagaAiIdentity.country_id==Panstwo.PANSTWO_ID).order_by(Panstwo.panstwo_nazwa)
    if query:statement=statement.where(Panstwo.panstwo_nazwa.icontains(query[:80],autoescape=True))
    return [{'id':id,'name':name} for id,name in session.execute(statement.limit(200))]


def _names(session,ids):
    from models import Panstwo
    from flask import url_for
    rows=session.execute(select(Panstwo.PANSTWO_ID,Panstwo.panstwo_nazwa).where(Panstwo.PANSTWO_ID.in_(set(ids)))).all() if ids else []
    return {id:{'name':name,'flag':url_for('static',filename='flags/'+(name or '').replace(' ','_')+'.jpg')} for id,name in rows}


def _game_times(session,job_ids):
    if not job_ids:return {}
    return dict(session.execute(select(PagaAiLog.job_id,func.min(PagaAiLog.game_at)).where(PagaAiLog.job_id.in_(job_ids)).group_by(PagaAiLog.job_id)).all())


def _parse(value,end=False):
    if not value:return None
    try:moment=datetime.strptime(value[:10],'%Y-%m-%d')
    except ValueError:raise ValueError('Podaj datę w formacie RRRR-MM-DD.')
    return moment+timedelta(days=1) if end else moment


def rows(session,filters):
    """Chronological registry (newest first) of model decisions and ZEUS-only task outcomes."""
    country=filters.get('country');real_from=_parse(filters.get('from'));real_to=_parse(filters.get('to'),True)
    game_from=_parse(filters.get('game_from'));game_to=_parse(filters.get('game_to'),True)
    calls=select(PagaAiMetric,PagaAiJob).join(PagaAiJob,PagaAiJob.id==PagaAiMetric.job_id).where(PagaAiMetric.is_call.is_(True))
    tasks=select(PagaAiJob).where(~exists().where(and_(PagaAiMetric.job_id==PagaAiJob.id,PagaAiMetric.is_call.is_(True))))
    if country:calls=calls.where(PagaAiMetric.country_id==country);tasks=tasks.where(PagaAiJob.country_id==country)
    if real_from:calls=calls.where(PagaAiMetric.created_at>=real_from);tasks=tasks.where(PagaAiJob.created_at>=real_from)
    if real_to:calls=calls.where(PagaAiMetric.created_at<real_to);tasks=tasks.where(PagaAiJob.created_at<real_to)
    result=[]
    for metric,task in session.execute(calls.order_by(PagaAiMetric.id.desc()).limit(WINDOW)):
        detail=metric.detail or {};decision=detail.get('decision') or {};actions=decision.get('actions') or []
        domain=KINDS.get(task.kind,KINDS['legacy'])['domain']
        main=next((action for action in actions if not str(action.get('operation_id','')).endswith(':GET')),actions[0] if actions else None)
        categories={action_category(str(action.get('operation_id') or ''),action.get('data'),domain) for action in actions} or {DOMAIN_CATEGORY.get(domain,'strategia')}
        status=decision_status(metric,task.status)
        reason=decision.get('ocena') or ''
        rationale=next((str((action.get('data') or {}).get('rationale') or (action.get('data') or {}).get('reason') or '') for action in actions if (action.get('data') or {}).get('rationale') or (action.get('data') or {}).get('reason')),'')
        result.append({'key':f'd{metric.id}','real_at':metric.created_at,'game_at':detail.get('game_at'),'country_id':metric.country_id,
                       'category':action_category(str(main.get('operation_id') or ''),main.get('data'),domain) if main else DOMAIN_CATEGORY.get(domain,'strategia'),'categories':sorted(categories),
                       'name':('Decyzja sprzed włączenia monitoringu (bez zapisanej treści)' if 'decision' not in detail and metric.outcome=='OK' else
                               (' + '.join(action_label(action) for action in actions[:3]) if actions else 'Brak działania') if status!='ERROR' or actions else 'Decyzja nie powstała'),
                       'reason':(rationale or reason)[:300] if (rationale or reason) else (detail.get('error') or '')[:300],'status':status,'model_ms':metric.total_ms,
                       'task_id':task.id,'task_kind':task.kind,'source':'model','provider':metric.provider,'model':metric.model_name})
    window_tasks=list(session.scalars(tasks.order_by(PagaAiJob.id.desc()).limit(WINDOW)))
    times=_game_times(session,[task.id for task in window_tasks])
    for task in window_tasks:
        domain=KINDS.get(task.kind,KINDS['legacy'])['domain'];journal=task.journal or []
        last=next((str(row.get('wynik')) for row in reversed(journal) if row.get('wynik')),None)
        result.append({'key':f't{task.id}','real_at':task.finished_at or task.created_at,'game_at':str(times[task.id])[:19] if times.get(task.id) else None,'country_id':task.country_id,
                       'category':DOMAIN_CATEGORY.get(domain,'strategia'),'categories':[DOMAIN_CATEGORY.get(domain,'strategia')],
                       'name':TASK_LABELS.get(task.kind,task.kind.replace('_',' ')),'reason':(last or task.error or ('Czeka w kolejce PAGA' if task.status in ('PENDING','QUEUED','BLOCKED') else ''))[:300],
                       'status':task_status(task),'model_ms':None,'task_id':task.id,'task_kind':task.kind,'source':'zeus'})
    category=filters.get('category');status=filters.get('status')
    if category:result=[row for row in result if category in row['categories']]
    if status:result=[row for row in result if row['status']==status]
    if game_from or game_to:
        result=[row for row in result if row['game_at'] and (not game_from or row['game_at']>=str(game_from)) and (not game_to or row['game_at']<str(game_to))]
    result.sort(key=lambda row:(row['real_at'],row['key']),reverse=True)
    return result


def registry(session,filters,page=1):
    items=rows(session,filters);page=max(1,min(400,page))
    chosen=items[(page-1)*PAGE:page*PAGE]
    names=_names(session,[row['country_id'] for row in chosen])
    for row in chosen:
        row['country']=names.get(row['country_id'],{'name':f"#{row['country_id']}",'flag':None})
        row['category_label']=CATEGORIES.get(row['category'],row['category']);row['status_label']=STATUSES.get(row['status'],row['status'])
        row['real_at']=row['real_at'].isoformat()+'Z' if row['real_at'] else None
    return {'items':chosen,'page':page,'hasMore':len(items)>page*PAGE,'categories':CATEGORIES,'statuses':STATUSES}


def statistics(session,country=None):
    since=now()-timedelta(hours=24)
    calls=select(PagaAiMetric,PagaAiJob.status).join(PagaAiJob,PagaAiJob.id==PagaAiMetric.job_id).where(PagaAiMetric.is_call.is_(True),PagaAiMetric.created_at>=since)
    pending=select(func.count()).select_from(PagaAiJob).where(PagaAiJob.status.in_(['PENDING','QUEUED','BLOCKED','RUNNING']))
    if country:calls=calls.where(PagaAiMetric.country_id==country);pending=pending.where(PagaAiJob.country_id==country)
    statuses=[];times=[]
    for metric,status in session.execute(calls):
        statuses.append(decision_status(metric,status))
        if metric.outcome=='OK' and metric.total_ms:times.append(metric.total_ms)
    return {'decisions_24h':len(statuses),'executed':sum(status in ('EXECUTED','PARTIAL','ALREADY_DONE','DATA','NO_ACTION') for status in statuses),
            'rejected':statuses.count('REJECTED'),'errors':statuses.count('ERROR'),'pending':session.scalar(pending),
            'avg_model_ms':round(sum(times)/len(times)) if times else None}


# ---------------- details ----------------

def _operations(session,job_id,first,last):
    statement=select(PagaAiLog).where(PagaAiLog.job_id==job_id).order_by(PagaAiLog.id)
    if first is not None:statement=statement.where(PagaAiLog.id>first)
    if last is not None:statement=statement.where(PagaAiLog.id<=last)
    result=[]
    for row in session.scalars(statement.limit(60)):
        output=scrub(row.result or {})
        text=json.dumps(output.get('result',output),ensure_ascii=False,default=str)
        result.append({'id':row.id,'game_at':str(row.game_at)[:19],'operation':row.operation,'technical':row.operation.endswith(':GET') or row.operation=='game_finance.preview:POST',
                       'parameters':scrub(row.parameters),'validation':row.validation,'reason':row.reason,'result':text[:1500]+('…' if len(text)>1500 else '')})
    return result


def _goal(session,goal_id,country_id):
    if not goal_id:return None
    goal=session.scalar(select(PagaAiGoal).where(PagaAiGoal.id==goal_id,PagaAiGoal.country_id==country_id))
    return {'id':goal.id,'title':goal.title,'status':goal.status} if goal else None


def detail(session,key):
    match=re.fullmatch(r'([dt])(\d{1,12})',key or '')
    if not match:raise ValueError('Nieznany wpis.')
    kind,identifier=match.group(1),int(match.group(2))
    if kind=='d':
        metric=session.get(PagaAiMetric,identifier)
        if metric is None or not metric.is_call:raise LookupError
        task=session.get(PagaAiJob,metric.job_id);data=metric.detail or {}
        model_ms=session.scalar(select(func.sum(PagaAiMetric.total_ms)).where(PagaAiMetric.job_id==task.id,PagaAiMetric.is_call.is_(True)))
        next_call=session.scalar(select(func.min(PagaAiMetric.id)).where(PagaAiMetric.job_id==task.id,PagaAiMetric.is_call.is_(True),PagaAiMetric.id>metric.id))
        last=data.get('log_to')
        if last is None and next_call is not None:
            following=session.get(PagaAiMetric,next_call);last=(following.detail or {}).get('log_from')
        return {'key':key,'task':_task(task),'decision':scrub(data.get('decision')),'outcomes':scrub(data.get('outcomes') or []),'error':data.get('error'),
                'status':STATUSES.get(decision_status(metric,task.status)),'call':data.get('call'),'model_ms':metric.total_ms,'task_model_ms':model_ms,
                'tokens':{'prompt':metric.prompt_tokens,'generated':metric.generated_tokens},
                'provider':metric.provider,'model':metric.model_name,'validation':metric.validation,'outcome':metric.outcome,
                'started_at':metric.started_at.isoformat()+'Z' if metric.started_at else None,'finished_at':metric.finished_at.isoformat()+'Z' if metric.finished_at else None,'goal':_goal(session,data.get('goal_id') or task.goal_id,task.country_id),
                'operations':_operations(session,task.id,data.get('log_from'),last)}
    task=session.get(PagaAiJob,identifier)
    if task is None:raise LookupError
    return {'key':key,'task':_task(task),'decision':None,'outcomes':[],'status':STATUSES.get(task_status(task)),'goal':_goal(session,task.goal_id,task.country_id),
            'operations':_operations(session,task.id,None,None),'journal':scrub(task.journal or [])}


def _task(task):
    return {'id':task.id,'kind':task.kind,'label':TASK_LABELS.get(task.kind,task.kind),'status':task.status,'priority':PRIORITY_NAME.get(task.priority,task.priority),'source':task.source,
            'created_at':task.created_at.isoformat()+'Z' if task.created_at else None,'finished_at':task.finished_at.isoformat()+'Z' if task.finished_at else None,
            'model_calls':task.model_calls,'retries':task.retries,'attempts':task.attempts,'error':task.error,'details':scrub(task.context or {}),'provider':getattr(task,'provider',None)}


# ---------------- goals ----------------

GOAL_ID=re.compile(r'#(\d+)')

def goal_history(session,goal):
    """Creation and every change of a goal, taken from the model's executed goal decisions."""
    history=[]
    calls=session.scalars(select(PagaAiMetric).where(PagaAiMetric.country_id==goal.country_id,PagaAiMetric.is_call.is_(True),PagaAiMetric.created_at>=goal.created_at-timedelta(minutes=5)).order_by(PagaAiMetric.id).limit(500))
    for metric in calls:
        data=metric.detail or {};actions=(data.get('decision') or {}).get('actions') or [];outcomes=data.get('outcomes') or []
        for action,outcome in zip(actions,outcomes):
            operation=action.get('operation_id');payload=action.get('data') or {}
            if operation=='goal.create' and outcome.get('outcome')=='OK':
                found=GOAL_ID.search(outcome.get('summary') or '')
                if found and int(found.group(1))==goal.id:history.append({'key':f'd{metric.id}','real_at':metric.created_at.isoformat()+'Z','game_at':data.get('game_at'),'change':'utworzenie','details':payload})
            elif operation=='goal.update' and payload.get('goal_id')==goal.id:
                change={'ACTIVE':'wznowienie / aktywacja','SUSPENDED':'zawieszenie','ABANDONED':'porzucenie','ACHIEVED':'zakończenie (osiągnięty)'}.get(payload.get('status'),'aktualizacja')
                history.append({'key':f'd{metric.id}','real_at':metric.created_at.isoformat()+'Z','game_at':data.get('game_at'),'change':change,'details':payload,'executed':outcome.get('outcome')=='OK','result':outcome.get('summary')})
    return history


def goals(session,country=None,status=None):
    statement=select(PagaAiGoal).order_by(PagaAiGoal.country_id,PagaAiGoal.priority,PagaAiGoal.id)
    if country:statement=statement.where(PagaAiGoal.country_id==country)
    if status:statement=statement.where(PagaAiGoal.status==status)
    goals_=list(session.scalars(statement.limit(200)))
    names=_names(session,[goal.country_id for goal in goals_])
    result=[]
    for goal in goals_:
        tasks=list(session.scalars(select(PagaAiJob).where(PagaAiJob.goal_id==goal.id).order_by(PagaAiJob.id.desc()).limit(10)))
        decisions=list(session.scalars(select(PagaAiMetric.id).where(PagaAiMetric.job_id.in_([task.id for task in tasks]),PagaAiMetric.is_call.is_(True)).order_by(PagaAiMetric.id.desc()).limit(10))) if tasks else []
        plans=list(session.scalars(select(PagaAiPlan).where(PagaAiPlan.goal_id==goal.id,PagaAiPlan.country_id==goal.country_id).order_by(PagaAiPlan.id.desc()).limit(5)))
        result.append({'id':goal.id,'title':goal.title,'description':goal.description,'country':names.get(goal.country_id,{'name':f'#{goal.country_id}','flag':None}),'country_id':goal.country_id,
                       'priority':goal.priority,'status':goal.status,'parent_id':goal.parent_id,'created_at':goal.created_at.isoformat()+'Z','created_game_at':str(goal.created_game_at)[:19] if goal.created_game_at else None,
                       'progress':scrub(goal.progress or {}),'note':goal.note,'criteria':scrub(goal.criteria or []),
                       'tasks':[{'id':task.id,'label':TASK_LABELS.get(task.kind,task.kind),'status':task.status} for task in tasks],
                       'decisions':[f'd{identifier}' for identifier in decisions],'plans':[{'id':plan.id,'kind':plan.kind,'status':plan.status,'note':plan.note} for plan in plans],
                       'history':goal_history(session,goal)})
    return result
