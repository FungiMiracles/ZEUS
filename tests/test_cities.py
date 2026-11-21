"""Obiekty miejskie — etap 1 (21 Nov 2026): katalog, efekty, budowa, likwidacja, utrzymanie przy zatwierdzeniu budżetu,
bonus edukacji do czasu badań, dodatek żłobków do przyrostu, wywiad surowcowy ważny 180 dni."""
import unittest
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace as NS
from unittest.mock import patch
from uuid import uuid4
from sqlalchemy import select, text
from extensions import db
from models import Miasto, Spoleczenstwo
from game import cities
from game.city_models import CityBuilding, CityExpense, CityEffectState
from game.finance_service import FinanceError
from test_game_military import MilitaryFixture, NOW


def fake(kind, city=1, ready=-1, removed=None, cell=0):
    return NS(kind=kind, miasto_id=city, ready_at=NOW + timedelta(days=ready), removed_at=removed, cell=cell)


class CityRulesTests(unittest.TestCase):
    def test_catalog_matches_specification(self):
        expected = {   # koszt, dni, utrzymanie, obsługiwani, sektor, ikona
            'clinic': (25_000_000, 14, 5_000_000, 25_000, 'healthcare', 'CLINIC.svg'),
            'hospital': (400_000_000, 30, 50_000_000, 1_250_000, 'healthcare', 'SZPITAL.svg'),
            'nursery': (15_000_000, 14, 3_000_000, None, 'social_policy', 'NURSERY.svg'),
            'school': (50_000_000, 28, 12_000_000, 50_000, 'education', 'SZKOŁA.svg'),
            'university': (500_000_000, 90, 70_000_000, 500_000, 'education', 'UNIWERSYTET.svg'),
            'tram': (250_000_000, 60, 30_000_000, 300_000, 'infrastructure', 'TRAMWAJ.svg'),
            'bus': (50_000_000, 21, 15_000_000, 150_000, 'infrastructure', 'AUTOBUS.svg'),
            'metro': (1_500_000_000, 120, 150_000_000, 1_000_000, 'infrastructure', 'METRO.svg'),
            'monument': (200_000_000, 60, 5_000_000, None, 'infrastructure', 'MONUMENT.svg'),
        }
        for kind, (cost, days, upkeep, served, sector, icon) in expected.items():
            rule = cities.rule(kind)
            self.assertEqual((rule['cost'], rule['days'], rule['maintenance'], rule['served'], rule['sector'], rule['icon']),
                             (Decimal(cost), days, Decimal(upkeep), served, sector, icon), kind)
        self.assertEqual((cities.GRID, cities.REFUND_SHARE), (8, Decimal('0.25')))
        with self.assertRaises(FinanceError):
            cities.rule('castle')

    def test_icons_exist(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1] / 'static' / 'icons'
        for kind in cities.CATALOG:
            self.assertTrue((root / cities.rule(kind)['icon']).exists(), kind)
        for name in ('MIASTO.svg', 'INFRASTRUKTURA REGIONÓW.svg', 'SAMOLOT.svg'):
            self.assertTrue((root / name).exists(), name)

    def test_coverage_effects(self):
        city_list = [{'id': 1, 'population': 3_000_000}, {'id': 2, 'population': 100_000}]
        buildings = [fake('hospital', 1), fake('hospital', 1), fake('hospital', 1),        # 3,75 mln obsłużonych → ludność 3 mln
                     fake('hospital', 2),                                                 # miasto 100 tys. — nie więcej niż ludność
                     fake('school', 1), *[fake('university', 1) for _ in range(3)],      # 50 tys. szkoła, 1,5 mln uczelnie
                     fake('metro', 1), fake('metro', 1), fake('bus', 2),                  # 2 mln + 100 tys. komunikacji
                     fake('monument', 1), fake('monument', 2), fake('nursery', 1),
                     fake('clinic', 1, ready=+5),                                         # w budowie — bez efektu
                     fake('clinic', 1, removed=NOW)]                                      # zlikwidowana — bez efektu
        result = cities.coverage(None, 1, NOW, cities=city_list, buildings=buildings)
        self.assertEqual(result['served'], {'health': 3_100_000, 'school': 50_000, 'university': 1_500_000, 'transport': 2_100_000, 'education': 1_550_000})
        self.assertEqual(result['targets'], {'zdrowie_publiczne': 3, 'poziom_edukacji': 1, 'zadowolenie_spoleczne': 1,
                                             'spojnosc_spoleczna': 2, 'tozsamosc_narodowa': 2})
        self.assertEqual(result['percent'], {'education': 50.0, 'health': 100.0, 'transport': 67.7})
        self.assertEqual(result['nurseryBonus'], Decimal('0.01'))
        many = cities.coverage(None, 1, NOW, cities=city_list, buildings=[fake('nursery') for _ in range(30)])
        self.assertEqual(many['nurseryBonus'], Decimal('0.20'))                                # najwyżej +0,20%

    def test_education_research_bonus(self):
        from game.research_timing import education_bonus, effective_days, start, timing, DURATION_DAYS
        self.assertEqual((education_bonus(60), education_bonus(80), education_bonus(50), education_bonus(None)), (12.0, 16.0, 0.0, 0.0))
        self.assertEqual(education_bonus(51), 10.2)
        self.assertEqual(effective_days('air_transport', 12), round(DURATION_DAYS['air_transport'] * .88, 2))
        timers = start({}, 'air_transport', NOW, 16)
        self.assertEqual(timing(timers, 'air_transport')['days'], round(28 * .84, 2))
        self.assertEqual(timing(start({}, 'air_transport', NOW), 'air_transport')['days'], 28)


