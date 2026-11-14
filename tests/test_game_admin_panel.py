"""Przycisk „Panel administratora” w pasku gry: hasło roli → sesja ZEUS WIKI (14 Nov 2026)."""
import unittest
from unittest.mock import patch
from flask import Flask
import routes_auth

PASSWORDS = {'wszechmocny': 'test-all', 'tworzyciel': 'test-create', 'obserwator': 'test-view'}


class AdminPanelTests(unittest.TestCase):
    def setUp(self):
        self.patch = patch.dict(routes_auth.HASLA_ROLE, PASSWORDS, clear=True)
        self.patch.start()
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY='admin-panel-test')
        app.add_url_rule('/home', 'home_page', lambda: 'wiki')
        routes_auth.init_auth_routes(app)
        self.client = app.test_client()
        with self.client.session_transaction() as browser:
            browser['game_user_id'] = 1
            browser['game_csrf_token'] = 'token'

    def tearDown(self):
        self.patch.stop()

    def post(self, password, token='token'):
        return self.client.post('/game/panel-administratora', data={'haslo': password, 'csrf_token': token})

    def role(self):
        with self.client.session_transaction() as browser:
            return browser.get('rola')

    def test_password_selects_matching_role_and_redirects_to_wiki(self):
        response = self.post('test-create')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['redirect'], '/home')
        self.assertEqual(self.role(), 'tworzyciel')

    def test_wrong_password_csrf_and_logged_out_player_are_rejected(self):
        self.assertEqual(self.post('zle').status_code, 403)
        self.assertEqual(self.post('test-all', token='zly').status_code, 400)
        self.assertIsNone(self.role())
        with self.client.session_transaction() as browser:
            browser.pop('game_user_id')
        self.assertEqual(self.post('test-all').status_code, 401)
        self.assertIsNone(self.role())

    def test_lockout_after_five_failures(self):
        for _ in range(5):
            self.assertEqual(self.post('zle').status_code, 403)
        response = self.post('test-all')
        self.assertEqual(response.status_code, 429)
        self.assertIsNone(self.role())


if __name__ == '__main__':
    unittest.main()
