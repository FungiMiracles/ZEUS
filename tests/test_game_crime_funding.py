"""Finansowanie walki z przestępczością (16 Nov 2026)."""
from datetime import datetime
from decimal import Decimal as D
from unittest.mock import patch
from sqlalchemy import text,select
from game_features_support import FeatureTestCase
from extensions import db
from models import Spoleczenstwo
from game.finance_models import StateBudget
from game.finance_service import FinanceError
from game.forum_models import GameNotification
from game.crime_funding import CrimeFunding,effect,expected_amount,record_funding,details,settle_due
from game.budget_transfers import sector_balances


class CrimeFundingRulesTests(FeatureTestCase):
    def setUp(self):
        super().setUp()
        Spoleczenstwo.__table__.create(db.engine,checkfirst=True)
        db.session.execute(text('INSERT INTO game_state_budgets (id,panstwo_id,game_year,period) VALUES (1,1,2990,1),(2,1,2990,2)'))
        db.session.execute(text("INSERT INTO game_state_budget_allocations (id,budget_id,category_code,amount) VALUES (1,1,'security_services',1000),(2,2,'security_services',1000)"))
        db.session.add(Spoleczenstwo(panstwo_id=1,przestepczosc=10,zadowolenie_spoleczne=50,zaufanie_do_wladzy=50))
        db.session.commit()
        self.expected=patch('game.crime_funding.expectations',return_value={'expected':D('500.00'),'level':10})
        self.expected.start();self.addCleanup(self.expected.stop)

    def budget(self,id):return db.session.get(StateBudget,id)

    def test_expected_amount_is_population_times_crime_rounded_to_hundreds_of_millions(self):
        self.assertEqual(expected_amount(38_000_000,8),D('300000000.00'))
        self.assertEqual(expected_amount(38_000_000,9),D('300000000.00'))
        self.assertEqual(expected_amount(38_000_000,10),D('400000000.00'))
        self.assertEqual(expected_amount(25_000_000,2),D('100000000.00'))
        self.assertEqual(expected_amount(10_000_000,0),D('0.00'))
        self.assertIsNone(expected_amount(None,5))
        self.assertIsNone(expected_amount(1000,None))

    def test_effect_thresholds(self):
        cases=[('100',0),('105',0),('105.01',-1),('120',-1),('120.01',-2),('300',-2),
               ('99.99',1),('65',1),('64.99',2),('40',2),('39.99',3),('0',3)]
        for paid,delta in cases:
            self.assertEqual(effect(D(paid),D(100)),delta,paid)
        self.assertEqual(effect(D(0),D(0)),0)

    def test_record_validates_amount_and_sector_limit(self):
        for raw in ('-1','0.001','NaN','1000.01'):
            with self.assertRaises(FinanceError):record_funding(db.session,self.budget(1),None,D(1000),raw,False)
        record_funding(db.session,self.budget(1),None,D(1000),'400.50',False);db.session.flush()
        self.assertEqual(details(db.session,self.budget(1))['paid'],D('400.50'))
        self.assertEqual(details(db.session,self.budget(1))['expected'],D('500.00'))

    def test_repeat_copies_previous_amount_and_missing_value_defaults_to_expectation(self):
        record_funding(db.session,self.budget(1),None,D(1000),None,False);db.session.flush()
        self.assertEqual(details(db.session,self.budget(1))['paid'],D('500.00'))
        db.session.get(CrimeFunding,1).paid=D('321.00');db.session.flush()
        record_funding(db.session,self.budget(2),self.budget(1),D(300),None,True);db.session.flush()
        self.assertEqual(details(db.session,self.budget(2))['paid'],D('300.00'))   # ograniczone przydziałem sektora

    def test_funding_is_spent_from_security_services(self):
        record_funding(db.session,self.budget(1),None,D(1000),'400',False);db.session.flush()
        balance=sector_balances(db.session,self.budget(1))['security_services']
        self.assertEqual((balance['spent'],balance['remaining']),(D(400),D(600)))

    def test_settlement_one_week_before_period_end_with_notification(self):
        record_funding(db.session,self.budget(1),None,D(1000),'250',False);db.session.commit()   # niedofinansowanie 50% → +2
        self.assertEqual(settle_due(db.session,datetime(2990,6,23,23)),0)
        self.assertEqual(settle_due(db.session,datetime(2990,6,24)),1);db.session.commit()
        society=db.session.scalar(select(Spoleczenstwo).where(Spoleczenstwo.panstwo_id==1))
        self.assertEqual(society.przestepczosc,12)
        row=db.session.get(CrimeFunding,1)
        self.assertEqual((row.effect,row.old_level,row.new_level),(2,10,12))
        notice=db.session.scalar(select(GameNotification).where(GameNotification.user_id==1))
        self.assertIn('wzrósł o 2 pkt',notice.system_text)
        self.assertEqual(settle_due(db.session,datetime(2990,6,30)),0)   # idempotentne
        self.assertEqual(society.przestepczosc,12)

    def test_surplus_lowers_crime_and_never_below_zero(self):
        record_funding(db.session,self.budget(1),None,D(1000),'700',False);db.session.commit()   # nadwyżka 40% → −2
        db.session.scalar(select(Spoleczenstwo)).przestepczosc=1;db.session.commit()
        settle_due(db.session,datetime(2990,7,1));db.session.commit()
        self.assertEqual(db.session.scalar(select(Spoleczenstwo)).przestepczosc,0)
        self.assertIn('spadł o 1 pkt',db.session.scalar(select(GameNotification)).system_text)


class Paga2CrimeFundingTests(FeatureTestCase):
    def test_paga2_funds_expectation_within_sector_and_raises_floor(self):
        from types import SimpleNamespace
        from game.paga2.budget import crime_payment,crime_target,with_crime_floor,SECTORS
        ctx=SimpleNamespace(traits={'loss_tolerance':50,'prosociality':50},situation={})
        ratio=crime_target(ctx)
        self.assertTrue(1.0<=ratio<=1.15)
        self.assertEqual(crime_target(SimpleNamespace(traits={},situation={'level':'war'})),1.0)
        paid,covered=crime_payment({'crime':{'expected':'1000'},'allocations':{'security_services':'600'}},1.1)
        self.assertEqual((paid,covered),('600',D('0.6')))
        self.assertEqual(crime_payment({'crime':{'expected':'1000'},'allocations':{'security_services':'5000'}},1.1)[0],'1100.00')
        shares={s:D('5') for s in SECTORS}
        adjusted,changed=with_crime_floor(shares,{'crime':{'expected':'200'},'budget_total':'1000'},1.0)
        self.assertTrue(changed)
        self.assertGreaterEqual(adjusted['security_services'],D('20'))
        self.assertLessEqual(sum(adjusted.values()),sum(shares.values()))
