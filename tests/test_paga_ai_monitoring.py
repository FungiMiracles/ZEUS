"""PAGA decision monitor: built only from real PAGA records, read-only, UAT-only, no model calls."""
import json,unittest
from datetime import datetime,timedelta
from unittest.mock import patch
from sqlalchemy import select
from extensions import db
import test_paga_ai_tasks as scenarios
import test_paga_ai as ai_fixture
from game.paga_ai_models import PagaAiJob,PagaAiMetric,PagaAiGoal,PagaAiLog,PagaAiControl,PagaAiPlan,PagaAiIdentity,PagaAiWrite
from game.paga_ai_tasks import enqueue,now
from game import paga_ai_monitoring as monitoring

REASON=scenarios.REASON
DONE=scenarios.DONE


class MonitoringScenarioTests(scenarios.Scenario,unittest.TestCase):
    """Real run_tick -> runner -> executor, then the monitor reads what was recorded."""
    def setUp(self):
        import test_paga_ai_budget as budget_fixture
        self.base=budget_fixture.BudgetAdapterTests();self.base.setUp();self.app=self.base.app;self.actor=self.base.actor;self.ready()
        self.ctx=self.app.test_request_context();self.ctx.push();self.addCleanup(self.ctx.pop)
    def tearDown(self):self.base.tearDown()

    def run_budget(self):
        self.quiet_review()
        plan={'ocena':'Budżet zgodny z priorytetami.','actions':[{'operation_id':'budget.plan','path':{},'data':{'pit_rate':15,'allocation_weights':{'social_policy':8,'infrastructure':4,'healthcare':2,'reserve':2},'benefits_mld':{'children':0.25,'seniors':0.25},'rationale':REASON}}],'task_done':True}
        self.tick([plan])

    def test_decision_is_listed_with_real_outcome_and_grouped_operations(self):
        self.run_budget()
        data=monitoring.registry(db.session,{})
        row=next(item for item in data['items'] if item['source']=='model')
        self.assertEqual((row['category'],row['status'],row['name']),('finanse','EXECUTED','Plan budżetu okresu'))
        self.assertEqual(row['reason'],REASON);self.assertEqual(row['model_ms'],1500);self.assertTrue(row['game_at'].startswith('2990'))
        self.assertTrue(row['country']['flag'].endswith('.jpg'));self.assertTrue(row['real_at'].endswith('Z'))
        detail=monitoring.detail(db.session,row['key'])
        operations=[operation['operation'] for operation in detail['operations']]
        # One strategic decision -> several ZEUS operations: reading data, preview (technical), approval.
        self.assertIn('game_finance.page:GET',operations);self.assertIn('game_finance.preview:POST',operations);self.assertEqual(operations[-1],'game_finance.approve:POST')
        self.assertTrue(next(o for o in detail['operations'] if o['operation']=='game_finance.preview:POST')['technical'])
        self.assertEqual(detail['outcomes'][0]['outcome'],'OK');self.assertIn('Zatwierdzono budżet',detail['outcomes'][0]['summary'])
        self.assertEqual(detail['task']['model_calls'],1);self.assertEqual(detail['task_model_ms'],1500)
        text=json.dumps(detail,ensure_ascii=False)
        for secret in ('basis_token','_budget_plan','csrf','request_id','password'):self.assertNotIn(secret,text)

    def test_status_reflects_execution_not_the_model_answer(self):
        self.quiet_review()
        bad={'ocena':'Wypłacamy dużo.','actions':[{'operation_id':'budget.plan','path':{},'data':{'pit_rate':15,'allocation_weights':{'social_policy':1},'benefits_mld':{'children':5,'seniors':5},'accept_social_shortfall':True,'rationale':REASON}}],'task_done':True}
        self.tick([bad,bad,bad])
        statuses=[row['status'] for row in monitoring.registry(db.session,{})['items'] if row['source']=='model']
        self.assertTrue(statuses and set(statuses)<={'REJECTED'},statuses)
        problem=monitoring.detail(db.session,next(row['key'] for row in monitoring.registry(db.session,{})['items'] if row['source']=='model'))['outcomes'][0]
        self.assertIn('Świadczenia przekraczają',json.dumps(problem,ensure_ascii=False))

    def test_zeus_only_tasks_no_action_and_superseded_are_visible(self):
        self.quiet_review()
        self.collect()
        old=enqueue(db.session,1,'budget','budget:2989/2',0,source='test');old.status='SUPERSEDED';old.finished_at=now()
        db.session.commit()
        self.base.call('game_finance.preview:POST',{'pit_rate':15,'allocation_weights':{'social_policy':1},'benefits_millions':{'children':250,'seniors':250}})
        self.assertEqual(self.base.call('game_finance.approve:POST',{'rationale':REASON})['status'],200)
        self.tick([])                                           # ZEUS detects the budget is done: no model call
        review=enqueue(db.session,1,'strategic_review','review:idle',0,source='test');db.session.commit();self.only(review)
        self.quiet_review(10000)
        self.tick([{'ocena':'Sytuacja stabilna, świadomie czekamy.','actions':[{'operation_id':'no_action','path':{},'data':{'reason':'Brak potrzeby działania.'}}],'task_done':True}])
        statuses={row['status'] for row in monitoring.registry(db.session,{})['items']}
        self.assertTrue({'ALREADY_DONE','SUPERSEDED','NO_ACTION'}<=statuses,statuses)
        idle=next(row for row in monitoring.registry(db.session,{'status':'NO_ACTION'})['items'])
        self.assertEqual(idle['category'],'strategia');self.assertIn('Brak potrzeby',idle['reason'])

    def test_filters_paging_and_statistics(self):
        self.run_budget()
        for index in range(30):
            task=enqueue(db.session,1,'trade_event',f'note:{index}',0,source='test');task.status='CANCELLED';task.finished_at=now()-timedelta(minutes=index)
        db.session.commit()
        first=monitoring.registry(db.session,{});self.assertEqual(len(first['items']),25);self.assertTrue(first['hasMore'])
        times=[row['real_at'] for row in first['items']];self.assertEqual(times,sorted(times,reverse=True),'newest first')
        self.assertEqual(len(monitoring.registry(db.session,{},page=2)['items']),len(monitoring.rows(db.session,{}))-25)
        self.assertTrue(all(row['category']=='finanse' for row in monitoring.registry(db.session,{'category':'finanse'})['items']))
        self.assertEqual({row['status'] for row in monitoring.registry(db.session,{'status':'CANCELLED'})['items']},{'CANCELLED'})
        self.assertEqual(monitoring.registry(db.session,{'country':2})['items'],[])
        tomorrow=(datetime.utcnow()+timedelta(days=1)).strftime('%Y-%m-%d')
        self.assertEqual(monitoring.registry(db.session,{'from':tomorrow})['items'],[])
        game_rows=monitoring.registry(db.session,{'game_from':'2990-01-01','game_to':'2990-12-31'})['items']
        self.assertTrue(game_rows and all(row['game_at'] for row in game_rows))
        with self.assertRaises(ValueError):monitoring.registry(db.session,{'from':'jutro'})
        stats=monitoring.statistics(db.session)
        self.assertEqual((stats['decisions_24h'],stats['executed'],stats['errors']),(1,1,0));self.assertEqual(stats['avg_model_ms'],1500)
        self.assertEqual(monitoring.statistics(db.session,2)['decisions_24h'],0,'statistics follow the country filter')

    def test_goal_view_progress_history_and_link_to_decisions(self):
        self.quiet_review(10000)
        review=enqueue(db.session,1,'strategic_review','review:goals',0,source='test');db.session.commit();self.only(review)
        create={'ocena':'Budujemy przewagę.','actions':[{'operation_id':'goal.create','path':{},'data':{'title':'Przewaga technologiczna','priority':1,'criteria':[{'metric':'research_points','op':'>=','value':1}]}}],'task_done':True}
        self.tick([create])
        later=enqueue(db.session,1,'strategic_review','review:goals2',0,source='test');db.session.commit();self.only(later);self.quiet_review(10000)
        self.tick([{'ocena':'Wstrzymujemy.','actions':[{'operation_id':'goal.update','path':{},'data':{'goal_id':1,'status':'SUSPENDED','note':'Brak środków.'}}],'task_done':True}])
        goals=monitoring.goals(db.session,1)
        goal=goals[0];self.assertEqual((goal['title'],goal['status'],goal['priority']),('Przewaga technologiczna','SUSPENDED',1))
        self.assertEqual([entry['change'] for entry in goal['history']],['utworzenie','zawieszenie'])
        self.assertTrue(all(entry['key'].startswith('d') for entry in goal['history']))
        self.assertIn(goal['history'][0]['key'],[row['key'] for row in monitoring.registry(db.session,{})['items']],'goal history links to the decision registry')
        self.assertEqual(monitoring.goals(db.session,2),[])

    def test_decisions_recorded_before_the_monitor_show_the_task_status(self):
        task=enqueue(db.session,1,'strategic_review','review:old',0,source='test');task.status='PENDING';db.session.flush()
        db.session.add(PagaAiMetric(job_id=task.id,country_id=1,kind='strategic_review',is_call=True,outcome='OK',total_ms=90000,created_at=now()));db.session.commit()
        row=next(item for item in monitoring.registry(db.session,{})['items'] if item['task_id']==task.id)
        self.assertEqual(row['status'],'PENDING');self.assertIn('sprzed włączenia monitoringu',row['name'])

    def test_monitoring_never_calls_the_model(self):
        self.run_budget()
        with patch('game.qwen_runtime.generate',side_effect=AssertionError('model called')),patch('game.qwen_runtime.ModelSession.generate',side_effect=AssertionError('model called')),patch('game.paga_ai_providers.remote_generate',side_effect=AssertionError('model called')):
            data=monitoring.registry(db.session,{});monitoring.statistics(db.session);monitoring.goals(db.session)
            for row in data['items']:monitoring.detail(db.session,row['key'])
        self.assertEqual(db.session.query(PagaAiMetric).filter_by(is_call=True).count(),1)

    def test_history_survives_a_restart(self):
        """Everything shown comes from database rows (no in-memory state)."""
        self.run_budget()
        before=monitoring.registry(db.session,{})['items']
        db.session.remove();db.session.expire_all()
        after=monitoring.registry(db.session,{})['items']
        self.assertEqual([row['key'] for row in before],[row['key'] for row in after])


