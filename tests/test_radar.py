"""Radary (11 Nov 2026): technologia, budowa, rozbudowa, likwidacja, wykrywanie lotów, cel ataku i obrona przeciwrakietowa."""
import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from sqlalchemy import select
from sqlalchemy.orm import Session
from extensions import db
from models import Stosunki, Region
from test_game_military import MilitaryFixture, NOW
from game.finance_service import FinanceError
from game.commerce_models import ResourceStock
from game.military_models import MilitaryOrder, MilitaryFlight, MissileDefense
from game.radar_models import Radar, RadarExpense, RadarDetection
from game.forum_models import GameNotification
from game import radar as radars

ROOT = Path(__file__).resolve().parents[1]


def key():
    return str(uuid.uuid4())


class RadarFixture(MilitaryFixture):
    def setUp(self):
        super().setUp()
        self.now = NOW
        for target in ('game.radar.game_now',):
            clock = patch(target, side_effect=lambda: self.now); clock.start(); self.addCleanup(clock.stop)
        self.player = 1
        who = patch('game.finance_service._country_for_user', side_effect=lambda session, user_id, lock=False: SimpleNamespace(PANSTWO_ID=self.player))
        who.start(); self.addCleanup(who.stop)
        self.tech = True
        tech = patch('game.industry_service.researched', side_effect=lambda session, country, key: self.tech); tech.start(); self.addCleanup(tech.stop)
        inside = patch('game.military_geography.region_contains', return_value=True); inside.start(); self.addCleanup(inside.stop)
        db.session.add_all([ResourceStock(panstwo_id=1, resource='chip_natsyt', quantity=10), ResourceStock(panstwo_id=1, resource='zelazo', quantity=1000)])
        db.session.commit()

    def act(self, **data):
        result = radars.change_radar(1, data)
        db.session.expire_all()
        return result

    def build(self, x=500, y=0, region=1):
        return self.act(action='build', region_id=region, x=x, y=y, request_id=key())[0]

    def stock(self, code):
        db.session.expire_all()
        return int(db.session.get(ResourceStock, (1, code)).quantity)


class TechnologyTests(RadarFixture):
    def test_research_bubble_branches_off_the_natsyt_chip(self):
        from game.industry_catalog import TECHNOLOGIES, TECHNOLOGY_DESCRIPTIONS
        from game.research import technology_layout
        rule = TECHNOLOGIES['radar']
        self.assertEqual((rule['label'], rule['cost'], rule['parent'], rule['icon']), ('Rozpoznanie radarowe', 600, 'chip_natsyt', 'radar'))
        self.assertIn('radar', TECHNOLOGY_DESCRIPTIONS)
        layout = technology_layout()
        self.assertIn('radar', layout['positions'])
        self.assertTrue(any(edge['child'] == 'radar' for edge in layout['edges']))
        self.assertIn("'radar':'RADAR.svg'", (ROOT / 'templates/macros/icons.html').read_text())
        self.assertTrue((ROOT / 'static/icons/RADAR.svg').exists())

    def test_building_requires_the_technology(self):
        self.tech = False
        with self.assertRaises(FinanceError) as error:
            self.build()
        self.assertIn('Rozpoznanie radarowe', str(error.exception))


