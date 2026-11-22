"""Transactional roads, port access and WIKI treasury authorization."""
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import patch
from sqlalchemy import select,text,MetaData,Table,Column,String
from test_game_commerce import CommerceFixture
from test_game_military import MilitaryFixture,NOW
from extensions import db
from models import Region
from game.roads import quote_road,build_road,segment_inside
from game.civic_models import Road,TreasuryAdjustment,CountryTaxPolicy
from game.finance_models import StateBudget,StateFinancialAccount,BudgetCategory
from game.finance_service import FinanceError,FinanceConflict,_reserve_for_account
from game.budget_transfers import infrastructure_balance,sector_balances,effective_allocation
from game.admin_finance import adjust,tax_plan
from game.trade_service import set_port_access,choose_port,port_allows,buy_offer
from game.commerce_models import PortTariff,TradeShipment,TradeOffer


def feature(id=1,points=None):return {'properties':{'region_id':id},'geometry':{'type':'Polygon','coordinates':[points or [[0,0],[100,0],[100,100],[0,100],[0,0]]]}}


class RoadTests(MilitaryFixture):
    def setUp(self):
        super().setUp()
        db.session.execute(text("INSERT INTO game_state_budget_allocations (id,budget_id,category_code,amount) VALUES (2,1,'infrastructure',1000000000)"));db.session.commit()
        for target,value in [('game.roads.map_features',[feature()]),('game.roads.distance_km',10),('game.roads.game_now',NOW)]:
            mocked=patch(target,return_value=value);mocked.start();self.addCleanup(mocked.stop)
        mocked=patch('game.roads._country_for_user',return_value=SimpleNamespace(PANSTWO_ID=1));mocked.start();self.addCleanup(mocked.stop)

    def data(self,kind='motorway'):
        quote=quote_road(db.session,1,{'kind':kind,'start':[1,1],'end':[11,1]})
        return {**quote,'expected_cost':quote['cost'],'request_id':str(uuid4())}

    def test_cost_spending_exactly_once_and_duplicate_rejected(self):
        for kind,cost in [('motorway',100420000),('national',2510500)]:
            data=self.data(kind);before=infrastructure_balance(db.session,db.session.get(StateBudget,1))[1]
            road=build_road(1,data);again=build_road(1,data);self.assertEqual(road['id'],again['id']);db.session.expire_all()
            self.assertEqual(before-infrastructure_balance(db.session,db.session.get(StateBudget,1))[1],cost)
            duplicate={**data,'request_id':str(uuid4())}
            with self.assertRaises(FinanceError):build_road(1,duplicate)
        self.assertEqual(db.session.query(Road).count(),2)
        self.assertEqual(sector_balances(db.session,db.session.get(StateBudget,1))['infrastructure']['spent'],102930500)

    def test_no_funds_stale_quote_invalid_points_and_forged_admin(self):
        data=self.data()
        with self.assertRaises(FinanceConflict):build_road(1,{**data,'expected_cost':'0'})
        for point in ([True,1],[float('nan'),1],[1000,1000],[1]):
            with self.assertRaises(FinanceError):quote_road(db.session,1,{**data,'start':point})
        db.session.execute(text("UPDATE game_state_budget_allocations SET amount=0 WHERE category_code='infrastructure'"));db.session.commit()
        with self.assertRaises(FinanceError):build_road(1,{**data,'admin':True,'admin_actor':'forged'})
        self.assertEqual(db.session.query(Road).count(),0)

    def test_admin_roads_free_without_player_budget(self):
        data=self.data();data['expected_cost']='0'
        road=build_road(None,data,admin_country_id=1,admin_actor='WIKI admin')
        self.assertEqual(Decimal(road['cost']),0)
        stored=db.session.get(Road,road['id']);self.assertIsNone(stored.budget_id);self.assertIsNone(stored.user_id)
        self.assertEqual(infrastructure_balance(db.session,db.session.get(StateBudget,1))[1],1000000000)

    def test_player_road_routes_were_removed_from_the_game(self):
        """Administrator decision 10 Nov 2026: no road building in the game; the WIKI road builder stays."""
        from game.infrastructure import infrastructure_bp
        self.app.register_blueprint(infrastructure_bp)
        for path in ('/game/infrastruktura/drogi/buduj','/game/infrastruktura/drogi/wycena','/game/infrastruktura/drogi/ulepsz','/game/infrastruktura/drogi/decyzja'):
            self.assertEqual(self.client.post(path,json=self.data('national'),headers={'X-CSRF-Token':'token'}).status_code,404,path)
        self.assertEqual(self.client.get('/game/infrastruktura/drogi/stan').status_code,404)
        self.assertFalse(any('/drogi' in str(rule) and rule.endpoint.startswith('game_') for rule in self.app.url_map.iter_rules()))
        self.assertEqual(db.session.query(Road).count(),0)

    def test_changed_map_scale_invalidates_cost_and_paid_roads_protect_spent_funds(self):
        from game.military_models import MapCalibration
        from game.military_flights import distance_km
        data=self.data()
        with patch('game.roads.distance_km',side_effect=distance_km):
            calibration=db.session.get(MapCalibration,1);calibration.km_per_unit=2;db.session.commit()
            with self.assertRaises(FinanceConflict):build_road(1,data)
        build_road(1,data);db.session.expire_all()
        with patch('game.admin_finance.game_now',return_value=NOW):
            with self.assertRaises(FinanceError):adjust(1,{'amount':'-1000000000','category':'infrastructure','reason':'Cannot remove spent funds','request_id':str(uuid4())},'Admin')

    def test_curve_is_saved_and_included_in_the_price(self):
        data=self.data()
        self.assertEqual(len(data['path']),25)
        self.assertGreater(Decimal(data['distanceKm']),10)
        self.assertTrue(any(point[1]!=1 for point in data['path'][1:-1]))
        road=build_road(1,data);db.session.expire_all()
        self.assertEqual(db.session.get(Road,road['id']).path,data['path'])
        self.assertEqual(db.session.get(Road,road['id']).cost,Decimal(data['distanceKm'])*10000000)

    def test_wiki_can_connect_adjacent_countries_but_player_cannot(self):
        left=feature(1,[[0,0],[5,0],[5,10],[0,10],[0,0]])
        right=feature(2,[[5,0],[10,0],[10,10],[5,10],[5,0]])
        payload={'kind':'national','start':[1,5],'end':[9,5]}
        with patch('game.roads.map_features',return_value=[left,right]):
            quote=quote_road(db.session,1,payload,admin=True)
            self.assertEqual(Decimal(quote['cost']),0)
            with self.assertRaises(FinanceError):quote_road(db.session,1,payload)

    def test_segment_rejects_water_holes_and_foreign_gap(self):
        a=feature(points=[[0,0],[4,0],[4,10],[0,10],[0,0]])
        b=feature(2,[[6,0],[10,0],[10,10],[6,10],[6,0]])
        self.assertFalse(segment_inside([a,b],[1,5],[9,5]))
        b=feature(2,[[4,0],[10,0],[10,10],[4,10],[4,0]])
        self.assertTrue(segment_inside([a,b],[1,5],[9,5]))
        hole=feature();hole['geometry']['coordinates'].append([[4,4],[6,4],[6,6],[4,6],[4,4]])
        self.assertFalse(segment_inside([hole],[1,5],[9,5]))

    def test_foreign_and_overseas_regions_cannot_be_player_road(self):
        db.session.get(Region,1).terytorium_zamorskie=True;db.session.commit()
        with self.assertRaises(FinanceError):self.data()


