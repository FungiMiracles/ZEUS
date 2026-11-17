"""Third-party world news: delivery, secrecy, read isolation, idempotence and real rules."""
from sqlalchemy import select
from sqlalchemy.orm import lazyload
from game_features_support import FeatureTestCase
from extensions import db
from game.diplomacy_news import NewsControl,NewsBaseline,NewsEvent,NewsNotice,collect
from game.diplomacy_service import create_action,decide_action,apply_change
from game.forum_models import GameNotification
from game.models import GameUser
from models import Stosunki,DictStosunkiRelacja,AudytStosunki
from test_game_military import NOW


class DiplomacyNewsTests(FeatureTestCase):
    def setUp(self):
        super().setUp();self.app.config.update(ENV_NAME='UAT',DIPLOMACY_NEWS_ENABLED=True)
        for model in (NewsControl,NewsBaseline,NewsEvent,NewsNotice):model.__table__.create(db.engine)
        db.session.add(NewsControl(id=1,audit_start=0,action_start=0))
        db.session.add(DictStosunkiRelacja(relacja_id=1,relacja_nazwa='Sojusznicze'))
        db.session.commit();self.login(3)

    def war(self):
        db.session.add(Stosunki(PANSTWO_ID=1,PANSTWO_ID2=2,relacja_id=10,stan_id=1));db.session.commit()
        action=create_action(db.session,1,2,'WAR',None,NOW,sender_user_id=1);db.session.commit();return action

    def test_war_start_and_end_reach_main_and_separate_panel_only_third_parties(self):
        self.war()
        main=self.client.get('/game/forum/powiadomienia').json
        self.assertEqual(len(main['items']),1);self.assertEqual(main['items'][0]['severity'],'war')
        self.assertIn('rozpoczęła się wojna',main['items'][0]['text'])
        news=self.client.get('/game/dyplomacja/wiadomosci-swiatowe').json
        self.assertEqual(news['unread_count'],1);self.assertEqual(news['items'][0]['kind'],'WAR_STARTED')
        self.assertEqual([flag['name'] for flag in news['items'][0]['flags']],['Państwo 1','Państwo 2'])
        self.assertTrue(all(flag['url'].startswith('/static/flags/') for flag in news['items'][0]['flags']))
        peace=create_action(db.session,1,2,'PEACE',None,NOW,sender_user_id=1);db.session.flush()
        decide_action(db.session,peace.id,2,True,NOW,user_id=2);db.session.commit()
        main=self.client.get('/game/forum/powiadomienia').json
        self.assertEqual(len(main['items']),2);self.assertIn('została zakończona',main['items'][0]['text']);self.assertEqual(main['items'][0]['severity'],'info')
        self.login(1);self.assertEqual(self.client.get('/game/dyplomacja/wiadomosci-swiatowe').json['items'],[])
        self.login(2);self.assertEqual(self.client.get('/game/dyplomacja/wiadomosci-swiatowe').json['items'],[])

    def test_private_pending_and_acceptance_vs_rejection(self):
        proposal=create_action(db.session,1,2,'RELATION',1,NOW,sender_user_id=1);db.session.commit()
        self.assertEqual(db.session.query(NewsEvent).count(),0)
        self.assertEqual(self.client.get('/game/dyplomacja/wiadomosci-swiatowe').json['items'],[])
        decide_action(db.session,proposal.id,2,False,NOW,user_id=2);db.session.commit()
        item=self.client.get('/game/dyplomacja/wiadomosci-swiatowe').json['items'][0]
        self.assertEqual(item['kind'],'PROPOSAL_REJECTED');self.assertIn('Sojusznicze',item['text'])
        self.assertEqual([flag['name'] for flag in item['flags']],['Państwo 2','Państwo 1'])
        self.assertEqual(db.session.query(GameNotification).filter_by(user_id=3).count(),0)
        proposal=create_action(db.session,1,2,'RELATION',1,NOW,sender_user_id=1);db.session.flush()
        decide_action(db.session,proposal.id,2,True,NOW,user_id=2);db.session.commit()
        self.assertEqual(self.client.get('/game/dyplomacja/wiadomosci-swiatowe').json['items'][0]['kind'],'RELATION_CHANGED')

    def test_collector_handles_wiki_changes_once_and_retains_baseline(self):
        db.session.add(NewsBaseline(a=1,b=2,relation=10,state=8))
        db.session.add(AudytStosunki(panstwo_id=1,panstwo_id2=2,relacja_id=10,stan_id=1,data_zmiany_entenda=NOW,data_zmiany_rzeczywista=NOW));db.session.commit()
        collect(db.session,NOW);db.session.commit();collect(db.session,NOW);db.session.commit()
        self.assertEqual(db.session.query(NewsEvent).count(),1)
        self.assertEqual(db.session.scalar(select(NewsEvent.kind)),'WAR_ENDED')
        self.assertEqual(db.session.query(NewsNotice).count(),1)
        self.assertEqual(db.session.query(GameNotification).filter_by(user_id=3).count(),1)

    def test_read_is_csrf_protected_per_user_and_independent_of_main_notifications(self):
        self.war();id=db.session.scalar(select(NewsEvent.id))
        self.assertEqual(self.client.post('/game/dyplomacja/wiadomosci-swiatowe/odczytaj',data={'ids':id}).status_code,400)
        response=self.post('/game/dyplomacja/wiadomosci-swiatowe/odczytaj',ids=str(id))
        self.assertEqual(response.json['unread_count'],0)
        self.assertEqual(self.client.get('/game/forum/powiadomienia').json['unread_count'],1)
        self.login(1);self.post('/game/dyplomacja/wiadomosci-swiatowe/odczytaj',ids=str(id))
        self.assertEqual(db.session.query(NewsNotice).filter_by(user_id=1).count(),0)

    def test_mark_all_world_news_read_covers_every_page_and_only_own_notices(self):
        # 16 Nov 2026: przycisk „Oznacz wszystkie jako przeczytane” w panelu powiadomień modułu dyplomatycznego.
        for index in range(23):
            db.session.add(AudytStosunki(panstwo_id=1,panstwo_id2=2,relacja_id=6 if index%2 else 10,stan_id=1,data_zmiany_entenda=NOW,data_zmiany_rzeczywista=NOW))
        db.session.commit();collect(db.session,NOW);db.session.commit()
        total=self.client.get('/game/dyplomacja/wiadomosci-swiatowe').json['unread_count']
        self.assertGreater(total,20)
        self.assertEqual(self.client.post('/game/dyplomacja/wiadomosci-swiatowe/odczytaj',data={'all':'1'}).status_code,400)   # bez CSRF
        self.assertEqual(self.post('/game/dyplomacja/wiadomosci-swiatowe/odczytaj',all='1').json['unread_count'],0)
        self.assertEqual(db.session.query(NewsNotice).filter(NewsNotice.user_id!=3,NewsNotice.read_at.is_not(None)).count(),0)

    def test_inline_and_collector_do_not_duplicate_and_rollback_erases_news(self):
        self.war();collect(db.session,NOW);db.session.commit()
        self.assertEqual(db.session.query(NewsEvent).count(),1)
        self.assertEqual(db.session.query(NewsNotice).count(),1)
        row=db.session.scalar(select(Stosunki).options(lazyload('*')).where(Stosunki.PANSTWO_ID==1,Stosunki.PANSTWO_ID2==2))
        apply_change(db.session,row,1,2,10,1,NOW);db.session.rollback()
        self.assertEqual(db.session.query(NewsEvent).count(),1)
        self.assertEqual(db.session.query(NewsNotice).count(),1)

    def test_guards_and_existing_events_survive_new_client(self):
        self.war()
        self.assertEqual(self.client.get('/game/dyplomacja/wiadomosci-swiatowe').json['unread_count'],1)
        with self.client.session_transaction() as session:session.clear()
        self.assertEqual(self.client.get('/game/dyplomacja/wiadomosci-swiatowe').status_code,401)
        self.login(3);self.app.config['ENV_NAME']='PROD'
        self.assertEqual(self.client.get('/game/dyplomacja/wiadomosci-swiatowe').status_code,404)

    def test_npc_changes_and_peace_response_use_the_same_world_delivery(self):
        from game.paga import PagaConfiguration,PagaRevision,save_configuration,TRAITS,INTERESTS
        self.app.config['PAGA_ENABLED']=True
        for model in (PagaConfiguration,PagaRevision):model.__table__.create(db.engine)
        save_configuration(db.session,4,{'mode':'approve','revision':0,'autonomyEnabled':True,'character':{key:50 for key in TRAITS},'interests':[{'key':key,'active':key=='survival'} for key in INTERESTS]},'Test');db.session.commit()
        offer=create_action(db.session,4,1,'RELATION',1,NOW,npc=True);db.session.flush()
        decide_action(db.session,offer.id,1,True,NOW,user_id=1)
        create_action(db.session,4,1,'RELATION',10,NOW,npc=True)
        create_action(db.session,4,1,'WAR',None,NOW,npc=True)
        peace=create_action(db.session,1,4,'PEACE',None,NOW,sender_user_id=1);db.session.flush()
        decide_action(db.session,peace.id,4,True,NOW);db.session.commit()
        self.assertEqual(db.session.query(NewsEvent).count(),4)
        self.assertEqual(len(self.client.get('/game/dyplomacja/wiadomosci-swiatowe').json['items']),4)
        self.assertEqual(len(self.client.get('/game/forum/powiadomienia').json['items']),2)

    def test_pagination_and_noop_audits_do_not_starve_collector(self):
        for index in range(23):
            db.session.add(AudytStosunki(panstwo_id=1,panstwo_id2=2,relacja_id=6 if index%2 else 10,stan_id=1,data_zmiany_entenda=NOW,data_zmiany_rzeczywista=NOW))
        db.session.commit();collect(db.session,NOW);db.session.commit()
        first=self.client.get('/game/dyplomacja/wiadomosci-swiatowe').json
        second=self.client.get('/game/dyplomacja/wiadomosci-swiatowe?page=2').json
        self.assertEqual(len(first['items']),20);self.assertEqual(len(second['items']),3)
        self.assertFalse({row['id'] for row in first['items']} & {row['id'] for row in second['items']})
