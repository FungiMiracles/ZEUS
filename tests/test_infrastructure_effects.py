"""Regional infrastructure effects (administrator rules, 10 Nov 2026): energy output, energy deficit, mining time,
port export limits, connection expansion and the shared module funds container."""
import unittest
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4
from unittest.mock import patch
from sqlalchemy import select
from extensions import db
from models import Region
import test_industry_0011 as industry_fixture
import test_game_commerce as commerce_fixture
from game.infrastructure_effects import energy_factor,power_output,extraction_time_factor,port_export_limit


class ThresholdTests(unittest.TestCase):
    def test_energy_tiers_and_rounding_up(self):
        for level,factor in [(100,1),(80,1),(79,Decimal('0.8')),(60,Decimal('0.8')),(59,Decimal('0.5')),(30,Decimal('0.5')),(29,Decimal('0.25')),(10,Decimal('0.25')),(9,0),(0,0)]:
            with self.subTest(level=level):self.assertEqual(energy_factor(level),factor)
        self.assertEqual(power_output(12,70),10,'9.6 is rounded up');self.assertEqual(power_output(10,25),3,'2.5 is rounded up')
        self.assertEqual(power_output(100,5),0);self.assertEqual(power_output(12,None),12,'no data is not penalised')

    def test_rail_tiers(self):
        for level,factor in [(80,1),(79,Decimal('1.2')),(59,Decimal('1.4')),(29,Decimal('1.6')),(10,Decimal('1.6')),(9,None)]:
            with self.subTest(level=level):self.assertEqual(extraction_time_factor(level),factor)

    def test_port_tiers(self):
        for level,limit in [(100,(None,None)),(80,(None,None)),(79,(500,None)),(60,(500,None)),(59,(300,None)),(30,(300,None)),(29,(100,None)),(10,(100,None)),(9,(100,'wegiel_kamienny')),(None,(None,None))]:
            with self.subTest(level=level):self.assertEqual(port_export_limit(level),limit)


class EnergyTests(unittest.TestCase):
    def setUp(self):
        self.base=industry_fixture.IndustryTests();self.base.setUp()
    def tearDown(self):self.base.tearDown()
    def region(self,**values):
        row=db.session.get(Region,1)
        for key,value in values.items():setattr(row,key,value)
        db.session.commit()

    def test_plant_output_follows_regional_energy_infrastructure(self):
        from game.industry_service import energy_balance
        self.base.operation(category='power',kind='solar');self.base.operation(category='power',kind='wind');self.base.refresh()
        self.region(region_stan_infra_energetycznej=70)
        sources=energy_balance(db.session,1)['sources']
        self.assertEqual((sources['solar']['production'],sources['wind']['production']),(7,5),'21 Nov 2026: 8×0.8=6.4→7, 6×0.8=4.8→5 (zaokrąglenie w górę)')
        self.region(region_stan_infra_energetycznej=5)
        self.assertEqual(energy_balance(db.session,1)['production'],'0')
        from game.industry_service import industry_state
        with self.base.app.test_request_context():state=industry_state(db.session,1)
        plants=[row for row in state['objects'] if row['category']=='power']
        self.assertTrue(all(row['status']=='brak infrastruktury' and row['efficiencyPercent']==0 for row in plants))

    def test_deficit_stops_largest_consumers_first_and_notifies(self):
        from game.industry_service import powered_factories,settle_industry,FACTORIES
        from game.research_models import AmmunitionFactory
        from game.forum_models import GameNotification
        energies=sorted({(rule['levels'][0]['energy'],kind) for kind,rule in FACTORIES.items() if rule['levels'][0]['energy']>0})
        small,large=energies[0],energies[-1];self.assertLess(small[0],large[0])
        ids={kind:self.base.operation(kind=kind) for _,kind in (small,large)};self.base.refresh()
        factories=list(db.session.scalars(select(AmmunitionFactory)))
        with patch('game.industry_service.factory_can_work',return_value=True):
            self.assertEqual(powered_factories(db.session,factories,small[0],Decimal(0)),{ids[small[1]]},'the largest consumer stops first')
            self.assertEqual(powered_factories(db.session,factories,small[0]+large[0],Decimal(0)),set(ids.values()))
            self.assertEqual(powered_factories(db.session,factories,0,Decimal(0)),set())
        factory=db.session.get(AmmunitionFactory,ids[small[1]]);factory.running=True;factory.ever_worked=True;db.session.commit()
        with patch('game.industry_service.factory_can_work',return_value=True),patch('game.industry_service.economy',return_value={'population':0}):
            settle_industry(db.session,1,industry_fixture.NOW+timedelta(days=1));db.session.commit()
        self.assertTrue(db.session.scalar(select(GameNotification.id).where(GameNotification.system_text.like('%brak energii w sieci%'))))