class PortAccessTests(CommerceFixture):
    def setUp(self):
        super().setUp();self.owner=patch('game.trade_service._country_for_user',return_value=SimpleNamespace(PANSTWO_ID=1));self.owner.start();self.addCleanup(self.owner.stop)

    def test_selective_and_global_blocks_keep_own_ports_accessible(self):
        # Country 3 has no usable own port in this test.
        with patch('game.trade_service.ports',return_value=[db.session.get(__import__('models').Miasto,101)]):
            set_port_access(1,{'block_foreign':False,'blocked_countries':[2]});db.session.expire_all()
            self.assertFalse(port_allows(db.session,1,2));self.assertTrue(port_allows(db.session,1,3))
            self.assertTrue(port_allows(db.session,1,1))
            with self.assertRaises(FinanceError):choose_port(db.session,2,101)
            self.assertEqual(choose_port(db.session,3,101).miasto_id,101)
            set_port_access(1,{'block_foreign':True,'blocked_countries':[]});db.session.expire_all()
            self.assertFalse(port_allows(db.session,1,3));self.assertTrue(port_allows(db.session,1,1))
            set_port_access(1,{'block_foreign':False,'blocked_countries':[]});db.session.expire_all()
            self.assertTrue(port_allows(db.session,1,2))

    def test_block_after_offer_prevents_payment_and_preserves_goods(self):
        offer_id=self.offer()
        set_port_access(1,{'block_foreign':False,'blocked_countries':[2]});db.session.expire_all()
        balance=db.session.get(StateFinancialAccount,2).reserve_balance
        with patch('game.trade_service._country_for_user',return_value=SimpleNamespace(PANSTWO_ID=2)):
            with patch('game.trade_service.ports',return_value=[db.session.get(__import__('models').Miasto,101)]):
                with self.assertRaises(FinanceError):self.buy(offer_id,port_id=101)
        db.session.expire_all();self.assertEqual(db.session.get(StateFinancialAccount,2).reserve_balance,balance)
        self.assertEqual(db.session.query(TradeShipment).count(),0);self.assertEqual(db.session.get(TradeOffer,offer_id).status,'open')


    def test_blocking_transit_does_not_embargo_owners_own_exports(self):
        offer=self.offer()
        set_port_access(1,{'block_foreign':True,'blocked_countries':[]})
        with patch('game.trade_service._country_for_user',return_value=SimpleNamespace(PANSTWO_ID=2)):
            shipment=self.buy(offer)
        self.assertIsNotNone(shipment)

    def test_block_does_not_cancel_a_paid_shipment_or_break_retry(self):
        offer=self.offer();key=str(uuid4())
        with patch('game.trade_service._country_for_user',return_value=SimpleNamespace(PANSTWO_ID=2)):
            shipment=self.buy(offer,request_id=key,port_id=102)
        set_port_access(1,{'block_foreign':True,'blocked_countries':[2]});db.session.expire_all()
        with patch('game.trade_service._country_for_user',return_value=SimpleNamespace(PANSTWO_ID=2)):
            self.assertEqual(self.buy(offer,request_id=key,port_id=102),shipment)
        self.assertEqual(db.session.query(TradeShipment).count(),1)