class BuildTests(RadarFixture):
    def test_level_costs_and_budget(self):
        from game.military_service import military_budget
        with Session(db.engine) as session:
            before = military_budget(session, 1)[2]
        radar_id = self.build()
        radar = db.session.get(Radar, radar_id)
        self.assertEqual((radar.level, radar.health, radar.map_x, radar.region_id), (1, 100, 500, 1))
        self.assertEqual((self.stock('chip_natsyt'), self.stock('zelazo')), (9, 900))
        self.act(action='upgrade', radar_id=radar_id)
        self.assertEqual((self.stock('chip_natsyt'), self.stock('zelazo')), (7, 750))
        self.act(action='upgrade', radar_id=radar_id)
        self.assertEqual((self.stock('chip_natsyt'), self.stock('zelazo')), (4, 550))
        self.assertEqual(db.session.get(Radar, radar_id).level, 3)
        self.assertEqual(sorted(int(row.amount) for row in db.session.query(RadarExpense)), [11_000_000_000, 18_000_000_000, 24_000_000_000])
        with Session(db.engine) as session:
            after = military_budget(session, 1)[2]
        self.assertEqual(before - after, Decimal(53_000_000_000), 'radar costs come from the armed forces budget')
        with self.assertRaises(FinanceError) as error:
            self.act(action='upgrade', radar_id=radar_id)
        self.assertIn('maksymalny', str(error.exception))

    def test_missing_resources_or_money(self):
        db.session.get(ResourceStock, (1, 'zelazo')).quantity = 99
        db.session.commit()
        with self.assertRaises(FinanceError) as error:
            self.build()
        self.assertIn('żelaza', str(error.exception))
        db.session.get(ResourceStock, (1, 'zelazo')).quantity = 1000
        db.session.commit()
        self.set_budget(10_000_000_000)
        with self.assertRaises(FinanceError) as error:
            self.build()
        self.assertIn('budżecie sił zbrojnych', str(error.exception))
        self.assertEqual(self.stock('chip_natsyt'), 10, 'nothing is consumed by a refused build')

    def test_only_own_unoccupied_region_and_idempotent(self):
        with self.assertRaises(FinanceError):
            self.build(region=2)
        request = key()
        first = self.act(action='build', region_id=1, x=1, y=1, request_id=request)[0]
        self.assertEqual(self.act(action='build', region_id=1, x=1, y=1, request_id=request)[0], first)
        self.assertEqual(db.session.query(Radar).count(), 1)
        from game.land_war_models import Occupation
        db.session.add(Occupation(kind='region', region_id=1, owner_id=1, occupier_id=2, status='ACTIVE', started_at=NOW)); db.session.commit()
        with self.assertRaises(FinanceError) as error:
            self.build()
        self.assertIn('okupowany', str(error.exception))

    def test_location_cannot_change(self):
        radar_id = self.build()
        with self.assertRaises(FinanceError):
            self.act(action='location', radar_id=radar_id, x=1, y=1)
        script = (ROOT / 'static/js/game_radar.js').read_text()
        self.assertNotIn("action:'location'", script)
        self.assertIn('Lokalizacji radaru nie można zmienić.', script)

    def test_liquidation_refund_regardless_of_level(self):
        radar_id = self.build()
        self.act(action='upgrade', radar_id=radar_id)
        db.session.add(MissileDefense(panstwo_id=1, region_id=1, target_kind='radar', target_id=radar_id, level=1, ammunition=10)); db.session.commit()
        chips, iron = self.stock('chip_natsyt'), self.stock('zelazo')
        message = self.act(action='liquidate', radar_id=radar_id)[1]
        self.assertIn('1 chip natsytowy i 20 żelaza', message)
        self.assertIsNone(db.session.get(Radar, radar_id))
        self.assertEqual((self.stock('chip_natsyt'), self.stock('zelazo')), (chips + 1, iron + 20))
        self.assertEqual(db.session.query(MissileDefense).count(), 0)

    def test_not_tradeable(self):
        from game.industry_catalog import GOODS
        self.assertNotIn('radar', GOODS)
        from game.trade_goods import trade_warehouse
        with Session(db.engine) as session:
            self.assertFalse(any('radar' in code for code in trade_warehouse(session, 1)))


class DetectionTests(RadarFixture):
    def setUp(self):
        super().setUp()
        self.radar_id = self.build(x=500, y=0)            # level I: 400 km (1 map unit = 1 km)
        order = MilitaryOrder(panstwo_id=2, user_id=2, region_id=1, kind='missile', payload={'missile_type': 'short', 'missiles': 7})
        db.session.add(order); db.session.flush()
        flight = MilitaryFlight(order_id=order.id, panstwo_id=2, target_country_id=3, kind='missile', missile_type='short', missiles=7, target_name='Cel Testowy',
                                source_x=0, source_y=0, target_x=1000, target_y=0, distance_km=1000, starts_at=NOW, impact_at=NOW + timedelta(seconds=1000))
        db.session.add(flight); db.session.commit()
        self.flight_id = flight.id

    def detect(self, seconds):
        self.now = NOW + timedelta(seconds=seconds)
        with Session(db.engine) as session, session.begin():
            return radars.detect(session, self.now)

    def test_track_covers_only_the_part_inside_the_range(self):
        with Session(db.engine) as session:
            items = radars.radar_flights(session, 1, set(), NOW)
        self.assertEqual(len(items), 1)
        piece = items[0]['radarTrack'][0]
        self.assertAlmostEqual(piece['from'][0], 100); self.assertAlmostEqual(piece['to'][0], 900)
        self.assertNotIn('source', items[0], 'the launch site of a foreign flight stays hidden')
        self.assertEqual((items[0]['missiles'], items[0]['targetName']), (7, 'Cel Testowy'))
        with Session(db.engine) as session:
            self.assertEqual(radars.radar_flights(session, 2, set(), NOW), [], 'own flights are not radar sightings')

    def test_one_notification_when_entering_the_range(self):
        self.assertEqual(self.detect(50), 0, 'not yet in range (enters at 100 s)')
        self.assertEqual(self.detect(150), 1)
        self.assertEqual(self.detect(300), 0, 'one notification per flight')
        row = db.session.query(RadarDetection).one()
        self.assertEqual((row.panstwo_id, row.flight_id, row.radar_id), (1, self.flight_id, self.radar_id))
        text = [n.system_text for n in db.session.query(GameNotification) if 'Radar' in (n.system_text or '')]
        self.assertEqual(len(text), 1)
        self.assertIn('7', text[0]); self.assertIn('Cel: Cel Testowy', text[0])

    def test_range_grows_with_level_and_destroyed_radar_is_blind(self):
        self.assertEqual(radars.LEVELS[2]['range_km'], 800); self.assertEqual(radars.LEVELS[3]['range_km'], 1200)
        db.session.get(Radar, self.radar_id).health = 0; db.session.commit()
        self.assertEqual(self.detect(500), 0)
        with Session(db.engine) as session:
            self.assertEqual(radars.radar_flights(session, 1, set(), NOW), [])


