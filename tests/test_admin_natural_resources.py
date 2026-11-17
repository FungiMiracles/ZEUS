"""Panel zasobów WIKI — izolowana baza SQLite, bez aplikacji i schedulerów."""
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask, render_template
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.datastructures import MultiDict

from extensions import db
from models import CountryMiningSettings, DictZasob, Panstwo, Region, RegionZasob
from routes_admin import init_admin_routes
from services.natural_resources import MAX_QUANTITY, RESOURCES, field_name


class NaturalResourcesTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        self.app = Flask(__name__, template_folder=str(root / 'templates'), static_folder=str(root / 'static'))
        self.app.config.update(TESTING=True, SECRET_KEY='resource-test-only', SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        db.init_app(self.app)
        from routes_region_secession import region_sovereignty_bp
        self.app.register_blueprint(region_sovereignty_bp)
        init_admin_routes(self.app)
        names = ['home_page', 'wejscie', 'zeus_versions', 'zdarzenia_list', 'raporty_stan_tabel',
                 'wykresy', 'mapy', 'historia', 'kultura', 'sily_zbrojne', 'gospodarka',
                 'demografia', 'natura', 'dyplomacja', 'artykuly', 'pliki', 'info']
        for name in names:
            self.app.add_url_rule('/test/' + name, name, lambda: '')
        self.app.add_url_rule('/test/menu', 'test_menu', lambda: render_template('base_layout.html'))
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.metadata.create_all(db.engine, tables=[model.__table__ for model in [
            Panstwo, Region, DictZasob, RegionZasob, CountryMiningSettings,
        ]])
        db.session.add_all([
            Panstwo(PANSTWO_ID=1, panstwo_nazwa='Testlandia'),
            Panstwo(PANSTWO_ID=2, panstwo_nazwa='Inny kraj'),
            Panstwo(PANSTWO_ID=3, panstwo_nazwa='Bez regionów'),
            Region(region_id=11, panstwo_id=1, region_nazwa='Północ'),
            Region(region_id=12, panstwo_id=1, region_nazwa='Południe'),
            Region(region_id=21, panstwo_id=2, region_nazwa='Obcy region'),
            *[DictZasob(zasob_id=index, zasob_kod=code, zasob_nazwa=name,
                        zasob_kategoria='Surowce naturalne', zasob_jednostka='jednostka')
              for index, (code, name) in enumerate(RESOURCES, 1)],
        ])
        db.session.commit()
        self.client = self.app.test_client()
        self.role('wszechmocny')
        self.path = '/admin/surowce-naturalne?country_id=1'
        self.assertEqual(self.client.get(self.path).status_code, 200)

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.ctx.pop()

    def role(self, name):
        with self.client.session_transaction() as browser:
            browser.clear()
            if name is not None:
                browser['rola'] = name

    def form(self, country_id=1, amount='0', technology='50'):
        settings = db.session.get(CountryMiningSettings, country_id)
        with self.client.session_transaction() as browser:
            token = browser.get('wiki_resources_csrf', '')
        data = {'csrf_token': token, 'country_id': str(country_id), 'version': str(settings.version if settings else 0),
                'technology': technology}
        region_ids = db.session.scalars(select(Region.region_id).where(Region.panstwo_id == country_id)).all()
        data.update({field_name(region_id, code): amount for region_id in region_ids for code, _ in RESOURCES})
        return data

    def count(self, model):
        return db.session.scalar(select(func.count()).select_from(model))

    def test_separate_region_and_technology_updates(self):
        data = self.form(technology='35')
        data = {key: value for key, value in data.items() if not key.startswith('quantity_')}
        self.assertEqual(self.client.post(self.path, data=dict(data, action='technology')).status_code, 303)
        self.assertEqual(self.count(RegionZasob), 0)
        data = self.form(amount='42')
        data = {key: value for key, value in data.items() if not key.startswith('quantity_12_')}
        self.assertEqual(self.client.post(self.path + '&region_id=11', data=dict(data, action='region', region_id='11')).status_code, 303)
        self.assertEqual(self.count(RegionZasob), len(RESOURCES))
        self.assertEqual(db.session.get(CountryMiningSettings, 1).technology, 35)
        data = self.form()
        data = {key: value for key, value in data.items() if not key.startswith('quantity_12_')}
        self.assertEqual(self.client.post(self.path, data=dict(data, action='region', region_id='21')).status_code, 400)

    def test_random_preview_requires_confirmation(self):
        data = dict(self.form(), action='generate', resource='cemium', minimum='10', maximum='400')
        response = self.client.post(self.path, data=data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.count(RegionZasob), 0)
        import re
        html = response.get_data(as_text=True)
        values = dict(re.findall(r'name="(quantity_[^"]+)" value="([0-9]+)"', html))
        for region_id in [11, 12]:
            self.assertTrue(10 <= int(values[field_name(region_id, 'cemium')]) <= 400)
            self.assertEqual(values[field_name(region_id, 'zloto')], '0')
        confirmed = dict(self.form(), **values, action='bulk')
        self.assertEqual(self.client.post(self.path, data=confirmed).status_code, 303)
        self.assertEqual(self.count(RegionZasob), len(RESOURCES)*2)
        self.assertEqual(self.client.post(self.path, data=dict(data, minimum='401')).status_code, 400)
        self.assertEqual(self.client.post(self.path, data=dict(data, resource='unknown')).status_code, 400)

    def test_infrastructure_suggestion_and_region_selection(self):
        region = db.session.get(Region, 11)
        region.region_stan_infra_kolejowej = 40
        region.region_stan_infra_drogowej = 60
        db.session.commit()
        response = self.client.get('/admin/surowce-naturalne?region_id=11')
        self.assertEqual(response.status_code, 200)
        self.assertIn('data-value="50"', response.get_data(as_text=True))
        self.assertIn('Zatwierdź złoża regionu', response.get_data(as_text=True))
        self.assertEqual(self.count(CountryMiningSettings), 0)

    def test_permissions_and_menu_visibility(self):
        self.assertIn('Surowce naturalne', self.client.get('/test/menu').get_data(as_text=True))
        for role in ['tworzyciel', 'obserwator', None]:
            self.role(role)
            self.assertEqual(self.client.get(self.path).status_code, 403)
            self.assertEqual(self.client.post(self.path, data={}).status_code, 403)
            self.assertNotIn('/admin/surowce-naturalne', self.client.get('/test/menu').get_data(as_text=True))

    def test_save_reload_update_and_preserve_other_resources(self):
        db.session.add(DictZasob(zasob_id=99, zasob_kod='miedz', zasob_nazwa='Miedź', zasob_kategoria='Inne', zasob_jednostka='jednostka'))
        db.session.add_all([RegionZasob(region_id=11, zasob_id=99, zloze_ilosc=777),
                            RegionZasob(region_id=21, zasob_id=1, zloze_ilosc=888)])
        db.session.commit()
        self.assertEqual(self.client.post(self.path, data=self.form(amount='123', technology='80')).status_code, 303)
        self.assertEqual(self.count(RegionZasob), len(RESOURCES)*2+2)
        settings = db.session.get(CountryMiningSettings, 1)
        self.assertEqual((settings.technology, settings.version), (80, 1))
        html = self.client.get(self.path).get_data(as_text=True)
        self.assertIn('value="123"', html)
        self.assertIn('Obcy region', html)  # Mapa i lista obejmują teraz cały świat.
        self.assertEqual(self.client.post(self.path, data=self.form(amount='999', technology='80')).status_code, 303)
        db.session.refresh(settings)
        self.assertEqual(settings.version, 2)
        rows = db.session.execute(select(RegionZasob.region_id, RegionZasob.zasob_id, RegionZasob.zloze_ilosc)).all()
        self.assertIn((11, 99, 777), rows)
        self.assertIn((21, 1, 888), rows)
        self.assertEqual(self.count(RegionZasob), len(RESOURCES)*2+2)

    def test_invalid_quantities_are_atomic_and_preserved(self):
        for value in ['-1', '1.5', '1e3', '', 'abc', str(MAX_QUANTITY + 1), '١٢']:
            with self.subTest(value=value):
                data = self.form(amount='25')
                data[field_name(12, 'cemium')] = value
                response = self.client.post(self.path, data=data)
                self.assertEqual(response.status_code, 400)
                self.assertIn('value="25"', response.get_data(as_text=True))
                self.assertEqual(self.count(RegionZasob), 0)
                self.assertEqual(self.count(CountryMiningSettings), 0)
        self.assertEqual(self.client.post(self.path, data=self.form(amount=str(MAX_QUANTITY), technology='0')).status_code, 303)
        self.assertEqual(db.session.scalar(select(RegionZasob.zloze_ilosc).limit(1)), MAX_QUANTITY)
        self.assertIn(str(MAX_QUANTITY), self.client.get(self.path).get_data(as_text=True))

    def test_technology_range(self):
        for value in ['-1', '101', '0.5', '', '1e2']:
            self.assertEqual(self.client.post(self.path, data=self.form(technology=value)).status_code, 400)
        for value in ['0', '100']:
            self.assertEqual(self.client.post(self.path, data=self.form(technology=value)).status_code, 303)
            self.assertEqual(db.session.get(CountryMiningSettings, 1).technology, int(value))

    def test_country_region_tampering_incomplete_and_duplicate_fields(self):
        valid = self.form()
        cases = []
        foreign = dict(valid, quantity_21_zloto='1')
        cases.append(foreign)
        missing = dict(valid)
        del missing[field_name(11, 'zloto')]
        cases.append(missing)
        cases.append(dict(valid, quantity_11_unknown='1'))
        cases.append(dict(valid, country_id='2'))
        duplicate = MultiDict(valid)
        duplicate.add(field_name(11, 'zloto'), '2')
        cases.append(duplicate)
        for data in cases:
            self.assertEqual(self.client.post(self.path, data=data).status_code, 400)
            self.assertEqual(self.count(RegionZasob), 0)

    def test_csrf_and_concurrent_editor_version(self):
        data = self.form(amount='5')
        for token in ['', 'wrong']:
            self.assertEqual(self.client.post(self.path, data=dict(data, csrf_token=token)).status_code, 400)
        self.assertEqual(self.client.post(self.path, data=data).status_code, 303)
        stale = dict(data)
        stale[field_name(11, 'zloto')] = '678'
        response = self.client.post(self.path, data=stale)
        self.assertEqual(response.status_code, 409)
        self.assertIn('value="678"', response.get_data(as_text=True))
        self.assertEqual(db.session.scalar(select(RegionZasob.zloze_ilosc).where(RegionZasob.region_id == 11, RegionZasob.zasob_id == 3)), 5)

    def test_rollback_when_commit_fails(self):
        self.client.post(self.path, data=self.form(amount='10', technology='20'))
        with patch.object(db.session, 'commit', side_effect=SQLAlchemyError('test failure')):
            response = self.client.post(self.path, data=self.form(amount='99', technology='88'))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(db.session.get(CountryMiningSettings, 1).technology, 20)
        self.assertEqual(db.session.scalar(select(RegionZasob.zloze_ilosc).limit(1)), 10)
        self.assertIn('value="99"', response.get_data(as_text=True))

    def test_country_search_empty_country_and_missing_dictionary(self):
        response = self.client.get('/admin/surowce-naturalne?q=Test')
        self.assertIn('Testlandia', response.get_data(as_text=True))
        self.assertNotIn('Inny kraj', response.get_data(as_text=True))
        response = self.client.get('/admin/surowce-naturalne?q=%25')
        self.assertIn('Brak państw', response.get_data(as_text=True))
        self.assertEqual(self.client.get('/admin/surowce-naturalne?country_id=999').status_code, 404)
        self.assertEqual(self.client.post('/admin/surowce-naturalne?country_id=3', data=self.form(country_id=3, technology='77')).status_code, 303)
        self.assertEqual(db.session.get(CountryMiningSettings, 3).technology, 77)
        db.session.delete(db.session.get(DictZasob, 1))
        db.session.commit()
        self.assertEqual(self.client.get(self.path).status_code, 409)
        self.assertEqual(self.client.post(self.path, data=self.form()).status_code, 409)
        self.assertEqual(self.count(DictZasob), len(RESOURCES)-1)

    def test_legacy_dictionary_code_is_preserved(self):
        row = db.session.get(DictZasob, 1)
        row.zasob_kod = 'legacy_coal'
        db.session.commit()
        self.assertEqual(self.client.post(self.path, data=self.form(amount='321')).status_code, 303)
        self.assertEqual(db.session.get(DictZasob, 1).zasob_kod, 'legacy_coal')
        self.assertEqual(self.count(DictZasob), len(RESOURCES))

    def bulk_form(self, action, **extra):
        return dict({key: value for key, value in self.form().items() if not key.startswith('quantity_')}, action=action, **extra)

    def test_increase_every_percentage_country_and_region(self):
        for percentage in (25, 50, 75, 100, 200, 300, 500, 1000):
            self.client.post(self.path, data=self.form(amount='100', technology='37'))
            data = self.bulk_form('increase', scope='region', region_id='11', percentage=str(percentage))
            self.assertEqual(self.client.post(self.path, data=data).status_code, 303)
            for region_id, expected in [(11, 100 + percentage), (12, 100)]:
                amounts = db.session.scalars(select(RegionZasob.zloze_ilosc).where(RegionZasob.region_id == region_id)).all()
                self.assertEqual(amounts, [expected] * len(RESOURCES))
            self.assertEqual(db.session.get(CountryMiningSettings, 1).technology, 37)
        data = self.bulk_form('increase', scope='country', percentage='100')
        self.assertEqual(self.client.post(self.path, data=data).status_code, 303)
        self.assertEqual(db.session.scalar(select(RegionZasob.zloze_ilosc).where(RegionZasob.region_id == 12)), 200)
        self.assertEqual(self.client.post(self.path, data=data).status_code, 409)

    def test_increase_rounding_zero_overflow_and_invalid_scope(self):
        self.client.post(self.path, data=self.form(amount='2'))
        data = self.bulk_form('increase', scope='country', percentage='25')
        self.assertEqual(self.client.post(self.path, data=data).status_code, 303)
        self.assertEqual(db.session.scalar(select(RegionZasob.zloze_ilosc).limit(1)), 3)
        for extra in ({'scope': 'other', 'percentage': '25'}, {'scope': 'country', 'percentage': '26'},
                      {'scope': 'region', 'region_id': '21', 'percentage': '50'}):
            self.assertEqual(self.client.post(self.path, data=self.bulk_form('increase', **extra)).status_code, 400)
        row = db.session.scalar(select(RegionZasob).where(RegionZasob.region_id == 12, RegionZasob.zasob_id == 10))
        row.zloze_ilosc = MAX_QUANTITY
        db.session.commit()
        self.assertEqual(self.client.post(self.path, data=self.bulk_form('increase', scope='country', percentage='100')).status_code, 400)
        self.assertEqual(db.session.scalar(select(RegionZasob.zloze_ilosc).where(RegionZasob.region_id == 11).limit(1)), 3)
        self.client.post(self.path, data=self.form(amount='0'))
        self.assertEqual(self.client.post(self.path, data=self.bulk_form('increase', scope='country', percentage='1000')).status_code, 303)
        self.assertEqual(db.session.scalar(select(func.sum(RegionZasob.zloze_ilosc))), 0)

    def distribution_form(self, minimum='101', maximum='101'):
        data = self.bulk_form('distribute')
        for code, _ in RESOURCES:
            data[f'minimum_{code}'] = minimum
            data[f'maximum_{code}'] = maximum
        return data

    def test_distribution_preserves_country_totals_and_other_country(self):
        db.session.add(RegionZasob(region_id=21, zasob_id=1, zloze_ilosc=777))
        db.session.commit()
        self.client.post(self.path, data=self.form(amount='500', technology='68'))
        data = self.distribution_form()
        with patch('services.natural_resources.secrets.randbelow', side_effect=lambda size: size - 1):
            self.assertEqual(self.client.post(self.path, data=data).status_code, 303)
        for resource_id in range(1, 11):
            amounts = db.session.scalars(select(RegionZasob.zloze_ilosc).where(RegionZasob.region_id.in_([11, 12]), RegionZasob.zasob_id == resource_id)).all()
            self.assertEqual(sorted(amounts), [0, 101])
        self.assertEqual(db.session.get(CountryMiningSettings, 1).technology, 68)
        self.assertEqual(db.session.scalar(select(RegionZasob.zloze_ilosc).where(RegionZasob.region_id == 21)), 777)
        self.assertEqual(self.client.post(self.path, data=data).status_code, 409)

    def test_distribution_ranges_validation_and_integer_limits(self):
        data = self.distribution_form(minimum='10', maximum='20')
        with patch('services.natural_resources.secrets.randbelow', return_value=0):
            self.assertEqual(self.client.post(self.path, data=data).status_code, 303)
        self.assertEqual(db.session.scalar(select(func.sum(RegionZasob.zloze_ilosc))), 100)
        for minimum, maximum in [('21', '20'), ('-1', '20'), ('1.5', '20'), ('0', str(MAX_QUANTITY + 1))]:
            self.assertEqual(self.client.post(self.path, data=self.distribution_form(minimum, maximum)).status_code, 400)
        invalid = self.distribution_form()
        del invalid['maximum_uran']
        self.assertEqual(self.client.post(self.path, data=invalid).status_code, 400)
        self.assertEqual(db.session.scalar(select(func.sum(RegionZasob.zloze_ilosc))), 100)
        self.assertEqual(self.client.post(self.path, data=self.distribution_form('0', '0')).status_code, 303)
        self.assertEqual(db.session.scalar(select(func.sum(RegionZasob.zloze_ilosc))), 0)
        with patch('services.natural_resources.secrets.randbelow', return_value=0):
            self.assertEqual(self.client.post(self.path, data=self.distribution_form(str(MAX_QUANTITY), str(MAX_QUANTITY))).status_code, 303)
        for resource_id in range(1, 11):
            self.assertEqual(db.session.scalar(select(func.sum(RegionZasob.zloze_ilosc)).where(RegionZasob.zasob_id == resource_id)), MAX_QUANTITY)

    def test_new_actions_permissions_csrf_empty_country_and_rollback(self):
        for action in ('increase', 'distribute'):
            data = self.bulk_form(action, scope='country', percentage='25') if action == 'increase' else self.distribution_form()
            self.assertEqual(self.client.post(self.path, data=dict(data, csrf_token='wrong')).status_code, 400)
            with patch.object(db.session, 'commit', side_effect=SQLAlchemyError('test')):
                self.assertEqual(self.client.post(self.path, data=data).status_code, 503)
            self.assertEqual(self.count(RegionZasob), 0)
            self.assertEqual(self.client.post('/admin/surowce-naturalne?country_id=3', data=dict(data, country_id='3')).status_code, 400)
        self.role('tworzyciel')
        self.assertEqual(self.client.post(self.path, data=data).status_code, 403)

    def test_single_region_distribution_and_form_controls(self):
        db.session.get(Region, 12).panstwo_id = 2
        db.session.commit()
        data = self.distribution_form('100', '200')
        with patch('services.natural_resources.secrets.randbelow', side_effect=lambda size: size - 1):
            self.assertEqual(self.client.post(self.path, data=data).status_code, 303)
        self.assertEqual(db.session.scalars(select(RegionZasob.zloze_ilosc)).all(), [200] * len(RESOURCES))
        html = self.client.get(self.path).get_data(as_text=True)
        for code, _ in RESOURCES:
            self.assertIn(f'name="minimum_{code}"', html)
            self.assertIn(f'name="maximum_{code}"', html)
        response = self.client.post(self.path, data=self.distribution_form('100', '99'))
        self.assertEqual(response.status_code, 400)
        self.assertIn('name="minimum_uran" value="100"', response.get_data(as_text=True))
