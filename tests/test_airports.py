"""Transport lotniczy (20 Nov 2026): technologia, zasady budowy lotnisk, połączenia i dochody, obrona/atak, handel lotniczy."""
import unittest
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace as NS
from unittest.mock import patch
from uuid import uuid4
from sqlalchemy import select, text
from extensions import db
from models import Miasto
from game import airports
from game.airport_models import Airport, AirportExpense, AirRouteSuspension
from game.finance_service import FinanceError
from test_game_military import MilitaryFixture, NOW
from test_game_commerce import CommerceFixture


class AirportRulesTests(unittest.TestCase):
    def test_technology(self):
        from game.industry_catalog import TECHNOLOGIES, PLANNED_TECHNOLOGIES
        from game.research_timing import DURATION_DAYS
        rule = TECHNOLOGIES['air_transport']
        self.assertEqual((rule['label'], rule['cost'], rule['parent'], rule['icon'], DURATION_DAYS['air_transport']),
                         ('Transport lotniczy', 400, 'rail_transport', 'airplane', 28))
        self.assertEqual(TECHNOLOGIES['national_hubs']['label'], 'Transport i komunikacja')
        self.assertNotIn('air_transport', PLANNED_TECHNOLOGIES)
        from game.research import technology_layout
        self.assertIn('air_transport', technology_layout()['positions'])

    def test_constants(self):
        self.assertEqual(airports.MATERIALS, {'kamien': 1400, 'zelazo': 200, 'chip_kerbit': 5, 'chip_natsyt': 3})
        self.assertEqual((airports.BUILD_DAYS, airports.MIN_POPULATION, airports.NAME_MAX), (14, 100_000, 60))
        self.assertEqual((airports.PRICE_PER_RESIDENT, airports.INCOME_PER_RESIDENT), (Decimal('100'), Decimal('10')))
        from game.trade_service import AIR_SPEED
        self.assertEqual(AIR_SPEED, 1000)

    def test_eligible_cities(self):
        city = lambda id, population: {'id': id, 'population': population}
        self.assertEqual(airports.eligible_ids([city(1, 150_000), city(2, 100_000), city(3, 5_000_000)]), {1, 3})
        # bez miast powyżej 100 000 — tylko największe miasto państwa
        self.assertEqual(airports.eligible_ids([city(1, 90_000), city(2, 40_000)]), {1})
        self.assertEqual(airports.eligible_ids([]), set())

    def test_default_name(self):
        self.assertEqual(airports.default_name('Saint Adams', 'SAD'), 'Port lotniczy Saint Adams – SAD')
        self.assertEqual(airports.default_name('Delin', None), 'Port lotniczy Delin')
        self.assertLessEqual(len(airports.default_name('X' * 80, 'ABC')), 60)

    def test_route_bonus_example(self):
        # miasto A 5 mln + miasto B 3 mln → (5 + 3) mln × 10 = 80 mln ROI na cykl
        self.assertEqual(airports.route_bonus(5_000_000, 3_000_000), Decimal('80000000.00'))

    def test_budget_includes_air_income(self):
        from game.finance_service import calculate_budget, EXPENDITURE_CODES
        shares = {code: 0 for code in EXPENDITURE_CODES}
        shares[EXPENDITURE_CODES[0]] = 50
        shares['reserve'] = 50
        base = calculate_budget(Decimal('300000000000'), 10_000_000, Decimal('100'), 10, 10, shares)
        air = calculate_budget(Decimal('300000000000'), 10_000_000, Decimal('100'), 10, 10, shares, air_income=Decimal('80000000'))
        self.assertEqual(base['air_income'], 0)
        self.assertEqual(air['air_income'], Decimal('80000000.00'))
        self.assertEqual(air['budget_total'] - base['budget_total'], Decimal('80000000.00'))
        self.assertEqual(air['budget_total'], air['opening_reserve'] + air['tax_total'] + air['rail_income'] + air['air_income'] - air['imf_collection'])

    def test_clean_name(self):
        self.assertEqual(airports._clean_name('  Lotnisko   Północ ', 'x'), 'Lotnisko Północ')
        self.assertEqual(airports._clean_name('', 'domyślna'), 'domyślna')
        with self.assertRaises(FinanceError):
            airports._clean_name('A' * 61, 'x')


