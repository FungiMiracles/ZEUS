"""23 Nov 2026: utrzymanie wojska od posiadanego wojska, bez względu na rozmieszczenie; niedobór → proporcjonalna demobilizacja;
w trakcie okresu nic nie jest naliczane ani wycofywane. 25 Nov 2026: rozliczane za poprzedni okres z sektora sił zbrojnych."""
from decimal import Decimal
from unittest.mock import patch
from sqlalchemy import text
from extensions import db
from models import Panstwo, Wojsko
from game.military_models import MilitaryBase, MilitaryMaintenance
from game.military_service import reconcile_maintenance
from game import military_upkeep
from test_game_military import MilitaryFixture, NOW


def shares():
    from game.finance_service import EXPENDITURE_CODES
    result = {code: 0 for code in EXPENDITURE_CODES}
    result[EXPENDITURE_CODES[0]] = 50
    result['reserve'] = 50
    return result


class CalculationTests(MilitaryFixture):
    def test_upkeep_is_taken_before_allocation_and_capped_by_funds(self):
        from game.finance_service import calculate_budget
        args = (Decimal('300000000000'), 10_000_000, Decimal('1000'), 10, 10, shares())
        base = calculate_budget(*args)
        self.assertIsNone(base['military_upkeep'])
        paid = calculate_budget(*args, military_upkeep=Decimal('1000000'))
        self.assertEqual(paid['military_upkeep'], Decimal('1000000.00'))
        self.assertEqual(paid['budget_total'], base['budget_total'] - Decimal('1000000'))
        self.assertEqual(sum(paid['allocations'].values()), paid['budget_total'])
        short = calculate_budget(*args, military_upkeep=base['budget_total'] + 500)
        self.assertEqual((short['military_upkeep'], short['budget_total']), (base['budget_total'], Decimal('0.00')))
        self.assertEqual(short['military_upkeep_due'], base['budget_total'] + 500)


class UpkeepFixture(MilitaryFixture):
    def setUp(self):
        super().setUp()
        db.session.execute(db.update(Panstwo).where(Panstwo.PANSTWO_ID == 1).values(panstwo_PKB=1_000_000_000_000, panstwo_populacja=1_000_000))
        db.session.commit()   # PKB per capita 1 mln → 10 000 ROI za żołnierza na okres
        for target in ('game.military_upkeep.game_now', 'game.finance_service.game_now'):
            try:
                p = patch(target, return_value=NOW); p.start(); self.addCleanup(p.stop)
            except AttributeError:
                pass

    def bases(self):
        db.session.expire_all()
        return {b.id: b for b in db.session.query(MilitaryBase).filter_by(panstwo_id=1)}

    def wojsko(self):
        db.session.expire_all()
        return db.session.query(Wojsko).filter_by(panstwo_id=1).one()


class AssessmentTests(UpkeepFixture):
    def test_everything_owned_is_charged_wherever_it_is(self):
        # 500 czołgów: 10 w bazie, reszta w rezerwie — płaci się za wszystkie
        db.session.add(MilitaryBase(panstwo_id=1, region_id=1, kind='land', level=7, garrison={'soldiers': 1000, 'tanks': 10, 'armored': 0}))
        db.session.commit()
        result = military_upkeep.assess(db.session, 1, 2990, 2)   # półrocze
        items = result['items']
        self.assertEqual(items['tanks']['count'], 500)
        self.assertEqual(items['tanks']['amount'], Decimal('4000000.00'))          # 500 × 8 000
        self.assertEqual(items['soldiers']['count'], 150000)                        # lądowe + powietrzne + morskie
        self.assertEqual(items['soldiers']['amount'], Decimal('1500000000.00'))    # × 10 000
        self.assertEqual(items['warships']['amount'], Decimal('1800000.00'))        # 3 × 600 000
        self.assertEqual(result['total'], sum(item['amount'] for item in items.values()))

    def test_quarter_halves_equipment_rates_and_abroad_doubles(self):
        db.session.add(MilitaryBase(panstwo_id=1, region_id=99, kind='land', level=7, garrison={'tanks': 100}))   # region obcy
        db.session.commit()
        with patch('game.finance_service.period_months', return_value=3):
            quarter = military_upkeep.assess(db.session, 1, 2990, 1)
        self.assertEqual(quarter['items']['tanks']['amount'], Decimal('2000000.00'))   # 500 × 4 000
        self.assertEqual(quarter['items']['abroad']['amount'], Decimal('400000.00'))   # 100 × 4 000 dopłaty
        self.assertEqual(quarter['items']['soldiers']['amount'], Decimal('1500000000.00'), 'stawka za żołnierza jest już „na okres”')


