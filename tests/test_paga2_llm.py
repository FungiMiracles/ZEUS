"""PAGA2 etap 9 — integracja z modelami AI: polityka PAGA2 w kontekście modeli, twardy limit pożyczek,
lista państw obsługiwanych przez modele oraz inicjowanie wpisów i wiadomości przez PAGA2."""
import unittest
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace as NS
from unittest.mock import patch
from flask import Flask
from sqlalchemy import select,event
from extensions import db
from game.paga2 import catalog,communication
from game.paga2.models import Paga2Profile,Paga2Decision,Paga2Plan
from test_paga2_foundation import Paga2Fixture
from test_paga2_diplomacy import dctx


class PolicyContextTests(Paga2Fixture,unittest.TestCase):
    def setUp(self):
        super().setUp()
        from game.paga_relationships import PagaRelationship
        from game.autonomy_models import AutonomyAssessment
        from models import Stosunki,DictStosunkiRelacja,DictStosunkiStan
        for model in (PagaRelationship,Paga2Plan,Stosunki,DictStosunkiRelacja,DictStosunkiStan,AutonomyAssessment):model.__table__.create(db.engine,checkfirst=True)
        profile=db.session.get(Paga2Profile,1);profile.traits={**profile.traits,'militarism':90,'secrecy':10,'health':55};profile.categories=['imperialist'];profile.priorities=['conquest','trade']
        db.session.add(Paga2Decision(request_key='d1',country_id=1,mode='CYCLIC',trigger='t',domain='war',action='LAND_ATTACK',status='EXECUTED',options=[],inputs={},
                                     result={'wykonane':[{'action':'LAND_ATTACK','label':'Najazd na miasto #5','target':2}]},game_at=datetime(3000,1,1)))
        db.session.add(Paga2Plan(country_id=1,goal='factory:tanks',priority='conquest',status='ACTIVE',steps=[]))
        db.session.commit()

    def test_policy_block_reflects_profile_decisions_and_plans(self):
        from game.paga2.llm_context import policy
        block=policy(db.session,1,datetime(3000,1,10),other_id=2)
        self.assertIn('PAGA2',block['zasada'])
        self.assertEqual(block['ogólny_charakter'],['Państwo imperialistyczne'])
        self.assertEqual(block['priorytety_od_najważniejszego'],['Podbój nowych terytoriów','Rozwój handlu międzynarodowego'])
        self.assertEqual(block['wyraziste_cechy'],{'Militaryzm':90,'Skrytość':10})   # tylko cechy wyraźnie odbiegające od 50
        self.assertEqual(block['ostatnie_decyzje_PAGA2'],[{'data':'3000-01-01','działanie':'Najazd na miasto #5'}])
        self.assertEqual(block['aktywne_plany'],['Fabryka czołgów'])
        self.assertEqual(block['stosunek_do_rozmówcy']['państwo_id'],2)
        self.assertIsNone(policy(db.session,2,datetime(3000,1,10)))   # bez profilu PAGA2 — stary kontekst

    def test_eligible_ids_follow_paga2_profiles(self):
        from game.autonomy_engine import eligible_ids
        self.assertEqual(eligible_ids(db.session),[1])
        db.session.get(Paga2Profile,1).autonomy_enabled=False;db.session.commit()
        self.assertEqual(eligible_ids(db.session),[])