POINTS = {11: [0, 0], 12: [10, 0], 13: [20, 0], 14: [30, 0], 21: [40, 0]}


class AirportDataTests(MilitaryFixture):
    def setUp(self):
        super().setUp()
        for model in (Airport, AirportExpense, AirRouteSuspension):
            model.__table__.create(db.engine, checkfirst=True)
        from game.commerce_models import ResourceStock
        ResourceStock.__table__.create(db.engine, checkfirst=True)
        db.session.add_all([Miasto(miasto_id=11, miasto_nazwa='A', miasto_kod='AAA', panstwo_id=1, region_id=1, miasto_populacja=5_000_000, czy_na_mapie='TAK'),
                            Miasto(miasto_id=12, miasto_nazwa='B', miasto_kod='BBB', panstwo_id=1, region_id=1, miasto_populacja=3_000_000, czy_na_mapie='TAK'),
                            Miasto(miasto_id=13, miasto_nazwa='C', miasto_kod='CCC', panstwo_id=1, region_id=1, miasto_populacja=50_000, czy_na_mapie='TAK'),
                            Miasto(miasto_id=21, miasto_nazwa='X', miasto_kod='XXX', panstwo_id=2, region_id=2, miasto_populacja=2_000_000, czy_na_mapie='TAK')])
        db.session.execute(text("INSERT INTO game_state_budget_allocations (id,budget_id,category_code,amount) VALUES (2,1,'infrastructure',1000000000000)"))
        db.session.commit()
        for target, value in [('game.airports.controlled_ids', lambda s, c: [c]), ('game.military_geography.city_point', POINTS.get)]:
            p = patch(target, side_effect=value); p.start(); self.addCleanup(p.stop)
        for target in ('game.airports.game_now', 'game.road_projects.game_now'):
            p = patch(target, return_value=NOW); p.start(); self.addCleanup(p.stop)
        p = patch('game.airports.has_technology', return_value=True); p.start(); self.addCleanup(p.stop)
        p = patch('game.nuclear.require_clear'); p.start(); self.addCleanup(p.stop)
        p = patch('game.land_war.require_buildable'); p.start(); self.addCleanup(p.stop)
        p = patch('game.airports._country_for_user', side_effect=lambda s, user, lock=False: NS(PANSTWO_ID=user)); p.start(); self.addCleanup(p.stop)
        p = patch('game.industry_service.settle_industry'); p.start(); self.addCleanup(p.stop)

    def materials(self, country=1, factor=1):
        from game.commerce_models import ResourceStock
        for code, need in airports.MATERIALS.items():
            row = db.session.get(ResourceStock, (country, code))
            if row is None:
                db.session.add(ResourceStock(panstwo_id=country, resource=code, quantity=need * factor))
            else:
                row.quantity = need * factor
        db.session.commit()

    def airport(self, city, country=1, ready=-1, health=100):
        row = Airport(panstwo_id=country, miasto_id=city, region_id=1 if country == 1 else 2, name=f'Port {city}', map_x=POINTS[city][0], map_y=POINTS[city][1],
                      cost=Decimal('1'), materials={}, health=health, starts_at=NOW - timedelta(days=20), ready_at=NOW + timedelta(days=ready), request_id=str(uuid4()))
        db.session.add(row); db.session.commit(); return row

    def test_quote_rules(self):
        quote = airports.quote(db.session, 1, {'city_id': 11})
        self.assertEqual((quote['cost'], quote['buildDays'], quote['defaultName']), ('500000000.00', 14, 'Port lotniczy A – AAA'))
        with self.assertRaises(FinanceError):
            airports.quote(db.session, 1, {'city_id': 13})                # 50 000 mieszkańców, a państwo ma większe miasta
        with self.assertRaises(FinanceError):
            airports.quote(db.session, 1, {'city_id': 21})                # miasto innego państwa
        self.airport(11)
        with self.assertRaises(FinanceError):
            airports.quote(db.session, 1, {'city_id': 11})                # miasto ma już lotnisko

    def test_build_consumes_materials_budget_and_takes_14_days(self):
        self.materials(factor=2)
        data = airports.build(1, {'city_id': 12, 'name': 'Lotnisko Bravo', 'request_id': str(uuid4())})
        db.session.expire_all()
        airport = db.session.get(Airport, data['id'])
        self.assertEqual((airport.name, airport.miasto_id, airport.cost), ('Lotnisko Bravo', 12, Decimal('300000000.00')))
        self.assertEqual(airport.ready_at - airport.starts_at, timedelta(days=14))
        self.assertFalse(data['completed'])
        from game.industry_service import available
        self.assertEqual({code: available(db.session, 1, code) for code in airports.MATERIALS}, airports.MATERIALS)
        expense = db.session.scalar(select(AirportExpense))
        self.assertEqual((expense.amount, expense.budget_id), (Decimal('300000000.00'), 1))
        from game.budget_transfers import infrastructure_balance
        from game.finance_models import StateBudget
        self.assertEqual(infrastructure_balance(db.session, db.session.get(StateBudget, 1))[1], Decimal('1000000000000') - Decimal('300000000'))

    def test_build_default_name_and_missing_materials(self):
        with self.assertRaises(FinanceError):
            airports.build(1, {'city_id': 11, 'request_id': str(uuid4())})
        self.materials()
        data = airports.build(1, {'city_id': 11, 'request_id': str(uuid4())})
        self.assertEqual(data['name'], 'Port lotniczy A – AAA')

    def test_connections_income_and_suspension(self):
        a, b, x = self.airport(11), self.airport(12), self.airport(21, country=2)
        self.airport(13, ready=+3)                                             # w budowie — bez połączeń
        self.assertEqual(len(airports.connections(db.session, NOW)), 3)          # A–B, A–X, B–X
        # państwo 1: A–B (5+3) + A–X (5+2) + B–X (3+2) = 20 mln × 10
        self.assertEqual(airports.income(db.session, 1, NOW), Decimal('200000000.00'))
        # państwo 2: tylko połączenia własnego lotniska X: (5+2) + (3+2) = 12 mln × 10
        self.assertEqual(airports.income(db.session, 2, NOW), Decimal('120000000.00'))
        db.session.add(AirRouteSuspension(airport_id=x.id, other_id=a.id)); db.session.commit()   # zawiesza druga strona
        self.assertEqual(airports.income(db.session, 1, NOW), Decimal('130000000.00'))
        routes = airports.airport_routes(db.session, a, NOW)
        x_route = next(r for r in routes if r['otherId'] == x.id)
        self.assertEqual((x_route['active'], x_route['suspendedByOther'], x_route['suspendedByMe']), (False, True, False))

    def test_set_suspension_is_reversible(self):
        a, b = self.airport(11), self.airport(12)
        airports.set_suspension(1, {'action': 'suspend', 'airport_id': a.id, 'other_id': b.id})
        self.assertEqual(airports.connections(db.session, NOW), [])
        airports.set_suspension(1, {'action': 'resume', 'airport_id': a.id, 'other_id': b.id})
        self.assertEqual(len(airports.connections(db.session, NOW)), 1)
        x = self.airport(21, country=2)
        with self.assertRaises(FinanceError):
            airports.set_suspension(1, {'action': 'suspend', 'airport_id': x.id, 'other_id': a.id})   # cudze lotnisko

    def test_rename_once_per_entenda_year(self):
        a = self.airport(11)
        data = airports.rename(1, {'airport_id': a.id, 'name': '  Lotnisko   Alfa '})
        self.assertEqual((data['name'], data['canRename']), ('Lotnisko Alfa', False))
        self.assertEqual(data['renameAvailableAt'], NOW.replace(year=NOW.year + 1).isoformat() + 'Z')
        with self.assertRaises(FinanceError):
            airports.rename(1, {'airport_id': a.id, 'name': 'Lotnisko Beta'})          # przed upływem roku
        with patch('game.airports.game_now', return_value=NOW.replace(year=NOW.year + 1)):
            self.assertEqual(airports.rename(1, {'airport_id': a.id, 'name': 'Lotnisko Beta'})['name'], 'Lotnisko Beta')
        for bad in ('', 'X' * 61):
            with self.assertRaises(FinanceError):
                airports.rename(1, {'airport_id': a.id, 'name': bad})
        x = self.airport(21, country=2)
        with self.assertRaises(FinanceError):
            airports.rename(1, {'airport_id': x.id, 'name': 'Cudze'})                  # lotnisko innego państwa

    def test_rename_leap_day(self):
        from datetime import datetime
        self.assertEqual(airports.rename_available_at(NS(renamed_at=datetime(3004, 2, 29, 12))), datetime(3005, 2, 28, 12))
        self.assertIsNone(airports.rename_available_at(NS(renamed_at=None)))

    def test_missile_defense_and_destruction(self):
        from game.missile_defense import owned_target, defense_data
        from game.military_models import MissileDefense
        a = self.airport(11)
        with patch('game.missile_defense.controlled_ids', side_effect=lambda s, c: [c]):
            self.assertEqual(owned_target(db.session, 1, 'airport', a.id).id, a.id)
        defense = MissileDefense(panstwo_id=1, region_id=1, target_kind='airport', target_id=a.id, level=7, ammunition=100)
        db.session.add(defense); db.session.commit()
        self.assertEqual(defense_data(defense)['position'], POINTS[11])
        from game.military_flights import apply_structural_damage
        flight = NS(target_kind='airport', target_airport_id=a.id, target_country_id=1, impact_at=NOW, panstwo_id=2, id=1)
        with patch('game.military_flights.controller_id', side_effect=lambda s, c: c), patch('game.military_flights.randbelow', return_value=11):
            damage = apply_structural_damage(db.session, flight, NS(payload={}), 10)      # 10 × 15 pkt ≥ 100
        db.session.commit(); db.session.expire_all()
        self.assertTrue(damage['airportDestroyed'])
        airport = db.session.get(Airport, a.id)
        self.assertEqual(airport.health, 0); self.assertIsNotNone(airport.removed_at)
        self.assertIsNone(db.session.get(MissileDefense, defense.id))
        self.assertEqual(airports.active_airports(db.session, NOW), [])
        self.materials()
        self.assertEqual(airports.quote(db.session, 1, {'city_id': 11})['cityId'], 11)   # w mieście można zbudować nowe lotnisko


