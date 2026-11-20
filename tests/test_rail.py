"""Kolej (19 Nov 2026): technologie, czas budowy, bonus budżetowy, ludność połączona koleją, wydatki infrastruktury i PAGA2."""
import unittest
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace as NS
from unittest.mock import patch
from sqlalchemy import text
from extensions import db
from models import Miasto
from game.rail_models import RailLine, RailExpense
from game import rail
from test_game_military import MilitaryFixture, NOW


class RailRulesTests(unittest.TestCase):
    def test_technologies(self):
        from game.industry_catalog import TECHNOLOGIES
        from game.research_timing import DURATION_DAYS
        hubs, line = TECHNOLOGIES['national_hubs'], TECHNOLOGIES['rail_transport']
        self.assertEqual((hubs['cost'], hubs['parent'], DURATION_DAYS['national_hubs']), (50, 'method', 14))
        self.assertEqual((line['cost'], line['parent'], DURATION_DAYS['rail_transport']), (200, 'national_hubs', 21))
        from game.research import technology_layout
        self.assertIn('rail_transport', technology_layout()['positions'])

    def test_build_days_cut_remainder(self):
        self.assertEqual(rail.build_days(Decimal('230')), 4)
        self.assertEqual(rail.build_days(Decimal('49.9')), 1)
        self.assertEqual(rail.build_days(Decimal('50')), 1)
        self.assertEqual(rail.build_days(Decimal('100')), 2)

    def test_price(self):
        self.assertEqual(rail.PRICE_PER_KM, Decimal('6000000'))

    def test_bonus_formula(self):
        # PKB per capita 30 000 × 0,01 × 5,5 mln połączonych = 1,65 MLD
        self.assertEqual(rail.bonus(Decimal('300000000000'), 10_000_000, 5_500_000), Decimal('1650000000.00'))
        self.assertEqual(rail.bonus(Decimal('1'), 0, 10), Decimal('0.00'))
        # 19 Nov 2026: × średnia infrastruktura kolejowa / 100 (65 → × 0,65)
        self.assertEqual(rail.bonus(Decimal('300000000000'), 10_000_000, 5_500_000, 65), Decimal('1072500000.00'))
        self.assertEqual(rail.bonus(Decimal('300000000000'), 10_000_000, 5_500_000, 0), Decimal('0.00'))

    def test_budget_includes_rail_income(self):
        from game.finance_service import calculate_budget
        from game.finance_service import EXPENDITURE_CODES
        shares = {code: 0 for code in EXPENDITURE_CODES}
        shares[EXPENDITURE_CODES[0]] = 50
        shares['reserve'] = 50
        base = calculate_budget(Decimal('300000000000'), 10_000_000, Decimal('100'), 10, 10, shares)
        with_rail = calculate_budget(Decimal('300000000000'), 10_000_000, Decimal('100'), 10, 10, shares, rail_population=5_500_000)
        self.assertEqual(base['rail_income'], 0)
        self.assertEqual(with_rail['rail_income'], Decimal('1650000000.00'))
        lower = calculate_budget(Decimal('300000000000'), 10_000_000, Decimal('100'), 10, 10, shares, rail_population=5_500_000, rail_infrastructure=Decimal('65'))
        self.assertEqual(lower['rail_income'], Decimal('1072500000.00'))
        self.assertEqual(with_rail['budget_total'], with_rail['opening_reserve'] + with_rail['tax_total'] + with_rail['rail_income'] - with_rail['imf_collection'])


