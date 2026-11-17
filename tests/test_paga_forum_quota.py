"""16 Nov 2026: globalny dobowy limit wpisów PAGA na forum międzynarodowym (30 / 24 h); po wyczerpaniu wyłącznie
odpowiedzi na wpisy graczy ludzkich. Gracze ludzcy nie podlegają limitowi."""
import unittest
from datetime import date, timedelta
from extensions import db
from game.forum_models import ForumMessage
from game.models import utc_now
from game.paga_forum_quota import GLOBAL_DAILY_LIMIT, LIMIT_MESSAGE
import test_game_forum   # import modułu (nie klasy), aby testy forum nie uruchamiały się tu drugi raz


class PagaForumQuotaTests(unittest.TestCase):
    tearDown = test_game_forum.ForumTests.tearDown
    login = test_game_forum.ForumTests.login
    post = test_game_forum.ForumTests.post
    message = test_game_forum.ForumTests.message

    def setUp(self):
        test_game_forum.ForumTests.setUp(self)
        from game.paga_forum_quota import _READY
        _READY.clear()
        from game.paga_ai_models import PagaAiIdentity
        PagaAiIdentity.__table__.create(db.engine, checkfirst=True)
        db.session.add(PagaAiIdentity(country_id=2, user_id=2, memory='')); db.session.commit()   # państwo 2 — PAGA

    def ai_posts(self, count, hours_ago=1):
        when = utc_now() - timedelta(hours=hours_ago)
        db.session.add_all([ForumMessage(user_id=2, panstwo_id=2, author_name='Drugi', country_name='Drugie Państwo', flag_path='f',
                                         content=f'Wpis AI {i}', entenda_date=date(3010, 1, 1), created_at=when) for i in range(count)])
        db.session.commit()

    def test_ai_public_posts_blocked_after_limit_but_old_posts_do_not_count(self):
        self.ai_posts(GLOBAL_DAILY_LIMIT - 1); self.ai_posts(50, hours_ago=25)
        self.login(2)
        self.assertEqual(self.post('Zapowiedź PAGA').status_code, 303)            # 30. wpis w dobie — jeszcze dozwolony
        response = self.post('Kolejna zapowiedź PAGA')
        self.assertEqual(response.status_code, 429)
        self.assertIn(LIMIT_MESSAGE.split(' (')[0], response.get_data(as_text=True))

    def test_reply_to_human_allowed_reply_to_ai_blocked_and_humans_unlimited(self):
        self.ai_posts(GLOBAL_DAILY_LIMIT)
        self.login(1)
        self.assertEqual(self.post('Wpis gracza').status_code, 303)               # gracz ludzki — bez limitu
        human = self.message()
        self.login(2)
        self.assertEqual(self.post('Odpowiedź PAGA graczowi', reply_to_id=str(human.id)).status_code, 303)
        ai_post = db.session.query(ForumMessage).filter_by(user_id=2).order_by(ForumMessage.id).first()
        self.login(1)
        self.assertEqual(self.post('Gracz odpowiada AI', reply_to_id=str(ai_post.id)).status_code, 303)
        db.session.add(ForumMessage(user_id=1, panstwo_id=1, author_name='Autor', country_name='Państwo Testowe', flag_path='f',
                                    content='x', entenda_date=date(3010, 1, 1), created_at=utc_now()))
        from game.paga_forum_quota import blocked
        self.assertEqual(blocked(db.session, 2, ai_post), LIMIT_MESSAGE)              # PAGA odpowiada PAGA — zablokowane
        self.assertIsNone(blocked(db.session, 1, None))


if __name__ == '__main__':
    unittest.main()


class AvalancheTests(unittest.TestCase):
    """16 Nov 2026 — naprawa lawiny: reakcje PAGA na wpisy z powiadomień FORUM_MESSAGE."""
    tearDown = test_game_forum.ForumTests.tearDown
    login = test_game_forum.ForumTests.login

    def setUp(self):
        test_game_forum.ForumTests.setUp(self)
        from game.paga_ai_models import PagaAiIdentity
        PagaAiIdentity.__table__.create(db.engine, checkfirst=True)
        db.session.add_all([PagaAiIdentity(country_id=2, user_id=2, memory=''), PagaAiIdentity(country_id=3, user_id=3, memory='')]); db.session.commit()
        self.ai = {2, 3}

    def post(self, user, reply_to=None, to=None):
        from game.forum_models import ForumMessageRecipient
        message = ForumMessage(user_id=user, panstwo_id=user, author_name=f'U{user}', country_name='K', flag_path='f', content='x',
                               entenda_date=date(3010, 1, 1), created_at=utc_now(), reply_to_id=reply_to.id if reply_to else None,
                               recipient_user_id=to)
        db.session.add(message); db.session.flush()
        if to:db.session.add(ForumMessageRecipient(message_id=message.id, user_id=to, name='n', country_name='k', flag_path='f'))
        db.session.commit(); return message

    def allowed(self, message, user, country):
        from game.paga_forum_quota import reaction_allowed
        db.session.refresh(message)
        return reaction_allowed(db.session, message, user, country, self.ai, [2, 3])

    def test_ai_ignores_public_ai_posts_and_chains_end_after_one_exchange(self):
        public = self.post(3)
        self.assertFalse(self.allowed(public, 2, 2))                      # publiczny wpis innej AI — bez reakcji
        addressed = self.post(3, to=2)
        self.assertTrue(self.allowed(addressed, 2, 2))                    # skierowany do nas
        answer = self.post(2, reply_to=addressed, to=3)
        self.assertTrue(self.allowed(answer, 3, 3))                       # odpowiedź na nasz wpis
        again = self.post(3, reply_to=answer, to=2)
        self.assertFalse(self.allowed(again, 2, 2))                       # trzecie ogniwo AI–AI — koniec łańcucha
        self.assertFalse(self.allowed(answer, 2, 2))                      # własny wpis

    def test_human_posts_addressed_always_public_only_limited_countries(self):
        from game.paga_forum_quota import public_reactors, PUBLIC_REACTIONS
        self.assertTrue(self.allowed(self.post(1, to=2), 2, 2))
        public = self.post(1)
        countries = list(range(2, 40))
        chosen = public_reactors(public.id, countries)
        self.assertEqual(len(chosen), PUBLIC_REACTIONS); self.assertEqual(chosen, public_reactors(public.id, countries))
        from game.paga_forum_quota import reaction_allowed
        self.assertEqual({c for c in countries if reaction_allowed(db.session, public, 1000 + c, c, self.ai, countries)}, chosen)
