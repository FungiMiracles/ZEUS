"""25 Nov 2026: budżet pokrywa utrzymanie za poprzedni okres, bez sektora „Propaganda”, wymuszone zatwierdzenie przez
administratora i zakaz zmian zatwierdzonego budżetu (MySQL: wyzwalacz trg_gsb_no_update)."""
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch
from sqlalchemy import event, select, text, MetaData, Table, Column, Integer, String
from extensions import db
from test_game_military import MilitaryFixture, NOW
from game.finance_models import StateBudget
from game.finance_service import FinanceError, cover_dues, calculate_budget


class CoverDuesTests(MilitaryFixture):
    def test_sector_net_may_be_negative_and_reserve_covers_it(self):
        from game.finance_service import EXPENDITURE_CODES
        shares = {code: 0 for code in EXPENDITURE_CODES}
        shares.update({'armed_forces': 10, 'healthcare': 5})
        calc = calculate_budget(Decimal('300000000000'), 10_000_000, Decimal('0'), 10, 0, shares)
        dues = {code: Decimal(0) for code in EXPENDITURE_CODES}
        dues.update({'armed_forces': calc['allocations']['armed_forces'] + 1000, 'administration': Decimal(500)})
        result = cover_dues(calc, dues)
        self.assertEqual(result['sector_net']['armed_forces'], Decimal(-1000))
        self.assertEqual(result['sector_net']['administration'], Decimal(-500), 'udział 0% → kwota na minusie')
        self.assertEqual(result['sector_net']['healthcare'], calc['allocations']['healthcare'])
        self.assertEqual(result['dues_from_reserve'], Decimal(1500))
        self.assertEqual(result['reserve_after_dues'], calc['closing_reserve'] - 1500)

    def test_propaganda_is_not_a_budget_sector_anymore(self):
        from game.finance_service import CATEGORY_CODES, normalize_shares
        self.assertNotIn('propaganda', CATEGORY_CODES)
        with self.assertRaises(FinanceError):
            normalize_shares({'propaganda': 5})


class RetiredPropagandaTests(MilitaryFixture):
    def test_old_propaganda_allocation_counts_as_reserve_and_is_swept(self):
        from game.budget_categories import complete, normalize
        from game.finance_service import unspent_sectors, _previous_plan
        from game.finance_models import StateBudgetAllocation
        db.session.execute(text("DELETE FROM game_state_budget_allocations"))
        codes = ('administration', 'infrastructure', 'armed_forces', 'social_policy', 'environment', 'healthcare', 'education',
                 'research', 'security_services', 'propaganda', 'reserve')
        for i, code in enumerate(codes, start=1):
            db.session.execute(text('INSERT INTO game_state_budget_allocations (id,budget_id,category_code,share_percent,amount) VALUES (:i,1,:c,:s,:a)'),
                               {'i': i, 'c': code, 's': 10 if code == 'propaganda' else (90 if code == 'reserve' else 0), 'a': 300 if code == 'propaganda' else 0})
        db.session.commit()
        rows = list(db.session.scalars(select(StateBudgetAllocation).where(StateBudgetAllocation.budget_id == 1)))
        self.assertTrue(complete(rows))
        self.assertEqual(normalize((row.category_code, row.share_percent) for row in rows)['reserve'], 100)
        budget = db.session.get(StateBudget, 1)
        self.assertEqual(unspent_sectors(db.session, budget)['propaganda'], 300)