class MiningAndPortTests(unittest.TestCase):
    def setUp(self):
        self.base=commerce_fixture.CommerceFixture();self.base.setUp()
        from game.commerce_models import Mine
        self.Mine=Mine
    def tearDown(self):self.base.tearDown()
    def region(self,**values):
        row=db.session.get(Region,1)
        for key,value in values.items():setattr(row,key,value)
        db.session.commit()
    def ready_mine(self):
        id=self.base.mine();mine=db.session.get(self.Mine,id);mine.extracted_at=mine.ready_at;db.session.commit();return id,mine.ready_at

    def test_rail_infrastructure_lengthens_extraction_time(self):
        from game.mining_service import extract_country
        from game.commerce_models import ResourceStock
        from models import RegionZasob
        db.session.scalar(select(RegionZasob).where(RegionZasob.region_id==1,RegionZasob.zasob_id==1)).zloze_ilosc=100;db.session.commit()
        id,start=self.ready_mine();self.region(region_stan_infra_kolejowej=70)
        before=db.session.get(ResourceStock,(1,'wegiel_kamienny')).quantity
        extract_country(db.session,1,start+timedelta(days=1));db.session.commit()
        self.assertEqual(db.session.get(ResourceStock,(1,'wegiel_kamienny')).quantity,before,'one unit now takes 1.2 days')
        extract_country(db.session,1,start+timedelta(days=1,hours=5));db.session.commit()
        self.assertEqual(db.session.get(ResourceStock,(1,'wegiel_kamienny')).quantity,before+1)
        self.region(region_stan_infra_kolejowej=5)
        extract_country(db.session,1,start+timedelta(days=5));db.session.commit()
        self.assertEqual(db.session.get(ResourceStock,(1,'wegiel_kamienny')).quantity,before+1,'no extraction below 10')
        self.assertEqual(db.session.get(self.Mine,id).extracted_at,start+timedelta(days=5),'time passes: no backlog later')

    def test_port_infrastructure_limits_sea_export(self):
        # 22 Nov 2026: limit infrastruktury portowej obowiązuje przy zakupie — za duży ładunek nie może wypłynąć z tego portu
        # (droga morska z tego portu jest niedostępna), oferta może być wystawiona.
        from game.commerce_models import ResourceStock,TradeOffer
        from game.trade_routes import delivery_options
        db.session.get(ResourceStock,(1,'wegiel_kamienny')).quantity=5000;db.session.add(ResourceStock(panstwo_id=1,resource='zloto',quantity=50));db.session.commit()
        sea=lambda id:any(o['mode']=='sea' for o in delivery_options(db.session,db.session.get(TradeOffer,id),2))
        self.region(region_stan_infra_portowej=65)
        self.assertFalse(sea(create(self,{'wegiel_kamienny':501})))
        self.assertTrue(sea(create(self,{'wegiel_kamienny':500})))
        self.region(region_stan_infra_portowej=5)
        self.assertFalse(sea(create(self,{'zloto':1})))
        self.assertFalse(sea(create(self,{'wegiel_kamienny':101})))
        self.assertTrue(sea(create(self,{'wegiel_kamienny':100})))
        self.region(region_stan_infra_portowej=85)
        self.assertTrue(sea(create(self,{'wegiel_kamienny':300})))


def create(case,cargo):
    from game.trade_service import create_offer
    return create_offer(1,dict(request_id=str(uuid4()),cargo=cargo,price='1000'))


class ExpansionAndFundsTests(unittest.TestCase):
    def test_connection_level_can_be_expanded(self):
        from pathlib import Path
        root=Path(__file__).resolve().parents[1]
        self.assertNotIn('Rozbudowa skomunikowania jest obecnie niedostępna',(root/'game/infrastructure_service.py').read_text())
        self.assertNotIn("metric.code === 'connection'",(root/'static/js/game_infrastructure.js').read_text())

    def test_module_sector_assignment(self):
        from game.module_funds import MODULE_SECTORS
        self.assertEqual(MODULE_SECTORS,{'infrastructure':'infrastructure','defense':'armed_forces','war':'armed_forces','army':'armed_forces',
                                         'intelligence':'security_services','research':'research','environment':'environment','demography':'social_policy','society':'social_policy','trade':None,'diplomacy':None})

    def test_infrastructure_screen_texts(self):
        from pathlib import Path
        page=(Path(__file__).resolve().parents[1]/'templates/game/infrastructure.html').read_text()
        self.assertIn('Stan infrastruktury wpływa na efektywność produkcji energii, produkcji przemysłowej, wydobycia oraz przepustowości portów w danym regionie.',page)
        self.assertIn('Koszt rozbudowy zależny jest od populacji regionu.',page)
