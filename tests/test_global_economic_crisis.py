"""Isolated crisis lifecycle, authorization and concurrent submissions."""
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from flask import Flask
from jinja2 import ChoiceLoader, DictLoader
from sqlalchemy import Integer, MetaData, select, func
from sqlalchemy.orm import Session
from extensions import db
from models import Panstwo, Gospodarka, Region, Miasto, Zdarzenie, ZdarzenieSzablon, ProcentWzrostuStateHistory
from services.global_economic_crisis import GlobalEconomicCrisis, CrisisError, generate_crisis
from routes_zdarzenia import init_zdarzenia_routes

NOW = datetime(3000, 6, 15, 12)


class GlobalEconomicCrisisTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[1] / 'templates'))
        self.app.config.update(TESTING=True, SECRET_KEY='isolated-crisis-test',
            SQLALCHEMY_DATABASE_URI='sqlite:///' + self.tmp.name + '/crisis.db')
        self.app.jinja_loader = ChoiceLoader([DictLoader({'base_layout.html': '{% block content %}{% endblock %}'}), self.app.jinja_loader])
        db.init_app(self.app)
        init_zdarzenia_routes(self.app)
        self.ctx = self.app.app_context(); self.ctx.push()
        db.metadata.create_all(db.engine, tables=[model.__table__ for model in
            [Panstwo, Gospodarka, Region, Miasto, Zdarzenie, ZdarzenieSzablon, GlobalEconomicCrisis]])
        # SQLite autoincrement needs INTEGER; leave the actual MySQL model intact.
        metadata = MetaData()
        Panstwo.__table__.to_metadata(metadata)
        history = ProcentWzrostuStateHistory.__table__.to_metadata(metadata)
        history.c.id.type = Integer()
        history.create(db.engine)
        for id in range(1, 7):
            db.session.add(Panstwo(PANSTWO_ID=id, panstwo_nazwa=f'Country {id}',
                status='usunięte' if id == 6 else 'aktywne', czy_suwerenny='NIE' if id == 3 else 'TAK'))
        for id, growth in [(1, '4'), (2, '-4'), (3, '0'), (4, None), (6, '4')]:
            db.session.add(Gospodarka(gospodarka_id=id, panstwo_id=id, wzrost_pkb=growth))
        db.session.commit()
        self.clock = patch('services.global_economic_crisis.get_current_entenda_datetime', return_value=NOW)
        self.clock.start()
        self.client = self.app.test_client()

    def tearDown(self):
        self.clock.stop(); db.session.remove(); db.engine.dispose(); self.ctx.pop(); self.tmp.cleanup()

    def growths(self):
        db.session.expire_all()
        return dict(db.session.execute(select(Gospodarka.panstwo_id, Gospodarka.wzrost_pkb)).all())

    def test_three_levels_positive_negative_zero_null_deleted_and_audit(self):
        for level, positive, negative in [('deep', '1.00', '-7.00'), ('medium', '2.00', '-6.00'), ('mild', '3.00', '-5.00')]:
            with self.subTest(level=level):
                event_id = generate_crisis(level, 3000, 'Tester')
                growths = self.growths()
                self.assertEqual(growths[1], Decimal(positive))
                self.assertEqual(growths[2], Decimal(negative))
                self.assertEqual(growths[3], 0)
                self.assertIsNone(growths[4])
                self.assertEqual(growths[6], 4)
                event = db.session.get(Zdarzenie, event_id)
                self.assertEqual(event.zdarzenie_typ, 'globalny_kryzys_gospodarczy')
                self.assertTrue(event.effect_applied)
                self.assertIsNone(event.panstwo_id)
                self.assertEqual(event.payload_json['actor'], 'Tester')
                self.assertEqual(event.payload_json['affected_countries'], 3)
                self.assertEqual(event.payload_json['missing_countries'], 2)
                self.assertEqual(db.session.query(ProcentWzrostuStateHistory).filter_by(event_id=event_id).count(), 3)
                # Reset only this isolated fixture for the next severity.
                db.session.query(GlobalEconomicCrisis).delete()
                db.session.query(ProcentWzrostuStateHistory).delete()
                db.session.query(Zdarzenie).delete()
                for id, growth in [(1, 4), (2, -4), (3, 0)]:
                    db.session.get(Gospodarka, id).wzrost_pkb = growth
                db.session.commit()

    def test_duplicate_year_rejected_and_new_year_allowed(self):
        generate_crisis('mild', 3000, 'Tester')
        with self.assertRaises(CrisisError):
            generate_crisis('deep', 3000, 'Tester')
        self.assertEqual(self.growths()[1], 3)
        self.assertEqual(db.session.query(Zdarzenie).count(), 1)
        with patch('services.global_economic_crisis.get_current_entenda_datetime', return_value=datetime(3001, 1, 1)):
            generate_crisis('medium', 3001, 'Tester')
        self.assertEqual(self.growths()[1], Decimal('1.50'))

    def test_invalid_level_stale_year_and_failed_save_leave_no_changes(self):
        for level, year in [('unknown', 3000), ('deep', 2999)]:
            with self.assertRaises(CrisisError):
                generate_crisis(level, year, 'Tester')
        with patch('services.global_economic_crisis.reduced_growth', side_effect=RuntimeError('save failed')):
            with self.assertRaises(RuntimeError):
                generate_crisis('deep', 3000, 'Tester')
        self.assertEqual(self.growths()[1], 4)
        self.assertEqual(db.session.query(GlobalEconomicCrisis).count(), 0)
        self.assertEqual(db.session.query(Zdarzenie).count(), 0)
        self.assertEqual(db.session.query(ProcentWzrostuStateHistory).count(), 0)

    def test_empty_growth_data_does_not_consume_year(self):
        db.session.query(Gospodarka).update({'wzrost_pkb': None}); db.session.commit()
        with self.assertRaises(CrisisError):
            generate_crisis('deep', 3000, 'Tester')
        self.assertEqual(db.session.query(GlobalEconomicCrisis).count(), 0)

    def test_parallel_requests_apply_crisis_only_once(self):
        def run():
            with self.app.app_context():
                try:
                    return generate_crisis('medium', 3000, 'Concurrent tester')
                except CrisisError:
                    return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: run(), range(2)))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(self.growths()[1], 2)
        self.assertEqual(db.session.query(Zdarzenie).count(), 1)

    def test_role_csrf_and_page_panel(self):
        form = dict(level='deep', year='3000', csrf_token='test-token')
        self.assertEqual(self.client.post('/zdarzenia/globalny-kryzys', data=form).status_code, 403)
        with self.client.session_transaction() as browser:
            browser['rola'] = 'czytelnik'; browser['global_crisis_csrf'] = 'test-token'
        self.assertEqual(self.client.post('/zdarzenia/globalny-kryzys', data=form).status_code, 403)
        with patch('routes_zdarzenia.get_current_entenda_datetime', return_value=NOW):
            self.assertNotIn('id="global-crisis-title"', self.client.get('/zdarzenia').get_data(as_text=True))
        with self.client.session_transaction() as browser:
            browser['rola'] = 'wszechmocny'
        self.assertEqual(self.client.post('/zdarzenia/globalny-kryzys', data={**form, 'csrf_token': 'wrong'}).status_code, 403)
        with patch('routes_zdarzenia.get_current_entenda_datetime', return_value=NOW):
            self.assertIn('id="global-crisis-level"', self.client.get('/zdarzenia').get_data(as_text=True))
        self.assertEqual(self.client.post('/zdarzenia/globalny-kryzys', data=form).status_code, 303)
        self.assertEqual(self.growths()[1], 1)

    def test_banner_is_independent_of_filters_and_lasts_only_current_year(self):
        event_id = generate_crisis('medium', 3000, 'Tester')
        for when in [NOW, datetime(3000, 12, 31)]:
            with patch('routes_zdarzenia.get_current_entenda_datetime', return_value=when):
                html = self.client.get('/zdarzenia?typ=nonexistent').get_data(as_text=True)
                self.assertIn('trwa średni globalny kryzys gospodarczy', html)
        with patch('routes_zdarzenia.get_current_entenda_datetime', return_value=datetime(3001, 1, 1)):
            self.assertNotIn('id="global-crisis-banner"', self.client.get('/zdarzenia').get_data(as_text=True))
        with self.client.session_transaction() as browser:
            browser['rola'] = 'wszechmocny'
        self.assertEqual(self.client.post(f'/zdarzenia/usun/{event_id}').status_code, 303)
        self.assertIsNotNone(db.session.get(Zdarzenie, event_id))
        self.assertEqual(self.client.get('/export_zdarzenia_excel').status_code, 200)
