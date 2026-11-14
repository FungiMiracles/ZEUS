"""PAGA2 etap 2 — panel administratora: zakładki, profil państwa, konfiguracja, historia decyzji i stan państwa."""
import unittest,json,re
from datetime import datetime
from pathlib import Path
from flask import Flask
from jinja2 import ChoiceLoader,DictLoader
from sqlalchemy import select
from extensions import db
from models import Panstwo,DictKontynent
from routes_paga import paga_bp
from game.paga import PagaConfiguration,PagaRevision,TRAITS as OLD_TRAITS,INTERESTS
from game.paga2 import catalog
from game.paga2.models import Paga2Control,Paga2Profile,Paga2ProfileRevision,Paga2Decision,Paga2RandomDraw


def profile(**changes):
    data={'revision':0,'categories':['economic'],'priorities':['trade','research'],'traits':{key:40 for key in catalog.TRAITS},'autonomyEnabled':True}
    data.update(changes);return data


class Paga2PanelTests(unittest.TestCase):
    def setUp(self):
        root=Path(__file__).resolve().parents[1]
        self.app=Flask(__name__,template_folder=str(root/'templates'),static_folder=str(root/'static'))
        self.app.config.update(TESTING=True,SECRET_KEY='paga2-test-only',SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',PAGA_ENABLED=True)
        self.app.jinja_loader=ChoiceLoader([DictLoader({'base_layout.html':'{% block content %}{% endblock %}'}),self.app.jinja_loader])
        self.app.add_url_rule('/home','home_page',lambda:'home')
        db.init_app(self.app);self.app.register_blueprint(paga_bp)
        self.ctx=self.app.app_context();self.ctx.push()
        from sqlalchemy import event
        @event.listens_for(db.engine,'connect')
        def sqlite_functions(connection,record):
            connection.create_function('CHAR_LENGTH',1,len);connection.create_collation('ascii_bin',lambda a,b:(a>b)-(a<b))
        from game.models import GameUser,GamePlayerCountry
        from game.finance_models import StateBudget,StateBudgetAllocation,StateFinancialAccount,StateFinancialPeriod,BudgetTransfer
        from game.military_models import MilitaryBase,MilitaryVessel,MissileDefense
        from game.commerce_models import Mine,ResourceStock
        from game.industry_models import PowerPlant
        from game.research_models import AmmunitionFactory,ResearchAccount
        from game.radar_models import Radar
        from game.intelligence_models import IntelligenceAgent
        from game.communication_models import PrivateMessage
        from models import Wojsko,Stosunki,DictStosunkiRelacja,DictStosunkiStan,Region
        tables=[DictKontynent,Panstwo,Region,PagaConfiguration,PagaRevision,GameUser,GamePlayerCountry,Paga2Control,Paga2Profile,Paga2ProfileRevision,Paga2Decision,Paga2RandomDraw,
                StateFinancialPeriod,StateBudget,StateBudgetAllocation,StateFinancialAccount,BudgetTransfer,MilitaryBase,MilitaryVessel,MissileDefense,Mine,ResourceStock,PowerPlant,
                AmmunitionFactory,ResearchAccount,Radar,IntelligenceAgent,PrivateMessage,Wojsko,DictStosunkiRelacja,DictStosunkiStan,Stosunki]
        for model in tables:model.__table__.create(db.engine,checkfirst=True)
        db.session.add_all([DictKontynent(kontynent_id=1,kontynent_nazwa='Alfa'),
                            Panstwo(PANSTWO_ID=1,panstwo_nazwa='Kraj A',panstwo_pelna_nazwa='Republika A',kontynent_id=1),
                            Panstwo(PANSTWO_ID=2,panstwo_nazwa='Kraj B',kontynent_id=1),Panstwo(PANSTWO_ID=3,panstwo_nazwa='Kraj C',kontynent_id=1),
                            Paga2Control(id=1,enabled=False,interval_minutes=60,revision=0,actor='test')])
        db.session.commit()
        self.client=self.app.test_client()
        with self.client.session_transaction() as session:session['rola']='wszechmocny'
        page=self.client.get('/admin/paga');self.assertEqual(page.status_code,200);self.page=page.text
        self.config=json.loads(re.search(r'<script type="application/json" id="paga-config">(.*?)</script>',page.text,re.S)[1])
        self.headers={'X-CSRF-Token':self.config['csrf'],'X-PAGA-Access':self.config['access']}

    def tearDown(self):db.session.remove();db.engine.dispose();self.ctx.pop()

    def get(self,url):return self.client.get(url,headers=self.headers)
    def post(self,url,data):return self.client.post(url,json=data,headers=self.headers)

    # ---- strona i zakładki ----
    def test_panel_has_five_tabs_and_no_legacy_character_form(self):
        for label in ('>PAGA<','>PAGA2<','>Konfiguracja PAGA2<','>Historia decyzji<','>Stan państwa PAGA<'):self.assertIn(label,self.page)
        self.assertEqual(self.page.count('role="tab" id="paga-main-tab-'),5)
        self.assertNotIn('id="paga-form"',self.page);self.assertNotIn('id="paga-continent"',self.page)
        self.assertIn('id="paga-relationships"',self.page)  # powiązania w zakładce PAGA2
        self.assertIn('wiki_paga2.js',self.page)
        cfg=self.config['paga2']
        self.assertEqual(len(cfg['catalog']['traits']),25);self.assertEqual(cfg['catalog']['maxCategories'],3)
        self.assertIsNone(cfg['mapUrl'])  # blueprint mapy WIKI nie jest zarejestrowany w teście

    def test_new_endpoints_require_access_token(self):
        for url in ('/admin/paga/paga2/panstwa','/admin/paga/paga2/panstwo/1','/admin/paga/paga2/konfiguracja','/admin/paga/paga2/decyzje','/admin/paga/paga2/stan/1'):
            with self.subTest(url=url):self.assertEqual(self.client.get(url).status_code,403)

    # ---- profil ----
    def test_profile_defaults_save_and_revision_conflict(self):
        data=self.get('/admin/paga/paga2/panstwo/1').get_json()
        self.assertEqual(data['country']['fullName'],'Republika A');self.assertEqual(data['profile']['revision'],0)
        self.assertEqual(set(data['profile']['traits']),set(catalog.TRAITS))
        response=self.post('/admin/paga/paga2/panstwo/1',profile())
        self.assertEqual(response.status_code,200,response.get_json())
        saved=response.get_json()['profile']
        self.assertEqual(saved['revision'],1);self.assertTrue(saved['autonomyEnabled']);self.assertEqual(saved['source'],'admin')
        self.assertEqual(len(response.get_json()['history']),1)
        self.assertEqual(self.post('/admin/paga/paga2/panstwo/1',profile()).status_code,409)
        self.assertEqual(self.post('/admin/paga/paga2/panstwo/1',profile(revision=1,priorities=['research','trade','alliances'])).status_code,200)
        self.assertEqual(db.session.get(Paga2Profile,1,populate_existing=True).priorities,['research','trade','alliances'])

    def test_profile_validation_errors(self):
        for data in (profile(categories=[]),profile(categories=['economic','welfare','terrorist','imperialist']),profile(priorities=[]),
                     profile(traits={**{k:40 for k in catalog.TRAITS},'ambition':120}),profile(autonomyEnabled='tak')):
            with self.subTest(data=data):self.assertEqual(self.post('/admin/paga/paga2/panstwo/1',data).status_code,400)
        self.assertEqual(self.get('/admin/paga/paga2/panstwo/99').status_code,404)

    def test_human_country_cannot_get_autonomy(self):
        from game.models import GameUser,GamePlayerCountry
        db.session.add(GameUser(id=5,username='gracz',username_normalized='gracz',email='g@example.invalid',email_normalized='g@example.invalid',password_hash='x',is_active=True));db.session.flush()
        db.session.add(GamePlayerCountry(user_id=5,panstwo_id=2));db.session.commit()
        response=self.post('/admin/paga/paga2/panstwo/2',profile())
        self.assertEqual(response.status_code,400);self.assertIn('gracza',response.get_json()['error'])
        self.assertEqual(self.post('/admin/paga/paga2/panstwo/2',profile(autonomyEnabled=False)).status_code,200)

    def test_saving_profile_syncs_legacy_autonomy_and_eligibility(self):
        from game.diplomacy_service import npc_eligible
        db.session.add(PagaConfiguration(panstwo_id=1,revision=1,approved_at=datetime(2026,1,1),approved_character={k:50 for k in OLD_TRAITS},
                                         approved_interests=[{'key':k,'active':True} for k in INTERESTS],autonomy_enabled=True,updated_at=datetime(2026,1,1),actor='t'))
        db.session.commit()
        self.assertTrue(npc_eligible(db.session,1))  # bez profilu PAGA2 obowiązuje dotychczasowa konfiguracja
        self.assertEqual(self.post('/admin/paga/paga2/panstwo/1',profile(autonomyEnabled=False)).status_code,200)
        db.session.expire_all()
        self.assertFalse(db.session.get(PagaConfiguration,1).autonomy_enabled)
        self.assertFalse(npc_eligible(db.session,1))
        self.assertEqual(self.post('/admin/paga/paga2/panstwo/1',profile(revision=1,autonomyEnabled=True)).status_code,200)
        db.session.expire_all();self.assertTrue(npc_eligible(db.session,1))

    def test_countries_overview_statuses(self):
        db.session.add(Paga2Profile(panstwo_id=3,categories=['welfare'],priorities=['welfare'],traits={k:50 for k in catalog.TRAITS},autonomy_enabled=False,source='migrated',actor='m'))
        db.session.commit()
        self.post('/admin/paga/paga2/panstwo/1',profile())
        items={c['id']:c for c in self.get('/admin/paga/paga2/panstwa').get_json()['countries']}
        self.assertEqual(items[1]['status'],'active');self.assertEqual(items[2]['status'],'none')
        self.assertEqual(items[3]['status'],'profile');self.assertTrue(items[3]['migrated'])

    # ---- konfiguracja ----
    def test_control_tab_reads_and_saves_settings(self):
        data=self.get('/admin/paga/paga2/konfiguracja').get_json()['control']
        self.assertFalse(data['enabled']);self.assertEqual(data['intervalMinutes'],60);self.assertEqual(data['randomizer']['total'],0)
        bad=self.post('/admin/paga/paga2/konfiguracja',{'enabled':False,'intervalMinutes':2,'revision':0})
        self.assertEqual(bad.status_code,400)
        saved=self.post('/admin/paga/paga2/konfiguracja',{'enabled':False,'intervalMinutes':120,'revision':0}).get_json()['control']
        self.assertEqual(saved['intervalMinutes'],120);self.assertEqual(saved['revision'],1);self.assertFalse(saved['enabled'])
        self.assertEqual(self.post('/admin/paga/paga2/konfiguracja',{'enabled':True,'intervalMinutes':120,'revision':0}).status_code,409)
        self.assertFalse(db.session.get(Paga2Control,1,populate_existing=True).enabled)

    def test_control_reports_randomizer_counts(self):
        db.session.add_all([Paga2RandomDraw(country_id=1,reason='konflikt',candidates=[['a',1],['b',1]],chosen='a'),Paga2RandomDraw(country_id=1,reason='konflikt',candidates=[],chosen='b'),
                            Paga2RandomDraw(country_id=2,reason='x',candidates=[],chosen='c')])
        db.session.commit()
        r=self.get('/admin/paga/paga2/konfiguracja').get_json()['control']['randomizer']
        self.assertEqual(r['total'],3);self.assertEqual(r['last24h'],3)
        self.assertEqual(r['perCountry'][0],{'countryId':1,'country':'Kraj A','calls':2});self.assertEqual(len(r['recent']),3)

    # ---- historia decyzji ----
    def test_decision_history_filters_and_detail(self):
        for index,(country,domain) in enumerate([(1,'economy'),(1,'diplomacy'),(2,'economy')]):
            db.session.add(Paga2Decision(request_key=f'k{index}',country_id=country,mode='CYCLIC',trigger='cykl',domain=domain,action='A'+str(index),status='EXECUTED',score=60+index,
                                         options=[{'action':'A','score':60,'feasible':True}],inputs={'reserve':1},result={'ok':True},game_at=datetime(3000,1,1)))
        db.session.add(Paga2RandomDraw(country_id=1,decision_key='k0',reason='remis',candidates=[['A',60],['B',59.5]],chosen='A'))
        db.session.commit()
        data=self.get('/admin/paga/paga2/decyzje').get_json()
        self.assertEqual(len(data['items']),3);self.assertEqual(data['items'][0]['action'],'A2')
        self.assertEqual({c['name'] for c in data['countries']},{'Kraj A','Kraj B'})
        self.assertEqual(len(self.get('/admin/paga/paga2/decyzje?country=1').get_json()['items']),2)
        self.assertEqual(len(self.get('/admin/paga/paga2/decyzje?country=1&domain=economy').get_json()['items']),1)
        first=data['items'][-1]['id']
        detail=self.get(f'/admin/paga/paga2/decyzje/{first}').get_json()['decision']
        self.assertEqual(detail['inputs'],{'reserve':1});self.assertEqual(detail['options'][0]['score'],60)
        self.assertEqual(detail['draws'][0]['chosen'],'A')
        self.assertEqual(self.get('/admin/paga/paga2/decyzje/999').status_code,404)

    def test_decision_history_stats_follow_filters_and_count_rejected_attempts(self):
        # 14 Nov 2026: kontenerki statystyk w Historii decyzji.
        rejected=[{'domain':'war','action':'VESSEL_SAIL','blocked':'Gra odrzuciła operację: Cel rejsu musi znajdować się na wodzie.'}]*2+[{'domain':'war','action':'LAND_ATTACK','blocked':'Gra odrzuciła operację: X'}]
        rows=[(1,'war','REJECTED',rejected,True),(1,'economy','EXECUTED',[],False),(2,'war','PASSIVE',[],False)]
        for index,(country,domain,status,options,randomized) in enumerate(rows):
            db.session.add(Paga2Decision(request_key=f's{index}',country_id=country,mode='CYCLIC',trigger='cykl',domain=domain,action='A',status=status,score=50,
                                         options=options,inputs={},result={},randomized=randomized,game_at=datetime(3000,1,1)))
        db.session.commit()
        stats=self.get('/admin/paga/paga2/decyzje').get_json()['stats']
        self.assertEqual(stats['total'],3);self.assertEqual(stats['byStatus']['REJECTED'],1);self.assertEqual(stats['byStatus']['EXECUTED'],1)
        self.assertEqual(stats['randomized'],1);self.assertEqual(stats['countries'],2);self.assertEqual(stats['last24h'],3)
        self.assertEqual(stats['topRejected'],[{'domain':'war','action':'VESSEL_SAIL','count':2},{'domain':'war','action':'LAND_ATTACK','count':1}])
        self.assertEqual({d['domain']:d['count'] for d in stats['domains']},{'war':2,'economy':1})
        filtered=self.get('/admin/paga/paga2/decyzje?country=1&status=EXECUTED').get_json()['stats']
        self.assertEqual(filtered['total'],2)   # filtr statusu nie zawęża podziału na statusy
        html=self.get('/admin/paga').get_data(as_text=True)
        self.assertIn('id="paga2-history-stats"',html)

    def test_proposals_nobody_can_answer_expire(self):
        from game.diplomacy_models import DiplomaticAction
        from game.diplomacy_service import expire_unanswerable
        from game.forum_models import GameNotification
        for model in (DiplomaticAction,GameNotification):model.__table__.create(db.engine,checkfirst=True)
        from game.models import GameUser
        db.session.add(GameUser(id=3,username='s',username_normalized='s',is_active=True));db.session.flush()
        db.session.add(DiplomaticAction(sender_user_id=3,source_country_id=2,target_country_id=3,source_country_name='B',target_country_name='C',kind='PEACE',status='PENDING',expected_relation_id=0,expected_state_id=0,expected_audit_id=0))
        db.session.commit()
        self.assertEqual(expire_unanswerable(db.session),1);db.session.commit()
        self.assertEqual(db.session.scalar(select(DiplomaticAction.status)),'EXPIRED')
        self.assertTrue(db.session.scalar(select(GameNotification.system_text)).startswith('Propozycja dla państwa C wygasła'))

    # ---- stan państwa ----
    def test_country_state_summarizes_finance_objects_army_and_messages(self):
        from game.military_models import MilitaryBase
        from game.commerce_models import Mine,ResourceStock
        from game.research_models import ResearchAccount
        from game.communication_models import PrivateMessage
        from game.finance_models import StateFinancialAccount
        from models import Wojsko
        from game.models import GameUser
        now=datetime(3000,1,1)
        db.session.add_all([GameUser(id=7,username='a',username_normalized='a',is_active=True),GameUser(id=8,username='b',username_normalized='b',is_active=True)])
        db.session.flush()
        db.session.add_all([MilitaryBase(panstwo_id=1,region_id=10,kind='land',name='Baza 1',level=2,garrison={'soldiers':100},map_x=1.0,map_y=2.0),
                            MilitaryBase(panstwo_id=1,region_id=10,kind='naval',level=1,garrison={},map_x=3.0,map_y=4.0),
                            Mine(panstwo_id=1,region_id=10,resource='zelazo',map_x=5.0,map_y=6.0,starts_at=now,ready_at=datetime(3000,2,1),extracted_at=datetime(3000,2,1),request_id='r1'),
                            ResearchAccount(panstwo_id=1,points=7,ammunition=0,nodes={'method':25,'arms_industry':10}),
                            ResourceStock(panstwo_id=1,resource='zelazo',quantity=120),
                            Wojsko(panstwo_id=1,wojska_ladowe_ilosc=1000,czolgi_ilosc=5),
                            PrivateMessage(sender_user_id=7,recipient_user_id=8,sender_country_id=2,recipient_country_id=1,sender_name='a',recipient_name='b',sender_country_name='Kraj B',recipient_country_name='Kraj A',sender_flag_path='x',recipient_flag_path='y',content='Witajcie',created_at=now)])
        db.session.commit()
        state=self.get('/admin/paga/paga2/stan/1').get_json()['state']
        self.assertEqual(state['country']['name'],'Kraj A')
        self.assertEqual(state['counts']['base_land']['count'],1);self.assertEqual(state['counts']['base_naval']['count'],1);self.assertEqual(state['counts']['mine']['count'],1)
        self.assertEqual({o['kind'] for o in state['objects']},{'base_land','base_naval','mine'})
        self.assertEqual([t['code'] for t in state['technologies'] if t['developed']],['method'])
        self.assertEqual(state['researchPoints'],7);self.assertEqual(state['stocks'],{'zelazo':120})
        self.assertEqual(state['army']['wojska_ladowe_ilosc'],1000)
        self.assertEqual(state['messages'][0]['content'],'Witajcie');self.assertFalse(state['messages'][0]['outgoing'])
        self.assertIsNone(state['finance']['budget'])
        self.assertEqual(self.get('/admin/paga/paga2/stan/99').status_code,404)


if __name__=='__main__':unittest.main()