class AirTradeTests(CommerceFixture):
    def setUp(self):
        super().setUp()
        for model in (Airport, AirportExpense, AirRouteSuspension):
            model.__table__.create(db.engine, checkfirst=True)
        for country, city in ((1, 101), (2, 102)):
            db.session.add(Airport(panstwo_id=country, miasto_id=city, region_id=country, name=f'Lotnisko {country}', map_x=(city - 101) * 100, map_y=0,
                                   cost=Decimal('1'), materials={}, health=100, starts_at=NOW - timedelta(days=20), ready_at=NOW - timedelta(days=1), request_id=str(uuid4())))
        db.session.commit()
        p = patch('game.airports.game_now', return_value=NOW); p.start(); self.addCleanup(p.stop)

    # 22 Nov 2026: transport wybiera kupujący — droga lotnicza między czynnymi lotniskami obu państw, 8% opłaty MFW.
    def test_air_delivery_option_and_purchase(self):
        from game.commerce_models import TradeShipment
        from game.trade_service import buy_offer
        from game.trade_routes import AIR_SPEED, ImfShippingFee
        offer_id = self.offer()
        shipment = db.session.get(TradeShipment, buy_offer(2, {'request_id': str(uuid4()), 'offer_id': offer_id, 'delivery': 'air:102'}))
        self.assertEqual((shipment.transport, shipment.departure_port_id, shipment.arrival_port_id, shipment.departure_fee, shipment.arrival_fee), ('air', 101, 102, 0, 0))
        self.assertEqual(shipment.arrives_at - shipment.starts_at, timedelta(seconds=shipment.distance_km / AIR_SPEED * 3600))
        fee = db.session.scalar(select(ImfShippingFee.amount).where(ImfShippingFee.shipment_id == shipment.id))
        self.assertEqual(fee, Decimal('80.00'), '8% of the price goes to the IMF account')
        from game.finance_models import StateFinancialAccount
        self.assertEqual(db.session.get(StateFinancialAccount, 2).reserve_balance, 10000 - 1000 - 80)
        from game.commerce import trade_state
        with self.app.test_request_context():
            data = trade_state(2)
        self.assertEqual(data['ownAirports'], ['102'])
        self.assertEqual(data['shipments'][0]['transport'], 'air')

    def test_air_delivery_requires_working_airports_and_open_connection(self):
        from game.commerce_models import TradeOffer
        from game.trade_routes import delivery_options
        from game.airport_models import AirRouteSuspension
        offer_id = self.offer()
        keys = lambda: {o['key'] for o in delivery_options(db.session, db.session.get(TradeOffer, offer_id), 2)}
        self.assertIn('air:102', keys())
        ids = [a.id for a in db.session.scalars(select(Airport).order_by(Airport.id))]
        db.session.add(AirRouteSuspension(airport_id=ids[0], other_id=ids[1])); db.session.commit()
        self.assertNotIn('air:102', keys(), 'suspended connection')
        db.session.query(AirRouteSuspension).delete(); db.session.execute(text('UPDATE game_airports SET health=0 WHERE panstwo_id=2')); db.session.commit()
        self.assertNotIn('air:102', keys(), 'buyer airport destroyed')


