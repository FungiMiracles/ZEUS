"""Satelity szpiegowskie (26 Nov 2026): technologia, fabryka na zamówienie, wyniesienie z bazy lotniczej, dryf po orbicie,
misje rozpoznawcze nad całym państwem (koszt z budżetu służb, 100% skuteczności), widoczność obcych satelitów."""
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4
from unittest.mock import patch
from sqlalchemy import select, text
from extensions import db
from models import Miasto, Wojsko, Region
from test_game_military import NOW
from test_game_commerce import CommerceFixture
from game.finance_service import FinanceError
from game.forum_models import GameNotification
from game.commerce_models import ResourceStock
from game.research_models import ResearchAccount, AmmunitionFactory
from game.industry_catalog import TECHNOLOGIES, FACTORIES
from game.industry_models import IndustryMovement
from game.military_models import MilitaryBase, MissileDefense
from game.satellite_models import SpySatellite, SatelliteMission
from game.intelligence_models import IntelligenceExpense, CounterIntelligence
from game import satellites


def stock(code, country=1):
    db.session.expire_all(); row = db.session.get(ResourceStock, (country, code)); return int(row.quantity) if row else 0


def put(code, quantity, country=1):
    row = db.session.get(ResourceStock, (country, code))
    if row is None: db.session.add(ResourceStock(panstwo_id=country, resource=code, quantity=quantity))
    else: row.quantity = quantity
    db.session.commit()


class SatelliteCatalogTests(CommerceFixture):
    def test_technology_branches_off_radar_with_cost_and_duration(self):
        rule = TECHNOLOGIES['spy_satellite']
        self.assertEqual((rule['label'], rule['cost'], rule['parent'], rule['requires']), ('Satelita szpiegowski', 900, 'radar', ['radar']))
        from game.research_timing import DURATION_DAYS
        self.assertEqual(DURATION_DAYS['spy_satellite'], 60)
        from game.research import technology_layout
        layout = technology_layout()
        self.assertIn('spy_satellite', layout['positions'])
        self.assertTrue(any(edge['child'] == 'spy_satellite' for edge in layout['edges']))

    def test_factory_rules(self):
        rule = FACTORIES['satellites']; level = rule['levels'][0]
        self.assertEqual((rule['label'], level['cost'], rule['build_days'], level['days'], level['energy'], level['product']),
                         ('Fabryka satelitów', 21500000000, 24, 90, 600, 'spy_satellites'))
        self.assertEqual(level['inputs'], {'zelazo': 300, 'ropa_naftowa': 25, 'chip_cemium_i': 3})
        self.assertEqual(level['technologies'], ['spy_satellite'])
        self.assertTrue(rule['on_demand'])
        self.assertNotEqual(rule.get('budget_sector'), 'armed_forces')   # budowa z budżetu infrastruktury


class SatelliteFixture(CommerceFixture):
    def setUp(self):
        super().setUp()
        from game.satellite_views import satellites_bp
        self.app.register_blueprint(satellites_bp)
        self.login(1)
        db.session.add(ResearchAccount(panstwo_id=1, points=0, ammunition=0, nodes={key: value['cost'] for key, value in TECHNOLOGIES.items()}, timers={}))
        db.session.execute(text("INSERT INTO game_state_budget_allocations(id,budget_id,category_code,amount) VALUES(3,1,'security_services',1000000000)"))
        db.session.execute(text("INSERT INTO game_state_budget_allocations(id,budget_id,category_code,amount) VALUES(4,1,'infrastructure',100000000000)"))
        db.session.execute(text("UPDATE panstwa SET status='aktywne'"))
        db.session.get(Miasto, 102).miasto_typ_id = 1   # stolica państwa 2 — punkt (100, 0)
        db.session.commit()
        self.now = NOW
        for target in ['game.research_service.game_now', 'game.industry_service.game_now', 'game.finance_service.game_now', 'game.satellites.game_now',
                       'game.intelligence_service.game_now']:
            p = patch(target, side_effect=lambda: self.now); p.start(); self.addCleanup(p.stop)
        p = patch('engine.clock.get_time_multiplier', return_value=1); p.start(); self.addCleanup(p.stop)

    def air_base(self, country=1, region=1, x=10.0, y=10.0):
        base = MilitaryBase(panstwo_id=country, region_id=region, kind='air', level=1, garrison={}, map_x=x, map_y=y, health=100, operational=True)
        db.session.add(base); db.session.commit(); return base.id

    def ready_to_launch(self):
        put('spy_satellites', 1); put('ropa_naftowa', 300)
        army = db.session.scalar(select(Wojsko).where(Wojsko.panstwo_id == 1)); army.rakiety_dalekiego_zasiegu = 1; db.session.commit()
        return self.air_base()

    def launch(self, base_id, country=1):
        with db.session.no_autoflush:
            result = satellites.launch_in_transaction(db.session, country, {'base_id': base_id, 'request_id': str(uuid4())}, self.now)
        db.session.commit(); db.session.expire_all(); return result

    def settle(self):
        satellites.settle(db.session, self.now); db.session.commit(); db.session.expire_all()

    def orbit(self):
        sat_id, _ = self.launch(self.ready_to_launch())
        self.now = NOW + timedelta(minutes=2); self.settle()
        return sat_id


