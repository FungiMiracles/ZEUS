"""18 Nov 2026: państwo bez własnego portu wysyła i odbiera ładunki tylko przez port najbliższego sąsiada (sąsiad → sąsiad sąsiada)."""
from uuid import uuid4
from unittest.mock import patch
from extensions import db
from models import Miasto, Region
from test_game_commerce import CommerceFixture
from game.finance_service import FinanceError
from game.trade_service import create_offer, departure_countries


class NeighborPortTests(CommerceFixture):
    def setUp(self):
        super().setUp()
        db.session.add_all([Region(region_id=3, panstwo_id=3, region_nazwa='Trzeci region'),
                            Region(region_id=4, panstwo_id=4, region_nazwa='Czwarty region')])
        db.session.add(Miasto(miasto_id=104, panstwo_id=4, region_id=4, miasto_nazwa='Port 4', czy_portowe='TAK', czy_na_mapie='TAK'))
        db.session.get(Miasto, 101).czy_portowe = 'NIE'   # państwo 1 bez portu
        db.session.commit()
        # 1 graniczy z 2; 2 graniczy z 3; 4 leży daleko (brak granicy z 1, 2, 3)
        adjacency = {1: {2}, 2: {1, 3}, 3: {2}, 4: set()}
        p = patch('game.military_geography.region_adjacency', return_value=adjacency); p.start(); self.addCleanup(p.stop)

    # 22 Nov 2026: port wybiera gra przy zakupie (game.trade_routes.allowed_ports) — reguła portu sąsiada bez zmian.
    def ports(self, country=1):
        from game.trade_routes import allowed_ports
        return sorted(port.miasto_id for port in allowed_ports(db.session, country))

    def test_only_direct_neighbor_port_when_neighbor_has_one(self):
        self.assertEqual(departure_countries(db.session, 1), {2})
        self.assertEqual(self.ports(), [102])

    def test_neighbor_of_neighbor_when_no_neighbor_has_port(self):
        db.session.get(Miasto, 102).czy_portowe = 'NIE'; db.session.commit()
        self.assertEqual(departure_countries(db.session, 1), {3})
        self.assertEqual(self.ports(), [103])

    def test_own_port_rule_unchanged(self):
        db.session.get(Miasto, 101).czy_portowe = 'TAK'; db.session.commit()
        self.assertIsNone(departure_countries(db.session, 1))
        self.assertEqual(self.ports(), [101])

    def test_isolated_country_falls_back_to_any_port(self):
        db.session.get(Miasto, 102).czy_portowe = 'NIE'; db.session.get(Miasto, 103).czy_portowe = 'NIE'; db.session.commit()
        self.assertEqual(departure_countries(db.session, 1), {4})
        self.assertEqual(self.ports(), [104])

    def test_screen_marks_departure_ports(self):
        from game.commerce import trade_state
        with self.app.test_request_context():
            ports = trade_state(1)['ports']
        self.assertTrue(ports['102']['departureAllowed'])
        self.assertFalse(ports['103']['departureAllowed'])
        self.assertFalse(ports['103']['allowed'])  # 18 Nov 2026: odbiór też tylko przez port najbliższego sąsiada

    def test_arrival_port_follows_neighbor_rule(self):
        # Państwo 1 (bez portu) kupuje od dalekiego państwa 4: odbiór tylko w porcie najbliższego sąsiada (102, potem koleją
        # do magazynu), nie w porcie 103 sąsiada sąsiada.
        from datetime import datetime, timedelta
        from game.trade_service import buy_offer
        from game.finance_models import StateFinancialAccount
        from game.commerce_models import ResourceStock, TradeShipment
        from game.rail_models import RailLine
        now = datetime(2990, 1, 1)
        RailLine.__table__.create(db.engine, checkfirst=True)
        db.session.add(RailLine(initiator_id=1, partner_id=2, city_a_id=101, city_b_id=102, path=[[0, 0], [100, 0]], distance_km=100, cost=0, shares={}, build_days=1,
                                status='ACTIVE', starts_at=now - timedelta(days=5), ready_at=now - timedelta(days=1), request_id=str(uuid4())))
        db.session.add(ResourceStock(panstwo_id=4, resource='wegiel_kamienny', quantity=5))
        db.session.add(StateFinancialAccount(panstwo_id=1, reserve_balance=100000, last_transaction_sequence=0, created_at=now, updated_at=now))
        db.session.commit()
        with patch('game.trade_service._country_for_user', side_effect=lambda session, user_id, lock=False: __import__('types').SimpleNamespace(PANSTWO_ID=4)):
            offer = create_offer(4, dict(request_id=str(uuid4()), cargo={'wegiel_kamienny': 1}, price='10'))
        with self.assertRaises(FinanceError):
            buy_offer(1, {'request_id': str(uuid4()), 'offer_id': offer, 'delivery': 'sea:103'})
        shipment = buy_offer(1, {'request_id': str(uuid4()), 'offer_id': offer, 'delivery': 'sea:102'})
        row = db.session.get(TradeShipment, shipment)
        self.assertEqual(row.arrival_port_id, 102)
        self.assertEqual([leg['mode'] for leg in row.legs], ['sea', 'land'], 'ship to the neighbour port, then rail to the warehouse')
