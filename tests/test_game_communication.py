from unittest.mock import patch
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from game_features_support import FeatureTestCase
from extensions import db
from game.communication_models import PrivateMessage
from game.models import GameUser
from models import Stosunki


class CommunicationTests(FeatureTestCase):
    def send(self, content='Prywatna wiadomość', recipient=2, **extra):
        return self.post('/game/wiadomosci', content=content, recipient_id=recipient, **extra)

    def test_recipients_length_unicode_and_no_public_forum_copy(self):
        addresses = self.client.get('/game/wiadomosci/adresaci').json['items']
        self.assertEqual({item['id'] for item in addresses}, {2, 3})
        self.assertTrue(all('flag' in item for item in addresses))
        for recipient in [1, 4, 999]:
            self.assertEqual(self.send(recipient=recipient).status_code, 400)
        self.assertEqual(self.send('ą 😀 ' * 750).status_code, 201)
        message = db.session.scalar(select(PrivateMessage))
        self.assertEqual(len(message.content), 3000)
        self.assertEqual(self.send('a' * 3001).status_code, 400)
        self.assertEqual(self.send(' \n ').status_code, 400)
        self.assertEqual(self.send('a' * 2999 + '\r\n').status_code, 201)
        db.session.get(GameUser, 2).is_active = False
        db.session.commit()
        self.assertEqual(self.send().status_code, 400)
        self.assertNotIn(2, {item['id'] for item in self.client.get('/game/wiadomosci/adresaci').json['items']})

    def test_privacy_detail_read_count_and_csrf(self):
        response = self.send('<script>prywatne</script>')
        message_id = response.json['id']
        path = f'/game/wiadomosci/{message_id}'
        self.assertEqual(self.client.get('/game/wiadomosci').json['unread_count'], 0)
        self.assertEqual(self.client.get('/game/wiadomosci?folder=sent').json['items'][0]['id'], message_id)
        self.login(3)
        self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.post(path + '/odczytaj').status_code, 404)
        self.assertEqual(self.client.get('/game/wiadomosci').json['items'], [])
        self.login(2)
        feed = self.client.get('/game/wiadomosci')
        self.assertIn('no-store', feed.headers['Cache-Control'])
        self.assertEqual(feed.json['unread_count'], 1)
        detail = self.client.get(path)
        self.assertEqual(detail.json['message']['content'], '<script>prywatne</script>')
        self.assertEqual(self.client.get('/game/wiadomosci').json['unread_count'], 1)
        self.assertEqual(self.client.post(path + '/odczytaj').status_code, 400)
        self.assertEqual(self.post(path + '/odczytaj').status_code, 200)
        first_read = db.session.get(PrivateMessage, message_id).read_at
        self.assertEqual(self.post(path + '/odczytaj').status_code, 200)
        self.assertEqual(db.session.get(PrivateMessage, message_id).read_at, first_read)
        self.assertEqual(self.client.get('/game/wiadomosci').json['unread_count'], 0)
        self.assertEqual(self.client.delete(path).status_code, 405)

    def test_reply_is_linked_and_cannot_be_spoofed(self):
        original_id = self.send().json['id']
        self.login(2)
        self.assertEqual(self.send(recipient=3, reply_to_id=original_id).status_code, 400)
        reply = self.send('Odpowiedź', recipient=1, reply_to_id=original_id)
        self.assertEqual(reply.status_code, 201)
        row = db.session.get(PrivateMessage, reply.json['id'])
        self.assertEqual(row.reply_to_id, original_id)
        self.assertEqual((row.sender_user_id, row.recipient_user_id), (2, 1))
        self.login(3)
        self.assertEqual(self.send(recipient=1, reply_to_id=original_id).status_code, 404)
        self.login(1)
        self.assertEqual(self.send(recipient=2, reply_to_id=original_id).status_code, 400)

    def test_pagination_current_relation_snapshots_and_rollback(self):
        for number in range(21):
            self.send(str(number))
        self.login(2)
        first = self.client.get('/game/wiadomosci').json
        self.assertEqual(len(first['items']), 20)
        self.assertEqual(first['next_page'], 2)
        self.assertEqual(len(self.client.get('/game/wiadomosci?page=2').json['items']), 1)
        self.assertEqual(first['items'][0]['relation'], 'Neutralne · Pokój')
        db.session.add(Stosunki(PANSTWO_ID=1, PANSTWO_ID2=2, relacja_id=10, stan_id=8))
        db.session.get(GameUser, 1).username = 'Nowy login'
        db.session.commit()
        item = self.client.get('/game/wiadomosci').json['items'][0]
        self.assertEqual(item['relation'], 'Wrogie · Wojna kinetyczna')
        self.assertEqual(item['sender_name'], 'Gracz1')
        self.login(1)
        with patch.object(db.session, 'commit', side_effect=SQLAlchemyError('test failure')):
            self.assertEqual(self.send().status_code, 503)
        self.assertEqual(self.count(PrivateMessage), 21)

    def test_authentication_and_send_csrf(self):
        self.assertEqual(self.client.post('/game/wiadomosci', data={'content': 'Tekst', 'recipient_id': 2}).status_code, 400)
        self.login(4)
        self.assertEqual(self.client.get('/game/wiadomosci').status_code, 403)
        self.login(None)
        self.assertEqual(self.client.get('/game/wiadomosci').status_code, 401)
        self.assertEqual(self.send().status_code, 401)
