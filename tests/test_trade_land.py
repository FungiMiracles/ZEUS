"""18 Nov 2026: handel drogą lądową — zakup od państwa z granicą lądową jedzie lądem między stolicami (150 km/h)."""
from datetime import timedelta
from uuid import uuid4
from unittest.mock import patch
from sqlalchemy import select
from extensions import db
from models import Miasto
from game.commerce_models import TradeShipment, TradeReserveMovement
from game.finance_models import StateFinancialAccount
from game.trade_service import buy_offer, deliver_shipments, LAND_SPEED, SHIP_SPEED
from test_game_commerce import CommerceFixture, NOW


class LandTradeTests(CommerceFixture):
    def setUp(self):
        super().setUp()
        # Stolice (miasto typu 1): państwo 1 w punkcie [9900,0], państwo 2 w [10000,0] (city_point z fikstury: (id−101)·100).
        db.session.add_all([Miasto(miasto_id=200, panstwo_id=1, region_id=1, miasto_nazwa='Stolica 1', miasto_typ_id=1, czy_portowe='NIE', czy_na_mapie='TAK'),
                            Miasto(miasto_id=201, panstwo_id=2, region_id=2, miasto_nazwa='Stolica 2', miasto_typ_id=1, czy_portowe='NIE', czy_na_mapie='TAK')])
        db.session.commit()

    def border(self, adjacency):
        p = patch('game.road_projects.region_adjacency', return_value=adjacency); p.start(); self.addCleanup(p.stop)

    def purchase(self, **extra):
        return buy_offer(2, {'request_id': str(uuid4()), 'offer_id': self.offer(), **extra})

    def test_neighbor_purchase_travels_by_land_between_capitals_without_port_fees(self):
        self.border({1: {2}, 2: {1}})
        db.session.get(Miasto, 102).czy_portowe = 'NIE'; db.session.commit()   # kupujący bez portu też może kupić lądem
        shipment = db.session.get(TradeShipment, self.purchase(arrival_rate='0'))
        self.assertEqual((shipment.transport, shipment.departure_port_id, shipment.arrival_port_id), ('land', 200, 201))
        self.assertEqual((shipment.departure_fee, shipment.arrival_fee), (0, 0))
        self.assertEqual(shipment.route, [[9900, 0], [10000, 0]])
        self.assertAlmostEqual(shipment.distance_km, 100.0)
        self.assertEqual(shipment.arrives_at - shipment.starts_at, timedelta(seconds=100 / LAND_SPEED * 3600))
        self.assertEqual(shipment.origin_country_id, 1)
        movements = {row.panstwo_id: row.amount for row in db.session.scalars(select(TradeReserveMovement))}
        self.assertEqual(movements, {1: 1000, 2: -1000})
        deliver_shipments(db.session, NOW + timedelta(days=1)); db.session.commit()
        self.assertIsNotNone(db.session.get(TradeShipment, shipment.id).delivered_at)

    def test_land_speed_is_150_kmh(self):
        self.border({1: {2}, 2: {1}})
        with patch('game.trade_service.city_point', side_effect=lambda id: {200: [0, 0], 201: [300, 0]}.get(id, [(id - 101) * 100, 0])):
            shipment = db.session.get(TradeShipment, self.purchase(arrival_rate='0'))
        self.assertAlmostEqual(shipment.distance_km, 300.0)
        self.assertEqual(shipment.arrives_at - shipment.starts_at, timedelta(hours=2))

    def test_without_land_border_purchase_still_goes_by_sea(self):
        self.border({})
        shipment = db.session.get(TradeShipment, self.purchase(port_id=102, arrival_rate='0'))
        self.assertEqual(shipment.transport, 'sea')
        self.assertEqual((shipment.departure_port_id, shipment.arrival_port_id), (101, 102))
        self.assertEqual(shipment.arrives_at - shipment.starts_at, timedelta(seconds=max(1, shipment.distance_km / SHIP_SPEED * 3600)))

    def test_trade_screen_marks_land_offers_and_shipments(self):
        self.border({1: {2}, 2: {1}})
        offer = self.offer()
        from game.commerce import trade_state
        with self.app.test_request_context():
            data = trade_state(2)
        item = next(o for o in data['offers'] if o['id'] == offer)
        self.assertEqual((item['land']['fromCity'], item['land']['toCity'], item['usable']), ('Stolica 1', 'Stolica 2', True))
        buy_offer(2, {'request_id': str(uuid4()), 'offer_id': offer, 'arrival_rate': '0'})
        with self.app.test_request_context():
            data = trade_state(2)
        self.assertEqual(data['shipments'][0]['transport'], 'land')
        from game.trade_navigation import visible_shipments
        with patch('game.trade_navigation.game_now', return_value=NOW + timedelta(seconds=1)):
            self.assertEqual(visible_shipments(db.session, 2)[0]['transport'], 'land')
