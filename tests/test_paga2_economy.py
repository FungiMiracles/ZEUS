"""PAGA2 etap 5 — gospodarka: wycena, handel (opłaty, blokady portów, sprzedaż nadwyżek, zakupy), przemysł
(naprawy, rozbudowa, filtry, likwidacja), finanse (przesunięcia, pożyczki, zdolność do udzielenia pożyczki)."""
import unittest
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch
from extensions import db
from game.paga2 import pricing,trade,industry,finance
from game.paga2.scoring import score
from test_paga2_engine import FakeCtx
from test_paga2_planner import FakeHoldings


class EconomyCtx(FakeCtx):
    def __init__(self,screens=None,holdings=None,**kwargs):
        super().__init__(**kwargs);self.screens=screens or {};self._holdings=holdings or FakeHoldings();self.country_id=1;self.now=datetime(3000,1,1)
        self.situation.setdefault('at_war',[]);self.situation.setdefault('hostile',[])
    def screen(self,name):return {'status':200,'data':self.screens.get(name,{})}


def trade_screen(**extra):
    data={'ownPorts':True,'ownTariff':'0','countries':{'1':'My','2':'B','3':'C','4':'Wróg'},'portAccess':{'block_foreign':False,'blocked_countries':[]},
          'ports':{'10':{'countryId':1,'rate':'0','allowed':True},'20':{'countryId':2,'rate':'5','allowed':True}},'reserve':'100000000000',
          'warehouse':{'wegiel_kamienny':{'available':500},'tanks':{'available':1000},'zelazo':{'available':0}},'offers':[]}
    data.update(extra);return data


class PricingTests(unittest.TestCase):
    def test_unit_values_follow_production_costs(self):
        self.assertAlmostEqual(pricing.unit_value('wegiel_kamienny'),2e9/73,delta=1)
        self.assertGreater(pricing.unit_value('tanks'),pricing.unit_value('zelazo')*10)  # fabryka + surowce wejściowe
        self.assertEqual(pricing.unit_value('interceptor_ammunition'),15000)

    def test_market_factor_needs_two_offers_and_is_bounded(self):
        coal=pricing.unit_value('wegiel_kamienny')
        offers=[{'cargo':{'wegiel_kamienny':10},'price':str(coal*10*2)},{'cargo':{'wegiel_kamienny':10},'price':str(coal*10*2)}]
        self.assertAlmostEqual(pricing.market_factors(offers)['wegiel_kamienny'],2.0)
        self.assertEqual(pricing.market_factors(offers[:1]),{})
        self.assertAlmostEqual(pricing.reference('wegiel_kamienny',{'wegiel_kamienny':10}),coal*3)

    def test_operating_reserve(self):
        h=FakeHoldings(factories=['tanks'],plants=['coal'])
        need=pricing.consumption(h,days=70)
        self.assertEqual(need['zelazo'],100);self.assertEqual(need['wegiel_kamienny'],70)


