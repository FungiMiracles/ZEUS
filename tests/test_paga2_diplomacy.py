"""PAGA2 etap 7 — dyplomacja (zmiana relacji, sojusze, pokój, odpowiedzi na propozycje) i wywiad wojskowy
(rekrutacja, kontrwywiad, rozpoznanie wrogów, działania hybrydowe)."""
import unittest
from datetime import datetime
from types import SimpleNamespace as NS
from unittest.mock import patch
from game.paga2 import diplomacy,intelligence
from game.paga2.scoring import score
from test_paga2_economy import EconomyCtx

IDS={name:i for i,name in enumerate(diplomacy.ORDER,start=1)}


def dctx(relations=None,level='peace',**kwargs):
    c=EconomyCtx(level=level,**kwargs)
    c.situation.update(relations=relations or {},at_war=[o for o,r in (relations or {}).items() if r.get('state')=='wojnakinetyczna'],hostile=[],threats=[],occupied_regions={})
    c._executed=[];c._addressable={2,3,4,9};c._pending=set();c._occupations=[];c.memory={'own_decisions':[],'actions_against_us':[],'perception':{}}
    c.world_summary=lambda session=None:{'neighbor_countries':[2,3]}
    c.history=lambda other:{'hostile_from':0,'hostile_to':0,'friendly':0}
    return c


class RelationTests(unittest.TestCase):
    def options(self,c):
        with patch('game.paga2.diplomacy.weakness',return_value=0.0):return {(o.action,o.target):o for o in diplomacy.relation_options(c,IDS)}

    def test_improve_worsen_and_alliance_options(self):
        c=dctx({2:{'relation':'przyjazne','state':'pokoj'},3:{'relation':'chlodne','state':'pokoj'}},perception={2:{'trust':80},3:{'trust':20}})
        by=self.options(c)
        self.assertEqual(by[('RELATION_IMPROVE',2)].payload['relation_id'],IDS['partnerskie'])
        self.assertEqual(by[('RELATION_WORSEN',3)].payload['relation_id'],IDS['zle'])
        self.assertIn(('ALLIANCE',2),by);self.assertNotIn(('ALLIANCE',3),by)   # sojusz tylko przy wysokim zaufaniu
        self.assertFalse(any(a=='WAR' for a,_ in by))                          # wojna nie należy do tego etapu

    def test_proposals_only_to_countries_that_can_answer(self):
        c=dctx({2:{'relation':'przyjazne','state':'pokoj'},5:{'relation':'przyjazne','state':'pokoj'},6:{'relation':'wrogie','state':'wojnakinetyczna'}},perception={5:{'trust':90}})
        c._addressable={2}
        c.world_summary=lambda session=None:{'neighbor_countries':[2,5,6]}
        by=self.options(c)
        self.assertIn(('RELATION_IMPROVE',2),by)
        self.assertNotIn(('RELATION_IMPROVE',5),by);self.assertNotIn(('ALLIANCE',5),by);self.assertNotIn(('PEACE',6),by)
        self.assertIn(('RELATION_WORSEN',5),by)   # jednostronne pogorszenie nie wymaga odbiorcy

    def test_no_duplicate_of_pending_proposal(self):
        c=dctx({2:{'relation':'przyjazne','state':'pokoj'}},perception={2:{'trust':90}});c._pending={(2,'RELATION')}
        by=self.options(c)
        self.assertNotIn(('RELATION_IMPROVE',2),by);self.assertNotIn(('ALLIANCE',2),by);self.assertIn(('RELATION_WORSEN',2),by)

    def test_occupying_an_allys_land_worsens_relations_with_occupier(self):
        relations={8:{'relation':'neutralne','state':'pokoj'}}
        c=dctx(relations,traits={'alliance_loyalty':90,'interventionism':90});c.situation['allies']=[2];c._occupations=[(8,2)];c._addressable={8}
        neutral=dctx(relations,traits={'alliance_loyalty':90,'interventionism':90});neutral._addressable={8}
        worse=score(self.options(c)[('RELATION_WORSEN',8)],c);base=score(self.options(neutral)[('RELATION_WORSEN',8)],neutral)
        self.assertGreater(worse.score,base.score+5)
        better=score(self.options(c)[('RELATION_IMPROVE',8)],c);plain=score(self.options(neutral)[('RELATION_IMPROVE',8)],neutral)
        self.assertLess(better.score,plain.score-5)

    def test_character_drives_choice(self):
        relations={2:{'relation':'neutralne','state':'pokoj'}}
        dove=dctx(relations,traits={'agreeableness':95,'provocation':5,'isolationism':5},categories=['hegemonic'],priorities=['alliances'])
        hawk=dctx(relations,traits={'agreeableness':5,'provocation':95,'revenge':90,'isolationism':80},categories=['imperialist'],priorities=['conquest'])
        d={k:score(o,dove) for k,o in self.options(dove).items()}
        h={k:score(o,hawk) for k,o in self.options(hawk).items()}
        self.assertGreater(d[('RELATION_IMPROVE',2)].score,d[('RELATION_WORSEN',2)].score)
        self.assertGreater(h[('RELATION_WORSEN',2)].score,h[('RELATION_IMPROVE',2)].score)

    def test_historical_ally_is_protected(self):
        c=dctx({2:{'relation':'dobre','state':'pokoj'}},relationships={2:{'status':'historical_ally'}},traits={'alliance_loyalty':90})
        worsen=score(self.options(c)[('RELATION_WORSEN',2)],c)
        neutral=dctx({2:{'relation':'dobre','state':'pokoj'}})
        self.assertLess(worsen.score,score(self.options(neutral)[('RELATION_WORSEN',2)],neutral).score-20)

    def test_peace_offers_at_war_and_cooldown(self):
        c=dctx({2:{'relation':'wrogie','state':'wojnakinetyczna'}})
        by=self.options(c)
        self.assertEqual({a for a,t in by if t==2},{'PEACE','CEASEFIRE'})
        c._executed=[('PEACE',2,datetime(3000,1,1))]
        self.assertNotIn(('PEACE',2),self.options(c))

    def test_military_weakness_favours_peace(self):
        c=dctx({2:{'relation':'wrogie','state':'wojnakinetyczna'}})
        with patch('game.paga2.diplomacy.weakness',return_value=12.0):weak=diplomacy.peace_terms(c,2)['base']
        with patch('game.paga2.diplomacy.weakness',return_value=0.0):strong=diplomacy.peace_terms(c,2)['base']
        self.assertEqual(weak-strong,12.0)


