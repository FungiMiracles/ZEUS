"""Wydobycie, depozyt ofert, rozliczenia rezerwy i dostawy fizyczne."""
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4
from unittest.mock import patch
from sqlalchemy import text,select
from extensions import db
from models import DictZasob,RegionZasob,Miasto
from services.natural_resources import RESOURCES
from test_game_military import MilitaryFixture,NOW
from game.commerce_models import ResourceStock,Mine,MiningExpense,TradeOffer,TradeShipment,PortTariff,TradeReserveMovement
from game.finance_models import StateFinancialAccount
from game.finance_service import FinanceError,_reserve_for_account
from game.mining_service import build_mine,extract_country,warehouse
from game.trade_service import create_offer,cancel_offer,buy_offer,deliver_shipments,set_tariff


class CommerceFixture(MilitaryFixture):
    ENFORCE_TRADE_RULES=False
    def tearDown(self):
        if getattr(self,'_trade_rules',None):self._trade_rules.stop();self._trade_rules=None
        super().tearDown()
    def setUp(self):
        super().setUp()
        # Reguły cen i jednego towaru (12 Nov 2026) mają własne testy (test_game_trade_prices); tu sprawdzane są opłaty, dostawy i magazyn.
        # Zatrzymanie w tearDown (nie addCleanup): część testów wywołuje setUp/tearDown tego fixture'a ręcznie.
        self._trade_rules=None
        if not self.ENFORCE_TRADE_RULES:
            self._trade_rules=patch('game.trade_prices.check_offer',return_value=None);self._trade_rules.start()
        db.metadata.create_all(db.engine,tables=[DictZasob.__table__,RegionZasob.__table__])
        db.session.add_all([DictZasob(zasob_id=i,zasob_kod=code,zasob_nazwa=name,zasob_kategoria='Surowce',zasob_jednostka='jednostka') for i,(code,name) in enumerate(RESOURCES,1)])
        db.session.add(RegionZasob(region_id=1,zasob_id=1,zloze_ilosc=3))
        db.session.add_all([Miasto(miasto_id=100+i,panstwo_id=i,region_id=1 if i==1 else 2,miasto_nazwa=f'Port {i}',czy_portowe='TAK',czy_na_mapie='TAK') for i in (1,2,3)])
        db.session.add(ResourceStock(panstwo_id=1,resource='wegiel_kamienny',quantity=20))
        db.session.add(StateFinancialAccount(panstwo_id=2,reserve_balance=10000,last_transaction_sequence=0,created_at=NOW,updated_at=NOW))
        db.session.execute(text("INSERT INTO game_state_budget_allocations (id,budget_id,category_code,amount) VALUES (2,1,'mining_infrastructure',1000000000000)"))
        db.session.commit()
        for target,value in [('game.mining_service.game_now',NOW),('game.trade_service.game_now',NOW),('game.commerce.game_now',NOW)]:
            patcher=patch(target,return_value=value);patcher.start();self.addCleanup(patcher.stop)
        route=patch('game.trade_service.shortest_sea_route',side_effect=lambda a,b:[a,b]);route.start();self.addCleanup(route.stop)
        p=patch('game.trade_service.city_point',side_effect=lambda id:[(id-101)*100,0]);p.start();self.addCleanup(p.stop)
        p=patch('game.military_geography.region_contains',return_value=True);p.start();self.addCleanup(p.stop)
        # 18 Nov 2026: domyślnie bez granic lądowych (handel morski); transport lądowy testuje test_trade_land.
        p=patch('game.road_projects.region_adjacency',return_value={});p.start();self.addCleanup(p.stop)

    def offer(self,**extra):
        return create_offer(1,dict(request_id=str(uuid4()),cargo={'wegiel_kamienny':5},price='1000',port_id=101,departure_rate='0',**extra))
    def buy(self,id,**extra):
        data=dict(request_id=str(uuid4()),offer_id=id,port_id=102,arrival_rate='0');data.update(extra)
        return buy_offer(2,data)
    def mine(self,**extra):
        data=dict(request_id=str(uuid4()),region_id=1,resource='wegiel_kamienny',x=1,y=2);data.update(extra)
        from game.research_models import ResearchAccount
        from game.industry_catalog import TECHNOLOGIES
        if db.session.get(ResearchAccount,1) is None:
            db.session.add(ResearchAccount(panstwo_id=1,points=0,ammunition=0,nodes={key:rule['cost'] for key,rule in TECHNOLOGIES.items()}));db.session.commit()
        return build_mine(1,data)


