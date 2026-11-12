"""PAGA MULTI-AI (10 Nov 2026): Gemini (strategy), Groq (operations & diplomacy), local Qwen (incoming loans only).

Scenario tests run the real run_tick -> routing -> runner -> guard -> executor -> player routes with ZEUS validation;
only the model answers are scripted (no network). Required checks i.1–i.7 are marked in the test names.
"""
import io,json,os,unittest,urllib.error
from datetime import timedelta
from decimal import Decimal
from email.message import Message
from unittest.mock import patch
from sqlalchemy import select
from extensions import db
import test_paga_ai_tasks as scenarios
import test_paga_ai_budget as budget_fixture
import test_paga_ai as ai_fixture
from game.paga_ai_models import PagaAiJob,PagaAiLog,PagaAiMetric,PagaAiControl,PagaAiProvider
from game.paga_ai_tasks import enqueue,now
from game.finance_models import StateBudget
from game import paga_ai_providers as providers

DONE=scenarios.DONE


class MultiAi(scenarios.Scenario):
    def tick(self,script,captured=None):
        """One scheduler tick over all lanes; records which model got each call."""
        from engine.paga_ai_scheduler import run_tick
        captured=[] if captured is None else captured
        sequence=iter(script)
        def model(provider):
            def call(messages,**kwargs):
                entry={'provider':provider,'system':messages[0]['content'],'context':json.loads(messages[1]['content']),'schema':kwargs.get('schema')}
                captured.append(entry)
                stats=kwargs.get('stats')
                if stats is not None:stats.update(prompt_tokens=1500,generated_tokens=90,seconds=0.8)
                item=next(sequence,DONE)
                if isinstance(item,Exception):raise item
                return item(entry) if callable(item) else item
            return call
        with patch('game.qwen_runtime.generate',side_effect=model('qwen')),\
             patch('game.paga_ai_providers.remote_generate',side_effect=lambda provider,messages,**kwargs:model(provider)(messages,**kwargs)):
            run_tick(self.app)
        db.session.expire_all()
        return captured
    def calls(self,task):
        return list(db.session.scalars(select(PagaAiMetric).where(PagaAiMetric.job_id==task.id,PagaAiMetric.is_call.is_(True)).order_by(PagaAiMetric.id)))
    def environment(self,**values):
        patcher=patch.dict(os.environ,values);patcher.start();self.addCleanup(patcher.stop)


