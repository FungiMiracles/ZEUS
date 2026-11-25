"""Mine protection, scoped interception, header budget and notification icon routing."""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from sqlalchemy import select,text
from extensions import db
from test_game_military import MilitaryFixture,NOW
from game.commerce_models import Mine
from game.military_models import MissileDefense,MissileDefenseExpense
from game.military_service import military_budget
from game.military_flights import apply_structural_damage
from game.missile_defense import defense_data,intercept
from game.finance_service import FinanceError
from game.budget_overview import budget_overview
from game.forum import notification_icon


class MineDefenseTests(MilitaryFixture):
    def setUp(self):
        super().setUp()
        from models import DictZasob,RegionZasob
        from services.natural_resources import RESOURCES
        db.metadata.create_all(db.engine,tables=[DictZasob.__table__,RegionZasob.__table__])
        db.session.add_all([DictZasob(zasob_id=i,zasob_kod=code,zasob_nazwa=label,zasob_kategoria='Surowce',zasob_jednostka='szt.') for i,(code,label) in enumerate(RESOURCES,1)]);db.session.commit()
        self.mine=Mine(panstwo_id=1,region_id=1,resource='zloto',map_x=12,map_y=34,starts_at=NOW-timedelta(days=5),ready_at=NOW-timedelta(days=1),extracted_at=NOW,request_id='mine-test')
        db.session.add(self.mine);db.session.commit();self.mine_id=self.mine.id

    def protect(self):
        self.change('defense_place',target_kind='mine',target_id=self.mine_id)
        return db.session.scalar(select(MissileDefense).where(MissileDefense.target_kind=='mine',MissileDefense.target_id==self.mine_id))

    def test_placement_price_position_and_duplicate_or_foreign_rejected(self):
        before=military_budget(db.session,1)[2];defense=self.protect()
        self.assertEqual(before-military_budget(db.session,1)[2],100000000)
        self.assertEqual(defense_data(defense)['position'],[12,34])
        with self.assertRaises(FinanceError):self.protect()
        self.mine.panstwo_id=2;db.session.commit()
        with self.assertRaises(FinanceError):self.change('defense_repair',defense_id=defense.id,count=1)

    def test_mine_intercepts_only_its_attack_and_after_regional_shield(self):
        defense=self.protect();flight=SimpleNamespace(target_country_id=1,missiles=3)
        with patch('game.missile_defense.randbelow',return_value=0):
            self.assertEqual(intercept(db.session,flight,1,'mine',self.mine_id+10),3)
            self.assertEqual(intercept(db.session,flight,1,'mine',self.mine_id),0)
        self.assertEqual(defense.ammunition,97);db.session.commit()
        self.change('defense_place',target_kind='region',target_id=1)
        with patch('game.missile_defense.randbelow',return_value=0):self.assertEqual(intercept(db.session,flight,1,'mine',self.mine_id),0)
        self.assertEqual(defense.ammunition,97)

    def test_destroyed_mine_removes_shield_but_preserves_expense(self):
        defense=self.protect();id=defense.id
        flight=SimpleNamespace(target_kind='mine',target_mine_id=self.mine_id,target_country_id=1)
        with patch('game.military_flights.randbelow',return_value=11):apply_structural_damage(db.session,flight,1,100)
        db.session.commit();db.session.expire_all()
        self.assertIsNone(db.session.get(Mine,self.mine_id));self.assertIsNone(db.session.get(MissileDefense,id))
        expense=db.session.scalar(select(MissileDefenseExpense));self.assertEqual(expense.amount,Decimal(100000000));self.assertIsNone(expense.defense_id)


class BudgetOverviewTests(MilitaryFixture):
    def test_current_half_year_only_and_remaining_after_spending(self):
        with patch('game.budget_overview.game_now',return_value=NOW):
            overview=budget_overview(db.session,1);self.assertEqual((overview['year'],overview['period']),(2990,1));self.assertEqual(len(overview['items']),10);self.assertNotIn('propaganda',[item['code'] for item in overview['items']])   # 25 Nov 2026: bez propagandy
            values={item['code']:item['remaining'] for item in overview['items']};self.assertEqual(values['armed_forces'],Decimal(1000000000000))
            self.change('defense_place',target_kind='region',target_id=1)
            self.assertEqual(next(i['remaining'] for i in budget_overview(db.session,1)['items'] if i['code']=='armed_forces'),values['armed_forces']-100000000)
        with patch('game.budget_overview.game_now',return_value=NOW.replace(month=7)):self.assertEqual(budget_overview(db.session,1)['items'],[])

    def test_notification_icon_categories(self):
        with self.app.test_request_context():
            for kind,message,expected in [('SYSTEM','Wywiad wojskowy: raport','WYWIAD'),('SYSTEM','Pożyczka #3: zaakceptowana','POŻYCZKA'),('INFRASTRUCTURE_COMPLETED',None,'PRACE')]:
                icon=notification_icon(SimpleNamespace(notification_type=kind,system_text=message));from urllib.parse import unquote
                self.assertIn(expected,unquote(icon))
            self.assertIsNone(notification_icon(SimpleNamespace(notification_type='SYSTEM',system_text='Inna wiadomość')))