class MonitoringRouteTests(unittest.TestCase):
    """Access: WIKI 'wszechmocny' + panel token, UAT with PAGA AI only; read-only."""
    def setUp(self):
        from test_paga import PagaTests
        self.fixture=PagaTests();self.fixture.setUp();self.app=self.fixture.app;self.client=self.fixture.client
        self.app.config.update(ENV_NAME='UAT',PAGA_AI_CONFIGURED=True)
        from game.paga_ai_models import PagaAiProvider
        for model in [PagaAiControl,PagaAiJob,PagaAiLog,PagaAiMetric,PagaAiPlan,PagaAiGoal,PagaAiIdentity,PagaAiWrite,PagaAiProvider]:model.__table__.create(db.engine,checkfirst=True)
        from game.models import GameUser
        GameUser.__table__.create(db.engine,checkfirst=True)
        db.session.add(PagaAiControl(id=1,enabled=True,revision=0))
        db.session.add(GameUser(id=50,username='Kraj A (PAGA)',username_normalized='__paga_ai_1',is_active=True))
        db.session.add(PagaAiIdentity(country_id=1,user_id=50,memory=''))
        task=PagaAiJob(id=7,country_id=1,trigger='review:x',revision=0,status='COMPLETED',kind='strategic_review',source='schedule',priority=40,model_calls=1,created_at=now(),finished_at=now())
        db.session.add(task);db.session.flush()
        db.session.add(PagaAiMetric(job_id=7,country_id=1,kind='strategic_review',is_call=True,outcome='OK',total_ms=61000,created_at=now(),
                                    detail={'decision':{'ocena':'Wysyłamy ostrzeżenie.','actions':[{'operation_id':'game_messages.send:POST','path':{},'data':{'content':'Uwaga.','recipient_id':2}}],'task_done':True},
                                            'outcomes':[{'operation':'game_messages.send:POST','outcome':'OK','summary':'Wykonano operację gracza.'}],'game_at':'3001-07-11 10:00:00','log_from':0,'finished':True}))
        db.session.add(PagaAiLog(job_id=7,country_id=1,game_at=datetime(3001,7,11,10),operation='game_messages.send:POST',parameters={'path':{},'data':{'content':'Uwaga.','recipient_id':2,'csrf_token':'SEKRET'}},
                                 validation='EXECUTED',result={'status':201,'result':{'ok':True,'basis_token':'f'*64}},model_id='test'))
        db.session.commit()
        self.fixture.enter();self.headers=self.fixture.headers
    def tearDown(self):self.fixture.tearDown()

    def test_admin_reads_registry_detail_countries_and_goals(self):
        page=self.client.get('/admin/paga')
        self.assertIn('Monitoring decyzji',page.text);self.assertIn('wiki_paga_monitoring.js',page.text)
        data=self.client.get('/admin/paga/monitoring/decyzje',headers=self.headers).json
        row=data['items'][0]
        self.assertEqual((row['country']['name'],row['category'],row['status'],row['name']),('Kraj A','komunikacja','EXECUTED','Wiadomość prywatna'))
        self.assertEqual(data['statistics']['decisions_24h'],1)
        detail=self.client.get('/admin/paga/monitoring/decyzje/'+row['key'],headers=self.headers)
        self.assertEqual(detail.status_code,200);text=detail.text
        self.assertIn('game_messages.send:POST',text);self.assertNotIn('SEKRET',text);self.assertNotIn('f'*64,text)
        self.assertEqual(self.client.get('/admin/paga/monitoring/panstwa?q=kraj',headers=self.headers).json['countries'],[{'id':1,'name':'Kraj A'}])
        self.assertEqual(self.client.get('/admin/paga/monitoring/cele',headers=self.headers).json['goals'],[])
        self.assertEqual(self.client.get('/admin/paga/monitoring/decyzje/zly-klucz',headers=self.headers).status_code,400)
        self.assertEqual(self.client.get('/admin/paga/monitoring/decyzje/d999',headers=self.headers).status_code,404)
        self.assertEqual(self.client.get('/admin/paga/monitoring/decyzje?from=wczoraj',headers=self.headers).status_code,400)

    def test_access_is_restricted_and_read_only(self):
        url='/admin/paga/monitoring/decyzje'
        self.assertEqual(self.client.get(url).status_code,403,'panel token required')
        with self.client.session_transaction() as session:session['rola']='obserwator'
        self.assertEqual(self.client.get(url,headers=self.headers).status_code,403)
        with self.client.session_transaction() as session:session['rola']='wszechmocny'
        for method in ('post','put','delete'):
            self.assertEqual(getattr(self.client,method)(url,headers=self.headers).status_code,405)

    def test_not_available_outside_uat_or_without_paga_ai(self):
        url='/admin/paga/monitoring/decyzje'
        self.app.config['ENV_NAME']='PROD'
        self.assertEqual(self.client.get(url,headers=self.headers).status_code,404)
        self.app.config.update(ENV_NAME='UAT',PAGA_AI_CONFIGURED=False)
        self.assertEqual(self.client.get(url,headers=self.headers).status_code,404)
        self.assertNotIn('Monitoring decyzji',self.client.get('/admin/paga').text)
        self.app.config['PAGA_ENABLED']=False
        self.assertEqual(self.client.get(url,headers=self.headers).status_code,404)


if __name__=='__main__':unittest.main()