class RailCoastRouteTests(unittest.TestCase):
    """19 Nov 2026: gdy prosta trasa przecina wodę (zatoka), tor biegnie po lądzie wzdłuż wybrzeża."""

    def features(self):
        # ląd w kształcie litery U: zatoka (woda) między ramionami x∈(2,8), y>2
        ring = [[0, 0], [10, 0], [10, 10], [8, 10], [8, 2], [2, 2], [2, 10], [0, 10], [0, 0]]
        return [{'owner': 1, 'geometry': {'type': 'Polygon', 'coordinates': [ring]}, 'bounds': (0, 0, 10, 10)}]

    def test_route_goes_around_the_bay(self):
        from shapely.geometry import LineString, Polygon
        features = self.features()
        a = {'name': 'A', 'point': [1, 9]}
        b = {'name': 'B', 'point': [9, 9]}
        path = rail._route(features, a, b, km_per_unit=1)
        land = Polygon(features[0]['geometry']['coordinates'][0]).buffer(.2)
        self.assertTrue(land.covers(LineString(path)), path)
        self.assertGreater(rail.path_length(path), 20)          # wokół zatoki, nie 8 jednostek na wprost
        self.assertEqual((path[0], path[-1]), ([1, 9], [9, 9]))

    def test_partition_skips_pieces_over_water(self):
        """19 Nov 2026 (Saint Mona – Harffa): odcinek poza lądem nie przerywa podziału kosztów między państwa."""
        a = {'owner': 1, 'geometry': {'type': 'Polygon', 'coordinates': [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]}, 'bounds': (0, 0, 10, 10)}
        b = {'owner': 2, 'geometry': {'type': 'Polygon', 'coordinates': [[[10, 0], [20, 0], [20, 10], [10, 10], [10, 0]]]}, 'bounds': (10, 0, 20, 10)}
        parts = rail.partition([[-2, 5], [5, 5], [15, 5]], [a, b])      # start 2 jednostki nad wodą (port)
        self.assertEqual([p['countryId'] for p in parts], [1, 2])
        self.assertEqual(rail.path_length(parts[0]['path']), 10)

    def test_separate_islands_are_rejected(self):
        from game.finance_service import FinanceError
        island = lambda x: {'owner': 1, 'geometry': {'type': 'Polygon', 'coordinates': [[[x, 0], [x + 2, 0], [x + 2, 2], [x, 2], [x, 0]]]}, 'bounds': (x, 0, x + 2, 2)}
        with self.assertRaises(FinanceError):
            rail._route([island(0), island(10)], {'name': 'A', 'point': [1, 1]}, {'name': 'B', 'point': [11, 1]}, km_per_unit=1)


class RailDataTests(MilitaryFixture):
    def setUp(self):
        super().setUp()
        for model in (RailLine, RailExpense):
            model.__table__.create(db.engine, checkfirst=True)
        db.session.add_all([Miasto(miasto_id=11, miasto_nazwa='A', panstwo_id=1, miasto_populacja=1_000_000, czy_na_mapie='TAK'),
                            Miasto(miasto_id=12, miasto_nazwa='B', panstwo_id=1, miasto_populacja=3_000_000, czy_na_mapie='TAK'),
                            Miasto(miasto_id=13, miasto_nazwa='C', panstwo_id=1, miasto_populacja=1_500_000, czy_na_mapie='TAK'),
                            Miasto(miasto_id=14, miasto_nazwa='D', panstwo_id=1, miasto_populacja=9_000_000, czy_na_mapie='TAK'),
                            Miasto(miasto_id=21, miasto_nazwa='X', panstwo_id=2, miasto_populacja=7_000_000, czy_na_mapie='TAK')])
        db.session.commit()

    def line(self, a, b, status='ACTIVE', ready=-1, partner=None, key=None):
        row = RailLine(initiator_id=1, partner_id=partner, city_a_id=a, city_b_id=b, path=[[0, 0], [1, 1]], distance_km=100, cost=600000000,
                       shares={'1': {'countryId': 1, 'distanceKm': '100', 'cost': '600000000'}}, build_days=2, status=status,
                       starts_at=NOW - timedelta(days=3), ready_at=NOW + timedelta(days=ready), request_id=key or f'{a}-{b}-{status}')
        db.session.add(row); db.session.commit(); return row

    def test_connected_population_counts_completed_lines_and_each_city_once(self):
        self.line(11, 12); self.line(12, 13)                 # A–B–C: 1 + 3 + 1,5 mln (B raz)
        self.line(13, 14, ready=+5)                          # w budowie — D się nie liczy
        self.line(14, 11, status='PENDING', key='p')         # wniosek — nie liczy się
        self.line(11, 21, partner=2, key='x')                # linia do sąsiada: liczy się tylko własne miasto A
        with patch('game.rail.controlled_ids', side_effect=lambda s, c: [c]):
            self.assertEqual(rail.connected_population(db.session, 1, NOW), 5_500_000)
            self.assertEqual(rail.connected_population(db.session, 2, NOW), 7_000_000)

    def test_only_largest_coherent_network_counts(self):
        # 20 Nov 2026: odcinki A–B i C–D nie tworzą sieci — liczy się tylko większa z nich (C–D: 1,5 + 9 mln)
        self.line(11, 12); self.line(13, 14)
        with patch('game.rail.controlled_ids', side_effect=lambda s, c: [c]):
            self.assertEqual(rail.connected_population(db.session, 1, NOW), 10_500_000)
            self.assertEqual(rail.network(db.session, 1, NOW)[0], {13, 14})
            self.line(12, 13, key='bc')                      # B–C łączy oba odcinki w jedną sieć A–B–C–D
            self.assertEqual(rail.connected_population(db.session, 1, NOW), 14_500_000)

    def test_wiki_network_summary(self):
        # 20 Nov 2026: strona państwa w WIKI — linie państwa, budowy i spójna sieć
        self.line(11, 12); self.line(13, 14, ready=+5); self.line(11, 21, partner=2, key='x')
        points = {11: [0, 0], 12: [1, 0], 13: [2, 0], 14: [3, 0], 21: [4, 0]}
        with patch('game.rail.controlled_ids', side_effect=lambda s, c: [c]), \
             patch('game.military_geography.city_point', side_effect=points.get), patch('game.rail._multiplier', return_value=12), patch('game.rail.game_now', return_value=NOW):
            data = rail.wiki_network(db.session, 1)
            self.assertEqual({k: data['summary'][k] for k in ('lines', 'completed', 'building', 'international', 'networkCities')},
                             {'lines': 3, 'completed': 2, 'building': 1, 'international': 1, 'networkCities': 2})
            self.assertEqual(data['summary']['networkPopulation'], 4_000_000)
            self.assertEqual({c['id'] for c in data['cities'] if c['inNetwork']}, {11, 12})   # miasto sąsiada — tylko węzeł
            self.assertEqual(rail.wiki_network(db.session, 2)['summary']['lines'], 1)     # współfinansowana linia sąsiada

    def test_network_through_neighbour_city(self):
        # A–X i X–D (X — miasto sąsiada): A i D w jednej sieci, ludność X się nie liczy
        self.line(11, 21, partner=2, key='ax'); self.line(21, 14, partner=2, key='xd'); self.line(12, 13, key='bc')
        with patch('game.rail.controlled_ids', side_effect=lambda s, c: [c]):
            self.assertEqual(rail.connected_population(db.session, 1, NOW), 10_000_000)

    def test_infrastructure_balance_includes_rail_expenses(self):
        from game.budget_transfers import infrastructure_balance
        from game.finance_models import StateBudget
        db.session.execute(text("INSERT INTO game_state_budget_allocations (id,budget_id,category_code,amount) VALUES (2,1,'infrastructure',1000000000)"))
        db.session.commit()
        budget = db.session.get(StateBudget, 1)
        before = infrastructure_balance(db.session, budget)[1]
        line = self.line(11, 12)
        db.session.add(RailExpense(line_id=line.id, panstwo_id=1, budget_id=1, amount=Decimal('250000000'))); db.session.commit()
        self.assertEqual(before - infrastructure_balance(db.session, budget)[1], Decimal('250000000'))