class SatelliteFactoryTests(SatelliteFixture):
    def op(self, action, **values):
        from game.industry_service import change_industry
        data = dict(action=action, category='factory', request_id=str(uuid4())); data.update(values)
        result = change_industry(1, data); db.session.expire_all(); return result

    def test_build_charges_infrastructure_and_produces_one_satellite_per_90_days(self):
        id = self.op('build', kind='satellites', level=1, region_id=1, x=10, y=10)
        self.assertEqual(db.session.scalar(select(IndustryMovement.amount).order_by(IndustryMovement.id.desc()).limit(1)), Decimal('21500000000'))
        from game import nuclear
        self.assertEqual(nuclear.factory_ready_at(db.session.get(AmmunitionFactory, id)), NOW + timedelta(days=24))
        put('zelazo', 1000); put('ropa_naftowa', 100); put('chip_cemium_i', 10)
        with self.assertRaisesRegex(FinanceError, 'w budowie'): self.op('order', object_id=id, count=1)
        self.now = NOW + timedelta(days=24)
        self.op('order', object_id=id, count=2)
        self.assertEqual((stock('zelazo'), stock('ropa_naftowa'), stock('chip_cemium_i')), (400, 50, 4))
        from game.industry_service import on_demand_energy, settle_industry
        self.assertEqual(on_demand_energy(db.session, 1), Decimal(600))
        self.now = NOW + timedelta(days=24 + 89); settle_industry(db.session, 1, self.now); db.session.commit(); self.assertEqual(stock('spy_satellites'), 0)
        self.now = NOW + timedelta(days=24 + 90); settle_industry(db.session, 1, self.now); db.session.commit(); self.assertEqual(stock('spy_satellites'), 1)
        self.now = NOW + timedelta(days=24 + 180); settle_industry(db.session, 1, self.now); db.session.commit(); self.assertEqual(stock('spy_satellites'), 2)
        self.assertEqual(stock('nuclear_missiles'), 0)
        self.assertEqual(on_demand_energy(db.session, 1), Decimal(0))

    def test_factory_requires_technology(self):
        account = db.session.get(ResearchAccount, 1); nodes = dict(account.nodes); nodes.pop('spy_satellite'); account.nodes = nodes; db.session.commit()
        with self.assertRaisesRegex(FinanceError, 'Satelita szpiegowski'): self.op('build', kind='satellites', level=1, region_id=1, x=10, y=10)


