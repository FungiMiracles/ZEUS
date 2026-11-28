"""PAGA AI rebuild: real run_tick -> detector -> task manager -> runner -> guard -> executor -> player routes.

Only the language model is replaced by a scripted stand-in; every decision it 'makes' is executed through the same
player operations and validations as a human. Isolated SQLite only.
"""
import json,unittest,fcntl
from datetime import datetime,timedelta
from decimal import Decimal
from tempfile import TemporaryDirectory
from unittest.mock import patch
from sqlalchemy import select,text,func
from extensions import db
import test_paga_ai_budget as budget_fixture
import test_paga_ai as ai_fixture
from game.paga_ai_models import PagaAiJob,PagaAiIdentity,PagaAiControl,PagaAiLog,PagaAiWrite,PagaAiGoal,PagaAiPlan,PagaAiMetric
from game.paga_ai_tasks import enqueue,pick,PRIORITY,now,housekeeping
from game.finance_models import StateBudget

REASON='Plan finansuje świadczenia społeczne i inwestycje infrastrukturalne zgodnie z priorytetami państwa.'
DONE={'ocena':'Nic więcej nie wymaga działania.','actions':[],'task_done':True}




def give_base_materials(country=1,count=1):
    """13 Nov 2026: rozmieszczenie bazy zużywa kamień i żelazo z magazynu — scenariusz dostaje surowce na `count` baz lądowych."""
    from extensions import db
    from game.commerce_models import ResourceStock
    from game.military_service import BASE_MATERIALS
    for code,need in BASE_MATERIALS['land'].items():
        row=db.session.get(ResourceStock,(country,code))
        if row is None:db.session.add(ResourceStock(panstwo_id=country,resource=code,quantity=need*count))
        else:row.quantity+=need*count
    db.session.commit()
class Scenario:
    """Shared helpers. Subclasses compose an existing isolated fixture (no inherited test methods)."""
    def ready(self):
        temporary=TemporaryDirectory();self.addCleanup(temporary.cleanup);self.app.root_path=temporary.name
    def quiet_review(self,minutes_ago=1):
        identity=db.session.get(PagaAiIdentity,1);identity.last_review_at=now()-timedelta(minutes=minutes_ago);db.session.commit()
    def tick(self,script,captured=None):
        from engine.paga_ai_scheduler import run_tick
        captured=[] if captured is None else captured
        sequence=iter(script)
        def model(messages,**kwargs):
            captured.append({'system':messages[0]['content'],'context':json.loads(messages[1]['content']),'schema':kwargs.get('schema')})
            stats=kwargs.get('stats')
            if stats is not None:stats.update(prompt_tokens=1200,prompt_ms=900,generated_tokens=80,generation_ms=400,seconds=1.5,peak_rss_bytes=10)
            item=next(sequence,DONE)
            if isinstance(item,Exception):raise item
            return item(captured[-1]) if callable(item) else item
        import paga_multi_ai_env
        first,second=paga_multi_ai_env.models(model)
        with first,second:run_tick(self.app)
        db.session.expire_all()
        return captured
    def tasks(self,**filters):
        return list(db.session.scalars(select(PagaAiJob).filter_by(**filters).order_by(PagaAiJob.id)))
    def only(self,*keep):
        """Leave just the tasks under test in the queue (fixtures also produce budget/research tasks)."""
        ids={task.id for task in keep}
        for task in db.session.scalars(select(PagaAiJob).where(PagaAiJob.status.in_(['PENDING','BLOCKED']),PagaAiJob.id.notin_(ids))):
            task.status='CANCELLED'
        db.session.commit()
    def collect(self):
        from engine.paga_ai_scheduler import collect
        collect(db.session);db.session.commit();db.session.expire_all()


