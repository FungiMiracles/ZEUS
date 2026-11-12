"""Wiki area ranking and calibrated map use the same stored data as the game."""
import unittest
from pathlib import Path
from datetime import datetime, date
from flask import Flask
from jinja2 import ChoiceLoader, DictLoader
from extensions import db
from models import Panstwo, Region, Miasto, RocznyPrzyrostStateHistory, PKBStateHistory, HistoriaPopulacjiPanstw, RegionStateHistory
from game.military_models import MapCalibration
from game.population_structure import PopulationStructure, save_structure
from routes_wykresy import init_wykresy_routes
from routes_mapy import init_mapy_routes


class WikiAreaTests(unittest.TestCase):
    def test_current_world_metrics_weighting_nulls_deleted_and_stored_events(self):
        from decimal import Decimal
        from models import Zdarzenie
        from services.wiki_world_stats import world_current_metrics
        Zdarzenie.__table__.create(db.engine)
        for country, population, gdp in [(1, 100, 1000), (2, 300, 3000), (4, 999, 999999)]:
            db.session.query(Panstwo).filter(Panstwo.PANSTWO_ID == country).update(
                {'panstwo_populacja': population, 'panstwo_PKB': gdp})
        db.session.query(Panstwo).filter(Panstwo.PANSTWO_ID == 4).update({'status': 'usunięte'})
        db.session.add_all([
            Region(region_id=1, region_nazwa="Test 1", panstwo_id=1, region_ludnosc_pozamiejska=40,
                roczny_przyrost_wies_pct=2, roczny_przyrost_miasto_pct=-1,
                region_stan_infra_drogowej=80, region_stan_infra_kolejowej=0,
                region_stan_infra_mieszkalnej=40, region_stan_infra_portowej=100, region_polozenie_id=1),
            Region(region_id=2, region_nazwa="Test 2", panstwo_id=2, region_ludnosc_pozamiejska=300,
                roczny_przyrost_wies_pct=1, region_stan_infra_drogowej=20,
                region_stan_infra_portowej=60, region_polozenie_id=2),
            Region(region_id=4, region_nazwa="Test 4", panstwo_id=4, region_ludnosc_pozamiejska=999,
                roczny_przyrost_wies_pct=100, region_stan_infra_drogowej=100),
            Miasto(miasto_id=1, panstwo_id=1, region_id=1, miasto_populacja=60),
            Miasto(miasto_id=4, panstwo_id=4, region_id=4, miasto_populacja=999),
        ])
        for id, status in enumerate(['aktywne', 'zakonczone', 'archiwalne'], 1):
            db.session.add(Zdarzenie(zdarzenie_id=id, zdarzenie_typ='test', status=status))
        db.session.commit()
        self.assertEqual(world_current_metrics(db.session), dict(gdp_per_capita=10,
            infrastructure=40, urbanization=15, population_growth=Decimal('.8'), events=3))
        db.session.query(Panstwo).filter(Panstwo.PANSTWO_ID == 1).update({'panstwo_PKB': 3000})
        db.session.query(Zdarzenie).filter(Zdarzenie.zdarzenie_id == 3).delete()
        db.session.commit()
        result = world_current_metrics(db.session)
        self.assertEqual(result['gdp_per_capita'], 15)
        self.assertEqual(result['events'], 2)

    def test_current_world_metrics_missing_data_is_not_zero(self):
        from models import Zdarzenie
        from services.wiki_world_stats import world_current_metrics
        Zdarzenie.__table__.create(db.engine)
        self.assertEqual(world_current_metrics(db.session), dict(gdp_per_capita=None,
            infrastructure=None, urbanization=None, population_growth=None, events=0))

    def test_gdp_growth_chart_latest_negative_zero_gaps_and_world_weights(self):
        from models import ProcentWzrostuStateHistory
        ProcentWzrostuStateHistory.__table__.create(db.engine)
        for id, country, when, value in [(1, 1, date(3000, 1, 1), 4),
                (2, 1, date(3000, 12, 1), -2), (3, 1, date(3001, 1, 1), 0),
                (4, 2, date(3000, 12, 1), 2), (5, 4, date(3000, 12, 1), -100)]:
            db.session.add(ProcentWzrostuStateHistory(id=id, panstwo_id=country,
                data_entenda=when, source='GLOBAL_CRISIS', new_wzrost=value))
        for id, country, value in [(1, 1, 100), (2, 2, 300), (3, 4, 1000)]:
            db.session.add(PKBStateHistory(id=id, panstwo_id=country, data_entenda=date(3000, 12, 31), source='test', new_pkb=value))
        db.session.query(Panstwo).filter(Panstwo.PANSTWO_ID == 4).update({'status': 'usunięte'})
        db.session.commit()
        data = self.client.get('/api/wykresy/chart?typ=wzrost_pkb&panstwo_id=1').get_json()
        values = dict(zip(data['labels'], data['values']))
        self.assertEqual(data['unit'], 'gdp_growth_pct')
        self.assertEqual(values[3000], -2)
        self.assertEqual(values[3001], 0)
        self.assertIsNone(values[2999])
        world = self.client.get('/api/wykresy/chart?typ=wzrost_pkb&scope=world').get_json()
        values = dict(zip(world['labels'], world['values']))
        self.assertEqual(values[3000], 1)
        self.assertIsNone(values[3001])
        self.assertEqual(self.client.get('/api/wykresy/chart?typ=wzrost_pkb&panstwo_id=4').status_code, 404)

    def test_world_roads_requires_wiki_and_returns_only_active_geometry(self):
        from game.civic_models import Road
        Road.__table__.create(db.engine)
        curved = [[10, -20], [15, -23], [30, -25]]
        for id, country_id, kind, path in [(1, 1, 'motorway', curved), (2, 2, 'national', None)]:
            db.session.add(Road(id=id, panstwo_id=country_id, kind=kind,
                start_x=10, start_y=-20, end_x=30, end_y=-25, path=path,
                distance_km=50, cost=100, request_id=str(id)))
        db.session.commit()
        self.assertEqual(self.client.get('/wiki/mapa/drogi.geojson').status_code, 403)
        with self.client.session_transaction() as browser:
            browser['game_user_id'] = 1
        self.assertEqual(self.client.get('/wiki/mapa/drogi.geojson').status_code, 403)
        with self.client.session_transaction() as browser:
            browser['rola'] = 'czytelnik'
        response = self.client.get('/wiki/mapa/drogi.geojson')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Cache-Control'], 'private, no-store')
        features = response.get_json()['features']
        self.assertEqual(features[0]['geometry']['coordinates'], curved)
        self.assertEqual(features[1]['geometry']['coordinates'], [[10, -20], [30, -25]])
        self.assertEqual(features[0]['properties']['kind'], 'motorway')
        self.assertNotIn('cost', features[0]['properties'])
        db.session.query(Panstwo).filter(Panstwo.PANSTWO_ID == 2).update({'status': 'usunięte'})
        db.session.commit()
        self.assertEqual([f['properties']['id'] for f in self.client.get('/wiki/mapa/drogi.geojson').get_json()['features']], [1])

    def test_world_map_shows_road_toggle_for_wiki_readers(self):
        self.assertNotIn('id="toggleRoads"', self.client.get('/mapy_swiata').get_data(as_text=True))
        with self.client.session_transaction() as browser:
            browser['rola'] = 'czytelnik'
        html = self.client.get('/mapy_swiata').get_data(as_text=True)
        self.assertIn('id="toggleRoads"', html)
        self.assertIn('/wiki/mapa/drogi.geojson', html)
        self.assertIn('js/world_roads.js', html)

    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        self.app = Flask(__name__, template_folder=str(root / 'templates'))
        self.app.config.update(TESTING=True, SECRET_KEY='wiki-tests-only', SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        self.app.jinja_loader = ChoiceLoader([
            DictLoader({'base_layout.html': '{% block content %}{% endblock %}'}),
            self.app.jinja_loader,
        ])
        db.init_app(self.app)
        init_wykresy_routes(self.app)
        init_mapy_routes(self.app)
        from routes_region_secession import region_sovereignty_bp
        self.app.register_blueprint(region_sovereignty_bp)
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.metadata.create_all(db.engine, tables=[Panstwo.__table__, Region.__table__, MapCalibration.__table__, RocznyPrzyrostStateHistory.__table__, PopulationStructure.__table__, PKBStateHistory.__table__, Miasto.__table__, HistoriaPopulacjiPanstw.__table__, RegionStateHistory.__table__])
        for id, area, sovereign in [(1, 100, 'TAK'), (2, 300, 'TAK'), (3, None, 'TAK'), (4, 500, 'NIE')]:
            db.session.add(Panstwo(PANSTWO_ID=id, panstwo_nazwa=f'Country {id}', panstwo_powierzchnia=area, czy_suwerenny=sovereign))
        db.session.add(MapCalibration(id=1, reference_city_a=1, reference_city_b=852,
            reference_km=100, km_per_unit=3.910919870403471,
            reference_a_x=954.7510623012616, reference_a_y=-1801.62366708549,
            reference_b_x=952.4987942837062, reference_b_y=-1776.1536230000308))
        db.session.commit()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_area_ranking_both_orders_missing_last_and_sovereign_filter(self):
        for order, expected in [('DESC', [2, 1, 3]), ('ASC', [1, 2, 3])]:
            data = self.client.get(f'/api/wykresy/ranking?typ=powierzchnia&sort={order}').get_json()
            self.assertTrue(data['success'])
            self.assertEqual([r['id'] for r in data['ranking']], expected)
            self.assertEqual([r['lp'] for r in data['ranking']], [1, 2, 3])
            self.assertIsNone(data['ranking'][-1]['wartosc'])

    def test_world_map_renders_database_calibration_and_metric_scale(self):
        response = self.client.get('/mapy_swiata')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('const kmPerUnit = 3.910919870403471;', html)
        self.assertIn('mapDistance(a, b) * kmPerUnit * 1000', html)
        self.assertIn('L.control.scale({imperial: false, metric: true})', html)

    def test_region_area_persists_and_templates_compile(self):
        db.session.add(Region(region_id=1, panstwo_id=1, region_nazwa='Region', region_powierzchnia=12345))
        db.session.commit()
        db.session.expire_all()
        self.assertEqual(db.session.get(Region, 1).region_powierzchnia, 12345)
        for name in ['region_form.html', 'wykresy.html']:
            self.app.jinja_env.get_template(name)

    def test_annual_growth_uses_latest_record_and_preserves_negative_zero_and_gaps(self):
        for country, year, month, value in [
            (1, 2995, 1, 1.2), (1, 2995, 12, -0.75),
            (1, 2997, 12, 0.0), (1, 3036, 12, 0.25), (2, 2996, 12, 9.0),
        ]:
            db.session.add(RocznyPrzyrostStateHistory(
                panstwo_id=country, data_entenda=datetime(year, month, 1),
                data_rzeczywista=datetime(2026, 10, 26), new_roczny_przyrost=value,
            ))
        db.session.commit()
        data = self.client.get('/api/wykresy/chart?typ=przyrost_ludnosci&panstwo_id=1').get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['unit'], 'population_growth_pct')
        values = dict(zip(data['labels'], data['values']))
        self.assertEqual(values[2995], -0.75)
        self.assertIsNone(values[2996])
        self.assertEqual(values[2997], 0.0)
        self.assertEqual(values[3036], 0.25)
        empty = self.client.get('/api/wykresy/chart?typ=przyrost_ludnosci&panstwo_id=3').get_json()
        self.assertTrue(all(value is None for value in empty['values']))

    def test_wiki_population_map_has_country_boundaries_and_saved_country_ids(self):
        from routes_civic_admin import wiki_civic_bp
        from unittest.mock import patch
        self.app.register_blueprint(wiki_civic_bp)
        save_structure(db.session,1,{'children':20,'working':60,'seniors':20,'version':0},'Admin')
        db.session.commit()
        with self.client.session_transaction() as browser:
            browser['rola']='wszechmocny'
        with patch('routes_civic_admin.render_template',return_value='ok') as render:
            response=self.client.get('/admin/struktura-ludnosci')
        self.assertEqual(response.status_code,200)
        config=render.call_args.kwargs['population_config']
        self.assertEqual(config['countriesUrl'], '/wiki/mapa/panstwa.geojson')
        self.assertIn(1,config['structuredCountries'])
        self.assertNotIn('regionOwners',config)
        self.app.jinja_env.get_template('admin_population_structure.html')


    def test_world_structure_is_population_weighted_and_reports_missing_coverage(self):
        from services.wiki_world_stats import world_population_structure
        db.session.query(Panstwo).filter(Panstwo.PANSTWO_ID == 1).update({'panstwo_populacja': 100})
        db.session.query(Panstwo).filter(Panstwo.PANSTWO_ID == 2).update({'panstwo_populacja': 300})
        db.session.query(Panstwo).filter(Panstwo.PANSTWO_ID == 3).update({'panstwo_populacja': 100})
        for id, shares in [(1, (20, 60, 20)), (2, (40, 50, 10))]:
            db.session.add(PopulationStructure(panstwo_id=id, children=shares[0], working=shares[1], seniors=shares[2], actor='Test'))
        db.session.commit()
        data = world_population_structure(db.session)
        self.assertEqual([r['percent'] for r in data['groups']], [35, 52.5, 12.5])
        self.assertEqual(sum(r['percent'] for r in data['groups']), 100)
        self.assertEqual(data['coveragePercent'], 80)
        self.assertEqual(data['coveredPopulation'], '400')

    def test_world_gdp_compares_last_previous_year_values_and_handles_no_change(self):
        from services.wiki_world_stats import world_gdp
        for id, gdp in [(1, 200), (2, 400)]:
            db.session.query(Panstwo).filter(Panstwo.PANSTWO_ID == id).update({'panstwo_PKB': gdp})
        for id, country, when, gdp in [
            (1, 1, date(2999, 1, 1), 90), (2, 1, date(2999, 12, 30), 100),
            (3, 2, date(2999, 12, 30), 300), (4, 1, date(3000, 1, 1), 200),
        ]:
            db.session.add(PKBStateHistory(id=id, panstwo_id=country, data_entenda=when, source='test', new_pkb=gdp))
        db.session.commit()
        self.assertEqual(world_gdp(db.session, 3000), {'total': 600, 'previous': 400, 'trend': 'up', 'previousYear': 2999})
        db.session.query(Panstwo).filter(Panstwo.PANSTWO_ID == 2).update({'panstwo_PKB': 100})
        self.assertEqual(world_gdp(db.session, 3000)['trend'], 'down')
        db.session.query(Panstwo).filter(Panstwo.PANSTWO_ID == 2).update({'panstwo_PKB': 200})
        self.assertEqual(world_gdp(db.session, 3000)['trend'], 'flat')
        self.assertIsNone(world_gdp(db.session, 3002)['trend'])

    def test_wiki_road_builder_renders_city_populations_and_capitals(self):
        import json, re
        from routes_civic_admin import wiki_civic_bp
        self.app.register_blueprint(wiki_civic_bp)
        db.session.add(Region(region_id=1, panstwo_id=1, region_nazwa='Region'))
        db.session.add_all([
            Miasto(miasto_id=1, panstwo_id=1, region_id=1, miasto_nazwa='Capital', miasto_populacja=6000000, miasto_typ_id=1, czy_na_mapie='TAK'),
            Miasto(miasto_id=2, panstwo_id=1, region_id=1, miasto_nazwa='Town', miasto_populacja=5000, miasto_typ_id=2, czy_na_mapie='TAK'),
            Miasto(miasto_id=3, panstwo_id=1, region_id=1, miasto_nazwa='Hidden', czy_na_mapie='NIE'),
        ])
        db.session.commit()
        with self.client.session_transaction() as browser:
            browser['rola']='wszechmocny'
        response=self.client.get('/admin/drogi')
        self.assertEqual(response.status_code,200)
        html=response.get_data(as_text=True)
        config=json.loads(re.search(r'<script id="road-config" type="application/json">(.*?)</script>',html,re.S).group(1))
        self.assertEqual(config['cities']['1']['population'],6000000)
        self.assertTrue(config['cities']['1']['capital'])
        self.assertFalse(config['cities']['2']['capital'])
        self.assertNotIn('3',config['cities'])
        self.assertIn('wiki_roads.css',html)
        self.assertIn('road-city-legend',html)

    def test_game_changes_requires_player_and_renders_document_and_logo_link(self):
        from unittest.mock import patch
        from game.public_panels import public_panels_bp
        self.app.register_blueprint(public_panels_bp)
        self.app.add_template_filter(str,'spacenum')
        self.app.add_template_filter(str,'game_money')
        for endpoint in ['wejscie','game_demography.page','game_diplomacy.page','game_environment.page',
                         'game_forum.page','game_forum.notifications','game_forum.read_notifications',
                         'game_messages.index','game_messages.addressees']:
            self.app.add_url_rule('/test/'+endpoint,endpoint,lambda:'')
        with patch('game.public_panels.player',return_value=(None,None)):
            self.assertEqual(self.client.get('/game/informacje-o-zmianach').status_code,302)
        ctx={'game_user':None,'game_country':None,'game_home_url':'/game',
             'game_logout_url':'/logout','game_active_page':'changes'}
        with patch('game.public_panels.player',return_value=(object(),object())),patch('game.public_panels.context',return_value=ctx):
            response=self.client.get('/game/informacje-o-zmianach')
        self.assertEqual(response.status_code,200)
        html=response.get_data(as_text=True)
        self.assertIn('GAME-1026001',html)
        self.assertIn('GAME-1026024',html)
        self.assertNotIn('game-logo-stack',html)
        self.assertNotIn('class="game-changes-link"',html)
        self.assertNotIn('aria-current="page">Informacje o zmianach',html)

    def test_world_gdp_shows_latest_annual_direction_before_next_recalculation(self):
        from services.wiki_world_stats import world_gdp
        for id, before, after in [(1,100,120),(2,200,230)]:
            db.session.query(Panstwo).filter(Panstwo.PANSTWO_ID==id).update({'panstwo_PKB':after})
            db.session.add(PKBStateHistory(id=id,panstwo_id=id,data_entenda=date(2999,12,30),
                source='PKB_REGEN',old_pkb=before,new_pkb=after))
        db.session.commit()
        result=world_gdp(db.session,3000)
        self.assertEqual(result['total'],350)
        self.assertEqual(result['trend'],'up')
        self.assertEqual(result['comparisonYear'],2999)
        self.assertEqual(result['previousYear'],2998)
        db.session.query(PKBStateHistory).update({'old_pkb':300})
        self.assertEqual(world_gdp(db.session,3000)['trend'],'down')

    def test_chart_country_filter_can_list_the_world_or_one_continent(self):
        db.session.query(Panstwo).filter(Panstwo.PANSTWO_ID == 1).update({'kontynent_id': 1})
        db.session.query(Panstwo).filter(Panstwo.PANSTWO_ID == 2).update({'kontynent_id': 2})
        db.session.commit()
        world=self.client.get('/api/wykresy/panstwa?kontynent_id=all').get_json()
        self.assertEqual([row['id'] for row in world['panstwa']],[1,2,3])
        continent=self.client.get('/api/wykresy/panstwa?kontynent_id=1').get_json()
        self.assertEqual([row['id'] for row in continent['panstwa']],[1])
        for scope in ['', 'bad', '0', '-1']:
            self.assertEqual(self.client.get('/api/wykresy/panstwa?kontynent_id='+scope).status_code,400)

    def test_world_charts_aggregate_history_and_do_not_require_a_country(self):
        for id, population, gdp, growth in [(1,100,1000,2.0),(2,300,1500,-2.0)]:
            db.session.add(HistoriaPopulacjiPanstw(id=id,panstwo_id=id,data_entenda=date(2999,12,31),panstwo_populacja=population))
            db.session.add(PKBStateHistory(id=id,panstwo_id=id,data_entenda=date(2999,12,30),source='test',new_pkb=gdp))
            db.session.add(RocznyPrzyrostStateHistory(id=id,panstwo_id=id,data_entenda=datetime(2999,12,27),data_rzeczywista=datetime(2026,10,26),new_roczny_przyrost=growth))
        db.session.add(Region(region_id=1,panstwo_id=1,region_nazwa='Region'))
        db.session.add(RegionStateHistory(id=1,region_id=1,source='test',data_entenda=datetime(2999,12,31),data_rzeczywista=datetime(2026,10,26),old_kolej=20,old_drogi=40,old_energia=60,old_mieszkania=80,old_porty=100))
        db.session.commit()
        for kind, expected in [('populacja',400),('pkb',2500),('pkbpc',6.25),('przyrost_ludnosci',-1.0),('infrastruktura',50.0)]:
            response=self.client.get('/api/wykresy/chart?scope=world&typ='+kind)
            self.assertEqual(response.status_code,200)
            data=response.get_json()
            values=dict(zip(data['labels'],data['values']))
            self.assertEqual(values[2999],expected)
            self.assertIsNone(values[2998])
        self.assertEqual(self.client.get('/api/wykresy/chart?scope=world&typ=invalid').status_code,400)
        self.assertEqual(self.client.get('/api/wykresy/chart?typ=populacja').status_code,400)