class Paga2RailTests(unittest.TestCase):
    def ctx(self, relation='Neutralne', war=False, available=5e9):
        return NS(country_id=2, traits={'fiscal_conservatism': 50},
                  situation={'relations': {1: {'relation_label': relation}}, 'at_war': [1] if war else []},
                  available=lambda sector: available)

    def screen(self):
        return {'available': True, 'lines': [{'id': 7, 'awaitingMe': True, 'initiatorId': 1, 'initiator': 'A', 'cityAName': 'a', 'cityBName': 'b',
                                             'shares': {'2': {'cost': '1000000000'}}, 'status': 'PENDING'}]}

    def test_cofinancing_decision(self):
        from game.paga2.rail import decision_options
        self.assertEqual(decision_options(self.ctx(), self.screen())[0].action, 'RAIL_ACCEPT')
        self.assertEqual(decision_options(self.ctx('Wrogie'), self.screen())[0].action, 'RAIL_REJECT')
        self.assertEqual(decision_options(self.ctx(war=True), self.screen())[0].action, 'RAIL_REJECT')
        self.assertEqual(decision_options(self.ctx(available=1e8), self.screen())[0].action, 'RAIL_REJECT')
        option = decision_options(self.ctx(), self.screen())[0]
        self.assertTrue(option.payload['required']); self.assertEqual(option.cost, 0)

    def test_decisions_without_own_technology_and_in_immediate_runs(self):
        from game.paga2.rail import propose
        ctx = self.ctx(); ctx.mode = 'IMMEDIATE'
        screen = {**self.screen(), 'available': False}
        ctx.screen = lambda name: {'data': screen}
        self.assertEqual([o.action for o in propose(ctx)], ['RAIL_ACCEPT'])

    def test_route_through_intermediate_city_is_split(self):
        from game.paga2.rail import staged_quote
        a = {'id': 1, 'name': 'A', 'own': True, 'population': 1, 'point': [0, 0]}
        b = {'id': 2, 'name': 'B', 'own': True, 'population': 1, 'point': [50, 5]}
        c = {'id': 3, 'name': 'C', 'own': True, 'population': 1, 'point': [100, 0]}
        screen = {'kmPerUnit': 1, 'cities': [a, b, c], 'lines': []}
        calls = []
        def call(path, json=None, **kw):
            calls.append((json['city_a'], json['city_b']))
            target = {1: a, 2: b, 3: c}[json['city_b']]
            return 200, {'path': [a['point'], target['point']], 'partnerId': None, 'cost': '1', 'distanceKm': '1'}
        ctx = self.ctx(); ctx.call = call
        quote, target = staged_quote(ctx, screen, a, c)
        self.assertEqual(target['id'], 2)                    # A→C przechodzi obok B (5 km) → najpierw A→B
        self.assertEqual(calls, [(1, 3), (1, 2)])

    def test_build_candidates_prefer_populous_unconnected_cities(self):
        from game.paga2.rail import candidates
        screen = {'kmPerUnit': 1, 'lines': [], 'cities': [
            {'id': 1, 'name': 'Duże', 'own': True, 'population': 5_000_000, 'point': [0, 0]},
            {'id': 2, 'name': 'Blisko', 'own': True, 'population': 100_000, 'point': [10, 0]},
            {'id': 3, 'name': 'Daleko', 'own': True, 'population': 2_000_000, 'point': [500, 0]},
            {'id': 4, 'name': 'Obce', 'own': False, 'population': 9_000_000, 'point': [5, 0]}]}
        best = candidates(self.ctx(), screen)[0]
        self.assertEqual((best[1]['id'], best[2]['id']), (1, 2))

    def test_main_network_pure(self):
        population = {1: 10, 2: 10, 3: 5, 4: 30, 5: 1}
        self.assertEqual(rail.main_network([(1, 2), (3, 4)], population), ({3, 4}, 35))
        self.assertEqual(rail.main_network([(1, 2), (3, 4), (2, 3)], population), ({1, 2, 3, 4}, 55))
        self.assertEqual(rail.main_network([(1, 99), (99, 5)], population), ({1, 5, 99}, 11))   # 99 — węzeł sąsiada
        self.assertEqual(rail.main_network([], population), (set(), 0))

    def test_build_candidates_join_main_network(self):
        from game.paga2.rail import candidates, network_gain
        cities = [{'id': 1, 'name': 'A', 'own': True, 'population': 5_000_000, 'point': [0, 0]},
                  {'id': 2, 'name': 'B', 'own': True, 'population': 4_000_000, 'point': [10, 0]},
                  {'id': 3, 'name': 'C', 'own': True, 'population': 1_000_000, 'point': [100, 0]},
                  {'id': 4, 'name': 'D', 'own': True, 'population': 1_000_000, 'point': [110, 0]}]
        screen = {'kmPerUnit': 1, 'cities': cities, 'lines': [{'cityA': 1, 'cityB': 2, 'status': 'ACTIVE'}]}
        self.assertEqual(network_gain(screen, 3, 4), 0)                  # oderwany odcinek C–D nic nie daje
        self.assertEqual(network_gain(screen, 2, 3), 1_000_000)
        for _, city, target, gain in candidates(self.ctx(), screen):
            self.assertIn(target['id'], {1, 2}); self.assertGreater(gain, 0)


