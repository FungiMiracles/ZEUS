"""Testy forum na izolowanej bazie SQLite w pamięci, bez uruchamiania aplikacji i schedulerów."""
import unittest
from unittest.mock import patch
from sqlalchemy.exc import SQLAlchemyError
from datetime import date, datetime
from pathlib import Path

from flask import Flask, session
from sqlalchemy import event, select, func
from sqlalchemy.orm import lazyload

from extensions import db
from game.infrastructure_models import InfrastructureProject
from game.communication import messages_bp
from game.event_models import GeneratedEventSnapshot
from game.forum import forum_bp, real_date
from game.srodowisko import environment_bp
from game.diplomacy import diplomacy_bp
from game.diplomacy_models import DiplomaticAction
from game.forum_models import ForumMessage, ForumMessageRecipient, GameNotification
from game.models import GameUser, GamePlayerCountry
from models import Panstwo, Region


class ForumTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        self.app = Flask(__name__, template_folder=str(root / 'templates'), static_folder=str(root / 'static'))
        self.app.config.update(TESTING=True, SECRET_KEY='forum-test-only', SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        db.init_app(self.app)
        self.app.register_blueprint(forum_bp)
        self.app.register_blueprint(messages_bp)
        self.app.register_blueprint(environment_bp)
        self.app.register_blueprint(diplomacy_bp)
        for endpoint in ['wejscie', 'game_main_page', 'game_logout']:
            self.app.add_url_rule('/test/' + endpoint, endpoint, lambda: '')
        self.app.add_url_rule('/test/demography', 'game_demography.page', lambda: '')
        self.app.add_template_filter(lambda value: str(value), 'spacenum')
        self.app.add_template_filter(lambda value: str(value), 'game_money')

        @self.app.context_processor
        def context():
            return dict(game_csrf_token=session.get('game_csrf_token', ''), ENTENDA_DATE='01.01.3010', ENTENDA_DATETIME='3010-01-01T00:00:00')

        self.ctx = self.app.app_context()
        self.ctx.push()
        @event.listens_for(db.engine, 'connect')
        def sqlite_functions(connection, record):
            connection.create_function('CHAR_LENGTH', 1, len)
        # Tylko tabele potrzebne forum. Żadnych połączeń z MySQL.
        db.metadata.create_all(db.engine, tables=[Panstwo.__table__, Region.__table__, GameUser.__table__, GamePlayerCountry.__table__, ForumMessage.__table__, ForumMessageRecipient.__table__, GameNotification.__table__, DiplomaticAction.__table__, GeneratedEventSnapshot.__table__])
        InfrastructureProject.__table__.create(db.engine, checkfirst=True)
        from game.intelligence_models import IntelligenceAgent,CounterIntelligence,IntelligenceMission
        for model in (IntelligenceAgent,CounterIntelligence,IntelligenceMission):model.__table__.create(db.engine,checkfirst=True)
        db.session.add_all([
            Panstwo(PANSTWO_ID=1, panstwo_nazwa='Państwo Testowe'),
            Panstwo(PANSTWO_ID=2, panstwo_nazwa='Drugie Państwo'),
            GameUser(id=1, username='Autor', username_normalized='autor', email='a@test', email_normalized='a@test', password_hash='test'),
            GameUser(id=2, username='Drugi', username_normalized='drugi', email='b@test', email_normalized='b@test', password_hash='test'),
            GameUser(id=3, username='Bez państwa', username_normalized='bez', email='c@test', email_normalized='c@test', password_hash='test'),
            GamePlayerCountry(user_id=1, panstwo_id=1), GamePlayerCountry(user_id=2, panstwo_id=2),
        ])
        db.session.commit()
        self.client = self.app.test_client()
        self.login()

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.ctx.pop()

    def login(self, user=1):
        with self.client.session_transaction() as browser:
            browser['game_user_id'] = user
            browser['game_csrf_token'] = 'test-token'

    def post(self, content, path='/game/forum', **extra):
        return self.client.post(path, data=dict(content=content, csrf_token='test-token', **extra))

    def message(self):
        return db.session.scalar(select(ForumMessage).order_by(ForumMessage.id.desc()))

    def test_page_publish_and_escape(self):
        self.assertEqual(self.client.get('/game/forum').status_code, 200)
        self.assertEqual(self.post('<script>alert(1)</script>\nPolskie ąę').status_code, 303)
        message = self.message()
        self.assertEqual(message.author_name, 'Autor')
        self.assertEqual(message.country_name, 'Państwo Testowe')
        self.assertEqual(message.flag_path, 'flags/Państwo_Testowe.jpg')
        self.assertIsInstance(message.entenda_date, date)
        page = self.client.get('/game/forum').get_data(as_text=True)
        self.assertIn('&lt;script&gt;', page)
        self.assertNotIn('<script>alert(1)</script>', page)
        self.assertIn('Data rzeczywista (Polska)', page)

    def test_limit_unicode_spaces_and_newlines(self):
        self.assertEqual(self.post('ą 😀 ' * 250).status_code, 303)
        self.assertEqual(len(self.message().content), 1000)
        self.assertEqual(self.post('a' * 1001).status_code, 400)
        self.assertEqual(self.post(' ' * 10 + '\n').status_code, 400)
        self.assertEqual(self.post('a' * 999 + '\r\n').status_code, 303)
        self.assertEqual(len(self.message().content), 1000)

    def test_edit_preserves_metadata_and_rejects_stale_version(self):
        self.post('Pierwotna treść')
        message = self.message()
        path = f'/game/forum/{message.id}/edytuj'
        original = (message.created_at, message.entenda_date, message.author_name, message.country_name, message.flag_path)
        self.assertEqual(self.client.get(path).status_code, 200)
        self.assertEqual(self.post('Poprawiona', path, version='1').status_code, 303)
        db.session.refresh(message)
        self.assertEqual(message.content, 'Poprawiona')
        self.assertEqual(message.version, 2)
        self.assertIsNotNone(message.edited_at)
        self.assertEqual(original, (message.created_at, message.entenda_date, message.author_name, message.country_name, message.flag_path))
        self.assertEqual(self.post('Nadpisanie', path, version='1').status_code, 409)
        self.assertEqual(self.post('x' * 1001, path, version='2').status_code, 400)
        self.assertEqual(self.message().content, 'Poprawiona')
        self.assertIn('Edytowano:', self.client.get('/game/forum').get_data(as_text=True))

    def test_other_author_and_delete_forbidden(self):
        self.post('Własna wiadomość')
        message = self.message()
        self.login(2)
        path = f'/game/forum/{message.id}/edytuj'
        self.assertEqual(self.client.get(path).status_code, 403)
        self.assertEqual(self.post('Cudza edycja', path, version='1').status_code, 403)
        self.assertEqual(self.client.delete(f'/game/forum/{message.id}').status_code, 405)
        self.assertEqual(self.client.delete(path).status_code, 405)
        self.assertEqual(self.message().content, 'Własna wiadomość')

    def test_access_and_csrf(self):
        self.assertEqual(self.client.post('/game/forum', data={'content': 'Bez CSRF'}).status_code, 400)
        self.post('Treść')
        path = f'/game/forum/{self.message().id}/edytuj'
        self.assertEqual(self.client.post(path, data={'content': 'Zmiana', 'version': '1'}).status_code, 400)
        self.login(3)
        self.assertEqual(self.client.get('/game/forum').status_code, 403)
        self.login(True)
        self.assertEqual(self.client.get('/game/forum').status_code, 302)
        self.login(1)
        user = db.session.get(GameUser, 1)
        user.is_active = False
        db.session.commit()
        self.assertEqual(self.client.get('/game/forum').status_code, 302)
        with self.client.session_transaction() as browser:
            browser.clear()
        self.assertEqual(self.post('Niezalogowany').status_code, 302)

    def test_pagination_newest_first(self):
        for index in range(21):
            self.post(f'Wpis numer {index:02}')
        first = self.client.get('/game/forum').get_data(as_text=True)
        second = self.client.get('/game/forum?page=2').get_data(as_text=True)
        self.assertIn('Wpis numer 20', first)
        self.assertNotIn('Wpis numer 00', first)
        self.assertIn('Wpis numer 00', second)
        self.assertLess(first.index('Wpis numer 20'), first.index('Wpis numer 19'))
        self.assertEqual(db.session.scalar(select(func.count()).select_from(ForumMessage)), 21)

    def test_author_snapshot_survives_renaming(self):
        self.post('Historyczny podpis')
        user = db.session.get(GameUser, 1)
        country = db.session.scalar(select(Panstwo).where(Panstwo.PANSTWO_ID == 1).options(lazyload("*")))
        user.username = 'Nowy login'
        country.panstwo_nazwa = 'Nowa nazwa państwa'
        db.session.commit()
        page = self.client.get('/game/forum').get_data(as_text=True)
        message = self.message()
        self.assertEqual(message.author_name, 'Autor')
        self.assertEqual(message.country_name, 'Państwo Testowe')
        self.assertIn('Historyczny podpis', page)
        self.assertEqual(message.flag_path, 'flags/Państwo_Testowe.jpg')

    def test_recipient_picker_and_public_addressed_message(self):
        page = self.client.get('/game/forum').get_data(as_text=True)
        self.assertIn('name="recipient_id" value="2"', page)
        self.assertNotIn('name="recipient_id" value="1"', page)
        self.assertNotIn('name="recipient_id" value="3"', page)
        self.assertIn('flags/Drugie_Pa%C5%84stwo.jpg', page)
        self.assertEqual(self.post('Do konkretnego gracza', recipient_id='2').status_code, 303)
        message = self.message()
        self.assertEqual(message.recipient_user_id, 2)
        self.assertEqual(message.recipient_name, 'Drugi')
        self.assertEqual(message.recipient_country_name, 'Drugie Państwo')
        self.login(2)
        self.assertIn('Do konkretnego gracza', self.client.get('/game/forum').get_data(as_text=True))
        db.session.get(GameUser, 2).username = 'Nowy adresat'
        db.session.commit()
        self.assertEqual(self.message().recipient_name, 'Drugi')
        db.session.add(Panstwo(PANSTWO_ID=3, panstwo_nazwa='Trzecie Państwo'))
        db.session.add(GamePlayerCountry(user_id=3, panstwo_id=3))
        db.session.commit()
        self.login(3)
        self.assertIn('Do konkretnego gracza', self.client.get('/game/forum').get_data(as_text=True))

    def test_invalid_recipients_and_error_preserves_selection(self):
        for recipient_id in ['1', '3', '9999', 'niewłaściwy', '-2']:
            self.assertEqual(self.post('Treść', recipient_id=recipient_id).status_code, 400)
        self.assertIsNone(self.message())
        page = self.post('x' * 1001, recipient_id='2')
        self.assertEqual(page.status_code, 400)
        self.assertIn('value="2" checked', page.get_data(as_text=True))
        db.session.get(GameUser, 2).is_active = False
        db.session.commit()
        self.assertEqual(self.post('Treść', recipient_id='2').status_code, 400)
        self.assertNotIn('name="recipient_id" value="2"', self.client.get('/game/forum').get_data(as_text=True))

    def source_message(self):
        self.login(2)
        self.post('Oryginalna wiadomość')
        source_id = self.message().id
        self.login(1)
        return source_id

    def test_reply_sets_author_as_recipient_and_preserves_context_on_error(self):
        source_id = self.source_message()
        page = self.client.get(f'/game/forum?reply_to_id={source_id}').get_data(as_text=True)
        self.assertIn(f'name="reply_to_id" value="{source_id}"', page)
        self.assertIn('Oryginalna wiadomość', page)
        self.assertIn('obowiązkowym adresatem odpowiedzi', page)
        failure = self.post('x' * 1001, reply_to_id=str(source_id))
        self.assertEqual(failure.status_code, 400)
        self.assertIn(f'name="reply_to_id" value="{source_id}"', failure.get_data(as_text=True))
        # Próba podmiany adresata formularzem nie zmienia autora wiadomości źródłowej.
        self.assertEqual(self.post('Odpowiedź', reply_to_id=str(source_id), recipient_id='1').status_code, 400)
        self.assertEqual(self.post('Odpowiedź', reply_to_id=str(source_id), recipient_id='2').status_code, 303)
        message = self.message()
        self.assertEqual(message.reply_to_id, source_id)
        self.assertEqual(message.recipient_user_id, 2)
        page = self.client.get('/game/forum').get_data(as_text=True)
        self.assertIn('W odpowiedzi na wiadomość: Drugi', page)
        self.assertIn(f'href="/game/forum/{source_id}"', page)

    def test_invalid_reply_self_reply_and_reply_csrf(self):
        self.post('Własna')
        self.assertEqual(self.post('Do siebie', reply_to_id=str(self.message().id)).status_code, 400)
        for reply_id, code in [('nie-id', 400), ('999999999999', 400), ('9999', 404)]:
            self.assertEqual(self.post('Treść', reply_to_id=reply_id).status_code, code)
        source_id = self.source_message()
        response = self.client.post('/game/forum', data={'content': 'Bez CSRF', 'reply_to_id': source_id})
        self.assertEqual(response.status_code, 400)
        db.session.get(GameUser, 2).is_active = False
        db.session.commit()
        self.assertEqual(self.post('Nieaktywny autor', reply_to_id=str(source_id)).status_code, 400)

    def test_reply_edit_cannot_change_recipient_or_source(self):
        source_id = self.source_message()
        self.post('Odpowiedź', reply_to_id=str(source_id))
        message = self.message()
        response = self.post('Poprawiona odpowiedź', f'/game/forum/{message.id}/edytuj',
                             version='1', recipient_id='3', reply_to_id='9999')
        self.assertEqual(response.status_code, 303)
        db.session.refresh(message)
        self.assertEqual(message.content, 'Poprawiona odpowiedź')
        self.assertEqual(message.recipient_user_id, 2)
        self.assertEqual(message.reply_to_id, source_id)
        self.assertEqual(message.recipient_name, 'Drugi')

    def test_permalink_finds_source_on_older_page(self):
        source_id = self.source_message()
        for index in range(20):
            self.post(f'Nowsza wiadomość {index}')
        self.post('Odpowiedź do starszej', reply_to_id=str(source_id))
        response = self.client.get(f'/game/forum/{source_id}')
        self.assertEqual(response.status_code, 302)
        self.assertIn(f'page=2#message-{source_id}', response.location)
        self.assertIn('Oryginalna wiadomość', self.client.get(response.location).get_data(as_text=True))
        # Podgląd źródła działa także na pierwszej stronie.
        self.assertIn('Oryginalna wiadomość', self.client.get('/game/forum').get_data(as_text=True))

    def assign_third_player(self):
        db.session.add(Panstwo(PANSTWO_ID=3, panstwo_nazwa='Trzecie Państwo'))
        db.session.add(GamePlayerCountry(user_id=3, panstwo_id=3))
        db.session.commit()

    def test_multiple_recipients_deduplicate_and_notify_only_addressees(self):
        self.assign_third_player()
        self.assertEqual(self.post('Wielu adresatów', recipient_id=['2', '3', '2']).status_code, 303)
        message = self.message()
        self.assertEqual({item.user_id for item in message.addressees}, {2, 3})
        notices = db.session.scalars(select(GameNotification).where(GameNotification.message_id == message.id)).all()
        self.assertEqual({item.user_id for item in notices}, {2, 3})
        self.assertEqual(len(notices), 2)
        page = self.client.get('/game/forum').get_data(as_text=True)
        self.assertIn('Drugie Państwo · Drugi', page)
        self.assertIn('Trzecie Państwo · Bez państwa', page)
        self.assertIn('type="checkbox"', page)
        failed = self.post('x' * 1001, recipient_id=['2', '3'])
        self.assertEqual(failed.status_code, 400)
        self.assertIn('value="2" checked', failed.get_data(as_text=True))
        self.assertIn('value="3" checked', failed.get_data(as_text=True))
        self.login(2)
        self.assertEqual(self.client.get('/game/forum/powiadomienia').json['unread_count'], 1)

    def test_broadcast_notifies_active_assigned_players_only(self):
        self.post('Do wszystkich')
        message = self.message()
        notices = db.session.scalars(select(GameNotification).where(GameNotification.message_id == message.id)).all()
        self.assertEqual([item.user_id for item in notices], [2])
        self.assertEqual(message.addressees, [])
        self.assertIsNone(message.recipient_user_id)
        self.assertEqual(self.client.get('/game/forum/powiadomienia').json['unread_count'], 0)
        db.session.get(GameUser, 2).is_active = False
        db.session.commit()
        self.post('Brak aktywnych odbiorców')
        self.assertEqual(db.session.scalar(select(func.count()).select_from(GameNotification)), 1)

    def test_reply_mandatory_recipient_and_optional_addressees(self):
        self.assign_third_player()
        source_id = self.source_message()
        self.assertEqual(self.post('Odpowiedź dla dwóch', reply_to_id=str(source_id), recipient_id=['3']).status_code, 303)
        message = self.message()
        self.assertEqual({item.user_id for item in message.addressees}, {2, 3})
        notices = db.session.scalars(select(GameNotification).where(GameNotification.message_id == message.id)).all()
        self.assertEqual({item.user_id for item in notices}, {2, 3})
        notice_count = db.session.scalar(select(func.count()).select_from(GameNotification))
        self.post('Edytowana odpowiedź', f'/game/forum/{message.id}/edytuj', version='1', recipient_id=['3'])
        db.session.refresh(message)
        self.assertEqual({item.user_id for item in message.addressees}, {2, 3})
        self.assertEqual(db.session.scalar(select(func.count()).select_from(GameNotification)), notice_count)

    def test_notification_read_ownership_csrf_and_old_message_destination(self):
        self.post('Adresowana', recipient_id='2')
        first_message = self.message().id
        for index in range(20):
            self.post(f'Nowszy wpis {index}', recipient_id='2')
        notice = db.session.scalar(select(GameNotification).where(GameNotification.message_id == first_message))
        path = f'/game/forum/powiadomienia/{notice.id}/otworz'
        # Autor nie może odczytać cudzego powiadomienia.
        self.assertEqual(self.post('', path).status_code, 404)
        self.login(2)
        feed = self.client.get('/game/forum/powiadomienia')
        self.assertEqual(feed.json['unread_count'], 21)
        self.assertEqual(len(feed.json['items']), 20)
        self.assertEqual(feed.json['next_page'], 2)
        self.assertIn('no-store', feed.headers['Cache-Control'])
        ids = [item['id'] for item in feed.json['items']]
        self.assertEqual(ids, sorted(ids, reverse=True))
        self.assertTrue(all(item['received_at'] for item in feed.json['items']))
        self.assertEqual(self.client.get('/game/forum/powiadomienia?page=2').json['items'][0]['id'], notice.id)
        self.assertIsNone(notice.read_at)
        self.assertEqual(self.client.get(path).status_code, 405)
        self.assertEqual(self.client.post(path).status_code, 400)
        response = self.post('', path)
        self.assertEqual(response.status_code, 303)
        destination = self.client.get(response.location)
        self.assertIn(f'page=2#message-{first_message}', destination.location)
        db.session.refresh(notice)
        read_at = notice.read_at
        self.assertIsNotNone(read_at)
        self.assertEqual(self.client.get('/game/forum/powiadomienia').json['unread_count'], 20)
        self.post('', path)
        db.session.refresh(notice)
        self.assertEqual(notice.read_at, read_at)
        self.assertEqual(self.client.get('/game/forum/powiadomienia').json['unread_count'], 20)

    def test_notifications_require_active_authenticated_player(self):
        with self.client.session_transaction() as browser:
            browser.clear()
        self.assertEqual(self.client.get('/game/forum/powiadomienia').status_code, 401)
        self.login(1)
        db.session.get(GameUser, 1).is_active = False
        db.session.commit()
        self.assertEqual(self.client.get('/game/forum/powiadomienia').status_code, 401)

    def test_publication_and_notifications_rollback_together(self):
        with patch.object(db.session, 'commit', side_effect=SQLAlchemyError('test failure')):
            response = self.post('Niekompletny zapis', recipient_id='2')
        self.assertEqual(response.status_code, 503)
        for model in [ForumMessage, ForumMessageRecipient, GameNotification]:
            self.assertEqual(db.session.scalar(select(func.count()).select_from(model)), 0)

    def test_country_summary_infrastructure_matches_forum_header(self):
        from game.country_summary import country_summary
        db.session.add_all([
            Region(region_id=1, panstwo_id=1, region_nazwa='Śródlądowy',
                   region_polozenie_id=1, region_stan_infra_kolejowej=0,
                   region_stan_infra_drogowej=100, region_stan_infra_portowej=100),
            Region(region_id=2, panstwo_id=1, region_nazwa='Nadmorski',
                   region_polozenie_id=2, region_stan_infra_energetycznej=50,
                   region_stan_infra_portowej=50),
            Region(region_id=3, panstwo_id=2, region_nazwa='Obcy',
                   region_polozenie_id=2, region_stan_infra_drogowej=100),
        ])
        db.session.commit()
        country = db.session.scalar(select(Panstwo).where(Panstwo.PANSTWO_ID == 1).options(lazyload('*')))
        with self.app.test_request_context():
            self.assertEqual(country_summary(country)['infrastruktura'], 50.0)
        page = self.client.get('/game/forum').get_data(as_text=True)
        self.assertIn('50.0 / 100', page)
        self.assertIn('ROI to waluta Ozilandii, największego gospodarczo kraju świata.', page if country.panstwo_PKB is not None else self.header_with_gdp(country))

    def header_with_gdp(self, country):
        country.panstwo_PKB = 1000
        db.session.commit()
        return self.client.get('/game/forum').get_data(as_text=True)

    def test_country_summary_missing_infrastructure_and_zero_population(self):
        from game.country_summary import country_summary
        db.session.add(Region(region_id=1, panstwo_id=1, region_nazwa='Bez danych'))
        db.session.commit()
        country = db.session.scalar(select(Panstwo).where(Panstwo.PANSTWO_ID == 1).options(lazyload('*')))
        country.panstwo_populacja = 0
        country.panstwo_PKB = 1000
        with self.app.test_request_context():
            summary = country_summary(country)
            self.assertIsNone(summary['infrastruktura'])
            self.assertIsNone(summary['pkb_per_capita'])
            self.assertIsNone(country_summary(None)['infrastruktura'])

    def test_real_date_timezone(self):
        self.assertEqual(real_date(datetime(2026, 10, 23, 12)), '23.10.2026 14:00:00')
        self.assertEqual(real_date(datetime(2026, 1, 23, 12)), '23.01.2026 13:00:00')

    def test_removed_ai_recipients_are_rejected_and_author_stays_human(self):
        self.assertNotIn('value="paga:',self.client.get('/game/forum').text)
        self.assertEqual(self.post('Wpis do nieistniejącego adresata AI',recipient_id='paga:2').status_code,400)
        self.assertIsNone(self.message())
        self.assertEqual(self.post('Zwykły wpis gracza',author_kind='PAGA',user_id='2',author_name='Państwo (PAGA)').status_code,303)
        self.assertEqual(self.message().user_id,1)
        self.assertEqual(self.message().author_name,'Autor')


if __name__ == '__main__':
    unittest.main()
