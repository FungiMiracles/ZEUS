"""Prośba o dołączenie do wojny (12 Nov 2026): sojusznik lub partner strategiczny, zgoda = stan wojny z wrogiem."""
from sqlalchemy import select
from game_features_support import FeatureTestCase
from extensions import db
from game.diplomacy_service import create_action,decide_action,DiplomacyError,joinable_wars
from game.diplomacy_models import DiplomaticAction
from game.forum_models import GameNotification
from models import DictStosunkiRelacja,Stosunki
from test_game_military import NOW


class JoinWarTests(FeatureTestCase):
    def setUp(self):
        super().setUp()
        db.session.add(DictStosunkiRelacja(relacja_id=1,relacja_nazwa='Sojusznicze'))
        db.session.add_all([Stosunki(PANSTWO_ID=1,PANSTWO_ID2=2,relacja_id=1,stan_id=1),Stosunki(PANSTWO_ID=1,PANSTWO_ID2=3,relacja_id=10,stan_id=8)])
        db.session.commit();self.login(1)

    def ask(self,enemy=3,target=2):
        action=create_action(db.session,1,target,'JOIN_WAR',None,NOW,sender_user_id=1,params={'enemy_id':enemy});db.session.commit();return action

    def war(self,a,b):
        db.session.expire_all()
        return db.session.scalar(select(Stosunki.stan_id).where(Stosunki.PANSTWO_ID==min(a,b),Stosunki.PANSTWO_ID2==max(a,b)))==8

    def test_ally_accepts_and_is_at_war_with_enemy(self):
        self.assertEqual(joinable_wars(db.session,1,2),[3])
        action=self.ask()
        self.assertEqual(action.params,{'enemy_id':3,'enemy_name':'Państwo 3'});self.assertEqual(action.status,'PENDING')
        self.login(2);response=self.post(f'/game/dyplomacja/propozycje/{action.id}/decyzja',decision='accept')
        self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(self.war(2,3));self.assertEqual(db.session.get(DiplomaticAction,action.id).status,'ACCEPTED')
        self.assertEqual(db.session.scalar(select(Stosunki.relacja_id).where(Stosunki.PANSTWO_ID==2,Stosunki.PANSTWO_ID2==3)),10)
        self.assertEqual(db.session.scalar(select(Stosunki.relacja_id).where(Stosunki.PANSTWO_ID==1,Stosunki.PANSTWO_ID2==2)),1)   # sojusz bez zmian
        texts=[n.system_text or '' for n in db.session.scalars(select(GameNotification).where(GameNotification.user_id==3))]
        self.assertTrue(any('dołączyło do wojny' in t for t in texts))
        self.assertTrue(db.session.scalar(select(GameNotification.id).where(GameNotification.user_id==1,GameNotification.diplomatic_action_id==action.id)))

    def test_reject_keeps_peace_and_rules(self):
        action=self.ask()
        self.login(2);self.assertEqual(self.post(f'/game/dyplomacja/propozycje/{action.id}/decyzja',decision='reject').status_code,200)
        self.assertFalse(self.war(2,3))
        with self.assertRaises(DiplomacyError):create_action(db.session,1,3,'JOIN_WAR',None,NOW,sender_user_id=1,params={'enemy_id':2})   # nie sojusznik
        with self.assertRaises(DiplomacyError):create_action(db.session,1,2,'JOIN_WAR',None,NOW,sender_user_id=1,params={'enemy_id':4})   # brak takiej wojny
        db.session.rollback()

    def test_expires_when_war_ended(self):
        action=self.ask()
        from sqlalchemy import update
        db.session.execute(update(Stosunki).where(Stosunki.PANSTWO_ID==1,Stosunki.PANSTWO_ID2==3).values(stan_id=1));db.session.commit()
        self.assertEqual(decide_action(db.session,action.id,2,True,NOW,user_id=2),'EXPIRED');db.session.commit()
        self.assertFalse(self.war(2,3))

    def test_map_offers_join_war_and_form_sends_enemy(self):
        response=self.client.get('/game/dyplomacja');self.assertEqual(response.status_code,200)
        self.assertIn('"joinWars": [{"id": 3','\n'.join(response.text.split('\n')) .replace('"joinWars":[{"id":3','"joinWars": [{"id": 3'))
        response=self.post('/game/dyplomacja/akcje',target_id='2',kind='JOIN_WAR',enemy_id='3')
        self.assertEqual(response.status_code,201,response.text)
        html=self.client.get('/game/dyplomacja').text
        self.assertIn('Dołączenie do wojny z państwem Państwo 3',html)
