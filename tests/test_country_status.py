"""Country visibility is enforced across query styles and secession lifecycle."""
import json
import unittest
from pathlib import Path
from uuid import uuid4
from datetime import datetime
from sqlalchemy import select, func
from sqlalchemy.orm import Session, aliased, lazyload
from extensions import db
from models import Panstwo, Region, Miasto, PKBStateHistory
import test_region_secession as fixtures
from engine.selectors import select_regions
from services.region_secession import secede, rejoin, SecessionError
from services.world_charts import annual_country_values


class CountryStatusTests(unittest.TestCase):
    setUp = fixtures.RegionSecessionTests.setUp
    tearDown = fixtures.RegionSecessionTests.tearDown
    payload = fixtures.RegionSecessionTests.payload

    def test_search_status_filter_pagination_and_other_filters(self):
        from flask import template_rendered
        from jinja2 import ChoiceLoader, DictLoader
        from routes_panstwa import init_panstwa_routes
        root = Path(__file__).resolve().parents[1]
        self.app.template_folder = str(root / 'templates')
        self.app.jinja_loader = ChoiceLoader([
            DictLoader({'base_layout.html': '{% block content %}{% endblock %}'}),
            self.app.jinja_loader,
        ])
        init_panstwa_routes(self.app)
        self.app.add_url_rule('/home', 'home_page', lambda: '')
        self.archive()
        db.session.add_all([Panstwo(PANSTWO_ID=id, panstwo_nazwa=f'Archived {id}',
            status='usunięte', kontynent_id=1) for id in range(10, 36)])
        db.session.commit()
        contexts = []
        def capture(sender, template, context, **extra):
            contexts.append(context)
        with template_rendered.connected_to(capture, self.app):
            response = self.client.get('/wyniki_wyszukiwania')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(contexts[-1]['total'], 2)
            self.assertEqual(contexts[-1]['selected_status'], 'aktywne')
            response = self.client.get('/wyniki_wyszukiwania?status=usunięte')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(contexts[-1]['total'], 27)
            self.assertEqual(len(contexts[-1]['results']), 25)
            self.assertIn('Status: usunięte', response.get_data(as_text=True))
            self.assertIn('status=usuni%C4%99te', response.get_data(as_text=True))
            self.assertNotIn('Wyświetl', response.get_data(as_text=True))
            self.client.get('/wyniki_wyszukiwania?status=usunięte&page=2')
            self.assertEqual(len(contexts[-1]['results']), 2)
            self.client.get('/wyniki_wyszukiwania?status=usunięte&panstwo_nazwa=Target')
            self.assertEqual([p.PANSTWO_ID for p in contexts[-1]['results']], [2])
            self.client.get('/wyniki_wyszukiwania?status=invalid')
            self.assertEqual(contexts[-1]['total'], 2)
        self.assertEqual(db.session.query(Panstwo.PANSTWO_ID).count(), 2)

    def archive(self, id=2):
        country = db.session.get(Panstwo, id)
        country.status = 'usunięte'
        db.session.commit()
        return country

    def test_lists_projections_counts_sums_aliases_and_cached_get(self):
        deleted = self.archive()
        self.assertEqual([p.PANSTWO_ID for p in Panstwo.query.all()], [1, 3])
        self.assertEqual(db.session.query(Panstwo.PANSTWO_ID).count(), 2)
        self.assertEqual(db.session.query(func.sum(Panstwo.panstwo_populacja)).scalar(), 1320)
        self.assertEqual(list(db.session.scalars(select(Panstwo.PANSTWO_ID))), [1, 3])
        alias = aliased(Panstwo)
        self.assertEqual(list(db.session.scalars(select(alias.PANSTWO_ID))), [1, 3])
        self.assertIsNone(db.session.get(Panstwo, 2))
        self.assertIsNone(Panstwo.query.get(2))
        with self.assertRaises(Exception) as raised:
            Panstwo.query.get_or_404(2)
        self.assertEqual(raised.exception.code, 404)
        self.assertIs(db.session.get(Panstwo, 2, execution_options={'include_deleted_countries': True}), deleted)
        self.assertEqual(Panstwo.query.execution_options(include_deleted_countries=True).count(), 3)
        with Session(db.engine) as standalone:
            self.assertEqual(list(standalone.scalars(select(Panstwo.PANSTWO_ID))), [1, 3])

    def test_generator_excludes_regions_of_deleted_country(self):
        self.archive()
        self.assertEqual({r.region_id for r in select_regions(300)}, {11, 12})

    def test_apis_and_rankings_hide_deleted_and_reject_direct_chart(self):
        from routes_api import init_api_routes
        from routes_wykresy import init_wykresy_routes
        from routes_panstwa import init_panstwa_api, init_panstwa_routes
        init_api_routes(self.app)
        init_wykresy_routes(self.app)
        init_panstwa_routes(self.app)
        init_panstwa_api(self.app)
        self.archive()
        self.assertNotIn('2', self.client.get('/api/panstwa_nazwy').get_json())
        self.assertNotIn('2', self.client.get('/api/panstwa_meta').get_json())
        countries = self.client.get('/api/panstwa_by_kontynent?kontynent_id=1').get_json()
        self.assertNotIn(2, [p['id'] for p in countries])
        ranking = self.client.get('/api/wykresy/ranking?typ=powierzchnia').get_json()
        self.assertNotIn(2, [p['id'] for p in ranking['ranking']])
        self.assertEqual(self.client.get('/api/wykresy/chart?panstwo_id=2&typ=pkb').status_code, 404)

    def test_world_history_excludes_deleted_countries(self):
        for id in (1, 2):
            db.session.add(PKBStateHistory(id=id, panstwo_id=id, old_pkb=50, new_pkb=100,
                data_entenda=datetime(3000, 1, 1), source='test'))
        db.session.commit()
        self.archive()
        self.assertEqual(annual_country_values(db.session, PKBStateHistory, PKBStateHistory.new_pkb), {3000: {1: 100}})

    def test_map_and_snapshot_hide_deleted(self):
        id = secede(11, self.payload(), 'Tester')
        rejoin(11, dict(request_id=str(uuid4()), expected_country_id=str(id), target_country_id='1'), 'Tester')
        self.assertEqual(self.client.get(f'/wiki/panstwo/{id}/mapa-po-secesji').status_code, 404)
        maps = Path(self.tmp.name) / 'maps'
        (maps / 'entenda_panstwa.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [
            {'type': 'Feature', 'properties': {'panstwo_id': pid}, 'geometry': None} for pid in (1, id)]}))
        (maps / 'entenda_regiony.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': []}))
        data = self.client.get('/wiki/mapa/panstwa.geojson').get_json()
        self.assertEqual([f['properties']['panstwo_id'] for f in data['features']], [1])

    def test_rejoin_retains_country_that_has_another_region(self):
        id = secede(11, self.payload(), 'Tester')
        db.session.add(Region(region_id=99, region_nazwa='Other', panstwo_id=id))
        db.session.commit()
        rejoin(11, dict(request_id=str(uuid4()), expected_country_id=str(id), target_country_id='1'), 'Tester')
        self.assertEqual(db.session.get(Panstwo, id).status, 'aktywne')

    def test_deleted_target_rejected(self):
        id = secede(11, self.payload(), 'Tester')
        self.archive()
        with self.assertRaises(SecessionError):
            rejoin(11, dict(request_id=str(uuid4()), expected_country_id=str(id), target_country_id='2'), 'Tester')
