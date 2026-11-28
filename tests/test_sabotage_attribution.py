"""28 Nov 2026: kontrwywiad poziomu 6–7 ustala sprawcę sabotażu; reakcja PAGA2 (rejestr prób, stosunki, odwet, forum)."""
import unittest
from datetime import timedelta,datetime
from unittest.mock import patch
from sqlalchemy import select
from extensions import db
from models import Region,Panstwo
from game.forum_models import GameNotification
from game.intelligence_models import IntelligenceMission,CounterIntelligence
from game.intelligence_service import complete_missions,HYBRID
from game.paga2 import sabotage,diplomacy,communication,intelligence
from test_game_intelligence import IntelligenceFixture
from test_game_military import NOW
from test_paga2_diplomacy import dctx,IDS


class AttributionTests(IntelligenceFixture):
    def setUp(self):
        super().setUp();region=db.session.get(Region,2)
        for _,field,_,_ in HYBRID.values():setattr(region,field,50)
        region.region_polozenie_id=2;db.session.commit()

    def finish_with(self,rolls):
        with patch('game.intelligence_service.randbelow',side_effect=rolls):complete_missions(db.session,NOW+timedelta(days=7))
        db.session.commit();db.session.expire_all()

    def victim_texts(self):
        return [n.system_text for n in db.session.scalars(select(GameNotification).where(GameNotification.user_id==2))]

    def protect(self,level):
        db.session.add(CounterIntelligence(panstwo_id=2,level=level));db.session.commit()

    def test_level_six_reveals_culprit_of_failed_attempt(self):
        self.protect(6);mission=self.start('arson')
        self.finish_with([9999,99])   # nieudana, agent nie schwytany
        report=db.session.get(IntelligenceMission,mission.id).report
        self.assertTrue(report['attributed']);self.assertFalse(report['captured'])
        name=db.session.scalar(select(Panstwo.panstwo_nazwa).where(Panstwo.PANSTWO_ID==1))
        self.assertTrue(any(f'Kontrwywiad ustalił sprawcę: {name}.' in text for text in self.victim_texts()))

    def test_level_seven_reveals_culprit_of_successful_sabotage(self):
        self.protect(7);mission=self.start('cyber_energy')
        self.finish_with([0])
        mission=db.session.get(IntelligenceMission,mission.id)
        self.assertTrue(mission.success);self.assertTrue(mission.report['attributed'])
        self.assertTrue(any('ustalił sprawcę' in text for text in self.victim_texts()))

    def test_level_five_keeps_culprit_unknown(self):
        self.protect(5);mission=self.start('cyber_energy')
        self.finish_with([0])
        self.assertFalse(db.session.get(IntelligenceMission,mission.id).report['attributed'])
        self.assertFalse(any('ustalił sprawcę' in text for text in self.victim_texts()))

    def test_screen_lists_attributed_and_hides_undetected_failures(self):
        from game.intelligence import sabotage_against
        countries=dict(db.session.execute(select(Panstwo.PANSTWO_ID,Panstwo.panstwo_nazwa)).all())
        self.protect(5);self.start('arson');self.finish_with([9999,99])   # nieudana, niewykryta
        self.assertEqual(sabotage_against(2,countries),[])
        db.session.get(CounterIntelligence,2).level=6;db.session.commit()
        self.start('arson');self.finish_with([9999,99])
        items=sabotage_against(2,countries)
        self.assertEqual(len(items),1);self.assertEqual(items[0]['culprit'],countries[1]);self.assertFalse(items[0]['success'])


def event(id,actor=5,success=False,operation='arson',at='2999-12-01T00:00:00'):
    return {'id':id,'kind':'HYBRID_DETECTED','actor':actor,'target':1,'at':at,'operation':operation,'success':success}


