"""Międzynarodowy Fundusz Walutowy (18 Nov 2026): zdolność kredytowa, pula, spłaty, ściąganie długu i PAGA2."""
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import patch
from sqlalchemy import select, text
from extensions import db
from game.finance_models import StateBudget, StateFinancialAccount
from game.finance_service import FinanceError, _reserve_for_account, calculate_budget
from game.imf_models import ImfFundYear, ImfLoan, ImfMovement
from game.imf import request_loan, repay, imf_state, imf_bp, collection_amount, due_amount, ANNUAL_POOL, due_key
from game.loan_models import StateLoan
from test_game_military import MilitaryFixture, NOW


def create_imf_tables():
    for model in (ImfFundYear, ImfLoan, ImfMovement):
        model.__table__.create(db.engine, checkfirst=True)


class ImfFixture(MilitaryFixture):
    def setUp(self):
        super().setUp()
        self.app.register_blueprint(imf_bp)
        create_imf_tables()
        clock = patch('game.imf.game_now', return_value=NOW); clock.start(); self.addCleanup(clock.stop)
        db.session.execute(text('UPDATE game_state_budgets SET budget_total=1000, tax_total=2000, closing_reserve=100 WHERE id=1'))   # zdolność: 25% z 2000 = 500
        db.session.add(StateFinancialAccount(panstwo_id=1, reserve_balance=100, last_budget_id=1, last_transaction_sequence=0, created_at=NOW, updated_at=NOW))
        db.session.commit()

    def ask(self, amount, key=None):
        return request_loan(1, {'amount': amount, 'request_id': key or str(uuid4())})

    def reserve(self):
        db.session.expire_all()
        return db.session.get(StateFinancialAccount, 1).reserve_balance


class ImfRequestTests(ImfFixture):
    def test_loan_within_capacity_goes_to_reserve_once_and_keeps_reserve_invariant(self):
        key = str(uuid4())
        decision = self.ask('300', key)
        self.assertEqual(decision['status'], 'active')
        self.assertEqual(self.ask('300', key)['id'], decision['id'])          # idempotentny wniosek
        self.assertEqual(self.reserve(), 400)
        loan = db.session.get(ImfLoan, decision['id'])
        self.assertEqual((loan.outstanding, loan.start_year, loan.start_period, loan.due_year, loan.due_period), (300, 2990, 1, 2992, 1))
        self.assertEqual(db.session.get(ImfFundYear, 2990).lent, 300)
        self.assertEqual(db.session.query(ImfMovement).count(), 1)
        budget = db.session.get(StateBudget, 1)
        self.assertEqual(_reserve_for_account(db.session.get(StateFinancialAccount, 1), budget), 400)
        # Rezerwa widoczna w budżecie (sektor „reserve”) też obejmuje wypłatę MFW (zgłoszenie 18 Nov 2026: Ozilandia).
        from game.budget_transfers import sector_balances
        db.session.execute(text("INSERT INTO game_state_budget_allocations (id,budget_id,category_code,amount) VALUES (99,1,'reserve',100)")); db.session.commit()
        self.assertEqual(sector_balances(db.session, budget)['reserve']['remaining'], 400)
        repay(1, {'amount': '150', 'request_id': str(uuid4())})
        self.assertEqual(sector_balances(db.session, db.session.get(StateBudget, 1))['reserve']['remaining'], 250)
        self.assertEqual(self.reserve(), 250)

    def test_capacity_is_quarter_of_tax_tranche_minus_imf_and_state_debt(self):
        rejected = self.ask('501')                                            # 25% z 2000 = 500
        self.assertEqual(rejected['status'], 'rejected')
        self.assertIn('25% transzy podatkowej', rejected['reason'])
        db.session.add(StateLoan(borrower_id=1, lender_id=2, requested_by=2, amount=60, status='accepted', request_id=str(uuid4())))
        db.session.commit()
        self.assertEqual(self.ask('441')['status'], 'rejected')               # 500 − 60 = 440
        self.assertEqual(self.ask('440')['status'], 'active')
        self.assertEqual(self.reserve(), 540)

    def test_only_one_active_loan(self):
        self.assertEqual(self.ask('100')['status'], 'active')
        second = self.ask('10')
        self.assertEqual(second['status'], 'rejected')
        self.assertIn('niespłaconą pożyczkę', second['reason'])
        repay(1, {'amount': 'all', 'request_id': str(uuid4())})
        self.assertEqual(self.ask('10')['status'], 'active')                  # po spłacie — znów można

    def test_country_limit_is_ten_percent_of_annual_pool(self):
        db.session.add(ImfFundYear(game_year=2990, pool=Decimal('3000'), lent=0)); db.session.commit()   # limit państwa: 300
        self.assertEqual(self.ask('301')['status'], 'rejected')
        self.assertEqual(self.ask('200')['status'], 'active')
        repay(1, {'amount': 'all', 'request_id': str(uuid4())})
        limited = self.ask('101')                                             # w roku zostało 100
        self.assertIn('roczny limit', limited['reason'])
        self.assertEqual(self.ask('100')['status'], 'active')

    def test_annual_pool_limits_lending_and_repayments_do_not_refill_it(self):
        db.session.add(ImfFundYear(game_year=2990, pool=ANNUAL_POOL, lent=ANNUAL_POOL - 50)); db.session.commit()
        self.assertEqual(self.ask('60')['status'], 'rejected')
        self.assertEqual(self.ask('50')['status'], 'active')
        repay(1, {'amount': 'all', 'request_id': str(uuid4())})
        self.assertEqual(self.ask('1')['status'], 'rejected')

    def test_new_rules_constants(self):
        from game.imf import INTEREST_RATE, CAPACITY_SHARE, COUNTRY_SHARE
        self.assertEqual((ANNUAL_POOL, INTEREST_RATE, CAPACITY_SHARE, COUNTRY_SHARE), (Decimal('1000000000000.00'), Decimal('0.05'), Decimal('0.25'), Decimal('0.10')))

    def test_no_budget_means_no_assessment(self):
        db.session.get(StateFinancialAccount, 1).last_budget_id = None; db.session.commit()
        decision = self.ask('10')
        self.assertEqual(decision['status'], 'rejected')
        self.assertIn('budżetu', decision['reason'])

    def test_invalid_amounts(self):
        for value in ('0', '-5', '1.234', 'abc'):
            with self.assertRaises(FinanceError):
                self.ask(value)