class CityDataTests(MilitaryFixture):
    def setUp(self):
        super().setUp()
        for model in (CityBuilding, CityExpense, CityEffectState):
            model.__table__.create(db.engine, checkfirst=True)
        db.session.add_all([Miasto(miasto_id=11, miasto_nazwa='Stolica', miasto_kod='STO', panstwo_id=1, region_id=1, miasto_populacja=3_000_000, czy_na_mapie='TAK', miasto_typ_id=1),
                            Miasto(miasto_id=12, miasto_nazwa='Miasteczko', miasto_kod='MIA', panstwo_id=1, region_id=1, miasto_populacja=200_000, czy_na_mapie='TAK'),
                            Miasto(miasto_id=21, miasto_nazwa='Obce', miasto_kod='OBC', panstwo_id=2, region_id=2, miasto_populacja=2_000_000, czy_na_mapie='TAK'),
                            Spoleczenstwo(panstwo_id=1, zdrowie_publiczne=40, poziom_edukacji=55, zadowolenie_spoleczne=50, spojnosc_spoleczna=99, tozsamosc_narodowa=50)])
        db.session.execute(text("INSERT INTO game_state_budget_allocations (id,budget_id,category_code,amount) VALUES "
                                "(2,1,'healthcare',1000000000),(3,1,'education',100000000),(4,1,'infrastructure',5000000000),(5,1,'social_policy',0)"))
        db.session.execute(text("INSERT INTO game_state_financial_accounts (panstwo_id,reserve_balance) VALUES (1,300000000)"))
        db.session.commit()
        for target, value in [('game.cities.controlled_ids', lambda s, c: [c])]:
            p = patch(target, side_effect=value); p.start(); self.addCleanup(p.stop)
        p = patch('game.cities.game_now', return_value=NOW); p.start(); self.addCleanup(p.stop)
        p = patch('game.cities._country_for_user', side_effect=lambda s, user, lock=False: NS(PANSTWO_ID=user)); p.start(); self.addCleanup(p.stop)

    def build(self, kind, city=11, cell=0, **extra):
        return cities.build(1, {'kind': kind, 'city_id': city, 'cell': cell, 'request_id': str(uuid4()), **extra})

    def reserve(self):
        db.session.expire_all()
        return Decimal(db.session.execute(text('SELECT reserve_balance FROM game_state_financial_accounts WHERE panstwo_id=1')).scalar())

    def complete_all(self):
        db.session.execute(text('UPDATE game_city_buildings SET starts_at=:s, ready_at=:t'), {'s': NOW - timedelta(days=200), 't': NOW - timedelta(days=1)}); db.session.commit()

    def test_build_charges_sector_budget_and_takes_time(self):
        data = self.build('hospital', cell=5)
        self.assertEqual((data['kind'], data['cell'], data['completed']), ('hospital', 5, False))
        db.session.expire_all()
        building = db.session.get(CityBuilding, data['id'])
        self.assertEqual(building.ready_at - building.starts_at, timedelta(days=30))
        expense = db.session.scalar(select(CityExpense))
        self.assertEqual((expense.kind, expense.sector, expense.amount, expense.reserve_amount), ('build', 'healthcare', Decimal('400000000.00'), Decimal('0.00')))
        from game.budget_transfers import sector_balances, infrastructure_balance
        from game.finance_models import StateBudget
        budget = db.session.get(StateBudget, 1)
        self.assertEqual(sector_balances(db.session, budget)['healthcare']['remaining'], Decimal('600000000'))
        self.build('tram', cell=6)
        self.assertEqual(infrastructure_balance(db.session, budget)[1], Decimal('5000000000') - Decimal('250000000'))
        with self.assertRaises(FinanceError):
            self.build('clinic', cell=5)                     # kratka zajęta
        with self.assertRaises(FinanceError):
            self.build('clinic', city=21)                    # miasto innego państwa
        with self.assertRaises(FinanceError):
            self.build('clinic', cell=64)                    # poza planem 8×8

    def test_build_reserve_split_and_rejection(self):
        with self.assertRaises(FinanceError):
            self.build('university', cell=1)                 # 500 mln > 100 mln edukacji + 300 mln rezerwy
        self.build('school', cell=1)                         # 50 mln z edukacji
        data = cities.quote(db.session, 1, {'kind': 'school', 'city_id': 11, 'cell': 2})
        self.assertEqual((data['fromBudget'], data['fromReserve']), ('50000000.00', '0.00'))
        self.build('school', cell=2)                         # edukacja wyczerpana (100 mln)
        self.build('school', cell=3)                         # całość z rezerwy
        self.assertEqual(self.reserve(), Decimal('250000000.00'))
        expense = db.session.scalars(select(CityExpense).order_by(CityExpense.id.desc())).first()
        self.assertEqual((expense.amount, expense.reserve_amount), (Decimal('0.00'), Decimal('50000000.00')))

    def test_effects_follow_buildings_and_demolition_refunds(self):
        ids = [self.build('hospital', cell=i)['id'] for i in range(2)]   # 2,5 mln → ludność 3 mln: zdrowie +2
        self.build('monument', cell=9)
        cities.settle(db.session, 1, NOW); db.session.commit()
        society = db.session.scalar(select(Spoleczenstwo).where(Spoleczenstwo.panstwo_id == 1))
        self.assertEqual((society.zdrowie_publiczne, society.spojnosc_spoleczna), (40, 99))           # jeszcze w budowie
        self.complete_all()
        cities.settle(db.session, 1, NOW); db.session.commit(); db.session.expire_all()
        society = db.session.scalar(select(Spoleczenstwo).where(Spoleczenstwo.panstwo_id == 1))
        self.assertEqual((society.zdrowie_publiczne, society.spojnosc_spoleczna, society.tozsamosc_narodowa), (42, 100, 51))
        from game.forum_models import GameNotification
        texts = [n.system_text for n in db.session.scalars(select(GameNotification).where(GameNotification.user_id == 1))]
        self.assertEqual(sum(t.startswith('Miasta: zakończono budowę') for t in texts), 3)
        cities.settle(db.session, 1, NOW); db.session.commit()                                        # bez ponownych powiadomień
        self.assertEqual(db.session.query(GameNotification).filter(GameNotification.system_text.like('Miasta: zakończono%')).count(), 3)
        result = cities.demolish(1, {'building_id': ids[0]})
        self.assertEqual(result['refund'], '100000000.00')                                             # 25% z 400 mln
        db.session.expire_all()
        society = db.session.scalar(select(Spoleczenstwo).where(Spoleczenstwo.panstwo_id == 1))
        self.assertEqual(society.zdrowie_publiczne, 41)
        refund = db.session.scalar(select(CityExpense).where(CityExpense.kind == 'refund'))
        self.assertEqual((refund.sector, refund.amount), ('healthcare', Decimal('-100000000.00')))
        self.assertEqual(db.session.get(CityBuilding, ids[0]).removal_reason, 'demolished')
        # spójność była 99: +1 do 100 (granica) — po likwidacji monumentu wraca do 99, nie do 98
        monument = db.session.scalar(select(CityBuilding).where(CityBuilding.kind == 'monument'))
        cities.demolish(1, {'building_id': monument.id}); db.session.expire_all()
        society = db.session.scalar(select(Spoleczenstwo).where(Spoleczenstwo.panstwo_id == 1))
        self.assertEqual((society.spojnosc_spoleczna, society.tozsamosc_narodowa), (99, 50))

    def test_maintenance_on_budget_approval(self):
        from game.finance_models import StateBudget, StateFinancialAccount
        self.build('school', cell=1)                                                   # edukacja 12 mln / rok
        for cell in range(3):
            self.build('clinic', city=12, cell=cell)                                    # 3 × 5 mln / rok, ochrona zdrowia
        self.build('hospital', cell=4)                                                  # 50 mln / rok
        self.complete_all()
        # nowy okres: edukacja 1 mln, ochrona zdrowia 10 mln, rezerwa 2 mln
        db.session.execute(text("INSERT INTO game_state_budgets (id,panstwo_id,game_year,period) VALUES (2,1,2990,2)"))
        db.session.execute(text("INSERT INTO game_state_budget_allocations (id,budget_id,category_code,amount) VALUES "
                                "(12,2,'healthcare',10000000),(13,2,'education',1000000),(14,2,'infrastructure',0),(15,2,'social_policy',0)"))
        db.session.execute(text('UPDATE game_state_financial_accounts SET reserve_balance=2000000'))
        db.session.commit()
        with patch('game.cities.period_months', return_value=6):                       # półrocze — połowa rocznych kosztów
            budget = db.session.get(StateBudget, 2)
            account = db.session.scalar(select(StateFinancialAccount).where(StateFinancialAccount.panstwo_id == 1))
            cities.charge_maintenance(db.session, 1, budget, account, NOW)
            db.session.commit()
        db.session.expire_all()
        rows = {r.sector: r for r in db.session.scalars(select(CityExpense).where(CityExpense.budget_id == 2))}
        # edukacja: 6 mln za półrocze, 1 mln z sektora, 5 mln brakuje, rezerwa 2 mln → szkoła zlikwidowana
        self.assertNotIn('education', rows)
        school = db.session.scalar(select(CityBuilding).where(CityBuilding.kind == 'school'))
        self.assertEqual(school.removal_reason, 'unfunded')
        # zdrowie: (3×5 + 50) / 2 = 32,5 mln; 10 mln z sektora + 2 mln rezerwy → likwidacja od najtańszych:
        # kliniki (3 × 2,5 mln) nie wystarczą, szpital (25 mln) też musi zniknąć → zostaje 0 kosztów
        removed = {b.kind for b in db.session.scalars(select(CityBuilding).where(CityBuilding.removal_reason == 'unfunded'))}
        self.assertEqual(removed, {'school', 'clinic', 'hospital'})
        self.assertEqual(self.reserve(), Decimal('2000000.00'))
        from game.forum_models import GameNotification
        self.assertEqual(db.session.query(GameNotification).filter(GameNotification.system_text.like('Miasta: obiekt%zlikwidowany z braku środków%')).count(), 5)

    def test_maintenance_uses_reserve_before_removal(self):
        from game.finance_models import StateBudget, StateFinancialAccount
        self.build('hospital', cell=4)                                                  # 50 mln / rok → 25 mln za półrocze
        self.complete_all()
        db.session.execute(text("INSERT INTO game_state_budgets (id,panstwo_id,game_year,period) VALUES (2,1,2990,2)"))
        db.session.execute(text("INSERT INTO game_state_budget_allocations (id,budget_id,category_code,amount) VALUES (12,2,'healthcare',20000000)"))
        db.session.commit()
        with patch('game.cities.period_months', return_value=6):
            budget = db.session.get(StateBudget, 2)
            account = db.session.scalar(select(StateFinancialAccount).where(StateFinancialAccount.panstwo_id == 1))
            cities.charge_maintenance(db.session, 1, budget, account, NOW)
            cities.charge_maintenance(db.session, 1, budget, account, NOW)            # idempotentne
            db.session.commit()
        rows = list(db.session.scalars(select(CityExpense).where(CityExpense.budget_id == 2)))
        self.assertEqual([(r.sector, r.amount, r.reserve_amount) for r in rows], [('healthcare', Decimal('20000000.00'), Decimal('5000000.00'))])
        self.assertEqual(self.reserve(), Decimal('295000000.00'))
        self.assertIsNone(db.session.scalar(select(CityBuilding.removed_at)))
        from game.budget_transfers import sector_balances
        balances = sector_balances(db.session, db.session.get(StateBudget, 2))
        self.assertEqual((balances['healthcare']['spent'], balances['reserve']['spent']), (Decimal('20000000.00'), Decimal('5000000.00')))

    def test_state_and_upkeep_summary(self):
        with patch('game.military_geography.city_point', side_effect={11: [0, 0], 12: [5, 5]}.get):
            self.build('bus', cell=3); self.complete_all()
            data = cities.state(db.session, 1, NOW)
        self.assertEqual([c['id'] for c in data['cities']], [11, 12])
        self.assertTrue(data['cities'][0]['capital'])
        self.assertEqual(data['cities'][0]['buildings'][0]['kind'], 'bus')
        self.assertEqual(data['coverage']['percent']['transport'], round(150_000 / 3_200_000 * 100, 1))
        self.assertEqual(data['researchBonus'], 11.0)                                       # poziom edukacji 55
        upkeep = {item['code']: item for item in cities.upkeep_summary(db.session, 1, NOW)['items']}
        self.assertEqual(upkeep['transport']['annual'], '15000000.00')
        self.assertEqual(len(cities.admin_cities(db.session, 1)), 1)


