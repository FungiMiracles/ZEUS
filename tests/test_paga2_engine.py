"""PAGA2 etap 3 — silnik decyzji: punktacja, kontrola zasobów, wybór z randomizerem, budżet, wyzwalacze, harmonogram
oraz wyłączenie dotychczasowych mechanizmów (modele AI tylko forum / wiadomości / pożyczki; stary silnik regułowy)."""
import unittest
from datetime import datetime,timedelta
from decimal import Decimal
from unittest.mock import patch
from sqlalchemy import select
from extensions import db
from game.paga2 import catalog
from game.paga2.scoring import Option,score,check_resources,limits
from game.paga2.models import Paga2Control,Paga2Profile,Paga2Decision,Paga2RandomDraw,Paga2CountryState
from test_paga2_foundation import Paga2Fixture,profile_data


class FakeCtx:
    """Minimalny kontekst decyzji (bez bazy) do testów punktacji i budżetu."""
    def __init__(self,traits=None,priorities=('trade',),categories=('economic',),level='peace',sectors=None,stocks=None,relationships=None,perception=None,history=None,allies=()):
        from game.paga2.situation import MULTIPLIERS
        self.traits={key:50 for key in catalog.TRAITS};self.traits.update(traits or {})
        self.priorities=list(priorities);self.categories=list(categories)
        self.situation={'level':level,'multipliers':MULTIPLIERS[level],'allies':list(allies)}
        self.limits=limits(self.traits);self.spent={};self.used_resources={};self.request_key='test'
        self._sectors=sectors or {};self._stocks=stocks or {};self.relationships=relationships or {}
        self._perception=perception or {};self._history=history or {}
        self.mode='CYCLIC';self.calls=[];self.responses=[]
    def available(self,sector):return self._sectors.get(sector,0)-self.spent.get(sector,0)
    def sector_start(self,sector):return self._sectors.get(sector,0)
    def stock(self,resource):return self._stocks.get(resource,0)-self.used_resources.get(resource,0)
    def perception(self,other):return self._perception.get(other,{'trust':50,'threat':20})
    def history(self,other):return self._history.get(other,{'hostile_from':0,'hostile_to':0,'friendly':0})
    def passive_bonus(self):return 5.0
    def call(self,path,*,method='POST',json=None,form=None):
        self.calls.append((path,json));return self.responses.pop(0)


class ScoringTests(unittest.TestCase):
    def test_priority_position_and_war_multiplier(self):
        ctx=FakeCtx(priorities=['defensive_army','environment'])
        army=score(Option('a','defense','BUILD','armia',effects={'defensive_army':1}),ctx)
        green=score(Option('b','economy','FILTER','środowisko',effects={'environment':1}),ctx)
        self.assertGreater(army.score,green.score)  # pierwszy priorytet waży więcej
        war=FakeCtx(priorities=['environment','defensive_army'],level='war')
        army=score(Option('a','defense','BUILD','armia',effects={'defensive_army':1}),war)
        green=score(Option('b','economy','FILTER','środowisko',effects={'environment':1}),war)
        self.assertGreater(army.score,green.score)  # w czasie wojny armia ważniejsza niż ochrona środowiska

    def test_traits_and_categories_shape_the_score(self):
        option=lambda:Option('x','war','ATTACK','atak',traits={'militarism':1,'agreeableness':-1},categories={'imperialist':1})
        hawk=score(option(),FakeCtx(traits={'militarism':90,'agreeableness':10},categories=['imperialist']))
        dove=score(option(),FakeCtx(traits={'militarism':10,'agreeableness':90},categories=['welfare']))
        self.assertGreater(hawk.score,dove.score+20)
        self.assertIn('cechy',hawk.factors);self.assertIn('charakter',hawk.factors)

    def test_historical_ally_discourages_hostility_and_revenge_encourages_it(self):
        hostile=lambda:Option('h','war','ATTACK','atak',target=7,stance='hostile')
        ally=score(hostile(),FakeCtx(relationships={7:{'status':'historical_ally'}},traits={'alliance_loyalty':90}))
        neutral=score(hostile(),FakeCtx())
        self.assertLess(ally.score,neutral.score-20)
        attacked=score(hostile(),FakeCtx(traits={'revenge':100},history={7:{'hostile_from':3,'hostile_to':0,'friendly':0}},perception={7:{'trust':20,'threat':80}}))
        self.assertGreater(attacked.score,neutral.score+10)
        satellite=score(Option('f','diplomacy','IMPROVE','poprawa',target=7,stance='friendly'),FakeCtx(relationships={7:{'status':'satellite','role':'satellite'}}))
        self.assertGreater(satellite.score,score(Option('f','diplomacy','IMPROVE','poprawa',target=7,stance='friendly'),FakeCtx()).score)

    def test_resource_prudence_limits_depend_on_fiscal_conservatism(self):
        careful=FakeCtx(traits={'fiscal_conservatism':100},sectors={'infrastructure':1000})
        bold=FakeCtx(traits={'fiscal_conservatism':0},sectors={'infrastructure':1000})
        option=Option('b','economy','BUILD','fabryka',cost=400,sector='infrastructure')
        self.assertIn('Nierozważny',check_resources(option,careful))  # limit 20% środków
        self.assertIsNone(check_resources(option,bold))                 # limit 60%
        self.assertIn('Za mało środków',check_resources(Option('c','economy','BUILD','x',cost=2000,sector='infrastructure'),bold))
        self.assertIn('Nierozważne zużycie',check_resources(Option('d','trade','BUY','x',resources={'wegiel':90}),FakeCtx(stocks={'wegiel':100})))
        self.assertLess(score(Option('e','economy','BUILD','x',cost=500,sector='infrastructure'),bold).score,score(Option('f','economy','BUILD','x',cost=50,sector='infrastructure'),bold).score)