class ProposalTests(unittest.TestCase):
    def proposals(self,c,rows):
        class FakeSession:
            def __init__(self,*a):pass
            def __enter__(self):return self
            def __exit__(self,*a):return False
            def execute(self,query):return NS(all=lambda:[(i,name) for name,i in IDS.items()])
            def scalars(self,query):return rows
            def expunge(self,row):pass
        with patch('game.paga2.diplomacy.Session',FakeSession),patch('game.paga2.diplomacy.db',NS(engine=None)),patch('game.paga2.diplomacy.weakness',return_value=0.0),\
             patch('game.paga2.diplomacy.pair_now',lambda session,a,b:self.current.get(a,(1,1,1))):
            return diplomacy.proposal_options(c)

    current={}

    def test_stale_proposals_are_skipped(self):
        rows=[NS(id=5,source_country_id=2,source_country_name='B',kind='RELATION',proposed_relation_id=IDS['dobre'],target_country_id=1,expected_relation_id=1,expected_state_id=1,expected_audit_id=1),
              NS(id=6,source_country_id=3,source_country_name='C',kind='RELATION',proposed_relation_id=IDS['dobre'],target_country_id=1,expected_relation_id=1,expected_state_id=1,expected_audit_id=1)]
        self.current={3:(1,1,9)}   # para z państwem 3 zmieniła się od złożenia propozycji
        self.assertEqual({o.payload['proposal_id'] for o in self.proposals(dctx(),rows)},{5})

    def test_every_proposal_gets_accept_and_reject_with_required_decision(self):
        rows=[NS(id=5,source_country_id=2,source_country_name='B',kind='RELATION',proposed_relation_id=IDS['sojusznicze'],target_country_id=1,expected_relation_id=1,expected_state_id=1,expected_audit_id=1),NS(id=6,source_country_id=3,source_country_name='C',kind='PEACE',proposed_relation_id=None,target_country_id=1,expected_relation_id=1,expected_state_id=1,expected_audit_id=1)]
        c=dctx({3:{'relation':'wrogie','state':'wojnakinetyczna'}})
        options=self.proposals(c,rows)
        self.assertEqual([(o.action,o.payload['proposal_id']) for o in options],[('PROPOSAL_ACCEPT',5),('PROPOSAL_REJECT',5),('PROPOSAL_ACCEPT',6),('PROPOSAL_REJECT',6)])
        self.assertTrue(all(o.payload['required'] for o in options))

    def test_accepting_peace_scores_like_proposing_it(self):
        rows=[NS(id=6,source_country_id=3,source_country_name='C',kind='PEACE',proposed_relation_id=None,target_country_id=1,expected_relation_id=1,expected_state_id=1,expected_audit_id=1)]
        c=dctx({3:{'relation':'wrogie','state':'wojnakinetyczna'}},traits={'agreeableness':80,'revenge':20},priorities=['welfare'])
        accept,reject=self.proposals(c,rows)
        with patch('game.paga2.diplomacy.weakness',return_value=0.0):own=diplomacy.relation_options(c,IDS)
        peace=next(o for o in own if o.action=='PEACE')
        for o in (accept,reject,peace):score(o,c)
        self.assertGreater(accept.score,reject.score)
        self.assertGreaterEqual(accept.score,peace.score-1)  # spójnie: kto proponuje pokój, ten go przyjmuje


    def test_threat_from_enemy_favours_peace_and_heavy_losses_outweigh_revenge(self):
        # 14 Nov 2026 (przypadek Tunganirii): zagrożenie ze strony przeciwnika nie może premiować odrzucenia pokoju.
        rows=[NS(id=7,source_country_id=3,source_country_name='C',kind='PEACE',proposed_relation_id=None,target_country_id=1,expected_relation_id=1,expected_state_id=1,expected_audit_id=1)]
        c=dctx({3:{'relation':'wrogie','state':'wojnakinetyczna'}},traits={'agreeableness':46,'revenge':73,'militarism':70},priorities=['offensive_army','welfare'])
        c.perception=lambda other:{'trust':0,'threat':100}
        c.history=lambda other:{'hostile_from':3,'hostile_to':0,'friendly':0}
        with patch('game.paga2.war_losses.current_war',return_value=(72.0,{'bases':24,'factories':0,'power':0,'infrastructure':0,'nuclear':0},9)):
            accept,reject=self.proposals(c,rows)
        self.assertTrue(accept.payload['peace'])
        for o in (accept,reject):score(o,c)
        self.assertNotIn('zagrożenie',reject.factors['powiązania'])
        self.assertGreater(accept.factors['powiązania']['zagrożenie_skłania_do_pokoju'],0)
        self.assertGreater(accept.score,reject.score)

