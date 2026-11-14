"""Shared-player authorization, isolation and catalogue coverage, on isolated SQLite."""
import json,unittest
from datetime import datetime,timedelta
from unittest.mock import patch
from sqlalchemy import select,delete
from sqlalchemy.orm import Session
from flask import jsonify
from extensions import db
from test_industry_0011 import IndustryTests as _IndustryFixture


def give_base_materials(country=1,count=1):
    """13 Nov 2026: rozmieszczenie bazy zużywa kamień i żelazo z magazynu — scenariusz dostaje surowce na `count` baz lądowych."""
    from extensions import db
    from game.commerce_models import ResourceStock
    from game.military_service import BASE_MATERIALS
    for code,need in BASE_MATERIALS['land'].items():
        row=db.session.get(ResourceStock,(country,code))
        if row is None:db.session.add(ResourceStock(panstwo_id=country,resource=code,quantity=need*count))
        else:row.quantity+=need*count
    db.session.commit()
from game.models import GameUser,GamePlayerCountry
from game.paga import PagaConfiguration,PagaRevision,TRAITS,INTERESTS
from game.paga_ai_models import PagaAiControl,PagaAiIdentity,PagaAiJob,PagaAiLog,PagaAiWrite,PagaAiGoal,PagaAiPlan,PagaAiMetric,PagaAiProvider
import paga_multi_ai_env
from game.paga_ai_actor import AiActor,AiPermissionError,acting,authorized,ensure_identity
from game.paga_ai_executor import execute
from game.player_operations import catalogue
from game.forum_models import ForumMessage,ForumMessageRecipient,GameNotification
from game.communication_models import PrivateMessage
from game.research_models import AmmunitionFactory
from models import Panstwo,Stosunki
from game.autonomy_models import AutonomyEvent,AutonomyControl
from game.paga_relationships import PagaRelationship,PagaRelationshipRevision

