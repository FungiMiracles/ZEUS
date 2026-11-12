"""Sea-only routing, constant-speed sampling, interdiction and delivery ordering."""
import unittest
from datetime import timedelta
from uuid import uuid4
from unittest.mock import patch
from sqlalchemy import select
from shapely.geometry import box,Polygon
from game.sea_routes import SeaRouter,path_length,path_position
from test_game_military_flights import FlightFixture
from test_game_military import NOW
from game.commerce_models import TradeShipment,TradeOffer,ResourceStock
from game.military_models import MilitaryFlight
from game.military_service import create_order
from game.military_flights import complete_flights
from game.trade_service import deliver_shipments
from game.trade_navigation import shipment_position,visible_shipments
from game.finance_service import FinanceError
from extensions import db
from models import Region,Miasto,Wojsko


class SeaRoutingTests(unittest.TestCase):
    def test_shortest_visible_route_and_coastal_detour_never_cross_land(self):
        router=SeaRouter(box(0,0,10,10),resolution=100)
        path=router.route([-5,5],[15,5]);self.assertGreater(len(path),2)
        self.assertTrue(all(router.clear(a,b) for a,b in zip(path,path[1:])))
        self.assertLess(path_length(path),24.6);self.assertGreater(path_length(path),24)
        self.assertEqual(router.route([-5,-5],[15,-5]),[[-5,-5],[15,-5]])

    def test_ports_on_land_are_moved_to_the_seaward_side(self):
        router=SeaRouter(Polygon([(0,0),(10,0),(10,10),(0,10)],holes=[[(4,4),(6,4),(6,6),(4,6)]]),resolution=100)
        path=router.route([5,5],[15,5]);self.assertFalse(router.land.covers(__import__('shapely').Point(path[0])))
        self.assertTrue(all(router.clear(a,b) for a,b in zip(path,path[1:])))

    def test_sampling_follows_cumulative_distance_not_equal_vertex_time(self):
        path=[[0,0],[10,0],[10,30]]
        self.assertEqual(path_position(path,.5),[10,10]);self.assertEqual(path_position(path,1),[10,30]);self.assertEqual(path_position(path,0),[0,0])


class MerchantCombatTests(FlightFixture):
    def setUp(self):
        super().setUp();db.session.add(Region(region_id=3,panstwo_id=3,region_nazwa='Neutralny port',region_polozenie_id=2))
        db.session.add_all([Miasto(miasto_id=9100,panstwo_id=3,region_id=3,miasto_nazwa='Port tranzytowy',czy_portowe='TAK',czy_na_mapie='TAK'),Miasto(miasto_id=9101,panstwo_id=3,region_id=3,miasto_nazwa='Port odbioru',czy_portowe='TAK',czy_na_mapie='TAK')]);db.session.flush()
        offer=TradeOffer(panstwo_id=2,user_id=2,cargo={'wegiel_kamienny':5},price=1000,excluded=[],port_id=9100,port_country_id=3,departure_rate=0,status='sold',request_id=str(uuid4()));db.session.add(offer);db.session.flush()
        self.ship=TradeShipment(offer_id=offer.id,seller_id=2,buyer_id=3,cargo=offer.cargo,departure_port_id=9100,arrival_port_id=9101,departure_fee=0,arrival_fee=0,source_x=100,source_y=0,target_x=200,target_y=100,route=[[100,0],[100,100],[200,100]],distance_km=200,starts_at=NOW,arrives_at=NOW+timedelta(hours=2),origin_country_id=3,request_id=str(uuid4()));db.session.add(self.ship);db.session.commit();self.ship_id=self.ship.id
        self.base_source=self.source()

    def launch_ship(self,**extra):return create_order(1,dict(kind='missile',region_id=3,target_shipment_id=self.ship_id,source_base_id=self.base_source.id,missile_type='short',missiles=1,**extra))

    def test_attack_intercepts_moving_ship_even_when_origin_port_is_neutral(self):
        id=self.launch_ship();flight=db.session.get(MilitaryFlight,id)
        self.assertEqual(flight.target_kind,'shipment');self.assertEqual(flight.target_country_id,2)
        self.assertAlmostEqual(flight.target_y,shipment_position(self.ship,flight.impact_at)[1],places=5)
        self.assertGreater(flight.target_y,0)
        with patch('game.military_flights.randbelow',return_value=0):complete_flights(db.session,flight.impact_at)
        db.session.commit();db.session.expire_all();self.assertEqual(db.session.get(TradeShipment,self.ship_id).health,96)
        complete_flights(db.session,flight.impact_at);db.session.commit();self.assertEqual(db.session.get(TradeShipment,self.ship_id).health,96)

    def test_sink_before_arrival_is_settled_before_delivery_and_cargo_is_lost_once(self):
        id=create_order(1,dict(kind='missile',target_shipment_id=self.ship_id,source_base_id=self.base_source.id,missile_type='short',missiles=10))
        with patch('game.military_flights.randbelow',return_value=11):deliver_shipments(db.session,NOW+timedelta(hours=3),3)
        db.session.commit();db.session.expire_all();ship=db.session.get(TradeShipment,self.ship_id)
        self.assertEqual(ship.health,0);self.assertIsNotNone(ship.sunk_at);self.assertIsNone(ship.delivered_at)
        self.assertIsNone(db.session.get(ResourceStock,(3,'wegiel_kamienny')))
        deliver_shipments(db.session,NOW+timedelta(days=1),3);db.session.commit();self.assertIsNone(db.session.get(ResourceStock,(3,'wegiel_kamienny')))

    def test_neutral_own_delivered_and_too_late_targets_are_rejected_without_spending(self):
        for changes in ({'seller_id':3,'buyer_id':4},{'seller_id':1},{'delivered_at':NOW},{'health':0},{'arrives_at':NOW+timedelta(seconds=1)}):
            original={key:getattr(self.ship,key) for key in changes}
            for key,value in changes.items():setattr(self.ship,key,value)
            db.session.commit()
            with self.assertRaises(FinanceError):self.launch_ship()
            for key,value in original.items():setattr(self.ship,key,value)
            db.session.commit()
        self.assertEqual(db.session.query(MilitaryFlight).count(),0)
        self.assertEqual(db.session.scalar(select(Wojsko.rakiety_krotkiego_zasiegu).where(Wojsko.panstwo_id==1)),20)

    def test_visibility_includes_route_health_origin_and_enemy_cargo_without_contents(self):
        with patch('game.trade_navigation.game_now',return_value=NOW):rows=visible_shipments(db.session,1)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['originCountryId'],3);self.assertTrue(rows[0]['canAttack']);self.assertEqual(rows[0]['health'],100)
        self.assertNotIn('cargo',rows[0]);self.assertEqual(rows[0]['route'],self.ship.route)
