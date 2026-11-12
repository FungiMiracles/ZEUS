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
