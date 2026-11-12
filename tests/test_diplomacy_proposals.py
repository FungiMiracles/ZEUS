"""Pending diplomacy proposals under the map reuse the existing decision/notification APIs."""
from flask import template_rendered
from sqlalchemy import select
from game_features_support import FeatureTestCase
from extensions import db
from game.diplomacy_service import create_action
from game.diplomacy_models import DiplomaticAction
from game.forum_models import GameNotification
from models import DictStosunkiRelacja,Stosunki
from test_game_military import NOW


class DiplomacyProposalTests(FeatureTestCase):
    def setUp(self):
        super().setUp();db.session.add(DictStosunkiRelacja(relacja_id=1,relacja_nazwa='Sojusznicze'));db.session.commit();self.login(1)

    def offer(self,source,target,relation=1):
        action=create_action(db.session,source,target,'RELATION',relation,NOW,sender_user_id=source)
        db.session.commit();return action.id

    def test_sent_received_statuses_controls_and_third_country_isolation(self):
        outgoing=self.offer(1,2);incoming=self.offer(3,1);foreign=self.offer(2,3)
        before=db.session.query(GameNotification).count()
        contexts=[]
        def capture(sender,template,context,**kwargs):contexts.append(context)
        with template_rendered.connected_to(capture,self.app):response=self.client.get('/game/dyplomacja')
        self.assertEqual(response.status_code,200)
        self.assertIn('Oczekuje na odpowiedź od Państwo 2',response.text)
        self.assertIn('Państwo 3 oczekuje na Twoją odpowiedź',response.text)
        self.assertEqual({row['id'] for row in contexts[-1]['diplomacy_proposals']},{outgoing,incoming})
        self.assertNotIn(f'data-proposal-id="{foreign}"',response.text)
        self.assertEqual(response.text.count('data-diplomacy-proposal-form'),1)
        self.assertEqual(db.session.query(GameNotification).count(),before)
        self.assertLess(response.text.index('id="game-map-title"') if 'id="game-map-title"' in response.text else response.text.index('id="diplomacy-map"'),response.text.index('id="diplomacy-proposals"'))

    def test_accept_from_card_removes_pending_entry_and_preserves_notification(self):
        id=self.offer(2,1)
        notice=db.session.scalar(select(GameNotification).where(GameNotification.user_id==1));notice_id=notice.id
        response=self.post(f'/game/dyplomacja/propozycje/{id}/decyzja',decision='accept')
        self.assertEqual(response.status_code,200)
        self.assertEqual(db.session.get(DiplomaticAction,id).status,'ACCEPTED')
        self.assertEqual(db.session.scalar(select(Stosunki.relacja_id)),1)
        self.assertNotIn(f'data-proposal-id="{id}"',self.client.get('/game/dyplomacja').text)
        self.assertIsNotNone(db.session.get(GameNotification,notice_id));self.assertIsNone(db.session.get(GameNotification,notice_id).read_at)
        self.assertEqual(self.post(f'/game/dyplomacja/propozycje/{id}/decyzja',decision='reject').status_code,409)

    def test_reject_from_card_and_authorization(self):
        id=self.offer(2,1)
        self.assertEqual(self.client.post(f'/game/dyplomacja/propozycje/{id}/decyzja',data={'decision':'reject'}).status_code,400)
        self.login(3);self.assertEqual(self.post(f'/game/dyplomacja/propozycje/{id}/decyzja',decision='accept').status_code,404)
        self.login(1);self.assertEqual(self.post(f'/game/dyplomacja/propozycje/{id}/decyzja',decision='reject').status_code,200)
        self.assertEqual(db.session.get(DiplomaticAction,id).status,'REJECTED')
        self.assertEqual(db.session.query(Stosunki).count(),0)
        self.assertNotIn(f'data-proposal-id="{id}"',self.client.get('/game/dyplomacja').text)

    def test_sent_proposal_to_npc_is_visible_without_extra_main_notification(self):
        from game.paga import PagaConfiguration,PagaRevision,save_configuration,TRAITS,INTERESTS
        self.app.config['PAGA_ENABLED']=True
        for model in (PagaConfiguration,PagaRevision):model.__table__.create(db.engine)
        save_configuration(db.session,4,{'mode':'approve','revision':0,'autonomyEnabled':True,'character':{key:50 for key in TRAITS},'interests':[{'key':key,'active':key=='survival'} for key in INTERESTS]},'Test');db.session.commit()
        id=self.offer(1,4)
        html=self.client.get('/game/dyplomacja').text
        self.assertIn(f'data-proposal-id="{id}"',html)
        self.assertIn('Oczekuje na odpowiedź od Państwo 4',html)
        self.assertEqual(db.session.query(GameNotification).filter_by(user_id=1).count(),0)