class Paga2AirportTests(unittest.TestCase):
    def ctx(self, available=5e9):
        return NS(traits={'fiscal_conservatism': 50}, available=lambda sector: available)

    def screen(self, **extra):
        data = {'available': True, 'airports': [], 'worldAirports': 2, 'incomePerResident': '10',
                'materials': [{'code': code, 'need': need, 'have': need} for code, need in airports.MATERIALS.items()],
                'cities': [{'id': 1, 'name': 'A', 'population': 8_000_000, 'eligible': True, 'hasAirport': False, 'cost': '800000000.00'},
                           {'id': 2, 'name': 'B', 'population': 9_000_000, 'eligible': True, 'hasAirport': True, 'cost': '900000000.00'}]}
        data.update(extra); return data

    def test_builds_in_largest_city_without_airport(self):
        from game.paga2.airports import build_options
        options = build_options(self.ctx(), self.screen())
        self.assertEqual(len(options), 1)
        self.assertEqual((options[0].action, options[0].payload['city_id'], options[0].payload['expected_cost']), ('AIRPORT_BUILD', 1, '800000000.00'))

    def test_no_build_without_materials_money_or_while_building(self):
        from game.paga2.airports import build_options
        self.assertEqual(build_options(self.ctx(), self.screen(materials=[{'code': 'kamien', 'need': 1400, 'have': 10}])), [])
        self.assertEqual(build_options(self.ctx(available=1e9), self.screen()), [])
        self.assertEqual(build_options(self.ctx(), self.screen(airports=[{'completed': False}])), [])
        self.assertEqual(build_options(self.ctx(), self.screen(available=False)), [])

    def test_buys_offer_and_lets_the_game_choose_delivery(self):
        # 22 Nov 2026: PAGA2 kupuje z drogą dostawy 'auto' — gra wybiera najtańszą dostępną (kolej, morze, powietrze).
        from game.paga2 import trade
        screen = {'ownAirports': ['7'], 'offers': [{'id': 5, 'sellerId': 3, 'seller': 'S', 'cargo': {'zelazo': 10}, 'price': '1000', 'usable': True}]}
        holdings = NS(stock={})
        ctx = NS(country_id=1, traits={'trade_propensity': 50}, situation={'level': 'peace'}, _sectors={})
        with patch('game.paga2.planner._holdings', return_value=holdings), patch('game.paga2.trade.pricing.consumption', return_value={'zelazo': 10}), \
             patch('game.paga2.trade.planned_acquisitions', return_value=set()), patch('game.paga2.trade.arrival_port', return_value=(None, None)), \
             patch('game.paga2.trade.unfriendly', return_value=set()), patch('game.paga2.trade.pricing.cargo_value', return_value=1e12):
            options = trade.buy_options(ctx, screen, {})
        self.assertEqual(options[0].payload['delivery'], 'auto')
        self.assertNotIn('port_id', options[0].payload)
        self.assertAlmostEqual(options[0].cost, 1120.0, msg='price with a margin for delivery fees (IMF up to 8%, ports, customs)')