class SatelliteLaunchTests(SatelliteFixture):
    def test_launch_consumes_satellite_missile_and_oil_then_reaches_orbit(self):
        base_id = self.ready_to_launch()
        sat_id, seconds = self.launch(base_id)
        self.assertEqual(seconds, 60)
        self.assertEqual((stock('spy_satellites'), stock('ropa_naftowa')), (0, 0))
        self.assertEqual(db.session.scalar(select(Wojsko.rakiety_dalekiego_zasiegu).where(Wojsko.panstwo_id == 1)), 0)
        sat = db.session.get(SpySatellite, sat_id)
        self.assertEqual((sat.status, sat.orbit_at), ('launching', NOW + timedelta(seconds=60)))
        self.now = NOW + timedelta(seconds=30); self.settle(); self.assertEqual(db.session.get(SpySatellite, sat_id).status, 'launching')
        self.now = NOW + timedelta(seconds=61); self.settle()
        sat = db.session.get(SpySatellite, sat_id)
        self.assertEqual((sat.status, sat.mode), ('orbit', 'drift'))
        hours = (sat.seg_end - sat.seg_start).total_seconds() / 3600
        self.assertAlmostEqual(((sat.to_x - sat.from_x) ** 2 + (sat.to_y - sat.from_y) ** 2) ** .5, 100 * hours, places=3)   # 100 km/h, 1 km = 1 jednostka
        self.assertTrue(db.session.scalar(select(GameNotification.id).where(GameNotification.system_text.like('%osiągnął orbitę%'))))

    def test_drift_continues_in_new_segments(self):
        sat_id = self.orbit()
        first_end = db.session.get(SpySatellite, sat_id).seg_end
        self.now = first_end + timedelta(hours=1); self.settle()
        sat = db.session.get(SpySatellite, sat_id)
        self.assertGreater(sat.seg_end, self.now); self.assertEqual(sat.mode, 'drift')

    def test_launch_requirements(self):
        base_id = self.ready_to_launch()
        put('spy_satellites', 0)
        with self.assertRaisesRegex(FinanceError, 'nie ma satelity'): self.launch(base_id)
        put('spy_satellites', 1); put('ropa_naftowa', 299)
        with self.assertRaisesRegex(FinanceError, 'ropa naftowa'): self.launch(base_id)
        put('ropa_naftowa', 300)
        land = MilitaryBase(panstwo_id=1, region_id=1, kind='land', level=1, garrison={}, map_x=5, map_y=5, health=100); db.session.add(land); db.session.commit()
        with self.assertRaisesRegex(FinanceError, 'bazy lotniczej'): self.launch(land.id)
        abroad = self.air_base(region=2)
        with self.assertRaisesRegex(FinanceError, 'terytorium kraju'): self.launch(abroad)
        army = db.session.scalar(select(Wojsko).where(Wojsko.panstwo_id == 1)); army.rakiety_dalekiego_zasiegu = 0; db.session.commit()
        with self.assertRaisesRegex(FinanceError, 'rakieta dalekiego zasięgu'): self.launch(base_id)
        account = db.session.get(ResearchAccount, 1); nodes = dict(account.nodes); nodes.pop('spy_satellite'); account.nodes = nodes; db.session.commit()
        with self.assertRaisesRegex(FinanceError, 'Satelita szpiegowski'): self.launch(base_id)
        self.assertEqual(stock('spy_satellites'), 1)


