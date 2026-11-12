import unittest,json,re,copy
from pathlib import Path
from flask import Flask
from jinja2 import ChoiceLoader,DictLoader
from sqlalchemy import select
from extensions import db
from models import Panstwo,DictKontynent
from routes_paga import paga_bp
from game.paga import TRAITS,INTERESTS,PagaConfiguration,PagaRevision,approved_country_ids


class PagaTests(unittest.TestCase):
    def setUp(self):
        root=Path(__file__).resolve().parents[1]
        self.app=Flask(__name__,template_folder=str(root/'templates'),static_folder=str(root/'static'))
        self.app.config.update(TESTING=True,SECRET_KEY='paga-test-only',SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',PAGA_ENABLED=True)
        self.app.jinja_loader=ChoiceLoader([DictLoader({'base_layout.html':'{% block content %}{% endblock %}'}),self.app.jinja_loader])
        self.app.add_url_rule('/home','home_page',lambda:'home')
        db.init_app(self.app);self.app.register_blueprint(paga_bp)
        self.ctx=self.app.app_context();self.ctx.push()
        for model in (DictKontynent,Panstwo,PagaConfiguration,PagaRevision):model.__table__.create(db.engine)
        db.session.add_all([DictKontynent(kontynent_id=1,kontynent_nazwa='Alfa'),DictKontynent(kontynent_id=2,kontynent_nazwa='Beta'),Panstwo(PANSTWO_ID=1,panstwo_nazwa='Kraj A',panstwo_pelna_nazwa='Pełna nazwa kraju A',kontynent_id=1),Panstwo(PANSTWO_ID=2,panstwo_nazwa='Kraj B',kontynent_id=2),Panstwo(PANSTWO_ID=3,panstwo_nazwa='Usunięty',kontynent_id=1,status='usunięte')]);db.session.commit()
        self.client=self.app.test_client()
        with self.client.session_transaction() as session:session['rola']='wszechmocny'

    def tearDown(self):
        db.session.remove();db.engine.dispose();self.ctx.pop()

    def enter(self):
        response=self.client.get('/admin/paga')
        self.assertEqual(response.status_code,200)
        config=json.loads(re.search(r'<script type="application/json" id="paga-config">(.*?)</script>',response.text,re.S)[1])
        self.headers={'X-CSRF-Token':config['csrf'],'X-PAGA-Access':config['access']}
        return config

    def payload(self,mode='approve',revision=0):
        return {'mode':mode,'revision':revision,'character':{key:0 for key in TRAITS},'interests':[{'key':key,'active':index==0} for index,key in enumerate(INTERESTS)]}

    def save(self,data):return self.client.post('/admin/paga/panstwo/1',json=data,headers=self.headers)

    def test_wiki_role_opens_panel_without_extra_password(self):
        page=self.client.get('/admin/paga')
        self.assertEqual(page.status_code,200);self.assertIn('paga-config',page.text);self.assertNotIn('paga-password',page.text)
        self.enter()
        self.assertEqual(self.client.get('/admin/paga/panstwo/1',headers=self.headers).status_code,200)
        # Re-opening keeps the same CSRF binding, so an already open tab keeps working.
        first=self.headers['X-CSRF-Token'];self.enter();self.assertEqual(self.headers['X-CSRF-Token'],first)
        self.assertEqual(self.client.get('/admin/paga/panstwo/1',headers=self.headers).status_code,200)
        with self.client.session_transaction() as session:session.pop('rola')
        self.assertEqual(self.client.get('/admin/paga').status_code,403)
        self.assertEqual(self.client.get('/admin/paga/panstwo/1',headers=self.headers).status_code,403)

    def test_access_token_lasts_a_working_session_and_then_expires(self):
        from unittest.mock import patch
        import routes_paga
        self.enter()
        self.assertEqual(routes_paga.ACCESS_SECONDS,12*3600)
        with patch('routes_paga.ACCESS_SECONDS',-1):
            response=self.client.get('/admin/paga/panstwo/1',headers=self.headers)
        self.assertEqual(response.status_code,403)

    def test_role_csrf_access_token_and_uat_guards(self):
        self.enter()
        self.assertEqual(self.client.get('/admin/paga/panstwo/1').status_code,403)
        self.assertEqual(self.client.get('/admin/paga/panstwo/1',headers={**self.headers,'X-PAGA-Access':'bad'}).status_code,403)
        for role in ('tworzyciel','obserwator',''):
            with self.client.session_transaction() as session:session['rola']=role
            self.assertEqual(self.client.get('/admin/paga').status_code,403)
            self.assertEqual(self.save(self.payload()).status_code,403)
        self.app.config['PAGA_ENABLED']=False
        self.assertEqual(self.client.get('/admin/paga').status_code,404)

    def test_country_filter_and_unconfigured_blank_values(self):
        self.enter()
        self.assertEqual(self.client.get('/admin/paga/panstwa',headers=self.headers).json,{'countries':[]})
        self.assertEqual(self.client.get('/admin/paga/panstwa?continent=1&q=kraj',headers=self.headers).json,{'countries':[{'id':1,'name':'Kraj A'}]})
        self.assertEqual(self.client.get('/admin/paga/panstwa?continent=2&q=Kraj%20A',headers=self.headers).json,{'countries':[]})
        response=self.client.get('/admin/paga/panstwo/1',headers=self.headers)
        self.assertEqual(response.json['configuration']['character'],{key:None for key in TRAITS})
        self.assertEqual(response.json['country']['fullName'],'Pełna nazwa kraju A')
        self.assertTrue(response.json['country']['flag'].endswith('Kraj_A.jpg'))
        self.assertEqual(self.client.get('/admin/paga/panstwo/3',headers=self.headers).status_code,404)

    def test_partial_draft_is_not_approved_and_survives_reload(self):
        self.enter();data=self.payload('draft');data['character']={key:None for key in TRAITS};data['character']['ambition']=0
        for interest in data['interests']:interest['active']=False
        response=self.save(data);self.assertEqual(response.status_code,200)
        self.assertEqual(approved_country_ids(db.session),set())
        db.session.expire_all();row=db.session.get(PagaConfiguration,1)
        self.assertIsNone(row.approved_at);self.assertEqual(row.draft_character['ambition'],0)
        self.assertIsNone(row.draft_character['militarism'])
        self.assertEqual(self.client.get('/admin/paga/panstwo/1',headers=self.headers).json['configuration']['character'],data['character'])

    def test_zero_is_valid_order_is_preserved_and_draft_keeps_approved_snapshot(self):
        self.enter();data=self.payload();data['interests'].reverse()
        self.assertEqual(self.save(data).status_code,200)
        self.assertEqual(approved_country_ids(db.session),{1})
        data=self.payload('draft',1);data['character']['ambition']=100
        self.assertEqual(self.save(data).status_code,200)
        db.session.expire_all();row=db.session.get(PagaConfiguration,1)
        self.assertEqual(row.approved_character['ambition'],0);self.assertEqual(row.draft_character['ambition'],100)
        self.assertEqual(row.approved_interests[0]['key'],'terrorism')
        self.assertEqual(approved_country_ids(db.session),{1})
        data['mode']='approve';data['revision']=2
        self.assertEqual(self.save(data).status_code,200)
        db.session.expire_all();row=db.session.get(PagaConfiguration,1)
        self.assertEqual(row.approved_character['ambition'],100);self.assertIsNone(row.draft_character)
        self.assertEqual(db.session.query(PagaRevision).count(),3)

    def test_invalid_values_and_missing_interests_cannot_be_approved(self):
        self.enter()
        for value in (None,-1,101,True,'50',3.5):
            data=self.payload();data['character']['ambition']=value
            self.assertEqual(self.save(data).status_code,400,str(value))
        data=self.payload()
        for interest in data['interests']:interest['active']=False
        self.assertEqual(self.save(data).status_code,400)
        data=self.payload();data['interests'][0]=data['interests'][1]
        self.assertEqual(self.save(data).status_code,400)
        self.assertEqual(db.session.query(PagaConfiguration).count(),0)
        self.assertEqual(db.session.query(PagaRevision).count(),0)

    def test_stale_revision_does_not_overwrite_configuration_or_history(self):
        self.enter();data=self.payload();self.assertEqual(self.save(data).status_code,200)
        data['character']['ambition']=100
        self.assertEqual(self.save(data).status_code,409)
        db.session.expire_all()
        self.assertEqual(db.session.get(PagaConfiguration,1).approved_character['ambition'],0)
        self.assertEqual(db.session.query(PagaRevision).count(),1)

    def test_proof_is_bound_to_session_and_expires(self):
        from unittest.mock import patch
        from itsdangerous import SignatureExpired
        self.enter();other=self.app.test_client()
        with other.session_transaction() as session:session['rola']='wszechmocny';session['paga_api_csrf']='other'
        self.assertEqual(other.get('/admin/paga/panstwo/1',headers=self.headers).status_code,403)
        with patch('routes_paga.serializer') as serializer:
            serializer.return_value.loads.side_effect=SignatureExpired('expired')
            self.assertEqual(self.client.get('/admin/paga/panstwo/1',headers=self.headers).status_code,403)

    def test_autonomy_defaults_off_and_requires_approved_configuration(self):
        from game.paga import enabled_country_ids
        self.enter()
        self.assertFalse(self.client.get('/admin/paga/panstwo/1',headers=self.headers).json['configuration']['autonomyEnabled'])
        data=self.payload('draft');data['autonomyEnabled']=True
        self.assertEqual(self.save(data).status_code,200)
        self.assertEqual(enabled_country_ids(db.session),set())
        state=self.client.get('/admin/paga/panstwo/1',headers=self.headers).json['configuration']
        self.assertTrue(state['autonomyEnabled']);self.assertFalse(state['approvedAutonomyEnabled'])
        data.update(mode='approve',revision=1)
        self.assertEqual(self.save(data).status_code,200)
        self.assertEqual(enabled_country_ids(db.session),{1})

    def test_pause_resume_and_draft_do_not_change_approved_autonomy(self):
        from game.paga import enabled_country_ids
        self.enter();data=self.payload();data['autonomyEnabled']=True
        self.assertEqual(self.save(data).status_code,200)
        data.update(mode='draft',revision=1,autonomyEnabled=False)
        self.assertEqual(self.save(data).status_code,200)
        self.assertEqual(enabled_country_ids(db.session),{1})
        data.update(mode='approve',revision=2)
        self.assertEqual(self.save(data).status_code,200)
        self.assertEqual(enabled_country_ids(db.session),set())
        self.assertEqual(approved_country_ids(db.session),{1})
        data.update(revision=3,autonomyEnabled=True)
        self.assertEqual(self.save(data).status_code,200)
        self.assertEqual(enabled_country_ids(db.session),{1})
        db.session.expire_all()
        history=db.session.scalars(select(PagaRevision).order_by(PagaRevision.revision)).all()
        self.assertEqual([row.configuration['autonomyEnabled'] for row in history],[True,False,False,True])

    def test_invalid_autonomy_flag_cannot_be_saved(self):
        self.enter()
        for value in (None,0,1,'true','false',[],{}):
            data=self.payload();data['autonomyEnabled']=value
            self.assertEqual(self.save(data).status_code,400)
        self.assertEqual(db.session.query(PagaConfiguration).count(),0)

    def install_autonomy(self):
        # Wycofany silnik regułowy: sterowanie dostępne tylko z flagą testową (od 11 Nov 2026 decyzje podejmuje PAGA2).
        self.app.config['PAGA_LEGACY_ENGINES']=True
        from datetime import datetime
        from game import autonomy_models as models
        from game.models import GamePlayerCountry
        GamePlayerCountry.__table__.create(db.engine,checkfirst=True)
        classes=[models.AutonomyControl,models.AutonomySchedule,models.AutonomyEvent,models.AutonomySourceReceipt,models.AutonomyMemory,models.AutonomyAssessment,models.AutonomyReaction,models.AutonomyAnalysis]
        for model in classes:model.__table__.create(db.engine,checkfirst=True)
        db.session.add(models.AutonomyControl(id=1,enabled=True,revision=0,max_actions=3,window_days=30,cooldown_days=7,max_chain_depth=2,started_at=datetime(2990,1,1)));db.session.commit()

    def test_monitor_is_guarded_filters_dates_and_global_pause_is_versioned(self):
        self.install_autonomy();self.enter()
        self.assertEqual(self.client.get('/admin/paga/monitor').status_code,403)
        data=self.client.get('/admin/paga/monitor',headers=self.headers).json
        self.assertTrue(data['control']['enabled'])
        payload={'enabled':False,'revision':0,'maxActions':5,'windowDays':30,'cooldownDays':10}
        self.assertEqual(self.client.post('/admin/paga/sterowanie',headers=self.headers,json=payload).status_code,200)
        data=self.client.get('/admin/paga/monitor',headers=self.headers).json
        self.assertFalse(data['control']['enabled']);self.assertEqual(data['control']['maxActions'],5)
        self.assertEqual(self.client.post('/admin/paga/sterowanie',headers=self.headers,json=payload).status_code,409)
        self.assertEqual(self.client.get('/admin/paga/monitor?from=bad',headers=self.headers).status_code,400)

    def test_monitor_history_filters_and_private_memory_are_admin_only(self):
        self.install_autonomy();self.enter()
        from datetime import datetime
        from game.autonomy_models import AutonomyAnalysis
        for id,country,kind in [(1,1,'PASSIVE'),(2,2,'WAR')]:
            db.session.add(AutonomyAnalysis(id=id,request_key=str(id),country_id=country,game_at=datetime(2990,1,id),trigger='PERIODIC',action=kind,status='PASSIVE',factors={'reason':'Test'},candidates=[]))
        db.session.commit()
        data=self.client.get('/admin/paga/monitor?country=1&from=2990-01-01&to=2990-01-01&kind=PASSIVE',headers=self.headers).json
        self.assertEqual([row['id'] for row in data['analyses']],[1])
        self.assertEqual(self.client.get('/admin/paga/monitor?kind=WAR',headers=self.headers).json['analyses'][0]['id'],2)

    def test_bielik_forum_option_is_removed(self):
        config=self.enter()
        self.assertNotIn('forumControlUrl',config)
        self.assertEqual(self.client.get('/admin/paga/forum-ai',headers=self.headers).status_code,404)
        self.assertEqual(self.client.post('/admin/paga/forum-ai',headers=self.headers,json={'enabled':True}).status_code,404)
