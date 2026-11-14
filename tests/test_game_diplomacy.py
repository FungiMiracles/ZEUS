"""Integracja dyplomacji i powiadomień na bazie SQLite w pamięci."""
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask, template_rendered
from sqlalchemy import event, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import lazyload

from extensions import db
from game.infrastructure_models import InfrastructureProject
from game.diplomacy import diplomacy_bp
from game.diplomacy_models import DiplomaticAction
from game.communication import messages_bp
from game.event_models import GeneratedEventSnapshot
from game.forum import forum_bp
from game.forum_models import ForumMessage, GameNotification
from game.models import GameUser, GamePlayerCountry
from game.srodowisko import environment_bp
from models import Panstwo, Region, Stosunki, AudytStosunki, DictStosunkiRelacja, DictStosunkiStan


class DiplomacyTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        self.app = Flask(__name__, template_folder=str(root / 'templates'), static_folder=str(root / 'static'))
        self.app.config.update(TESTING=True, SECRET_KEY='diplomacy-test-only', SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        db.init_app(self.app)
        from routes_region_secession import region_sovereignty_bp
        self.app.register_blueprint(region_sovereignty_bp)
        for blueprint in [diplomacy_bp, forum_bp, environment_bp, messages_bp]:
            self.app.register_blueprint(blueprint)
        for name in ['wejscie', 'game_main_page', 'game_logout', 'game_demography.page']:
            self.app.add_url_rule('/test/' + name, name, lambda: '')
        self.app.add_template_filter(str, 'spacenum')
        self.app.add_template_filter(str, 'game_money')
        self.ctx = self.app.app_context()
        self.ctx.push()
        @event.listens_for(db.engine, 'connect')
        def sqlite_functions(connection, record):
            connection.create_function('CHAR_LENGTH', 1, len)
        db.metadata.create_all(db.engine, tables=[model.__table__ for model in [
            Panstwo, Region, GameUser, GamePlayerCountry, Stosunki, AudytStosunki,
            DictStosunkiRelacja, DictStosunkiStan, DiplomaticAction, ForumMessage, GameNotification, GeneratedEventSnapshot,
        ]])
        InfrastructureProject.__table__.create(db.engine, checkfirst=True)
        from game.intelligence_models import IntelligenceAgent,CounterIntelligence,IntelligenceMission
        for model in (IntelligenceAgent,CounterIntelligence,IntelligenceMission):model.__table__.create(db.engine,checkfirst=True)
        db.session.add_all([
            *[Panstwo(PANSTWO_ID=i, panstwo_nazwa=f'Państwo {i}') for i in range(1, 5)],
            *[GameUser(id=i, username=f'Gracz{i}', username_normalized=f'gracz{i}',
                       email=f'{i}@test', email_normalized=f'{i}@test', password_hash='test') for i in range(1, 4)],
            *[GamePlayerCountry(user_id=i, panstwo_id=i) for i in range(1, 4)],
            DictStosunkiRelacja(relacja_id=6, relacja_nazwa='Neutralne'),
            DictStosunkiRelacja(relacja_id=10, relacja_nazwa='Wrogie'),
            DictStosunkiRelacja(relacja_id=1, relacja_nazwa='Sojusznicze'),
            DictStosunkiStan(stan_id=1, stan_nazwa='Pokój'),
            DictStosunkiStan(stan_id=8, stan_nazwa='Wojna kinetyczna'),
            DictStosunkiStan(stan_id=2, stan_nazwa='Zawieszenie broni'),
        ])
        db.session.commit()
        self.client = self.app.test_client()
        self.login(1)

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.ctx.pop()

    def login(self, user_id):
        with self.client.session_transaction() as browser:
            browser['game_user_id'] = user_id
            browser['game_csrf_token'] = 'token'

    def post(self, path, **data):
        return self.client.post(path, data={'csrf_token': 'token', **data}, headers={'Accept': 'application/json'})

    def create(self, kind, **data):
        return self.post('/game/dyplomacja/akcje', kind=kind, target_id=2, **data)

    def hostile(self,commit=True):
        db.session.add(Stosunki(PANSTWO_ID=1,PANSTWO_ID2=2,relacja_id=10,stan_id=1));db.session.flush()
        if commit:db.session.commit()

    def action(self):
        return db.session.scalar(select(DiplomaticAction).order_by(DiplomaticAction.id.desc()))

    def relation(self):
        return db.session.scalar(select(Stosunki).where(Stosunki.PANSTWO_ID == 1, Stosunki.PANSTWO_ID2 == 2).options(lazyload('*')))

    def count(self, model):
        return db.session.scalar(select(func.count()).select_from(model))

    def decide(self, action_id, decision='accept'):
        return self.post(f'/game/dyplomacja/propozycje/{action_id}/decyzja', decision=decision)

    def test_map_default_relations_and_inactive_or_unassigned_targets(self):
        contexts = []
        def capture(sender, template, context, **kwargs):
            contexts.append(context)
        with template_rendered.connected_to(capture, self.app):
            response = self.client.get('/game/dyplomacja')
        self.assertEqual(response.status_code, 200)
        data = contexts[-1]['diplomacy_map']['countries']
        self.assertTrue(data['1']['own'])
        self.assertFalse(data['2']['canWar'])
        self.assertEqual(data['2']['relation'], 'Neutralne')
        self.assertTrue(data['4']['canAct'])
        self.assertEqual(self.post('/game/dyplomacja/akcje', kind='WAR', target_id=4).status_code, 409)
        self.assertEqual(self.post('/game/dyplomacja/akcje', kind='WAR', target_id=1).status_code, 400)
        self.assertEqual(self.count(DiplomaticAction), 0)
        self.assertEqual(self.count(AudytStosunki), 0)

    def test_war_is_immediate_audited_and_notification_opens_modal(self):
        self.hostile()
        self.assertEqual(self.create('WAR').status_code, 201)
        action = self.action()
        self.assertEqual(action.status, 'APPLIED')
        self.assertEqual(self.relation().stan_id, 8)
        self.assertEqual(self.count(AudytStosunki), 1)
        audit = db.session.scalar(select(AudytStosunki))
        self.assertEqual((audit.panstwo_id, audit.panstwo_id2, audit.relacja_id, audit.stan_id), (1, 2, 10, 8))
        self.assertIsNotNone(audit.data_zmiany_entenda)
        self.assertIsNotNone(audit.data_zmiany_rzeczywista)
        self.assertEqual(self.create('WAR').status_code, 409)
        self.assertEqual(self.count(GameNotification), 1)
        self.login(2)
        feed = self.client.get('/game/forum/powiadomienia').json
        self.assertEqual(feed['unread_count'], 1)
        self.assertIn('Państwo 1 wypowiada wojnę Twojemu krajowi', feed['items'][0]['text'])
        dialog = self.post(feed['items'][0]['open_url'])
        self.assertEqual(dialog.status_code, 200)
        self.assertFalse(dialog.json['dialog']['can_decide'])
        self.assertEqual(self.client.get('/game/forum/powiadomienia').json['unread_count'], 0)
        self.assertEqual(self.decide(action.id).status_code, 409)

    def test_peace_requires_acceptance_and_cannot_be_replayed(self):
        self.hostile()
        self.create('WAR')
        self.assertEqual(self.create('PEACE').status_code, 201)
        action_id = self.action().id
        self.assertEqual(self.relation().stan_id, 8)
        self.assertEqual(self.create('PEACE').status_code, 409)
        self.assertEqual(self.decide(action_id).status_code, 404)
        self.login(2)
        self.assertEqual(self.decide(action_id).status_code, 200)
        self.assertEqual(self.relation().stan_id, 1)
        self.assertEqual(self.count(AudytStosunki), 2)
        self.assertEqual(self.decide(action_id).status_code, 409)
        self.assertEqual(self.count(AudytStosunki), 2)

    def test_ceasefire_and_rejection(self):
        self.hostile()
        self.assertEqual(self.create('CEASEFIRE').status_code, 409)
        self.create('WAR')
        self.create('CEASEFIRE')
        first = self.action().id
        self.login(2)
        self.assertEqual(self.decide(first, 'reject').status_code, 200)
        self.assertEqual(self.relation().stan_id, 8)
        self.assertEqual(self.count(AudytStosunki), 1)
        self.login(1)
        self.assertEqual(self.create('CEASEFIRE').status_code, 201)
        self.login(2)
        self.assertEqual(self.decide(self.action().id).status_code, 200)
        self.assertEqual(self.relation().stan_id, 2)
        self.assertEqual(self.count(AudytStosunki), 2)

    def test_sender_is_notified_when_player_answers_any_proposal(self):
        # 14 Nov 2026: odpowiedź gracza (przyjęcie lub odrzucenie) trafia do panelu powiadomień nadawcy.
        from game.forum_models import GameNotification
        from game.diplomacy import notification_text
        self.hostile()
        self.create('WAR')
        self.create('PEACE')
        peace = self.action()
        self.login(2)
        self.assertEqual(self.decide(peace.id, 'reject').status_code, 200)
        notice = db.session.scalar(select(GameNotification).where(GameNotification.user_id == 1, GameNotification.diplomatic_action_id == peace.id))
        self.assertIsNotNone(notice)
        db.session.refresh(peace)
        self.assertIn('odrzuciło Twoją propozycję zawarcia pokoju', notification_text(peace, 1))
        self.login(1)
        self.create('CEASEFIRE')
        ceasefire = self.action()
        self.login(2)
        self.assertEqual(self.decide(ceasefire.id).status_code, 200)
        self.assertIsNotNone(db.session.scalar(select(GameNotification).where(GameNotification.user_id == 1, GameNotification.diplomatic_action_id == ceasefire.id)))

    def test_relation_proposal_and_stale_proposal(self):
        self.assertEqual(self.create('RELATION', relation_id=6).status_code, 400)
        self.assertEqual(self.create('RELATION', relation_id=999).status_code, 400)
        self.assertEqual(self.create('RELATION', relation_id=1).status_code, 201)
        action_id = self.action().id
        self.assertIsNone(self.relation())
        self.login(2)
        notice = self.client.get('/game/forum/powiadomienia').json['items'][0]
        dialog = self.post(notice['open_url']).json['dialog']
        self.assertTrue(dialog['can_decide'])
        self.assertEqual(dialog['relation'], 'Sojusznicze')
        self.assertEqual(self.decide(action_id).status_code, 200)
        self.assertEqual(self.relation().relacja_id, 1)
        self.login(1)
        self.create('RELATION', relation_id=10)
        self.assertEqual(self.action().status,'APPLIED')
        self.create('RELATION',relation_id=6)
        old_id = self.action().id
        self.create('WAR')
        self.login(2)
        self.assertEqual(self.decide(old_id).status_code, 409)
        old = db.session.get(DiplomaticAction, old_id)
        self.assertEqual(old.status, 'EXPIRED')
        self.assertEqual(self.relation().relacja_id, 10)

    def test_competing_peace_and_ceasefire_and_assignment_change(self):
        self.hostile()
        self.create('WAR')
        self.create('PEACE')
        peace_id = self.action().id
        self.create('CEASEFIRE')
        ceasefire_id = self.action().id
        self.login(2)
        self.assertEqual(self.decide(peace_id).status_code, 200)
        self.assertEqual(self.decide(ceasefire_id).status_code, 409)
        self.login(1)
        self.create('RELATION', relation_id=1)
        action_id = self.action().id
        assignment = db.session.scalar(select(GamePlayerCountry).where(GamePlayerCountry.user_id == 1))
        assignment.panstwo_id = 4
        db.session.commit()
        self.login(2)
        self.assertEqual(self.decide(action_id).status_code, 409)

    def test_csrf_authorization_and_rollback(self):
        self.assertEqual(self.client.post('/game/dyplomacja/akcje', data={'kind': 'WAR', 'target_id': 2}).status_code, 400)
        self.hostile(commit=False)
        with patch.object(db.session, 'commit', side_effect=SQLAlchemyError('test failure')):
            self.assertEqual(self.create('WAR').status_code, 503)
        for model in [Stosunki, AudytStosunki, DiplomaticAction, GameNotification]:
            self.assertEqual(self.count(model), 0)
        self.create('RELATION', relation_id=1)
        action_id = self.action().id
        notice_id = db.session.scalar(select(GameNotification.id))
        self.login(3)
        self.assertEqual(self.decide(action_id).status_code, 404)
        self.assertEqual(self.post(f'/game/forum/powiadomienia/{notice_id}/otworz').status_code, 404)
        self.login(2)
        self.assertEqual(self.client.post(f'/game/dyplomacja/propozycje/{action_id}/decyzja', data={'decision': 'accept'}).status_code, 400)
        with self.client.session_transaction() as browser:
            browser.clear()
        self.assertEqual(self.client.get('/game/dyplomacja').status_code, 302)
        self.assertEqual(self.create('WAR').status_code, 401)


    def test_paga_marker_uses_approved_configuration_only(self):
        from game.paga import PagaConfiguration,PagaRevision,TRAITS,INTERESTS,save_configuration
        self.app.config['PAGA_ENABLED']=True
        for model in (PagaConfiguration,PagaRevision):model.__table__.create(db.engine,checkfirst=True)
        payload={'mode':'draft','revision':0,'character':{key:None for key in TRAITS},'interests':[{'key':key,'active':False} for key in INTERESTS]}
        save_configuration(db.session,2,payload,'Test');db.session.commit()
        contexts=[]
        def capture(sender,template,context,**kwargs):contexts.append(context)
        with template_rendered.connected_to(capture,self.app):self.client.get('/game/dyplomacja')
        self.assertFalse(contexts[-1]['diplomacy_map']['countries']['2']['pagaConfigured'])
        payload.update(mode='approve',revision=1,character={key:0 for key in TRAITS});payload['interests'][0]['active']=True
        save_configuration(db.session,2,payload,'Test');db.session.commit()
        with template_rendered.connected_to(capture,self.app):self.client.get('/game/dyplomacja')
        self.assertTrue(contexts[-1]['diplomacy_map']['countries']['2']['pagaConfigured'])
        payload.update(mode='draft',revision=2);payload['character']['ambition']=None
        save_configuration(db.session,2,payload,'Test');db.session.commit()
        with template_rendered.connected_to(capture,self.app):self.client.get('/game/dyplomacja')
        self.assertTrue(contexts[-1]['diplomacy_map']['countries']['2']['pagaConfigured'])


if __name__ == '__main__':
    unittest.main()