class ImfRepaymentTests(ImfFixture):
    def test_partial_and_full_repayment_from_reserve(self):
        loan = self.ask('300')['id']
        self.assertEqual(self.reserve(), 400)
        key = str(uuid4())
        self.assertEqual(repay(1, {'amount': '250', 'request_id': key})['remaining'], '50.00')
        self.assertTrue(repay(1, {'amount': '250', 'request_id': key})['already'])   # idempotentna spłata
        db.session.expire_all()
        self.assertEqual(db.session.get(ImfLoan, loan).outstanding, 50)
        self.assertEqual(self.reserve(), 150)
        repay(1, {'amount': 'all', 'request_id': str(uuid4())})
        self.assertEqual(self.reserve(), 100)
        db.session.expire_all()
        self.assertEqual(db.session.get(ImfLoan, loan).status, 'repaid')
        self.assertEqual(_reserve_for_account(db.session.get(StateFinancialAccount, 1), db.session.get(StateBudget, 1)), 100)
        with self.assertRaises(FinanceError):
            repay(1, {'amount': '1', 'request_id': str(uuid4())})

    def test_repayment_cannot_exceed_debt_or_reserve(self):
        self.ask('300')
        with self.assertRaises(FinanceError):
            repay(1, {'amount': '301', 'request_id': str(uuid4())})
        db.session.get(StateFinancialAccount, 1).reserve_balance = 10; db.session.commit()
        with self.assertRaises(FinanceError):
            repay(1, {'amount': 'all', 'request_id': str(uuid4())})
        self.assertEqual(self.reserve(), 10)