class AiTests(unittest.TestCase):
    def setUp(self):
        self.environment=paga_multi_ai_env.start()
        self.fixture=_IndustryFixture();self.fixture.setUp();self.app=self.fixture.app
        # Zestaw weryfikuje wycofany pełny zakres modeli AI (kod zachowany): PAGA2 od 11 Nov 2026 ogranicza modele do forum, wiadomości i pożyczek.
        self.app.config.update(ENV_NAME='UAT',PAGA_ENABLED=True,PAGA_AI_CONFIGURED=True,PAGA_LEGACY_ENGINES=True)
        self.app.url_build_error_handlers.append(lambda error,endpoint,values:'/stub/'+endpoint)
        self.app.context_processor(lambda:{'game_csrf_token':'token'})
        from game.intelligence import intelligence_bp
        from game.loans import loans_bp
        from game.army import army_bp
        from game.public_panels import public_panels_bp
        from game.player_context import player_context_bp
        from game.finanse import finance_bp
        from game.finance_models import BudgetCategory,FinancialNotification,StateFinancialPeriod
        db.session.connection().connection.driver_connection.create_collation("ascii_bin",lambda a,b:(a>b)-(a<b))
        for model in [BudgetCategory,FinancialNotification,StateFinancialPeriod]:model.__table__.create(db.engine,checkfirst=True)
        for blueprint in [intelligence_bp,loans_bp,army_bp,public_panels_bp,finance_bp,player_context_bp]:
            if blueprint.name not in self.app.blueprints:self.app.register_blueprint(blueprint)
        for model in [PagaConfiguration,PagaRevision,PagaAiControl,PagaAiIdentity,PagaAiJob,PagaAiLog,PagaAiWrite,PagaAiGoal,PagaAiPlan,PagaAiMetric,PagaAiProvider,ForumMessageRecipient,AutonomyEvent,AutonomyControl,PagaRelationship,PagaRelationshipRevision]:model.__table__.create(db.engine,checkfirst=True)
        db.session.execute(delete(GamePlayerCountry).where(GamePlayerCountry.panstwo_id==1))
        db.session.add(PagaConfiguration(panstwo_id=1,revision=1,approved_at=datetime(2026,1,1),approved_character={key:50 for key in TRAITS},approved_interests=[{'key':key,'active':key=='survival'} for key in INTERESTS],autonomy_enabled=True,updated_at=datetime(2026,1,1),actor='Test'))
        db.session.add(PagaAiControl(id=1,enabled=True,revision=0,model_id='test-model'));db.session.commit()
        identity=ensure_identity(db.session,1);db.session.commit()
        self.actor=AiActor(1,identity.user_id,0);self.step=0
        @self.app.errorhandler(AiPermissionError)
        def forbidden(error):db.session.rollback();return jsonify(error=str(error)),403
    def tearDown(self):self.fixture.tearDown();self.fixture.doCleanups();self.environment.stop()
    def call(self,operation,data=None,path=None,actor=None):
        self.step+=1
        return execute(self.app,actor or self.actor,{'operation_id':operation,'data':data or {},'path':path or {}},step=self.step)
    def test_catalogue_covers_every_registered_gameplay_route(self):
        from game.player_operations import GAME_BLUEPRINTS
        operations=catalogue(self.app)
        for rule in self.app.url_map.iter_rules():
            if rule.endpoint.split('.')[0] in GAME_BLUEPRINTS:
                for method in rule.methods&{'GET','POST'}:
                    op=operations[rule.endpoint+':'+method];self.assertTrue(op.description);self.assertIn('type',op.input_schema);self.assertIn('required',op.path_schema)
        self.assertNotIn('paga.ai_control:POST',operations)
        self.assertEqual(self.call('operations.list')['status'],200)
        self.assertEqual(self.call('operations.describe',{'id':'game_military.war_order:POST'})['status'],200)
    def test_identity_is_not_a_human_assignment_or_login_account(self):
        identity=db.session.get(PagaAiIdentity,1);user=db.session.get(GameUser,identity.user_id)
        self.assertIsNone(user.password_hash);self.assertIsNone(user.email)
        self.assertIsNone(db.session.scalar(select(GamePlayerCountry).where(GamePlayerCountry.user_id==identity.user_id)))
        self.fixture.login(identity.user_id)
        self.assertEqual(self.fixture.client.get('/game/forum').status_code,403)
    def test_ai_posts_and_human_replies_use_original_forum_and_notifications(self):
        result=self.call('game_forum.page:POST',{'content':'Wzywamy do poszanowania suwerenności i dialogu.','recipient_id':2})
        self.assertEqual(result['status'],303,result)
        message=db.session.scalar(select(ForumMessage));self.assertEqual(message.user_id,self.actor.user_id)
        self.assertEqual(message.panstwo_id,1)
        # 14 Nov 2026: gracz nie dostaje powiadomienia o wpisie (plakietka w menu), skrzynka PAGA nadal tak.
        self.assertIsNone(db.session.scalar(select(GameNotification.user_id).where(GameNotification.message_id==message.id)))
        self.fixture.login(2)
        response=self.fixture.post('/game/forum',content='Czy popieracie pokojowe rozwiązanie?',reply_to_id=str(message.id))
        self.assertEqual(response.status_code,303)
        reply=db.session.scalar(select(ForumMessage).order_by(ForumMessage.id.desc()))
        self.assertEqual(reply.addressees[0].user_id,self.actor.user_id)
        self.assertEqual(db.session.scalar(select(GameNotification.user_id).where(GameNotification.message_id==reply.id)),self.actor.user_id)
    def test_private_messages_are_scoped_to_the_actor(self):
        first=self.call('game_messages.send:POST',{'content':'Proponujemy rozmowy dyplomatyczne.','recipient_id':2})
        self.assertEqual(first['status'],201,first)
        message=db.session.scalar(select(PrivateMessage));self.assertEqual(message.sender_country_id,1)
        other=PrivateMessage(sender_user_id=2,recipient_user_id=3,sender_country_id=2,recipient_country_id=3,sender_name='Dwa',recipient_name='Trzy',sender_country_name='Dwa',recipient_country_name='Trzy',sender_flag_path='f',recipient_flag_path='f',content='TAJNE_INNE_PAŃSTWA')
        db.session.add(other);db.session.commit()
        result=self.call('game_messages.detail:GET',path={'message_id':other.id})
        self.assertEqual(result['status'],404,result);self.assertNotIn('TAJNE_INNE_PAŃSTWA',str(result))
    def test_human_can_address_ai_privately_using_same_recipient_picker(self):
        self.fixture.login(2)
        response=self.fixture.post('/game/wiadomosci',recipient_id=str(self.actor.user_id),content='Wiadomość skierowana do waszego państwa.')
        self.assertEqual(response.status_code,201)
        message=db.session.scalar(select(PrivateMessage));self.assertEqual(message.recipient_country_id,1)
        result=self.call('game_messages.detail:GET',path={'message_id':message.id})
        self.assertEqual(result['status'],200)
        self.assertIn('Wiadomość skierowana',str(result))
    def test_same_build_operation_and_ownership_validation_as_player(self):
        result=self.call('game_infrastructure.industry_change:POST',{'action':'build','category':'factory','kind':'chips','level':1,'region_id':1,'x':10,'y':10})
        self.assertEqual(result['status'],200,result)
        self.assertEqual(db.session.query(AmmunitionFactory).count(),1)
        result=self.call('game_infrastructure.industry_change:POST',{'action':'build','category':'factory','kind':'chips','level':1,'region_id':2,'x':10,'y':10})
        self.assertEqual(result['status'],400,result);self.assertEqual(db.session.query(AmmunitionFactory).count(),1)
    def test_missing_research_or_budget_cannot_be_bypassed(self):
        from game.research_models import ResearchAccount
        account=db.session.get(ResearchAccount,1);account.nodes={};db.session.commit()
        result=self.call('game_infrastructure.industry_change:POST',{'action':'build','category':'factory','kind':'chips','level':1,'region_id':1,'x':10,'y':10})
        self.assertEqual(result['status'],400,result);self.assertEqual(db.session.query(AmmunitionFactory).count(),0)
    def test_takeover_and_country_disable_reject_generated_commands(self):
        db.session.add(GamePlayerCountry(user_id=1,panstwo_id=1));db.session.commit()
        self.assertEqual(self.call('game_forum.page:POST',{'content':'Nie wolno opublikować.'})['status'],403)
        self.assertEqual(db.session.query(ForumMessage).count(),0)
        db.session.execute(delete(GamePlayerCountry).where(GamePlayerCountry.panstwo_id==1));profile=db.session.get(PagaConfiguration,1);profile.autonomy_enabled=False;db.session.commit()
        self.assertEqual(self.call('game_forum.page:POST',{'content':'Nie wolno opublikować.'})['status'],403)
    def test_off_switch_invalidates_old_generations_and_cancels_queue(self):
        from engine.paga_ai_scheduler import toggle
        db.session.add(PagaAiJob(country_id=1,trigger='pending',revision=0,status='QUEUED'));db.session.commit()
        toggle(db.session,False,0);db.session.commit()
        self.assertEqual(db.session.scalar(select(PagaAiJob.status)),'CANCELLED')
        self.assertEqual(self.call('game_forum.page:POST',{'content':'Stara dyspozycja.'})['status'],403)
        toggle(db.session,True,1);db.session.commit()
        self.assertEqual(self.call('game_forum.page:POST',{'content':'Stara dyspozycja po ponownym włączeniu.'})['status'],403)
        self.assertEqual(db.session.query(ForumMessage).count(),0)
    def test_final_commit_rechecks_switch_even_after_mutations_were_prepared(self):
        with Session(db.engine) as session:
            with acting(self.actor):
                authorized(session,self.actor)
                session.add(ForumMessage(user_id=self.actor.user_id,panstwo_id=1,author_name='PAGA',country_name='Test',flag_path='f',content='Nie zatwierdzać.',entenda_date=datetime(2990,1,1).date()))
                control=session.get(PagaAiControl,1);control.enabled=False
                with self.assertRaises(AiPermissionError):session.commit()
                session.rollback()
        self.assertEqual(db.session.query(ForumMessage).count(),0)
    def test_model_cannot_change_identity_or_invoke_admin_sql_or_shell(self):
        for operation,data in [('paga.control:POST',{}),('sql',{}),('shell',{}),('game_forum.page:POST',{'content':'Podszycie','user_id':2}),('game_forum.page:POST',{'content':'Podszycie','csrf_token':'fake'})]:
            with self.subTest(operation=operation,data=data):self.assertEqual(self.call(operation,data)['status'],400)
        self.assertEqual(db.session.query(ForumMessage).count(),0)
    def test_country_memories_do_not_mix_and_drafts_are_not_exposed(self):
        from engine.paga_ai_scheduler import context
        one=db.session.get(PagaAiIdentity,1);one.memory='Strategia tylko kraju pierwszego'
        config=db.session.get(PagaConfiguration,1);config.draft_interests=[{'key':'terrorism','active':True}];db.session.commit()
        value=context(db.session,self.actor,'test')
        self.assertEqual(value['pamięć_strategiczna'],one.memory);self.assertNotIn('Terroryzm',str(value))
    def test_relationship_context_is_scoped_directional_and_not_a_war_block(self):
        from engine.paga_ai_scheduler import context
        from game.paga_relationships import save_relationship
        with Session(db.engine) as session,session.begin():
            save_relationship(session,1,2,{'revision':0,'status':'historical_ally','satelliteId':None},'Admin')
            save_relationship(session,2,3,{'revision':0,'status':'satellite','satelliteId':2},'Admin')
        preferences=context(db.session,self.actor,'test')['powiązania_historyczne_PAGA']
        self.assertEqual(len(preferences),1);self.assertEqual(preferences[0]['country_id'],2)
        self.assertEqual(preferences[0]['status'],'historical_ally')
        # A preference never bypasses or adds a rule to ordinary diplomacy.
        result=self.call('game_diplomacy.create_action:POST',{'kind':'RELATION','target_id':2,'relation_id':10})
        self.assertEqual(result['status'],201,result)
        result=self.call('game_diplomacy.create_action:POST',{'kind':'WAR','target_id':2})
        self.assertEqual(result['status'],201,result)
        self.assertEqual(db.session.get(PagaRelationship,(1,2),populate_existing=True).status,'historical_ally')

    def test_historical_hostility_does_not_prevent_improving_diplomacy(self):
        from models import DictStosunkiRelacja
        from game.paga_relationships import save_relationship
        from game.diplomacy_models import DiplomaticAction
        db.session.add(DictStosunkiRelacja(relacja_id=7,relacja_nazwa='Dobre'));db.session.commit()
        with Session(db.engine) as session,session.begin():
            save_relationship(session,1,2,{'revision':0,'status':'historical_hostile','satelliteId':None},'Admin')
        result=self.call('game_diplomacy.create_action:POST',{'kind':'RELATION','target_id':2,'relation_id':7})
        self.assertEqual(result['status'],201,result)
        self.assertEqual(db.session.scalar(select(DiplomaticAction)).status,'PENDING')

    def test_prompt_refreshes_administrator_preferences_between_model_decisions(self):
        from engine.paga_ai_scheduler import run_tick
        from game.paga_relationships import save_relationship
        from tempfile import TemporaryDirectory
        temporary=TemporaryDirectory();self.addCleanup(temporary.cleanup);self.app.root_path=temporary.name
        captured=[]
        def model(messages,**kwargs):
            captured.append(messages)
            if len(captured)==1:
                with Session(db.engine) as session,session.begin():
                    save_relationship(session,1,2,{'revision':0,'status':'satellite','satelliteId':1},'Admin')
                return {'operation_id':'operations.list','data':{},'path':{}}
            return {'operation_id':'finish','data':{},'path':{}}
        first,second=paga_multi_ai_env.models(model)
        with first,second:run_tick(self.app)
        self.assertEqual(len(captured),2)
        first=json.loads(captured[0][1]['content'])['własne_państwo']
        second=json.loads(captured[1][1]['content'])['własne_państwo']
        self.assertEqual(first['powiązania_historyczne_PAGA'],[])
        self.assertEqual(second['powiązania_historyczne_PAGA'][0]['role'],'satellite')
        self.assertIn('nie zakazy',captured[1][0]['content'])
        self.assertIn('wyjątkowo rzadko',captured[1][0]['content'])
    def test_response_projection_removes_credentials_scripts_and_hidden_csrf(self):
        from game.paga_ai_observation import PlayerDocument,scrub
        value=scrub({'csrf':'SECRET','password_hash':'SECRET','email':'SECRET','stateUrl':'SECRET','basis_token':'allowed_game_revision','balance':10,'nested':{'cookie':'SECRET'}})
        self.assertNotIn('SECRET',str(value));self.assertNotIn('basis_token',value)
        doc=PlayerDocument();doc.feed('<script>DELETE_APP_CODE</script><form><input name="csrf_token" type="hidden" value="SECRET"><input name="version" type="hidden" value="3"><textarea name="content">Tekst publiczny</textarea></form>')
        with self.app.test_request_context():projected=doc.observation()
        self.assertNotIn('DELETE_APP_CODE',str(projected));self.assertNotIn('SECRET',str(projected));self.assertIn('version',str(projected))
    def test_every_catalogued_write_rejects_forged_identity_before_reaching_handler(self):
        operations=catalogue(self.app)
        for op in operations.values():
            if op.method=='GET':continue
            with self.subTest(operation=op.id):self.assertEqual(self.call(op.id,{'user_id':2},path={name:1 for name in op.path_schema['required']})['status'],400)
        self.assertEqual(db.session.query(ForumMessage).count(),0)
    def test_audit_records_country_time_operation_validation_and_model(self):
        self.call('game_forum.page:POST',{'content':'Stanowisko państwa.'})
        log=db.session.scalar(select(PagaAiLog));self.assertEqual(log.country_id,1);self.assertEqual(log.operation,'game_forum.page:POST');self.assertEqual(log.validation,'EXECUTED');self.assertTrue(log.game_at);self.assertTrue(log.real_at);self.assertTrue(log.model_id);self.assertNotIn('csrf',str(log.parameters))
    def test_production_environment_never_executes_ai(self):
        self.app.config['ENV_NAME']='PROD'
        self.assertEqual(self.call('game_forum.page:POST',{'content':'Nie wolno.'})['status'],403)
        self.assertEqual(db.session.query(ForumMessage).count(),0)

    def test_direct_forum_and_private_messages_schedule_only_intended_country(self):
        from engine.paga_ai_scheduler import collect
        result=self.call('game_forum.page:POST',{'content':'Nasze stanowisko.'})
        self.assertEqual(result['status'],303)
        root=db.session.scalar(select(ForumMessage));self.fixture.login(2)
        self.fixture.post('/game/forum',content='Odpowiedź na wasze stanowisko.',reply_to_id=str(root.id))
        collect(db.session);db.session.commit()
        jobs=db.session.scalars(select(PagaAiJob).where(PagaAiJob.trigger.like('forum:%'))).all()
        # Rebuild 2026-11: named priority scale (CRITICAL 0 … LOW 40); a forum reply to us is MEDIUM, above routine work.
        from game.paga_ai_tasks import PRIORITY
        self.assertEqual(len(jobs),1);self.assertEqual(jobs[0].country_id,1);self.assertEqual(jobs[0].priority,PRIORITY['MEDIUM']);self.assertEqual(jobs[0].kind,'forum_reply')
    def test_event_projection_excludes_other_private_events_and_unknown_attacker(self):
        at=datetime(2990,1,1)
        db.session.add_all([AutonomyEvent(source_key='ours',kind='UNATTRIBUTED_DAMAGE',actor_id=2,target_id=1,occurred_at=at,public=False,private_country_id=1,audience=[1],payload={'secret':'DONT_SEND'}),AutonomyEvent(source_key='other',kind='HYBRID_DETECTED',actor_id=1,target_id=2,occurred_at=at,public=False,private_country_id=2,audience=[2],payload={'secret':'OTHER_PRIVATE'})]);db.session.commit()
        result=self.call('game_player.events:GET')
        self.assertEqual(result['status'],200);self.assertNotIn('DONT_SEND',str(result));self.assertNotIn('OTHER_PRIVATE',str(result));self.assertIn('nieustalony',str(result))
    def test_disabling_during_generation_prevents_execution(self):
        from engine.paga_ai_scheduler import run_tick,toggle
        from tempfile import TemporaryDirectory
        temporary=TemporaryDirectory();self.addCleanup(temporary.cleanup);self.app.root_path=temporary.name
        def model(*args,**kwargs):
            with Session(db.engine) as session,session.begin():toggle(session,False,0)
            return {'operation_id':'game_forum.page:POST','data':{'content':'Spóźniony komunikat.'},'path':{}}
        first,second=paga_multi_ai_env.models(model)
        with first,second:run_tick(self.app)
        self.assertEqual(db.session.query(ForumMessage).count(),0)
        self.assertEqual(db.session.get(PagaAiControl,1,populate_existing=True).enabled,False)
    def test_all_mutation_handlers_are_reached_with_valid_ai_identity_and_bad_input(self):
        # Each registered mutation is checked, including route variables and dispatcher actions.
        count=0
        for op in catalogue(self.app).values():
            if op.method=='GET':continue
            paths={key:('wycena' if key=='operation' else 999999) for key in op.path_schema['required']}
            values=op.input_schema.get('properties',{}).get('action',{}).get('enum',[None])
            for action in values:
                data={'content':''}
                if action:data['action']=action
                with self.subTest(operation=op.id,action=action):
                    result=self.call(op.id,data,paths)
                    self.assertNotEqual(result['status'],401,result)
                    self.assertNotEqual(result['status'],503,result)
                count+=1
        self.assertGreater(count,40)

    def test_shared_research_trade_mine_loan_and_defense_mutations(self):
        from sqlalchemy import text
        from game.commerce_models import TradeOffer,Mine
        from game.loan_models import StateLoan
        from game.military_models import MilitaryBase
        from game.research_models import ResearchAccount
        from game.finance_models import StateBudget
        give_base_materials()
        for operation,data,model in [
            ('game_trade.change:POST',{'action':'offer','cargo':{'wegiel_kamienny':2},'price':'100','port_id':101,'departure_rate':'0'},TradeOffer),
            ('game_trade.mining_build:POST',{'region_id':1,'resource':'wegiel_kamienny','level':1,'x':10,'y':10},Mine),
            ('game_loans.change:POST',{'action':'request','lender_id':2,'amount':'50'},StateLoan),
            ('game_military.defense_change:POST',{'action':'deploy','kind':'land','region_id':1,'x':10,'y':10,'garrison':{'soldiers':100,'tanks':1}},MilitaryBase),
        ]:
            with self.subTest(operation=operation):
                result=self.call(operation,data);self.assertLess(result['status'],400,result);self.assertEqual(db.session.query(model).count(),1)
        db.session.execute(text("INSERT INTO game_state_budget_allocations(id,budget_id,category_code,amount) VALUES(99,1,'research',1000000000)"));db.session.commit()
        before=db.session.get(ResearchAccount,1).points
        self.assertEqual(self.call('game_research.state:GET')['status'],200)
        result=self.call('game_research.change:POST',{'action':'buy','count':1})
        self.assertEqual(result['status'],200,result)
        self.assertEqual(db.session.get(ResearchAccount,1,populate_existing=True).points,before+1)

    def test_diplomacy_and_intelligence_use_shared_country_identity(self):
        from sqlalchemy import text
        from game.diplomacy_models import DiplomaticAction
        from game.intelligence_models import IntelligenceAgent
        result=self.call('game_diplomacy.create_action:POST',{'kind':'RELATION','target_id':2,'relation_id':10})
        self.assertEqual(result['status'],201,result)
        result=self.call('game_diplomacy.create_action:POST',{'kind':'WAR','target_id':2})
        self.assertEqual(result['status'],201,result)
        self.assertEqual(db.session.query(DiplomaticAction).count(),2)
        db.session.execute(text("INSERT INTO game_state_budget_allocations(id,budget_id,category_code,amount) VALUES(98,1,'security_services',1000000000)"));db.session.commit()
        with patch('game.intelligence_service.game_now',return_value=datetime(2990,1,1)):
            result=self.call('game_intelligence.change:POST',{'action':'recruit','level':1,'count':1})
        self.assertEqual(result['status'],200,result)
        self.assertEqual(db.session.query(IntelligenceAgent).count(),1)

    def test_military_order_uses_player_war_and_inventory_checks(self):
        from game.military_models import MilitaryBase,MilitaryOrder
        from models import Wojsko
        command={'source_base_id':1,'kind':'missile','region_id':2,'missile_type':'short','missiles':2,'infrastructure':'road'}
        self.assertEqual(self.call('game_military.war_order:POST',command)['status'],400)
        db.session.add(Stosunki(PANSTWO_ID=1,PANSTWO_ID2=2,stan_id=8));db.session.commit()
        give_base_materials()
        deploy=self.call('game_military.defense_change:POST',{'action':'deploy','kind':'land','region_id':1,'x':10,'y':10,'garrison':{'soldiers':100,'launchers':1}})
        self.assertEqual(deploy['status'],200,deploy)
        base=db.session.scalar(select(MilitaryBase));command['source_base_id']=base.id
        with patch('game.military_geography.region_contains',return_value=True):
            location=self.call('game_military.defense_change:POST',{'action':'location','base_id':base.id,'x':10,'y':10})
        self.assertEqual(location['status'],200,location)
        with patch('game.military_flights.region_point',return_value=[100,10]):
            result=self.call('game_military.war_order:POST',command)
        self.assertEqual(result['status'],200,result);self.assertEqual(db.session.query(MilitaryOrder).count(),1)
        self.assertEqual(db.session.scalar(select(Wojsko.rakiety_krotkiego_zasiegu).where(Wojsko.panstwo_id==1)),18)

    # Production test: grid with enough energy (since 10 Nov 2026 a deficit stops factories; see test_infrastructure_effects).
    @patch('game.industry_service.powered_factories',new=lambda session,factories,production,resident:{f.id for f in factories})
    def test_factory_production_through_player_state_consumes_inputs(self):
        from test_game_military import NOW
        from game.commerce_models import ResourceStock
        from game.research_models import ResearchAccount
        result=self.call('game_infrastructure.industry_change:POST',{'action':'build','category':'factory','kind':'interceptor_ammo','level':1,'region_id':1,'x':10,'y':10})
        self.assertEqual(result['status'],200,result)
        db.session.add_all([ResourceStock(panstwo_id=1,resource='zelazo',quantity=10),ResourceStock(panstwo_id=1,resource='ropa_naftowa',quantity=10)]);db.session.commit()
        with patch('game.industry_service.game_now',return_value=NOW+timedelta(days=1)),patch('game.research_service.game_now',return_value=NOW+timedelta(days=1)):
            read=self.call('game_infrastructure.industry_state:GET')
        self.assertEqual(read['status'],200,read)
        self.assertEqual(db.session.get(ResearchAccount,1,populate_existing=True).ammunition,5)
        self.assertEqual(db.session.get(ResourceStock,(1,'zelazo'),populate_existing=True).quantity,5)

    def test_forum_version_prepared_from_reviewed_form_and_stale_edit_rejected(self):
        self.assertEqual(self.call('game_forum.page:POST',{'content':'Pierwsze stanowisko.'})['status'],303)
        message=db.session.scalar(select(ForumMessage));path={'message_id':message.id}
        self.assertEqual(self.call('game_forum.edit:GET',path=path)['status'],200)
        message.content='Inna zatwierdzona edycja.';db.session.commit()
        stale=self.call('game_forum.edit:POST',{'content':'Poprawione stanowisko.'},path)
        self.assertEqual(stale['status'],409,stale)
        self.assertEqual(self.call('game_forum.edit:GET',path=path)['status'],200)
        result=self.call('game_forum.edit:POST',{'content':'Poprawione stanowisko.'},path)
        self.assertEqual(result['status'],303,result)
        self.assertEqual(db.session.get(ForumMessage,message.id,populate_existing=True).content,'Poprawione stanowisko.')

    def test_counterintelligence_uses_reviewed_level(self):
        from sqlalchemy import text
        from game.intelligence_models import CounterIntelligence
        db.session.execute(text("INSERT INTO game_state_budget_allocations(id,budget_id,category_code,amount) VALUES(98,1,'security_services',1000000000000)"));db.session.commit()
        with patch('game.intelligence_service.game_now',return_value=datetime(2990,1,1)):
            self.assertEqual(self.call('game_intelligence.state:GET')['status'],200)
            result=self.call('game_intelligence.change:POST',{'action':'counter_upgrade'})
        self.assertEqual(result['status'],200,result)
        self.assertEqual(db.session.get(CounterIntelligence,1,populate_existing=True).level,2)

    def test_research_quote_is_server_owned_and_stale_quote_still_fails(self):
        from sqlalchemy import text
        from game.research_models import ResearchExpense
        db.session.execute(text("INSERT INTO game_state_budget_allocations(id,budget_id,category_code,amount) VALUES(99,1,'research',1000000000)"));db.session.commit()
        self.assertEqual(self.call('game_research.change:POST',{'action':'buy','count':1})['status'],400)
        self.assertEqual(self.call('game_research.state:GET')['status'],200)
        with patch('game.research_service.POINT_PRICE',400000001):
            self.assertEqual(self.call('game_research.change:POST',{'action':'buy','count':1})['status'],400)
        self.assertEqual(db.session.query(ResearchExpense).count(),0)
        self.assertEqual(self.call('game_research.change:POST',{'action':'buy','count':1,'expected_point_price':400000000})['status'],400)

    def test_game_has_no_road_or_natural_resources_operations(self):
        """Removed from the game on 10 Nov 2026: road building and the 'Surowce naturalne' module."""
        operations=catalogue(self.app)
        self.assertFalse([name for name in operations if 'roads_' in name or name.startswith('game_resources.')])
        self.assertEqual(self.call('game_infrastructure.roads_change:POST',{},{'operation':'buduj'})['status'],400)
        self.fixture.login(1)
        self.assertEqual(self.fixture.client.get('/game/surowce-naturalne').status_code,404)

    def test_mines_screen_has_kind_filter_like_defense_screen(self):
        from pathlib import Path
        root=Path(__file__).resolve().parents[1]
        self.assertIn('id="industry-mine-filters" class="military-map-filters"',(root/'templates/game/_factories.html').read_text())
        script=(root/'static/js/game_industry.js').read_text()
        self.assertIn('renderMineFilters',script);self.assertIn("if(next==='mine')mineFilter=null",script)
        self.assertNotIn('surowce-naturalne',(root/'templates/game/game_base_layout.html').read_text())

    def test_result_pagination_does_not_repeat_writes_or_expose_other_country_logs(self):
        result=self.call('game_forum.page:POST',{'content':'Tylko jeden wpis.'})
        read=self.call('operations.result',{'id':result['audit_id']})
        self.assertEqual(read['status'],200,read);self.assertEqual(db.session.query(ForumMessage).count(),1)
        rejected=execute(self.app,self.actor,{'operation_id':'game_forum.page:POST','data':{'content':'Duplikat'},'offset':1})
        self.assertEqual(rejected['status'],400);self.assertEqual(db.session.query(ForumMessage).count(),1)
        db.session.add(PagaAiLog(country_id=2,game_at=datetime(2990,1,1),operation='private',parameters={},validation='ACCEPTED',result={'secret':'CUDZA_TAJEMNICA'},model_id='test'));db.session.commit()
        other=db.session.scalar(select(PagaAiLog.id).where(PagaAiLog.country_id==2))
        result=self.call('operations.result',{'id':other});self.assertEqual(result['status'],400);self.assertNotIn('CUDZA_TAJEMNICA',str(result))

    def test_decision_grammar_preserves_all_dispatcher_actions_and_pagination(self):
        from game.player_operations import decision_schema
        schema=decision_schema(catalogue(self.app))
        choices={row['properties']['operation_id']['enum'][0]:row for row in schema['anyOf']}
        self.assertIn('offset',choices['game_trade.change:POST']['properties'])
        self.assertIn('offer',choices['game_trade.change:POST']['properties']['data']['properties']['action']['enum'])
        self.assertIn('request',choices['game_loans.change:POST']['properties']['data']['properties']['action']['enum'])
        self.assertEqual(choices['game_finance.page:GET']['properties']['path']['properties'],{})

    def test_player_map_exposes_only_own_controlled_regions(self):
        geometry={'type':'Polygon','coordinates':[[[0,0],[20,0],[20,20],[0,20],[0,0]]]}
        features=[{'properties':{'region_id':i},'geometry':geometry} for i in (1,2)]
        with patch('game.military_geography.map_features',return_value=features):
            result=self.call('game_player.map_geometry:GET')
        self.assertEqual(result['status'],200,result)
        facts=json.loads(result['observation']['text'])['result']['items']
        self.assertEqual([item['region_id'] for item in facts],[1])

