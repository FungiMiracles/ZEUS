"""Depletion dates use Entenda days and current, shared industrial flows."""
from datetime import datetime,timedelta
from uuid import uuid4
from fractions import Fraction
from sqlalchemy import select
from extensions import db
from models import RegionZasob,Region
from test_game_commerce import CommerceFixture
from test_game_military import NOW
from game.research_models import AmmunitionFactory
from game.industry_models import PowerPlant
from game.commerce_models import ResourceStock,Mine
from game.industry_catalog import FACTORIES
from game.warehouse_forecast import depletion_dates,daily_flows


class WarehouseForecastTests(CommerceFixture):
    def stock(self,code,quantity):
        row=db.session.get(ResourceStock,(1,code))
        if row:row.quantity=quantity
        else:db.session.add(ResourceStock(panstwo_id=1,resource=code,quantity=quantity))

    def factory(self,kind,level=1,**values):
        values.setdefault('production_target',10**6)   # 22 Nov 2026: fabryka pracuje tylko w ramach zlecenia produkcji
        obj=AmmunitionFactory(panstwo_id=1,region_id=1,budget_id=1,map_x=10,map_y=10,level=level,kind=kind,cost=0,created_game_at=NOW,produced_at=NOW,request_id=str(uuid4()),**values)
        db.session.add(obj)
        for code,amount in FACTORIES[kind]['levels'][level-1]['inputs'].items():self.stock(code,max(100,amount))
        db.session.commit();return obj

    def forecast(self,**stocks):
        return depletion_dates(db.session,1,{code:{'available':quantity} for code,quantity in stocks.items()},now=NOW)

    def test_daily_factories_sum_all_inputs_and_round_up_entenda_days(self):
        self.factory('chips');self.factory('interceptor_ammo')
        self.assertEqual(self.forecast(zelazo=100,ropa_naftowa=100,srebro=100,chip_simple=0),{'zelazo':'08.01.2990','ropa_naftowa':'21.01.2990','srebro':'11.01.2990'})

    def test_fuel_minus_extraction_and_equal_or_positive_balance(self):
        plant=PowerPlant(panstwo_id=1,region_id=1,kind='coal',level=2,health=3,map_x=1,map_y=1,investment=1,created_game_at=NOW,checked_at=NOW)
        mine=Mine(panstwo_id=1,region_id=1,resource='wegiel_kamienny',level=1,health=100,investment=1,map_x=1,map_y=1,starts_at=NOW-timedelta(days=6),ready_at=NOW-timedelta(days=1),extracted_at=NOW,request_id=str(uuid4()))
        db.session.add_all([plant,mine]);db.session.commit()
        self.assertEqual(self.forecast(wegiel_kamienny=20),{'wegiel_kamienny':'21.01.2990'})
        plant.level=1;db.session.commit()
        self.assertEqual(self.forecast(wegiel_kamienny=20),{})
        mine.level=2;db.session.commit()
        self.assertEqual(self.forecast(wegiel_kamienny=20),{})

    def test_unavailable_objects_do_not_affect_rates(self):
        factory=self.factory('chips',paused=True)
        self.assertEqual(self.forecast(zelazo=100),{})
        factory.paused=False;factory.health=0;db.session.commit()
        self.assertEqual(self.forecast(zelazo=100),{})
        factory.health=100;factory.removed_at=NOW;db.session.commit()
        self.assertEqual(self.forecast(zelazo=100),{})
        factory.removed_at=None;self.stock('zloto',0);db.session.commit()
        self.assertEqual(self.forecast(zelazo=100),{})

    def test_weekly_and_monthly_recipes_use_daily_average(self):
        factory=self.factory('tanks')
        self.assertEqual(self.forecast(zelazo=10,ropa_naftowa=5,chip_simple=1),{'zelazo':'08.01.2990','ropa_naftowa':'08.01.2990','chip_simple':'08.01.2990'})
        factory.removed_at=NOW;db.session.commit()
        shipyard=self.factory('shipyard')
        incoming,usage=daily_flows(db.session,1,datetime(2990,1,31))
        self.assertEqual(usage['zelazo'],Fraction(41,28))
        self.assertEqual(incoming['warships'],Fraction(1,28))
        shipyard.production_progress=3;shipyard.cycle_days=31;db.session.commit()
        self.assertEqual(daily_flows(db.session,1,NOW)[1]['zelazo'],Fraction(41,31))

    def test_chip_production_offsets_consumption(self):
        self.factory('chips');self.factory('tanks')
        self.assertNotIn('chip_simple',self.forecast(chip_simple=1))

    def test_empty_deposit_building_and_foreign_mines_not_counted(self):
        plant=PowerPlant(panstwo_id=1,region_id=1,kind='coal',level=1,health=3,map_x=1,map_y=1,investment=1,created_game_at=NOW,checked_at=NOW)
        mine=Mine(panstwo_id=1,region_id=1,resource='wegiel_kamienny',level=1,health=100,investment=1,map_x=1,map_y=1,starts_at=NOW,ready_at=NOW+timedelta(days=1),extracted_at=NOW+timedelta(days=1),request_id=str(uuid4()))
        db.session.add_all([plant,mine]);db.session.commit()
        self.assertEqual(self.forecast(wegiel_kamienny=20),{'wegiel_kamienny':'21.01.2990'})
        mine.starts_at=NOW-timedelta(days=5);mine.ready_at=NOW;mine.extracted_at=NOW;deposit=db.session.scalar(select(RegionZasob).where(RegionZasob.region_id==1));deposit.zloze_ilosc=0;db.session.commit()
        self.assertEqual(self.forecast(wegiel_kamienny=20),{'wegiel_kamienny':'21.01.2990'})
        deposit.zloze_ilosc=100;db.session.get(Region,1).panstwo_id=2;db.session.commit()
        self.assertEqual(self.forecast(wegiel_kamienny=20),{'wegiel_kamienny':'21.01.2990'})

    def test_huge_stocks_outside_calendar_do_not_break_page(self):
        self.factory('chips')
        self.assertEqual(self.forecast(zelazo=10**29),{})