class CommerceTests(CommerceFixture):
    def test_build_cost_duration_and_idempotency(self):
        key=str(uuid4());id=self.mine(request_id=key);self.assertEqual(self.mine(request_id=key),id)
        db.session.expire_all();mine=db.session.get(Mine,id)
        self.assertEqual(mine.ready_at,NOW+timedelta(days=5));self.assertEqual(db.session.query(MiningExpense).one().amount,2000000000)
        self.assertEqual(self.count(Mine),1)
        with self.assertRaises(FinanceError):self.mine(request_id=key,x=9)
    def test_invalid_location_owner_funds(self):
        with self.assertRaises(FinanceError):self.mine(region_id=2)
        with patch('game.military_geography.region_contains',return_value=False):
            with self.assertRaises(FinanceError):self.mine()
        db.session.execute(text("UPDATE game_state_budget_allocations SET amount=0 WHERE category_code='mining_infrastructure'"));db.session.commit()
        with self.assertRaises(FinanceError):self.mine()
        self.assertEqual(self.count(Mine),0)
    def test_mining_starts_after_ready_is_finite_and_exactly_once(self):
        id=self.mine();db.session.expire_all()
        for days,quantity in [(5,20),(6,21),(7,22),(7,22),(50,23),(100,23)]:
            extract_country(db.session,1,NOW+timedelta(days=days));db.session.commit()
            self.assertEqual(int(db.session.get(ResourceStock,(1,'wegiel_kamienny')).quantity),quantity)
        self.assertEqual(db.session.scalar(select(RegionZasob).where(RegionZasob.region_id==1,RegionZasob.zasob_id==1)).zloze_ilosc,0)
    def test_mine_without_deposit_does_not_generate_goods(self):
        with self.assertRaises(FinanceError):self.mine(resource='zloto')
        self.assertIsNone(db.session.get(ResourceStock,(1,'zloto')))
    def test_escrow_cancel_and_no_sale_of_underground_ore(self):
        id=self.offer();db.session.expire_all();self.assertEqual(warehouse(db.session,1)['wegiel_kamienny'],{'available':15,'reserved':5,'total':20})
        cancel_offer(1,{'offer_id':id});cancel_offer(1,{'offer_id':id});db.session.expire_all();self.assertEqual(warehouse(db.session,1)['wegiel_kamienny']['available'],20)
        with self.assertRaises(FinanceError):create_offer(1,{'request_id':str(uuid4()),'cargo':{'zloto':1},'price':'10','port_id':101,'departure_rate':'0'})
    def test_payment_immediate_goods_only_on_arrival_idempotent(self):
        id=self.offer();key=str(uuid4());shipment=self.buy(id,request_id=key);self.assertEqual(self.buy(id,request_id=key),shipment);db.session.expire_all()
        self.assertEqual(db.session.get(StateFinancialAccount,1).reserve_balance,1000);self.assertEqual(db.session.get(StateFinancialAccount,2).reserve_balance,9000)
        row=db.session.get(TradeShipment,shipment);self.assertEqual(row.arrives_at,NOW+timedelta(hours=1));self.assertIsNone(db.session.get(ResourceStock,(2,'wegiel_kamienny')))
        deliver_shipments(db.session,NOW+timedelta(minutes=59));db.session.commit();self.assertIsNone(db.session.get(ResourceStock,(2,'wegiel_kamienny')))
        deliver_shipments(db.session,NOW+timedelta(hours=1));db.session.commit();deliver_shipments(db.session,NOW+timedelta(hours=2));db.session.commit()
        self.assertEqual(db.session.get(ResourceStock,(2,'wegiel_kamienny')).quantity,5)
        self.assertEqual(_reserve_for_account(db.session.get(StateFinancialAccount,1),None),1000)
        resale=create_offer(2,{'request_id':str(uuid4()),'cargo':{'wegiel_kamienny':5},'price':'500','port_id':102,'departure_rate':'0'});self.assertIsNotNone(resale)
    def test_own_ports_required_and_foreign_fees_split(self):
        with self.assertRaises(FinanceError):create_offer(1,{'request_id':str(uuid4()),'cargo':{'wegiel_kamienny':1},'price':'1000','port_id':103,'departure_rate':'0'})
        db.session.get(Miasto,101).czy_portowe='NIE';db.session.get(Miasto,102).czy_portowe='NIE';db.session.commit();set_tariff(3,{'rate':'2.5'})
        id=create_offer(1,{'request_id':str(uuid4()),'cargo':{'wegiel_kamienny':1},'price':'1000','port_id':103,'departure_rate':'2.5'})
        self.buy(id,port_id=103,arrival_rate='2.5');db.session.expire_all()
        self.assertEqual(db.session.get(StateFinancialAccount,1).reserve_balance,975);self.assertEqual(db.session.get(StateFinancialAccount,2).reserve_balance,8975);self.assertEqual(db.session.get(StateFinancialAccount,3).reserve_balance,50)
        self.assertEqual(sum(db.session.scalars(select(TradeReserveMovement.amount))),0)
    def test_excluded_country_and_failed_purchase_do_not_charge(self):
        id=self.offer(excluded=[2]);
        with self.assertRaises(FinanceError):self.buy(id)
        db.session.expire_all();self.assertEqual(db.session.get(StateFinancialAccount,2).reserve_balance,10000);self.assertEqual(self.count(TradeShipment),0)
        self.login(2);response=self.client.get('/game/handel/stan');self.assertEqual(response.status_code,200);self.assertFalse(response.json['offers'])
    def test_insufficient_reserve_atomic(self):
        id=self.offer();db.session.get(StateFinancialAccount,2).reserve_balance=5;db.session.commit()
        with self.assertRaises(FinanceError):self.buy(id)
        db.session.expire_all();self.assertEqual(db.session.get(TradeOffer,id).status,'open');self.assertEqual(self.count(TradeReserveMovement),0)
    @patch('game.military_geography.region_adjacency',return_value={})   # 18 Nov 2026: test opłat — bez sąsiadów lądowych (reguła portu sąsiada: test_trade_neighbor_ports)
    def test_tariff_changes_require_requote(self,_adjacency):
        db.session.get(Miasto,101).czy_portowe='NIE';db.session.commit();set_tariff(3,{'rate':'5'})
        with self.assertRaises(FinanceError):create_offer(1,{'request_id':str(uuid4()),'cargo':{'wegiel_kamienny':1},'price':'10','port_id':103,'departure_rate':'0'})
        id=create_offer(1,{'request_id':str(uuid4()),'cargo':{'wegiel_kamienny':1},'price':'10','port_id':103,'departure_rate':'5'})
        db.session.get(Miasto,102).czy_portowe='NIE';db.session.commit()
        with self.assertRaises(FinanceError):self.buy(id,port_id=103,arrival_rate='0')
    def test_http_csrf_and_page(self):
        self.assertEqual(self.client.get('/game/handel').status_code,200)
        for path in ['/game/handel/zmien','/game/handel/wydobycie/buduj']:
            self.assertEqual(self.client.post(path,json={}).status_code,403)
        self.assertEqual(self.client.get('/game/handel/wydobycie/stan').status_code,200)