if __name__ == '__main__':
    unittest.main()


from test_game_military_flights import FlightFixture


class AirportCombatTests(FlightFixture):
    """Lotnisko przeciwnika: atak bez rozpoznania wywiadu, przechwycenie przez obronę lotniska, zniszczenie przy życiu 0."""
    def setUp(self):
        super().setUp()
        for model in (Airport, AirportExpense, AirRouteSuspension):
            model.__table__.create(db.engine, checkfirst=True)
        db.session.add(Miasto(miasto_id=77, miasto_nazwa='Cel', panstwo_id=2, region_id=2, miasto_populacja=1_000_000, czy_na_mapie='TAK'))
        airport = Airport(panstwo_id=2, miasto_id=77, region_id=2, name='Port lotniczy Cel', map_x=100, map_y=0, cost=Decimal('1'), materials={},
                          health=100, starts_at=NOW - timedelta(days=20), ready_at=NOW - timedelta(days=1), request_id=str(uuid4()))
        db.session.add(airport); db.session.commit()
        self.airport_id = airport.id; self.source_base = self.source()

    def launch(self, count=1):
        from game.military_service import create_order
        return create_order(1, dict(kind='missile', target_airport_id=self.airport_id, source_base_id=self.source_base.id, missile_type='short', missiles=count))

    def test_attack_without_intelligence_and_destruction(self):
        from game.military_models import MilitaryFlight
        from game.military_flights import complete_flights
        flight = db.session.get(MilitaryFlight, self.launch())                   # bez misji wywiadu
        self.assertEqual((flight.target_kind, flight.target_airport_id, flight.target_name), ('airport', self.airport_id, 'Port lotniczy Cel'))
        with patch('game.military_flights.randbelow', return_value=11):           # 15 pkt życia na trafienie
            complete_flights(db.session, flight.impact_at); db.session.commit()
        self.assertEqual(db.session.get(Airport, self.airport_id).health, 85)
        with patch('game.military_flights.randbelow', return_value=11):
            flight = db.session.get(MilitaryFlight, self.launch(7))
            complete_flights(db.session, flight.impact_at); db.session.commit()
        airport = db.session.get(Airport, self.airport_id)
        self.assertEqual(airport.health, 0); self.assertIsNotNone(airport.removed_at)
        with self.assertRaises(FinanceError):
            self.launch()                                                          # zniszczone lotnisko nie jest celem

    def test_airport_defense_intercepts(self):
        from game.military_models import MilitaryFlight, MissileDefense
        from game.military_flights import complete_flights
        db.session.add(MissileDefense(panstwo_id=2, region_id=2, target_kind='airport', target_id=self.airport_id, level=7, ammunition=100)); db.session.commit()
        flight = db.session.get(MilitaryFlight, self.launch(3))
        with patch('game.missile_defense.randbelow', return_value=0):            # skuteczność 95% — każde przechwycenie udane
            complete_flights(db.session, flight.impact_at); db.session.commit()
        self.assertEqual(db.session.get(MilitaryFlight, flight.id).intercepted, 3)
        self.assertEqual(db.session.get(Airport, self.airport_id).health, 100)