class RailQuoteOnRealMapTests(unittest.TestCase):
    """Wycena na prawdziwej mapie i bazie UAT (tylko odczyt) — pomijana bez dostępu do bazy."""

    def test_quote_domestic_line(self):
        try:
            from zeus_app import app
        except Exception as error:
            self.skipTest(str(error))
        from sqlalchemy.orm import Session
        with app.app_context():
            try:
                with Session(db.engine) as session:
                    country = session.execute(text("SELECT panstwo_id FROM miasta WHERE czy_na_mapie='TAK' AND panstwo_id IS NOT NULL GROUP BY panstwo_id HAVING COUNT(*)>=5 ORDER BY panstwo_id LIMIT 1")).scalar()
                    cities = [c for c in rail.city_rows(session, [country]).values()]
                    with patch('game.rail.has_technology', return_value=True), patch('game.rail.require_technology'):
                        for a in cities:
                            for b in cities:
                                if a['id'] >= b['id']:
                                    continue
                                try:
                                    quote = rail.quote(session, country, {'city_a': a['id'], 'city_b': b['id']})
                                except Exception:
                                    continue
                                km = Decimal(quote['distanceKm'])
                                self.assertEqual(Decimal(quote['cost']), (km * rail.PRICE_PER_KM).quantize(Decimal('.01')))
                                self.assertEqual(quote['buildDays'], max(1, int(km // 50)))
                                self.assertIsNone(quote['partnerId'])
                                return
                    self.skipTest('Brak pary miast z trasą lądową.')
            except Exception as error:
                if 'Unknown database' in str(error) or 'no such table' in str(error) or "doesn't exist" in str(error):
                    self.skipTest(str(error))
                raise


if __name__ == '__main__':
    unittest.main()
