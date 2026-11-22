"""Lokalizacja magazynu państwa (22 Nov 2026): obowiązkowy wybór po pierwszym budżecie, zmiana, ikona na mapach."""
from pathlib import Path
from unittest.mock import patch
from extensions import db
from models import Miasto
from test_game_commerce import CommerceFixture
from game.finance_service import FinanceError
from game import warehouse

ROOT = Path(__file__).resolve().parents[1]


class WarehouseLocationTests(CommerceFixture):
    def setUp(self):
        super().setUp()
        db.session.add(Miasto(miasto_id=111, panstwo_id=1, region_id=1, miasto_nazwa='Stolica 1', czy_na_mapie='TAK', miasto_typ_id=1, miasto_populacja=500))
        db.session.commit()
        p = patch('game.military_geography.city_point', side_effect=lambda id: [id, 0]); p.start(); self.addCleanup(p.stop)
        p = patch('game.trade_service.city_point', side_effect=lambda id: [id, 0]); p.start(); self.addCleanup(p.stop)

    def test_required_after_first_budget_until_chosen(self):
        self.assertTrue(warehouse.required(db.session, 1), 'country 1 approved a budget and has no warehouse')
        self.assertFalse(warehouse.required(db.session, 2), 'no approved budget yet')
        self.assertEqual(warehouse.warehouse_city(db.session, 1), 111, 'without a choice the capital serves as warehouse')
        warehouse.choose(1, 1, 101)
        db.session.expire_all()
        self.assertFalse(warehouse.required(db.session, 1))
        self.assertEqual(warehouse.warehouse_city(db.session, 1), 101)
        with self.app.test_request_context():
            self.assertEqual(warehouse.marker(db.session, 1)['name'], 'Port 1')
            self.assertIsNone(warehouse.marker(db.session, 2), 'other countries never see the icon')

    def test_only_own_cities_and_relocation(self):
        with self.assertRaisesRegex(FinanceError, 'własnego państwa'):
            warehouse.choose(1, 1, 102)
        warehouse.choose(1, 1, 101)
        warehouse.choose(1, 1, 111)   # zmiana lokalizacji
        db.session.expire_all()
        self.assertEqual(warehouse.chosen_city(db.session, 1), 111)

    def test_lost_city_requires_a_new_choice(self):
        warehouse.choose(1, 1, 101)
        db.session.get(Miasto, 101).panstwo_id = 2; db.session.commit()
        self.assertIsNone(warehouse.chosen_city(db.session, 1))
        self.assertTrue(warehouse.required(db.session, 1))

    def test_route_checks_csrf_and_saves(self):
        self.login(1)
        url = '/game/magazyn/lokalizacja'
        with patch('game.forum.player', return_value=(type('U', (), {'id': 1})(), type('C', (), {'PANSTWO_ID': 1})())):
            self.assertEqual(self.client.post(url, json={'city_id': 101}).status_code, 403)
            response = self.client.post(url, json={'city_id': 101}, headers={'X-CSRF-Token': 'token'})
            self.assertEqual(response.status_code, 200, response.json)
            self.assertEqual(self.client.post(url, json={'city_id': 102}, headers={'X-CSRF-Token': 'token'}).status_code, 400)
        db.session.expire_all()
        self.assertEqual(warehouse.chosen_city(db.session, 1), 101)

    def test_templates_maps_and_guard(self):
        main = (ROOT / 'templates/game/game_main_page.html').read_text()
        self.assertIn("game/_warehouse_modal.html", main)
        self.assertIn("'warehouse': game_panel.warehouse", main)
        trade = (ROOT / 'templates/game/trade.html').read_text()
        self.assertIn('data-warehouse-open', trade); self.assertIn('Zmień lokalizację magazynu', trade)
        for name in ('game_panel_map.js', 'game_world.js', 'game_trade.js'):
            self.assertIn('GameWarehouse?.marker(map', (ROOT / 'static/js' / name).read_text(), name)
        script = (ROOT / 'static/js/game_warehouse_location.js').read_text()
        self.assertIn("if (config.required) event.preventDefault()", script, 'the mandatory window cannot be dismissed')
        self.assertIn('"game_warehouse"', (ROOT / 'zeus_app.py').read_text())