class IntelligenceTests(unittest.TestCase):
    def ictx(self,**kwargs):
        c=dctx(**kwargs);c.now=datetime(3000,1,1)
        return c

    def run_options(self,c,data,regions=(11,12)):
        with patch('game.paga2.intelligence.recent_missions',return_value=set()),patch('game.paga2.intelligence.target_regions',return_value=list(regions)):
            return intelligence.options_for(c,data)

    def test_recruit_when_no_free_agent_level_from_espionage(self):
        c=self.ictx(traits={'espionage':90})
        [recruit]=[o for o in self.run_options(c,{'budgetAvailable':'1000000000000','agents':[],'counterLevel':1}) if o.action=='RECRUIT_AGENT']
        self.assertEqual(recruit.payload,{'action':'recruit','level':6,'count':2})
        poor=self.ictx(traits={'espionage':90})
        [cheap]=[o for o in self.run_options(poor,{'budgetAvailable':'100000000','agents':[],'counterLevel':1}) if o.action=='RECRUIT_AGENT']
        self.assertLess(cheap.payload['level'],6)

    def test_scouting_enemies_first_and_hybrid_only_for_subversive(self):
        data={'budgetAvailable':'1e12','agents':[{'id':4,'level':3,'busy':False,'captured':False}],'counterLevel':1}
        c=self.ictx(relations={9:{'relation':'wrogie','state':'wojnakinetyczna'}},traits={'subversion':10})
        options=self.run_options(c,data)
        scouts=[o for o in options if o.action.startswith('SCOUT_')]
        self.assertEqual(scouts[0].target,9);self.assertEqual(scouts[0].payload['kind'],'bases');self.assertEqual(scouts[0].payload['agent_id'],4)
        self.assertFalse([o for o in options if o.action.startswith('HYBRID_')])
        subversive=self.ictx(relations={9:{'relation':'wrogie','state':'wojnakinetyczna'}},traits={'subversion':90})
        hybrid=[o for o in self.run_options(subversive,data) if o.action.startswith('HYBRID_')]
        self.assertTrue(hybrid);self.assertEqual(hybrid[0].stance,'hostile')

    def test_country_warehouse_scout_uses_agent_price_and_no_region(self):
        c=self.ictx(traits={'subversion':10})
        c.world_summary=lambda:{'neighbor_countries':[9]}
        data={'budgetAvailable':'1e12','agents':[{'id':4,'level':2,'busy':False}],'counterLevel':1}
        with patch('game.paga2.intelligence.recent_missions',return_value={(9,'resources'),(9,'infrastructure')}),patch('game.paga2.intelligence.target_regions',side_effect=AssertionError('Warehouse mission must not choose a region')):
            scouts=[o for o in intelligence.options_for(c,data) if o.action=='SCOUT_warehouses']
        self.assertEqual(len(scouts),1)
        self.assertEqual(scouts[0].cost,200000000)
        self.assertEqual(scouts[0].payload['country_id'],9)
        self.assertNotIn('region_id',scouts[0].payload)

    def test_counterintelligence_after_hybrid_attack(self):
        c=self.ictx();c.memory['actions_against_us']=[{'kind':'HYBRID_DETECTED'}]
        [counter]=[o for o in self.run_options(c,{'budgetAvailable':'1e12','agents':[{'id':1,'level':1,'busy':True}],'counterLevel':2}) if o.action=='COUNTER_UPGRADE']
        self.assertEqual(counter.payload,{'action':'counter_upgrade','expected_level':2})


