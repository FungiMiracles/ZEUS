"""Adapter integration through real Flask player routes, isolated SQLite only."""
import json,unittest
from datetime import datetime
from unittest.mock import patch
from sqlalchemy import MetaData,Table,Column,Integer,String,select,text
from extensions import db
from test_paga_ai import AiTests as _Fixture
from game.paga_ai_executor import execute
from game.paga_ai_models import PagaAiLog
from game.finance_models import BudgetCategory,StateFinancialPeriod,StateBudget,StateBudgetAllocation,StateTaxAssessment,StateFinancialTransaction

class BudgetAdapterTests(unittest.TestCase):
    def setUp(self):
        self.fixture=_Fixture();self.fixture.setUp();self.app=self.fixture.app;self.actor=self.fixture.actor
        db.session.remove()
        # Match native SQLite identities, retaining domain services and ordinary validation.
        for model in (StateBudgetAllocation,StateBudget,BudgetCategory,StateFinancialPeriod,StateTaxAssessment,StateFinancialTransaction):
            model.__table__.drop(db.engine,checkfirst=True)
        for model in (BudgetCategory,StateFinancialPeriod,StateBudget,StateBudgetAllocation,StateTaxAssessment,StateFinancialTransaction):
            metadata=MetaData()
            Table(model.__tablename__,metadata,*[Column(c.name,Integer() if c.primary_key and c.name=='id' else String(c.type.length) if isinstance(c.type,String) else c.type,primary_key=c.primary_key,nullable=True) for c in model.__table__.columns]).create(db.engine)
        from models import Spoleczenstwo,Gospodarka,fauna_panstwo,Fauna
        from game.population_structure import PopulationStructure
        from game.finance_service import CATEGORY_CODES
        Spoleczenstwo.__table__.create(db.engine,checkfirst=True)
        Gospodarka.__table__.create(db.engine,checkfirst=True)
        fauna_panstwo.create(db.engine,checkfirst=True)
        Fauna.__table__.create(db.engine,checkfirst=True)
        db.session.add(Gospodarka(panstwo_id=1,bezrobocie=5))
        db.session.add_all([BudgetCategory(code=code,name_pl=code,display_order=i+1,is_reserve=code=='reserve') for i,code in enumerate(CATEGORY_CODES)])
        db.session.execute(text('UPDATE panstwa SET panstwo_populacja=1000000,panstwo_PKB=50000000000 WHERE PANSTWO_ID=1'))
        db.session.execute(text('UPDATE regiony SET region_stan_infra_drogowej=50,region_stan_infra_kolejowej=50,region_stan_infra_energetycznej=50,region_stan_infra_mieszkalnej=50 WHERE region_id=1'))
        db.session.add(PopulationStructure(panstwo_id=1,children=20,working=60,seniors=20,version=1,actor='Test'))
        db.session.add(Spoleczenstwo(panstwo_id=1,zadowolenie_spoleczne=60,stabilnosc_spoleczna=70,poziom_edukacji=80,zdrowie_publiczne=75,przestepczosc=8,zaufanie_do_wladzy=61))
        db.session.commit();self.step=0
        self.reason='Plan finansuje świadczenia społeczne i inwestycje infrastrukturalne zgodnie z priorytetami państwa.'
    def tearDown(self):self.fixture.tearDown()
    def call(self,operation,data=None):
        self.step+=1
        return execute(self.app,self.actor,{'operation_id':operation,'path':{},'data':data or {}},step=self.step)
    def state(self,response):return json.loads(response['observation']['text'])['result']
    def plan(self,rate=15):return self.call('game_finance.preview:POST',{'pit_rate':rate,'shares':{'social_policy':35,'infrastructure':30,'healthcare':10,'research':5,'reserve':20},'benefits':{'children':250000000 if rate>=5 else 0,'seniors':250000000 if rate>=5 else 0},'rationale':self.reason})
    def test_full_budget_persists_and_technical_fields_are_server_owned(self):
        read=self.call('game_finance.page:GET');self.assertEqual(read['status'],200,read)
        self.assertIn('categories',self.state(read));self.assertNotIn('basis_token',str(read))
        preview=self.plan();self.assertEqual(preview['status'],200,preview);self.assertNotIn('basis_token',str(preview))
        approve=self.call('game_finance.approve:POST',{'rationale':self.reason});self.assertEqual(approve['status'],200,approve)
        budget=db.session.scalar(select(StateBudget));self.assertIsNotNone(budget);self.assertEqual(float(db.session.scalar(select(StateTaxAssessment.pit_rate))),15)
        self.assertEqual(db.session.query(StateTaxAssessment).count(),1)
        stored=db.session.scalar(select(PagaAiLog).where(PagaAiLog.operation=='game_finance.preview:POST'))
        page=self.call('operations.result',{'id':stored.id});self.assertNotIn('basis_token',str(page));self.assertNotIn('_budget_plan',str(page))
    def test_bad_plan_blocked_then_corrected_and_low_tax_remains_legal(self):
        bad={'pit_rate':10,'shares':{'infrastructure':80,'healthcare':80}}
        first=self.call('game_finance.preview:POST',bad);self.assertEqual(first['status'],400,first)
        second=self.call('game_finance.preview:POST',bad);self.assertEqual(second['status'],409,second)
        self.call('game_finance.page:GET')
        third=self.call('game_finance.preview:POST',bad);self.assertEqual(third['status'],400,third) # first new observation
        self.call('game_finance.page:GET')
        fourth=self.call('game_finance.preview:POST',bad);self.assertEqual(fourth['status'],409,fourth)
        self.assertEqual(self.plan(.05)['status'],200)
        self.assertEqual(self.call('game_finance.approve:POST',{'rationale':'Strategia niskich podatków: ograniczamy wydatki i świadomie akceptujemy niski dochód.','accept_social_shortfall':True,'accept_revenue_decline':True})['status'],200)
        self.assertEqual(float(db.session.scalar(select(StateTaxAssessment.pit_rate))),.05)
    def test_stale_period_and_changed_basis_are_rejected(self):
        self.assertEqual(self.plan()['status'],200)
        with patch('game.finance_service.game_now',return_value=datetime(2990,7,1)):
            self.assertEqual(self.call('game_finance.approve:POST',{'rationale':self.reason})['status'],409)
        self.assertEqual(db.session.query(StateBudget).count(),0)
        self.assertEqual(self.plan(16)['status'],200)
        db.session.execute(text('UPDATE panstwa SET panstwo_PKB=60000000000 WHERE PANSTWO_ID=1'));db.session.commit()
        self.assertEqual(self.call('game_finance.approve:POST',{'rationale':self.reason})['status'],409)
        self.assertEqual(db.session.query(StateBudget).count(),0)
    def test_approval_requires_review_and_rejects_forged_technical_fields(self):
        self.assertEqual(self.call('game_finance.approve:POST',{'rationale':self.reason})['status'],400)
        self.assertEqual(self.plan()['status'],200)
        self.assertEqual(self.call('game_finance.approve:POST',{'rationale':self.reason,'basis_token':'f'*64})['status'],400)
        self.assertEqual(self.call('game_finance.approve:POST',{'rationale':self.reason,'pit_rate':1})['status'],400)
        self.assertEqual(self.call('game_finance.approve:POST',{'rationale':self.reason})['status'],200)

    def test_economic_tradeoffs_require_explicit_ai_decision_but_remain_allowed(self):
        self.assertEqual(self.plan(.05)['status'],200)
        without=self.call('game_finance.approve:POST',{'rationale':self.reason})
        self.assertEqual(without['status'],400);self.assertIn('niedobór',str(without))
        partial=self.call('game_finance.approve:POST',{'rationale':self.reason,'accept_social_shortfall':True})
        self.assertEqual(partial['status'],400);self.assertIn('accept_revenue_decline',str(partial))
        allowed=self.call('game_finance.approve:POST',{'rationale':'Świadomie akceptujemy niedobór i spadek dochodów, ograniczając zakres świadczeń dla strategii niskich podatków.','accept_social_shortfall':True,'accept_revenue_decline':True})
        self.assertEqual(allowed['status'],200,allowed)

    def test_duplicate_guard_persists_across_jobs_and_numeric_spelling(self):
        from game.paga_ai_actor import AiActor
        from game.paga_ai_models import PagaAiJob
        db.session.add_all([PagaAiJob(id=100,country_id=1,trigger='first',revision=0),PagaAiJob(id=101,country_id=1,trigger='second',revision=0)]);db.session.commit()
        self.actor=AiActor(1,self.actor.user_id,0,100)
        first=self.call('game_finance.preview:POST',{'pit_rate':10,'shares':{'infrastructure':160}})
        self.assertEqual(first['status'],400)
        self.actor=AiActor(1,self.actor.user_id,0,101)
        blocked=self.call('game_finance.preview:POST',{'pit_rate':10.0,'shares':{'infrastructure':160.0}})
        self.assertEqual(blocked['status'],409,blocked)
        corrected=self.call('game_finance.preview:POST',{'pit_rate':10,'shares':{'infrastructure':60}})
        self.assertEqual(corrected['status'],200,corrected)

    def test_repeat_preserves_actual_benefits_from_player_history(self):
        from game.social_benefits import BenefitPayment
        self.assertEqual(self.plan()['status'],200)
        self.assertEqual(self.call('game_finance.approve:POST',{'rationale':self.reason})['status'],200)
        with patch('game.finance_service.game_now',return_value=datetime(2990,7,1)):
            preview=self.call('game_finance.preview:POST',{'repeat_previous':True})
            self.assertEqual(preview['status'],200,preview)
            self.assertEqual(self.state(preview)['planned_benefit_payments']['children'],'250000000.00')
            approved=self.call('game_finance.approve:POST',{'rationale':self.reason})
            self.assertEqual(approved['status'],200,approved)
        self.assertEqual(db.session.query(StateBudget).count(),2)
        self.assertEqual(sum(row.paid for row in db.session.scalars(select(BenefitPayment))),1000000000)

    def test_benefits_over_available_funds_rejected_by_standard_game_then_corrected(self):
        preview=self.call('game_finance.preview:POST',{'pit_rate':15,'shares':{'social_policy':35},'benefits':{'children':600000000,'seniors':600000000}})
        self.assertEqual(preview['status'],200)
        bad=self.call('game_finance.approve:POST',{'rationale':self.reason})
        self.assertEqual(bad['status'],400,bad);self.assertIn('Świadczenia przekraczają',str(bad))
        self.assertEqual(db.session.query(StateBudget).count(),0)
        self.assertEqual(self.plan()['status'],200)
        self.assertEqual(self.call('game_finance.approve:POST',{'rationale':self.reason})['status'],200)

    def test_relative_priorities_and_explicit_millions_use_same_player_validation(self):
        preview=self.call('game_finance.preview:POST',{'pit_rate':15,'allocation_weights':{'social_policy':8,'infrastructure':4,'healthcare':2,'reserve':2},'benefits_millions':{'children':250,'seniors':250}})
        self.assertEqual(preview['status'],200,preview)
        state=self.state(preview)
        self.assertEqual(state['plan']['shares']['social_policy'],'50.00')
        self.assertEqual(state['planned_benefit_payments']['children'],'250000000')
        self.assertEqual(self.call('game_finance.approve:POST',{'rationale':self.reason})['status'],200)
        self.assertEqual(db.session.query(StateBudget).count(),1)
    def test_invalid_weights_units_and_mixed_contract_are_rejected(self):
        for data in ({'allocation_weights':{'social_policy':-1}}, {'allocation_weights':{'social_policy':0}},
                     {'allocation_weights':{'fake_sector':1}}, {'allocation_weights':{'social_policy':1},'shares':{'reserve':100}},
                     {'benefits_millions':{'children':1},'benefits':{'children':1}}):
            with self.subTest(data=data):self.assertEqual(self.call('game_finance.preview:POST',data)['status'],400)
        self.assertEqual(db.session.query(StateBudget).count(),0)

    def test_explicit_available_policy_is_reviewed_then_shared_game_books_payments(self):
        from game.social_benefits import BenefitPayment
        preview=self.call('game_finance.preview:POST',{'pit_rate':5,'allocation_weights':{'social_policy':1,'infrastructure':1},'benefit_policy':'available_proportional'})
        self.assertEqual(preview['status'],200,preview)
        state=self.state(preview);self.assertEqual(state['chosen_benefit_policy'],'available_proportional')
        self.assertEqual(state['social_expectations_check']['unfunded_planned_payments'],'0')
        self.assertEqual(self.call('game_finance.approve:POST',{'rationale':self.reason})['status'],400)
        result=self.call('game_finance.approve:POST',{'rationale':'Wypłacamy świadczenia w ramach dostępnego przydziału, świadomie akceptując częściowe pokrycie oczekiwań.','accept_social_shortfall':True})
        self.assertEqual(result['status'],200,result)
        paid=sum(row.paid for row in db.session.scalars(select(BenefitPayment)))
        self.assertEqual(str(paid),'367899375.00')
    def test_policy_never_clamps_an_explicit_amount_request(self):
        bad=self.call('game_finance.preview:POST',{'benefit_policy':'available_proportional','benefits_millions':{'children':500}})
        self.assertEqual(bad['status'],400,bad)


    # Regression for the UAT loop of 9 Nov 2026: approve OK -> re-read -> preview/approve repeated for hours.
    WEIGHTS={'pit_rate':15,'allocation_weights':{'social_policy':8,'infrastructure':4,'healthcare':2,'reserve':2},'benefits_millions':{'children':250,'seniors':250}}
    FORUM={'content':'Hopia zaprasza sąsiadów do rozmów o handlu i bezpieczeństwie regionu.','recipient_id':2}

    def test_approved_budget_is_reported_as_finished_and_next_operation_still_runs(self):
        self.assertEqual(self.call('game_finance.preview:POST',self.WEIGHTS)['status'],200)
        approved=self.call('game_finance.approve:POST',{'rationale':self.reason})
        self.assertEqual(approved['status'],200,approved);self.assertIn('Zatwierdzono budżet',approved['summary'])
        budget_id=db.session.scalar(select(StateBudget.id))
        # Re-reading finances states the goal is finished, with the player's own budget id.
        read=self.state(self.call('game_finance.page:GET'))
        self.assertTrue(read['state']['approved']);self.assertEqual(read['state']['budget_id'],budget_id)
        self.assertEqual(read['completed_goal']['status'],'ZAKOŃCZONY');self.assertEqual(read['completed_goal']['budget_id'],budget_id)
        # The repeated preview explains completion instead of returning a bare approved flag.
        preview=self.call('game_finance.preview:POST',self.WEIGHTS)
        self.assertEqual(preview['status'],200,preview)
        self.assertIn('już zatwierdzony',self.state(preview)['completed_goal']['message'])
        # Approving again executes nothing and never reports a misleading adapter error or a duplicate block.
        for attempt in range(2):
            again=self.call('game_finance.approve:POST',{'rationale':self.reason+' Ponowna próba.','accept_social_shortfall':True})
            self.assertEqual(again['status'],409,again)
            text=again['observation']['text']
            self.assertIn('już zatwierdzony',text);self.assertNotIn('nowego adaptera',text);self.assertNotIn('Powtórzona odrzucona',text)
            self.assertIn('Cel już zrealizowany',again['summary'])
        rows=list(db.session.scalars(select(PagaAiLog.validation).where(PagaAiLog.operation=='game_finance.approve:POST').order_by(PagaAiLog.id)))
        self.assertEqual(rows,['EXECUTED','ALREADY_DONE','ALREADY_DONE'])
        self.assertEqual(db.session.query(StateBudget).count(),1);self.assertEqual(db.session.query(StateTaxAssessment).count(),1)
        # Other areas of government remain fully available after the finished goal.
        forum=self.call('game_forum.page:POST',self.FORUM)
        self.assertEqual(forum['status'],303,forum)
        # Ordinary post-approval finance operations are not blocked either (same player validation).
        self.assertEqual(self.call('game_finance.page:GET')['status'],200)