class PagaReactionTests(unittest.TestCase):
    def ctx(self,events,relations=None,revenge=50,**traits):
        c=dctx(relations or {5:{'relation':'neutralne','state':'pokoj'}})
        c.traits={**c.traits,'revenge':revenge,**traits};c.relationships={}
        c.memory['actions_against_us']=events;c._sabotage=None
        return c

    def test_record_counts_attempts_per_culprit(self):
        c=self.ctx([event(1),event(2,success=True,operation='cyber_rail'),event(3,actor=6),{'id':4,'kind':'UNATTRIBUTED_DAMAGE','actor':None,'at':'2999-12-02'}])
        record=sabotage.record(c)
        self.assertEqual(set(record),{5,6});self.assertEqual(record[5]['count'],2);self.assertEqual(record[5]['successful'],1)
        self.assertEqual(record[5]['last_kind'],'cyber_rail')

    def test_old_attempts_are_forgotten(self):
        c=self.ctx([event(1,at='2998-01-01T00:00:00')])
        self.assertEqual(sabotage.record(c),{})

    def test_pressure_grows_with_attempts_and_revenge(self):
        one=sabotage.relation_pressure(self.ctx([event(1)]),5)
        three=sabotage.relation_pressure(self.ctx([event(1),event(2),event(3)]),5)
        vengeful=sabotage.relation_pressure(self.ctx([event(1)],revenge=90),5)
        self.assertGreater(three,one);self.assertGreater(vengeful,one)
        self.assertEqual(sabotage.relation_pressure(self.ctx([]),5),0.0)

    def test_friendly_past_softens_single_incident(self):
        neutral=sabotage.relation_pressure(self.ctx([event(1)]),5)
        friendly=sabotage.relation_pressure(self.ctx([event(1)],relations={5:{'relation':'przyjazne','state':'pokoj'}}),5)
        self.assertLess(friendly,neutral)

    def test_repeated_sabotage_worsens_relations_by_two_steps(self):
        c=self.ctx([event(1),event(2),event(3)])
        with patch('game.paga2.diplomacy.weakness',return_value=0.0),patch('game.paga2.war_plans.active_plans',return_value=[]),\
             patch('game.paga2.war_plans.relation_lock',return_value=None),patch('game.paga2.war_plans.consistency_penalty',return_value=0.0):
            options={(o.action,o.target):o for o in diplomacy.relation_options(c,IDS)}
            calm=self.ctx([]);calm_options={(o.action,o.target):o for o in diplomacy.relation_options(calm,IDS)}
        worsen=options[('RELATION_WORSEN',5)]
        self.assertEqual(worsen.payload['relation_id'],IDS['zle'])   # neutralne → (chłodne) → złe
        self.assertGreater(worsen.base,calm_options[('RELATION_WORSEN',5)].base)
        self.assertTrue(any('sabotażu' in note for note in worsen.notes))

    def test_retaliation_needs_high_revenge_and_respects_strength(self):
        low=self.ctx([event(1)],revenge=40)
        self.assertEqual(sabotage.retaliation_targets(low),[])
        high=self.ctx([event(1)],revenge=80)
        with patch('game.paga2.sabotage.retaliations_since',return_value=0):
            self.assertEqual([o for o,_ in sabotage.retaliation_targets(high)],[5])
        with patch('game.paga2.sabotage.retaliations_since',return_value=1):
            self.assertEqual(sabotage.retaliation_targets(high),[])
        sabotage.record(high)
        with patch('game.paga2.diplomacy.powers',return_value=(10.0,0,100.0)):self.assertIsNone(sabotage.retaliation_terms(high,5,4))
        with patch('game.paga2.diplomacy.powers',return_value=(100.0,0,50.0)):self.assertIsNotNone(sabotage.retaliation_terms(high,5,4))
        fearless=self.ctx([event(1)],revenge=95);sabotage.record(fearless)
        with patch('game.paga2.diplomacy.powers',return_value=(10.0,0,100.0)):self.assertIsNotNone(sabotage.retaliation_terms(fearless,5,4))

    def test_retaliation_option_uses_same_kind(self):
        c=self.ctx([event(1,operation='cyber_rail')],revenge=80)
        c.limits={'per_action':.5,'per_run':.8};c._sectors={}
        data={'budgetAvailable':'10000000000','agents':[{'id':9,'level':5,'busy':False,'captured':False}],'counterLevel':1}
        with patch('game.paga2.sabotage.retaliations_since',return_value=0),patch('game.paga2.diplomacy.powers',return_value=(100.0,0,100.0)),\
             patch('game.paga2.intelligence.target_regions',return_value=[44]),patch('game.paga2.intelligence.recent_missions',return_value=set()),\
             patch('game.paga2.war_plans.intel_requests',return_value=[]):
            options=intelligence.options_for(c,data)
        revenge=[o for o in options if o.key.startswith('intel:revenge:')]
        self.assertEqual(len(revenge),1);self.assertEqual(revenge[0].payload['kind'],'cyber_rail');self.assertEqual(revenge[0].target,5)

    def test_forum_occasion_names_culprit(self):
        c=self.ctx([event(1,at=(datetime(3000,1,1)-timedelta(days=1)).isoformat())]);c.triggers=[]
        items=communication.sabotage_occasions(c,lambda id:{5:'Wrogland'}.get(id,str(id)),(c.now-timedelta(days=7)).isoformat())
        self.assertEqual(len(items),1);self.assertIn('Wrogland',items[0][3]);self.assertEqual(items[0][1],'forum_announcement')


if __name__=='__main__':unittest.main()
