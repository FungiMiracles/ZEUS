"""Obrona, utrzymanie i rozkazy fazy pierwszej — izolowane transakcje."""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from flask import template_rendered
from sqlalchemy import text
from game_features_support import FeatureTestCase
from extensions import db
from models import Region, Wojsko, Stosunki, Miasto
from game.military import military_bp
from game.army import army_bp
from game.military_models import MilitaryBase, MilitaryExpense, MilitaryMaintenance, MilitaryOrder
from game.military_service import (change_defense, reconcile_maintenance, active_counts, upkeep_cost, create_order, CAPACITIES, enemies)
from game.forum_models import GameNotification
from game.finance_service import FinanceError

NOW = datetime(2990,1,1)


class MilitaryFixture(FeatureTestCase):
    def setUp(self):
        super().setUp()
        self.app.register_blueprint(military_bp)
        self.app.register_blueprint(army_bp)
        Wojsko.__table__.create(db.engine)
        Miasto.__table__.create(db.engine)
        # Budget transfers read public trust (sector transfers need trust above 65, since 10 Nov 2026); no row = no data.
        from models import Spoleczenstwo
        Spoleczenstwo.__table__.create(db.engine,checkfirst=True)
        db.session.add(Wojsko(panstwo_id=1,liczba_baz_ladowych=3,liczba_baz_powietrznych=1,liczba_baz_morskich=1,
                            wojska_ladowe_ilosc=100000,wojska_powietrzne_ilosc=30000,wojska_morskie_ilosc=20000,
                            czolgi_ilosc=500,wozy_opancerzone_ilosc=200,wyrzutnie_rakiet_ilosc=100,mysliwce_ilosc=50,
                            okrety_wojenne_ilosc=3,okrety_podwodne_ilosc=1,rakiety_krotkiego_zasiegu=20))
        db.session.execute(text("INSERT INTO game_state_budgets (id,panstwo_id,game_year,period) VALUES (1,1,2990,1)"))
        db.session.execute(text("INSERT INTO game_state_budget_allocations (id,budget_id,category_code,amount) VALUES (1,1,'armed_forces',1000000000000)"))
        db.session.commit()
        industry_clock=patch('game.industry_service.game_now',return_value=NOW);industry_clock.start();self.addCleanup(industry_clock.stop)
        self.clock = patch('game.military_service.game_now',return_value=NOW)
        self.clock.start(); self.addCleanup(self.clock.stop)
        self.flight_clock=patch('game.military_flights.game_now',return_value=NOW)
        self.flight_clock.start();self.addCleanup(self.flight_clock.stop)

    def supply_materials(self,kind,count=1,country=1):
        """13 Nov 2026: budowa bazy zużywa kamień i żelazo — dokładamy dokładnie tyle, ile zużyje (stan magazynu po budowie bez zmian)."""
        from game.military_service import BASE_MATERIALS
        from game.commerce_models import ResourceStock
        for code,need in BASE_MATERIALS.get(kind,{}).items():
            row=db.session.get(ResourceStock,(country,code))
            if row is None:db.session.add(ResourceStock(panstwo_id=country,resource=code,quantity=need*count))
            else:row.quantity+=need*count
        db.session.commit()

    def change(self,action,**data):
        if action in ('deploy','place'):self.supply_materials(data.get('kind'),int(data.get('count',1)) if action=='place' else 1)
        with patch('game.military_service._country_for_user',return_value=SimpleNamespace(PANSTWO_ID=1)):
            change_defense(1,action,data)
        db.session.expire_all()

    def base(self,kind='land',region=1):
        self.change('place',kind=kind,region_id=region,count=1)
        return db.session.query(MilitaryBase).order_by(MilitaryBase.id.desc()).first()

    def set_budget(self,amount,period=1):
        db.session.execute(text('UPDATE game_state_budgets SET period=:period'),{'period':period})
        db.session.execute(text('UPDATE game_state_budget_allocations SET amount=:amount'),{'amount':amount})
        db.session.commit()