class ImfCollectionRuleTests(ImfFixture):
    def test_collection_is_capped_at_65_percent_and_reduces_budget_before_allocation(self):
        self.assertEqual(collection_amount(Decimal('500'), Decimal('1000')), Decimal('500'))
        self.assertEqual(collection_amount(Decimal('900'), Decimal('1000')), Decimal('650'))
        self.assertEqual(collection_amount(Decimal('0'), Decimal('1000')), Decimal('0'))
        result = calculate_budget(5000000, 1000, '100', 10, 0, {'reserve': 100, 'infrastructure': 0}, share=Decimal('0.5'), imf_due=Decimal('1000000'))
        self.assertEqual(result['imf_collection'], (Decimal(100) + result['tax_total']) * Decimal('0.65') // Decimal('0.01') * Decimal('0.01'))
        self.assertEqual(result['budget_total'], Decimal(100) + result['tax_total'] - result['imf_collection'])
        self.assertEqual(sum(result['allocations'].values()), result['budget_total'])

    def test_due_after_four_budget_cycles(self):
        self.assertEqual(due_key((3001, 1)), (3002, 2))      # I półr. → II półr. → IV kw. 3001 → I kw. → II kw. 3002
        self.assertEqual(due_key((3001, 4)), (3002, 4))
        loan_id = self.ask('300')['id']
        self.assertEqual(due_amount(db.session, 1, (2991, 2)), 0)
        self.assertEqual(due_amount(db.session, 1, (2992, 1)), Decimal('364.65'))   # z odsetkami: 300·1,05⁴
        self.assertEqual(db.session.get(ImfLoan, loan_id).due_period, 1)


class ImfInterestTests(ImfFixture):
    def test_interest_five_percent_per_cycle_compounded_and_only_for_new_loans(self):
        from game.imf import accrue_interest, projected
        loan_id = self.ask('300')['id']
        loan = db.session.get(ImfLoan, loan_id)
        self.assertEqual((loan.interest_rate, loan.interest_year, loan.interest_period), (Decimal('0.0500'), 2990, 1))
        self.assertEqual(projected(loan, (2990, 1))[0], 300)                          # okres wypłaty: bez odsetek
        self.assertEqual(projected(loan, (2991, 1)), (Decimal('330.75'), Decimal('30.75')))   # 2 cykle: 300·1,05²
        from sqlalchemy.orm import Session as OrmSession
        with OrmSession(db.engine) as session, session.begin():
            self.assertEqual(accrue_interest(session, 1, (2990, 2)), Decimal('15.00'))
            self.assertEqual(accrue_interest(session, 1, (2990, 2)), 0)                       # idempotentne w okresie
        db.session.expire_all()
        loan = db.session.get(ImfLoan, loan_id)
        self.assertEqual((loan.outstanding, loan.interest, loan.interest_period), (Decimal('315.00'), Decimal('15.00'), 2))
        self.assertEqual(due_amount(db.session, 1, (2992, 1)), Decimal('364.65'))              # termin: 315·1,05³ = 364,65
        repay(1, {'amount': 'all', 'request_id': str(uuid4())})                                # spłata z odsetkami
        self.assertEqual(self.reserve(), Decimal('85.00'))
        # pożyczka sprzed zmiany (stopa 0) — bez odsetek
        old = ImfLoan(borrower_id=2, requested_by=2, amount=100, outstanding=100, status='active', pool_year=2990, start_year=2990, start_period=1,
                      due_year=2992, due_period=1, capacity=0, request_id=str(uuid4()), created_game_at=NOW)
        db.session.add(old); db.session.commit()
        self.assertEqual(projected(old, (2992, 1)), (100, 0))


class ImfScreenTests(ImfFixture):
    def test_state_shows_pool_borrowers_with_flags_and_own_loans(self):
        self.ask('300'); self.ask('9999')
        with self.app.test_request_context():
            state = imf_state(db.session, 1)
        self.assertEqual((state['pool'], state['lent'], state['remaining']), (str(ANNUAL_POOL), '300.00', str(ANNUAL_POOL - 300)))
        self.assertEqual(state['borrowers'][0]['countryId'], 1)
        self.assertTrue(state['borrowers'][0]['flag'].endswith('.jpg'))
        self.assertEqual([loan['status'] for loan in state['loans']], ['rejected', 'active'])
        self.assertEqual(state['credit']['capacity'], '200.00')

    def test_http_page_state_and_csrf(self):
        self.login(1)
        self.assertEqual(self.client.get('/game/mfw/stan').status_code, 200)
        response = self.client.post('/game/mfw/zmien', json={'action': 'request', 'amount': '10', 'request_id': str(uuid4())})
        self.assertEqual(response.status_code, 403)
        response = self.client.post('/game/mfw/zmien', headers={'X-CSRF-Token': 'token'}, json={'action': 'request', 'amount': '10', 'request_id': str(uuid4())})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['status'], 'active')
        response = self.client.post('/game/mfw/zmien', headers={'X-CSRF-Token': 'token'}, json={'action': 'repay', 'amount': 'all', 'request_id': str(uuid4())})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.reserve(), 100)