class TradeTests(unittest.TestCase):
    def test_tariff_and_port_blockade_follow_character_and_relations(self):
        ctx=EconomyCtx(screens={'trade':trade_screen()},traits={'isolationism':90,'trade_propensity':10,'revenge':80},relationships={3:{'status':'historical_hostile'}})
        ctx.situation.update(at_war=[4],hostile=[2],allies=[2]);ctx._policy_history=[]
        options={o.action:o for o in trade.policy_options(ctx,trade_screen())}
        self.assertGreater(int(options['PORT_TARIFF'].payload['rate']),10)
        self.assertEqual(options['PORT_ACCESS'].payload['blocked_countries'],[3,4])  # sojusznika 2 nie wolno blokować
        open_ctx=EconomyCtx(traits={'isolationism':0,'trade_propensity':100,'solidarity':100});open_ctx._policy_history=[]
        rate=int(trade.policy_options(open_ctx,trade_screen(ownTariff='20'))[0].payload['rate'])
        self.assertLess(rate,20)
        self.assertEqual(trade.policy_options(open_ctx,trade_screen(ownPorts=False)),[])

    def test_port_policy_is_required_and_has_half_year_cooldown(self):
        ctx=EconomyCtx(traits={'isolationism':90,'trade_propensity':10});ctx._policy_history=[]
        ctx.situation.update(at_war=[4],hostile=[],allies=[])
        options={o.action:o for o in trade.policy_options(ctx,trade_screen())}
        self.assertTrue(options['PORT_TARIFF'].payload['required']);self.assertTrue(options['PORT_ACCESS'].payload['required'])
        ctx._policy_history=[('PORT_TARIFF',None,None),('PORT_ACCESS',None,None)]
        options={o.action:o for o in trade.policy_options(ctx,trade_screen())}
        self.assertNotIn('PORT_TARIFF',options)                       # zmiana stawki najwyżej raz na 180 dni
        self.assertIn('PORT_ACCESS',options)                          # nowa wojna: blokada portów od razu

    def test_surplus_offer_hidden_from_enemies_and_never_the_army(self):
        ctx=EconomyCtx(screens={'trade':trade_screen()},traits={'trade_propensity':100})
        ctx.situation.update(at_war=[4])
        [offer]=trade.sell_options(ctx,trade_screen(),{})
        self.assertEqual(offer.payload['cargo'],{'wegiel_kamienny':400})  # 80% nadwyżki; czołgi zostają w armii
        self.assertEqual(offer.payload['excluded'],[4])
        self.assertGreater(Decimal(offer.payload['price']),Decimal(str(pricing.unit_value('wegiel_kamienny')*400)))

    def test_offer_has_no_port_or_transport(self):
        # 22 Nov 2026: oferta czeka w magazynie — port, transport i limit portu wybiera gra przy zakupie (game.trade_routes).
        ctx=EconomyCtx(screens={'trade':trade_screen()},traits={'trade_propensity':100})
        [offer]=trade.sell_options(ctx,trade_screen(),{})
        for key in ('port_id','departure_rate','transport'):self.assertNotIn(key,offer.payload)

    def test_buys_needed_goods_at_reasonable_price_from_non_hostile_sellers(self):
        iron=pricing.unit_value('zelazo')
        offers=[{'id':1,'sellerId':2,'seller':'B','cargo':{'zelazo':200},'price':str(iron*200*.9),'usable':True},
                {'id':2,'sellerId':3,'seller':'C','cargo':{'zelazo':200},'price':str(iron*200*5),'usable':True},
                {'id':3,'sellerId':4,'seller':'Wróg','cargo':{'zelazo':200},'price':str(iron*200*.5),'usable':True},
                {'id':4,'sellerId':2,'seller':'B','cargo':{'kamien':5},'price':'1','usable':True}]
        screen=trade_screen(offers=offers)
        ctx=EconomyCtx(screens={'trade':screen},holdings=FakeHoldings(factories=['tanks']))
        ctx.situation.update(at_war=[4])
        with patch('game.paga2.trade.planned_acquisitions',return_value=set()):options=trade.buy_options(ctx,screen,{})
        self.assertEqual([o.payload['offer_id'] for o in options],[1])
        self.assertEqual(options[0].sector,'reserve');self.assertEqual(options[0].target,2);self.assertEqual(options[0].stance,'friendly')
        self.assertEqual(options[0].payload['delivery'],'auto')   # 22 Nov 2026: najtańsza droga dostawy wybierana przez grę
        # Surowiec wskazany przez plan (zakup w handlu) jest potrzebny nawet bez fabryk.
        ctx=EconomyCtx(screens={'trade':screen});ctx.situation.update(at_war=[4])
        with patch('game.paga2.trade.planned_acquisitions',return_value={'zelazo'}):self.assertEqual([o.payload['offer_id'] for o in trade.buy_options(ctx,screen,{})],[1])


class PortRateTests(unittest.TestCase):
    def test_own_port_is_free_and_foreign_port_uses_its_tariff(self):
        # 14 Nov 2026: gra nie pobiera opłaty we własnym porcie; ekran pokazuje stawkę dla innych państw.
        from game.paga2.trade import port_rate,arrival_port
        data=trade_screen(ports={'10':{'countryId':1,'rate':'7','allowed':True},'20':{'countryId':2,'rate':'5','allowed':True}})
        self.assertEqual(port_rate(data,10,1),'0')
        self.assertEqual(port_rate(data,20,1),'5')
        self.assertEqual(arrival_port(data,1),(10,'0'))


