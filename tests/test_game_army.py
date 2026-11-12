from decimal import Decimal
import unittest
"""Wojsko gracza: odczyt jego kraju, brak danych i kontrola dostępu."""
from flask import template_rendered
from game_features_support import FeatureTestCase
from extensions import db
from game.army import army_bp
from game.models import GameUser
from models import Wojsko


class GameArmyTests(FeatureTestCase):
    def setUp(self):
        super().setUp()
        self.app.register_blueprint(army_bp)
        db.metadata.create_all(db.engine, tables=[Wojsko.__table__])
        db.session.add_all([
            Wojsko(panstwo_id=1, wojska_ladowe_ilosc=12345, wojska_morskie_ilosc=0,
                   wojska_powietrzne_ilosc=200, czolgi_ilosc=123, procent_PKB=2.5),
            Wojsko(panstwo_id=2, wojska_ladowe_ilosc=999999),
        ])
        db.session.commit()

    def test_own_country_and_shared_icons(self):
        contexts = []
        def capture(sender, template, context, **extra):
            contexts.append(context)
        with template_rendered.connected_to(capture, self.app):
            response = self.client.get('/game/sily-zbrojne?country_id=2')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(contexts[-1]['army'].panstwo_id, 1)
        html = response.get_data(as_text=True)
        self.assertIn('12 345', html)
        self.assertIn('Budżet sił zbrojnych na bieżące półrocze', html)
        self.assertIn('W służbie czynnej',html)
        self.assertNotIn('2.5 %',html)
        self.assertNotIn('999 999', html)
        self.assertIn('CZ%C5%81OWIEK.svg', html)
        self.assertEqual(html.count('icons/BAZA.svg'), 3)
        self.assertIn('aria-current="page"', html)
        with self.app.test_request_context():
            module = self.app.jinja_env.get_template('macros/army.html').module
        for field, label, icon_key in module.army_fields:
            if field != 'procent_PKB':
                self.assertIn(label, html)
        # 12 Nov 2026: karty w grupach tematycznych, budżet w grupie budżetowej (nie między jednostkami)
        self.assertIn('class="game-sidebar"',html);self.assertIn('Średni poziom infrastruktury',html)   # stały lewy pasek (13 Nov 2026)
        order=[html.index(text) for text in ('Budżet i zaopatrzenie','Budżet sił zbrojnych','Wojska lądowe','Czołgi','Marynarka wojenna','Lotniskowce','Siły powietrzne','Myśliwce','Rakiety i broń strategiczna','Broń atomowa')]
        self.assertEqual(order,sorted(order))

    def test_missing_data(self):
        self.login(3)
        response = self.client.get('/game/sily-zbrojne')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Brak danych wojskowych', response.get_data(as_text=True))

    def test_authentication_and_assignment(self):
        self.login(4)
        self.assertEqual(self.client.get('/game/sily-zbrojne').status_code, 403)
        self.login(1)
        db.session.get(GameUser, 1).is_active = False
        db.session.commit()
        self.assertEqual(self.client.get('/game/sily-zbrojne').status_code, 302)
        with self.client.session_transaction() as browser:
            browser.clear()
        self.assertEqual(self.client.get('/game/sily-zbrojne').status_code, 302)


class SidebarTests(unittest.TestCase):
    """13 Nov 2026: wycinki wykresu budżetu proporcjonalne do przydziału sektora."""
    def test_budget_pie_segments(self):
        from game.sidebar import budget_pie
        items=[{'code':'administration','label':'Administracja','allocated':Decimal(300),'remaining':Decimal(100),'spent':Decimal(200)},
               {'code':'armed_forces','label':'Siły zbrojne','allocated':Decimal(100),'remaining':Decimal(100),'spent':Decimal(0)},
               {'code':'research','label':'Badania','allocated':Decimal(0),'remaining':Decimal(0),'spent':Decimal(0)}]
        segments=budget_pie(items)
        self.assertEqual([s['code'] for s in segments],['administration','armed_forces'])   # sektor bez przydziału pominięty
        self.assertEqual([s['share'] for s in segments],[75.0,25.0])
        self.assertTrue(all(s['path'].startswith('M') and s['path'].endswith('Z') for s in segments))
        self.assertEqual(budget_pie([{'code':'x','label':'x','allocated':0,'remaining':0}]),[])