class SatelliteMissionTests(SatelliteFixture):
    def mission(self, sat_id, kind='bases', country=2):
        result = satellites.order_mission_in_transaction(db.session, 1, {'satellite_id': sat_id, 'kind': kind, 'country_id': country, 'request_id': str(uuid4())}, self.now)
        db.session.commit(); db.session.expire_all(); return result

    def test_mission_flies_at_600_kmh_costs_120_million_and_reports_whole_country(self):
        enemy_base = MilitaryBase(panstwo_id=2, region_id=2, kind='land', level=2, garrison={}, map_x=90, map_y=5, health=100)
        silo = MilitaryBase(panstwo_id=2, region_id=2, kind='nuclear', level=1, garrison={}, map_x=95, map_y=5, health=100)
        db.session.add_all([enemy_base, silo, CounterIntelligence(panstwo_id=2, level=7)]); db.session.commit()   # kontrwywiad nie działa na satelity
        sat_id = self.orbit()
        sat = db.session.get(SpySatellite, sat_id); start = satellites.position(sat, self.now)
        mission_id = self.mission(sat_id)
        mission = db.session.get(SatelliteMission, mission_id); sat = db.session.get(SpySatellite, sat_id)
        distance = ((100 - start[0]) ** 2 + start[1] ** 2) ** .5
        self.assertAlmostEqual((mission.arrives_at - self.now).total_seconds() / 3600, max(distance / 600, 1 / 60), places=3)
        self.assertEqual((sat.mode, sat.to_x, sat.to_y), ('mission', 100, 0))
        self.assertEqual(db.session.scalar(select(IntelligenceExpense.amount)), Decimal('120000000'))
        with self.assertRaisesRegex(FinanceError, 'wykonuje już misję'): self.mission(sat_id)
        from game.intelligence_service import known_ids
        self.assertNotIn(enemy_base.id, known_ids(db.session, 1, 'bases'))
        self.now = mission.arrives_at + timedelta(minutes=1); self.settle()
        mission = db.session.get(SatelliteMission, mission_id)
        self.assertIsNotNone(mission.completed_at)
        self.assertEqual(mission.report['base_ids'], [enemy_base.id])   # silos tylko w misji „silosy”
        self.assertIn(enemy_base.id, known_ids(db.session, 1, 'bases'))
        self.assertEqual(db.session.get(SpySatellite, sat_id).mode, 'drift')
        self.assertTrue(db.session.scalar(select(GameNotification.id).where(GameNotification.system_text.like('Satelita szpiegowski: Położenie baz wojskowych — państwo%'))))
        silo_mission = self.mission(sat_id, 'silos')
        self.now = db.session.get(SatelliteMission, silo_mission).arrives_at; self.settle()
        self.assertEqual(db.session.get(SatelliteMission, silo_mission).report['base_ids'], [silo.id])
        with self.app.test_request_context():
            objects = satellites.intel_objects(db.session, 1)
        self.assertEqual({(o['kind'], o['id']) for o in objects}, {('base', enemy_base.id), ('base', silo.id)})

    def test_mission_requires_security_budget_and_foreign_country(self):
        sat_id = self.orbit()
        with self.assertRaisesRegex(FinanceError, 'inne istniejące państwo'): self.mission(sat_id, country=1)
        db.session.execute(text("UPDATE game_state_budget_allocations SET amount=119999999 WHERE category_code='security_services'")); db.session.commit()
        with self.assertRaisesRegex(FinanceError, '120 mln'): self.mission(sat_id)
        with self.assertRaisesRegex(FinanceError, 'rodzaj'): self.mission(sat_id, kind='warehouses')

    def test_foreign_satellites_visible_only_with_own_satellite_in_orbit(self):
        foreign = SpySatellite(panstwo_id=2, status='orbit', mode='drift', launched_at=NOW, orbit_at=NOW, from_x=0, from_y=0, to_x=10, to_y=0,
                               seg_start=NOW, seg_end=NOW + timedelta(hours=1), request_id=str(uuid4()))
        db.session.add(foreign); db.session.commit()
        with self.app.test_request_context():
            self.assertEqual(satellites.visible(db.session, 1, self.now), [])
        self.orbit()
        with self.app.test_request_context():
            items = satellites.visible(db.session, 1, self.now)
        self.assertEqual(sorted(item['countryId'] for item in items), [1, 2])
        self.assertEqual(next(i for i in items if i['countryId'] == 2)['own'], False)

    def test_state_endpoint_and_army_summary(self):
        self.orbit(); put('spy_satellites', 2)
        response = self.client.get('/game/satelity/stan')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['enabled']); self.assertEqual(len(data['satellites']), 1)
        self.assertEqual([m['code'] for m in data['missions']], ['bases', 'defenses', 'mines', 'power', 'silos'])
        self.assertEqual(satellites.summary(db.session, 1), {'stock': 2, 'orbit': 1, 'launching': 0, 'total': 3})

    def test_launch_and_mission_routes_require_csrf(self):
        base_id = self.ready_to_launch()
        response = self.client.post('/game/satelity/wystrzel', json={'base_id': base_id, 'request_id': str(uuid4())})
        self.assertEqual(response.status_code, 403)
        response = self.client.post('/game/satelity/wystrzel', json={'base_id': base_id, 'request_id': str(uuid4())}, headers={'X-CSRF-Token': 'token'})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()['seconds'], 60)