class MilitaryTests(MilitaryFixture):
    def test_base_limits_and_sea_coast(self):
        # 13 Nov 2026: liczba baz nie jest ograniczona tabelą „wojsko” (liczba_baz_ladowych=3) — czwarta baza powstaje.
        self.base();self.base();self.base();self.assertEqual(self.base().kind,'land')
        self.assertEqual(db.session.query(MilitaryBase).filter_by(kind='land').count(),4)
        with self.assertRaises(FinanceError): self.base(region=2)
        with self.assertRaises(FinanceError): self.base(kind='naval')
        db.session.get(Region,1).region_polozenie_id=2;db.session.commit()
        self.assertEqual(self.base(kind='naval').level,1)
        self.assertEqual(CAPACITIES['air'][0]['fighters'],25)

    def test_inventory_capacity_and_withdraw(self):
        base=self.base()
        self.change('garrison',base_id=base.id,garrison={'soldiers':10000,'tanks':100,'armored':25})
        base=db.session.get(MilitaryBase,base.id)
        self.assertEqual(active_counts([base])['wojska_ladowe_ilosc'],10000)
        self.assertEqual(upkeep_cost([base]),41000000)
        with self.assertRaises(FinanceError): self.change('garrison',base_id=base.id,garrison={'soldiers':10001})
        with self.assertRaises(FinanceError): self.change('garrison',base_id=base.id,garrison={'fighters':1})
        with self.assertRaises(FinanceError): self.change('garrison',base_id=999,garrison={})
        self.change('withdraw',base_id=base.id)
        self.assertEqual(db.session.get(MilitaryBase,base.id).garrison,{})
        self.assertEqual(db.session.query(MilitaryMaintenance).one().amount,0)

    def test_upgrade_cost_level_seven_and_insufficient_funds(self):
        base=self.base()
        self.change('upgrade',base_id=base.id)
        self.assertEqual(db.session.get(MilitaryBase,base.id).level,2)
        self.assertEqual(db.session.query(MilitaryExpense).one().amount,1000000000)
        self.set_budget(1000000000)
        with self.assertRaises(FinanceError):self.change('upgrade',base_id=base.id)
        self.set_budget(1000000000000)
        for level in range(3,8):self.change('upgrade',base_id=base.id)
        with self.assertRaises(FinanceError):self.change('upgrade',base_id=base.id)
        self.assertEqual(db.session.query(MilitaryExpense).count(),6)
        self.assertEqual(sum(row.amount for row in db.session.query(MilitaryExpense)),264000000000)

    def test_proportional_withdrawal_notification_and_no_duplicates(self):
        base=self.base()
        self.change('garrison',base_id=base.id,garrison={'soldiers':10000,'tanks':100})
        self.set_budget(20400000)
        reconcile_maintenance(db.session,1,NOW);db.session.commit()
        base=db.session.get(MilitaryBase,base.id)
        self.assertEqual(base.garrison['soldiers'],5000)
        self.assertEqual(base.garrison['tanks'],50)
        self.assertEqual(db.session.query(MilitaryMaintenance).one().amount,20400000)
        notice=db.session.query(GameNotification).one()
        self.assertEqual(notice.user_id,1)
        self.assertIn('proporcjonalnie',notice.system_text)
        reconcile_maintenance(db.session,1,NOW);db.session.commit()
        self.assertEqual(db.session.query(GameNotification).count(),1)

    def test_half_years_and_budget_shared_with_upgrades(self):
        base=self.base()
        self.change('garrison',base_id=base.id,garrison={'soldiers':10000})
        self.assertEqual(db.session.query(MilitaryMaintenance).one().amount,40000000)
        self.set_budget(1000000000)
        with self.assertRaises(FinanceError):self.change('upgrade',base_id=base.id)
        self.set_budget(20000000,period=2)
        reconcile_maintenance(db.session,1,datetime(2990,7,1));db.session.commit()
        self.assertEqual(db.session.query(MilitaryMaintenance).count(),2)
        self.assertEqual(db.session.get(MilitaryBase,base.id).garrison['soldiers'],5000)

    def test_upkeep_rollback(self):
        base=self.base();self.change('garrison',base_id=base.id,garrison={'soldiers':10000})
        self.set_budget(0)
        reconcile_maintenance(db.session,1,NOW);db.session.rollback()
        self.assertEqual(db.session.get(MilitaryBase,base.id).garrison['soldiers'],10000)
        self.assertEqual(db.session.query(GameNotification).count(),0)

    def test_pages_access_csrf_and_country_scope(self):
        with patch('game.military.land_targets',return_value=[]):
            self.assertEqual(self.client.get('/game/obrona-panstwa').status_code,200)
            self.assertEqual(self.client.get('/game/panel-wojenny').status_code,403)
        self.assertEqual(self.client.post('/game/obrona-panstwa/zmien',json={}).status_code,403)
        self.assertEqual(self.client.post('/game/obrona-panstwa/zmien',json={'action':'place','kind':'land','count':1,'region_id':2},headers={'X-CSRF-Token':'token'}).status_code,400)
        db.session.add(Stosunki(PANSTWO_ID=1,PANSTWO_ID2=2,stan_id=8));db.session.commit()
        self.assertEqual(enemies(db.session,1),[2])
        with patch('game.military.land_targets',return_value=[2]):self.assertEqual(self.client.get('/game/panel-wojenny').status_code,200)

    def test_orders_consume_missiles_and_enforce_war(self):
        base=self.base()
        base.map_x=0;base.map_y=0;base.garrison={'launchers':1};db.session.commit()
        target_patch=patch('game.military_flights.region_point',return_value=[100,0]);target_patch.start();self.addCleanup(target_patch.stop)
        data={'source_base_id':base.id,'kind':'missile','region_id':2,'missile_type':'short','missiles':2,'infrastructure':'road'}
        with patch('game.military_service._country_for_user',return_value=SimpleNamespace(PANSTWO_ID=1)):
            with self.assertRaises(FinanceError):create_order(1,data)
            db.session.add(Stosunki(PANSTWO_ID=1,PANSTWO_ID2=2,stan_id=8));db.session.commit()
            create_order(1,data)
            with self.assertRaises(FinanceError):create_order(1,{**data,'missiles':21})
            with self.assertRaises(FinanceError):create_order(1,{**data,'region_id':1})
            with self.assertRaises(FinanceError):create_order(1,{**data,'kind':'naval'})
            with patch('game.military_service.land_targets',return_value=[]):
                with self.assertRaises(FinanceError):create_order(1,{'kind':'land','region_id':2,'soldiers':1})
            with patch('game.military_service.land_targets',return_value=[2]):
                create_order(1,{'kind':'land','region_id':2,'soldiers':100,'tanks':1,'armored':1})
        db.session.expire_all()
        self.assertEqual(db.session.query(MilitaryOrder).count(),2)
        self.assertEqual(db.session.query(Wojsko).one().rakiety_krotkiego_zasiegu,18)
        self.assertEqual(db.session.get(Region,2).panstwo_id,2)

    def test_border_requires_segment_not_corner(self):
        from game.military_geography import adjacency
        def feature(id,points):return {'properties':{'region_id':id},'geometry':{'type':'Polygon','coordinates':[points]}}
        regions=[feature(1,[[0,0],[1,0],[1,1],[0,1],[0,0]]),feature(2,[[1,0],[2,0],[2,1],[1,1],[1,.5],[1,0]]),feature(3,[[2,1],[3,1],[3,2],[2,2],[2,1]])]
        graph=adjacency(regions)
        self.assertEqual(graph[1],{2})
        self.assertNotIn(3,graph[2])