from test_game_military_flights import FlightFixture
from game.military_models import MilitaryFlight,MilitaryOrder
from game.military_service import create_order
from game.military_flights import complete_flights
from game.intelligence_models import IntelligenceAgent,IntelligenceMission
from game.intelligence_service import collect_report

class MineCombatTests(FlightFixture):
    def setUp(self):
        super().setUp()
        self.target=Mine(panstwo_id=2,region_id=2,resource='zloto',map_x=100,map_y=0,health=100,starts_at=NOW-timedelta(days=10),ready_at=NOW-timedelta(days=2),extracted_at=NOW-timedelta(days=2),request_id=str(uuid4()))
        db.session.add(self.target);db.session.commit();self.mine_id=self.target.id
    def reveal(self):
        agent=IntelligenceAgent(panstwo_id=1,level=7);db.session.add(agent);db.session.flush()
        mission=IntelligenceMission(panstwo_id=1,agent_id=agent.id,region_id=2,target_country_id=2,region_name='Cel',kind='mines',starts_at=NOW-timedelta(days=7),ends_at=NOW,completed_at=NOW,success=True)
        mission.report=collect_report(db.session,mission);db.session.add(mission);db.session.commit();return mission
    def test_mines_hidden_until_successful_intelligence_and_cannot_attack_blind(self):
        source=self.source()
        self.assertFalse(self.client.get('/game/panel-wojenny/stan').json['mines'])
        with self.assertRaises(FinanceError):self.launch(source,city_id=None,target_mine_id=self.mine_id)
        mission=self.reveal();self.assertEqual(mission.report['mine_ids'],[self.mine_id]);self.assertEqual(len(self.client.get('/game/panel-wojenny/stan').json['mines']),1)
        id=self.launch(source,city_id=None,target_mine_id=self.mine_id)
        with patch('game.military_flights.randbelow',return_value=0):complete_flights(db.session,NOW+timedelta(hours=1));db.session.commit()
        self.assertEqual(db.session.get(Mine,self.mine_id).health,96);self.assertEqual(db.session.get(MilitaryFlight,id).damage['mineHealthLost'],4)
    def test_zero_health_deletes_mine_preserves_flight_and_expense(self):
        self.reveal();self.target.health=4
        db.session.add(MiningExpense(panstwo_id=2,budget_id=1,mine_id=self.mine_id,amount=100));db.session.commit()
        source=self.source();first=self.launch(source,city_id=None,target_mine_id=self.mine_id);second=self.launch(source,city_id=None,target_mine_id=self.mine_id)
        with patch('game.military_flights.randbelow',return_value=0):complete_flights(db.session,NOW+timedelta(hours=1));db.session.commit()
        self.assertIsNone(db.session.get(Mine,self.mine_id));self.assertIsNone(db.session.query(MiningExpense).one().mine_id)
        self.assertTrue(db.session.get(MilitaryFlight,first).damage['mineDestroyed']);self.assertEqual(db.session.get(MilitaryFlight,second).target_kind,'mine');self.assertEqual(db.session.get(MilitaryFlight,second).damage,{})
        from game.forum_models import GameNotification
        self.assertTrue(any('Kopalnia została zniszczona' in n.system_text for n in db.session.scalars(select(GameNotification))))

