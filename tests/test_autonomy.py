"""Autonomous actions execute real shared services on isolated SQLite worlds."""
from datetime import timedelta
from unittest.mock import patch
from sqlalchemy import select,delete,text,update
from sqlalchemy.orm import lazyload
from extensions import db
from models import Panstwo,AudytStosunki,Stosunki,DictStosunkiRelacja,Region
from game.models import GamePlayerCountry
from game.paga import PagaConfiguration,PagaRevision,save_configuration,TRAITS,INTERESTS
from game import autonomy_models as state
from game.autonomy_engine import collect_and_schedule,analyze,eligible_ids
from game.autonomy_memory import record_event,observe,assessment,ingest_sources
from game.autonomy_actions import Candidate,score,build_context,REGISTRY
from game.diplomacy_service import create_action,decide_action
from game.diplomacy_models import DiplomaticAction
from game.intelligence_service import operate_in_transaction,complete_missions,mission_days   # czas misji: 4 dni, hybrydowe 2 (od 17 Nov 2026)
from game.intelligence_models import IntelligenceAgent,IntelligenceMission,IntelligenceExpense
from game.forum_models import GameNotification
from test_game_intelligence import IntelligenceFixture
from test_game_military import NOW

CLASSES=[state.AutonomyControl,state.AutonomySchedule,state.AutonomyEvent,state.AutonomySourceReceipt,state.AutonomyMemory,state.AutonomyAssessment,state.AutonomyReaction,state.AutonomyAnalysis]