class BudgetTests(unittest.TestCase):
    def state(self,rate,**extra):
        rate=Decimal(str(rate))
        tax=rate*Decimal(10**9)
        data={'approved':False,'pit_rate':str(rate),'tax_total':str(tax),'budget_total':str(tax+Decimal(10**9)),'tax_penalty':0 if rate<=27 else int((rate-20)/10-Decimal('0.7')+Decimal('0.5')),
              'allocations':{'social_policy':str(tax*Decimal('0.14'))},'benefits':{'expected':{'children':'3000000000','seniors':'3000000000'},'carry_in':'0'},
              'revenue_basis':{'trust':40,'satisfaction':30},'year':3001,'period':1,'basis_token':'t'*64,'has_previous':True,'shares':{'armed_forces':'10','social_policy':'14'}}
        data.update(extra);return data

    def test_sector_weights_follow_profile_and_war(self):
        from game.paga2.budget import plan_shares
        peace=plan_shares(FakeCtx(priorities=['welfare'],categories=['welfare'],traits={'prosociality':90}),None)
        war=plan_shares(FakeCtx(priorities=['welfare'],categories=['welfare'],traits={'prosociality':90},level='war'),None)
        self.assertGreater(war['armed_forces'],peace['armed_forces']);self.assertLess(war['environment'],peace['environment'])
        self.assertLessEqual(sum(peace.values()),Decimal(100))
        smooth=plan_shares(FakeCtx(traits={'predictability':100}),{'armed_forces':'50'})
        self.assertGreater(smooth['armed_forces'],plan_shares(FakeCtx(),None)['armed_forces'])

    def test_penalty_free_rate_uses_game_formula(self):
        from game.paga2.budget import penalty_free_rate
        from game.general_tax import tax_penalty
        limit=penalty_free_rate({'revenue_basis':{'trust':40,'satisfaction':30}})
        self.assertEqual(tax_penalty({'trust':40,'satisfaction':30},limit),0)
        self.assertGreater(tax_penalty({'trust':40,'satisfaction':30},limit+Decimal('0.5')),0)
        self.assertIsNone(penalty_free_rate({}))

    def test_first_budget_may_reach_penalty_free_rate_at_once(self):
        from game.paga2 import budget
        ctx=FakeCtx(traits={'strategic_flexibility':0,'fiscal_conservatism':100,'prosociality':0})
        first=self.state(5,has_previous=False)
        ctx.responses=[(200,{'state':first})]+[(200,{'state':first})]*20
        rates=sorted(Decimal(o.payload['pit_rate']) for o in budget.propose(ctx))
        self.assertEqual(rates[-1],budget.penalty_free_rate(first))   # mimo kroku 3 pkt: od razu do stawki bez kary

    def test_tax_change_per_half_year_is_limited(self):
        from game.paga2 import budget
        ctx=FakeCtx(traits={'strategic_flexibility':0,'fiscal_conservatism':100,'prosociality':0})
        ctx.responses=[(200,{'state':self.state(5)})]+[(200,{'state':self.state(5)})]*20
        options=budget.propose(ctx)
        rates=sorted(Decimal(o.payload['pit_rate']) for o in options)
        self.assertEqual(budget.max_step(ctx),Decimal('3'))
        self.assertEqual(rates,[Decimal('2.0'),Decimal('3.5'),Decimal('5.0'),Decimal('6.5'),Decimal('8.0')])  # 5% ± 3 pkt, wielokrotności 0,5
        self.assertTrue(all(abs(rate-Decimal(5))<=3 for rate in rates))

    def test_payments_never_exceed_social_budget(self):
        from game.paga2.budget import payments
        paid,covered=payments({'allocations':{'social_policy':'4000000000'},'benefits':{'expected':{'children':'3000000000','seniors':'3000000000'},'carry_in':'1000000000'}})
        self.assertEqual(sum(Decimal(v) for v in paid.values()),Decimal('5000000000.00'));self.assertAlmostEqual(float(covered),5/6,places=3)
        paid,covered=payments({'allocations':{'social_policy':'9000000000'},'benefits':{'expected':{'children':'1','seniors':'2'},'carry_in':'0'}})
        self.assertEqual(paid,{'children':'1.00','seniors':'2.00'});self.assertEqual(covered,1)

    def test_social_floor_takes_from_other_sectors(self):
        from game.paga2.budget import with_social_floor,SECTORS
        shares={s:Decimal('9') for s in SECTORS}
        new,changed=with_social_floor(shares,{'budget_total':'100000000000','benefits':{'expected':{'children':'10000000000','seniors':'10000000000'},'carry_in':'0'}},1.0)
        self.assertTrue(changed);self.assertGreaterEqual(new['social_policy'],Decimal('20'));self.assertLessEqual(sum(new.values()),sum(shares.values()))

    def test_propose_previews_variants_and_execute_approves(self):
        from game.paga2 import budget
        ctx=FakeCtx(traits={'prosociality':10,'fiscal_conservatism':90})
        previews=[self.state(10)]+[self.state(r) for r in ('10','21','24','27','30','33')]*2
        ctx.responses=[(200,{'state':item}) for item in previews]
        options=budget.propose(ctx)
        self.assertTrue(options);self.assertTrue(all(o.payload['group']=='budget' for o in options))
        self.assertEqual(ctx.calls[0],('/game/finanse/podglad',{}))
        for option in options:score(option,ctx)
        best=max(options,key=lambda o:o.score)
        self.assertTrue(any('PIT' in note for note in best.notes))
        ctx.responses=[(200,{'ok':True,'budget_id':5,'already_approved':False})]
        result=budget.execute(ctx,best)
        self.assertEqual(result['budget_id'],5)
        path,body=ctx.calls[-1]
        self.assertEqual(path,'/game/finanse/zatwierdz');self.assertEqual(body['basis_token'],'t'*64);self.assertFalse(body['repeat_previous'])
        self.assertEqual(set(body['benefits']),{'children','seniors'})

    def test_no_variants_when_budget_already_approved(self):
        from game.paga2 import budget
        ctx=FakeCtx();ctx.responses=[(200,{'state':{'approved':True}})]
        self.assertEqual(budget.propose(ctx),[])