class ApprovalFixture(MilitaryFixture):
    """Pełne zatwierdzanie budżetu w SQLite (jak GeneralTaxTests.approval_scenario) — państwo 2, gracz 2."""

    def setUp(self):
        super().setUp()
        from models import Gospodarka, Spoleczenstwo
        from game.finance_models import BudgetCategory, StateFinancialPeriod, StateTaxAssessment, StateFinancialTransaction, StateBudgetAllocation
        from game.population_structure import PopulationStructure
        Gospodarka.__table__.create(db.engine, checkfirst=True)
        db.session.add_all([Gospodarka(panstwo_id=i, bezrobocie=3) for i in (1, 2)])
        db.session.commit()
        db.session.remove()
        for model in (StateBudgetAllocation, StateBudget):
            model.__table__.drop(db.engine)
        for model in (BudgetCategory, StateFinancialPeriod, StateBudget, StateBudgetAllocation, StateTaxAssessment, StateFinancialTransaction):
            metadata = MetaData()
            Table(model.__tablename__, metadata, *[Column(c.name, Integer() if c.primary_key and c.name == 'id' else String(c.type.length) if isinstance(c.type, String) else c.type,
                                                         primary_key=c.primary_key, nullable=True) for c in model.__table__.columns]).create(db.engine)
        from game.budget_categories import CODES
        db.session.add_all([BudgetCategory(code=code, name_pl=code, display_order=i + 1, is_reserve=code == 'reserve') for i, code in enumerate(CODES)])
        Spoleczenstwo.__table__.create(db.engine, checkfirst=True)
        db.session.execute(text('UPDATE panstwa SET panstwo_populacja=1000,panstwo_PKB=5000000,czy_suwerenny="TAK" WHERE PANSTWO_ID=2'))
        db.session.execute(text('UPDATE regiony SET region_stan_infra_drogowej=50,region_stan_infra_kolejowej=50,region_stan_infra_energetycznej=50,region_stan_infra_mieszkalnej=50,region_polozenie_id=1 WHERE region_id=2'))
        db.session.add(PopulationStructure(panstwo_id=2, children=20, working=60, seniors=20, version=1, actor='Test'))
        db.session.add(Spoleczenstwo(panstwo_id=2, zadowolenie_spoleczne=60, stabilnosc_spoleczna=70, poziom_edukacji=80, zdrowie_publiczne=75, przestepczosc=8, zaufanie_do_wladzy=61))
        db.session.commit()
        # MySQL: wyzwalacz trg_gsb_no_update — zatwierdzonego budżetu nie wolno zmieniać (błąd zatwierdzania z 25 Nov 2026).
        self.updates = []
        listener = lambda mapper, connection, target: self.updates.append(target.id)
        event.listen(StateBudget, 'before_update', listener)
        self.addCleanup(event.remove, StateBudget, 'before_update', listener)


class ForceApprovalTests(ApprovalFixture):
    def test_admin_forces_first_then_repeats_previous_plan(self):
        from game.finance_service import force_approve_budget, approve_manual_budget, preview_budget
        from game.finance_models import StateTaxAssessment
        from game.forum_models import GameNotification
        with patch('game.finance_service.game_now', return_value=NOW):
            first = force_approve_budget(2, 'Administrator')
            self.assertFalse(first['already_approved'])
            self.assertTrue(force_approve_budget(2, 'Administrator')['already_approved'])
        budget = db.session.get(StateBudget, first['budget_id'])
        self.assertEqual((budget.approval_mode, budget.approved_by_user_id), ('FIRST', 2))
        self.assertEqual(db.session.scalar(select(StateTaxAssessment.pit_rate).where(StateTaxAssessment.budget_id == budget.id)), 5)
        with patch('game.finance_service.game_now', return_value=datetime(2990, 7, 1)):
            quote = preview_budget(2, pit_rate=12, shares={'reserve': 100})
            approve_manual_budget(2, year=2990, period=2, expected_basis=quote['basis_token'], pit_rate=12, cit_rate=0, shares={'research': 10, 'reserve': 90})
        with patch('game.finance_service.game_now', return_value=datetime(2991, 1, 1)):
            third = force_approve_budget(2, 'Administrator')
        forced = db.session.get(StateBudget, third['budget_id'])
        self.assertEqual((forced.approval_mode, forced.approved_by_user_id, forced.period), ('MANUAL_REPEAT', 2, 1))
        self.assertEqual(db.session.scalar(select(StateTaxAssessment.pit_rate).where(StateTaxAssessment.budget_id == forced.id)), 12)
        from game.finance_models import StateBudgetAllocation
        research = db.session.scalar(select(StateBudgetAllocation.share_percent).where(StateBudgetAllocation.budget_id == forced.id, StateBudgetAllocation.category_code == 'research'))
        self.assertEqual(research, 10)
        texts = [row.system_text for row in db.session.scalars(select(GameNotification).where(GameNotification.user_id == 2))]
        self.assertTrue(any('Administrator zatwierdził budżet' in text and 'poprzednim okresie' in text for text in texts))
        self.assertEqual(self.updates, [])

    def test_country_without_player_is_refused(self):
        from game.finance_service import force_approve_budget
        with patch('game.finance_service.game_now', return_value=NOW):
            with self.assertRaises(FinanceError):
                force_approve_budget(4, 'Administrator')
