"""Bounded real-Qwen session on an ISOLATED in-memory SQLite database, through the real run_tick path.

Safety: holds the same worker.lock as the live UAT scheduler (never two model instances), checks free RAM and that
no other llama-server runs, hard time limit, never touches the UAT/PROD database or the global AI switch.

    venv/bin/python scripts/paga_ai_real_session.py --scenarios budget,review,attack --max-minutes 40
"""
import sys,json,time,fcntl,argparse,subprocess,signal,hashlib
from pathlib import Path
from datetime import timedelta
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT)]


def free_memory_gib():
    return next(int(line.split()[1])/1024**2 for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))


def other_model_running():
    return subprocess.run(['pgrep','-x','llama-server'],capture_output=True,text=True).stdout.strip()


def run_scenario(name,record):
    import test_paga_ai_budget as budget_fixture
    import test_paga_ai as ai_fixture
    from tempfile import TemporaryDirectory
    from extensions import db
    from sqlalchemy import select
    from game.paga_ai_models import PagaAiJob,PagaAiIdentity,PagaAiMetric,PagaAiGoal,PagaAiPlan,PagaAiLog
    from game.paga_ai_tasks import now,enqueue
    from engine.paga_ai_scheduler import run_tick
    # The finance fixture is a superset of the AI fixture (finance tables + military, diplomacy, research).
    base=budget_fixture.BudgetAdapterTests()
    base.setUp();temporary=TemporaryDirectory()
    try:
        app=base.app;app.root_path=temporary.name
        # Production runtime path: one model session per tick, several tasks back to back.
        app.config.update(PAGA_AI_PERSISTENT_MODEL=True,PAGA_AI_TASKS_PER_TICK=3)
        assert db.engine.url.drivername=='sqlite' and db.engine.url.database in (None,'',':memory:'),'Tylko izolowana baza w pamięci.'
        identity=db.session.get(PagaAiIdentity,1)
        if name!='review':identity.last_review_at=now()
        if name=='attack':
            from game.autonomy_models import AutonomyEvent
            from datetime import datetime
            db.session.add(AutonomyEvent(source_key='flight:real',kind='BOMBARDMENT',actor_id=2,target_id=1,occurred_at=datetime(2990,1,1),public=True,audience=[],payload={}))
        db.session.commit()
        if name in ('review','attack'):
            # Only the task under test (the fixture also produces a research task).
            from engine.paga_ai_scheduler import collect
            collect(db.session);db.session.commit()
            keep='strategic_review' if name=='review' else 'under_attack'
            for task in db.session.scalars(select(PagaAiJob).where(PagaAiJob.kind!=keep,PagaAiJob.status=='PENDING')):task.status='CANCELLED'
            db.session.commit()
        if name in ('transfer','reply'):
            if name=='transfer':
                assert base.plan()['status']==200
                assert base.call('game_finance.approve:POST',{'rationale':base.reason})['status']==200
                test_task=enqueue(db.session,1,'military_funding','diagnostic:transfer',0,source='test',priority=0,
                    context={'cel':'Przesuń dokładnie 0.1 MLD z reserve do research w zatwierdzonym budżecie, jeśli są dostępne środki. Nie zmieniaj podatków ani planu półrocza.'})
            else:
                from game.forum_models import ForumMessage
                from datetime import date
                message=ForumMessage(user_id=2,panstwo_id=2,author_name='Test',country_name='Dwa',flag_path='f',content='Proponujemy rozmowy o współpracy. Czy jesteście zainteresowani?',entenda_date=date(2990,1,1))
                db.session.add(message);db.session.flush()
                test_task=enqueue(db.session,1,'forum_reply','diagnostic:reply',0,source='test',priority=0,object_ref=message.id,
                    context={'cel':'Odpowiedz na wskazany wpis, określając własne stanowisko w sprawie rozmów.'})
            db.session.commit()
            from engine.paga_ai_scheduler import collect
            collect(db.session);db.session.commit()
            for task in db.session.scalars(select(PagaAiJob).where(PagaAiJob.id!=test_task.id,PagaAiJob.status.in_(['PENDING','BLOCKED']))):task.status='CANCELLED'
            db.session.commit()
        from contextlib import nullcontext
        from unittest.mock import patch
        from datetime import datetime
        clock=patch('game.budget_transfers.game_now',return_value=datetime(2990,1,1)) if name=='transfer' else nullcontext()
        started=time.monotonic()
        with clock:run_tick(app)
        elapsed=time.monotonic()-started
        db.session.expire_all()
        tasks=[{'kind':t.kind,'status':t.status,'model_calls':t.model_calls,'retries':t.retries,'error':t.error,'journal':t.journal,'duration_ms':t.duration_ms}
               for t in db.session.scalars(select(PagaAiJob).where(PagaAiJob.status!='CANCELLED').order_by(PagaAiJob.id))]
        metrics=[{k:getattr(m,k) for k in ('kind','is_call','outcome','context_ms','prompt_tokens','prompt_ms','generated_tokens','generation_ms','total_ms','peak_rss_bytes')}
                 for m in db.session.scalars(select(PagaAiMetric).order_by(PagaAiMetric.id))]
        writes=[{'operation':row.operation,'validation':row.validation,'reason':row.reason} for row in db.session.scalars(select(PagaAiLog).where(PagaAiLog.operation.not_like('%:GET')).order_by(PagaAiLog.id))]
        extra={}
        if name=='budget':
            from game.finance_models import StateBudget
            extra['budgets']=db.session.query(StateBudget).count()
        if name=='transfer':
            from game.finance_models import BudgetTransfer
            rows=list(db.session.scalars(select(BudgetTransfer)))
            extra['transfers']=[{'source':r.source,'destination':r.destination,'amount':str(r.amount),'budget_id':r.budget_id} for r in rows]
            extra['passed']=len(rows)==1 and rows[0].amount==100000000 and rows[0].destination=='research'
        if name=='reply':
            from game.forum_models import ForumMessage
            replies=list(db.session.scalars(select(ForumMessage).where(ForumMessage.user_id==base.actor.user_id)))
            extra['replies']=[{'reply_to_id':r.reply_to_id,'content':r.content} for r in replies]
            extra['passed']=len(replies)==1 and bool(replies[0].content.strip()) and replies[0].reply_to_id==message.id
        extra['goals']=[(g.title,g.status,g.parent_id) for g in db.session.scalars(select(PagaAiGoal))]
        extra['plans']=[(p.kind,p.status,p.note) for p in db.session.scalars(select(PagaAiPlan))]
        extra['strategy_memory']=db.session.get(PagaAiIdentity,1).strategy
        return {'scenario':name,'seconds':round(elapsed,1),'tasks':tasks,'metrics':metrics,'player_writes':writes,'model_io':record,**extra}
    finally:
        base.tearDown();temporary.cleanup()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--scenarios',default='budget,review,attack');parser.add_argument('--max-minutes',type=int,default=40)
    parser.add_argument('--output',default=str(ROOT/'docs'/'paga-ai-real-session.json'));args=parser.parse_args()
    lock_path=ROOT/'runtime/qwen/worker.lock';evidence={'database':'sqlite:///:memory:','scenarios':[],'started_free_gib':round(free_memory_gib(),2)}
    with lock_path.open('a') as lock:
        def lock_timeout(*_):raise TimeoutError('Scheduler UAT nie zwolnił modelu w ciągu 20 minut.')
        signal.signal(signal.SIGALRM,lock_timeout);signal.alarm(20*60)
        print('Oczekuję na wspólną blokadę modelu bez wyłączania AI…',flush=True)
        try:fcntl.flock(lock,fcntl.LOCK_EX)
        finally:signal.alarm(0)
        if other_model_running():raise SystemExit('Działa inna instancja llama-server; sesja przerwana.')
        if free_memory_gib()<4.0:raise SystemExit(f'Za mało wolnej pamięci: {free_memory_gib():.2f} GiB < 4.0 GiB.')
        def timeout(*_):raise TimeoutError('Przekroczono limit czasu sesji.')
        signal.signal(signal.SIGALRM,timeout);signal.alarm(args.max_minutes*60)
        from game import qwen_runtime
        original=qwen_runtime.ModelSession.generate
        sources=['game/paga_ai_runner.py','game/paga_ai_context.py','game/paga_ai_guard.py','game/paga_ai_tasks.py','game/paga_ai_detector.py','game/paga_ai_strategy.py','engine/paga_ai_scheduler.py','game/qwen_runtime.py','game/paga_ai_contracts.py','game/player_operations.py','game/paga_ai_quotes.py']
        evidence['source_sha256']={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in sources}
        try:
            for name in args.scenarios.split(','):
                record=[]
                def recording(self,messages,**kwargs):
                    decision=original(self,messages,**kwargs)
                    record.append({'context_chars':len(messages[1]['content']),'system_chars':len(messages[0]['content']),'decision':decision,'stats':{k:v for k,v in (kwargs.get('stats') or {}).items() if k!='reason'}})
                    print(json.dumps({'scenario':name,'decision':decision},ensure_ascii=False)[:1500],flush=True)
                    return decision
                qwen_runtime.ModelSession.generate=recording
                for _ in range(30):
                    if free_memory_gib()>=4.0:break
                    time.sleep(3)
                try:evidence['scenarios'].append(run_scenario(name,record))
                except Exception as error:evidence['scenarios'].append({'scenario':name,'error':f'{type(error).__name__}: {error}','model_io':record})
                finally:qwen_runtime.ModelSession.generate=original
                print(json.dumps({'scenario':name,'done':True},ensure_ascii=False),flush=True)
        finally:
            signal.alarm(0)
            evidence['finished_free_gib']=round(free_memory_gib(),2)
            evidence['source_unchanged']=all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest for name,digest in evidence['source_sha256'].items())
            Path(args.output).write_text(json.dumps(evidence,ensure_ascii=False,indent=1,default=str))
            print('Zapisano',args.output,flush=True)


if __name__=='__main__':main()
