"""Player and NPC diplomacy enforce identical war and unilateral pact rules."""
from unittest.mock import patch
from flask import template_rendered
from sqlalchemy import select,delete
from sqlalchemy.orm import lazyload
from game_features_support import FeatureTestCase
from extensions import db
from models import Stosunki,DictStosunkiRelacja,DictStosunkiStan,AudytStosunki
from game.models import GamePlayerCountry
from game.paga import PagaConfiguration,PagaRevision,save_configuration,TRAITS,INTERESTS
from game.diplomacy_models import DiplomaticAction
from game.diplomacy_service import create_action,DiplomacyError
from game.forum_models import GameNotification
from test_game_military import NOW

RELATIONS={1:'Sojusznicze',2:'Partnerskie strategiczne',3:'Partnerskie',4:'Dobre',5:'Przyjazne',6:'Neutralne',7:'Chłodne',8:'Złe',9:'Napięte',10:'Wrogie',11:'Egzystencjalnie wrogie'}


class DiplomacyRuleTests(FeatureTestCase):
    def setUp(self):
        super().setUp();self.login(1)
        for id,name in RELATIONS.items():
            if db.session.get(DictStosunkiRelacja,id) is None:db.session.add(DictStosunkiRelacja(relacja_id=id,relacja_nazwa=name))
        for id,name in [(9,'Wojna informacyjna'),(10,'Wojna hybrydowa'),(11,'Wojna kinetyczna (zamrożone)'),(12,'Okupacja')]:db.session.add(DictStosunkiStan(stan_id=id,stan_nazwa=name))
        db.session.commit()

    def pair(self,relation,state=1):
        row=db.session.scalar(select(Stosunki).options(lazyload('*')).where(Stosunki.PANSTWO_ID==1,Stosunki.PANSTWO_ID2==2))
        if row is None:row=Stosunki(PANSTWO_ID=1,PANSTWO_ID2=2);db.session.add(row)
        row.relacja_id=relation;row.stan_id=state;db.session.commit();return row

    def npc(self):
        self.app.config['PAGA_ENABLED']=True
        for model in (PagaConfiguration,PagaRevision):model.__table__.create(db.engine)
        db.session.execute(delete(GamePlayerCountry).where(GamePlayerCountry.panstwo_id==1))
        save_configuration(db.session,1,{'mode':'approve','revision':0,'autonomyEnabled':True,'character':{key:50 for key in TRAITS},'interests':[{'key':key,'active':key=='survival'} for key in INTERESTS]},'Test');db.session.commit()

    def test_war_relation_and_state_matrix_for_player_and_npc(self):
        for npc in (False,True):
            if npc:self.npc()
            for relation in RELATIONS:
                for state in (1,2,8,9,10,11,12):
                    with self.subTest(npc=npc,relation=relation,state=state):
                        self.pair(relation,state)
                        if relation in (8,9,10,11) and state!=8:
                            create_action(db.session,1,2,'WAR',None,NOW,sender_user_id=None if npc else 1,npc=npc,dry_run=True)
                        else:
                            with self.assertRaises(DiplomacyError):create_action(db.session,1,2,'WAR',None,NOW,sender_user_id=None if npc else 1,npc=npc,dry_run=True)
        self.assertEqual(db.session.query(DiplomaticAction).count(),0)
        self.assertEqual(db.session.query(AudytStosunki).count(),0)

    def test_all_three_pacts_can_be_replaced_unilaterally_with_every_nonpact(self):
        for npc in (False,True):
            if npc:self.npc()
            for current in (1,2,3):
                for proposed in range(4,12):
                    with self.subTest(npc=npc,current=current,proposed=proposed):
                        row=self.pair(current,10)
                        action=create_action(db.session,1,2,'RELATION',proposed,NOW,sender_user_id=None if npc else 1,npc=npc)
                        db.session.commit();self.assertEqual(action.status,'APPLIED')
                        self.assertEqual(tuple(db.session.execute(select(Stosunki.relacja_id,Stosunki.stan_id).where(Stosunki.PANSTWO_ID==1,Stosunki.PANSTWO_ID2==2)).one()),(proposed,10))
                        self.assertIsNotNone(action.decided_at)
                        self.assertTrue(db.session.scalar(select(GameNotification.id).where(GameNotification.diplomatic_action_id==action.id)))

    def test_immediate_break_expires_old_offer_and_notification_needs_no_acceptance(self):
        self.pair(3)
        self.assertEqual(self.post('/game/dyplomacja/akcje',kind='RELATION',target_id=2,relation_id=2).status_code,201)
        old=db.session.scalar(select(DiplomaticAction))
        self.assertEqual(old.status,'PENDING')
        result=self.post('/game/dyplomacja/akcje',kind='RELATION',target_id=2,relation_id=9)
        self.assertEqual(result.status_code,201);self.assertIn('Jednostronnie',result.json['message'])
        db.session.refresh(old);self.assertEqual(old.status,'EXPIRED')
        self.login(2)
        feed=self.client.get('/game/forum/powiadomienia').json
        notice=next(item for item in feed['items'] if 'jednostronnie' in item['text'])
        dialog=self.post(notice['open_url']).json['dialog']
        self.assertFalse(dialog['can_decide']);self.assertEqual(dialog['relation'],'Napięte')
        self.assertIn('jednostronnie',dialog['status'])

    def test_player_can_escalate_information_war_when_relation_is_tense(self):
        self.pair(9,9)
        response=self.post('/game/dyplomacja/akcje',kind='WAR',target_id=2)
        self.assertEqual(response.status_code,201)
        self.assertEqual(db.session.scalar(select(Stosunki.stan_id)),8)
        self.assertEqual(db.session.scalar(select(DiplomaticAction.status)),'APPLIED')

    def test_unilateral_actions_do_not_need_a_player_or_enabled_npc_recipient(self):
        db.session.add(Stosunki(PANSTWO_ID=1,PANSTWO_ID2=4,relacja_id=3,stan_id=1));db.session.commit()
        response=self.post('/game/dyplomacja/akcje',kind='RELATION',target_id=4,relation_id=10)
        self.assertEqual(response.status_code,201)
        self.assertEqual(self.post('/game/dyplomacja/akcje',kind='WAR',target_id=4).status_code,201)
        self.assertEqual(db.session.query(DiplomaticAction).filter_by(target_country_id=4,status='APPLIED').count(),2)

    def test_map_flags_follow_shared_rules_even_during_information_war(self):
        contexts=[]
        def capture(sender,template,context,**kwargs):contexts.append(context)
        with template_rendered.connected_to(capture,self.app):
            self.pair(9,9);self.assertEqual(self.client.get('/game/dyplomacja').status_code,200)
            self.assertTrue(contexts[-1]['diplomacy_map']['countries']['2']['canWar'])
            self.pair(1,1);self.client.get('/game/dyplomacja')
            data=contexts[-1]['diplomacy_map']
            self.assertFalse(data['countries']['2']['canWar']);self.assertTrue(data['countries']['2']['pact'])
            self.assertEqual(set(data['pactRelations']),{1,2,3})

    def test_unilateral_break_rollback_preserves_pact_and_pending_offer(self):
        self.pair(3)
        old=create_action(db.session,1,2,'RELATION',2,NOW,sender_user_id=1);db.session.commit()
        with patch.object(db.session,'commit',side_effect=RuntimeError('simulated failure')):
            action=create_action(db.session,1,2,'RELATION',9,NOW,sender_user_id=1)
            try:db.session.commit()
            except RuntimeError:db.session.rollback()
        self.assertEqual(db.session.get(DiplomaticAction,old.id).status,'PENDING')
        self.assertEqual(db.session.scalar(select(Stosunki.relacja_id)),3)

    def test_every_relation_pair_uses_quality_and_not_pact_membership(self):
        # Explicit product order, independent of dictionary IDs.
        worst_to_best=[11,10,9,8,7,6,4,5,3,2,1]
        for current in worst_to_best:
            for proposed in worst_to_best:
                if current==proposed:continue
                with self.subTest(current=current,proposed=proposed):
                    self.pair(current)
                    for pending in db.session.scalars(select(DiplomaticAction).where(DiplomaticAction.status=='PENDING')):pending.status='EXPIRED'
                    db.session.commit()
                    action=create_action(db.session,1,2,'RELATION',proposed,NOW,sender_user_id=1)
                    db.session.commit()
                    worsening=worst_to_best.index(proposed)<worst_to_best.index(current)
                    self.assertEqual(action.status,'APPLIED' if worsening else 'PENDING')
                    self.assertEqual(db.session.scalar(select(Stosunki.relacja_id)),proposed if worsening else current)
                    self.assertIsNotNone(db.session.scalar(select(GameNotification.id).where(GameNotification.diplomatic_action_id==action.id)))

    def test_nonpact_worsening_notification_cannot_be_accepted(self):
        self.pair(6)
        response=self.post('/game/dyplomacja/akcje',kind='RELATION',target_id=2,relation_id=7)
        self.assertEqual(response.status_code,201)
        action=db.session.scalar(select(DiplomaticAction))
        self.login(2)
        feed=self.client.get('/game/forum/powiadomienia').json
        notice=next(item for item in feed['items'] if 'jednostronnie' in item['text'])
        self.assertFalse(self.post(notice['open_url']).json['dialog']['can_decide'])
        self.assertEqual(self.post(f'/game/dyplomacja/propozycje/{action.id}/decyzja',decision='accept').status_code,409)

    def test_cold_to_tense_for_paga_country_is_immediate(self):
        self.pair(7)
        self.app.config['PAGA_ENABLED']=True
        for model in (PagaConfiguration,PagaRevision):model.__table__.create(db.engine)
        db.session.execute(delete(GamePlayerCountry).where(GamePlayerCountry.panstwo_id==2))
        save_configuration(db.session,2,{'mode':'approve','revision':0,'autonomyEnabled':True,'character':{key:50 for key in TRAITS},'interests':[{'key':key,'active':key=='survival'} for key in INTERESTS]},'Test')
        db.session.commit()
        response=self.post('/game/dyplomacja/akcje',kind='RELATION',target_id=2,relation_id=9)
        self.assertEqual(response.status_code,201)
        self.assertEqual(db.session.scalar(select(DiplomaticAction.status)),'APPLIED')
        self.assertEqual(db.session.scalar(select(Stosunki.relacja_id)),9)
        self.assertEqual(db.session.query(DiplomaticAction).filter_by(status='PENDING').count(),0)
