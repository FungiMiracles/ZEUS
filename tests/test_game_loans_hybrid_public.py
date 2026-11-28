"""Real transfers, hybrid outcomes and player-facing WIKI data."""
from datetime import timedelta,datetime
from decimal import Decimal
from uuid import uuid4
from unittest.mock import patch
from sqlalchemy import select,text
from extensions import db
from models import Region,Spoleczenstwo,Zdarzenie,ZdarzenieSzablon,RegionStateHistory
from game.finance_models import StateBudget,StateFinancialAccount,BudgetTransfer
from game.finance_service import FinanceError,_reserve_for_account
from game.loan_models import StateLoan,LoanMovement
from game.loans import request_loan,settle_loan,loans_bp
from game.budget_transfers import sector_balances
from game.forum_models import GameNotification
from game.intelligence_models import IntelligenceAgent,IntelligenceMission,CounterIntelligence
from game.intelligence_service import complete_missions,HYBRID
from game.public_panels import public_panels_bp
from test_game_military import MilitaryFixture,NOW
from test_game_intelligence import IntelligenceFixture


class LoanTests(MilitaryFixture):
    def setUp(self):
        super().setUp();self.app.register_blueprint(loans_bp)
        clock=patch('game.loans.game_now',return_value=NOW);clock.start();self.addCleanup(clock.stop)
        db.session.execute(text("UPDATE game_state_budgets SET closing_reserve=100 WHERE id=1"))
        db.session.execute(text("INSERT INTO game_state_budgets(id,panstwo_id,game_year,period,closing_reserve) VALUES(2,2,2990,1,200)"))
        db.session.execute(text("INSERT INTO game_state_budget_allocations(id,budget_id,category_code,amount) VALUES(2,2,'infrastructure',1000)"))
        for country,reserve in [(1,100),(2,200)]:db.session.add(StateFinancialAccount(panstwo_id=country,reserve_balance=reserve,last_budget_id=country,last_transaction_sequence=0,created_at=NOW,updated_at=NOW))
        db.session.commit()

    def loan(self,amount='300'):
        return request_loan(1,{'lender_id':2,'amount':amount,'request_id':str(uuid4())})

    def balances(self):
        db.session.expire_all();return [db.session.get(StateFinancialAccount,id).reserve_balance for id in (1,2)]

    def test_request_repeat_and_reject_never_move_money(self):
        data={'lender_id':2,'amount':'50','request_id':str(uuid4())};id=request_loan(1,data);self.assertEqual(request_loan(1,data),id)
        self.assertEqual(self.balances(),[100,200]);self.assertEqual(db.session.query(StateLoan).count(),1)
        settle_loan(2,{'action':'reject','loan_id':id});settle_loan(2,{'action':'reject','loan_id':id})
        self.assertEqual(self.balances(),[100,200]);self.assertEqual(db.session.query(LoanMovement).count(),0)
        with self.assertRaises(FinanceError):settle_loan(2,{'action':'accept','loan_id':id})

    def test_accept_with_explicit_sector_funding_exactly_once_and_repay(self):
        id=self.loan()
        with self.assertRaises(FinanceError):settle_loan(2,{'action':'accept','loan_id':id})
        self.assertEqual(self.balances(),[100,200]);self.assertEqual(db.session.query(BudgetTransfer).count(),0)
        settle_loan(2,{'action':'accept','loan_id':id,'funding_category':'infrastructure'})
        settle_loan(2,{'action':'accept','loan_id':id,'funding_category':'infrastructure'})
        self.assertEqual(self.balances(),[400,0]);transfer=db.session.query(BudgetTransfer).one();self.assertEqual(transfer.amount,100)
        self.assertEqual(sector_balances(db.session,db.session.get(StateBudget,2))['infrastructure']['remaining'],900)
        self.assertEqual(db.session.query(LoanMovement).count(),2)
        for country in (1,2):self.assertEqual(_reserve_for_account(db.session.get(StateFinancialAccount,country),db.session.get(StateBudget,country)),self.balances()[country-1])
        settle_loan(1,{'action':'repay','loan_id':id});settle_loan(1,{'action':'repay','loan_id':id})
        self.assertEqual(self.balances(),[100,300]);self.assertEqual(db.session.query(LoanMovement).count(),4)
        for country in (1,2):_reserve_for_account(db.session.get(StateFinancialAccount,country),db.session.get(StateBudget,country))

    def test_unauthorized_decisions_and_insufficient_sector_cannot_partially_pay(self):
        id=self.loan('1500')
        for user,action in [(1,'accept'),(3,'accept'),(2,'cancel')]:
            with self.assertRaises(FinanceError):settle_loan(user,{'action':action,'loan_id':id})
        with self.assertRaises(FinanceError):settle_loan(2,{'action':'accept','loan_id':id,'funding_category':'infrastructure'})
        self.assertEqual(self.balances(),[100,200]);self.assertEqual(db.session.query(LoanMovement).count(),0)
        self.assertEqual(db.session.query(BudgetTransfer).count(),0)

    def test_stale_gap_does_not_take_unexpected_sector_funds(self):
        id=self.loan()
        with self.assertRaises(FinanceError):settle_loan(2,{'action':'accept','loan_id':id,'expected_gap':'50','funding_category':'infrastructure'})
        self.assertEqual(self.balances(),[100,200]);self.assertEqual(db.session.query(BudgetTransfer).count(),0)
        self.assertEqual(db.session.query(LoanMovement).count(),0)

    def test_prebudget_borrower_and_csrf(self):
        id=request_loan(3,{'lender_id':2,'amount':'50','request_id':str(uuid4())})
        settle_loan(2,{'action':'accept','loan_id':id});db.session.expire_all()
        self.assertEqual(_reserve_for_account(db.session.get(StateFinancialAccount,3),None),50)
        self.assertEqual(self.client.post('/game/pozyczki/zmien',json={'action':'request','lender_id':2,'amount':'1','request_id':str(uuid4())}).status_code,403)
        for value in ('-1','0','NaN','0.001'):
            with self.assertRaises(FinanceError):request_loan(1,{'lender_id':2,'amount':value,'request_id':str(uuid4())})

    def test_cancellation_and_wrong_recipient(self):
        id=self.loan('50');settle_loan(1,{'action':'cancel','loan_id':id})
        with self.assertRaises(FinanceError):settle_loan(2,{'action':'accept','loan_id':id})
        for lender in (1,4,999):
            with self.assertRaises(FinanceError):request_loan(1,{'lender_id':lender,'amount':'5','request_id':str(uuid4())})