class AdminFinanceTests(MilitaryFixture):
    def setUp(self):
        super().setUp()
        self.clock=patch('game.admin_finance.game_now',return_value=NOW);self.clock.start();self.addCleanup(self.clock.stop)
        db.session.add(StateFinancialAccount(panstwo_id=1,reserve_balance=500,last_budget_id=1,last_transaction_sequence=0,created_at=NOW,updated_at=NOW))
        db.session.execute(text("UPDATE game_state_budgets SET closing_reserve=500 WHERE id=1"));db.session.commit()

    def change(self,amount,category='reserve',**extra):return adjust(1,{'amount':str(amount),'category':category,'reason':'Test correction','request_id':str(uuid4()),**extra},'Wiki administrator')

    def test_reserve_adjustments_audited_idempotent_and_carry_consistent(self):
        key=str(uuid4());self.change(100,request_id=key);self.change(100,request_id=key);self.change(-50)
        db.session.expire_all();account=db.session.get(StateFinancialAccount,1)
        self.assertEqual(account.reserve_balance,550)
        self.assertEqual(_reserve_for_account(account,db.session.get(StateBudget,1)),550)
        self.assertEqual(db.session.query(TreasuryAdjustment).count(),2)
        with self.assertRaises(FinanceError):self.change(-551)
        self.assertEqual(sector_balances(db.session,db.session.get(StateBudget,1))['reserve']['adjustment'],50)

    def test_sector_correction_increases_shared_pool_without_rewriting_snapshot(self):
        self.change(12345,'infrastructure');db.session.expire_all()
        self.assertEqual(effective_allocation(db.session,1,'infrastructure'),12345)
        self.assertEqual(infrastructure_balance(db.session,db.session.get(StateBudget,1))[1],12345)
        with self.assertRaises(FinanceError):self.change(-12346,'infrastructure')
        self.assertEqual(db.session.get(StateFinancialAccount,1).reserve_balance,500)

    def test_tax_policy_overrides_next_plan_and_is_audited(self):
        self.change(0,taxes={'pit_rate':'12.5','cit_rate':'20'})
        plan=tax_plan(db.session,1,{'pit_rate':5,'cit_rate':10,'shares':{'reserve':100}})
        self.assertEqual(plan['pit_rate'],Decimal('12.50'));self.assertEqual(plan['cit_rate'],0)
        self.assertEqual(plan['shares'],{'reserve':100});self.assertEqual(db.session.get(StateFinancialAccount,1).reserve_balance,500)
        self.assertEqual(db.session.query(TreasuryAdjustment).one().policy_after,{'pit_rate':'12.50','cit_rate':'0.00'})
        for rate in (-1,101,'NaN'):
            with self.assertRaises(FinanceError):self.change(0,taxes={'pit_rate':rate,'cit_rate':10})

    def test_prebudget_funding_and_negative_protection(self):
        adjust(4,{'amount':'1000','category':'reserve','reason':'Initial funding','request_id':str(uuid4())},'Wiki admin');db.session.expire_all()
        self.assertEqual(_reserve_for_account(db.session.get(StateFinancialAccount,4),None),1000)

    def test_wiki_routes_require_role_and_csrf(self):
        from routes_civic_admin import wiki_civic_bp
        self.app.register_blueprint(wiki_civic_bp)
        self.assertEqual(self.client.get('/admin/drogi').status_code,403)
        self.assertEqual(self.client.post('/admin/gospodarka/1/budzet').status_code,403)
        with self.client.session_transaction() as browser:browser['rola']='wszechmocny'
        self.assertEqual(self.client.post('/admin/drogi/buduj',json={}).status_code,403)
        self.assertEqual(self.client.post('/admin/gospodarka/1/budzet',data={}).status_code,403)