class LoanLimitTests(unittest.TestCase):
    def setUp(self):
        self.app=Flask(__name__);self.app.config.update(SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        db.init_app(self.app);self.ctx=self.app.app_context();self.ctx.push()
        from game.loan_models import StateLoan
        from game.models import GameUser
        from models import Panstwo
        for model in (Panstwo,GameUser,StateLoan,Paga2Profile):model.__table__.create(db.engine,checkfirst=True)
        db.session.add(GameUser(id=1,username='u',username_normalized='u',is_active=True));db.session.flush()
        db.session.add_all([StateLoan(id=5,borrower_id=2,lender_id=1,requested_by=1,amount=Decimal('5000000000'),request_id='r1'),
                            StateLoan(id=6,borrower_id=2,lender_id=1,requested_by=1,amount=Decimal('100000000'),request_id='r2'),
                            Paga2Profile(panstwo_id=1,categories=['economic'],priorities=['trade'],traits={k:50 for k in catalog.TRAITS},actor='t')])
        db.session.commit()
    def tearDown(self):db.session.remove();db.engine.dispose();self.ctx.pop()

    def test_accept_above_capacity_is_blocked(self):
        from game.paga_ai_executor import require_loan_capacity
        actor=NS(country_id=1)
        with patch('game.paga2.finance.loan_capacity',return_value={'max_loan':1e9}),patch('game.finance_service.game_now',return_value=datetime(3000,1,1)):
            with self.assertRaisesRegex(ValueError,'przekracza zdolność pożyczkową'):require_loan_capacity(actor,5)
            require_loan_capacity(actor,6)          # w granicach — decyzja należy do modelu
            require_loan_capacity(NS(country_id=3),5)  # cudza pożyczka — walidację robi gra


class CommunicationTests(unittest.TestCase):
    def ctx(self,**kwargs):
        c=dctx(**kwargs);c.triggers=[];c.now=datetime(3000,1,10);c.country_id=1
        c.memory['world_conflicts']=[]
        return c

    def run_occasions(self,c,recent=()):
        with patch('game.paga2.communication.recent_actions',return_value=list(recent)):
            return communication.occasions(c,{2:'B',3:'C',7:'Wróg'})

    def test_occasions_from_attacks_allies_wars_offers_and_relations(self):
        c=self.ctx();c.situation['allies']=[2]
        c.triggers=[{'kind':'land_invasion','label':'najazd','source':'powiadomienie','id':11,'text':'Wtargnięcie'},{'kind':'forum_message','id':12}]
        c.memory['world_conflicts']=[{'id':40,'kind':'BOMBARDMENT','actor':7,'target':2,'at':'3000-01-08'},{'id':41,'kind':'WAR','actor':7,'target':3,'at':'3000-01-09'},
                                     {'id':42,'kind':'WAR','actor':7,'target':3,'at':'2999-01-01'}]
        recent=[('TRADE_OFFER',None,datetime(3000,1,9)),('RELATION_IMPROVE',3,datetime(3000,1,9)),('WAR',7,datetime(3000,1,9)),('BUDGET_APPROVE',None,datetime(3000,1,9))]
        keys={item[0]:item for item in self.run_occasions(c,recent)}
        self.assertIn('paga2:attack:powiadomienie:11',keys)
        self.assertIn('paga2:ally:40',keys);self.assertEqual(keys['paga2:ally-pm:40'][2],2)         # wiadomość do zaatakowanego sojusznika
        self.assertIn('paga2:war:41',keys);self.assertNotIn('paga2:war:42',keys)                  # stare wydarzenia pominięte
        kinds={k.split(':')[1] for k in keys}
        self.assertTrue({'offer','relation','hostile'}<=kinds)
        self.assertFalse(any('forum_message' in k for k in keys))                               # odpowiedzi na forum to zadanie modeli, nie inicjatywa

    def test_reactions_to_recapture_depend_on_relations_and_character(self):
        from game.paga2.communication import recapture_side
        c=self.ctx();c.situation['allies']=[2]
        self.assertEqual(recapture_side(c,2,7)[0],2)                       # sojusznik odbija ziemie — popieramy go
        self.assertEqual(recapture_side(c,7,2)[0],2)                       # sojusznik jest okupantem — stoimy po jego stronie
        self.assertIsNone(recapture_side(self.ctx(traits={'solidarity':10,'interventionism':10}),5,6))   # obojętne państwo milczy
        calm=recapture_side(self.ctx(traits={'solidarity':90}),5,6);self.assertIn('rozmów',calm[2])
        # Jesteśmy okupantem: ugodowe państwo proponuje rozmowy, prowokacyjne zapowiada utrzymanie kontroli.
        event={'id':50,'kind':'RECAPTURE_ATTACK','actor':7,'target':1,'at':'3000-01-09','object':'Cirn','won':False}
        soft=self.ctx(traits={'agreeableness':90});soft.memory['actions_against_us']=[event]
        hard=self.ctx(traits={'agreeableness':10,'provocation':90});hard.memory['actions_against_us']=[event]
        soft_items={k:i for k,*i in self.run_occasions(soft)};hard_items={k:i for k,*i in self.run_occasions(hard)}
        self.assertIn('rozmów',soft_items['paga2:recapture-us:50'][2]);self.assertIn('paga2:recapture-talks:50',soft_items)
        self.assertIn('utrzymamy kontrolę',hard_items['paga2:recapture-us:50'][2]);self.assertNotIn('paga2:recapture-talks:50',hard_items)
        # Wydarzenie z innego regionu: wpis i wiadomość do sojusznika, który odbija swoje ziemie.
        ally=self.ctx();ally.situation['allies']=[2]
        ally.memory['world_conflicts']=[{'id':51,'kind':'RECAPTURE_ATTACK','actor':2,'target':7,'at':'3000-01-09','object':'Cirn','won':True}]
        keys={k:i for k,*i in self.run_occasions(ally)}
        self.assertIn('popieramy sojusznika',keys['paga2:recapture:51'][2]);self.assertEqual(keys['paga2:recapture-pm:51'][1],2)

    def test_no_initiatives_when_llm_is_off_or_daily_limit_reached(self):
        c=self.ctx();c.triggers=[{'kind':'under_attack','label':'atak','source':'powiadomienie','id':1,'text':'x'}]
        class FakeSession:
            def __init__(self,*a):pass
            def __enter__(self):return self
            def __exit__(self,*a):return False
            def execute(self,q):return NS(all=lambda:[])
        with patch('game.paga2.communication.Session',FakeSession),patch('game.paga2.communication.db',NS(engine=None)):
            with patch('game.paga2.communication.llm_control',return_value=None):self.assertEqual(communication.propose(c),[])
            with patch('game.paga2.communication.llm_control',return_value=NS(enabled=True)),patch('game.paga2.communication.used_today',return_value=communication.DAILY_LIMIT):
                self.assertEqual(communication.propose(c),[])
            with patch('game.paga2.communication.llm_control',return_value=NS(enabled=True)),patch('game.paga2.communication.used_today',return_value=0),\
                 patch('game.paga2.communication.already',return_value=False),patch('game.paga2.communication.recent_actions',return_value=[]):
                [option]=communication.propose(c)
        self.assertEqual(option.action,'FORUM_POST');self.assertEqual(option.payload['group'],'communication')

    def test_secretive_states_speak_less(self):
        from game.paga2.scoring import score,Option
        make=lambda:Option('x','communication','FORUM_POST','w',traits={'secrecy':-.6,'provocation':.4},base=0.0)
        loud=score(make(),self.ctx(traits={'secrecy':5,'provocation':90}));quiet=score(make(),self.ctx(traits={'secrecy':95,'provocation':10}))
        self.assertGreater(loud.score,quiet.score+10)


class InitiativeTaskTests(unittest.TestCase):
    def setUp(self):
        self.app=Flask(__name__);self.app.config.update(SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',ENV_NAME='UAT',PAGA_AI_CONFIGURED=True,PAGA_ENABLED=True)
        db.init_app(self.app);self.ctx=self.app.app_context();self.ctx.push()
        from game.paga_ai_models import PagaAiJob,PagaAiControl
        from models import Panstwo
        for model in (PagaAiJob,PagaAiControl,Panstwo):model.__table__.create(db.engine,checkfirst=True)
        db.session.add_all([PagaAiControl(id=1,enabled=True,revision=4,model_id='m'),Panstwo(PANSTWO_ID=2,panstwo_nazwa='B')]);db.session.commit()
    def tearDown(self):db.session.remove();db.engine.dispose();self.ctx.pop()

    def test_execute_enqueues_llm_task_with_recipient_and_dedupes(self):
        from game.paga2.scoring import Option
        from game.paga_ai_models import PagaAiJob
        c=NS(country_id=1)
        option=Option('comm:k','communication','PM_INITIATE','x',payload={'kind':'private_initiative','key':'paga2:ally-pm:40','text':'Wsparcie','target':2,'group':'communication'})
        with patch('game.paga_ai_actor.country_user_id',return_value=77):
            result=communication.execute(c,option)
            self.assertEqual(result['status'],200)
            self.assertEqual(communication.execute(c,option)['status'],409)
        job=db.session.scalar(select(PagaAiJob))
        self.assertEqual((job.kind,job.revision,job.source),('private_initiative',4,'paga2'))
        self.assertEqual((job.context['recipient_user_id'],job.context['target_country_name']),(77,'B'))
        from game.paga_ai_context import reply_reference,goal_text
        answer,_=reply_reference(db.session,job,None)
        self.assertEqual(answer['data'],{'recipient_id':77})
        self.assertIn('Wsparcie',goal_text(job))


if __name__=='__main__':unittest.main()