def adapter(name,options,results=None,modes=('CYCLIC','IMMEDIATE','BUDGET'),check=None):
    from game.paga2.engine import Adapter
    executed=[]
    def execute(ctx,option):
        executed.append(option.key)
        return (results or {}).get(option.key,{'status':200})
    item=Adapter(name=name,modes=modes,propose=lambda ctx:[Option(**o) for o in options],execute=execute,check=check)
    return item,executed


class EngineTests(Paga2Fixture,unittest.TestCase):
    def setUp(self):
        super().setUp()
        from game.paga_relationships import PagaRelationship
        from models import Stosunki,DictStosunkiRelacja,DictStosunkiStan
        for model in (PagaRelationship,Paga2CountryState,Stosunki,DictStosunkiRelacja,DictStosunkiStan):model.__table__.create(db.engine,checkfirst=True)

    def run_engine(self,adapters,mode='CYCLIC',key=None):
        from game.paga2.engine import run
        return run(self.app,1,mode,'test',request_key=key,adapters=adapters,now=datetime(3000,1,1))

    def decision(self,id):return db.session.get(Paga2Decision,id,populate_existing=True)

    def test_best_option_is_executed_and_logged_with_all_options(self):
        good,executed=adapter('a',[dict(key='good',domain='economy',action='BUILD',label='dobra',effects={'trade':1},base=20),
                                   dict(key='weak',domain='economy',action='BUILD',label='słaba',effects={'trade':-1})])
        row=self.decision(self.run_engine([good]))
        self.assertEqual(row.status,'EXECUTED');self.assertEqual(executed,['good']);self.assertEqual(row.action,'BUILD')
        keys=[o['key'] for o in row.options];self.assertEqual(set(keys),{'good','weak','passive'})
        self.assertTrue(next(o for o in row.options if o['key']=='good')['chosen'])
        self.assertIn('profil',row.inputs);self.assertIn('sytuacja',row.inputs);self.assertIn('pamięć',row.inputs)

    def test_passive_when_nothing_scores_above_waiting(self):
        weak,executed=adapter('a',[dict(key='weak',domain='economy',action='BUILD',label='słaba',effects={'trade':-1})])
        row=self.decision(self.run_engine([weak]))
        self.assertEqual(row.status,'PASSIVE');self.assertEqual(executed,[]);self.assertEqual(row.action,'PASSIVE')

    def test_budget_mode_always_acts(self):
        weak,executed=adapter('b',[dict(key='budget:1',domain='finance',action='BUDGET_APPROVE',label='budżet',base=-40,payload={'group':'budget'}),
                                   dict(key='budget:2',domain='finance',action='BUDGET_APPROVE',label='budżet 2',base=-45,payload={'group':'budget'})],modes=('BUDGET',))
        row=self.decision(self.run_engine([weak],mode='BUDGET'))
        self.assertEqual(row.status,'EXECUTED');self.assertEqual(executed,['budget:1'])  # tylko jeden wariant z grupy

    def test_required_decision_acts_below_waiting_threshold_once_per_group(self):
        item,executed=adapter('a',[dict(key='accept',domain='diplomacy',action='PROPOSAL_ACCEPT',label='a',base=-30,payload={'group':'proposal:1','required':True}),
                                   dict(key='reject',domain='diplomacy',action='PROPOSAL_REJECT',label='r',base=-35,payload={'group':'proposal:1','required':True}),
                                   dict(key='other',domain='economy',action='X',label='x',base=-30)])
        row=self.decision(self.run_engine([item]))
        self.assertEqual(executed,['accept']);self.assertEqual(row.status,'EXECUTED')  # odpowiedź udzielona, choć poniżej progu; zwykła opcja nie

    def test_required_decisions_do_not_use_the_action_limit(self):
        profile=db.session.get(Paga2Profile,1);profile.traits={**profile.traits,'ambition':0};db.session.commit()   # limit: 1 działanie
        item,executed=adapter('a',[dict(key='war',domain='war',action='STRIKE',label='w',base=40),
                                   dict(key='answer',domain='diplomacy',action='PROPOSAL_REJECT',label='p',base=5,payload={'group':'proposal:9','required':True})])
        self.run_engine([item])
        self.assertEqual(sorted(executed),['answer','war'])   # odpowiedź na propozycję zawsze, a limit dla zwykłych działań

    def test_rejected_by_game_falls_back_to_next_option(self):
        item,executed=adapter('a',[dict(key='first',domain='economy',action='A',label='a',base=30),dict(key='second',domain='economy',action='B',label='b',base=25)],
                              results={'first':{'status':400,'error':'Za mało surowców'}})
        row=self.decision(self.run_engine([item]))
        self.assertEqual(executed,['first','second']);self.assertEqual(row.status,'EXECUTED');self.assertEqual(row.action,'B')
        first=next(o for o in row.options if o['key']=='first')
        self.assertIn('Za mało surowców',first['blocked'])

    def test_tie_is_resolved_by_randomizer_and_counted(self):
        db.session.get(Paga2Profile,1).traits={**db.session.get(Paga2Profile,1).traits,'predictability':100,'ambition':0};db.session.commit()
        item,executed=adapter('a',[dict(key='x',domain='economy',action='X',label='x',base=30),dict(key='y',domain='economy',action='Y',label='y',base=30)])
        row=self.decision(self.run_engine([item]))
        self.assertTrue(row.randomized);self.assertEqual(len(executed),1)
        draw=db.session.scalar(select(Paga2RandomDraw))
        self.assertEqual(draw.decision_key,row.request_key);self.assertIn(draw.chosen,('x','y'))

    def test_infeasible_option_is_recorded_not_executed(self):
        item,executed=adapter('a',[dict(key='costly',domain='economy',action='BUILD',label='drogo',base=40,cost=10**15,sector='infrastructure')])
        row=self.decision(self.run_engine([item]))
        self.assertEqual(executed,[]);self.assertEqual(row.status,'PASSIVE')
        self.assertFalse(next(o for o in row.options if o['key']=='costly')['feasible'])

    def test_disabled_paga2_or_autonomy_does_nothing_and_key_deduplicates(self):
        item,executed=adapter('a',[dict(key='good',domain='economy',action='BUILD',label='dobra',base=30)])
        first=self.run_engine([item],key='k1');self.assertEqual(self.run_engine([item],key='k1'),first);self.assertEqual(executed,['good'])
        db.session.get(Paga2Control,1).enabled=False;db.session.commit()
        self.assertIsNone(self.run_engine([item],key='k2'))
        db.session.get(Paga2Control,1).enabled=True;db.session.get(Paga2Profile,1).autonomy_enabled=False;db.session.commit()
        self.assertIsNone(self.run_engine([item],key='k3'))

    def test_adapter_error_is_recorded_and_others_continue(self):
        from game.paga2.engine import Adapter
        def broken(ctx):raise RuntimeError('awaria')
        good,executed=adapter('ok',[dict(key='good',domain='economy',action='BUILD',label='dobra',base=30)])
        row=self.decision(self.run_engine([Adapter('broken',('CYCLIC',),broken,lambda c,o:{}),good]))
        self.assertEqual(executed,['good']);self.assertIn('awaria',' '.join(row.inputs['błędy_adapterów']))

    def test_situation_war_from_relations(self):
        from models import Stosunki,DictStosunkiRelacja,DictStosunkiStan
        from game.paga2.situation import assess
        db.session.add_all([DictStosunkiRelacja(relacja_id=91,relacja_nazwa='Wrogie'),DictStosunkiStan(stan_id=91,stan_nazwa='Wojna kinetyczna')]);db.session.flush()
        db.session.add(Stosunki(PANSTWO_ID=1,PANSTWO_ID2=2,relacja_id=91,stan_id=91));db.session.commit()
        situation=assess(db.session,1,datetime(3000,1,1))
        self.assertEqual(situation['level'],'war');self.assertEqual(situation['at_war'],[2]);self.assertGreater(situation['multipliers']['defensive_army'],1)

    # ---- wyzwalacze trybu doraźnego ----
    def test_triggers_classify_and_order_security_first(self):
        from game.forum_models import GameNotification
        from game.communication_models import PrivateMessage
        from game.paga2.triggers import collect,security,initial_cursors
        from game.paga2.gateway import actor_for
        actor=actor_for(db.session,1);db.session.commit()
        db.session.add_all([GameNotification(user_id=actor.user_id,notification_type='SYSTEM',system_text='Wtargnięcie: armia państwa X wkroczyła na nasze terytorium.'),
                            GameNotification(user_id=actor.user_id,notification_type='SYSTEM',system_text='Coś zwyczajnego')])
        for model in (PrivateMessage,):model.__table__.create(db.engine,checkfirst=True)
        db.session.commit()
        state=Paga2CountryState(panstwo_id=1,notification_cursor=0,message_cursor=0)
        items=collect(db.session,1,state,actor.user_id)
        self.assertEqual(items[0]['kind'],'land_invasion');self.assertEqual(len(security(items)),1)
        self.assertEqual(collect(db.session,1,state,actor.user_id),[])  # kursor przesunięty
        self.assertEqual(initial_cursors(db.session,1,actor.user_id)[0],state.notification_cursor)

    # ---- harmonogram ----
    def test_scheduler_runs_budget_immediate_and_cyclic_modes(self):
        from engine import paga2_scheduler
        from game.communication_models import PrivateMessage
        PrivateMessage.__table__.create(db.engine,checkfirst=True)
        calls=[]
        def fake_run(app,country,mode,trigger,**kwargs):calls.append((mode,kwargs.get('request_key')));return None
        control=db.session.get(Paga2Control,1)
        now=datetime(2026,11,12,12,0)
        with patch('game.paga2.engine.run',fake_run),patch('engine.paga2_scheduler.budget_needed',return_value=(3001,1)):
            paga2_scheduler.process_country(self.app,1,control,now)
            state=db.session.get(Paga2CountryState,1,populate_existing=True)
            state.next_cycle_at=now-timedelta(minutes=1);db.session.commit()
            paga2_scheduler.process_country(self.app,1,control,now)
        modes=[mode for mode,key in calls]
        self.assertEqual(modes.count('BUDGET'),2);self.assertIn('CYCLIC',modes)
        self.assertGreater(db.session.get(Paga2CountryState,1,populate_existing=True).next_cycle_at,now)

    def test_scheduler_does_nothing_when_paga2_disabled(self):
        from engine import paga2_scheduler
        from tempfile import TemporaryDirectory
        folder=TemporaryDirectory();self.addCleanup(folder.cleanup);self.app.root_path=folder.name
        db.session.get(Paga2Control,1).enabled=False;db.session.commit()
        with patch('engine.paga2_scheduler.process_country') as process:paga2_scheduler.run_tick(self.app)
        process.assert_not_called()