class IndustryTests(unittest.TestCase):
    def run_propose(self,factories=(),plants=(),mines=(),deposits=None,holdings=None,traits=None):
        ctx=EconomyCtx(holdings=holdings or FakeHoldings(),traits=traits,priorities=['environment','production','infrastructure'])
        with patch('game.paga2.industry.objects',return_value=(list(factories),list(plants),list(mines),deposits or {})):
            return {o.action:o for o in industry.propose(ctx)}

    def test_repairs_filters_upgrades_and_liquidation(self):
        h=FakeHoldings(nodes={'air_filters':True,'waste_filters':True},energy=(0,50))
        options=self.run_propose(plants=[dict(id=1,kind='coal',level=1,health=1,filter=False,region=1,investment=3.1e9)],
                                 factories=[dict(id=2,kind='tanks',level=1,health=100,paused=True,filter=False,region=1),dict(id=3,kind='drones',level=1,health=0,paused=False,filter=True,region=1)],
                                 mines=[dict(id=4,resource='zloto',level=1,health=100,ready=True,region=1),dict(id=5,resource='kamien',level=1,health=100,ready=True,region=1)],
                                 deposits={4:100,5:0},holdings=h)
        self.assertAlmostEqual(options['POWER_REPAIR'].cost,3.1e9*2/3)
        self.assertEqual(options['AIR_FILTER'].sector,'environment');self.assertEqual(options['AIR_FILTER'].payload,{'action':'filter','category':'power','object_id':1})
        self.assertEqual(options['WASTE_FILTER'].payload['object_id'],2)
        self.assertEqual(options['FACTORY_RESUME'].payload['action'],'resume')
        self.assertEqual(options['FACTORY_REMOVE'].payload['object_id'],3)
        self.assertEqual(options['MINE_REMOVE'].payload['object_id'],5)          # złoże wyczerpane
        self.assertEqual(options['MINE_UPGRADE'].payload['object_id'],4)
        self.assertNotIn('POWER_UPGRADE',options)                                # najpierw naprawa

    def test_no_filters_without_technology_and_no_power_upgrade_without_deficit(self):
        options=self.run_propose(plants=[dict(id=1,kind='coal',level=1,health=3,filter=False,region=1,investment=1)],holdings=FakeHoldings(energy=(100,0)))
        self.assertEqual(options,{})

    def test_ecology_prefers_filters(self):
        h=FakeHoldings(nodes={'air_filters':True})
        plant=[dict(id=1,kind='coal',level=1,health=3,filter=False,region=1,investment=1)]
        green=self.run_propose(plants=plant,holdings=h,traits={'ecology':100,'industrialism':0})['AIR_FILTER']
        grey=self.run_propose(plants=plant,holdings=h,traits={'ecology':0,'industrialism':100})['AIR_FILTER']
        ctx=EconomyCtx(priorities=['environment']);self.assertGreater(score(green,EconomyCtx(priorities=['environment'],traits={'ecology':100})).score,score(grey,EconomyCtx(priorities=['environment'],traits={'ecology':0})).score)


