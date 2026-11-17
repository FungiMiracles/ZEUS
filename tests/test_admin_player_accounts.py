"""16 Nov 2026: panel WIKI — administrator zmienia hasło kont graczy ludzkich (bez kont technicznych PAGA)."""
from sqlalchemy import select
from werkzeug.security import check_password_hash
from game_features_support import FeatureTestCase
from extensions import db
from game.models import GameUser
from game.forum_models import GameNotification


class PlayerAccountsAdminTests(FeatureTestCase):
    def setUp(self):
        super().setUp()
        from routes_civic_admin import wiki_civic_bp
        from game.paga_ai_models import PagaAiIdentity
        self.app.register_blueprint(wiki_civic_bp)
        # Szablon WIKI linkuje do ekranów, których ten test nie rejestruje.
        self.app.url_build_error_handlers.append(lambda error, endpoint, values: '/stub/' + endpoint)
        PagaAiIdentity.__table__.create(db.engine, checkfirst=True)
        db.session.add(PagaAiIdentity(country_id=4, user_id=4, memory='')); db.session.commit()
        with self.client.session_transaction() as browser:
            browser['rola'] = 'wszechmocny'; browser['wiki_civic_csrf'] = 'admin-token'

    def change(self, user_id, password, confirm=None, token='admin-token'):
        return self.client.post(f'/admin/konta-graczy/{user_id}/haslo', data={'csrf_token': token, 'password': password,
                                                                                'password_confirm': password if confirm is None else confirm})

    def test_list_shows_only_human_players_and_requires_admin(self):
        page = self.client.get('/admin/konta-graczy').get_data(as_text=True)
        self.assertIn('Gracz1', page); self.assertIn('Gracz3', page)
        self.assertNotIn('Gracz4', page)                                   # konto techniczne PAGA
        with self.client.session_transaction() as browser:browser['rola'] = 'gosc'
        self.assertEqual(self.client.get('/admin/konta-graczy').status_code, 403)
        self.assertEqual(self.change(1, 'nowe-haslo').status_code, 403)

    def test_password_changed_with_any_characters_and_player_notified(self):
        response = self.change(2, '1@ #Ł!7')
        self.assertEqual(response.status_code, 302)
        user = db.session.get(GameUser, 2); db.session.refresh(user)
        self.assertTrue(check_password_hash(user.password_hash, '1@ #Ł!7'))
        notice = db.session.scalar(select(GameNotification).where(GameNotification.user_id == 2))
        self.assertIn('Administrator zmienił hasło', notice.system_text)
        self.assertIn('Zmieniono hasło gracza Gracz2', self.client.get('/admin/konta-graczy').get_data(as_text=True))

    def test_rejections_leave_password_unchanged(self):
        before = db.session.get(GameUser, 1).password_hash
        self.assertEqual(self.change(1, 'nowe-haslo', token='zly').status_code, 403)          # CSRF
        self.change(1, '123456')                                                              # 6 znaków
        self.assertIn('Hasło musi mieć od 7 do 128 znaków.', self.client.get('/admin/konta-graczy').get_data(as_text=True))
        self.change(1, 'nowe-haslo', 'inne-haslo')
        self.assertIn('Podane hasła nie są identyczne.', self.client.get('/admin/konta-graczy').get_data(as_text=True))
        self.assertEqual(self.change(4, 'nowe-haslo').status_code, 404)                       # konto PAGA
        self.assertEqual(self.change(999, 'nowe-haslo').status_code, 404)
        db.session.expire_all()
        self.assertEqual(db.session.get(GameUser, 1).password_hash, before)
        self.assertIsNone(db.session.scalar(select(GameNotification).where(GameNotification.user_id == 1)))