class ImfApprovalTests(MilitaryFixture):
    """Pełne zatwierdzenie budżetu: zaległość w MFW pobierana przed podziałem (najwyżej 65%), reszta później."""

    def setUp(self):
        super().setUp()
        from models import Gospodarka   # jak GeneralTaxTests: bezrobocie do podstawy podatku ogólnego
        Gospodarka.__table__.create(db.engine, checkfirst=True)
        db.session.add_all([Gospodarka(panstwo_id=i, bezrobocie=3) for i in (1, 2)])
        db.session.commit()

    def test_overdue_debt_is_collected_at_budget_approval(self):
        create_imf_tables()
        # Państwo 2 przed pierwszym budżetem: pożyczka 10 mln (wypłacona do rezerwy), termin minął.
        loan = ImfLoan(borrower_id=2, requested_by=2, amount=Decimal('10000000'), outstanding=Decimal('10000000'), status='active', pool_year=2988,
                       start_year=2988, start_period=1, due_year=2990, due_period=1, capacity=0, request_id=str(uuid4()), created_game_at=NOW)
        db.session.add(loan); db.session.flush()
        db.session.add(ImfMovement(loan_id=loan.id, panstwo_id=2, budget_id=None, stage='disbursement', amount=Decimal('10000000'), request_id='x', game_datetime=NOW))
        db.session.add(StateFinancialAccount(panstwo_id=2, reserve_balance=Decimal('10000000'), last_budget_id=None, last_transaction_sequence=0, created_at=NOW, updated_at=NOW))
        db.session.commit()
        self.scenario_with_collection()

    def scenario_with_collection(self):
        from sqlalchemy import MetaData, Table, Column, Integer, String
        from game.finance_models import BudgetCategory, StateFinancialPeriod, StateTaxAssessment, StateFinancialTransaction, StateBudgetAllocation
        from game.finance_service import preview_budget, approve_manual_budget
        from models import Spoleczenstwo
        from game.population_structure import PopulationStructure
        db.session.remove()
        for model in (StateBudgetAllocation, StateBudget):
            model.__table__.drop(db.engine)
        for model in (BudgetCategory, StateFinancialPeriod, StateBudget, StateBudgetAllocation, StateTaxAssessment, StateFinancialTransaction):
            metadata = MetaData()
            Table(model.__tablename__, metadata, *[Column(c.name, Integer() if c.primary_key and c.name == 'id' else String(c.type.length) if isinstance(c.type, String) else c.type,
                                                         primary_key=c.primary_key, nullable=True) for c in model.__table__.columns]).create(db.engine)
        db.session.add_all([BudgetCategory(code=code, name_pl=code, display_order=i + 1, is_reserve=code == 'reserve')
                            for i, code in enumerate(__import__('game.budget_categories', fromlist=['CODES']).CODES)])
        db.session.execute(text('UPDATE panstwa SET panstwo_populacja=1000,panstwo_PKB=5000000 WHERE PANSTWO_ID=2'))
        db.session.execute(text('UPDATE regiony SET region_stan_infra_drogowej=50,region_stan_infra_kolejowej=50,region_stan_infra_energetycznej=50,region_stan_infra_mieszkalnej=50,region_polozenie_id=1 WHERE region_id=2'))
        db.session.add(PopulationStructure(panstwo_id=2, children=20, working=60, seniors=20, version=1, actor='Test'))
        db.session.add(Spoleczenstwo(panstwo_id=2, zadowolenie_spoleczne=60, stabilnosc_spoleczna=70, poziom_edukacji=80, zdrowie_publiczne=75, przestepczosc=8, zaufanie_do_wladzy=61))
        db.session.commit()
        with patch('game.finance_service.game_now', return_value=NOW), patch('game.imf.game_now', return_value=NOW):
            quote = preview_budget(2, pit_rate=10, cit_rate=0, shares={'reserve': 100})
            available = Decimal('10000000') + Decimal(quote['tax_total'])
            expected = min(Decimal('10000000'), (available * Decimal('0.65')).quantize(Decimal('0.01'), rounding='ROUND_DOWN'))
            self.assertEqual(quote['imf_collection'], expected)
            self.assertEqual(quote['budget_total'], available - expected)
            approve_manual_budget(2, year=2990, period=1, expected_basis=quote['basis_token'], pit_rate=10, cit_rate=0, shares={'reserve': 100})
        db.session.expire_all()
        budget = db.session.scalar(select(StateBudget).where(StateBudget.panstwo_id == 2))
        self.assertEqual(Decimal(budget.imf_collection), expected)
        self.assertEqual(Decimal(budget.budget_total), Decimal(budget.opening_reserve) + Decimal(budget.tax_total) - Decimal(budget.imf_collection))
        account = db.session.get(StateFinancialAccount, 2)
        self.assertEqual(account.reserve_balance, Decimal(budget.closing_reserve))
        loan = db.session.scalar(select(ImfLoan))
        self.assertEqual(loan.outstanding, Decimal('10000000') - expected)
        self.assertEqual(loan.status, 'active' if expected < Decimal('10000000') else 'repaid')
        operations = list(db.session.scalars(select(StateFinancialTransaction.operation_type)))
        self.assertEqual(operations.count('IMF_COLLECTION'), 1)
        self.assertEqual(db.session.scalar(select(ImfMovement).where(ImfMovement.stage == 'collection')).amount, -expected)
        self.assertEqual(_reserve_for_account(account, budget), account.reserve_balance)