class FinanceTests(unittest.TestCase):
    def test_transfer_to_sector_needed_by_plan_from_least_important_donor(self):
        ctx=EconomyCtx(screens={'finance':{'finance_state':{'budget_id':9,'can_transfer':True,'sector_transfers_allowed':True}}},priorities=['offensive_army','research'],
                       sectors={'research':1e9,'administration':2e10,'armed_forces':5e9,'reserve':0})
        with patch('game.paga2.finance.plan_needs',return_value={'research':4e9}):options=finance.transfer_options(ctx)
        [option]=options
        # 25 Nov 2026: bez sektora „Propaganda” — dawcą jest najmniej ważny sektor z nadwyżką (administracja)
        self.assertEqual((option.payload['source'],option.payload['destination'],option.payload['budget_id']),('administration','research',9))
        self.assertEqual(Decimal(option.payload['amount']),Decimal('4000000000.00'))

    def test_low_trust_allows_only_reserve_transfers(self):
        ctx=EconomyCtx(screens={'finance':{'finance_state':{'budget_id':9,'sector_transfers_allowed':False}}},sectors={'research':0,'propaganda':2e10,'reserve':1e10},traits={'fiscal_conservatism':0})
        with patch('game.paga2.finance.plan_needs',return_value={'research':4e9}):[option]=finance.transfer_options(ctx)
        self.assertEqual(option.payload['source'],'reserve')

    def test_war_moves_money_to_armed_forces(self):
        ctx=EconomyCtx(screens={'finance':{'finance_state':{'budget_id':9}}},level='war',sectors={'armed_forces':1e8,'propaganda':5e10,'research':5e10})
        with patch('game.paga2.finance.plan_needs',return_value={}):options=finance.transfer_options(ctx)
        self.assertEqual(options[0].payload['destination'],'armed_forces')

    def test_loan_request_needs_shortage_debt_tolerance_and_trusted_lender(self):
        screen={'reserve':'0','loans':[],'countries':{'2':'Przyjaciel','3':'Wróg'}}
        ctx=EconomyCtx(screens={'loans':screen},traits={'debt_tolerance':80},perception={2:{'trust':80},3:{'trust':80}},allies=[2])
        ctx.situation['at_war']=[3]
        with patch('game.paga2.finance.plan_needs',return_value={'infrastructure':2e10}):options=finance.loan_options(ctx)
        [request]=options
        self.assertEqual(request.payload['lender_id'],2);self.assertEqual(request.target,2)
        cautious=EconomyCtx(screens={'loans':screen},traits={'debt_tolerance':10})
        with patch('game.paga2.finance.plan_needs',return_value={'infrastructure':2e10}):self.assertEqual(finance.loan_options(cautious),[])

    def test_repay_only_after_half_a_year_and_from_surplus(self):
        loan={'id':7,'ownRequest':True,'status':'accepted','amount':'1000000000','lenderId':2,'lender':'B','createdAt':'2026-01-01T00:00:00Z'}
        screen={'reserve':'10000000000','loans':[loan],'countries':{}}
        ctx=EconomyCtx(screens={'loans':screen},traits={'fiscal_conservatism':90})
        with patch('game.paga2.finance.plan_needs',return_value={}),patch('game.paga2.finance.loan_age_days',return_value=200):
            self.assertEqual([o.action for o in finance.loan_options(ctx)],['LOAN_REPAY'])
        with patch('game.paga2.finance.plan_needs',return_value={}),patch('game.paga2.finance.loan_age_days',return_value=5):
            self.assertEqual(finance.loan_options(ctx),[])                       # świeża pożyczka nie jest od razu spłacana
        with patch('game.paga2.finance.plan_needs',return_value={'infrastructure':9.5e9}),patch('game.paga2.finance.loan_age_days',return_value=200):
            self.assertEqual(finance.loan_options(ctx),[])                       # rezerwa potrzebna na plany

    def test_no_new_request_with_outstanding_debt_or_after_refusal(self):
        base={'reserve':'0','countries':{'2':'Przyjaciel','3':'Drugi'}}
        kw=dict(traits={'debt_tolerance':60},perception={2:{'trust':80},3:{'trust':70}},allies=[2,3])
        with patch('game.paga2.finance.plan_needs',return_value={'infrastructure':2e10}),patch('game.paga2.finance.loan_age_days',return_value=10):
            debt=EconomyCtx(screens={'loans':{**base,'loans':[{'id':1,'ownRequest':True,'status':'accepted','amount':'1','lenderId':2}]}},**kw)
            self.assertFalse([o for o in finance.loan_options(debt) if o.action=='LOAN_REQUEST'])
            refused=EconomyCtx(screens={'loans':{**base,'loans':[{'id':1,'ownRequest':True,'status':'rejected','amount':'1','lenderId':2}]}},**kw)
            [request]=[o for o in finance.loan_options(refused) if o.action=='LOAN_REQUEST']
            self.assertEqual(request.payload['lender_id'],3)                    # odmawiający pomijany, prośba do innego państwa


class LoanCapacityTests(unittest.TestCase):
    def setUp(self):
        from flask import Flask
        self.app=Flask(__name__);self.app.config.update(SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        db.init_app(self.app);self.ctx=self.app.app_context();self.ctx.push()
        from sqlalchemy import event
        @event.listens_for(db.engine,'connect')
        def functions(connection,record):connection.create_collation('ascii_bin',lambda a,b:(a>b)-(a<b))
        from game.finance_models import StateFinancialAccount
        from game.paga2.models import Paga2Profile,Paga2Plan
        for model in (StateFinancialAccount,Paga2Profile,Paga2Plan):model.__table__.create(db.engine)
    def tearDown(self):db.session.remove();db.engine.dispose();self.ctx.pop()

    def test_capacity_keeps_reserve_and_plan_needs(self):
        from game.finance_models import StateFinancialAccount
        from game.paga2.models import Paga2Profile,Paga2Plan
        from game.paga2.catalog import TRAITS
        now=datetime(2026,1,1)
        db.session.add(StateFinancialAccount(panstwo_id=1,reserve_balance=Decimal('100000000000'),last_transaction_sequence=0,created_at=now,updated_at=now))
        db.session.add(Paga2Profile(panstwo_id=1,categories=['economic'],priorities=['trade'],traits={**{k:50 for k in TRAITS},'fiscal_conservatism':100},actor='t'))
        db.session.commit()
        careful=finance.loan_capacity(db.session,1)
        self.assertAlmostEqual(careful['max_loan'],100e9*.2,delta=1)
        db.session.add(Paga2Plan(country_id=1,goal='factory:tanks',status='ACTIVE',steps=[{'status':'ready','cost':40e9}]));db.session.commit()
        self.assertAlmostEqual(finance.loan_capacity(db.session,1)['max_loan'],100e9*.2-10e9,delta=1)
        self.assertEqual(finance.loan_capacity(db.session,2)['max_loan'],0)


if __name__=='__main__':unittest.main()
