"""Administrative preferences are versioned, private to each AI actor and nonbinding."""
import unittest

from sqlalchemy import select

from extensions import db
from models import Panstwo, Stosunki
from game.paga_relationships import (
    PagaRelationship, PagaRelationshipRevision, country_preferences,
)


class RelationshipTests(unittest.TestCase):
    def setUp(self):
        from test_paga import PagaTests
        self.fixture=PagaTests();self.fixture.setUp()
        self.app=self.fixture.app;self.client=self.fixture.client
        for model in (PagaRelationship,PagaRelationshipRevision):model.__table__.create(db.engine)
        db.session.add(Panstwo(PANSTWO_ID=4,panstwo_nazwa='Kraj C',kontynent_id=1))
        db.session.commit();self.fixture.enter();self.headers=self.fixture.headers

    def tearDown(self):self.fixture.tearDown()

    def post(self,status='historical_ally',satellite=None,revision=0,first=1,second=2):
        return self.client.post(f'/admin/paga/powiazania/{first}/{second}',headers=self.headers,
                                json={'status':status,'satelliteId':satellite,'revision':revision})

    def test_admin_entry_csrf_roles_and_feature_guard(self):
        for path in ('/admin/paga/powiazania','/admin/paga/powiazania/panstwa','/admin/paga/powiazania/1/2'):
            self.assertEqual(self.client.get(path).status_code,403)
            self.assertEqual(self.client.get(path,headers={**self.headers,'X-CSRF-Token':'invalid'}).status_code,403)
        with self.client.session_transaction() as session:session['rola']='tworzyciel'
        self.assertEqual(self.post().status_code,403)
        with self.client.session_transaction() as session:session['rola']='wszechmocny'
        self.app.config['PAGA_ENABLED']=False
        self.assertEqual(self.post().status_code,404)

    def test_new_pair_symmetric_read_directional_satellite_and_revision_history(self):
        result=self.client.get('/admin/paga/powiazania/2/1',headers=self.headers)
        self.assertEqual(result.json['relationship']['revision'],0)
        self.assertEqual(self.post('satellite',satellite=2).status_code,200)
        forward=self.client.get('/admin/paga/powiazania/1/2',headers=self.headers).json
        reverse=self.client.get('/admin/paga/powiazania/2/1',headers=self.headers).json
        self.assertEqual(forward,reverse);self.assertEqual(forward['relationship']['satelliteId'],2)
        self.assertEqual(self.post('satellite',satellite=1,revision=1,first=2,second=1).status_code,200)
        self.assertEqual(country_preferences(db.session,1)[0]['role'],'satellite')
        self.assertEqual(country_preferences(db.session,2)[0]['role'],'patron')
        self.assertEqual(db.session.query(PagaRelationship).count(),1)
        history=list(db.session.scalars(select(PagaRelationshipRevision).order_by(PagaRelationshipRevision.revision)))
        self.assertEqual([row.configuration['satelliteId'] for row in history],[2,1])
        self.assertTrue(all(row.actor and row.created_at for row in history))

    def test_stale_writes_and_deletion_keep_version(self):
        self.assertEqual(self.post().status_code,200)
        self.assertEqual(self.post('historical_hostile').status_code,409)
        self.assertEqual(self.post('none',revision=1).status_code,200)
        self.assertEqual(country_preferences(db.session,1),[])
        self.assertEqual(self.client.get('/admin/paga/powiazania',headers=self.headers).json['relationships'],[])
        self.assertEqual(self.post().status_code,409)
        self.assertEqual(self.post('historical_hostile',revision=2).status_code,200)
        self.assertEqual(db.session.query(PagaRelationshipRevision).count(),3)

    def test_invalid_pairs_and_payloads_do_not_create_records(self):
        for first,second in ((1,1),(1,3),(1,999999),(1,2147483648)):
            self.assertEqual(self.post(first=first,second=second).status_code,400)
        invalid=[{'status':[],'satelliteId':None,'revision':0},
                 {'status':'unknown','satelliteId':None,'revision':0},
                 {'status':'satellite','satelliteId':None,'revision':0},
                 {'status':'satellite','satelliteId':4,'revision':0},
                 {'status':'satellite','satelliteId':True,'revision':0},
                 {'status':'historical_ally','satelliteId':1,'revision':0},
                 {'status':'historical_ally','satelliteId':None,'revision':True},
                 {'status':'historical_hostile','revision':0},None]
        for data in invalid:
            self.assertEqual(self.client.post('/admin/paga/powiazania/1/2',json=data,headers=self.headers).status_code,400)
        self.assertEqual(db.session.query(PagaRelationship).count(),0)
        self.assertEqual(db.session.query(PagaRelationshipRevision).count(),0)

    def test_choices_active_countries_and_admin_list(self):
        countries=self.client.get('/admin/paga/powiazania/panstwa',headers=self.headers).json['countries']
        self.assertEqual({row['id'] for row in countries},{1,2,4})
        self.post('historical_ally');self.post('satellite',satellite=4,first=1,second=4)
        items=self.client.get('/admin/paga/powiazania',headers=self.headers).json['relationships']
        self.assertEqual(len(items),2);self.assertEqual(items[0]['first']['name'],'Kraj A')
        self.assertEqual(items[1]['satelliteId'],4)

    def test_own_preferences_only_and_no_overwrite_of_actual_relations(self):
        self.post('historical_ally');self.post('historical_hostile',first=2,second=4)
        own=country_preferences(db.session,1)
        self.assertEqual([row['country_id'] for row in own],[2])
        self.assertEqual(own[0]['status'],'historical_ally')
        self.assertNotIn('actor',own[0]);self.assertNotIn('revision',own[0])
        self.assertEqual(country_preferences(db.session,3),[])
        # This fixture doesn't create the actual stosunki table: save never accesses it.
        from sqlalchemy import inspect
        self.assertFalse(inspect(db.engine).has_table(Stosunki.__tablename__))