class AiControlTests(unittest.TestCase):
    def setUp(self):
        from test_paga import PagaTests
        self.fixture=PagaTests();self.fixture.setUp();self.app=self.fixture.app;self.client=self.fixture.client
        self.app.config.update(ENV_NAME='UAT',PAGA_AI_CONFIGURED=True)
        for model in [PagaAiControl,PagaAiJob,PagaAiLog,PagaAiMetric,PagaAiPlan,PagaAiProvider]:model.__table__.create(db.engine)
        db.session.add(PagaAiControl(id=1,enabled=False,revision=0));db.session.commit()
        self.fixture.enter();self.headers=self.fixture.headers
    def tearDown(self):self.fixture.tearDown()
    def test_authenticated_persistent_switch_revision_and_csrf_guards(self):
        url='/admin/paga/ai'
        self.assertEqual(self.client.get(url).status_code,403)
        self.assertFalse(self.client.get(url,headers=self.headers).json['enabled'])
        self.assertEqual(self.client.post(url,json={'enabled':True,'revision':0},headers=self.headers).status_code,200)
        db.session.expire_all();self.assertTrue(db.session.get(PagaAiControl,1).enabled)
        self.assertEqual(self.client.post(url,json={'enabled':False,'revision':0},headers=self.headers).status_code,409)
        self.assertEqual(self.client.post(url,json={'enabled':'true','revision':1},headers=self.headers).status_code,400)
        self.assertEqual(self.client.post(url,json={'enabled':False,'revision':1},headers=self.headers).status_code,200)
        self.assertFalse(self.client.get(url,headers=self.headers).json['enabled'])
        self.app.config['ENV_NAME']='PROD'
        self.assertEqual(self.client.get(url,headers=self.headers).status_code,404)