class PowerDefenseTests(FlightFixture):
    """Naprawa (20 Nov 2026): obrona przeciwrakietowa elektrowni przechwytuje rakiety (wcześniej intercept() pomijał rodzaj 'power')."""
    def test_power_plant_defense_intercepts(self):
        from game.industry_models import PowerPlant
        from game.military_models import MilitaryFlight, MissileDefense
        from game.military_flights import complete_flights
        from game.intelligence_models import IntelligenceAgent, IntelligenceMission
        from game.military_service import create_order
        plant = PowerPlant(panstwo_id=2, region_id=2, kind='wind', level=1, health=3, map_x=100, map_y=0, investment=800000000, created_game_at=NOW, checked_at=NOW)
        db.session.add(plant); db.session.flush()
        agent = IntelligenceAgent(panstwo_id=1, level=1); db.session.add(agent); db.session.flush()
        db.session.add(IntelligenceMission(panstwo_id=1, agent_id=agent.id, region_id=2, target_country_id=2, region_name='Cel', kind='power', starts_at=NOW - timedelta(days=7),
                                           ends_at=NOW, completed_at=NOW, success=True, report={'power_ids': [plant.id]}))
        db.session.add(MissileDefense(panstwo_id=2, region_id=2, target_kind='power', target_id=plant.id, level=7, ammunition=100)); db.session.commit()
        base = self.source()
        flight = db.session.get(MilitaryFlight, create_order(1, dict(kind='missile', target_power_id=plant.id, source_base_id=base.id, missile_type='short', missiles=2)))
        with patch('game.missile_defense.randbelow', return_value=0):
            complete_flights(db.session, flight.impact_at); db.session.commit()
        self.assertEqual(db.session.get(MilitaryFlight, flight.id).intercepted, 2)
        self.assertEqual(db.session.get(PowerPlant, plant.id).health, 3)
        self.assertEqual(db.session.scalar(select(MissileDefense.ammunition).where(MissileDefense.target_kind == 'power')), 98)
