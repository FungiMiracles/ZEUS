"""Account removal on isolated worlds: erasure, authorization, history and PAGA handover."""
from datetime import date
from unittest.mock import patch
from sqlalchemy import select
from werkzeug.security import generate_password_hash
from game_features_support import FeatureTestCase
from extensions import db
from game.account import account_bp,delete_account,AccountDeletionError
from game.models import GameUser,GamePlayerCountry
from game.paga import PagaConfiguration,PagaRevision,save_configuration,TRAITS,INTERESTS
from game.autonomy_models import AutonomyControl,AutonomySchedule
from game.autonomy_engine import eligible_ids
from game.diplomacy_service import create_action
from game.diplomacy_models import DiplomaticAction
from game.forum_models import ForumMessage
from models import Region
from test_game_military import NOW

PASSWORD='TestoweHaslo123!'


class AccountTests(FeatureTestCase):
    def setUp(self):
        super().setUp()
        self.app.config.update(ENV_NAME='UAT',PAGA_ENABLED=True,AUTONOMY_ENABLED=True)
        self.app.register_blueprint(account_bp)
        self.app.context_processor(lambda:{'game_csrf_token':'token'})
        for model in (PagaConfiguration,PagaRevision,AutonomySchedule,AutonomyControl):model.__table__.create(db.engine,checkfirst=True)
        user=db.session.get(GameUser,1);user.password_hash=generate_password_hash(PASSWORD)
        self.payload={'mode':'approve','revision':0,'autonomyEnabled':False,'character':{key:50 for key in TRAITS},'interests':[{'key':key,'active':key=='survival'} for key in INTERESTS]}
        self.clock=patch('game.finance_service.game_now',return_value=NOW);self.clock.start();self.addCleanup(self.clock.stop)
        db.session.commit()
        with self.client.session_transaction() as session:session.update(game_user_id=1,game_csrf_token='token')

    def submit(self,password=PASSWORD,csrf='token'):
        return self.client.post('/game/konto/usun',data={'csrf_token':csrf,'password':password})

    def test_two_step_confirmation_and_password_form(self):
        first=self.client.get('/game/konto/usun')
        self.assertEqual(first.status_code,200)
        self.assertIn('Czy jesteś pewien, że chcesz usunąć konto?',first.text)
        self.assertNotIn('name="password"',first.text)
        second=self.client.get('/game/konto/usun?confirm=1')
        self.assertIn('type="password"',second.text);self.assertIn('Usuń konto',second.text)
        self.assertTrue(db.session.get(GameUser,1).is_active)

    def test_csrf_and_incorrect_password_leave_account_untouched(self):
        self.assertEqual(self.submit(csrf='wrong').status_code,400)
        response=self.submit(password='wrong')
        self.assertEqual(response.status_code,400);self.assertIn('Nieprawidłowe hasło',response.text)
        db.session.expire_all();self.assertTrue(db.session.get(GameUser,1).is_active)
        self.assertEqual(db.session.get(GameUser,1).email,'1@test')
        self.assertIsNotNone(db.session.scalar(select(GamePlayerCountry.id).where(GamePlayerCountry.user_id==1)))

    def test_erases_credentials_releases_country_and_preserves_history_and_state(self):
        save_configuration(db.session,1,self.payload,'Test')
        db.session.get(Region,1).region_stan_infra_energetycznej=47
        post=ForumMessage(user_id=1,panstwo_id=1,author_name='Gracz1',country_name='Państwo 1',flag_path='flag.jpg',content='Wpis historyczny',entenda_date=date(2990,1,1))
        db.session.add(post)
        from models import DictStosunkiRelacja
        db.session.add(DictStosunkiRelacja(relacja_id=1,relacja_nazwa='Sojusznicze'));db.session.flush()
        proposal=create_action(db.session,1,2,'RELATION',1,NOW,sender_user_id=1)
        db.session.commit();post_id=post.id;proposal_id=proposal.id
        counts={table:db.session.execute(select(db.metadata.tables[table])).all() for table in ('game_state_budgets','game_state_budget_allocations')}
        response=self.submit();self.assertEqual(response.status_code,303)
        db.session.expire_all();user=db.session.get(GameUser,1)
        self.assertFalse(user.is_active)
        self.assertIsNone(user.email);self.assertIsNone(user.email_normalized);self.assertIsNone(user.password_hash)
        self.assertIsNone(db.session.scalar(select(GamePlayerCountry.id).where(GamePlayerCountry.user_id==1)))
        self.assertEqual(db.session.get(ForumMessage,post_id).content,'Wpis historyczny')
        self.assertEqual(db.session.get(DiplomaticAction,proposal_id).status,'EXPIRED')
        self.assertEqual(db.session.get(DiplomaticAction,proposal_id).sender_user_id,1)
        self.assertEqual(db.session.get(Region,1).region_stan_infra_energetycznej,47)
        for table,rows in counts.items():self.assertEqual(db.session.execute(select(db.metadata.tables[table])).all(),rows)
        self.assertIn(1,eligible_ids(db.session))
        self.assertIsNotNone(db.session.get(AutonomySchedule,1))
        with self.client.session_transaction() as session:self.assertNotIn('game_user_id',session)
        # A previously signed session cannot restore access to this inactive historical identity.
        with self.client.session_transaction() as session:session['game_user_id']=1
        self.assertEqual(self.client.get('/game/forum').status_code,302)

    def test_only_approved_configuration_can_enable_autonomy_and_draft_survives(self):
        draft={**self.payload,'mode':'draft'}
        save_configuration(db.session,1,draft,'Test');db.session.commit()
        self.assertEqual(self.submit().status_code,303);db.session.expire_all()
        self.assertFalse(db.session.get(PagaConfiguration,1).autonomy_enabled)
        self.assertNotIn(1,eligible_ids(db.session))
        self.assertIsNone(db.session.get(AutonomySchedule,1))

    def test_approved_handover_preserves_draft_and_global_pause(self):
        save_configuration(db.session,1,self.payload,'Test')
        save_configuration(db.session,1,{**self.payload,'mode':'draft','revision':1,'character':{key:99 for key in TRAITS}},'Test')
        db.session.add(AutonomyControl(id=1,enabled=False,started_at=NOW));db.session.commit()
        self.assertEqual(self.submit().status_code,303);db.session.expire_all()
        config=db.session.get(PagaConfiguration,1)
        self.assertTrue(config.autonomy_enabled)
        self.assertEqual(config.approved_character['ambition'],50)
        self.assertEqual(config.draft_character['ambition'],99)
        self.assertFalse(db.session.get(AutonomyControl,1).enabled)
        self.assertEqual(db.session.scalar(select(PagaRevision).where(PagaRevision.revision==3)).mode,'handover')

    def test_handover_enables_paga2_profile(self):
        from game.paga2.models import Paga2Profile,Paga2ProfileRevision
        from game.diplomacy_service import npc_eligible
        for model in (Paga2Profile,Paga2ProfileRevision):model.__table__.create(db.engine,checkfirst=True)
        save_configuration(db.session,1,self.payload,'Test');db.session.commit()
        self.assertEqual(self.submit().status_code,303);db.session.expire_all()
        profile=db.session.get(Paga2Profile,1)
        self.assertTrue(profile.autonomy_enabled);self.assertEqual(profile.source,'migrated');self.assertEqual(profile.actor,'Przekazanie po usunięciu konta')
        self.assertTrue(db.session.scalar(select(Paga2ProfileRevision).where(Paga2ProfileRevision.panstwo_id==1)).configuration['handover'])
        self.assertTrue(npc_eligible(db.session,1))

    def test_handover_switches_on_existing_paga2_profile_without_legacy_configuration(self):
        from game.paga2.models import Paga2Profile,Paga2ProfileRevision
        from game.paga2 import catalog
        for model in (Paga2Profile,Paga2ProfileRevision):model.__table__.create(db.engine,checkfirst=True)
        db.session.add(Paga2Profile(panstwo_id=1,categories=['economic'],priorities=['trade'],traits={k:50 for k in catalog.TRAITS},autonomy_enabled=False,source='admin',revision=1,actor='admin'))
        db.session.commit()
        self.assertEqual(self.submit().status_code,303);db.session.expire_all()
        profile=db.session.get(Paga2Profile,1)
        self.assertTrue(profile.autonomy_enabled);self.assertEqual(profile.revision,2)

    def test_missing_configuration_still_allows_account_deletion(self):
        self.assertEqual(self.submit().status_code,303)
        self.assertIsNone(db.session.get(PagaConfiguration,1));self.assertNotIn(1,eligible_ids(db.session))

    def test_email_can_be_reused_but_deleted_identity_cannot_be_used_again(self):
        self.assertEqual(self.submit().status_code,303)
        db.session.add(GameUser(username='NowyGracz',username_normalized='nowygracz',email='1@test',email_normalized='1@test',password_hash=generate_password_hash(PASSWORD)))
        db.session.commit()
        self.assertEqual(db.session.scalar(select(GameUser.username).where(GameUser.email_normalized=='1@test')),'NowyGracz')
        with self.assertRaises(AccountDeletionError):delete_account(db.session,1,PASSWORD)

    def test_login_with_erased_hash_fails_normally(self):
        from flask import Flask
        from game.routes_auth import init_game_auth_routes
        login_app=Flask('account-login-test');login_app.config.update(TESTING=True,SECRET_KEY='isolated-login',SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        db.init_app(login_app)
        login_app.add_url_rule('/entry','wejscie',lambda:'entry')
        init_game_auth_routes(login_app)
        with login_app.app_context():
            GameUser.__table__.create(db.engine)
            db.session.add(GameUser(username='Usuniety',username_normalized='usuniety',email=None,email_normalized=None,password_hash=None,is_active=False));db.session.commit()
            client=login_app.test_client()
            with client.session_transaction() as session:session['game_csrf_token']='token'
            response=client.post('/game/logowanie',data={'csrf_token':'token','game_login':'Usuniety','game_password':PASSWORD})
            self.assertEqual(response.status_code,303)
            with client.session_transaction() as session:self.assertNotIn('game_user_id',session)
            db.session.remove();db.engine.dispose()

    def test_anonymous_and_production_requests_cannot_delete(self):
        self.app.config['ENV_NAME']='PROD'
        self.assertEqual(self.submit().status_code,404)
        self.app.config['ENV_NAME']='UAT'
        with self.client.session_transaction() as session:session.clear()
        self.assertEqual(self.submit().status_code,303)
        self.assertTrue(db.session.get(GameUser,1).is_active)

    def test_handover_error_rolls_back_erasure_and_assignment(self):
        save_configuration(db.session,1,self.payload,'Test');db.session.commit()
        with patch('game.finance_service.game_now',side_effect=RuntimeError('test failure')):
            with self.assertRaises(RuntimeError):delete_account(db.session,1,PASSWORD)
        db.session.rollback();db.session.expire_all()
        self.assertEqual(db.session.get(GameUser,1).email,'1@test')
        self.assertTrue(db.session.get(GameUser,1).is_active)
        self.assertIsNotNone(db.session.scalar(select(GamePlayerCountry.id).where(GamePlayerCountry.user_id==1)))