class HybridTests(IntelligenceFixture):
    def setUp(self):
        super().setUp();region=db.session.get(Region,2)
        for _,field,_,_ in HYBRID.values():setattr(region,field,50)
        region.region_polozenie_id=2;db.session.commit()

    def test_all_hybrid_effects_exactly_once_and_both_sides_notified(self):
        for kind,(_,field,_,loss) in HYBRID.items():
            before=getattr(db.session.get(Region,2),field);mission=self.start(kind)
            self.finish(0);complete_missions(db.session,NOW+timedelta(days=8));db.session.commit()
            self.assertEqual(getattr(db.session.get(Region,2),field),before-loss)
            self.assertTrue(db.session.get(IntelligenceMission,mission.id).success)
        self.assertEqual(db.session.query(RegionStateHistory).filter_by(source='HYBRID').count(),5)
        self.assertEqual(set(db.session.scalars(select(GameNotification.user_id))),{1,2})

    def test_failure_capture_prevents_reuse_but_preserves_report(self):
        mission=self.start('cyber_energy');agent=mission.agent_id
        with patch('game.intelligence_service.randbelow',side_effect=[9999,0]):complete_missions(db.session,NOW+timedelta(days=7),country_id=2)
        db.session.commit();db.session.expire_all()
        self.assertFalse(db.session.get(IntelligenceMission,mission.id).success)
        self.assertIsNotNone(db.session.get(IntelligenceAgent,agent).captured_at)
        self.assertEqual(db.session.get(Region,2).region_stan_infra_energetycznej,50)
        with self.assertRaises(FinanceError):self.start('bases',agent=db.session.get(IntelligenceAgent,agent))
        self.assertTrue(db.session.get(IntelligenceMission,mission.id).report['captured'])

    def test_failed_but_not_captured_agent_returns(self):
        mission=self.start('arson')
        with patch('game.intelligence_service.randbelow',side_effect=[9999,99]):complete_missions(db.session,NOW+timedelta(days=7))
        db.session.commit();self.assertIsNone(db.session.get(IntelligenceAgent,mission.agent_id).captured_at)
        self.assertEqual(db.session.get(Region,2).region_stan_infra_mieszkalnej,50)

    def test_damage_clamped_and_port_requires_coast(self):
        region=db.session.get(Region,2);region.region_stan_infra_energetycznej=1;db.session.commit()
        self.start('cyber_energy');self.finish();self.assertEqual(db.session.get(Region,2).region_stan_infra_energetycznej,0)
        region=db.session.get(Region,2);region.region_polozenie_id=1;db.session.commit()
        with self.assertRaises(FinanceError):self.start('cyber_port')


class PublicPanelTests(MilitaryFixture):
    def setUp(self):
        super().setUp();self.app.register_blueprint(public_panels_bp)
        from models import MiastoStateHistory
        MiastoStateHistory.__table__.create(db.engine,checkfirst=True)
        Spoleczenstwo.__table__.create(db.engine,checkfirst=True);ZdarzenieSzablon.__table__.create(db.engine,checkfirst=True)
        db.session.add(Spoleczenstwo(panstwo_id=1,stabilnosc_spoleczna=67,poziom_edukacji=42))
        db.session.add_all([Zdarzenie(zdarzenie_id=i,panstwo_id=i,region_id=i,zdarzenie_typ='TestEvent',data_entenda=datetime(2990,1,i),ilosc_ofiar=10*i,skala=i,status='aktywne',effect_applied=True,opis_wygenerowany='Test event description') for i in (1,2)])
        db.session.add(RegionStateHistory(region_id=1,event_id=1,source='EVENT',data_entenda=NOW,data_rzeczywista=NOW,old_energia=70,new_energia=67))
        db.session.commit()

    def test_society_actual_values_and_all_wiki_tooltips(self):
        html=self.client.get('/game/spoleczenstwo').get_data(as_text=True)
        self.assertIn('67',html);self.assertIn('Poziom stabilności społecznej kraju',html)
        self.assertEqual(html.count('class="indicator-help"'),18)
        self.assertNotIn('value="42" name=',html)

    def test_society_requires_login(self):
        # 28 Nov 2026: lista generatora zdarzeń usunięta z ekranu „Wydarzenia” (gazeta „Entenda News” — test_newspaper.py)
        with self.client.session_transaction() as browser:browser.clear()
        self.assertEqual(self.client.get('/game/spoleczenstwo').status_code,302)