class ExecuteTests(unittest.TestCase):
    def test_diplomacy_uses_player_forms(self):
        c=dctx();calls=[];c.call=lambda path,**kw:(calls.append((path,kw.get('form'))) or (201,{}))
        from game.paga2.scoring import Option
        diplomacy.execute(c,Option('x','diplomacy','RELATION_IMPROVE','x',payload={'kind':'RELATION','target_id':2,'relation_id':7}))
        diplomacy.execute(c,Option('y','diplomacy','PROPOSAL_REJECT','y',payload={'proposal_id':5}))
        self.assertEqual(calls[0],('/game/dyplomacja/akcje',{'kind':'RELATION','target_id':'2','relation_id':'7'}))
        self.assertEqual(calls[1],('/game/dyplomacja/propozycje/5/decyzja',{'decision':'reject'}))


if __name__=='__main__':unittest.main()


class JoinWarDecisionTests(unittest.TestCase):
    def test_loyal_interventionist_strong_ally_accepts_more_readily(self):
        from unittest.mock import patch
        from game.paga2 import diplomacy
        def base(traits,power):
            c=dctx(traits=traits);c.situation['at_war']=[]
            with patch.object(diplomacy,'powers',return_value=power):return diplomacy.join_terms(c,9)['base']
        loyal=base({'alliance_loyalty':95,'interventionism':90},(5000,4,1000))
        aloof=base({'alliance_loyalty':10,'interventionism':10},(5000,4,1000))
        weak=base({'alliance_loyalty':95,'interventionism':90},(100,0,5000))
        self.assertGreater(loyal,0);self.assertLess(aloof,0);self.assertGreater(loyal,weak)


class JoinWarCapabilityTests(unittest.TestCase):
    """16 Nov 2026: przyjęcie prośby o dołączenie do wojny wymaga zdolności do wojny z wrogiem (jak wypowiedzenie)."""
    def test_accept_blocked_without_capability_and_reject_still_possible(self):
        from game.paga2.scoring import Option
        c=dctx()
        # 21 Nov 2026: warunki A/B/C (game.paga2.war_plans.join_blockers) — odmowa z uzasadnieniem, odrzucenie nadal możliwe
        accept=Option('a','diplomacy','PROPOSAL_ACCEPT','x',payload={'proposal_id':1,'group':'proposal:1','required':True,'join_blockers':['A. Możliwości militarne poniżej 80%.']})
        reject=Option('r','diplomacy','PROPOSAL_REJECT','x',payload={'proposal_id':1,'group':'proposal:1','required':True})
        self.assertIn('Odmowa udziału w wojnie sojusznika: A.',diplomacy.check(c,accept))
        self.assertIsNone(diplomacy.check(c,reject))

    def test_capability_uses_war_rules(self):
        c=dctx()
        with patch('game.paga2.defense._forces',return_value='F'),patch('game.paga2.war.war_screen',return_value={}),\
             patch('game.paga2.war.war_capability',return_value={'able':False,'notes':['n'],'bonus':0.0,'distant':True}) as cap:
            self.assertFalse(diplomacy.join_capability(c,9)['able'])
        cap.assert_called_once_with(c,'F',{},9)