class FinanceScenarioTests(Scenario,unittest.TestCase):
    """Budget, units, completion, double execution — on the finance fixture (real budget routes)."""
    WEIGHTS={'social_policy':8,'infrastructure':4,'healthcare':2,'reserve':2}
    def setUp(self):
        self.base=budget_fixture.BudgetAdapterTests();self.base.setUp();self.app=self.base.app;self.actor=self.base.actor;self.ready()
    def tearDown(self):self.base.tearDown()
    def plan(self,**extra):
        return {'ocena':'Budżet zgodny z priorytetami.','actions':[{'operation_id':'budget.plan','path':{},'data':{'pit_rate':15,'allocation_weights':self.WEIGHTS,'rationale':REASON,**extra}}],'task_done':True}

    # 4, 5, 7, 8, 9 — one model decision approves the budget; afterwards it is never approved again
    def test_budget_is_one_decision_then_completed_and_never_reapproved(self):
        self.quiet_review()
        captured=self.tick([self.plan(benefits_mld={'children':0.25,'seniors':0.25})])
        self.assertEqual(len(captured),1,'technical preview->approve needs no extra model call')
        context=captured[0]['context']
        self.assertEqual(context['zadanie']['rodzaj'],'budget');self.assertEqual(context['zadanie']['priorytet'],'MEDIUM')
        finance=context['dane_gry']['game_finance.page']
        self.assertFalse(finance['budżet_zatwierdzony']);self.assertIn('half_year_tax_revenue_mld',finance);self.assertNotIn('tax_total',json.dumps(finance))
        self.assertEqual(finance['expected_children_benefits_mld'],0.25)
        self.assertIn('budget.plan',context['możliwe_działania']);self.assertNotIn('game_finance.approve:POST',context['możliwe_działania'])
        task=self.tasks(kind='budget')[0]
        self.assertEqual(task.status,'COMPLETED');self.assertEqual(task.model_calls,1)
        self.assertTrue(any('Zatwierdzono budżet' in str(row.get('wynik')) for row in task.journal))
        self.assertEqual(db.session.query(StateBudget).count(),1)
        from game.social_benefits import BenefitPayment
        self.assertEqual(sum(row.paid for row in db.session.scalars(select(BenefitPayment))),Decimal('500000000'))
        # The same half-year never produces another budget task; a stray attempt is reported as finished.
        self.collect()
        self.assertEqual(len(self.tasks(kind='budget')),1)
        review=enqueue(db.session,1,'strategic_review','review:test',0,source='test');db.session.commit()
        self.quiet_review(10000)
        captured=self.tick([self.plan(benefits_mld={'children':0.3,'seniors':0.3})])
        self.assertEqual(db.session.query(StateBudget).count(),1)
        journal=db.session.get(PagaAiJob,review.id).journal
        self.assertTrue(any('już zrealizowany' in str(row.get('wynik')) or 'zatwierdzony' in str(row.get('wynik')) for row in journal),journal)

    def test_budget_completion_is_detected_without_a_model_call(self):
        self.quiet_review()
        self.collect()
        self.base.call('game_finance.preview:POST',{'pit_rate':15,'allocation_weights':self.WEIGHTS,'benefits_millions':{'children':250,'seniors':250}})
        self.assertEqual(self.base.call('game_finance.approve:POST',{'rationale':REASON})['status'],200)
        captured=self.tick([])
        self.assertEqual(captured,[])
        task=self.tasks(kind='budget')[0];self.assertEqual(task.status,'COMPLETED');self.assertIn('already_done',task.result)
        self.assertEqual(db.session.query(PagaAiMetric).filter_by(is_call=False,outcome='ALREADY_DONE').count(),1)

    # 15, 24 — a decision error goes back to the model once, with a compact reason; player validation decides
    def test_shortfall_needs_explicit_acceptance_and_is_corrected_in_one_round(self):
        self.quiet_review()
        def corrected(call):
            problem=call['context']['wymaga_korekty'][0]
            self.assertIn('niedobór',problem['błąd'])
            self.assertEqual(problem['twój_plan_po_przeliczeniu']['benefits_coverage_percent'],40.0)
            return self.plan(benefits_mld={'children':0.1,'seniors':0.1},accept_social_shortfall=True)
        self.tick([self.plan(benefits_mld={'children':0.1,'seniors':0.1}),corrected])
        task=self.tasks(kind='budget')[0]
        self.assertEqual((task.status,task.model_calls,task.retries),('COMPLETED',2,1))
        self.assertEqual(db.session.query(StateBudget).count(),1)

    def test_unaffordable_benefits_feedback_lists_the_ways_out(self):
        """Regression (UAT 10 Nov 2026, Tunganiria task 423): 4.5% social policy but 62.8 MLD of benefits, 'accept shortfall'."""
        self.quiet_review()
        def check(call):
            problem=call['context']['wymaga_korekty'][0]
            self.assertIn('Świadczenia przekraczają',problem['błąd'])
            text=problem['możliwości']
            self.assertIn('Zwiększ udział social_policy do ≥',text);self.assertIn('available_proportional',text);self.assertIn('nie pozwala wypłacić więcej',text)
            self.assertGreater(problem['twój_plan_po_przeliczeniu']['social_policy_share_needed_percent'],problem['twój_plan_po_przeliczeniu']['shares_percent']['social_policy'] and 5)
            return self.plan(benefit_policy='available_proportional',accept_social_shortfall=True)
        self.tick([self.plan(benefits_mld={'children':0.25,'seniors':0.25},accept_social_shortfall=True,allocation_weights={'social_policy':1,'reserve':19}),check])
        task=self.tasks(kind='budget')[0]
        self.assertEqual((task.status,task.model_calls),('COMPLETED',2));self.assertEqual(db.session.query(StateBudget).count(),1)

    def test_standard_game_validation_still_rejects_unaffordable_benefits(self):
        self.quiet_review()
        self.tick([self.plan(benefits_mld={'children':5,'seniors':5},accept_social_shortfall=True)]*3)
        task=self.tasks(kind='budget')[0]
        self.assertEqual(task.status,'FAILED');self.assertIn('Świadczenia przekraczają',task.error)
        self.assertEqual(db.session.query(StateBudget).count(),0)

    # 9 — units
    def test_money_is_shown_in_mld_and_converted_back_exactly(self):
        from game.paga_ai_context import finance_view,to_mld
        from game.paga_ai_runner import millions
        view=finance_view({'state':{'year':3001,'period':2,'approved':True,'budget_id':15,'tax_total':'172302115672.50','budget_total':'172302115672.50',
                                    'allocations':{'social_policy':'34805027365.84'},'benefits':{'expected':{'children':'38130906757.86','seniors':'59919992189.60'},'paid':{'children':'100000000.00','seniors':'100000000.00'}}}})
        # Two decimals in the decision context (0.01 MLD = 10 mln), administrator decision 10 Nov 2026.
        self.assertEqual(view['half_year_tax_revenue_mld'],172.3);self.assertEqual(view['social_policy_allocation_mld'],34.81)
        self.assertEqual(view['expected_children_benefits_mld'],38.13);self.assertEqual(view['expected_seniors_benefits_mld'],59.92)
        self.assertEqual(view['benefits_coverage_percent'],0.2);self.assertIn('Nie zatwierdzaj',view['uwaga'])
        self.assertEqual(millions(0.25),250.0);self.assertEqual(millions('38.130906757'),38130.906757);self.assertEqual(to_mld('999999999'),1.0)

    def test_research_view_lists_real_codes_points_and_limits(self):
        """UAT 10 Nov 2026: the model invested in invented nodes (research_lab_1a) with 0 points."""
        from game.paga_ai_context import research_view,read
        from game.industry_catalog import TECHNOLOGIES
        view=research_view({'points':0,'pointPrice':400000000,'budget':'1000000000','technologies':{'method':{'label':'Metoda badawcza','parent':None},
                            'arms_industry':{'label':'Przemysł zbrojeniowy','parent':'method'},'air_filters':{'label':'Filtry','parent':'method','available':False}},
                            'nodes':{'method':{'level':0,'required':25,'progress':0,'maximum':False},'arms_industry':{'level':0,'required':25,'progress':0,'maximum':False},
                                     'air_filters':{'level':0,'required':0,'progress':0,'maximum':False}}})
        self.assertEqual(view['technologie_do_inwestycji'],[{'node':'method','nazwa':'Metoda badawcza','brakuje_punktów':25}],'children of undeveloped parents and planned techs are hidden')
        self.assertEqual((view['cena_punktu_mld'],view['budżet_badań_mld']),(0.4,1.0));self.assertIn('najpierw buy',view['jak_działa'])
        real=read(self.app,self.actor,'game_research.state:GET',step=1,model_id='test')
        self.assertTrue(all(item['node'] in TECHNOLOGIES for item in real['technologie_do_inwestycji']))
        self.assertLessEqual(len(json.dumps(real,ensure_ascii=False)),1500)

    def test_answer_texts_are_bounded_for_one_model_answer(self):
        from game.paga_ai_runner import ANSWER_TOKENS
        from game.paga_ai_contracts import schema
        self.assertEqual(ANSWER_TOKENS,640)
        self.assertEqual(schema('game_forum.page:POST')['properties']['content']['maxLength'],500)
        self.assertTrue(all(variant['properties']['content']['maxLength']==600 for variant in schema('game_messages.send:POST')['anyOf']))
        self.quiet_review()
        captured=self.tick([DONE])
        top=captured[0]['schema']['properties']
        self.assertEqual((top['ocena']['maxLength'],top['memory']['maxLength']),(120,120))

    # 23 — never executed twice
    def test_same_decision_is_never_executed_twice(self):
        from game.paga_ai_guard import guarded_write
        task=enqueue(db.session,1,'strategic_review','review:dup',0,source='test');db.session.commit()
        actor=self.actor.__class__(1,self.actor.user_id,0,task.id)
        data={'content':'Zapraszamy do współpracy gospodarczej i rozmów o handlu.','recipient_id':2}
        first=guarded_write(self.app,actor,task.id,'game_forum.page:POST',{},data,step=1,model_id='test')
        second=guarded_write(self.app,actor,task.id,'game_forum.page:POST',{},data,step=2,model_id='test')
        self.assertEqual(first['outcome'],'OK');self.assertEqual(second['validation'],'ALREADY_DONE')
        from game.forum_models import ForumMessage
        self.assertEqual(db.session.query(ForumMessage).count(),1)
        # The same text in another task is a duplicate message, not a new statement.
        other=enqueue(db.session,1,'forum_mention','mention:x',0,source='test');db.session.commit()
        again=guarded_write(self.app,actor.__class__(1,actor.user_id,0,other.id),other.id,'game_forum.page:POST',{},data,step=1,model_id='test')
        self.assertEqual(again['validation'],'DUPLICATE');self.assertEqual(db.session.query(ForumMessage).count(),1)

    def test_parallel_worker_does_not_start_a_second_model(self):
        self.quiet_review();self.collect()
        root=self.app.root_path+'/runtime/qwen';import os;os.makedirs(root,exist_ok=True)
        # PAGA MULTI-AI: the budget belongs to the strategic lane (Gemini); a busy worker of that lane blocks a second one.
        with open(root+'/worker-gemini.lock','a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            captured=self.tick([self.plan(benefits_mld={'children':0.25,'seniors':0.25})])
        self.assertEqual([call for call in captured if call['context']['zadanie']['rodzaj']=='budget'],[]);self.assertEqual(db.session.query(StateBudget).count(),0)
        # The local model's lock (busy Qwen) never blocks the other lanes.
        with open(root+'/worker.lock','a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.tick([self.plan(benefits_mld={'children':0.25,'seniors':0.25})])
        self.assertEqual(db.session.query(StateBudget).count(),1)

    # 22 — restart: an interrupted write is verified with the model, not replayed blindly
    def test_interrupted_write_is_verified_not_replayed(self):
        from game.paga_ai_guard import decision_hash
        from game.forum_models import ForumMessage
        self.quiet_review()
        task=enqueue(db.session,1,'forum_mention','mention:restart',0,source='test')
        task.status='RUNNING';task.claimed_at=now()-timedelta(hours=2);task.attempts=1
        data={'content':'Stanowisko naszego państwa w sprawie bezpieczeństwa regionu.','recipient_id':2}
        db.session.add(PagaAiWrite(job_id=task.id,country_id=1,operation='game_forum.page:POST',decision_hash=decision_hash('game_forum.page:POST',{},data),request_id='r-restart',status='PENDING'))
        db.session.commit();self.collect();self.only(task)
        def decide_again(call):
            problems=call['context']['wymaga_korekty']
            self.assertEqual(problems[0]['rodzaj'],'UNKNOWN');self.assertIn('nieznany',problems[0]['błąd'])
            return {'ocena':'Stan nie pokazuje wpisu; publikujemy.','actions':[{'operation_id':'game_forum.page:POST','path':{},'data':data}],'task_done':True}
        captured=self.tick([decide_again])
        self.assertEqual(len(captured),1)
        self.assertEqual(db.session.query(ForumMessage).count(),1)
        row=db.session.scalar(select(PagaAiWrite).where(PagaAiWrite.request_id=='r-restart'))
        self.assertEqual(row.status,'DONE','the same request_id is reused after verification')

    def test_oversized_prompt_is_retried_with_a_tighter_context(self):
        from game.qwen_runtime import ContextTooLarge
        from game.paga_ai_context import TIGHT_BUDGET
        self.quiet_review()
        captured=self.tick([ContextTooLarge('request (4123 tokens) exceeds the available context size (4096 tokens)'),
                            {'ocena':'Budżet zgodny z priorytetami.','actions':[{'operation_id':'budget.plan','path':{},'data':{'pit_rate':15,'allocation_weights':{'social_policy':8,'infrastructure':4,'healthcare':2,'reserve':2},'benefits_mld':{'children':0.25,'seniors':0.25},'rationale':REASON}}],'task_done':True}])
        self.assertEqual(len(captured),2);self.assertLessEqual(len(json.dumps(captured[1]['context'],ensure_ascii=False)),TIGHT_BUDGET)
        task=self.tasks(kind='budget')[0]
        self.assertEqual((task.status,task.model_calls,task.attempts),('COMPLETED',1,1));self.assertEqual(db.session.query(StateBudget).count(),1)

    def test_low_memory_postpones_without_using_an_attempt(self):
        self.quiet_review()
        self.tick([MemoryError('Za mało dostępnej pamięci')])
        task=self.tasks(kind='budget')[0]
        self.assertEqual((task.status,task.attempts),('PENDING',0));self.assertGreater(task.not_before,now())
        self.assertEqual(db.session.query(PagaAiMetric).filter_by(is_call=True,outcome='NO_MEMORY').count(),1)

    # 21 — timeouts are technical, bounded and measured
    def test_model_timeout_is_retried_later_then_fails(self):
        self.quiet_review()
        self.tick([TimeoutError('timed out')])
        task=self.tasks(kind='budget')[0]
        self.assertEqual(task.status,'PENDING');self.assertGreater(task.not_before,now());self.assertIn('Timeout',task.error)
        self.assertEqual(db.session.query(PagaAiMetric).filter_by(is_call=True,outcome='TIMEOUT').count(),1)
        for _ in range(2):
            task=db.session.get(PagaAiJob,task.id);task.not_before=None;db.session.commit()
            self.tick([TimeoutError('timed out')])
        self.assertEqual(db.session.get(PagaAiJob,task.id).status,'FAILED')
        from game.paga_ai_metrics import summary
        self.assertEqual(summary(db.session)['timeouts'],3)


class AiScenarioTests(Scenario,unittest.TestCase):
    """Detection, priorities, communication, war, plans, goals, isolation, injection — on the AI fixture."""
    def setUp(self):
        self.base=ai_fixture.AiTests();self.base.setUp();self.app=self.base.app;self.actor=self.base.actor;self.fixture=self.base.fixture;self.ready()
    def tearDown(self):self.base.tearDown()

    def test_military_view_keeps_decision_facts_from_the_whole_world_page(self):
        from game.paga_ai_military import military_view
        regions={str(index):{'name':f'R{index}','countryId':1 if index<3 else 7 if index<6 else 99,'coastal':index%2==0,'point':[0,0]} for index in range(1,400)}
        config={'countryId':1,'controlledCountryIds':[1],'enemyIds':[7],'countries':{'1':'Hopia','7':'Ozilandia','99':'Inny'},'regions':regions,
                'cities':{'5':{'name':'Wrogie Miasto','countryId':7,'regionId':'4'}},'missiles':{'short':{'label':'K','count':20}},'groundInventory':{'soldiers':900},
                'bases':[{'id':11,'kind':'land','regionId':1,'countryId':1,'level':1,'garrison':{'soldiers':100},'operational':True}],
                'visibleBases':[{'id':11,'countryId':1},{'id':12,'kind':'air','regionId':4,'countryId':7}],'defenses':[{'id':3,'countryId':1,'targetKind':'base','targetId':11,'level':1,'ammunition':5}],
                'landTargets':[3,4]}
        view=military_view({'game_data':[config],'visible_text':'x'*5000})
        self.assertEqual([row['region_id'] for row in view['nasze_regiony']],[1,2]);self.assertEqual(view['nasze_bazy'][0]['base_id'],11)
        self.assertEqual(view['regiony_przeciwnika'][0]['państwo'],'Ozilandia');self.assertEqual(view['miasta_przeciwnika'][0]['city_id'],5)
        self.assertEqual(view['znane_bazy_przeciwnika'],[{'base_id':12,'rodzaj':'air','region_id':4,'państwo':'Ozilandia'}])
        self.assertEqual(view['nasza_obrona_przeciwrakietowa'][0]['defense_id'],3);self.assertEqual(view['rakiety'],{'short':20})
        self.assertLess(len(json.dumps(view,ensure_ascii=False)),2500,'a whole-world page shrinks to the decision facts')

    def test_attack_task_sees_own_forces_and_exact_order_shapes(self):
        """Regression (UAT 10 Nov 2026, tasks 359–361): invented base/region numbers, missing kind, text in number fields."""
        from game.military_models import MilitaryBase
        from game.forum_models import ForumMessage
        give_base_materials()
        deploy=self.base.call('game_military.defense_change:POST',{'action':'deploy','kind':'land','region_id':1,'x':10,'y':10,'garrison':{'soldiers':100,'launchers':1}})
        self.assertEqual(deploy['status'],200,deploy)
        base=db.session.scalar(select(MilitaryBase))
        self.quiet_review();task=enqueue(db.session,1,'under_attack','event:attack',0,source='test');db.session.commit();self.only(task)
        def decide(call):
            facts=json.dumps(call['context']['dane_gry'],ensure_ascii=False)
            self.assertIn(f'"base_id": {base.id}',facts);self.assertIn('nasze_regiony',facts)
            choices={choice['properties']['operation_id']['enum'][0]:choice['properties']['data'] for choice in call['schema']['properties']['actions']['items']['anyOf']}
            orders=choices['game_military.war_order:POST']['anyOf']
            self.assertEqual({variant['properties']['kind']['enum'][0] for variant in orders},{'land','missile','air','naval'})
            missile=next(variant for variant in orders if variant['properties']['kind']['enum']==['missile'])
            self.assertIn('region_id',missile['required']);self.assertEqual(missile['properties']['region_id']['type'],'integer')
            defense={variant['properties']['action']['enum'][0]:variant for variant in choices['game_military.defense_change:POST']['anyOf']}
            self.assertEqual(defense['defense_upgrade']['required'],['action','defense_id'])
            diplomacy=choices['game_diplomacy.create_action:POST']['anyOf']
            self.assertTrue(any('enum' in variant['properties'].get('relation_id',{}) for variant in diplomacy))
            self.assertIn('adresaci',facts)
            # A small model writes 0 for "no parent post": the post must still be published.
            return {'ocena':'Apelujemy o pokój.','actions':[{'operation_id':'game_forum.page:POST','path':{},'data':{'content':'Wzywamy do natychmiastowego zawieszenia broni.','reply_to_id':0,'recipient_id':0}}],'task_done':True}
        self.assertEqual(len(self.tick([decide])),1)
        post=db.session.scalar(select(ForumMessage).where(ForumMessage.user_id==self.actor.user_id))
        self.assertIsNotNone(post);self.assertIsNone(post.reply_to_id);self.assertEqual(self.tasks(kind='under_attack')[0].status,'COMPLETED')

    def test_addressees_use_player_ids_not_country_ids(self):
        from game.paga_ai_military import addressees_view
        view=addressees_view({'items':[{'id':1,'name':'oskar','country_id':7,'country_name':'Ozilandia','flag_path':'f'}]})
        self.assertEqual(view['adresaci'],[{'recipient_id':1,'państwo':'Ozilandia','country_id':7}]);self.assertIn('nie numer państwa',view['uwaga'])

    def test_forum_reply_gets_the_exact_post_to_answer(self):
        """Regression (UAT 9 Nov 2026, task 352): replies used the task number as reply_to_id and got a bare 404."""
        from game.forum_models import ForumMessage
        self.quiet_review()
        for index in range(3):db.session.add(PagaAiJob(country_id=1,trigger=f'old:{index}',revision=0,status='COMPLETED',kind='legacy'))
        db.session.commit()
        self.fixture.login(2)
        self.assertEqual(self.fixture.post('/game/forum',content='Hej, Hopia. Co tam?',recipient_id=str(self.actor.user_id)).status_code,303)
        post=db.session.scalar(select(ForumMessage).order_by(ForumMessage.id.desc()))
        self.collect();self.only(*self.tasks(kind='forum_reply'))
        def answer(call):
            how=call['context']['zadanie']['jak_odpowiedzieć']
            self.assertEqual(how['data'],{'reply_to_id':post.id});self.assertNotIn('id',call['context']['zadanie'])
            self.assertIn('Co tam',json.dumps(call['context']['zadanie']['szczegóły'],ensure_ascii=False))
            return {'ocena':'Odpowiadamy uprzejmie.','actions':[{'operation_id':'game_forum.page:POST','path':{},'data':{'content':'Witamy Ozilandię, u nas spokojnie.','reply_to_id':how['data']['reply_to_id']}}],'task_done':True}
        self.assertEqual(len(self.tick([answer])),1)
        reply=db.session.scalar(select(ForumMessage).where(ForumMessage.user_id==self.actor.user_id))
        self.assertEqual(reply.reply_to_id,post.id);self.assertEqual(self.tasks(kind='forum_reply')[0].status,'COMPLETED')

    def test_private_message_to_ai_raises_no_reply_task(self):
        """26 Nov 2026: państwa PAGA nie piszą wiadomości prywatnych — wiadomość od gracza nie tworzy zadania odpowiedzi."""
        from game.communication_models import PrivateMessage
        self.quiet_review();self.fixture.login(2)
        self.assertEqual(self.fixture.post('/game/wiadomosci',recipient_id=str(self.actor.user_id),content='Czy możemy porozmawiać?').status_code,201)
        self.collect()
        self.assertEqual(self.tasks(kind='private_message'),[])
        self.assertEqual(db.session.query(PrivateMessage).filter_by(sender_user_id=self.actor.user_id).count(),0)

    def test_reply_recipient_only_from_own_inbox(self):
        """Regression (UAT 10 Nov 2026, task 358): recipient_id is filled only for messages from our own inbox."""
        from game.communication_models import PrivateMessage
        from game.paga_ai_quotes import prepare
        other=PrivateMessage(sender_user_id=2,recipient_user_id=3,sender_country_id=2,recipient_country_id=3,sender_name='B',recipient_name='C',sender_country_name='B',recipient_country_name='C',sender_flag_path='f',recipient_flag_path='f',content='Cudza')
        db.session.add(other);db.session.commit()
        self.assertNotIn('recipient_id',prepare(self.actor,'game_messages.send:POST',{},{'content':'x','reply_to_id':other.id}))

    def test_missing_object_is_reported_clearly(self):
        task=enqueue(db.session,1,'forum_reply','forum:9999',0,source='test');db.session.commit()
        from game.paga_ai_guard import guarded_write
        result=guarded_write(self.app,self.actor.__class__(1,self.actor.user_id,0,task.id),task.id,'game_forum.page:POST',{},{'content':'Odpowiedź na nieistniejący wpis.','reply_to_id':9999},step=1,model_id='test')
        self.assertGreaterEqual(result['status'],400);self.assertIn('Nie znaleziono wskazanego obiektu',result['reason'])

    def test_loan_request_shows_loan_number_direction_and_amount(self):
        """Regression (UAT 9 Nov 2026, task 350): the model used the task number 350 as loan_id instead of loan 4."""
        from game.loan_models import StateLoan
        from game.loans import notify
        self.quiet_review()
        for index in range(3):db.session.add(PagaAiJob(country_id=1,trigger=f'old:{index}',revision=0,status='COMPLETED',kind='legacy'))  # task ids ≠ loan ids
        loan=StateLoan(borrower_id=2,lender_id=1,requested_by=2,amount=Decimal('1000000000.00'),status='pending',request_id='r-1');db.session.add(loan);db.session.flush()
        notify(db.session,1,'Kraj B prosi o 1000000000.00 ROI. Zaakceptuj lub odrzuć w panelu budżetu.');db.session.commit()
        self.collect();self.only(*self.tasks(kind='loan_event'))
        def decide(call):
            context=call['context']
            self.assertNotIn('id',context['zadanie'],'internal task numbers are never shown to the model')
            case=context['dane_gry']['dotyczy']['pożyczki'][0]
            self.assertEqual((case['loan_id'],case['kwota_mld'],case['nasze_możliwe_decyzje']),(loan.id,1.0,['accept','reject']))
            self.assertIn('prosi NASZE państwo',case['kierunek'])
            return {'ocena':'Odmawiamy pożyczki.','actions':[{'operation_id':'game_loans.change:POST','path':{},'data':{'action':'reject','loan_id':case['loan_id']}}],'task_done':True}
        captured=self.tick([decide])
        self.assertEqual(len(captured),1)
        self.assertEqual(db.session.get(StateLoan,loan.id).status,'rejected','the decision reached the real loan through the player route')
        self.assertEqual(self.tasks(kind='loan_event')[0].status,'COMPLETED')

    def test_generator_news_and_roads_are_excluded_for_ai(self):
        """Administrator decision 10 Nov 2026: no Event Generator news, no road operations for PAGA AI."""
        from game.forum_models import GameNotification
        from game.event_models import GeneratedEventSnapshot
        from game.civic_models import Road
        identity=db.session.get(PagaAiIdentity,1)
        snapshot=GeneratedEventSnapshot(source_event_id=1,country_id=1,country_name='A',region_name='R',event_type='Powódź',content='Powódź w regionie R.',effects=[],entenda_date=datetime(2990,1,1).date(),created_at=now())
        db.session.add(snapshot);db.session.flush()
        db.session.add_all([GameNotification(user_id=identity.user_id,notification_type='GENERATED_EVENT',generated_event_id=snapshot.id),
                            GameNotification(user_id=identity.user_id,notification_type='SYSTEM',system_text='Droga: sąsiad proponuje drogę graniczną.')])
        db.session.commit();self.quiet_review(10000);self.collect()
        self.assertEqual(self.tasks(kind='domestic_event'),[]);self.assertEqual(self.tasks(kind='infrastructure_event'),[])
        self.assertGreater(db.session.get(PagaAiIdentity,1).notification_cursor,0,'ignored notices are consumed, not left pending')
        roads={'operation_id':'game_infrastructure.roads_change:POST','path':{'operation':'buduj'},'data':{'kind':'road','start':[0,0],'end':[1,1]}}
        captured=self.tick([{'ocena':'Budujemy drogę.','actions':[roads],'task_done':True},DONE])
        context=captured[0]['context']
        names={choice['properties']['operation_id']['enum'][0] for choice in captured[0]['schema']['properties']['actions']['items']['anyOf']}
        for blocked in ('game_infrastructure.roads_change:POST','game_infrastructure.roads_state:GET','game_newspaper.page:GET'):
            self.assertNotIn(blocked,names);self.assertNotIn(blocked,json.dumps(context,ensure_ascii=False))
        self.assertEqual(db.session.query(Road).count(),0)
        review=self.tasks(kind='strategic_review')[0]
        self.assertTrue(any('wyłączona dla PAGA AI' in str(row.get('wynik')) for row in review.journal),review.journal)
        from game.paga_ai_context import DOMAINS
        self.assertIn('game_diplomacy.world_news:GET',DOMAINS['diplomacy']['more'],'diplomatic world news stay available')

    # 1 — every game notification producer maps to a task kind (texts pinned)
    def test_notification_texts_map_to_task_kinds(self):
        from game.paga_ai_detector import classify_text
        cases={'Państwo Kraj B przeprowadziło atak na cel: Baza. Liczba pocisków: 2.':'under_attack',
               'Twoja baza Północ została zniszczona. Garnizon został utracony.':'military_loss',
               'Atak na statek handlowy #4: utracono 20 pkt życia.':'military_loss',
               'Zakończono nasz atak na cel: Most (Kraj B). Liczba pocisków: 1.':'military_report',
               'Działania hybrydowe: Sabotaż — region X. Sabotaż zakończony powodzeniem.':'hybrid_detected',
               'Wywiad wojskowy: Rozpoznanie — region X. Misja zakończona powodzeniem.':'intelligence_report',
               'Brakuje pieniędzy na utrzymanie wojska. System proporcjonalnie wycofał…':'military_funding',
               'Silos A został czasowo wyłączony: brak środków na utrzymanie.':'military_funding',
               'Elektrownia #3: produkcja energii została wstrzymana — brak paliwa lub uszkodzenie.':'energy_shortage',
               'Fabryka #7: produkcja została wstrzymana — brak surowców lub uszkodzenie.':'production_stopped',
               'Węgiel #2: wydobycie zatrzymane — wyczerpano złoże w regionie.':'resource_event',
               'Pożyczka: przyznano 2 MLD.':'loan_event','Droga: budowa zakończona.':'infrastructure_event',
               'Obywatele nie są zadowoleni z wysokiej stawki podatku. Zaufanie do władzy: -2':'social_unrest',
               'Kraj B zakupił/a 10 Stal za 5,00 ROI. Cło portowe: 0,00 ROI':'trade_event','Coś zupełnie nowego.':'system_notice'}
        for textual,kind in cases.items():
            with self.subTest(text=textual):self.assertEqual(classify_text(textual),kind)

    # 1, 2 — inbox detection, merge of repeated facts, semantic dedup
    def test_inbox_detection_merges_repeated_facts_and_dedups(self):
        from game.forum_models import GameNotification
        identity=db.session.get(PagaAiIdentity,1)
        for message in ('Pożyczka: przyznano 1 MLD.','Pożyczka: rata spłacona.','Fabryka #7: produkcja została wstrzymana — brak surowców lub uszkodzenie.'):
            db.session.add(GameNotification(user_id=identity.user_id,notification_type='SYSTEM',system_text=message))
        db.session.add(GameNotification(user_id=2,notification_type='SYSTEM',system_text='Pożyczka: inny kraj.'))
        db.session.commit();self.collect();self.collect()
        loans=self.tasks(kind='loan_event');self.assertEqual(len(loans),1)
        self.assertEqual(len(loans[0].context['zdarzenia']),2);self.assertNotIn('inny kraj',json.dumps(loans[0].context,ensure_ascii=False))
        self.assertEqual(len(self.tasks(kind='production_stopped')),1)
        self.assertIsNone(enqueue(db.session,1,'loan_event',loans[0].trigger,0))

    # 3 — priorities, ageing, guaranteed review
    def test_priority_order_ageing_and_guaranteed_review_under_load(self):
        control=db.session.get(PagaAiControl,1);moment=now()
        for index in range(25):enqueue(db.session,1,'diplomatic_proposal',f'proposal:{index}',0,source='test')
        review=enqueue(db.session,1,'strategic_review','review:load',0,source='test');db.session.commit()
        self.assertEqual(pick(db.session,control,moment,[1]).id,review.id,'overdue review beats a busy HIGH queue')
        self.quiet_review()
        self.assertEqual(pick(db.session,control,moment,[1]).kind,'diplomatic_proposal')
        old=enqueue(db.session,1,'trade_event','note:old',0,source='test');old.created_at=moment-timedelta(hours=4);db.session.commit()
        self.assertEqual(pick(db.session,control,moment,[1]).id,old.id,'a long-waiting LOW task is not starved')
        attack=enqueue(db.session,1,'under_attack','event:1',0,source='test');db.session.commit()
        self.assertEqual(pick(db.session,control,moment,[1]).id,attack.id)

    def test_review_is_scheduled_by_the_configured_cadence(self):
        control=db.session.get(PagaAiControl,1);control.review_interval_minutes=60;db.session.commit()
        self.quiet_review(30);self.collect();self.assertEqual(self.tasks(kind='strategic_review'),[])
        self.quiet_review(61);self.collect();self.assertEqual(len(self.tasks(kind='strategic_review')),1)
        self.collect();self.assertEqual(len(self.tasks(kind='strategic_review')),1,'one open review at a time')

    # 10, 20 — reaction to a message; injection stays data; one reply per message
    def test_ai_cannot_send_private_messages(self):
        """26 Nov 2026: także zadanie forum nie może wysłać wiadomości prywatnej (operacja poza zakresem, endpoint odmawia)."""
        from game.communication_models import PrivateMessage
        self.quiet_review()
        task=enqueue(db.session,1,'forum_mention','mention:pm',0,source='test');db.session.commit();self.only(task)
        attempt={'ocena':'x','actions':[{'operation_id':'game_messages.send:POST','path':{},'data':{'content':'Piszemy prywatnie.','recipient_id':2}}],'task_done':True}
        self.tick([attempt,DONE])
        self.assertEqual(db.session.query(PrivateMessage).filter_by(sender_user_id=self.actor.user_id).count(),0)

    def test_review_initiates_communication_and_conflict(self):
        from game.communication_models import PrivateMessage
        from game.diplomacy_models import DiplomaticAction
        # Game rule (unchanged): war needs a prior worsening of relations — done here as an ordinary player step.
        self.assertEqual(self.base.call('game_diplomacy.create_action:POST',{'kind':'RELATION','target_id':2,'relation_id':10})['status'],201)
        decision={'ocena':'Kraj B zagraża naszym interesom; ostrzegamy i przechodzimy do wojny.','actions':[
            {'operation_id':'game_diplomacy.create_action:POST','path':{},'data':{'kind':'WAR','target_id':2}}],'task_done':True,'memory':'Wypowiedzieliśmy wojnę Krajowi B po ostrzeżeniu.'}
        captured=self.tick([decision])
        self.assertEqual(captured[0]['context']['zadanie']['rodzaj'],'strategic_review')
        self.assertIn('game_military.war_order:POST',captured[0]['context']['możliwe_działania'])
        self.assertEqual(db.session.query(PrivateMessage).count(),0)   # 26 Nov 2026: PAGA nie pisze wiadomości prywatnych
        self.assertEqual(db.session.scalar(select(DiplomaticAction.kind).order_by(DiplomaticAction.id.desc()).limit(1)),'WAR')
        review=self.tasks(kind='strategic_review')[0];self.assertEqual(review.status,'COMPLETED')
        identity=db.session.get(PagaAiIdentity,1)
        self.assertIsNotNone(identity.last_review_at);self.assertIn('wojnę',identity.strategy['notes'][-1])

    # 13 + conditional plans — critical reaction; a model-authorised plan runs once without a model call
    def test_attack_triggers_conditional_plan_once_then_critical_task(self):
        from game.autonomy_models import AutonomyEvent
        from game.military_models import MilitaryBase
        deploy={'action':'deploy','kind':'land','region_id':1,'x':10,'y':10,'garrison':{'soldiers':100,'launchers':1}}
        give_base_materials()
        plan={'ocena':'Przygotowujemy obronę.','actions':[{'operation_id':'plan.conditional','path':{},'data':{'condition':{'type':'attacked_by','country_id':2},'operation_id':'game_military.defense_change:POST','path':{},'data':deploy,'valid_game_days':10,'note':'Baza obronna po ataku Kraju B'}}],'task_done':True}
        self.tick([plan])
        self.assertEqual(db.session.scalar(select(PagaAiPlan.status)),'ACTIVE')
        self.quiet_review()
        for index in range(2):
            db.session.add(AutonomyEvent(source_key=f'flight:{index}',kind='BOMBARDMENT',actor_id=2,target_id=1,occurred_at=datetime(2990,1,1),public=True,audience=[],payload={}))
        db.session.commit()
        captured=self.tick([])
        self.assertEqual(captured,[],'the authorised plan needs no model call')
        self.assertEqual(db.session.scalar(select(PagaAiPlan.status)),'FIRED');self.assertEqual(db.session.query(MilitaryBase).count(),1)
        attack=self.tasks(kind='under_attack');self.assertEqual(len(attack),1);self.assertEqual(attack[0].priority,PRIORITY['CRITICAL'])
        self.assertEqual(len(attack[0].context['zdarzenia']),1,'repeated identical labels merge into the open task')
        captured=self.tick([DONE])
        self.assertEqual(captured[0]['context']['zadanie']['rodzaj'],'under_attack')
        self.assertEqual(db.session.query(MilitaryBase).count(),1,'the plan never runs twice')
        self.assertEqual(len(self.tasks(kind='plan_result')),1)

    # 14 — goals: creation, decomposition, intentions, monitoring by ZEUS, decision by the model
    def test_goal_decomposition_intent_and_monitoring(self):
        decision={'ocena':'Budujemy potencjał badawczy.','actions':[
            {'operation_id':'goal.create','path':{},'data':{'title':'Przewaga technologiczna','description':'Rozwój badań i przemysłu.','priority':1,'criteria':[{'metric':'research_points','op':'>=','value':1}]}},
            {'operation_id':'goal.create','path':{},'data':{'title':'Zakup punktów badań','parent_id':1,'priority':2}},
            {'operation_id':'intent.create','path':{},'data':{'note':'Sprawdź postęp badań i zdecyduj o zakupie.','goal_id':1,'domain':'economy','when':{'type':'after_game_days','days':1}}}],'task_done':True}
        self.tick([decision])
        goals=list(db.session.scalars(select(PagaAiGoal).order_by(PagaAiGoal.id)))
        self.assertEqual([(goal.title,goal.parent_id) for goal in goals],[('Przewaga technologiczna',None),('Zakup punktów badań',1)])
        self.assertEqual(db.session.scalar(select(PagaAiPlan.kind)),'INTENT')
        self.quiet_review()
        import game.finance_service as finance
        later=finance.game_now()+timedelta(days=2)
        with patch('game.finance_service.game_now',return_value=later):
            identity=db.session.get(PagaAiIdentity,1);identity.last_probe_at=None;db.session.commit()
            self.collect();self.only(*self.tasks(kind='intent'))
            captured=self.tick([{'ocena':'Cel osiągnięty.','actions':[{'operation_id':'goal.update','path':{},'data':{'goal_id':2,'status':'ACHIEVED','note':'Zakupiono punkty.'}}],'task_done':True}])
        call=captured[0]['context']
        self.assertEqual(call['zadanie']['rodzaj'],'intent');self.assertIn('Sprawdź postęp',call['zadanie']['cel_zadania'])
        monitored=next(goal for goal in call['cele_strategiczne'] if goal['id']==1)
        self.assertEqual(monitored['postęp'][0]['metric'],'research_points');self.assertIn(monitored['postęp'][0]['spełnione'],(True,False))
        self.assertEqual(self.tasks(kind='intent')[0].goal_id,1)
        self.assertEqual(db.session.get(PagaAiGoal,2).status,'ACHIEVED');self.assertEqual(db.session.get(PagaAiGoal,1).status,'ACTIVE','ZEUS never closes goals itself')

    def test_goal_grammar_follows_the_countrys_real_goals(self):
        """Regression (UAT 10 Nov 2026, Tunganiria task 422): parent_id 1 with no goals; unmeasurable criteria."""
        from game.paga_ai_runner import decision_schema
        from game.paga_ai_strategy import apply
        def shapes():
            choices=decision_schema(self.app,['goal.create','goal.update','intent.create'],[],1)['properties']['actions']['items']['anyOf']
            return {choice['properties']['operation_id']['enum'][0]:choice['properties']['data'] for choice in choices}
        first=shapes()
        self.assertNotIn('parent_id',first['goal.create']['properties']);self.assertNotIn('goal.update',first);self.assertNotIn('goal_id',first['intent.create']['properties'])
        metrics=first['goal.create']['properties']['criteria']['items']['properties']['metric']['enum']
        self.assertIn('gdp_mld',metrics);self.assertIn('technology:method',metrics);self.assertIn('army:czolgi_ilosc',metrics);self.assertIn('at_war_with:2',metrics)
        self.assertNotIn('regional_influence',metrics)
        task=enqueue(db.session,1,'strategic_review','review:goals',0,source='test');db.session.commit()
        ok,message=apply(db.session,self.actor,task,'goal.create',{'title':'Hegemonia regionalna','parent_id':1});db.session.rollback()
        self.assertFalse(ok);self.assertIn('Istniejące cele: brak',message);self.assertIn('pomiń parent_id',message)
        ok,_=apply(db.session,self.actor,task,'goal.create',{'title':'Hegemonia regionalna'});db.session.commit();self.assertTrue(ok)
        goal_id=db.session.scalar(select(PagaAiGoal.id))
        second=shapes()
        self.assertEqual(second['goal.create']['properties']['parent_id']['enum'],[goal_id]);self.assertEqual(second['goal.update']['properties']['goal_id']['enum'],[goal_id])
        db.session.add(PagaAiGoal(country_id=2,title='Cudzy',status='ACTIVE'));db.session.commit()
        self.assertEqual(shapes()['goal.create']['properties']['parent_id']['enum'],[goal_id],'never another country\'s goals')

    def test_zero_means_no_parent_goal(self):
        from game.paga_ai_strategy import apply
        task=enqueue(db.session,1,'strategic_review','review:zero',0,source='test');db.session.commit()
        ok,summary=apply(db.session,self.actor,task,'goal.create',{'title':'Bez nadrzędnego','parent_id':0});db.session.commit()
        self.assertTrue(ok,summary);self.assertIsNone(db.session.scalar(select(PagaAiGoal.parent_id)))

    # 6, 19 — isolation of tasks, goals, plans and memory between countries
    def test_context_never_contains_other_countries_strategy(self):
        db.session.add_all([PagaAiGoal(country_id=2,title='TAJNY_CEL_INNEGO',description='x',priority=1,status='ACTIVE'),
                            PagaAiPlan(country_id=2,kind='INTENT',condition={'type':'after_game_days'},note='TAJNY_PLAN_INNEGO',status='ACTIVE',revision=0,expires_game_at=datetime(3999,1,1))])
        task=enqueue(db.session,2,'strategic_review','review:other',0,source='test');task.journal=[{'wynik':'TAJNY_DZIENNIK_INNEGO'}]
        db.session.commit()
        captured=self.tick([DONE])
        text_=json.dumps(captured[0]['context'],ensure_ascii=False)
        for secret in ('TAJNY_CEL_INNEGO','TAJNY_PLAN_INNEGO','TAJNY_DZIENNIK_INNEGO'):self.assertNotIn(secret,text_)
        self.assertEqual(captured[0]['context']['własne_państwo']['id'],1)
        self.assertEqual(db.session.get(PagaAiJob,task.id).status,'CANCELLED','country 2 is human-played: its tasks never run')

    # 15 — technical prerequisites are performed by ZEUS (no model call for reading the price)
    def test_technical_reads_are_done_by_zeus(self):
        from game.research_models import ResearchExpense
        db.session.execute(text("INSERT INTO game_state_budget_allocations(id,budget_id,category_code,amount) VALUES(99,1,'research',1000000000)"));db.session.commit()
        task=enqueue(db.session,1,'research_available','research:test',0,source='test');db.session.commit();self.quiet_review()
        captured=self.tick([{'ocena':'Kupujemy punkt badań.','actions':[{'operation_id':'game_research.change:POST','path':{},'data':{'action':'buy','count':1}}],'task_done':True}])
        self.assertEqual(len(captured),1);self.assertEqual(db.session.query(ResearchExpense).count(),1)
        self.assertEqual(db.session.get(PagaAiJob,task.id).status,'COMPLETED')

    def test_outcome_classification(self):
        from game.paga_ai_guard import classify
        self.assertEqual(classify({'status':201}),'OK')
        self.assertEqual(classify({'status':409,'validation':'ALREADY_DONE'}),'ALREADY_DONE')
        self.assertEqual(classify({'status':403}),'PERMISSION')
        self.assertEqual(classify({'status':503,'validation':'UNCERTAIN'}),'UNKNOWN')
        self.assertEqual(classify({'status':400,'reason':'Najpierw odczytaj stan lub wykonaj wycenę tej decyzji.'}),'TECHNICAL')
        self.assertEqual(classify({'status':409,'reason':'Dane państwa lub rezerwa zmieniły się. Odśwież podgląd.'}),'SITUATION_CHANGED')
        self.assertEqual(classify({'status':400,'reason':'Wymagane technologie: Stal.'}),'DECISION')
        self.assertEqual(classify({'status':409,'validation':'BLOCKED','reason':'zmienił'}),'DECISION')

    # 16, 17, 18 — global switch and human takeover cancel tasks and plans
    def test_global_switch_and_takeover_cancel_tasks_and_plans(self):
        from engine.paga_ai_scheduler import toggle
        from game.models import GamePlayerCountry
        enqueue(db.session,1,'trade_event','note:1',0,source='test')
        db.session.add(PagaAiPlan(country_id=1,kind='CONDITIONAL',condition={'type':'attacked_by','country_id':2},operation={'operation_id':'game_military.defense_change:POST'},status='ACTIVE',revision=0,expires_game_at=datetime(3999,1,1)))
        db.session.commit()
        toggle(db.session,False,0);db.session.commit()
        self.assertEqual({task.status for task in self.tasks()},{'CANCELLED'});self.assertEqual(db.session.scalar(select(PagaAiPlan.status)),'CANCELLED')
        self.assertEqual(self.tick([DONE]),[],'nothing runs while switched off')
        toggle(db.session,True,1);db.session.commit()
        enqueue(db.session,1,'trade_event','note:2',2,source='test');db.session.commit()
        db.session.add(GamePlayerCountry(user_id=1,panstwo_id=1));db.session.commit()
        self.assertEqual(self.tick([DONE]),[])
        self.assertEqual(db.session.scalar(select(PagaAiJob.status).where(PagaAiJob.trigger=='note:2')),'CANCELLED')

    # 5 + metrics — operational journal and basic metrics are recorded from stage 1
    def test_journal_and_metrics_are_recorded(self):
        self.tick([{'ocena':'Odczyt sytuacji wojskowej.','actions':[{'operation_id':'game_army.page:GET','path':{},'data':{}}],'task_done':False},DONE])
        review=self.tasks(kind='strategic_review')[0]
        self.assertEqual(review.model_calls,2)
        steps=[row.get('krok') for row in review.journal];self.assertIn('decyzja 1',steps);self.assertIn('1.1',steps);self.assertIn('decyzja 2',steps)
        self.assertEqual(db.session.query(PagaAiMetric).filter_by(is_call=True).count(),2)
        final=db.session.scalar(select(PagaAiMetric).where(PagaAiMetric.is_call.is_(False)))
        self.assertEqual(final.outcome,'COMPLETED');self.assertEqual(final.detail['model_calls'],2)
        from game.paga_ai_metrics import summary
        data=summary(db.session);self.assertEqual(data['completed'],1);self.assertEqual(data['calls']['OK']['avg_prompt_tokens'],1200)

    def test_decision_grammar_only_allows_task_operations(self):
        captured=self.tick([DONE])
        schema=captured[0]['schema']
        names={choice['properties']['operation_id']['enum'][0] for choice in schema['properties']['actions']['items']['anyOf']}
        self.assertIn('goal.create',names);self.assertIn('game_military.war_order:POST',names);self.assertNotIn('game_finance.approve:POST',names)
        self.assertNotIn('paga.ai_control:POST',names);self.assertLessEqual(schema['properties']['actions']['maxItems'],3)
        from game.paga_ai_context import USER_BUDGET
        size=len(json.dumps(captured[0]['context'],ensure_ascii=False))
        self.assertLessEqual(size,USER_BUDGET,'decision context stays compact')

    def test_context_fits_the_model_window_even_with_large_game_data(self):
        from game.paga_ai_context import USER_BUDGET
        big={'regions':[{'id':index,'name':'Region '+str(index),'description':'x'*300,'value':'123.4567891234'} for index in range(400)]}
        with patch('game.paga_ai_context.read',return_value=big):captured=self.tick([DONE])
        call=captured[0]
        self.assertLessEqual(len(json.dumps(call['context'],ensure_ascii=False)),USER_BUDGET)
        self.assertLessEqual(len(call['system'])+USER_BUDGET,10000,'≈3.3k tokens + 512 output < 4096')


if __name__=='__main__':unittest.main()
