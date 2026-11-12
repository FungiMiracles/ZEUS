"""Isolated region secession tests: no real UAT/production ownership changes."""
import tempfile, unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
from flask import Flask
from sqlalchemy import select, event
from extensions import db
from models import Panstwo, Region, Miasto, DictKontynent, DictMiastoTyp
from services.region_secession import RegionSecession, SecessionError, secede, rejoin
from routes_region_secession import region_sovereignty_bp, form_context


class RegionSecessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        static = Path(self.tmp.name)
        (static/'flags').mkdir(); (static/'maps').mkdir()
        (static/'flags/Parent.jpg').write_bytes(b'original-flag')
        self.app = Flask(__name__, static_folder=str(static))
        self.app.config.update(TESTING=True, SECRET_KEY='isolated-secession-tests', SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        db.init_app(self.app)
        self.app.register_blueprint(region_sovereignty_bp)
        self.app.add_url_rule('/region/<int:region_id>', 'region_form', lambda region_id: 'region')
        self.ctx = self.app.app_context(); self.ctx.push()
        @event.listens_for(db.engine, "connect")
        def sqlite_collations(connection, record):
            connection.create_function("CHAR_LENGTH", 1, len)
            connection.create_collation("ascii_bin", lambda a, b: (a > b) - (a < b))
        db.create_all()
        db.session.add(DictKontynent(kontynent_id=1, kontynent_nazwa='Kao'))
        db.session.add_all([DictMiastoTyp(miasto_typ_id=i, miasto_typ_nazwa=str(i)) for i in [1,2,3]])
        db.session.add_all([
            Panstwo(PANSTWO_ID=1, panstwo_nazwa='Parent', panstwo_populacja=1320, panstwo_powierzchnia=300, panstwo_PKB=100000, kontynent_id=1, czy_suwerenny='TAK'),
            Panstwo(PANSTWO_ID=2, panstwo_nazwa='Target', panstwo_populacja=800, panstwo_powierzchnia=50, kontynent_id=1, czy_suwerenny='TAK'),
            Panstwo(PANSTWO_ID=3, panstwo_nazwa='Dependent', czy_suwerenny='NIE', zwierzch_panstwo_id=2),
            Region(region_id=11, region_nazwa='Island', panstwo_id=1, region_powierzchnia=100, region_ludnosc_pozamiejska=100, region_mapa=b'region-image', region_mapa_mime='image/png'),
            Region(region_id=12, region_nazwa='Mainland', panstwo_id=1, region_powierzchnia=200, region_ludnosc_pozamiejska=500),
            Region(region_id=21, region_nazwa='Target region', panstwo_id=2, region_powierzchnia=50, region_ludnosc_pozamiejska=200),
            Miasto(miasto_id=101, miasto_nazwa='Regional capital', panstwo_id=1, region_id=11, miasto_populacja=200, miasto_typ_id=2),
            Miasto(miasto_id=102, miasto_nazwa='Town', panstwo_id=1, region_id=11, miasto_populacja=20, miasto_typ_id=3),
            Miasto(miasto_id=103, miasto_nazwa='Parent capital', panstwo_id=1, region_id=12, miasto_populacja=500, miasto_typ_id=1),
            Miasto(miasto_id=201, miasto_nazwa='Target capital', panstwo_id=2, region_id=21, miasto_populacja=600, miasto_typ_id=1),
        ])
        db.session.commit()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove(); db.drop_all(); self.ctx.pop(); self.tmp.cleanup()

    def payload(self, **extra):
        return dict(request_id=str(uuid4()), expected_country_id='1', country_name='Free Island', **extra)

    def refresh(self):
        db.session.expire_all()

    def test_secession_preserves_region_moves_cities_promotes_capital_copies_assets_and_totals(self):
        payload = self.payload()
        id = secede(11, payload, 'Tester')
        self.assertNotIn(id, [1,2,3])
        self.refresh()
        self.assertEqual(db.session.get(Region, 11).panstwo_id, id)
        self.assertEqual(db.session.get(Miasto, 101).miasto_typ_id, 1)
        self.assertEqual(db.session.get(Miasto, 102).panstwo_id, id)
        self.assertEqual(db.session.get(Miasto, 103).panstwo_id, 1)
        country = db.session.get(Panstwo, id)
        self.assertEqual((country.panstwo_populacja, country.panstwo_powierzchnia), (320,100))
        self.assertIsNone(country.panstwo_PKB)
        self.assertEqual(db.session.get(Panstwo, 1).panstwo_populacja, 1000)
        self.assertEqual(db.session.get(Panstwo, 1).panstwo_PKB, 100000)
        self.assertEqual((Path(self.tmp.name)/'flags/Free_Island.jpg').read_bytes(), b'original-flag')
        self.assertEqual((Path(self.tmp.name)/'maps/Free_Island.jpg').read_bytes(), b'region-image')
        self.assertEqual(secede(11, payload, 'Tester'), id)
        self.assertEqual(db.session.query(RegionSecession).count(), 1)
        response = self.client.get(f'/wiki/panstwo/{id}/mapa-po-secesji')
        self.assertEqual(response.data, b'region-image')
        self.assertEqual(response.mimetype, 'image/png')

    def test_absent_map_is_null_and_no_capital_is_invented(self):
        db.session.get(Region,11).region_mapa = None
        db.session.get(Miasto,101).miasto_typ_id = 3
        db.session.commit()
        id = secede(11,self.payload(),'Tester')
        record = db.session.query(RegionSecession).filter_by(new_country_id=id).one()
        self.assertIsNone(record.map_snapshot)
        self.assertIsNone(record.capital_city_id)
        self.assertFalse((Path(self.tmp.name)/'maps/Free_Island.jpg').exists())

    def test_rejoin_updates_region_and_cities_without_duplicate_capital_or_deleting_country(self):
        id = secede(11,self.payload(),'Tester')
        request = dict(request_id=str(uuid4()), expected_country_id=str(id), target_country_id='2')
        self.assertEqual(rejoin(11,request,'Tester'),2)
        self.assertEqual(rejoin(11,request,'Tester'),2)
        self.refresh()
        self.assertEqual(db.session.get(Region,11).panstwo_id,2)
        self.assertEqual(db.session.get(Miasto,101).panstwo_id,2)
        self.assertEqual(db.session.get(Miasto,101).miasto_typ_id,2)
        self.assertEqual(db.session.get(Miasto,201).miasto_typ_id,1)
        self.assertEqual(db.session.get(Panstwo,2).panstwo_populacja,1120)
        self.assertEqual(db.session.get(Panstwo,2).panstwo_powierzchnia,150)
        self.assertIsNone(db.session.get(Panstwo,id))
        archived = db.session.scalar(select(Panstwo).where(Panstwo.PANSTWO_ID == id)
            .execution_options(include_deleted_countries=True))
        self.assertEqual(archived.status, 'usunięte')
        self.assertIsNotNone(db.session.query(RegionSecession).one().rejoined_at)

    def test_stale_ownership_invalid_targets_duplicate_names_and_ambiguous_capitals_are_rejected(self):
        for name in ['Parent','../bad','bad/name','']:
            with self.assertRaises(SecessionError):secede(11,{**self.payload(),'country_name':name},'Tester')
        db.session.get(Miasto,102).miasto_typ_id=2;db.session.commit()
        with self.assertRaises(SecessionError):secede(11,self.payload(),'Tester')
        db.session.get(Miasto,102).miasto_typ_id=3;db.session.commit()
        id=secede(11,self.payload(),'Tester')
        with self.assertRaises(SecessionError):secede(11,self.payload(),'Tester')
        for target in [id,3,9999]:
            with self.assertRaises(SecessionError):rejoin(11,dict(request_id=str(uuid4()),expected_country_id=str(id),target_country_id=str(target)),'Tester')
        self.refresh();self.assertEqual(db.session.get(Region,11).panstwo_id,id)

    def test_asset_failure_rolls_back_ownership_and_cleans_up_created_files(self):
        from services.region_secession import _create_asset
        def write(path, data, created):
            if path.parent.name=='maps':raise OSError('simulated disk failure')
            return _create_asset(path,data,created)
        with patch('services.region_secession._create_asset',side_effect=write):
            with self.assertRaises(OSError):secede(11,self.payload(),'Tester')
        self.refresh()
        self.assertEqual(db.session.get(Region,11).panstwo_id,1)
        self.assertEqual(db.session.query(Panstwo).count(),3)
        self.assertEqual(db.session.query(RegionSecession).count(),0)
        self.assertFalse((Path(self.tmp.name)/'flags/Free_Island.jpg').exists())

    def test_routes_require_role_and_csrf_and_context_lists_only_valid_rejoin_targets(self):
        path='/region/11/niepodleglosc'
        self.assertEqual(self.client.post(path,data=self.payload()).status_code,403)
        with self.client.session_transaction() as browser:browser['rola']='wszechmocny'
        self.assertEqual(self.client.post(path,data=self.payload()).status_code,403)
        with self.client.session_transaction() as browser:browser['wiki_secession_csrf']='token'
        response=self.client.post(path,data={**self.payload(),'csrf_token':'token'})
        self.assertEqual(response.status_code,303)
        self.refresh()
        with self.app.test_request_context('/'):
            from flask import session
            session['rola']='wszechmocny'
            ctx=form_context(db.session.get(Region,11))
        self.assertEqual({row[0] for row in ctx['rejoin_countries']},{1,2})
        self.assertIsNotNone(ctx['region_secession'])

    def test_world_map_transfers_only_the_region_geometry_without_rewriting_sources(self):
        from services.region_secession import country_boundaries_data
        from shapely.geometry import shape
        base={'type':'FeatureCollection','features':[{'type':'Feature','properties':{'panstwo_id':1},'geometry':{'type':'Polygon','coordinates':[[[0,0],[10,0],[10,10],[0,10],[0,0]]]}}]}
        regions={'type':'FeatureCollection','features':[{'type':'Feature','properties':{'region_id':11},'geometry':{'type':'Polygon','coordinates':[[[0,0],[5,0],[5,10],[0,10],[0,0]]]}}]}
        result=country_boundaries_data(base,regions,{11:4})
        areas={f['properties']['panstwo_id']:shape(f['geometry']).area for f in result['features']}
        self.assertEqual(areas,{1:50,4:50})
        self.assertEqual(shape(base['features'][0]['geometry']).area,100)
        result=country_boundaries_data(base,regions,{11:1})
        self.assertEqual(shape(result['features'][0]['geometry']).area,100)

    def test_commit_failure_rolls_back_database_and_removes_new_assets(self):
        with patch('sqlalchemy.orm.session.SessionTransaction.commit',side_effect=RuntimeError('simulated commit failure')):
            with self.assertRaises(RuntimeError):secede(11,self.payload(),'Tester')
        self.refresh()
        self.assertEqual(db.session.get(Region,11).panstwo_id,1)
        self.assertEqual(db.session.query(Panstwo).count(),3)
        self.assertEqual(db.session.query(RegionSecession).count(),0)
        self.assertFalse((Path(self.tmp.name)/'flags/Free_Island.jpg').exists())
        self.assertFalse((Path(self.tmp.name)/'maps/Free_Island.jpg').exists())