class SatelliteUpgradeAndCancelTests(SatelliteFixture):
    def setUp(self):
        super().setUp()
        db.session.execute(text("UPDATE game_state_budget_allocations SET amount=200000000000 WHERE category_code='security_services'")); db.session.commit()

    def upgrade(self, sat_id, expected):
        result = satellites.upgrade_in_transaction(db.session, 1, {'satellite_id': sat_id, 'expected_level': expected, 'request_id': str(uuid4())}, self.now)
        db.session.commit(); db.session.expire_all(); return result

    def mission(self, sat_id):
        result = satellites.order_mission_in_transaction(db.session, 1, {'satellite_id': sat_id, 'kind': 'bases', 'country_id': 2, 'request_id': str(uuid4())}, self.now)
        db.session.commit(); db.session.expire_all(); return result

    def test_levels_speeds_and_costs(self):
        self.assertEqual({level: speed for level, (speed, _) in satellites.LEVELS.items()}, {1: 600, 2: 900, 3: 1200, 4: 1500})
        self.assertEqual([cost for _, cost in list(satellites.LEVELS.values())[1:]], [Decimal('17500000000'), Decimal('29000000000'), Decimal('36200000000')])

    def test_upgrade_charges_security_budget_and_speeds_up_missions(self):
        sat_id = self.orbit()
        self.assertEqual(self.upgrade(sat_id, 1), 2)
        self.assertEqual(db.session.scalar(select(IntelligenceExpense.amount).order_by(IntelligenceExpense.id.desc()).limit(1)), Decimal('17500000000'))
        with self.assertRaises(FinanceError): self.upgrade(sat_id, 1)   # nieaktualny poziom
        self.assertEqual(self.upgrade(sat_id, 2), 3); self.assertEqual(self.upgrade(sat_id, 3), 4)
        with self.assertRaisesRegex(FinanceError, 'najwyższy poziom'): self.upgrade(sat_id, 4)
        sat = db.session.get(SpySatellite, sat_id); start = satellites.position(sat, self.now)
        mission = db.session.get(SatelliteMission, self.mission(sat_id))
        distance = ((100 - start[0]) ** 2 + start[1] ** 2) ** .5
        self.assertAlmostEqual((mission.arrives_at - self.now).total_seconds() / 3600, max(distance / 1500, 1 / 60), places=3)

    def test_upgrade_blocked_during_mission_and_budget_checked(self):
        sat_id = self.orbit(); self.mission(sat_id)
        with self.assertRaisesRegex(FinanceError, 'nie wykonuje misji'): self.upgrade(sat_id, 1)
        sat2 = self.orbit_second()
        db.session.execute(text("UPDATE game_state_budget_allocations SET amount=17000000000 WHERE category_code='security_services'")); db.session.commit()
        with self.assertRaisesRegex(FinanceError, 'służb'): self.upgrade(sat2, 1)

    def orbit_second(self):
        sat = SpySatellite(panstwo_id=1, status='orbit', mode='drift', level=1, launched_at=NOW, orbit_at=NOW, from_x=0, from_y=0, to_x=1, to_y=0,
                           seg_start=self.now, seg_end=self.now + timedelta(hours=5), request_id=str(uuid4()))
        db.session.add(sat); db.session.commit(); return sat.id

    def test_cancel_mission_keeps_cost_and_returns_to_drift(self):
        sat_id = self.orbit(); mission_id = self.mission(sat_id)
        spent = db.session.scalar(select(IntelligenceExpense.amount).order_by(IntelligenceExpense.id.desc()).limit(1))
        self.now = self.now + timedelta(minutes=1)
        here = satellites.position(db.session.get(SpySatellite, sat_id), self.now)
        satellites.cancel_mission_in_transaction(db.session, 1, {'satellite_id': sat_id}, self.now); db.session.commit(); db.session.expire_all()
        sat = db.session.get(SpySatellite, sat_id); mission = db.session.get(SatelliteMission, mission_id)
        self.assertEqual((sat.mode, sat.mission_id), ('drift', None))
        self.assertAlmostEqual(sat.from_x, here[0], places=6); self.assertAlmostEqual(sat.from_y, here[1], places=6)
        self.assertTrue(mission.report['cancelled']); self.assertIsNotNone(mission.completed_at)
        self.assertEqual(db.session.scalar(select(IntelligenceExpense.amount).order_by(IntelligenceExpense.id.desc()).limit(1)), spent)   # bez zwrotu
        from game.intelligence_service import known_ids
        self.assertEqual(known_ids(db.session, 1, 'bases'), set())
        with self.assertRaisesRegex(FinanceError, 'nie wykonuje misji'):
            satellites.cancel_mission_in_transaction(db.session, 1, {'satellite_id': sat_id}, self.now)

    def test_routes(self):
        sat_id = self.orbit()
        response = self.client.post('/game/satelity/rozbuduj', json={'satellite_id': sat_id, 'expected_level': 1, 'request_id': str(uuid4())}, headers={'X-CSRF-Token': 'token'})
        self.assertEqual(response.status_code, 200, response.get_json()); self.assertEqual(response.get_json()['level'], 2)
        response = self.client.post('/game/satelity/anuluj-misje', json={'satellite_id': sat_id, 'request_id': str(uuid4())}, headers={'X-CSRF-Token': 'token'})
        self.assertEqual(response.status_code, 400)
