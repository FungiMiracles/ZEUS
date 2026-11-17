"""Infrastruktura: dostęp, izolacja państwa i progi kolorów WIKI."""
from flask import template_rendered
from game_features_support import FeatureTestCase
from extensions import db
from game.infrastructure import infrastructure_bp, indicator
from game.models import GameUser
from models import Region


class InfrastructureTests(FeatureTestCase):
    def setUp(self):
        super().setUp()
        self.app.register_blueprint(infrastructure_bp)
        from game.infrastructure_models import InfrastructureProject
        InfrastructureProject.__table__.create(db.engine, checkfirst=True)
        from models import Miasto
        Miasto.__table__.create(db.engine)
        # Minimalne tabele do testowania operacji; reguły schematu finansów są niezależne.
        from sqlalchemy import MetaData, Table, Column, String
        from game.finance_models import StateBudget, StateBudgetAllocation, StateFinancialAccount
        metadata = MetaData()
        for model in (StateBudget, StateBudgetAllocation, StateFinancialAccount):
            Table(model.__tablename__, metadata, *[Column(c.name, String(c.type.length) if isinstance(c.type, String) else c.type, primary_key=c.primary_key, nullable=True) for c in model.__table__.columns]).create(db.engine, checkfirst=True)
        row = db.session.get(Region, 1)
        row.region_stan_infra_drogowej = 85
        row.region_stan_infra_kolejowej = 70
        row.region_stan_infra_energetycznej = 60
        row.region_stan_infra_mieszkalnej = 40
        row.region_stan_infra_portowej = 0
        row.region_poziom_skomunikowania = 100
        db.session.commit()

    def test_country_and_six_indicators(self):
        contexts = []
        def capture(sender, template, context, **extra):
            contexts.append(context)
        with template_rendered.connected_to(capture, self.app):
            response = self.client.get('/game/infrastruktura?country_id=2')
        self.assertEqual(response.status_code, 200)
        data = contexts[-1]['infrastructure_map']
        self.assertEqual(data['countryId'], 1)
        self.assertEqual(set(data['regions']), {'1'})
        self.assertEqual(len(data['metrics']), 6)
        values = data['regions']['1']['indicators']
        self.assertEqual(values['road'], {'value': 85, 'color': 'green'})
        self.assertEqual(values['port'], {'value': 0, 'color': '#e74c3c'})
        self.assertEqual(values['connection']['value'], 100)
        for metric in data['metrics']:
            with self.client.get(metric['icon']) as icon_response:
                self.assertEqual(icon_response.status_code, 200)
        self.assertIn('id="infrastructure-map"', response.get_data(as_text=True))

    def test_wiki_color_boundaries_and_missing_values(self):
        for value, color in [(0, '#e74c3c'), (39, '#e74c3c'), (40, '#e67e22'),
                             (59, '#e67e22'), (60, '#f1c40f'), (74, '#f1c40f'),
                             (75, 'green'), (89, 'green'), (90, 'darkgreen'), (100, 'darkgreen')]:
            self.assertEqual(indicator(value), {'value': value, 'color': color})
        for value in [None, -1, 101]:
            self.assertEqual(indicator(value), {'value': None, 'color': '#7f8c8d'})

    def test_empty_country(self):
        self.login(3)
        response = self.client.get('/game/infrastruktura')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Brak regionów przypisanych', response.get_data(as_text=True))

    def test_authentication_and_assignment(self):
        self.login(4)
        self.assertEqual(self.client.get('/game/infrastruktura').status_code, 403)
        self.login(1)
        db.session.get(GameUser, 1).is_active = False
        db.session.commit()
        self.assertEqual(self.client.get('/game/infrastruktura').status_code, 302)
        with self.client.session_transaction() as browser:
            browser.clear()
        self.assertEqual(self.client.get('/game/infrastruktura').status_code, 302)


