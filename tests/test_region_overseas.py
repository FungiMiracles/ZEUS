"""Znacznik zamorski: zapis z rzeczywistych formularzy WIKI."""
from unittest.mock import patch
from sqlalchemy import select
from game_features_support import FeatureTestCase
from extensions import db
from models import (Region, RegionZasob, DictZasob, RegionBudzet, RegionInfrastruktura,
                    DictInfrastruktura, RegionMagazyn, DictRegionTeren, DictRegionPolozenie,
                    DictRegionTyp, Fauna, Flora)
from routes_regiony import init_regiony_routes


class OverseasWikiTests(FeatureTestCase):
    def setUp(self):
        super().setUp()
        init_regiony_routes(self.app)
        for model in (RegionZasob, DictZasob, RegionBudzet, RegionInfrastruktura,
                      DictInfrastruktura, RegionMagazyn, DictRegionTeren, DictRegionPolozenie,
                      DictRegionTyp, Fauna, Flora):
            model.__table__.create(db.engine)
        for name in ('fauna_panstwo', 'flora_panstwo'):
            db.metadata.tables[name].create(db.engine)
        with self.client.session_transaction() as browser:
            browser['rola'] = 'wszechmocny'
        self.render = patch('routes_regiony.render_template', side_effect=lambda name, **context: context.get('error', name))
        self.render.start()
        self.addCleanup(self.render.stop)

    def test_add_default_and_overseas(self):
        for name, value in [('Domyślny', None), ('Zamorski', 'TAK')]:
            data = {'region_nazwa': name, 'panstwo_id': '1'}
            if value:
                data['terytorium_zamorskie'] = value
            response = self.client.post('/region_form_add', data=data)
            self.assertEqual(response.status_code, 302)
            region = db.session.scalar(select(Region).where(Region.region_nazwa == name))
            self.assertEqual(region.terytorium_zamorskie, value == 'TAK')

    def test_edit_toggle_and_invalid_value(self):
        for value in ('TAK', 'NIE'):
            response = self.client.post('/region/1/edit', data={'region_nazwa': 'Pierwszy region', 'panstwo_id': '1', 'terytorium_zamorskie': value})
            self.assertEqual(response.status_code, 302)
            db.session.expire_all()
            self.assertEqual(db.session.get(Region, 1).terytorium_zamorskie, value == 'TAK')
        response = self.client.post('/region/1/edit', data={'region_nazwa': 'Pierwszy region', 'panstwo_id': '1', 'terytorium_zamorskie': 'invalid'})
        self.assertIn('Nieprawidłowa wartość', response.get_data(as_text=True))
        self.assertFalse(db.session.get(Region, 1).terytorium_zamorskie)

    def test_player_cannot_change_flag(self):
        with self.client.session_transaction() as browser:
            browser.pop('rola')
        self.assertEqual(self.client.post('/region/1/edit', data={'terytorium_zamorskie': 'TAK'}).status_code, 403)