class ImfPagaTests(ImfFixture):
    def make_ctx(self, screen, traits=None, war=False, needs=0.0, available=0.0):
        return SimpleNamespace(screen=lambda name: {'data': screen} if name == 'imf' else None,
                               traits={'debt_tolerance': 50, 'fiscal_conservatism': 50, 'isolationism': 50, **(traits or {})},
                               situation={'level': 'war' if war else 'peace'}, available=lambda sector: available,
                               sector_start=lambda sector: 1e11 if war else 0.0, country_id=1)

    def screen(self, **extra):
        return {'reserve': '0', 'loans': [], 'credit': {'maxLoan': '500000000000', 'capacity': '500000000000', 'base': '500000000000'}, **extra}

    def options(self, ctx, needs=0.0):
        from game.paga2 import finance
        with patch.object(finance, 'plan_needs', return_value={'infrastructure': needs} if needs else {}):
            return finance.imf_options(ctx)

    def request(self, need=2e11, screen=None, **traits):
        war = traits.pop('war', False)
        found = [o for o in self.options(self.make_ctx(screen or self.screen(), traits, war=war), need) if o.action == 'IMF_REQUEST']
        return found[0] if found else None

    def test_request_depends_on_tolerance_isolationism_and_war(self):
        self.assertIsNotNone(self.request())
        self.assertIsNone(self.request(debt_tolerance=20))
        self.assertIsNone(self.request(debt_tolerance=40, isolationism=95))
        war = self.request(need=0.0, debt_tolerance=25, war=True)
        self.assertIsNotNone(war)
        cautious = self.request(fiscal_conservatism=69)
        liberal = self.request(fiscal_conservatism=0, debt_tolerance=90)
        self.assertLess(Decimal(cautious.payload['amount']), Decimal(liberal.payload['amount']))

    def test_1_high_conservatism_blocks_in_peace_and_limits_in_war(self):
        self.assertIsNone(self.request(fiscal_conservatism=80, debt_tolerance=90))
        war = self.request(fiscal_conservatism=80, debt_tolerance=90, war=True)
        self.assertLessEqual(Decimal(war.payload['amount']), Decimal('80000000000'))      # 40% z 200 MLD

    def test_2_low_isolationism_does_not_lower_threshold_below_35(self):
        self.assertIsNone(self.request(debt_tolerance=30, isolationism=5))
        self.assertIsNotNone(self.request(debt_tolerance=36, isolationism=5))
        self.assertIsNone(self.request(need=0.0, debt_tolerance=19, isolationism=5, war=True))     # wojna: próg 20 (35 − 15)
        self.assertIsNotNone(self.request(need=0.0, debt_tolerance=21, isolationism=5, war=True))

    def test_3_keeps_credit_headroom(self):
        option = self.request(screen=self.screen(credit={'maxLoan': '100000000000', 'capacity': '100000000000', 'base': '100000000000'}))
        self.assertEqual(option.payload['amount'], '60000000000')                         # 60% zdolności przy tolerancji 50

    def test_4_requires_meaningful_coverage(self):
        small = self.screen(credit={'maxLoan': '10000000000', 'capacity': '10000000000', 'base': '10000000000'})
        self.assertIsNone(self.request(screen=small))                                     # 6 MLD < 30% z 200 MLD
        self.assertIsNotNone(self.request(need=1.5e10, screen=small))                    # 6 MLD ≥ 30% z 15 MLD

    def test_5_no_second_loan_while_one_is_active_even_in_war(self):
        loan = {'id': 1, 'status': 'active', 'amount': '30000000000', 'outstanding': '30000000000', 'overdue': False, 'periodsLeft': 4, 'createdAt': '2000-01-01T00:00:00Z'}
        roomy = self.screen(loans=[loan], credit={'maxLoan': '60000000000', 'capacity': '60000000000', 'base': '100000000000'})
        self.assertIsNone(self.request(need=0.0, screen=roomy, debt_tolerance=90, war=True))

    def test_interest_cost_in_notes_and_lower_score(self):
        cheap = self.request(screen=self.screen())
        costly = self.request(screen=self.screen(rules={'interestRate': '5'}))
        self.assertTrue(any('Koszt odsetek' in note for note in costly.notes))
        self.assertLess(costly.base, cheap.base)

    def test_6_separate_notes_for_plans_and_army_gap(self):
        option = self.request(need=0.0, war=True)
        self.assertTrue(any(note.startswith('Luka w budżecie sił zbrojnych') for note in option.notes))
        self.assertFalse(any(note.startswith('Niedobór środków na plany') for note in option.notes))
        option = self.request()
        self.assertTrue(any(note.startswith('Niedobór środków na plany') for note in option.notes))

    def test_repays_when_reserve_allows_or_deadline_is_near(self):
        loan = {'id': 1, 'status': 'active', 'amount': '5000000000', 'outstanding': '5000000000', 'overdue': False, 'periodsLeft': 3, 'createdAt': '2000-01-01T00:00:00Z'}
        rich = self.options(self.make_ctx(self.screen(reserve='20000000000', loans=[loan]), {'fiscal_conservatism': 70}))
        self.assertEqual(rich[0].action, 'IMF_REPAY'); self.assertEqual(rich[0].payload['amount'], 'all')
        urgent = self.options(self.make_ctx(self.screen(reserve='4000000000', loans=[{**loan, 'periodsLeft': 1}]), {'fiscal_conservatism': 20, 'debt_tolerance': 90}))
        self.assertEqual(urgent[0].action, 'IMF_REPAY'); self.assertEqual(urgent[0].payload['amount'], '4000000000.00')

    # ---- (B) spłata ratalna ----
    def test_installment_schedule(self):
        from game.paga2.finance import imf_installment
        loan = {'status': 'active', 'amount': '9000000000', 'outstanding': '9000000000'}
        self.assertEqual(imf_installment([{**loan, 'periodsLeft': 4}]), 0)                       # cykl wypłaty: bez raty
        self.assertAlmostEqual(imf_installment([{**loan, 'periodsLeft': 3}]), 3e9)
        self.assertAlmostEqual(imf_installment([{**loan, 'outstanding': '6000000000', 'periodsLeft': 3}]), 0)   # rata już spłacona
        self.assertAlmostEqual(imf_installment([{**loan, 'outstanding': '6000000000', 'periodsLeft': 2}]), 3e9)
        self.assertAlmostEqual(imf_installment([{**loan, 'outstanding': '3000000000', 'periodsLeft': 1}]), 3e9)  # przed terminem: reszta
        self.assertAlmostEqual(imf_installment([{**loan, 'periodsLeft': 0, 'overdue': True}]), 9e9)
        self.assertEqual(imf_installment([{**loan, 'status': 'repaid', 'periodsLeft': 3}]), 0)

    def test_installment_paid_even_without_surplus_and_plans_protect_less_near_deadline(self):
        loan = {'id': 1, 'status': 'active', 'amount': '9000000000', 'outstanding': '9000000000', 'overdue': False, 'periodsLeft': 3, 'createdAt': '2000-01-01T00:00:00Z'}
        traits = {'fiscal_conservatism': 20, 'debt_tolerance': 90}   # niechętne spłacie z nadwyżki
        screen = self.screen(reserve='10000000000', loans=[loan])
        repay = [o for o in self.options(self.make_ctx(screen, traits), needs=12e9) if o.action == 'IMF_REPAY']
        self.assertEqual(Decimal(repay[0].payload['amount']), Decimal('3000000000'))              # pełna rata 3 MLD
        tight = self.screen(reserve='5000000000', loans=[loan])
        partial = [o for o in self.options(self.make_ctx(tight, traits), needs=8e9) if o.action == 'IMF_REPAY']
        self.assertEqual(Decimal(partial[0].payload['amount']), Decimal('750000000'))             # 5 − 50%·8 − 5%·5 = 0,75 MLD
        last = self.screen(reserve='5000000000', loans=[{**loan, 'outstanding': '3000000000', 'periodsLeft': 1}])
        final = [o for o in self.options(self.make_ctx(last, traits), needs=8e9) if o.action == 'IMF_REPAY']
        self.assertEqual(final[0].payload['amount'], 'all')                                        # ostatni cykl: plany nie chronią

    def test_no_new_imf_request_in_a_cycle_with_repayment(self):
        loan = {'id': 1, 'status': 'active', 'amount': '9000000000', 'outstanding': '9000000000', 'overdue': False, 'periodsLeft': 3, 'createdAt': '2000-01-01T00:00:00Z'}
        screen = self.screen(reserve='10000000000', loans=[loan])
        actions = [o.action for o in self.options(self.make_ctx(screen, {'debt_tolerance': 90}, war=True))]   # luka wojenna 50 MLD, rata możliwa
        self.assertEqual(actions, ['IMF_REPAY'])

    # ---- (A) odkładanie raty w budżecie ----
    def test_budget_keeps_installment_in_reserve(self):
        from game.paga2.budget import with_imf_reserve, imf_reserve_target, SECTORS
        shares = {s: Decimal('9.50') for s in SECTORS}                                             # rezerwa 5%
        state = {'budget_total': '100000000000'}
        same, changed = with_imf_reserve(shares, state, Decimal('3000000000'))
        self.assertFalse(changed)                                                                  # 5% ≥ 3 MLD
        adjusted, changed = with_imf_reserve(shares, state, Decimal('20000000000'))
        self.assertTrue(changed)
        self.assertGreaterEqual(Decimal(100) - sum(adjusted.values()), Decimal('20'))
        capped, _ = with_imf_reserve(shares, state, Decimal('90000000000'), war=True)
        self.assertLessEqual(Decimal(100) - sum(capped.values()), Decimal('25.2'))
        loan = {'status': 'active', 'amount': '9000000000', 'outstanding': '9000000000', 'periodsLeft': 3}
        careful = imf_reserve_target(self.make_ctx(self.screen(loans=[loan]), {'fiscal_conservatism': 90, 'debt_tolerance': 10}))
        relaxed = imf_reserve_target(self.make_ctx(self.screen(loans=[loan]), {'fiscal_conservatism': 10, 'debt_tolerance': 90}))
        self.assertGreater(careful, relaxed)
        self.assertEqual(careful, Decimal('3900000000.00'))                                        # 1,3 raty
        self.assertEqual(relaxed, Decimal('2400000000.00'))                                        # 0,8 raty

