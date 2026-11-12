"""Persistent clock transitions never jump, and only admins may change speed."""
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from flask import Flask
from sqlalchemy.orm import Session
from extensions import db
from engine.clock import (SimulationClock, ClockError, get_clock_snapshot, set_clock_speed,
    get_current_entenda_datetime, get_current_entenda_date, get_time_multiplier, ENTENDA_START, REAL_START)
from routes_clock import clock_bp

REAL = datetime(2026, 10, 27, 12, 0, 0, 123456)
GAME = datetime(3000, 6, 15, 12, 0, 0, 654321)


class SimulationClockTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SECRET_KEY='clock-fixture-only',
            SQLALCHEMY_DATABASE_URI='sqlite:///:memory:', ENTENDA_CLOCK_CONTROL_ENABLED=True)
        db.init_app(self.app); self.app.register_blueprint(clock_bp)
        self.ctx = self.app.app_context(); self.ctx.push()
        SimulationClock.__table__.create(db.engine)
        db.session.add(SimulationClock(id=1, real_anchor=REAL, entenda_anchor=GAME, multiplier=12, revision=0))
        db.session.commit()
        self.timer = patch('engine.clock.datetime', wraps=datetime)
        self.now = self.timer.start(); self.now.now.return_value = REAL
        self.client = self.app.test_client()

    def tearDown(self):
        self.timer.stop(); db.session.remove(); db.engine.dispose(); self.ctx.pop()

    def test_pause_resume_all_speeds_and_continuity(self):
        expected = GAME
        for revision, speed in enumerate([0, 6, 12, 24, 36]):
            snapshot = set_clock_speed(speed, revision, 'Tester')
            self.assertEqual(datetime.fromisoformat(snapshot['entenda']), expected)
            self.now.now.return_value += timedelta(seconds=10)
            expected += timedelta(seconds=10*speed)
            self.assertEqual(get_current_entenda_datetime(), expected)
            self.assertEqual(get_time_multiplier(), speed)
            self.assertEqual(get_current_entenda_date(), expected.date())

    def test_stale_revision_and_invalid_values_rejected(self):
        set_clock_speed(0, 0, 'Tester')
        for speed, revision in [(36, 0), (-1, 1), (1, 1), (True, 1), ('12', 1)]:
            with self.assertRaises(ClockError):
                set_clock_speed(speed, revision, 'Tester')
        self.assertEqual(get_time_multiplier(), 0)

    def test_separate_sessions_see_persistent_state_and_pause_survives_elapsed_real_time(self):
        set_clock_speed(0, 0, 'Tester')
        self.now.now.return_value += timedelta(days=30)
        with Session(db.engine) as session:
            row = session.get(SimulationClock, 1)
            self.assertEqual((row.multiplier, row.revision, row.actor), (0, 1, 'Tester'))
        db.session.remove()
        self.assertEqual(get_current_entenda_datetime(), GAME)

    def test_legacy_clock_when_control_not_enabled(self):
        self.app.config['ENTENDA_CLOCK_CONTROL_ENABLED'] = False
        self.assertEqual(get_current_entenda_datetime(), ENTENDA_START+(REAL-REAL_START)*12)
        with self.assertRaises(ClockError):
            set_clock_speed(0, 0, 'Tester')

    def test_authorization_csrf_conflict_and_state_api(self):
        from routes_auth import HASLA_ROLE
        payload = dict(multiplier=0, revision=0)
        self.assertEqual(self.client.get('/wiki/zegar').get_json()['multiplier'], 12)
        self.assertEqual(self.client.post('/wiki/zegar/tempo', json=payload).status_code, 403)
        with self.client.session_transaction() as browser:
            browser['rola'] = 'czytelnik'; browser['clock_csrf'] = 'test-token'
        self.assertEqual(self.client.post('/wiki/zegar/tempo', json=payload, headers={'X-CSRF-Token':'test-token'}).status_code, 403)
        with self.client.session_transaction() as browser:
            browser['rola'] = 'wszechmocny'
        self.assertEqual(self.client.post('/wiki/zegar/tempo', json=payload).status_code, 403)
        for password in [None, '', 'wrong', 123]:
            rejected = dict(payload, password=password)
            self.assertEqual(self.client.post('/wiki/zegar/tempo', json=rejected,
                headers={'X-CSRF-Token':'test-token'}).status_code, 403)
            self.assertEqual(get_clock_snapshot()['revision'], 0)
        payload['password'] = HASLA_ROLE['wszechmocny']
        response = self.client.post('/wiki/zegar/tempo', json=payload, headers={'X-CSRF-Token':'test-token'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['multiplier'], 0)
        self.assertEqual(self.client.post('/wiki/zegar/tempo',
            json=dict(multiplier=6, revision=1), headers={'X-CSRF-Token':'test-token'}).status_code, 403)
        self.assertEqual(get_clock_snapshot()['revision'], 1)
        response = self.client.post('/wiki/zegar/tempo', json=payload, headers={'X-CSRF-Token':'test-token'})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()['clock']['multiplier'], 0)

    def test_generator_does_not_run_when_paused(self):
        from engine.generator import generate_events
        set_clock_speed(0, 0, 'Tester')
        with patch('engine.generator.run_annual_growth_regeneration') as annual:
            self.assertEqual(generate_events(), 0)
            annual.assert_not_called()
