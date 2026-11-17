"""16 Nov 2026: logowanie do ENTENDA GAME loginem albo adresem e-mail (bez rozróżniania wielkości liter)."""
import unittest
from flask import Flask
from sqlalchemy import Integer
from werkzeug.security import generate_password_hash
from extensions import db
from game.models import GameUser, GameLoginEvent

PASSWORD = 'Haslo#2026'


class LoginIdentifierTests(unittest.TestCase):
    def setUp(self):
        from game.routes_auth import init_game_auth_routes
        self.app = Flask('login-identifier-test'); self.app.config.update(TESTING=True, SECRET_KEY='login-test', SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        db.init_app(self.app)
        self.app.add_url_rule('/entry', 'wejscie', lambda: 'entry')
        init_game_auth_routes(self.app)
        self.ctx = self.app.app_context(); self.ctx.push()
        GameUser.__table__.create(db.engine)
        events = GameLoginEvent.__table__   # BigInteger → Integer dla autoinkrementacji w SQLite
        events.c.id.type = Integer(); events.create(db.engine)
        db.session.add(GameUser(username='Gracz_1', username_normalized='gracz_1', email='Gracz@Example.pl', email_normalized='gracz@example.pl',
                                password_hash=generate_password_hash(PASSWORD), is_active=True)); db.session.commit()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove(); db.engine.dispose(); self.ctx.pop()

    def login(self, identifier, password=PASSWORD):
        with self.client.session_transaction() as browser:browser['game_csrf_token'] = 'token'; browser.pop('game_user_id', None)
        response = self.client.post('/game/logowanie', data={'csrf_token': 'token', 'game_login': identifier, 'game_password': password})
        with self.client.session_transaction() as browser:return response, browser.get('game_user_id')

    def test_login_by_username_or_email_case_insensitive(self):
        for identifier in ('Gracz_1', 'gracz_1', 'gracz@example.pl', '  GRACZ@EXAMPLE.PL '):
            response, user_id = self.login(identifier)
            self.assertEqual((response.status_code, user_id), (303, 1), identifier)

    def test_wrong_password_unknown_email_and_too_long_identifier_fail(self):
        for identifier, password in (('gracz@example.pl', 'zle-haslo'), ('inny@example.pl', PASSWORD), ('a' * 255, PASSWORD)):
            response, user_id = self.login(identifier, password)
            self.assertEqual((response.status_code, user_id), (303, None), identifier)


if __name__ == '__main__':
    unittest.main()