class DemobilizationTests(UpkeepFixture):
    def test_half_paid_cuts_everything_in_half_reserve_first(self):
        base = MilitaryBase(panstwo_id=1, region_id=1, kind='land', level=7, garrison={'soldiers': 50000, 'tanks': 400, 'armored': 0})
        db.session.add(base); db.session.commit()
        assessment = military_upkeep.assess(db.session, 1, 2990, 2)
        result = military_upkeep.demobilize(db.session, 1, assessment, Decimal('0.5'), NOW); db.session.commit()
        army = self.wojsko()
        self.assertEqual(result['tanks'], 250)
        self.assertEqual(army.czolgi_ilosc, 250)
        # 100 czołgów w rezerwie znika najpierw, potem 150 z garnizonu
        self.assertEqual(self.bases()[base.id].garrison['tanks'], 250)
        self.assertEqual(result['soldiers'], 75000)
        self.assertEqual(army.wojska_ladowe_ilosc + army.wojska_powietrzne_ilosc + army.wojska_morskie_ilosc, 75000)
        self.assertEqual(army.mysliwce_ilosc, 25)

    def test_collect_and_record_full_payment(self):
        # 25 Nov 2026: pełna zapłata włącza silosy, rozliczenie okresu jest wydatkiem sektora sił zbrojnych.
        from game.finance_models import StateBudget
        db.session.execute(text("UPDATE game_state_budgets SET period=2"))
        db.session.commit()
        budget = db.session.get(StateBudget, 1)
        silo = MilitaryBase(panstwo_id=1, region_id=1, kind='nuclear', level=1, garrison={}, operational=False)
        db.session.add(silo); db.session.commit()
        due = military_upkeep.assess(db.session, 1, 2990, 2)
        self.assertEqual(military_upkeep.collect(db.session, 1, due, due['total'], NOW), {})
        military_upkeep.record(db.session, 1, budget, due, due['total']); db.session.commit()
        record = db.session.query(MilitaryMaintenance).one()
        self.assertEqual((record.amount, record.soldier_count, record.soldier_fee), (due['total'], 150000, Decimal('1500000000.00')))
        self.assertIsNotNone(record.soldiers_assessed_at)
        self.assertTrue(self.bases()[silo.id].operational, 'opłacony silos wraca do pracy')

    def test_collect_shortfall_demobilizes_current_army(self):
        db.session.add(MilitaryBase(panstwo_id=1, region_id=1, kind='land', level=7, garrison={'soldiers': 50000, 'tanks': 400, 'armored': 0}))
        db.session.commit()
        due = military_upkeep.assess(db.session, 1, 2990, 2)
        result = military_upkeep.collect(db.session, 1, due, due['total'] / 2, NOW); db.session.commit()
        self.assertEqual((result['tanks'], self.wojsko().czolgi_ilosc), (250, 250))


class PreviousPeriodTests(UpkeepFixture):
    """25 Nov 2026: utrzymanie za poprzedni okres — wojsko posiadane w tym okresie (większa liczba: początek albo koniec)."""

    def budget(self, version, snapshot=None):
        from types import SimpleNamespace
        return SimpleNamespace(game_year=2990, period=1, calculation_version=version,
                               military_upkeep_details={'snapshot': snapshot} if snapshot is not None else None)

    def test_first_and_transition_budgets_owe_nothing(self):
        self.assertEqual(military_upkeep.due_for_previous(db.session, 1, None)['total'], 0)
        old = military_upkeep.due_for_previous(db.session, 1, self.budget(5))
        self.assertEqual((old['total'], old['prepaid']), (0, True))

    def test_units_lost_before_period_end_are_still_charged(self):
        now = military_upkeep.holdings(db.session, 1)
        snapshot = {**now, 'tanks': now['tanks'] + 100, 'soldiers': now['soldiers'] - 1000}
        due = military_upkeep.due_for_previous(db.session, 1, self.budget(6, snapshot))
        self.assertEqual(due['items']['tanks']['count'], now['tanks'] + 100, 'czołgi zniszczone w trakcie okresu')
        self.assertEqual(due['items']['soldiers']['count'], now['soldiers'], 'rekruci z końca okresu')
        self.assertEqual((due['prepaid'], due['period']), (False, [2990, 1]))
        self.assertEqual(due['total'], sum(item['amount'] for item in due['items'].values()))


class InPeriodTests(UpkeepFixture):
    def test_nothing_is_charged_or_withdrawn_during_an_upfront_period(self):
        base = MilitaryBase(panstwo_id=1, region_id=1, kind='land', level=7, garrison={'soldiers': 1000, 'tanks': 400})
        db.session.add(base)
        db.session.execute(text("UPDATE game_state_budgets SET military_upkeep=100"))
        db.session.execute(text("UPDATE game_state_budget_allocations SET amount=0"))   # zero w sektorze sił zbrojnych
        db.session.commit()
        reconcile_maintenance(db.session, 1, NOW); db.session.commit()
        self.assertEqual(self.bases()[base.id].garrison['tanks'], 400)
        self.assertIsNone(db.session.query(MilitaryMaintenance).one_or_none())
        self.assertTrue(military_upkeep.upfront(db.session, 1, NOW))

    def test_without_approved_budget_nothing_is_withdrawn(self):
        base = MilitaryBase(panstwo_id=1, region_id=1, kind='land', level=7, garrison={'soldiers': 1000, 'tanks': 400})
        db.session.add(base)
        db.session.execute(text('DELETE FROM game_state_budget_allocations')); db.session.execute(text('DELETE FROM game_state_budgets'))
        db.session.commit()
        reconcile_maintenance(db.session, 1, NOW); db.session.commit()
        self.assertEqual(self.bases()[base.id].garrison['tanks'], 400)

    def test_old_budgets_keep_the_in_period_rules(self):
        base = MilitaryBase(panstwo_id=1, region_id=1, kind='land', level=7, garrison={'soldiers': 0, 'tanks': 400})
        db.session.add(base); db.session.commit()
        self.set_budget(0)
        reconcile_maintenance(db.session, 1, NOW); db.session.commit()
        self.assertEqual(self.bases()[base.id].garrison['tanks'], 0, 'budżet sprzed zasady — wycofanie z braku środków jak dotąd')