class AutonomyTests(IntelligenceFixture):
    def setUp(self):
        # Wycofany silnik regułowy (kod zachowany jako historia); od 11 Nov 2026 decyzje podejmuje PAGA2.
        super().setUp();self.app.config.update(PAGA_ENABLED=True,AUTONOMY_ENABLED=True,ENV_NAME="UAT",PAGA_LEGACY_ENGINES=True)
        for model in [PagaConfiguration,PagaRevision,*CLASSES]:model.__table__.create(db.engine,checkfirst=True)
        db.session.add(DictStosunkiRelacja(relacja_id=1,relacja_nazwa='Sojusznicze'))
        db.session.add(Stosunki(PANSTWO_ID=1,PANSTWO_ID2=2,relacja_id=10,stan_id=1))
        db.session.execute(delete(GamePlayerCountry).where(GamePlayerCountry.panstwo_id==1))
        self.payload={'mode':'approve','revision':0,'autonomyEnabled':True,'character':{key:50 for key in TRAITS},'interests':[{'key':key,'active':key=='survival'} for key in INTERESTS]}
        save_configuration(db.session,1,self.payload,'Test')
        db.session.add(state.AutonomyControl(id=1,enabled=True,revision=0,max_actions=3,window_days=30,cooldown_days=7,max_chain_depth=2,started_at=NOW-timedelta(days=1)))
        db.session.commit()
        self.neighbors=patch('game.road_projects.neighboring_countries',return_value={2});self.neighbors.start();self.addCleanup(self.neighbors.stop)

    def config(self,traits=None,interest=None):
        row=db.session.get(PagaConfiguration,1);data={**self.payload,'revision':row.revision,'character':{**self.payload['character'],**(traits or {})},'interests':[{'key':key,'active':key==(interest or 'survival')} for key in INTERESTS]}
        save_configuration(db.session,1,data,'Test');db.session.commit();return db.session.get(PagaConfiguration,1)

    def due(self):
        collect_and_schedule(db.session,NOW);db.session.flush()
        row=db.session.get(state.AutonomySchedule,1);row.next_at=NOW;db.session.commit()

    def test_only_approved_enabled_nonhuman_and_sovereign_countries_eligible(self):
        self.assertEqual(eligible_ids(db.session),[1])
        row=db.session.get(PagaConfiguration,1);row.autonomy_enabled=False;db.session.commit();self.assertEqual(eligible_ids(db.session),[])
        row.autonomy_enabled=True;row.approved_at=None;db.session.commit();self.assertEqual(eligible_ids(db.session),[])
        row.approved_at=NOW;db.session.add(GamePlayerCountry(user_id=1,panstwo_id=1));db.session.commit();self.assertEqual(eligible_ids(db.session),[])

    def test_schedule_is_staggered_persistent_and_coalesces_downtime(self):
        save_configuration(db.session,4,self.payload,'Test');db.session.commit()
        collect_and_schedule(db.session,NOW);db.session.commit()
        first=db.session.get(state.AutonomySchedule,1).next_at;second=db.session.get(state.AutonomySchedule,4).next_at
        self.assertNotEqual(first,second)
        self.assertLess(first,NOW+timedelta(days=1));self.assertLess(second,NOW+timedelta(days=1))
        collect_and_schedule(db.session,NOW+timedelta(days=2));db.session.commit();self.assertEqual(db.session.get(state.AutonomySchedule,1).next_at,first)
        row=db.session.get(state.AutonomySchedule,1);row.next_at=NOW;db.session.commit()
        self.config({'isolationism':100,'ambition':0,'militarism':0,'provocation':0,'agreeableness':0,'predictability':100,'revenge':0},'prosperity')
        id=analyze(db.session,1,NOW+timedelta(days=100));db.session.commit()
        self.assertEqual(db.session.get(state.AutonomyAnalysis,id).status,'PASSIVE')
        self.assertEqual(db.session.get(state.AutonomySchedule,1).next_at,NOW+timedelta(days=101))
        self.assertIsNone(analyze(db.session,1,NOW+timedelta(days=100)))

    def test_global_and_country_pause_and_player_takeover_prevent_execution(self):
        self.due();control=db.session.get(state.AutonomyControl,1);control.enabled=False;db.session.commit()
        self.assertIsNone(analyze(db.session,1,NOW))
        control.enabled=True;db.session.get(PagaConfiguration,1).autonomy_enabled=False;db.session.commit();self.assertIsNone(analyze(db.session,1,NOW))
        db.session.get(PagaConfiguration,1).autonomy_enabled=True;db.session.add(GamePlayerCountry(user_id=1,panstwo_id=1));db.session.commit()
        self.assertIsNone(analyze(db.session,1,NOW));self.assertEqual(db.session.query(state.AutonomyAnalysis).count(),0)

    def test_real_npc_war_executes_once_and_notifies_human(self):
        from models import DictStosunkiStan
        db.session.add(DictStosunkiStan(stan_id=9,stan_nazwa='Wojna informacyjna'))
        db.session.execute(update(Stosunki).where(Stosunki.PANSTWO_ID==1,Stosunki.PANSTWO_ID2==2).values(stan_id=9));db.session.commit()
        self.config({'militarism':100,'provocation':100,'ambition':100,'agreeableness':0,'isolationism':0,'predictability':100,'revenge':100},'conquer_neighbors');self.due()
        with patch('game.autonomy_engine.REGISTRY',[REGISTRY[0]]):
            id=analyze(db.session,1,NOW);db.session.commit()
            self.assertIsNone(analyze(db.session,1,NOW))
        row=db.session.get(state.AutonomyAnalysis,id)
        self.assertEqual(row.action,'WAR');self.assertEqual(row.status,'EXECUTED')
        self.assertEqual(db.session.scalar(select(Stosunki.stan_id).where(Stosunki.PANSTWO_ID==1,Stosunki.PANSTWO_ID2==2)),8)
        action=db.session.scalar(select(DiplomaticAction));self.assertIsNone(action.sender_user_id);self.assertEqual(action.recipient_user_id,2)
        self.assertEqual(db.session.query(DiplomaticAction).count(),1)
        self.assertEqual(db.session.query(GameNotification).count(),1)

    def test_player_proposal_requires_human_acceptance_when_sent_by_npc(self):
        action=create_action(db.session,1,2,'RELATION',1,NOW,npc=True);db.session.commit()
        self.assertEqual(action.status,'PENDING');self.assertEqual(db.session.scalar(select(Stosunki.relacja_id).where(Stosunki.PANSTWO_ID==1,Stosunki.PANSTWO_ID2==2)),10)
        self.login(2);response=self.client.post(f'/game/dyplomacja/propozycje/{action.id}/decyzja',data={'csrf_token':'token','decision':'accept'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(db.session.scalar(select(Stosunki.relacja_id).where(Stosunki.PANSTWO_ID==1,Stosunki.PANSTWO_ID2==2)),1)

    def test_human_can_propose_to_npc_and_npc_accepts_without_synthetic_account(self):
        self.config({'agreeableness':100,'provocation':0,'isolationism':0,'ambition':80,'predictability':100},'prosperity')
        action=create_action(db.session,2,1,'RELATION',1,NOW,sender_user_id=2);db.session.commit()
        self.assertIsNone(action.recipient_user_id)
        control=db.session.get(state.AutonomyControl,1);ingest_sources(db.session,control,NOW)
        observe(db.session,1,db.session.get(PagaConfiguration,1),NOW,control);db.session.commit()
        reaction=db.session.scalar(select(state.AutonomyReaction).where(state.AutonomyReaction.status=='READY'))
        self.assertIsNotNone(reaction)
        with patch('game.autonomy_engine.REGISTRY',[REGISTRY[0]]):
            id=analyze(db.session,1,reaction.ready_at,event_id=reaction.event_id);db.session.commit()
        self.assertEqual(db.session.get(state.AutonomyAnalysis,id).action,'ACCEPT')
        db.session.refresh(action);self.assertEqual(action.status,'ACCEPTED')
        self.assertEqual(db.session.query(GameNotification).count(),1)
        self.login(2)
        feed=self.client.get('/game/forum/powiadomienia').json
        self.assertEqual(feed['items'][0]['text'],'Państwo Państwo 1 zaakceptowało Twoją propozycję zmiany relacji.')
        dialog=self.post(feed['items'][0]['open_url']).json['dialog']
        self.assertEqual(dialog['title'],'Dyplomacja: Państwo 1')
        self.assertEqual(dialog['text'],feed['items'][0]['text']);self.assertFalse(dialog['can_decide'])

    def test_npc_rejection_notification_names_responder_not_players_own_country(self):
        action=create_action(db.session,2,1,'RELATION',1,NOW,sender_user_id=2)
        db.session.flush();decide_action(db.session,action.id,1,False,NOW);db.session.commit()
        self.login(2)
        item=self.client.get('/game/forum/powiadomienia').json['items'][0]
        self.assertEqual(item['text'],'Państwo Państwo 1 odrzuciło Twoją propozycję zmiany relacji.')
        dialog=self.post(item['open_url']).json['dialog']
        self.assertEqual(dialog['title'],'Dyplomacja: Państwo 1')
        self.assertEqual(dialog['text'],item['text']);self.assertFalse(dialog['can_decide'])

    def test_private_reports_never_enter_other_countries_memory(self):
        save_configuration(db.session,4,self.payload,'Test');db.session.commit()
        private=record_event(db.session,'private-test','INTELLIGENCE_REPORT',2,1,NOW,public=False,audience=[2],payload={'secret':'hidden'})
        public=record_event(db.session,'public-test','BOMBARDMENT',2,1,NOW)
        control=db.session.get(state.AutonomyControl,1)
        for country in (1,4):observe(db.session,country,db.session.get(PagaConfiguration,country),NOW,control)
        db.session.commit()
        self.assertIsNone(db.session.get(state.AutonomyMemory,(1,private.id)))
        self.assertIsNone(db.session.get(state.AutonomyMemory,(4,private.id)))
        self.assertIsNotNone(db.session.get(state.AutonomyMemory,(1,public.id)))
        self.assertIsNotNone(db.session.get(state.AutonomyMemory,(4,public.id)))

    def test_event_queue_is_separate_deduplicated_and_chain_limited(self):
        self.due();next_at=db.session.get(state.AutonomySchedule,1).next_at=NOW+timedelta(days=20)
        event=record_event(db.session,'attack-test','WAR',2,1,NOW)
        chained=record_event(db.session,'deep-test','WAR',2,1,NOW,depth=2)
        control=db.session.get(state.AutonomyControl,1);config=db.session.get(PagaConfiguration,1)
        observe(db.session,1,config,NOW,control);observe(db.session,1,config,NOW,control);db.session.commit()
        reaction=db.session.get(state.AutonomyReaction,(1,event.id));self.assertLess(reaction.ready_at,next_at)
        self.assertLess(reaction.ready_at,NOW+timedelta(days=1))
        self.assertEqual(db.session.get(state.AutonomyReaction,(1,chained.id)).status,'IGNORED')
        id=analyze(db.session,1,reaction.ready_at,event_id=event.id);db.session.commit()
        self.assertIsNotNone(id);self.assertIsNone(analyze(db.session,1,reaction.ready_at,event_id=event.id))
        self.assertEqual(db.session.get(state.AutonomySchedule,1).next_at,next_at)

    def test_memory_influence_decays_without_deleting_history(self):
        event=record_event(db.session,'memory-test','BOMBARDMENT',2,1,NOW)
        observe(db.session,1,db.session.get(PagaConfiguration,1),NOW,db.session.get(state.AutonomyControl,1));db.session.commit()
        first=assessment(db.session,1,2,NOW);later=assessment(db.session,1,2,NOW+timedelta(days=240));db.session.commit()
        self.assertLess(first['trust'],later['trust']);self.assertGreater(first['threat'],later['threat'])
        self.assertIsNotNone(db.session.get(state.AutonomyMemory,(1,event.id)))

    def test_hidden_enemy_army_not_used_without_intelligence(self):
        ctx=build_context(db.session,1,db.session.get(PagaConfiguration,1),NOW)
        target=next(row for row in ctx['targets'] if row['id']==2)
        self.assertIsNone(target['strength']);self.assertFalse(target['known_resources'])

    def test_recruit_and_mission_share_cost_duration_and_probability(self):
        from uuid import uuid4
        operate_in_transaction(db.session,1,{'action':'recruit','level':7,'count':1,'request_id':str(uuid4())},NOW)
        db.session.flush();agent=db.session.scalar(select(IntelligenceAgent).where(IntelligenceAgent.panstwo_id==1))
        id=operate_in_transaction(db.session,1,{'action':'mission','agent_id':agent.id,'region_id':2,'kind':'bases','request_id':str(uuid4())},NOW);db.session.commit()
        mission=db.session.get(IntelligenceMission,id);self.assertEqual(mission.ends_at,NOW+timedelta(days=mission_days('bases')))
        self.assertEqual(db.session.query(IntelligenceExpense).count(),2)
        with patch('game.intelligence_service.randbelow',return_value=0):complete_missions(db.session,NOW+timedelta(days=mission_days('bases')));db.session.commit()
        self.assertTrue(mission.success);self.assertIn(self.enemy.id,mission.report['base_ids'])
        ingest_sources(db.session,db.session.get(state.AutonomyControl,1),NOW+timedelta(days=mission_days('bases')));db.session.commit()
        observe(db.session,1,db.session.get(PagaConfiguration,1),NOW+timedelta(days=mission_days('bases')),db.session.get(state.AutonomyControl,1));db.session.commit()
        self.assertTrue(db.session.scalar(select(state.AutonomyEvent.id).where(state.AutonomyEvent.kind=='INTELLIGENCE_REPORT')))

    def test_atomic_failure_rolls_back_world_and_analysis(self):
        self.due();before=db.session.query(DiplomaticAction).count()
        adapter=REGISTRY[0]
        def fail_after_execute(*args):adapter.execute(*args);raise RuntimeError('crash')
        from game.autonomy_actions import ActionAdapter
        fake=ActionAdapter(adapter.propose,adapter.check,fail_after_execute)
        self.config({'militarism':100,'provocation':100,'ambition':100,'agreeableness':0,'isolationism':0,'predictability':100},'conquer_neighbors')
        with patch('game.autonomy_engine.REGISTRY',[fake]):
            with self.assertRaises(RuntimeError):analyze(db.session,1,NOW)
        db.session.rollback()
        self.assertEqual(db.session.query(DiplomaticAction).count(),before)
        self.assertEqual(db.session.query(state.AutonomyAnalysis).count(),0)

    def test_runtime_recruits_and_launches_real_reconnaissance(self):
        self.config({'militarism':100,'provocation':100,'ambition':100,'agreeableness':0,'isolationism':0,'predictability':100},'resources_economy');self.due()
        with patch('game.autonomy_engine.REGISTRY',[REGISTRY[1]]):
            id=analyze(db.session,1,NOW);db.session.commit()
            self.assertEqual(db.session.get(state.AutonomyAnalysis,id).action,'RECRUIT_AGENT')
            self.assertEqual(db.session.query(IntelligenceAgent).filter_by(panstwo_id=1).count(),1)
            db.session.get(state.AutonomySchedule,1).next_at=NOW+timedelta(days=1);db.session.commit()
            id=analyze(db.session,1,NOW+timedelta(days=1));db.session.commit()
            self.assertEqual(db.session.get(state.AutonomyAnalysis,id).action,'SCOUT_resources')
            self.assertEqual(db.session.query(IntelligenceExpense).count(),2)
            mission=db.session.scalar(select(IntelligenceMission))
            self.assertEqual(mission.ends_at,mission.starts_at+timedelta(days=mission_days('resources')))

    def test_runtime_hybrid_uses_real_mission_cost_and_changes_target_after_seven_days(self):
        self.config({'militarism':100,'provocation':100,'ambition':100,'agreeableness':0,'isolationism':0,'predictability':100,'revenge':100},'world_chaos');self.due()
        db.session.add(IntelligenceAgent(panstwo_id=1,level=7))
        db.session.get(Region,2).region_stan_infra_mieszkalnej=80;db.session.commit()
        from game.autonomy_actions import ActionAdapter
        adapter=REGISTRY[1]
        only_arson=ActionAdapter(lambda session,ctx:(candidate for candidate in adapter.propose(session,ctx) if candidate.action=='HYBRID_arson' and candidate.target==2),adapter.check,adapter.execute)
        with patch('game.autonomy_engine.REGISTRY',[only_arson]):
            id=analyze(db.session,1,NOW);db.session.commit()
        self.assertEqual(db.session.get(state.AutonomyAnalysis,id).action,'HYBRID_arson')
        self.assertEqual(db.session.query(IntelligenceExpense).count(),1)
        mission=db.session.scalar(select(IntelligenceMission))
        self.assertEqual(mission.ends_at,NOW+timedelta(days=mission_days('arson')));self.assertIsNone(mission.completed_at)
        with patch('game.intelligence_service.randbelow',return_value=0):
            complete_missions(db.session,NOW+timedelta(days=mission_days('arson')));db.session.commit()
        self.assertTrue(mission.success);self.assertEqual(db.session.get(Region,2).region_stan_infra_mieszkalnej,79)

    def test_maximum_actions_applies_to_periodic_and_reactive_decisions_together(self):
        self.config({'militarism':100,'provocation':100,'ambition':100,'agreeableness':0,'isolationism':0,'predictability':100},'conquer_neighbors');self.due()
        db.session.get(state.AutonomyControl,1).max_actions=1;db.session.commit()
        with patch('game.autonomy_engine.REGISTRY',[REGISTRY[0]]):analyze(db.session,1,NOW);db.session.commit()
        event=record_event(db.session,'quota-war','WAR',2,1,NOW)
        observe(db.session,1,db.session.get(PagaConfiguration,1),NOW,db.session.get(state.AutonomyControl,1));db.session.commit()
        reaction=db.session.get(state.AutonomyReaction,(1,event.id))
        id=analyze(db.session,1,reaction.ready_at,event_id=event.id);db.session.commit()
        row=db.session.get(state.AutonomyAnalysis,id)
        self.assertEqual(row.status,'PASSIVE');self.assertIn('Limit aktywności',row.factors['reason'])
        self.assertEqual(db.session.query(state.AutonomyAnalysis).filter_by(status='EXECUTED').count(),1)

    def test_all_active_interests_are_weighted_and_randomness_is_bounded_by_predictability(self):
        from random import Random
        config=self.config({'predictability':100},'survival')
        config.approved_interests=[{'key':key,'active':key in ('survival','world_chaos')} for key in INTERESTS]
        ctx=build_context(db.session,1,config,NOW)
        first=score(Candidate('WAR',2,{}),ctx,Random(1));second=score(Candidate('WAR',2,{}),ctx,Random(2))
        self.assertEqual(first.score,second.score);self.assertEqual(first.factors['randomness'],0)
        self.assertEqual(set(first.factors['interest_weights']),{'survival','world_chaos'})
        self.assertGreater(first.factors['interest_weights']['survival'],first.factors['interest_weights']['world_chaos'])
        ctx['traits']={**ctx['traits'],'predictability':0}
        varied=score(Candidate('WAR',2,{}),ctx,Random(2));self.assertLessEqual(abs(varied.factors['randomness']),20)

    def test_undetected_hybrid_does_not_reveal_attacker_and_receipts_are_idempotent(self):
        save_configuration(db.session,4,self.payload,'Test');db.session.commit()
        agent=IntelligenceAgent(panstwo_id=2,level=1);db.session.add(agent);db.session.flush()
        mission=IntelligenceMission(panstwo_id=2,agent_id=agent.id,region_id=1,target_country_id=1,region_name='Region',kind='arson',starts_at=NOW-timedelta(days=7),ends_at=NOW,completed_at=NOW,success=True,report={'captured':False,'damage':{'loss':1},'entries':[]})
        db.session.add(mission);db.session.commit()
        control=db.session.get(state.AutonomyControl,1)
        ingest_sources(db.session,control,NOW);ingest_sources(db.session,control,NOW);db.session.commit()
        event=db.session.scalar(select(state.AutonomyEvent).where(state.AutonomyEvent.kind=='UNATTRIBUTED_DAMAGE'))
        self.assertIsNone(event.actor_id);self.assertEqual(event.private_country_id,1)
        self.assertEqual(db.session.query(state.AutonomyEvent).count(),2)
        observe(db.session,1,db.session.get(PagaConfiguration,1),NOW,control)
        observe(db.session,4,db.session.get(PagaConfiguration,4),NOW,control);db.session.commit()
        self.assertIsNotNone(db.session.get(state.AutonomyMemory,(1,event.id)))
        self.assertIsNone(db.session.get(state.AutonomyMemory,(4,event.id)))

    def test_production_environment_never_executes_even_if_flag_is_misconfigured(self):
        self.due();self.app.config['ENV_NAME']='PROD'
        self.assertIsNone(analyze(db.session,1,NOW))
        self.assertEqual(db.session.query(state.AutonomyAnalysis).count(),0)

    def test_same_action_target_cooldown_is_enforced(self):
        self.config({'militarism':100,'provocation':100,'ambition':100,'agreeableness':0,'isolationism':0,'predictability':100},'conquer_neighbors');self.due()
        db.session.add(state.AutonomyAnalysis(request_key='previous-war',country_id=1,game_at=NOW-timedelta(days=1),trigger='PERIODIC',action='WAR',target_id=2,status='EXECUTED',score=100,factors={},candidates=[]));db.session.commit()
        with patch('game.autonomy_engine.REGISTRY',[REGISTRY[0]]):id=analyze(db.session,1,NOW);db.session.commit()
        row=db.session.get(state.AutonomyAnalysis,id)
        blocked=[candidate for candidate in row.candidates if candidate['action']=='WAR' and candidate['target']==2]
        self.assertTrue(blocked);self.assertIn('Okres oczekiwania',blocked[0]['blocked'])

    def test_npc_adapter_breaks_alliance_and_records_public_memory(self):
        row=db.session.scalar(select(Stosunki).where(Stosunki.PANSTWO_ID==1,Stosunki.PANSTWO_ID2==2).options(lazyload('*')))
        row.relacja_id=1;db.session.commit()
        ctx=build_context(db.session,1,db.session.get(PagaConfiguration,1),NOW)
        adapter=REGISTRY[0]
        candidate=next(candidate for candidate in adapter.propose(db.session,ctx) if candidate.action=='RELATION_WORSEN' and candidate.target==2 and candidate.payload['relation_id']==10)
        adapter.check(db.session,ctx,candidate)
        result=adapter.execute(db.session,ctx,candidate,'npc-break-test',{'root_id':None,'depth':0});db.session.commit()
        self.assertEqual(result['status'],'APPLIED')
        self.assertEqual(db.session.scalar(select(Stosunki.relacja_id).where(Stosunki.PANSTWO_ID==1,Stosunki.PANSTWO_ID2==2)),10)
        ingest_sources(db.session,db.session.get(state.AutonomyControl,1),NOW);db.session.commit()
        self.assertEqual(db.session.scalar(select(state.AutonomyEvent.kind).where(state.AutonomyEvent.source_key.like('audit:%'))),'ALLIANCE_BROKEN')

    def test_legacy_monthly_schedule_moves_within_day_and_stays_stable(self):
        self.due()
        schedule=db.session.get(state.AutonomySchedule,1);schedule.next_at=NOW+timedelta(days=25)
        control=db.session.get(state.AutonomyControl,1)
        limits=(control.max_actions,control.window_days,control.cooldown_days)
        collect_and_schedule(db.session,NOW);db.session.commit()
        updated=schedule.next_at
        self.assertGreaterEqual(updated,NOW);self.assertLess(updated,NOW+timedelta(days=1))
        collect_and_schedule(db.session,NOW+timedelta(minutes=1));db.session.commit()
        self.assertEqual(schedule.next_at,updated)
        self.assertEqual((control.max_actions,control.window_days,control.cooldown_days),limits)

    def test_revealed_enemy_base_does_not_reveal_garrison_or_change_scoring(self):
        from random import Random
        from game.military_models import MilitaryBase
        from game.intelligence_service import collect_report,known_ids
        agent=IntelligenceAgent(panstwo_id=1,level=7);db.session.add(agent);db.session.flush()
        mission=IntelligenceMission(panstwo_id=1,agent_id=agent.id,region_id=2,target_country_id=2,region_name='Region',kind='bases',starts_at=NOW-timedelta(days=7),ends_at=NOW,completed_at=NOW,success=True)
        mission.report=collect_report(db.session,mission)
        db.session.add(mission);db.session.commit()
        self.assertIn(self.enemy.id,known_ids(db.session,1,'bases'))
        config=db.session.get(PagaConfiguration,1)
        before=build_context(db.session,1,config,NOW)
        before_score=score(Candidate('WAR',2),before,Random(1))
        db.session.execute(update(MilitaryBase).where(MilitaryBase.id==self.enemy.id).values(garrison={'soldiers':999999999,'fighters':999999}));db.session.commit()
        after=build_context(db.session,1,config,NOW)
        after_score=score(Candidate('WAR',2),after,Random(1))
        self.assertIsNone(next(target for target in before['targets'] if target['id']==2)['strength'])
        self.assertIsNone(next(target for target in after['targets'] if target['id']==2)['strength'])
        self.assertEqual(before_score.score,after_score.score)
        self.assertEqual(before_score.factors,after_score.factors)
        self.assertFalse(after_score.factors['opponent_strength_known'])