class FinanceLaneTests(MultiAi,unittest.TestCase):
    def setUp(self):
        self.base=budget_fixture.BudgetAdapterTests();self.base.setUp();self.app=self.base.app;self.actor=self.base.actor;self.ready()
    def tearDown(self):self.base.tearDown()
    def plan(self):
        return {'ocena':'Budżet zgodny z priorytetami.','actions':[{'operation_id':'budget.plan','path':{},'data':{'pit_rate':15,'allocation_weights':scenarios.FinanceScenarioTests.WEIGHTS,
                'rationale':scenarios.REASON,'benefits_mld':{'children':0.25,'seniors':0.25}}}],'task_done':True}
    def budget_only(self):
        self.quiet_review();self.collect()
        task=self.tasks(kind='budget')[0];self.only(task);return task

    def test_i1_gemini_prepares_and_approves_the_budget_plan(self):
        task=self.budget_only()
        captured=self.tick([lambda call:self.plan() if call['provider']=='gemini' else DONE])
        call=next(item for item in captured if item['context']['zadanie']['rodzaj']=='budget')
        self.assertEqual(call['provider'],'gemini');self.assertIn('model strategiczny',call['system'])
        db.session.refresh(task)
        self.assertEqual((task.status,task.provider),('COMPLETED','gemini'))
        self.assertEqual(db.session.query(StateBudget).count(),1,'approved through the real budget routes and validation')
        metric=self.calls(task)[0]
        # g) call log: country, task, provider, model, kind, start/end, response time, tokens, decision, ZEUS validation
        self.assertEqual((metric.country_id,metric.job_id,metric.provider,metric.model_name,metric.kind),(1,task.id,'gemini','gemini-3.8-flash','budget'))
        self.assertIsNotNone(metric.started_at);self.assertIsNotNone(metric.finished_at);self.assertLessEqual(metric.started_at,metric.finished_at)
        self.assertEqual((metric.prompt_tokens,metric.generated_tokens,metric.total_ms),(1500,90,800))
        self.assertEqual(metric.detail['decision']['actions'][0]['operation_id'],'budget.plan');self.assertEqual(metric.validation,'OK')

    def test_i4_gemini_unavailable_hands_the_task_to_groq(self):
        task=self.budget_only()
        # Gemini answers 503: the call is logged, the provider paused, the task re-queued without using an attempt.
        error=urllib.error.HTTPError('https://generativelanguage.googleapis.com/x',503,'Unavailable',Message(),io.BytesIO(b'{"error":"overloaded"}'))
        with patch('game.paga_ai_providers.urllib.request.urlopen',side_effect=error):
            from engine.paga_ai_scheduler import run_tick
            run_tick(self.app,'gemini')
        db.session.expire_all();db.session.refresh(task)
        self.assertEqual((task.status,task.attempts),('PENDING',0));self.assertIn('niedostępny',task.error)
        self.assertEqual(self.calls(task)[0].outcome,'UNAVAILABLE')
        self.assertGreater(db.session.get(PagaAiProvider,'gemini').cooldown_until,now())
        captured=self.tick([lambda call:self.plan() if call['context']['zadanie']['rodzaj']=='budget' else DONE])
        self.assertEqual([item['provider'] for item in captured if item['context']['zadanie']['rodzaj']=='budget'],['groq'])
        db.session.refresh(task)
        self.assertEqual((task.status,task.provider),('COMPLETED','groq'));self.assertEqual(db.session.query(StateBudget).count(),1)
        # b.6) the handover is recorded in the task history and in the PAGA audit log
        self.assertTrue(any('Przekazano zadanie z Gemini do Groq' in str(row.get('wynik')) for row in task.journal))
        log=db.session.scalar(select(PagaAiLog).where(PagaAiLog.job_id==task.id,PagaAiLog.operation=='paga.handover'))
        self.assertEqual((log.validation,log.parameters),('HANDOVER',{'from':'gemini','to':'groq'}))

    def test_i6_switched_off_model_receives_no_new_tasks(self):
        task=self.budget_only()
        self.environment(PAGA_GEMINI_ENABLED='false',PAGA_GROQ_ENABLED='0')
        captured=self.tick([self.plan()])
        self.assertEqual(captured,[]);db.session.refresh(task);self.assertEqual(task.status,'PENDING')
        with db.session.no_autoflush:
            self.assertEqual(providers.route(db.session,'budget'),(None,None,'Gemini wyłączony (PAGA_GEMINI_ENABLED). Groq wyłączony (PAGA_GROQ_ENABLED).'))
        # Only Gemini off: the strategic task goes to Groq, Gemini gets nothing.
        os.environ['PAGA_GROQ_ENABLED']='true'
        captured=self.tick([lambda call:self.plan() if call['context']['zadanie']['rodzaj']=='budget' else DONE])
        self.assertNotIn('gemini',{item['provider'] for item in captured})
        db.session.refresh(task);self.assertEqual(task.provider,'groq')

    def test_i7_global_switches_stop_every_model_from_changing_the_game(self):
        task=self.budget_only()
        # Global PAGA emergency switch (panel): nothing is claimed by any lane.
        control=db.session.get(PagaAiControl,1);control.enabled=False;db.session.commit()
        self.assertEqual(self.tick([self.plan()]*3),[])
        control=db.session.get(PagaAiControl,1);control.enabled=True;db.session.commit()
        # PAGA_AUTONOMOUS_WRITES_ENABLED=false: the model decides, ZEUS executes nothing and records why.
        self.environment(PAGA_AUTONOMOUS_WRITES_ENABLED='false')
        captured=self.tick([lambda call:self.plan() if call['context']['zadanie']['rodzaj']=='budget' else DONE])
        self.assertEqual(len([item for item in captured if item['context']['zadanie']['rodzaj']=='budget']),1,'one decision, no correction rounds')
        db.session.refresh(task)
        self.assertEqual(task.status,'CANCELLED');self.assertIn('PAGA_AUTONOMOUS_WRITES_ENABLED',task.error)
        self.assertEqual(db.session.query(StateBudget).count(),0)
        self.assertEqual(self.calls(task)[0].validation,'WRITES_OFF')
        self.assertTrue(db.session.scalar(select(PagaAiLog.id).where(PagaAiLog.job_id==task.id,PagaAiLog.validation=='WRITES_OFF')))

    def test_missing_switch_means_no_writes(self):
        os.environ.pop('PAGA_AUTONOMOUS_WRITES_ENABLED',None)
        self.assertFalse(providers.writes_enabled())


