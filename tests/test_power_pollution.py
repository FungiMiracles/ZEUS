"""Coal power plant air pollution and pollution filters (administrator rules, 10 Nov 2026)."""
import unittest
from decimal import Decimal
from uuid import uuid4
from sqlalchemy import select
from extensions import db
from models import Region
import test_industry_0011 as industry_fixture
from game.industry_catalog import TECHNOLOGIES,FILTER_COSTS,POWER_PLANTS
from game.industry_models import PowerPlant,IndustryMovement
from game.research_models import ResearchAccount
from game.finance_service import FinanceError


class PowerPollutionTests(unittest.TestCase):
    def setUp(self):
        self.base=industry_fixture.IndustryTests();self.base.setUp()
        from sqlalchemy import text
        # Filters are paid from the environmental protection budget (since 10 Nov 2026).
        db.session.execute(text("INSERT INTO game_state_budget_allocations (id,budget_id,category_code,amount) VALUES (90,1,'environment',10000000000)"));db.session.commit()
        self.pollution(10)
    def tearDown(self):self.base.tearDown()
    def pollution(self,value=None):
        row=db.session.get(Region,1)
        if value is not None:row.region_zanieczyszczenie_powietrza=value;db.session.commit()
        db.session.expire_all();return db.session.get(Region,1).region_zanieczyszczenie_powietrza
    def build(self,kind='coal'):return self.base.operation(category='power',kind=kind)
    def act(self,action,id):return self.base.operation(action=action,category='power',object_id=id)
    def last_cost(self):return db.session.scalar(select(IndustryMovement.amount).order_by(IndustryMovement.id.desc()).limit(1))
    def last_sector(self):return db.session.scalar(select(IndustryMovement.sector).order_by(IndustryMovement.id.desc()).limit(1))
    def plant(self,id):db.session.expire_all();return db.session.get(PowerPlant,id)

    def test_technology_named_and_priced(self):
        rule=TECHNOLOGIES['air_filters']
        self.assertEqual((rule['label'],rule['cost'],rule['parent'],rule['icon']),('Filtr zanieczyszczeń',150,'environment_tech','air_filter'))
        self.assertEqual(FILTER_COSTS,[500000000,700000000,900000000])

    def test_coal_plant_adds_two_points_and_liquidation_removes_them(self):
        first=self.build();self.assertEqual(self.pollution(),12)
        self.build();self.assertEqual(self.pollution(),14)
        self.build('solar');self.assertEqual(self.pollution(),14,'only coal plants pollute')
        self.act('remove',first);self.assertEqual(self.pollution(),12)
        self.assertEqual(self.plant(first).pollution_points,0)

    def test_pollution_stays_within_zero_and_hundred_and_missing_data_is_zero(self):
        self.pollution(99);id=self.build();self.assertEqual(self.pollution(),100)
        self.pollution(1);self.act('remove',id);self.assertEqual(self.pollution(),0)
        db.session.get(Region,1).region_zanieczyszczenie_powietrza=None;db.session.commit()
        self.build();self.assertEqual(self.pollution(),2)

    def test_filter_requires_technology(self):
        id=self.build()
        account=db.session.get(ResearchAccount,1);nodes=dict(account.nodes);nodes.pop('air_filters');account.nodes=nodes;db.session.commit()
        with self.assertRaises(FinanceError) as error:self.act('filter',id)
        self.assertIn('Filtr zanieczyszczeń',str(error.exception))
        self.assertFalse(self.plant(id).air_filter);self.assertEqual(self.pollution(),12)

    def test_filter_cost_by_level_stops_pollution_and_is_not_refunded(self):
        id=self.build();self.assertEqual(self.pollution(),12)
        self.act('filter',id);self.assertEqual(self.last_cost(),Decimal(500000000));self.assertEqual(self.last_sector(),'environment')
        plant=self.plant(id);self.assertTrue(plant.air_filter);self.assertEqual(plant.pollution_points,0);self.assertEqual(self.pollution(),10)
        with self.assertRaises(FinanceError):self.act('filter',id)
        self.act('remove',id)
        self.assertEqual(self.last_cost(),-Decimal(POWER_PLANTS['coal']['costs'][0])/4,'refund covers the plant only, not the filter')
        self.assertEqual(self.pollution(),10,'a filtered plant added nothing, so liquidation removes nothing')

    def test_filter_on_higher_levels_and_upgrade_surcharge(self):
        id=self.build();self.act('upgrade',id);self.assertEqual(self.last_cost(),Decimal(POWER_PLANTS['coal']['costs'][1]))
        self.act('filter',id);self.assertEqual(self.last_cost(),Decimal(700000000))
        self.act('upgrade',id)
        rows=db.session.execute(select(IndustryMovement.sector,IndustryMovement.amount).order_by(IndustryMovement.id.desc()).limit(2)).all()
        self.assertEqual(sorted(rows),[('environment',Decimal(200000000)),('infrastructure',Decimal(POWER_PLANTS['coal']['costs'][2]))],'plant from infrastructure, filter difference 2→3 from environment')
        self.assertTrue(self.plant(id).air_filter)

    def test_filter_only_for_coal_plants(self):
        id=self.build('solar')
        with self.assertRaises(FinanceError):self.act('filter',id)

    def test_state_exposes_filter_and_pollution(self):
        from game.industry_service import industry_state
        coal=self.build();solar=self.build('solar')
        with self.base.app.test_request_context():rows={row['id']:row for row in industry_state(db.session,1)['objects'] if row['category']=='power'}
        self.assertEqual((rows[coal]['pollution'],rows[coal]['airFilter'],rows[coal]['filterCost']),(2,False,500000000))
        self.assertEqual((rows[solar]['pollution'],rows[solar]['filterCost']),(0,None))
        self.act('filter',coal)
        with self.base.app.test_request_context():row=next(r for r in industry_state(db.session,1)['objects'] if r['id']==coal and r['category']=='power')
        self.assertEqual((row['pollution'],row['airFilter'],row['filterCost']),(0,True,None))
        self.assertEqual(row['upgradeCost'],POWER_PLANTS['coal']['costs'][1]+200000000)

    def test_front_end_shows_filter_badge_and_pollution_icon(self):
        from pathlib import Path
        script=(Path(__file__).resolve().parents[1]/'static/js/game_industry.js').read_text()
        for text in ('Dodaj filtr zanieczyszczeń',"'FILTR.svg'","'ZANIECZYSZCZENIE POWIETRZA.svg'","'filter'"):self.assertIn(text,script)
        icons=Path(__file__).resolve().parents[1]/'static/icons'
        self.assertTrue((icons/'FILTR.svg').exists());self.assertTrue((icons/'ZANIECZYSZCZENIE POWIETRZA.svg').exists())
