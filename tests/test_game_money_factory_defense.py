"""Money units, exact point prices and factory attacks/production/shields."""
import unittest
from decimal import Decimal
from datetime import timedelta
from uuid import uuid4
from unittest.mock import patch
from sqlalchemy import select,text
from extensions import db
from game.money_display import format_money
from game.research_service import settle_production,POINT_PRICE
from game.research_models import AmmunitionFactory,ResearchAccount
from game.military_models import MilitaryFlight,MissileDefense
from game.military_service import create_order
from game.military_flights import complete_flights
from game.missile_defense import defense_data
from test_game_military_flights import FlightFixture
from test_game_military import MilitaryFixture,NOW
from game.finance_service import FinanceError

class MoneyDisplayTests(unittest.TestCase):
    def test_strict_boundaries_one_decimal_and_large_exact_values(self):
        cases=[('0','0,0 MLN ROI'),('123456789','123,5 MLN ROI'),('1000000000','1\u00a0000,0 MLN ROI'),('1000000000.01','1,0 MLD ROI'),('1500000000','1,5 MLD ROI'),('1000000000000','1\u00a0000,0 MLD ROI'),('1000000000000.01','1,0 BLN ROI'),('9007199254740993.27','9\u00a0007,2 BLN ROI'),('-2500000','-2,5 MLN ROI')]
        for value,expected in cases:self.assertEqual(format_money(value),expected)
        self.assertEqual(format_money('NaN'),'—');self.assertEqual(format_money(None),'—');self.assertEqual(POINT_PRICE,400000000)

class FactoryProtectionTests(MilitaryFixture):
    def test_factory_can_be_protected_only_by_its_owner_and_maps_at_factory(self):
        factory=AmmunitionFactory(panstwo_id=1,region_id=1,budget_id=1,map_x=10,map_y=20,cost=2000000000,produced_at=NOW,created_game_at=NOW,request_id=str(uuid4()));db.session.add(factory);db.session.commit();id=factory.id
        self.change('defense_place',target_kind='factory',target_id=id)
        defense=db.session.scalar(select(MissileDefense));self.assertEqual(defense_data(defense)['position'],[10,20])
        self.assertEqual(defense.target_kind,'factory')
        with self.assertRaises(FinanceError):self.change('defense_place',target_kind='factory',target_id=id)
        factory=db.session.get(AmmunitionFactory,id);factory.panstwo_id=2;db.session.commit()
        with self.assertRaises(FinanceError):self.change('defense_upgrade',defense_id=defense.id)

class FactoryAttackTests(FlightFixture):
    def setUp(self):
        super().setUp();self.factory=AmmunitionFactory(panstwo_id=2,region_id=2,budget_id=1,map_x=100,map_y=0,cost=2000000000,produced_at=NOW-timedelta(days=2),created_game_at=NOW-timedelta(days=2),request_id=str(uuid4()));db.session.add(self.factory);db.session.commit();self.factory_id=self.factory.id;self.source_base=self.source()
        from game.commerce_models import ResourceStock
        db.session.add_all([ResourceStock(panstwo_id=2,resource=code,quantity=100) for code in ('zelazo','ropa_naftowa')]);db.session.commit()

    def attack(self,count=1):return create_order(1,dict(kind='missile',target_factory_id=self.factory_id,source_base_id=self.source_base.id,missile_type='short',missiles=count))

    def test_each_hit_takes_exactly_eleven_percent_and_cannot_damage_twice(self):
        id=self.attack();flight=db.session.get(MilitaryFlight,id)
        with patch('game.military_flights.randbelow',return_value=0):complete_flights(db.session,flight.impact_at)
        db.session.commit();db.session.expire_all();self.assertEqual(db.session.get(AmmunitionFactory,self.factory_id).health,89)
        complete_flights(db.session,flight.impact_at);db.session.commit();self.assertEqual(db.session.get(AmmunitionFactory,self.factory_id).health,89)

    def test_factory_defense_intercepts_before_damage(self):
        shield=MissileDefense(panstwo_id=2,region_id=2,target_kind='factory',target_id=self.factory_id,level=1,ammunition=100);db.session.add(shield);db.session.commit()
        id=self.attack();flight=db.session.get(MilitaryFlight,id)
        with patch('game.missile_defense.randbelow',return_value=0):complete_flights(db.session,flight.impact_at)
        db.session.commit();db.session.expire_all();self.assertEqual(db.session.get(AmmunitionFactory,self.factory_id).health,100);self.assertEqual(db.session.get(MissileDefense,shield.id).ammunition,99)

    # Production test: grid with enough energy (since 10 Nov 2026 a deficit stops factories; see test_infrastructure_effects).
    @patch('game.industry_service.powered_factories',new=lambda session,factories,production,resident:{f.id for f in factories})
    def test_overdue_destruction_is_settled_before_factory_produces_future_ammo(self):
        id=self.attack(10)
        settle_production(db.session,2,NOW+timedelta(days=30));db.session.commit();db.session.expire_all()
        factory=db.session.get(AmmunitionFactory,self.factory_id);self.assertEqual(factory.health,0);self.assertIsNotNone(factory.destroyed_at)
        # Only two full days before the incoming strike count; the following thirty do not.
        self.assertEqual(db.session.get(ResearchAccount,2).ammunition,10)
        settle_production(db.session,2,NOW+timedelta(days=60));db.session.commit();self.assertEqual(db.session.get(ResearchAccount,2).ammunition,10)
        with self.assertRaises(FinanceError):self.attack()