class OperationalLaneTests(MultiAi,unittest.TestCase):
    def setUp(self):
        self.base=ai_fixture.AiTests();self.base.setUp();self.app=self.base.app;self.actor=self.base.actor;self.fixture=self.base.fixture;self.ready()
    def tearDown(self):self.base.tearDown()
    def forum_task(self,kind='world_event'):
        self.quiet_review();self.collect()   # detector tasks are created now and cancelled by only()
        task=enqueue(db.session,1,kind,f'{kind}:test',0,source='test',context={'cel':'Zareaguj na wydarzenie międzynarodowe.'});db.session.commit();self.only(task);return task
    POST={'ocena':'Komentujemy wydarzenie.','actions':[{'operation_id':'game_forum.page:POST','path':{},'data':{'content':'Hopia wzywa do spokoju i rozmów.'}}],'task_done':True}

    def test_i2_groq_publishes_on_the_diplomatic_forum(self):
        from game.forum_models import ForumMessage
        task=self.forum_task()
        captured=self.tick([self.POST])
        self.assertEqual([item['provider'] for item in captured],['groq']);self.assertIn('operacyjno-dyplomatyczny',captured[0]['system'])
        self.assertEqual(db.session.scalar(select(ForumMessage.content)),'Hopia wzywa do spokoju i rozmów.')
        db.session.refresh(task);self.assertEqual((task.status,task.provider),('COMPLETED','groq'))
        metric=self.calls(task)[0];self.assertEqual((metric.provider,metric.model_name,metric.validation),('groq','openai/gpt-oss-120b','OK'))

    def test_i5_rate_limit_puts_the_task_back_in_the_queue(self):
        from game.forum_models import ForumMessage
        task=self.forum_task()
        self.environment(PAGA_GEMINI_ENABLED='false')     # no fallback: the task must wait
        headers=Message();headers['retry-after']='42'
        error=urllib.error.HTTPError('https://api.groq.com/x',429,'Too Many Requests',headers,io.BytesIO(b'{"error":{"message":"Rate limit reached"}}'))
        from engine.paga_ai_scheduler import run_tick
        with patch('game.paga_ai_providers.urllib.request.urlopen',side_effect=error):run_tick(self.app,'groq')
        db.session.expire_all();db.session.refresh(task)
        self.assertEqual((task.status,task.attempts),('PENDING',0));self.assertIn('limit API',task.error)
        self.assertEqual(self.calls(task)[0].outcome,'RATE_LIMIT')
        pause=db.session.get(PagaAiProvider,'groq').cooldown_until-now()
        self.assertTrue(timedelta(seconds=30)<pause<=timedelta(seconds=42),'retry respects the provider retry-after')
        self.assertEqual(self.tick([self.POST]),[],'queued while the provider limit lasts');self.assertEqual(db.session.query(ForumMessage).count(),0)
        # After the pause the queued task is processed normally.
        row=db.session.get(PagaAiProvider,'groq');row.cooldown_until=now()-timedelta(seconds=1);db.session.commit()
        self.tick([self.POST]);db.session.refresh(task)
        self.assertEqual(task.status,'COMPLETED');self.assertEqual(db.session.query(ForumMessage).count(),1)

    def test_client_side_limits_defer_before_any_request(self):
        task=self.forum_task()
        self.environment(PAGA_GEMINI_ENABLED='false',PAGA_GROQ_RPM='1')
        db.session.add(PagaAiMetric(country_id=1,kind='forum_reply',is_call=True,outcome='OK',provider='groq',created_at=now()));db.session.commit()
        from engine.paga_ai_scheduler import run_tick
        with patch('game.paga_ai_providers.urllib.request.urlopen',side_effect=AssertionError('request sent')):run_tick(self.app,'groq')
        db.session.expire_all();db.session.refresh(task)
        self.assertEqual((task.status,task.attempts),('PENDING',0));self.assertIn('na minutę',task.error)
        self.assertEqual(self.calls(task),[],'a locally refused call is not a provider call')

    def test_groq_unavailable_gemini_takes_diplomacy(self):
        task=self.forum_task()
        self.environment(PAGA_GROQ_ENABLED='false')
        captured=self.tick([self.POST])
        self.assertEqual([item['provider'] for item in captured],['gemini'])
        db.session.refresh(task);self.assertEqual((task.status,task.provider),('COMPLETED','gemini'))

    def test_i3_qwen_decides_an_incoming_loan_request_and_nothing_else(self):
        from game.loan_models import StateLoan
        self.quiet_review()
        loan=StateLoan(borrower_id=2,lender_id=1,requested_by=2,amount=Decimal('1000000000.00'),status='pending',request_id='multi-1');db.session.add(loan);db.session.commit()
        self.collect()
        task=enqueue(db.session,1,'loan_event','loan:multi-1',0,source='test',context={'cel':'Rozpatrz wniosek o pożyczkę.'});db.session.commit();self.only(task)
        def decide(call):
            self.assertEqual(call['provider'],'qwen');self.assertIn('wyłącznie rozpatrujesz przychodzące wnioski',call['system'])
            self.assertEqual(sorted(call['context']['możliwe_działania']),['game_loans.change:POST','no_action'])
            variants=json.dumps(call['schema'],ensure_ascii=False)
            self.assertIn('"accept", "reject"',variants);self.assertNotIn('"repay"',variants);self.assertNotIn('goal.create',variants)
            return {'ocena':'Nie stać nas teraz na pożyczkę.','actions':[{'operation_id':'game_loans.change:POST','path':{},'data':{'action':'reject','loan_id':loan.id}}],'task_done':True}
        captured=self.tick([decide])
        self.assertEqual([item['provider'] for item in captured],['qwen'])
        self.assertEqual(db.session.get(StateLoan,loan.id).status,'rejected','decided through the real loan route')
        db.session.refresh(task);self.assertEqual((task.status,task.provider),('COMPLETED','qwen'))

    def test_loans_only_for_qwen_and_qwen_only_for_loans(self):
        self.assertEqual(providers.permitted('gemini','game_loans.change:POST',{'action':'accept','loan_id':1}),'Wnioski innych państw o pożyczkę rozpatruje wyłącznie model finansowy (Qwen).')
        self.assertIsNone(providers.permitted('gemini','game_loans.change:POST',{'action':'request','lender_id':2,'amount_mld':1}))
        self.assertIsNone(providers.permitted('gemini','game_loans.change:POST',{'action':'repay','loan_id':1}))
        self.assertIsNotNone(providers.permitted('qwen','game_forum.page:POST',{'content':'x'}))
        self.assertIsNotNone(providers.permitted('qwen','game_loans.change:POST',{'action':'request','lender_id':2,'amount_mld':1}))
        # Qwen switched off: no other model takes loans; the task waits.
        with patch.dict(os.environ,{'PAGA_QWEN_ENABLED':'false'}):
            self.assertEqual(providers.route(db.session,'loan_event')[0],None)
        self.assertEqual(providers.route(db.session,'loan_event')[0],'qwen')

    def test_one_task_never_runs_on_two_models_and_one_running_task_per_country(self):
        from engine.paga_ai_scheduler import claim
        self.quiet_review()
        self.collect()
        first=enqueue(db.session,1,'world_event','world:a',0,source='test');second=enqueue(db.session,1,'budget','budget:a',0,source='test');db.session.commit();self.only(first,second)
        with db.session.begin_nested():claimed=claim(db.session,'groq')
        db.session.commit()
        self.assertEqual(claimed[1:3],(first.id,'groq:openai/gpt-oss-120b'))
        self.assertIsNone(claim(db.session,'groq'),'the same task is not claimed again')
        self.assertIsNone(claim(db.session,'gemini'),'one running task per country across all lanes')
        db.session.rollback()

    def test_keys_never_reach_logs_errors_or_the_panel(self):
        key=os.environ['GROQ_API_KEY']
        task=self.forum_task()
        self.environment(PAGA_GEMINI_ENABLED='false')
        error=urllib.error.HTTPError('https://api.groq.com/x',400,'Bad Request',Message(),io.BytesIO(f'{{"error":"invalid request for key {key}"}}'.encode()))
        from engine.paga_ai_scheduler import run_tick
        with patch('game.paga_ai_providers.urllib.request.urlopen',side_effect=error):run_tick(self.app,'groq')
        db.session.expire_all()
        stored=json.dumps([[row.error,row.journal] for row in db.session.scalars(select(PagaAiJob))]+[[row.detail] for row in db.session.scalars(select(PagaAiMetric))]+
                          [[row.reason,row.parameters] for row in db.session.scalars(select(PagaAiLog))],ensure_ascii=False,default=str)
        self.assertIn('invalid request',stored);self.assertNotIn(key,stored)
        panel=json.dumps(providers.status(db.session),ensure_ascii=False)
        self.assertNotIn(key,panel);self.assertNotIn(os.environ['GEMINI_API_KEY'],panel);self.assertIn('"keyPresent": true',panel)

    def test_gemini_quota_is_per_model(self):
        """UAT 10 Nov 2026: a 429 of gemini-3.6-flash paused all of Gemini until the daily reset; other free models had quota."""
        answer={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'{"ocena":"ok","actions":[],"task_done":true}'}]}}],'usageMetadata':{'promptTokenCount':10,'candidatesTokenCount':5}}
        urls=[]
        def urlopen(request,timeout):
            urls.append(request.full_url.split('/models/')[1].split(':')[0])
            if 'gemini-3.5-flash-lite' in request.full_url:return ClientTests.Response(json.dumps(answer).encode())
            if 'gemini-3.6-flash' in request.full_url:
                headers=Message();headers['retry-after']='38000'
                raise urllib.error.HTTPError(request.full_url,429,'quota',headers,io.BytesIO(b'{}'))
            raise urllib.error.HTTPError(request.full_url,503,'high demand',Message(),io.BytesIO(b'{}'))
        stats={}
        with patch('game.paga_ai_providers.urllib.request.urlopen',side_effect=urlopen):providers.gemini_generate([{'role':'user','content':'U'}],stats=stats)
        self.assertEqual(urls,['gemini-3.8-flash','gemini-3.6-flash','gemini-3.5-flash-lite']);self.assertEqual(stats['model'],'gemini-3.5-flash-lite')
        db.session.expire_all()
        self.assertIsNone(db.session.get(PagaAiProvider,'gemini'),'Gemini as a whole stays available')
        self.assertGreater(db.session.get(PagaAiProvider,'gemini:gemini-3.6-flash').cooldown_until,now()+timedelta(hours=10))
        self.assertTrue(providers.availability(db.session,'gemini')[0])
        # The exhausted model is skipped on the next call (no wasted request).
        urls.clear()
        with patch('game.paga_ai_providers.urllib.request.urlopen',side_effect=urlopen):providers.gemini_generate([{'role':'user','content':'U'}],stats={})
        self.assertNotIn('gemini-3.6-flash',urls)
        # All free models limited/overloaded: only then is the provider paused (until the first model is free again).
        db.session.get(PagaAiProvider,'gemini:gemini-3.8-flash').cooldown_until=now()+timedelta(hours=1)
        db.session.add(PagaAiProvider(provider='gemini:gemini-3.5-flash-lite',cooldown_until=now()+timedelta(hours=2),updated_at=now()));db.session.commit()
        with self.assertRaises(providers.ProviderUnavailable):providers.gemini_generate([{'role':'user','content':'U'}],stats={})
        db.session.expire_all();pause=db.session.get(PagaAiProvider,'gemini').cooldown_until-now()
        self.assertTrue(timedelta(minutes=55)<pause<=timedelta(hours=1))
        self.assertEqual(set(providers.status(db.session)['providers'][0]['pausedModels']),{'gemini-3.8-flash','gemini-3.6-flash','gemini-3.5-flash-lite'})

    def test_missing_method_suffix_is_completed_but_never_bypasses_roles(self):
        """UAT task 480: Groq wrote 'game_research.change' four times and was refused without a usable hint."""
        from game.paga_ai_runner import act
        task=self.forum_task()
        allowed=['game_research.change:POST','game_loans.change:POST','no_action']
        result=act(self.app,self.actor,task.id,{'operation_id':'game_loans.change','data':{'action':'accept','loan_id':1}},allowed=allowed,reads=[],step=1,model_id='t',provider='gemini')
        self.assertIn('wyłącznie model finansowy',result['summary'])
        result=act(self.app,self.actor,task.id,{'operation_id':'game_unknown.change','data':{}},allowed=allowed,reads=['game_research.state:GET'],step=2,model_id='t',provider='groq')
        self.assertEqual(result['problem']['możliwe_operacje'],[*allowed,'game_research.state:GET'])
        result=act(self.app,self.actor,task.id,{'operation_id':'game_research.change','data':{'action':'buy','count':1}},allowed=allowed,reads=[],step=3,model_id='t',provider='groq')
        self.assertNotIn('nie należy do tego zadania',result['summary'],'the suffix was completed and the game validated the action')

    def test_missing_key_and_paid_model_are_unavailable_not_errors(self):
        with patch.dict(os.environ,{'GEMINI_API_KEY':''}):
            self.assertEqual(providers.availability(db.session,'gemini'),(False,'Gemini: brak klucza API (GEMINI_API_KEY).'))
        with patch.dict(os.environ,{'PAGA_GEMINI_MODEL':'gemini-4-argon'}):
            available,reason=providers.availability(db.session,'gemini')
            self.assertFalse(available);self.assertIn('bezpłatnego planu',reason)


