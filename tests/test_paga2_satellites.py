"""PAGA2 — satelity szpiegowskie (26 Nov 2026): cel planera, wyniesienie na orbitę, misje rozpoznawcze, wykonanie."""
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace as NS
from unittest.mock import patch
from uuid import uuid4
from game_features_support import FeatureTestCase
from extensions import db
from game.paga2 import satellites as ps
from game.satellite_models import SpySatellite, SatelliteMission

NOW = datetime(2026, 11, 26, 12, 0)


def ctx(**extra):
    base = dict(country_id=1, now=NOW, traits={'espionage': 50}, situation={'at_war': [], 'threats': [], 'allies': []},
                world_summary=lambda: {'neighbor_countries': []}, request_key='k')
    base.update(extra)
    return NS(**base)


class PlannerGoalTests(unittest.TestCase):
    def test_satellite_factory_is_a_goal_of_intelligence_and_offense(self):
        from game.paga2.planner import PRIORITY_GOALS, goal_traits
        self.assertEqual(PRIORITY_GOALS['intelligence'][0], 'factory:satellites')
        self.assertIn('factory:satellites', PRIORITY_GOALS['offensive_army'])
        self.assertGreater(goal_traits('factory:satellites')['espionage'], .5)


class TargetTests(unittest.TestCase):
    def test_order_war_then_threats_then_neighbours_without_duplicates(self):
        c = ctx(traits={'espionage': 80}, situation={'at_war': [5], 'threats': [5, 6], 'allies': [8]},
                world_summary=lambda: {'neighbor_countries': [6, 7, 8, 1]})
        with patch('game.paga2.war_plans.intel_requests', return_value=[(1, 9, None)]):
            self.assertEqual([(t[0], t[2]) for t in ps.targets(c)], [(9, 'plan'), (5, 'war'), (6, 'threat'), (7, 'peace')])

    def test_no_peacetime_espionage_for_low_espionage(self):
        c = ctx(world_summary=lambda: {'neighbor_countries': [6]})
        with patch('game.paga2.war_plans.intel_requests', return_value=[]):
            self.assertEqual(ps.targets(c), [])

    def test_wanted_count(self):
        self.assertEqual((ps.wanted(ctx()), ps.wanted(ctx(traits={'espionage': 75}))), (1, 2))
        self.assertEqual(ps.order_options(ctx(), None, 1), [])   # ma już tyle satelitów, ile chce


class LaunchTests(unittest.TestCase):
    def options(self, stock=1, missiles=1, oil=300, base=NS(id=4)):
        with patch('game.satellites.in_stock', return_value=stock), \
             patch('game.governance.army_for_country', return_value=NS(rakiety_dalekiego_zasiegu=missiles)), \
             patch('game.industry_service.available', return_value=oil), \
             patch.object(ps, 'launch_base', return_value=base):
            return ps.launch_options(ctx(), None)

    def test_launch_when_everything_is_ready(self):
        [option] = self.options()
        self.assertEqual((option.action, option.payload['base_id']), ('SATELLITE_LAUNCH', 4))

    def test_no_launch_without_satellite_missile_oil_or_base(self):
        for kwargs in ({'stock': 0}, {'missiles': 0}, {'oil': 299}, {'base': None}):
            with self.subTest(**{k: str(v) for k, v in kwargs.items()}):
                self.assertEqual(self.options(**kwargs), [])


class MissionTests(FeatureTestCase):
    def satellite(self, mode='drift', status='orbit'):
        sat = SpySatellite(panstwo_id=1, status=status, mode=mode, level=1, launched_at=NOW, orbit_at=NOW, from_x=0, from_y=0, to_x=0, to_y=0,
                           seg_start=NOW, seg_end=NOW, request_id=str(uuid4()))
        db.session.add(sat); db.session.commit(); return sat.id

    def missions(self, c):
        from sqlalchemy.orm import Session
        with patch('game.satellites.settle'), patch('game.finance_service.game_now', return_value=NOW), Session(db.engine) as session:
            return ps.mission_options(c, session)

    def test_idle_satellite_scouts_enemy_kinds_in_order_and_skips_recent(self):
        sat = self.satellite()
        c = ctx(situation={'at_war': [2], 'threats': [], 'allies': []})
        with patch('game.paga2.war_plans.intel_requests', return_value=[]):
            [first] = self.missions(c)
            self.assertEqual((first.action, first.payload['kind'], first.payload['country_id'], first.sector), ('SATELLITE_MISSION', 'bases', 2, 'security_services'))
            db.session.add(SatelliteMission(panstwo_id=1, satellite_id=sat, kind='bases', target_country_id=2, target_name='B', cost=120000000,
                                            starts_at=NOW - timedelta(days=3), arrives_at=NOW, request_id=str(uuid4())))
            db.session.commit()
            [second] = self.missions(c)
            self.assertEqual(second.payload['kind'], 'defenses')     # baz już szukano w ostatnich 30 dniach

    def test_busy_or_launching_satellite_gets_no_mission(self):
        self.satellite(mode='mission'); self.satellite(status='launching')
        with patch('game.paga2.war_plans.intel_requests', return_value=[]):
            self.assertEqual(self.missions(ctx(situation={'at_war': [2], 'threats': [], 'allies': []})), [])


class ExecuteTests(unittest.TestCase):
    def test_calls_game_routes(self):
        from game.paga2.scoring import Option
        calls = []
        c = ctx(call=lambda path, json=None: calls.append((path, json)) or (200, {'ok': True}))
        for action, payload in (('SATELLITE_ORDER', {'factory_id': 3, 'count': 1}), ('SATELLITE_LAUNCH', {'base_id': 4}),
                                ('SATELLITE_MISSION', {'satellite_id': 5, 'kind': 'bases', 'country_id': 2})):
            ps.execute(c, Option(key=f'sat:{action}', domain='intelligence', action=action, label='x', payload=payload))
        self.assertEqual([p for p, _ in calls], ['/game/infrastruktura/obiekty/zmien', '/game/satelity/wystrzel', '/game/satelity/misja'])
        self.assertEqual(calls[0][1]['action'], 'order')
        self.assertEqual({k: calls[2][1][k] for k in ('satellite_id', 'kind', 'country_id')}, {'satellite_id': 5, 'kind': 'bases', 'country_id': 2})
        self.assertTrue(all(json.get('request_id') for _, json in calls))


if __name__ == '__main__':
    unittest.main()