class AttackTests(RadarFixture):
    def test_missile_defense_and_damage(self):
        radar_id = self.build()
        from game.missile_defense import change_defense_system, defense_data, intercept
        with Session(db.engine) as session, session.begin():
            change_defense_system(session, 1, 'defense_place', {'target_kind': 'radar', 'target_id': radar_id})
        defense = db.session.query(MissileDefense).one()
        self.assertEqual((defense.target_kind, defense.target_id, defense.region_id), ('radar', radar_id, 1))
        with Session(db.engine) as session:
            self.assertEqual(defense_data(session.get(MissileDefense, defense.id))['position'], [500, 0])
            flight = SimpleNamespace(missiles=50, target_country_id=1)
            with patch('game.missile_defense.randbelow', return_value=0):
                self.assertEqual(intercept(session, flight, 1, 'radar', radar_id), 0, 'the radar defence intercepts')
        from game.military_flights import apply_structural_damage, impact_summary
        with Session(db.engine) as session, session.begin():
            flight = SimpleNamespace(target_kind='radar', target_radar_id=radar_id, target_country_id=1, impact_at=NOW)
            with patch('game.military_flights.randbelow', return_value=11):
                damage = apply_structural_damage(session, flight, None, 10)
        self.assertEqual(damage, {'radarHealthLost': 100, 'remainingHealth': 0, 'radarDestroyed': True})
        self.assertIn('Radar został zniszczony', impact_summary(SimpleNamespace(damage=damage, intercepted=0, missiles=10, casualties=0)))
        db.session.expire_all()
        self.assertEqual(db.session.get(Radar, radar_id).health, 0)
        self.assertEqual(db.session.query(MissileDefense).count(), 0)

    def test_war_order_targets_an_enemy_radar(self):
        enemy = Radar(panstwo_id=2, region_id=2, map_x=100, map_y=0, level=1, health=100, request_id=key(), created_game_at=NOW)
        db.session.add(enemy); db.session.add(Stosunki(PANSTWO_ID=1, PANSTWO_ID2=2, stan_id=8)); db.session.commit()
        source = self.base('land')
        source.map_x, source.map_y = 0, 0
        source.garrison = {**source.garrison, 'launchers': 1}
        db.session.merge(source); db.session.commit()
        from game.military_service import create_order
        with patch('game.military_service._country_for_user', return_value=SimpleNamespace(PANSTWO_ID=1)):
            flight_id = create_order(1, {'kind': 'missile', 'region_id': 2, 'target_radar_id': enemy.id, 'source_base_id': source.id, 'missile_type': 'short', 'missiles': 1})
        flight = db.session.get(MilitaryFlight, flight_id)
        self.assertEqual((flight.target_kind, flight.target_radar_id, flight.target_name), ('radar', enemy.id, f'Radar #{enemy.id}'))


class InterfaceTests(RadarFixture):
    def test_filters_hover_range_and_template(self):
        template = (ROOT / 'templates/game/military.html').read_text()
        self.assertIn("('radars','Radary','RADAR.svg')", template)
        self.assertIn('js/game_radar.js', template)
        script = (ROOT / 'static/js/game_radar.js').read_text()
        for text in ("'Zbuduj radar'", "'Zlikwiduj radar'", 'L.circle(', "marker.on('mouseover',()=>showRange(radar))", "defenseActions('radar'"):
            self.assertIn(text, script)
        military = (ROOT / 'static/js/game_military.js').read_text()
        self.assertIn("'radars'", military)
        self.assertIn("'target_radar_id'", military)
        self.assertIn('radarSighting', military)

    def test_radar_module_ready_before_the_first_region_panel(self):
        """Regression (11 Nov 2026): a remembered region is drawn before the map exists; the radar module must already be initialised."""
        military = (ROOT / 'static/js/game_military.js').read_text()
        init = military.index('window.GameRadar?.init(')
        self.assertLess(init, military.index("const saved = sessionStorage.getItem('military-selected')"))
        self.assertLess(init, military.index('const map = L.map('))
        self.assertGreater(military.index('window.GameRadar?.attach(map)'), military.index('const map = L.map('))
        script = (ROOT / 'static/js/game_radar.js').read_text()
        self.assertIn("if(!api||cfg.mode!=='defense')return;", script)