class CityPreviewTests(CityDataTests):
    def test_preview_own_and_foreign_city(self):
        self.build('clinic', cell=7)
        own = cities.preview(db.session, 1, 11, NOW)
        self.assertEqual((own['own'], own['capital'], [b['cell'] for b in own['buildings']]), (True, True, [7]))
        foreign = cities.preview(db.session, 2, 11, NOW)                       # to samo miasto oglądane przez inne państwo
        self.assertEqual((foreign['own'], len(foreign['buildings'])), (False, 1))
        self.assertNotIn('funds', foreign)                                       # bez budżetów
        self.assertIsNone(cities.preview(db.session, 1, 999, NOW))

    # testy klasy bazowej nie są tu powtarzane
    for _name in [n for n in dir(CityDataTests) if n.startswith('test_')]:
        locals()[_name] = None


class ResourceIntelligenceExpiryTests(MilitaryFixture):
    def test_reports_valid_for_180_days(self):
        from game.intelligence_models import IntelligenceMission
        from game.foreign_mining import reports, REPORT_DAYS
        self.assertEqual(REPORT_DAYS, 180)
        for id, days in ((1, 10), (2, 200)):
            db.session.add(IntelligenceMission(id=id, panstwo_id=1, agent_id=1, region_id=2, target_country_id=2, region_name='R', kind='resources',
                                               starts_at=NOW - timedelta(days=days + 5), ends_at=NOW - timedelta(days=days), completed_at=NOW,
                                               success=True, report={'entries': [{'label': 'Złoto', 'value': '1'}]}))
        db.session.commit()
        self.assertEqual(reports(db.session, 1, NOW)[2].id, 1)
        db.session.execute(text('DELETE FROM game_intelligence_missions WHERE id=1')); db.session.commit()
        self.assertEqual(reports(db.session, 1, NOW), {})                                # raport sprzed 200 dni wygasł