class BaseMaterialsTests(MilitaryFixture):
    """13 Nov 2026: budowa baz zużywa kamień i żelazo; bez limitu z tabeli „wojsko”; zwroty przy rezygnacji (100%) i likwidacji (50%)."""
    def stock(self,code):
        from game.commerce_models import ResourceStock
        db.session.expire_all();row=db.session.get(ResourceStock,(1,code));return int(row.quantity) if row else 0

    def put(self,kamien,zelazo):
        from game.commerce_models import ResourceStock
        for code,value in (('kamien',kamien),('zelazo',zelazo)):
            row=db.session.get(ResourceStock,(1,code))
            if row is None:db.session.add(ResourceStock(panstwo_id=1,resource=code,quantity=value))
            else:row.quantity=value
        db.session.commit()

    def place(self,kind,region=1):
        with patch('game.military_service._country_for_user',return_value=SimpleNamespace(PANSTWO_ID=1)):
            change_defense(1,'place',{'kind':kind,'region_id':region,'count':1})
        db.session.expire_all();return db.session.query(MilitaryBase).order_by(MilitaryBase.id.desc()).first()

    def test_costs_per_kind_and_exact_consumption(self):
        from game.military_service import BASE_MATERIALS
        self.assertEqual(BASE_MATERIALS,{'land':{'kamien':21,'zelazo':16},'naval':{'kamien':28,'zelazo':18},'air':{'kamien':20,'zelazo':12}})
        db.session.get(Region,1).region_polozenie_id=2;db.session.commit()
        self.put(100,100)
        land=self.place('land');self.assertEqual((self.stock('kamien'),self.stock('zelazo')),(79,84))
        self.assertEqual(land.deployment_payload['materials'],{'kamien':21,'zelazo':16})
        self.place('naval');self.assertEqual((self.stock('kamien'),self.stock('zelazo')),(51,66))
        self.place('air');self.assertEqual((self.stock('kamien'),self.stock('zelazo')),(31,54))

    def test_missing_materials_block_without_side_effects(self):
        self.put(20,100)   # brakuje 1 kamienia do bazy lądowej
        with self.assertRaisesRegex(FinanceError,'Za mało surowców w magazynie: kamień'):self.place('land')
        self.assertEqual(db.session.query(MilitaryBase).count(),0)
        self.assertEqual((self.stock('kamien'),self.stock('zelazo')),(20,100))

    def test_no_limit_from_army_table(self):
        self.put(21*5,16*5)   # tabela „wojsko”: liczba_baz_ladowych=3
        for _ in range(5):self.place('land')
        self.assertEqual(db.session.query(MilitaryBase).filter_by(kind='land').count(),5)
        self.assertEqual((self.stock('kamien'),self.stock('zelazo')),(0,0))

    def test_buildable_bases_from_stock(self):
        from game.military_service import buildable_bases
        self.put(42,100)
        self.assertEqual(buildable_bases(db.session,1),{'land':2,'air':2,'naval':1,'nuclear':None})

    def test_liquidation_refunds_half_rounded_down_and_legacy_base_nothing(self):
        self.put(21,16);base=self.place('land')
        self.change('liquidate',base_id=base.id)
        self.assertEqual((self.stock('kamien'),self.stock('zelazo')),(10,8))   # 50% z 21 i 16, w dół
        legacy=MilitaryBase(panstwo_id=1,region_id=1,kind='land',level=1,garrison={});db.session.add(legacy);db.session.commit()
        self.change('liquidate',base_id=legacy.id)
        self.assertEqual((self.stock('kamien'),self.stock('zelazo')),(10,8))   # baza sprzed zmiany — bez zwrotu

    def test_nuclear_silo_needs_no_materials(self):
        from game.military_service import BASE_MATERIALS
        self.assertNotIn('nuclear',BASE_MATERIALS)


class PriceChangesTests(MilitaryFixture):
    """13 Nov 2026: 1 punkt rozwoju — 150 mln ROI; elektrownia węglowa (poziom I) — 2,3 mld ROI; progi technologii bez zmian."""
    def test_prices(self):
        from game.research_service import POINT_PRICE
        from game.paga2 import planner
        from game.industry_catalog import POWER_PLANTS
        self.assertEqual(POINT_PRICE,150000000);self.assertEqual(planner.POINT_PRICE,POINT_PRICE)
        self.assertEqual([int(cost) for cost in POWER_PLANTS['coal']['costs']][:1],[2300000000])