class ClientTests(unittest.TestCase):
    """HTTP clients: keys only in headers, free-tier response parsing, retry delays."""
    def setUp(self):
        import paga_multi_ai_env
        self.env=paga_multi_ai_env.start()
        # No database here: no model is paused.
        self.active=patch('game.paga_ai_providers.active_models',side_effect=lambda provider:[providers.model_name(provider),*providers.spare_models(provider)]);self.active.start()
    def tearDown(self):self.active.stop();self.env.stop()

    class Response(io.BytesIO):
        def __enter__(self):return self
        def __exit__(self,*args):return False

    def capture(self,body):
        sent=[]
        def urlopen(request,timeout):
            sent.append(request);return self.Response(json.dumps(body).encode())
        return sent,urlopen

    def test_gemini_request_and_usage(self):
        sent,urlopen=self.capture({'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'{"ocena":"ok","actions":[],"task_done":true}'}]}}],
                                   'usageMetadata':{'promptTokenCount':1200,'candidatesTokenCount':40,'thoughtsTokenCount':10}})
        stats={}
        with patch('game.paga_ai_providers.urllib.request.urlopen',side_effect=urlopen):
            decision=providers.gemini_generate([{'role':'system','content':'S'},{'role':'user','content':'U'}],schema={'type':'object'},stats=stats)
        self.assertEqual(decision['ocena'],'ok');self.assertEqual((stats['prompt_tokens'],stats['generated_tokens']),(1200,50))
        request=sent[0];body=json.loads(request.data)
        self.assertNotIn(os.environ['GEMINI_API_KEY'],request.full_url,'the key is never in the URL');self.assertEqual(request.get_header('X-goog-api-key'),os.environ['GEMINI_API_KEY'])
        self.assertIn('models/gemini-3.8-flash:generateContent',request.full_url)
        self.assertEqual(body['generationConfig']['responseMimeType'],'application/json');self.assertEqual(body['systemInstruction']['parts'][0]['text'],'S')

    def test_groq_request_and_usage(self):
        sent,urlopen=self.capture({'choices':[{'finish_reason':'stop','message':{'content':'{"ocena":"ok","actions":[],"task_done":true}'}}],'usage':{'prompt_tokens':900,'completion_tokens':70}})
        stats={}
        with patch('game.paga_ai_providers.urllib.request.urlopen',side_effect=urlopen):
            providers.groq_generate([{'role':'system','content':'S'},{'role':'user','content':'U'}],schema={'type':'object'},stats=stats)
        body=json.loads(sent[0].data)
        # Compact grammar: the full one alone exceeds Groq's free 8K tokens/min (live check 10 Nov 2026).
        self.assertEqual(body['model'],'openai/gpt-oss-120b');self.assertEqual(body['response_format']['type'],'json_schema');self.assertLessEqual(body['max_completion_tokens'],1280)
        self.assertEqual(sent[0].get_header('Authorization'),'Bearer '+os.environ['GROQ_API_KEY']);self.assertEqual((stats['prompt_tokens'],stats['generated_tokens']),(900,70))

    def test_gemini_overloaded_model_retries_once_on_the_free_spare(self):
        answer={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'{"ocena":"ok","actions":[],"task_done":true}'}]}}],'usageMetadata':{'promptTokenCount':10,'candidatesTokenCount':5}}
        urls=[]
        def urlopen(request,timeout):
            urls.append(request.full_url)
            if 'gemini-3.8-flash' in request.full_url:raise urllib.error.HTTPError(request.full_url,503,'high demand',Message(),io.BytesIO(b'{}'))
            return self.Response(json.dumps(answer).encode())
        stats={}
        with patch('game.paga_ai_providers.urllib.request.urlopen',side_effect=urlopen),patch('game.paga_ai_providers.set_cooldown') as pause:
            providers.gemini_generate([{'role':'user','content':'U'}],stats=stats)
        self.assertEqual([url.split('/models/')[1] for url in urls],['gemini-3.8-flash:generateContent','gemini-3.6-flash:generateContent'])
        self.assertEqual(stats['model'],'gemini-3.6-flash')
        self.assertEqual([call.args[0] for call in pause.call_args_list],['gemini:gemini-3.8-flash'],'only the overloaded model is paused, never the provider')
        # A paid model can never be the spare.
        with patch.dict(os.environ,{'PAGA_GEMINI_SPARE_MODELS':'gemini-4-argon,gemini-3.5-flash-lite'}):self.assertEqual(providers.spare_models('gemini'),['gemini-3.5-flash-lite'])

    def test_gemini_gets_the_compact_grammar_limited_to_task_operations(self):
        grammar={'type':'object','properties':{'ocena':{'type':'string'},'actions':{'type':'array','maxItems':3,'items':{'anyOf':[
            {'type':'object','properties':{'operation_id':{'type':'string','enum':['game_forum.page:POST']},'data':{'type':'object'}}},
            {'type':'object','properties':{'operation_id':{'type':'string','enum':['no_action']},'data':{'type':'object'}}}]}},'task_done':{'type':'boolean'}}}
        compact=providers.compact_schema(grammar)
        self.assertEqual(compact['properties']['actions']['items']['properties']['operation_id']['enum'],['game_forum.page:POST','no_action'])
        self.assertEqual(compact['properties']['actions']['maxItems'],3)

    def test_request_too_large_means_smaller_context(self):
        from game.qwen_runtime import ContextTooLarge
        error=urllib.error.HTTPError('https://api.groq.com/x',413,'Too Large',Message(),io.BytesIO(b'{"error":{"message":"Request too large for model"}}'))
        with patch('game.paga_ai_providers.urllib.request.urlopen',side_effect=error),self.assertRaises(ContextTooLarge):
            providers.groq_generate([{'role':'user','content':'U'}])

    def test_truncated_answers_are_rejected(self):
        _,urlopen=self.capture({'candidates':[{'finishReason':'MAX_TOKENS','content':{'parts':[{'text':'{"oc'}]}}]})
        with patch('game.paga_ai_providers.urllib.request.urlopen',side_effect=urlopen),self.assertRaises(ValueError):
            providers.gemini_generate([{'role':'user','content':'U'}])

    def test_retry_delay_parsing(self):
        headers=Message();headers['retry-after']='7'
        self.assertEqual(providers._retry_after(headers,''),7)
        self.assertEqual(providers._retry_after(Message(),'{"retryDelay": "31s"}'),32)
        self.assertEqual(providers._retry_after(Message(),'Please try again in 1m2.5s'),63)
        self.assertEqual(providers._retry_after(None,''),60)

    def test_switch_values_are_booleans(self):
        for value,expected in [('true',True),('TRUE',True),('1',True),('"true"',True),('false',False),('0',False),('',False),('nie',False)]:
            with patch.dict(os.environ,{'PAGA_GROQ_ENABLED':value}):self.assertEqual(providers.flag('PAGA_GROQ_ENABLED'),expected,value)


if __name__=='__main__':unittest.main()