class Paga2CityAdapterTests(unittest.TestCase):
    def ctx(self, funds, prosociality=50):
        return NS(available=lambda sector: funds.get(sector, 0.0), sector_start=lambda sector: funds.get(sector, 0.0),
                  traits={'prosociality': prosociality, 'ambition': 50})

    def screen(self, buildings=()):
        return {'available': True, 'hasBudget': True, 'grid': 8, 'catalog': cities.catalog_data(),
                'cities': [{'id': 11, 'name': 'Stolica', 'population': 3_000_000, 'capital': True, 'buildings': list(buildings)},
                           {'id': 12, 'name': 'Miasteczko', 'population': 60_000, 'capital': False, 'buildings': []}]}

    def test_options_follow_budget_and_unserved_population(self):
        from game.paga2.cities import build_options
        options = build_options(self.ctx({'healthcare': 2e9, 'education': 0, 'infrastructure': 4e9, 'social_policy': 1e9}), self.screen())
        kinds = {o.payload['kind']: o for o in options}
        self.assertIn('hospital', kinds); self.assertIn('metro', kinds); self.assertIn('nursery', kinds)
        self.assertNotIn('school', kinds)                                   # brak środków edukacji
        self.assertEqual((kinds['hospital'].payload['city_id'], kinds['hospital'].payload['cell'], kinds['hospital'].payload['group']), (11, 0, 'city:build'))
        self.assertEqual(kinds['hospital'].sector, 'healthcare')
        self.assertGreater(kinds['hospital'].effects['welfare'], 0); self.assertGreater(kinds['metro'].effects['infrastructure'], 0)
        busy = [{'kind': 'clinic', 'cell': 0, 'completed': False, 'sector': 'healthcare', 'maintenance': '5000000'},
                {'kind': 'clinic', 'cell': 1, 'completed': False, 'sector': 'healthcare', 'maintenance': '5000000'}]
        self.assertEqual(build_options(self.ctx({'healthcare': 2e9}), self.screen(busy)), [])   # dwie budowy w toku

    def test_upkeep_limit(self):
        from game.paga2.cities import build_options
        # 1 mld środków infrastruktury: metro kosztuje 1,5 mld (> 50%), tramwaj 250 mln — dozwolony
        kinds = {o.payload['kind'] for o in build_options(self.ctx({'infrastructure': 1e9}), self.screen())}
        self.assertIn('tram', kinds); self.assertNotIn('metro', kinds)
        # 100 mln: utrzymanie tramwaju (30 mln / 4 = 7,5 mln) mieści się w 35 mln, ale koszt 250 mln > 50 mln
        self.assertNotIn('tram', {o.payload['kind'] for o in build_options(self.ctx({'infrastructure': 1e8}), self.screen())})


if __name__ == '__main__':
    unittest.main()
