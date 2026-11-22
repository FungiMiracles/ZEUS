"""Drogi dostawy w handlu (22 Nov 2026): kolej magazyn → magazyn z wyborem państw tranzytowych i cłem lądowym,
opłaty MFW zależne od transportu, odcinki podróży (kolej / statek / samolot), cło lądowe państwa."""
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from sqlalchemy import select
from extensions import db
from models import Miasto
from game.commerce_models import TradeOffer, TradeShipment, TradeReserveMovement
from game.finance_models import StateFinancialAccount
from game.finance_service import FinanceError
from game.rail_models import RailLine
from game import trade_routes
from game.trade_service import buy_offer, create_offer, deliver_shipments
from test_game_commerce import CommerceFixture, NOW

ROOT = Path(__file__).resolve().parents[1]


class RailDeliveryTests(CommerceFixture):
    """Magazyn sprzedającego 101 (państwo 1), magazyn kupującego 102 (państwo 2); dwie trasy kolejowe:
    przez miasto 103 (państwo 3, 240 km) albo przez miasto 104 (państwo 4, 300 km)."""
    def setUp(self):
        super().setUp()
        RailLine.__table__.create(db.engine, checkfirst=True)
        db.session.add(Miasto(miasto_id=104, panstwo_id=4, region_id=2, miasto_nazwa='Miasto 4', czy_portowe='NIE', czy_na_mapie='TAK'))
        for a, b, km in ((101, 103, 120), (103, 102, 120), (101, 104, 150), (104, 102, 150)):
            db.session.add(RailLine(initiator_id=1, partner_id=None, city_a_id=a, city_b_id=b, path=[[(a - 101) * 100, 0], [(b - 101) * 100, 0]], distance_km=km, cost=0,
                                    shares={}, build_days=1, status='ACTIVE', starts_at=NOW - timedelta(days=5), ready_at=NOW - timedelta(days=1), request_id=str(uuid4())))
        db.session.add_all([trade_routes.LandCustoms(panstwo_id=3, rate=Decimal('2')), trade_routes.LandCustoms(panstwo_id=4, rate=Decimal('5'))])
        db.session.add(StateFinancialAccount(panstwo_id=4, reserve_balance=0, last_transaction_sequence=0, created_at=NOW, updated_at=NOW))
        db.session.commit()
        self.id = create_offer(1, {'request_id': str(uuid4()), 'cargo': {'wegiel_kamienny': 5}, 'price': '1000'})

    def options(self, buyer=2):
        return trade_routes.delivery_options(db.session, db.session.get(TradeOffer, self.id), buyer, NOW)

    def rail(self):
        return {o['key']: o for o in self.options() if o['mode'] == 'land'}

    def test_buyer_chooses_transit_country_and_pays_its_customs(self):
        rail = self.rail()
        self.assertEqual(set(rail), {'land:3', 'land:4'})
        self.assertEqual([(t['countryId'], t['amount']) for t in rail['land:3']['transit']], [(3, '20.00')])
        self.assertEqual(rail['land:4']['total'], '1050.00', 'price + 5% customs of country 4, rail has no IMF fee')
        self.assertEqual(rail['land:3']['imfFee'], '0.00')
        shipment = db.session.get(TradeShipment, buy_offer(2, {'request_id': str(uuid4()), 'offer_id': self.id, 'delivery': 'land:4', 'expected_total': '1050.00'}))
        db.session.expire_all()
        self.assertEqual(db.session.get(StateFinancialAccount, 2).reserve_balance, 10000 - 1050)
        self.assertEqual(db.session.get(StateFinancialAccount, 4).reserve_balance, 50, 'customs go to the transit country reserve')
        self.assertEqual(sum(db.session.scalars(select(TradeReserveMovement.amount))), 0)
        self.assertEqual((shipment.transport, [leg['mode'] for leg in shipment.legs]), ('land', ['land']))
        self.assertEqual(shipment.arrives_at, NOW + timedelta(hours=300 / 120), 'freight train at 120 km/h of game time')
        deliver_shipments(db.session, shipment.arrives_at); db.session.commit()
        self.assertIsNotNone(db.session.get(TradeShipment, shipment.id).delivered_at)

    def test_route_avoids_countries_at_war_with_buyer_or_seller(self):
        with patch('game.military_service.enemies', side_effect=lambda session, country: {4} if country == 2 else {2} if country == 4 else set()):
            self.assertEqual(set(self.rail()), {'land:3'})

    def test_no_rail_connection_means_no_rail_option(self):
        db.session.query(RailLine).delete(); db.session.commit()
        self.assertEqual(self.rail(), {})

    def test_sea_imf_fee_and_attack_only_at_sea(self):
        sea = next(o for o in self.options() if o['mode'] == 'sea')
        self.assertEqual((sea['imfRate'], sea['imfFee']), ('5', '50.00'))
        shipment = db.session.get(TradeShipment, buy_offer(2, {'request_id': str(uuid4()), 'offer_id': self.id, 'delivery': sea['key']}))
        self.assertEqual(trade_routes.mode_at(shipment, NOW + timedelta(minutes=1)), 'sea')
        self.assertEqual(trade_routes.imf_shipping_total(db.session)['total'], Decimal('50.00'))

    def test_customs_setting_validated(self):
        trade_routes.set_customs(1, {'rate': '7.5'})
        self.assertEqual(trade_routes.customs_rates(db.session)[1], Decimal('7.5'))
        with self.assertRaises(FinanceError):
            trade_routes.set_customs(1, {'rate': '101'})

    def test_positions_follow_the_current_leg(self):
        from datetime import datetime
        from game.trade_navigation import shipment_position
        legs, end = trade_routes.schedule([{'mode': 'land', 'km': 120, 'path': [[0, 0], [120, 0]]}, {'mode': 'sea', 'km': 100, 'path': [[120, 0], [220, 0]]}], NOW)
        ship = TradeShipment(legs=legs, transport='sea', starts_at=NOW, arrives_at=end, route=[[0, 0], [220, 0]], source_x=0, source_y=0, target_x=220, target_y=0)
        self.assertEqual(trade_routes.mode_at(ship, NOW + timedelta(minutes=30)), 'land')
        self.assertEqual(shipment_position(ship, NOW + timedelta(minutes=30))[0], 60, 'half of the 1 h rail leg')
        self.assertEqual(trade_routes.mode_at(ship, NOW + timedelta(minutes=90)), 'sea')
        self.assertEqual(shipment_position(ship, NOW + timedelta(minutes=90))[0], 170)
        self.assertEqual(end, NOW + timedelta(hours=2))

    def test_front_end(self):
        script = (ROOT / 'static/js/game_trade.js').read_text()
        for text in ("delivery:chosenOption.key", "action:'customs'", 'config.rails', 'config.citiesUrl'):
            self.assertIn(text, script)
        navigation = (ROOT / 'static/js/game_trade_navigation.js').read_text()
        self.assertIn('PACZKA.svg', navigation); self.assertIn('#f57c00', navigation)
        for name in ('game_world.js', 'game_military.js'):
            self.assertIn('GameTradeNavigation.trainSymbol', (ROOT / 'static/js' / name).read_text(), name)
        template = (ROOT / 'templates/game/trade.html').read_text()
        self.assertIn('id="trade-customs"', template); self.assertNotIn('id="trade-transport"', template)
        self.assertIn('Opłaty za wysyłkę towarów (konto MFW)', (ROOT / 'templates/game/imf.html').read_text())