class CommerceBudgetTests(CommerceFixture):
    def test_trade_receipts_and_spending_integrate_with_budget_balances(self):
        from game.finance_models import StateBudget
        from game.budget_transfers import sector_balances,transfer_funds
        db.session.execute(text("INSERT INTO game_state_budgets (id,panstwo_id,game_year,period,closing_reserve) VALUES (2,2,2990,1,10000)"))
        db.session.execute(text("INSERT INTO game_state_budget_allocations (id,budget_id,category_code,amount) VALUES (3,1,'reserve',0),(4,2,'reserve',10000)"))
        db.session.execute(text('UPDATE game_state_budgets SET closing_reserve=0 WHERE id=1'))
        db.session.add(StateFinancialAccount(panstwo_id=1,reserve_balance=0,last_budget_id=1,last_transaction_sequence=0,created_at=NOW,updated_at=NOW));db.session.get(StateFinancialAccount,2).last_budget_id=2;db.session.commit()
        id=self.offer();self.buy(id);db.session.expire_all()
        for country,budget_id,expected in [(1,1,1000),(2,2,9000)]:
            budget=db.session.get(StateBudget,budget_id);self.assertEqual(_reserve_for_account(db.session.get(StateFinancialAccount,country),budget),expected)
            self.assertEqual(sector_balances(db.session,budget)['reserve']['remaining'],expected)
        with patch('game.budget_transfers.game_now',return_value=NOW):
            transfer_funds(1,{'request_id':str(uuid4()),'budget_id':1,'source':'reserve','destination':'infrastructure','amount':'500'})
        db.session.expire_all();self.assertEqual(_reserve_for_account(db.session.get(StateFinancialAccount,1),db.session.get(StateBudget,1)),500)
        self.mine();db.session.expire_all();self.assertEqual(sector_balances(db.session,db.session.get(StateBudget,1))['infrastructure']['remaining'],1000000000500-2000000000)
