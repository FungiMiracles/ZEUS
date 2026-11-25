from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import patch
from sqlalchemy import text,select
from game_features_support import FeatureTestCase
from extensions import db
from models import Spoleczenstwo
from game.finance_models import StateBudget
from game.finance_service import FinanceError
from game.social_benefits import (annual_effect,record_payments,details,settle_years,BenefitSettlement)
from game.budget_transfers import sector_balances


class SocialBenefitTests(FeatureTestCase):
    def setUp(self):
        super().setUp()
        Spoleczenstwo.__table__.create(db.engine,checkfirst=True)
        db.session.execute(text('INSERT INTO game_state_budgets (id,panstwo_id,game_year,period) VALUES (1,1,2990,1),(2,1,2990,2),(3,1,2991,1)'))
        db.session.execute(text("INSERT INTO game_state_budget_allocations (id,budget_id,category_code,amount) VALUES (1,1,'social_policy',1000),(2,2,'social_policy',1000),(3,3,'social_policy',1000)"))
        db.session.add(Spoleczenstwo(panstwo_id=1,zadowolenie_spoleczne=50,zaufanie_do_wladzy=50,nierownosci_spoleczne=50))
        db.session.commit()
        self.expected=patch('game.social_benefits.expectations',return_value={'children':D(200),'seniors':D(300)})
        self.expected.start();self.addCleanup(self.expected.stop)

    def pay(self,id,children,seniors,previous=None,repeat=False):
        record_payments(db.session,db.session.get(StateBudget,id),db.session.get(StateBudget,previous) if previous else None,D(1000),{'children':str(children),'seniors':str(seniors)},repeat)
        db.session.flush()

    def test_thresholds_include_fractional_percentages(self):
        for ratio,effect in [('0',(-2,-1,1)),('.39999',(-2,-1,1)),('.4',(-2,0,0)),('.74999',(-2,0,0)),('.75',(-1,0,0)),('.94999',(-1,0,0)),('.95',(0,0,0)),('1.19999',(0,0,0)),('1.2',(1,1,-1))]:
            self.assertEqual(annual_effect(D(ratio)*100,D(100)),effect)
        self.assertEqual(annual_effect(D(100),D(0)),(0,0,0))

    def test_payments_are_spent_and_unused_funds_are_not_carried(self):
        # 25 Nov 2026: niewykorzystane środki socjalne przechodzą do rezerwy (sweep_unspent), nie na świadczenia kolejnego okresu.
        self.pay(1,200,300)
        self.assertEqual(sector_balances(db.session,db.session.get(StateBudget,1))['social_policy']['remaining'],500)
        with self.assertRaises(FinanceError):self.pay(2,600,500,previous=1)   # 1100 > przydział 1000 — bez przeniesienia
        self.pay(2,500,500,previous=1)
        balance=sector_balances(db.session,db.session.get(StateBudget,2))['social_policy']
        self.assertEqual((balance['allocated'],balance['remaining']),(1000,0))
        self.assertEqual(details(db.session,db.session.get(StateBudget,2))['carry_in'],0)

    def test_historical_carry_in_is_still_counted(self):
        from game.social_benefits import BenefitPayment
        db.session.add_all([BenefitPayment(budget_id=1,kind='children',expected=200,paid=900,carry_in=500),BenefitPayment(budget_id=1,kind='seniors',expected=300,paid=0,carry_in=0)])
        db.session.flush()
        balance=sector_balances(db.session,db.session.get(StateBudget,1))['social_policy']
        self.assertEqual((balance['allocated'],balance['remaining']),(1500,600))

    def test_unspent_social_funds_are_swept_to_reserve(self):
        from game.finance_service import unspent_sectors,SWEEP_EXCLUDED
        self.pay(1,200,300)
        self.assertNotIn('social_policy',SWEEP_EXCLUDED)
        self.assertEqual(unspent_sectors(db.session,db.session.get(StateBudget,1))['social_policy'],500)

    def test_invalid_and_overspending_payments_rejected(self):
        for raw in ({'children':'-1'},{'children':'0.001'},{'children':'NaN'},{'children':'1001'},[],{'wrong':'1'}):
            with self.assertRaises(FinanceError):record_payments(db.session,db.session.get(StateBudget,1),None,D(1000),raw,False)

    def test_annual_totals_and_restart_idempotency(self):
        self.pay(1,400,0)
        self.pay(2,0,900,previous=1)
        settle_years(db.session,1,2990)
        self.assertEqual(db.session.query(BenefitSettlement).count(),0)
        settle_years(db.session,1,2991)
        db.session.commit()
        # Children 100%, pensions 150%: only pensions increase satisfaction/trust.
        society=db.session.scalar(select(Spoleczenstwo).where(Spoleczenstwo.panstwo_id==1))
        self.assertEqual((society.zadowolenie_spoleczne,society.zaufanie_do_wladzy,society.nierownosci_spoleczne),(51,51,49))
        settle_years(db.session,1,2991);db.session.commit()
        self.assertEqual(db.session.query(BenefitSettlement).count(),1)
        self.assertEqual(society.zadowolenie_spoleczne,51)

    def test_automatic_repeat_uses_previous_paid_amounts(self):
        self.pay(1,100,200)
        self.pay(2,0,0,previous=1,repeat=True)
        self.assertEqual(details(db.session,db.session.get(StateBudget,2))['paid'],{'children':100,'seniors':200})

    def test_missed_half_year_counts_as_unpaid_and_is_recorded_once(self):
        from game.social_benefits import record_missed_period,MissedBenefitPeriod
        self.pay(1,200,300)
        record_missed_period(db.session,1,2990,2)
        db.session.flush()
        record_missed_period(db.session,1,2990,2)
        settle_years(db.session,1,2991)
        society=db.session.scalar(select(Spoleczenstwo).where(Spoleczenstwo.panstwo_id==1))
        self.assertEqual(society.zadowolenie_spoleczne,46)
        self.assertEqual(db.session.query(MissedBenefitPeriod).count(),1)

    def test_expectations_use_counts_and_half_of_five_percent(self):
        self.expected.stop()
        from game.social_benefits import expectations
        with patch('game.population_structure.structure_data',return_value={'groups':[{'key':'children','count':200},{'key':'seniors','count':100}]}),patch('game.finance_service.economy',return_value={'gdp':D(1000000),'population':1000}):
            self.assertEqual(expectations(db.session,1),{'children':D('5000.00'),'seniors':D('2500.00')})