class RetiredMechanismTests(unittest.TestCase):
    """Bez flagi testowej PAGA_LEGACY_ENGINES: modele AI tylko forum / wiadomości / pożyczki; stary silnik nie decyduje."""
    def setUp(self):
        from flask import Flask
        self.app=Flask(__name__);self.app.config.update(TESTING=True,SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        db.init_app(self.app);self.ctx=self.app.app_context();self.ctx.push()
        from game.paga_ai_models import PagaAiJob
        PagaAiJob.__table__.create(db.engine)
    def tearDown(self):db.session.remove();db.engine.dispose();self.ctx.pop()

    def test_llm_task_scope(self):
        from game.paga_ai_tasks import enqueue,LLM_KINDS,llm_allowed
        # 19 Nov 2026: decyzje o pożyczkach podejmuje wyłącznie PAGA2 — loan_event poza zakresem modeli AI.
        self.assertEqual(LLM_KINDS,{'private_message','forum_reply','forum_mention','forum_announcement','private_initiative'})
        for kind in ('loan_event','budget','strategic_review','war_declared','under_attack','diplomatic_proposal','intent','conditional_plan','research_available'):
            with self.subTest(kind=kind):self.assertIsNone(enqueue(db.session,1,kind,'k-'+kind,0));self.assertFalse(llm_allowed(kind))
        for kind in LLM_KINDS:
            with self.subTest(kind=kind):self.assertIsNotNone(enqueue(db.session,1,kind,'k-'+kind,0))

    def test_pick_cancels_out_of_scope_tasks(self):
        from game.paga_ai_models import PagaAiJob,PagaAiIdentity
        from game.paga_ai_tasks import pick
        PagaAiIdentity.__table__.create(db.engine)
        db.session.add_all([PagaAiJob(country_id=1,trigger='old',revision=0,status='PENDING',kind='budget',priority=10,journal=[],context={}),
                            PagaAiJob(country_id=1,trigger='pm',revision=0,status='PENDING',kind='private_message',priority=20,journal=[],context={})])
        db.session.commit()
        class Control:review_interval_minutes=180
        task=pick(db.session,Control,datetime.utcnow(),[1])
        self.assertEqual(task.kind,'private_message')
        self.assertEqual(db.session.scalar(select(PagaAiJob).where(PagaAiJob.trigger=='old')).status,'CANCELLED')

    def test_communication_tasks_cannot_change_diplomacy_or_strategy(self):
        from game.paga_ai_context import DOMAINS
        self.assertEqual(DOMAINS['communication']['writes'],['game_messages.send:POST','game_forum.page:POST'])
        self.assertEqual(DOMAINS['loans']['writes'],['game_loans.change:POST'])

    def test_rule_engine_never_decides(self):
        from game.autonomy_engine import analyze
        self.assertIsNone(analyze(db.session,1,datetime(3000,1,1)))


if __name__=='__main__':unittest.main()