class ConstructionTests(InfrastructureTests):
    def prepare_budget(self):
        from sqlalchemy import text
        db.session.execute(text("INSERT INTO game_state_budgets (id, panstwo_id, game_year, period, closing_reserve) VALUES (1,1,2990,1,3000000000)"))
        db.session.execute(text("INSERT INTO game_state_budget_allocations (id,budget_id,category_code,amount) VALUES (1,1,'road_infrastructure',1000000000)"))
        db.session.execute(text("INSERT INTO game_state_financial_accounts (panstwo_id,reserve_balance,last_budget_id) VALUES (1,3000000000,1)"))
        region = db.session.get(Region, 1)
        region.region_ludnosc_pozamiejska = 10000000
        db.session.commit()

    def start(self, metric='road', levels=1, reserve=False, region=1):
        from unittest.mock import patch
        from datetime import datetime
        from types import SimpleNamespace
        from game.infrastructure_service import start_project
        with patch('game.infrastructure_service.game_now', return_value=datetime(2990,1,1)), patch('game.infrastructure_service._country_for_user', return_value=SimpleNamespace(PANSTWO_ID=1)):
            return start_project(1, region, metric, levels, reserve)

    def test_cost_and_duration(self):
        from game.infrastructure_service import quote
        from decimal import Decimal
        self.assertEqual(quote(10000000, 'road'), (Decimal('2000000000'), 4))
        self.assertEqual(quote(10000000, 'housing'), (Decimal('2500000000'), 4))
        self.assertEqual(quote(10000001, 'port')[1], 4)
        self.assertEqual(quote(1, 'rail')[1], 4)

    def test_payment_and_completion_exactly_once(self):
        from datetime import datetime
        from game.infrastructure_models import InfrastructureProject as Project
        from game.infrastructure_service import complete_due
        from game.finance_models import StateFinancialAccount
        self.prepare_budget()
        self.start(reserve=True)
        db.session.expire_all()
        project = db.session.query(Project).one()
        self.assertEqual(project.budget_spent, 1000000000)
        self.assertEqual(project.reserve_spent, 1000000000)
        self.assertEqual(db.session.get(StateFinancialAccount, 1).reserve_balance, 2000000000)
        self.assertEqual(db.session.get(Region, 1).region_stan_infra_drogowej, 85)
        complete_due(db.session, datetime(2990,1,4))
        self.assertIsNone(project.completed_at)
        complete_due(db.session, datetime(2990,1,5))
        complete_due(db.session, datetime(2990,1,6))
        self.assertEqual(db.session.get(Region, 1).region_stan_infra_drogowej, 86)
        self.assertIsNotNone(project.completed_at)

    def test_rejections_are_atomic(self):
        from game.finance_service import FinanceError
        from game.infrastructure_models import InfrastructureProject as Project
        self.prepare_budget()
        for kwargs in ({}, {'metric':'port'}, {'metric':'connection'}, {'levels':16}, {'levels':True}, {'region':2}, {'levels':3,'reserve':True}):
            with self.assertRaises(FinanceError):
                self.start(**kwargs)
        self.assertEqual(db.session.query(Project).count(), 0)
        self.start(reserve=True)
        with self.assertRaises(FinanceError):
            self.start(reserve=True)
        self.assertEqual(db.session.query(Project).count(), 1)

    def test_csrf_and_connection_endpoint(self):
        self.assertEqual(self.client.post('/game/infrastruktura/rozbuduj', json={}).status_code, 403)
        response = self.client.post('/game/infrastruktura/rozbuduj', json={'region_id':1,'metric':'connection','levels':1}, headers={'X-CSRF-Token':'token'})
        self.assertEqual(response.status_code, 400)


    def test_reserve_carries_into_next_budget(self):
        from game.finance_models import StateBudget, StateFinancialAccount
        from game.finance_service import _reserve_for_account
        self.prepare_budget()
        self.start(reserve=True)
        db.session.expire_all()
        self.assertEqual(_reserve_for_account(db.session.get(StateFinancialAccount, 1), db.session.get(StateBudget, 1)), 2000000000)

    def test_missing_current_budget(self):
        from game.finance_service import FinanceError
        region = db.session.get(Region, 1)
        region.region_ludnosc_pozamiejska = 10000000
        db.session.commit()
        with self.assertRaisesRegex(FinanceError, 'budżet'):
            self.start()


    def test_duration_increases_with_levels(self):
        from game.infrastructure_models import InfrastructureProject as Project
        self.prepare_budget()
        from sqlalchemy import text
        db.session.execute(text("UPDATE game_state_budget_allocations SET amount=10000000000"))
        db.session.commit()
        self.start(levels=2)
        project = db.session.query(Project).one()
        self.assertEqual((project.ends_at - project.starts_at).days, 8)

    def test_map_cities_are_limited_to_country(self):
        from models import Miasto
        db.session.add_all([
            Miasto(miasto_id=1, panstwo_id=1, region_id=1, miasto_nazwa='Nasze miasto'),
            Miasto(miasto_id=2, panstwo_id=2, region_id=2, miasto_nazwa='Obce miasto'),
            Miasto(miasto_id=3, panstwo_id=1, region_id=1, miasto_nazwa='Ukryte miasto', czy_na_mapie='NIE'),
        ])
        db.session.commit()
        contexts = []
        def capture(sender, template, context, **extra):
            contexts.append(context)
        with template_rendered.connected_to(capture, self.app):
            response = self.client.get('/game/infrastruktura')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(contexts[-1]['infrastructure_map']['cities'], {'1': {'name': 'Nasze miasto', 'regionId': '1'}})
        self.assertIn('expand-reserve-value', response.get_data(as_text=True))


    def test_distinct_insufficient_funds_messages(self):
        from game.finance_service import FinanceError
        from game.infrastructure_models import InfrastructureProject as Project
        from game.finance_models import StateFinancialAccount
        self.prepare_budget()
        with self.assertRaisesRegex(FinanceError, 'Zaznacz zgodę'):
            self.start()
        for reserve in (False, True):
            with self.assertRaisesRegex(FinanceError, 'łącznie nie pokrywają'):
                self.start(levels=3, reserve=reserve)
        db.session.expire_all()
        self.assertEqual(db.session.query(Project).count(), 0)
        self.assertEqual(db.session.get(StateFinancialAccount, 1).reserve_balance, 3000000000)


    def test_overseas_regions_excluded_from_map_scope(self):
        from game.country_summary import metropolitan_region_ids
        db.session.add(Region(region_id=3, panstwo_id=1, region_nazwa='Zamorskie', terytorium_zamorskie=True))
        db.session.commit()
        self.assertEqual(metropolitan_region_ids(1), ['1'])
        for path, key in [('/game/infrastruktura', 'infrastructure_map'), ('/game/srodowisko', 'environment_map')]:
            contexts = []
            def capture(sender, template, context, **extra):
                contexts.append(context)
            with template_rendered.connected_to(capture, self.app):
                response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(contexts[-1][key]['metropolitanRegionIds'], ['1'])
            self.assertIn('3', contexts[-1][key]['regions'])
        db.session.get(Region, 1).terytorium_zamorskie = True
        db.session.commit()
        self.assertEqual(metropolitan_region_ids(1), [])
        db.session.get(Region, 3).terytorium_zamorskie = False
        db.session.commit()
        self.assertEqual(metropolitan_region_ids(1), ['3'])

    def add_due_project(self):
        from datetime import datetime
        from game.infrastructure_models import InfrastructureProject as Project
        project = Project(panstwo_id=1, region_id=1, budget_id=1, metric='road', levels=2,
                          cost=4000000000, budget_spent=4000000000, reserve_spent=0,
                          starts_at=datetime(2990, 1, 1), ends_at=datetime(2990, 1, 9))
        db.session.add(project)
        db.session.commit()
        return project

    def test_completion_notification_once_private_and_readable(self):
        from datetime import datetime
        from unittest.mock import patch
        from game.forum_models import GameNotification
        self.add_due_project()
        with patch('game.finance_service.game_now', return_value=datetime(2990, 1, 8)):
            self.assertEqual(self.client.get('/game/forum/powiadomienia').json['unread_count'], 0)
        with patch('game.finance_service.game_now', return_value=datetime(2990, 1, 9)):
            for _ in range(2):
                feed = self.client.get('/game/forum/powiadomienia').json
                self.assertEqual(feed['unread_count'], 1)
                self.assertEqual(feed['items'][0]['text'], 'Zakończyła się rozbudowa infrastruktury drogowej w regionie Pierwszy region')
            self.assertEqual(db.session.query(GameNotification).count(), 1)
            self.assertEqual(db.session.get(Region, 1).region_stan_infra_drogowej, 87)
            path = feed['items'][0]['open_url']
            self.login(2)
            self.assertEqual(self.client.get('/game/forum/powiadomienia').json['unread_count'], 0)
            self.assertEqual(self.post(path).status_code, 404)
            self.login(1)
            response = self.post(path)
            self.assertEqual(response.status_code, 303)
            self.assertTrue(response.location.endswith('/game/infrastruktura'))
            self.assertEqual(self.client.get('/game/forum/powiadomienia').json['unread_count'], 0)

    def test_production_stop_notifications_open_infrastructure_screen(self):
        # 16 Nov 2026: zatrzymanie fabryki, kopalni lub elektrowni — powiadomienie prowadzi do „Infrastruktura i energetyka”.
        from game.forum_models import GameNotification
        texts = ['Fabryka amunicji #3: produkcja została wstrzymana — brak energii w sieci (deficyt energii).',
                 'Elektrownia węglowa #4: produkcja energii została wstrzymana — brak paliwa lub uszkodzenie.',
                 'Elektrownia #9: produkcja energii wstrzymana po trafieniu.',
                 'Kopalnia węgla #2: wydobycie zatrzymane — wyczerpano złoże w regionie.']
        rows = [GameNotification(user_id=1, notification_type='SYSTEM', system_text=text) for text in texts]
        other = GameNotification(user_id=1, notification_type='SYSTEM', system_text='Państwo X przeprowadziło atak na cel: baza.')
        db.session.add_all(rows + [other]); db.session.commit()
        for row in rows:
            response = self.post(f'/game/forum/powiadomienia/{row.id}/otworz')
            self.assertEqual(response.status_code, 303)
            self.assertTrue(response.location.endswith('/game/infrastruktura'), row.system_text)
        self.assertFalse(self.post(f'/game/forum/powiadomienia/{other.id}/otworz').location.endswith('/game/infrastruktura'))

    def test_completion_notification_rollback(self):
        from datetime import datetime
        from game.forum_models import GameNotification
        from game.infrastructure_service import complete_due
        from game.infrastructure_models import InfrastructureProject as Project
        self.add_due_project()
        complete_due(db.session, datetime(2990, 1, 9))
        self.assertEqual(db.session.query(GameNotification).count(), 1)
        db.session.rollback()
        self.assertEqual(db.session.query(GameNotification).count(), 0)
        self.assertIsNone(db.session.query(Project).one().completed_at)
        self.assertEqual(db.session.get(Region, 1).region_stan_infra_drogowej, 85)

    def test_background_completion_without_visiting_page(self):
        from datetime import datetime
        from unittest.mock import patch
        from engine.infrastructure_scheduler import run_infrastructure_tick
        from game.forum_models import GameNotification
        self.add_due_project()
        with patch('engine.infrastructure_scheduler.game_now', return_value=datetime(2990, 1, 9)):
            run_infrastructure_tick(self.app)
            run_infrastructure_tick(self.app)
        db.session.expire_all()
        self.assertEqual(db.session.query(GameNotification).count(), 1)
        self.assertEqual(db.session.get(Region, 1).region_stan_infra_drogowej, 87)


class ForeignMapRegressionTests(InfrastructureTests):
    def test_page_with_region_without_sovereign_controller(self):
        from models import Panstwo
        from sqlalchemy import update
        db.session.execute(update(Panstwo).where(Panstwo.PANSTWO_ID==4).values(czy_suwerenny='NIE'))
        db.session.add(Region(region_id=3,panstwo_id=4,region_nazwa='Bez gospodarza'))
        db.session.commit()
        response=self.client.get('/game/infrastruktura')
        self.assertEqual(response.status_code,200)
        self.assertIn('Bez gospodarza',response.get_data(as_text=True))
