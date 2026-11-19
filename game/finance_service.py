"""Obliczenia i transakcyjne zatwierdzanie budżetów państw."""

import hashlib
import hmac
import json
from game.governance import economy, controlled_ids
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP
from decimal import localcontext

from sqlalchemy import select
from sqlalchemy.orm import Session, object_session, lazyload

from extensions import db
from engine.clock import get_current_entenda_datetime
from game.models import GamePlayerCountry, GameUser
from models import Panstwo

from game.finance_models import (
    BudgetCategory,
    StateBudget,
    StateBudgetAllocation,
    StateFinancialAccount,
    StateFinancialPeriod,
    StateFinancialTransaction,
    StateTaxAssessment,
)


CALCULATION_VERSION = 5

CENT = Decimal("0.01")
HUNDRED = Decimal("100")
ZERO = Decimal("0.00")
MONEY_LIMIT = Decimal("10000000000000000000000000000")

from game.budget_categories import CODES as CATEGORY_CODES,normalize as normalize_categories,complete as complete_categories

EXPENDITURE_CODES = CATEGORY_CODES[:-1]


class FinanceError(Exception):
    """Błąd danych lub stanu finansów."""


class FinanceConflict(FinanceError):
    """Stan zmienił się od czasu przygotowania formularza."""


class FinancePermissionError(FinanceError):
    """Brak dostępu do finansów państwa."""


def utc_now():
    """UTC bez tzinfo, zgodnie z kolumnami MySQL DATETIME."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def game_now():
    return get_current_entenda_datetime()


# 13 Nov 2026: od 1 października 3001 budżet ustala się kwartalnie (1 stycznia, 1 kwietnia, 1 lipca, 1 października).
# Wcześniej obowiązywały półrocza; II półrocze 3001 kończy się 1 października 3001. Numer okresu:
# półrocza 1–2 (do 3001), kwartały 1–4 (IV kwartał 3001 = (3001, 4), od 3002 kwartały 1–4) — kolejność krotek zachowana.
QUARTER_START = datetime(3001, 10, 1)


def is_quarterly(year, period):
    return year > QUARTER_START.year or (year == QUARTER_START.year and period == 4)


def period_key(moment):
    if not 1 <= moment.year <= 9998:
        raise FinanceError("Rok gry poza obsługiwanym zakresem.")
    if moment >= QUARTER_START:
        return moment.year, (moment.month - 1) // 3 + 1
    return moment.year, 1 if moment.month <= 6 else 2


def period_bounds(year, period):
    if (
        isinstance(year, bool)
        or not isinstance(year, int)
        or not 1 <= year <= 9998
        or isinstance(period, bool)
        or period not in (1, 2, 3, 4)
    ):
        raise FinanceError("Nieprawidłowy rok lub okres budżetowy.")
    if is_quarterly(year, period):
        start = datetime(year, 3 * (period - 1) + 1, 1)
        end = datetime(year + 1, 1, 1) if period == 4 else datetime(year, 3 * period + 1, 1)
        return start, end
    if period not in (1, 2) or year > QUARTER_START.year:
        raise FinanceError("Nieprawidłowy rok lub okres budżetowy.")
    if period == 1:
        return datetime(year, 1, 1), datetime(year, 7, 1)
    end = datetime(year + 1, 1, 1)
    return datetime(year, 7, 1), min(end, QUARTER_START) if year == QUARTER_START.year else end


def period_months(year, period):
    """Nominalna długość okresu: kwartał 3 miesiące, półrocze 6 (podstawa przeliczania kwot rocznych)."""
    return 3 if is_quarterly(year, period) else 6


def period_share(year, period):
    return Decimal(period_months(year, period)) / Decimal(12)


def current_period_months(moment=None):
    return period_months(*period_key(moment or game_now()))


def next_period_key(key):
    year, period = key
    if is_quarterly(year, period):
        return (year + 1, 1) if period == 4 else (year, period + 1)
    if period == 1:
        return (year, 2)
    return (year, 4) if year == QUARTER_START.year else (year + 1, 1)


def period_words(year=None, period=None):
    """16 Nov 2026: odmiana nazwy okresu budżetowego do tekstów gry (kwartał od 1 października 3001, wcześniej półrocze)."""
    if year is None or period is None:
        year, period = period_key(game_now())
    quarterly = is_quarterly(year, period)
    return {'nom': 'kwartał' if quarterly else 'półrocze', 'gen': 'kwartału' if quarterly else 'półrocza',
            'loc': 'kwartale' if quarterly else 'półroczu', 'current': 'bieżący kwartał' if quarterly else 'bieżące półrocze', 'adj': 'kwartalne' if quarterly else 'półroczne',
            'months': period_months(year, period), 'share': 25 if quarterly else 50,
            'per_year': 'cztery razy do roku: w styczniu, kwietniu, lipcu i październiku' if quarterly else 'dwa razy do roku: w styczniu i lipcu',
            'label': period_label(year, period)}


def period_label(year, period):
    roman = {1: "I", 2: "II", 3: "III", 4: "IV"}[period]
    return f"{roman} kwartał {year}" if is_quarterly(year, period) else f"{roman} półrocze {year}"


def decimal_value(value, label):
    if isinstance(value, bool) or value is None:
        raise FinanceError(f"{label}: nieprawidłowa wartość.")

    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise FinanceError(f"{label}: podaj liczbę.") from None

    if not result.is_finite():
        raise FinanceError(f"{label}: podaj skończoną liczbę.")

    return result


def percentage(value, label):
    number = decimal_value(value, label)

    if not ZERO <= number <= HUNDRED:
        raise FinanceError(f"{label}: wartość musi wynosić od 0 do 100%.")

    with localcontext() as context:
        context.prec = 64
        rounded = number.quantize(CENT)

    if number != rounded:
        raise FinanceError(f"{label}: maksymalnie dwa miejsca po przecinku.")

    return rounded


def money(value, label="Kwota"):
    number = decimal_value(value, label)

    if number < 0 or number >= MONEY_LIMIT:
        raise FinanceError(f"{label}: kwota poza obsługiwanym zakresem.")

    with localcontext() as context:
        context.prec = 64
        result = number.quantize(CENT, rounding=ROUND_HALF_UP)

    if result >= MONEY_LIMIT:
        raise FinanceError(f"{label}: kwota poza obsługiwanym zakresem.")

    return result


def normalize_shares(raw_shares):
    if not isinstance(raw_shares, dict):
        raise FinanceError("Podział budżetu musi być słownikiem kategorii.")

    unknown = set(raw_shares) - set(CATEGORY_CODES)

    if unknown:
        raise FinanceError("Przekazano nieznaną kategorię budżetową.")

    shares = {
        code: percentage(raw_shares.get(code, "0"), code)
        for code in CATEGORY_CODES
    }

    total = sum(shares.values(), ZERO)

    if total > HUNDRED:
        raise FinanceError("Suma udziałów przekracza 100%.")

    # Niewykorzystana część powiększa rezerwę.
    shares["reserve"] += HUNDRED - total

    return shares


def _general_tax_basis(session,country_id):
    from game.general_tax import capture_basis
    return capture_basis(session,country_id)


def calculate_budget(gdp, population, reserve, pit_rate, cit_rate, shares, *, revenue_basis=None, share=Decimal("0.5"), imf_due=ZERO):
    """Czyste obliczenia. Funkcja nie korzysta z bazy."""

    with localcontext() as context:
        context.prec = 64

        gdp = money(gdp, "PKB")
        reserve = money(reserve, "Rezerwa")

        population_decimal = decimal_value(population, "Ludność")

        if (
            population_decimal <= 0
            or population_decimal != population_decimal.to_integral_value()
            or population_decimal > Decimal("9223372036854775807")
        ):
            raise FinanceError("Ludność musi być dodatnią liczbą całkowitą.")

        population = int(population_decimal)

        pit_rate = percentage(pit_rate, "PIT")
        cit_rate = percentage(cit_rate, "CIT") if revenue_basis is None else ZERO
        shares = normalize_shares(shares)

        gdp_per_capita = gdp / population

        if gdp_per_capita >= Decimal("100000000000000000000000000"):
            raise FinanceError("PKB per capita poza zakresem zapisu.")

        # Roczne wpływy. PIT jest algebraicznie uproszczony:
        # (PKB / ludność) * (ludność / 2) * (PIT / 100).
        annual_pit = gdp * pit_rate / Decimal("200")
        annual_cit = gdp * cit_rate / Decimal("200")
        components=None
        penalty=0
        if revenue_basis is not None:
            from game.general_tax import annual_revenue
            annual_pit,components=annual_revenue(revenue_basis,pit_rate)
            from game.general_tax import tax_penalty
            penalty=tax_penalty(revenue_basis,pit_rate)
            annual_cit=ZERO

        # Transza okresu: półrocze 50%, kwartał 25% rocznych wpływów (pola zachowują nazwy half_year_*).
        half_year_pit = money(annual_pit * share, "PIT okresu")
        half_year_cit = money(annual_cit * share, "CIT okresu")

        tax_total = money(half_year_pit + half_year_cit)
        # 18 Nov 2026: zaległy dług w MFW pobierany przed podziałem — najwyżej 65% środków budżetu (game.imf).
        from game.imf import collection_amount
        imf_collection = collection_amount(money(imf_due or ZERO, "Dług w MFW"), reserve + tax_total)
        budget_total = money(reserve + tax_total - imf_collection, "Dostępne środki")

        allocations = {}

        for code in EXPENDITURE_CODES:
            allocations[code] = (
                budget_total * shares[code] / HUNDRED
            ).quantize(CENT, rounding=ROUND_DOWN)

        expenditure_total = sum(allocations.values(), ZERO)

        # Różnice groszowe również pozostają w rezerwie.
        closing_reserve = budget_total - expenditure_total
        allocations["reserve"] = closing_reserve

        if sum(allocations.values(), ZERO) != budget_total:
            raise FinanceError("Niezgodność sumy przydziałów.")

        return {
            "revenue_basis":revenue_basis, "revenue_components":components,
            "tax_penalty":penalty,
            "gdp": gdp,
            "population": population,
            "gdp_per_capita": gdp_per_capita.quantize(
                Decimal("0.000000000001"),
                rounding=ROUND_HALF_UP,
            ),
            "pit_rate": pit_rate,
            "cit_rate": cit_rate,
            "annual_pit": annual_pit,
            "annual_cit": annual_cit,
            "half_year_pit": half_year_pit,
            "half_year_cit": half_year_cit,
            "tax_total": tax_total,
            "opening_reserve": reserve,
            "imf_due": money(imf_due or ZERO),
            "imf_collection": imf_collection,
            "budget_total": budget_total,
            "expenditure_total": expenditure_total,
            "closing_reserve": closing_reserve,
            "shares": shares,
            "allocations": allocations,
        }


def _country_for_user(session, user_id, lock=False):
    user_statement = select(GameUser).where(GameUser.id == user_id)

    if lock:
        user_statement = user_statement.with_for_update()

    user = session.scalar(user_statement)

    if user is None or not user.is_active:
        raise FinancePermissionError("Konto gracza jest nieaktywne.")

    from game.paga_ai_actor import assigned_country
    ai_country=assigned_country(session,user_id,lock=lock)
    from game.sovereignty import require_sovereign
    if ai_country is not None:
        require_sovereign(session,ai_country.PANSTWO_ID)
        return ai_country

    assignment_statement = select(GamePlayerCountry).where(
        GamePlayerCountry.user_id == user_id
    )

    if lock:
        assignment_statement = assignment_statement.with_for_update()

    assignment = session.scalar(assignment_statement)

    if assignment is None:
        raise FinancePermissionError("Do konta nie przypisano państwa.")

    country_statement = select(Panstwo).options(lazyload("*")).where(
        Panstwo.PANSTWO_ID == assignment.panstwo_id
    )

    if lock:
        country_statement = country_statement.with_for_update()

    country = session.scalar(country_statement)

    if country is None:
        raise FinanceError("Przypisane państwo nie istnieje.")
    if country.czy_suwerenny != "TAK":
        raise FinancePermissionError("Państwo niesuwerenne jest zarządzane przez państwo zwierzchnie.")
    require_sovereign(session, country.PANSTWO_ID)

    return country


def _existing_budget(session, country_id, year, period):
    return session.scalar(
        select(StateBudget)
        .where(
            StateBudget.panstwo_id == country_id,
            StateBudget.game_year == year,
            StateBudget.period == period,
        )
        .with_for_update()
    )


def _previous_budget(session, country_id, year, period):
    return session.scalar(
        select(StateBudget)
        .where(
            StateBudget.panstwo_id == country_id,
            (
                (StateBudget.game_year < year)
                | (
                    (StateBudget.game_year == year)
                    & (StateBudget.period < period)
                )
            ),
        )
        .order_by(
            StateBudget.game_year.desc(),
            StateBudget.period.desc(),
        )
        .limit(1)
    )


def _previous_plan(session, previous):
    if previous is None:
        return {
            "pit_rate": Decimal("5.00"),
            "cit_rate": Decimal("0.00"),
            "shares": {
                code: HUNDRED if code == "reserve" else ZERO
                for code in CATEGORY_CODES
            },
        }

    assessment = session.scalar(
        select(StateTaxAssessment).where(
            StateTaxAssessment.budget_id == previous.id
        )
    )

    rows = session.scalars(
        select(StateBudgetAllocation).where(
            StateBudgetAllocation.budget_id == previous.id
        )
    ).all()

    if (
        assessment is None
        or not complete_categories(rows)
    ):
        raise FinanceError("Poprzedni budżet ma niekompletne dane.")

    shares = normalize_categories((row.category_code,row.share_percent) for row in rows)

    if sum(shares.values(), ZERO) != HUNDRED:
        raise FinanceError("Niepoprawne udziały poprzedniego budżetu.")

    return {
        "pit_rate": assessment.pit_rate,
        "cit_rate": assessment.cit_rate,
        "shares": shares,
    }


def _validate_categories(session):
    rows = session.scalars(select(BudgetCategory).where(BudgetCategory.code.in_(CATEGORY_CODES))).all()

    if (
        len(rows) != len(CATEGORY_CODES)
        or {row.code for row in rows} != set(CATEGORY_CODES)
        or {row.code for row in rows if row.is_reserve} != {"reserve"}
    ):
        raise FinanceError("Słownik kategorii budżetowych jest niepoprawny.")


def _reserve_for_account(account, previous):
    if account is None:
        if previous is not None:
            raise FinanceError("Brak rachunku dla istniejącej historii budżetów.")

        return ZERO

    if previous is None:
        from game.loans import loan_delta
        from game.trade_service import reserve_delta
        from game.admin_finance import adjustment_delta
        from game.imf import reserve_delta as imf_delta
        incoming=loan_delta(object_session(account),account.panstwo_id,None)+reserve_delta(object_session(account),account.panstwo_id,None)+adjustment_delta(object_session(account),account.panstwo_id,None)+imf_delta(object_session(account),account.panstwo_id,None)
        if (
            account.last_budget_id is not None
            or account.reserve_balance != incoming
            or account.last_transaction_sequence != 0
        ):
            raise FinanceError("Niespójny rachunek przed pierwszym budżetem.")

        return account.reserve_balance

    from game.loans import loan_delta
    from game.admin_finance import adjustment_delta
    from game.infrastructure_service import reserve_spent
    from game.trade_service import reserve_delta
    from game.budget_transfers import transfer_delta
    from game.imf import reserve_delta as imf_delta
    if (
        account.last_budget_id != previous.id
        or account.reserve_balance != previous.closing_reserve + imf_delta(object_session(account),account.panstwo_id,previous.id) + loan_delta(object_session(account),account.panstwo_id,previous.id) + adjustment_delta(object_session(account),account.panstwo_id,previous.id) + transfer_delta(object_session(account),previous.id,"reserve") + reserve_delta(object_session(account),account.panstwo_id,previous.id) - reserve_spent(object_session(account), previous.id)
    ):
        raise FinanceError("Saldo rachunku nie odpowiada ostatniemu budżetowi.")

    return account.reserve_balance


def _basis_token(country, year, period, reserve, previous, imf_due=ZERO):
    """Znacznik wykrywający zmianę podstaw od ostatniego podglądu."""

    from game.civic_models import CountryTaxPolicy
    from game.population_structure import PopulationStructure
    structure=object_session(country).get(PopulationStructure,country.PANSTWO_ID)
    policy=object_session(country).get(CountryTaxPolicy,country.PANSTWO_ID)
    data = {
        "population_structure_version":structure.version if structure else 0,
        "tax_policy_version":policy.version if policy else 0,
        "general_tax_basis":_general_tax_basis(object_session(country),country.PANSTWO_ID),
        "country_id": country.PANSTWO_ID,
        "year": year,
        "period": period,
        "gdp": str(economy(object_session(country), country.PANSTWO_ID)["gdp"]),
        "population": str(economy(object_session(country), country.PANSTWO_ID)["population"]),
        "reserve": str(money(reserve)),
        "previous_budget_id": previous.id if previous else None,
        "controlled_country_ids": controlled_ids(object_session(country), country.PANSTWO_ID),
        "calculation_version": CALCULATION_VERSION,
    }
    if imf_due:
        data["imf_due"] = str(money(imf_due))   # 18 Nov 2026: zmiana zaległości w MFW wymaga odświeżenia podglądu

    payload = json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(payload).hexdigest()


def preview_budget(user_id, pit_rate=None, cit_rate=None, shares=None,
                   repeat_previous=False):
    """Podgląd bez tworzenia okresu, rachunku ani budżetu."""

    moment = game_now()
    year, period = period_key(moment)

    with Session(db.engine, expire_on_commit=False) as session:
        country = _country_for_user(session, user_id)
        _validate_categories(session)

        existing = session.scalar(
            select(StateBudget).where(
                StateBudget.panstwo_id == country.PANSTWO_ID,
                StateBudget.game_year == year,
                StateBudget.period == period,
            )
        )

        if existing is not None:
            return {
                "approved": True,
                "budget_id": existing.id,
                "year": year,
                "period": period,
            }

        financial_period = session.scalar(
            select(StateFinancialPeriod).where(
                StateFinancialPeriod.panstwo_id == country.PANSTWO_ID,
                StateFinancialPeriod.game_year == year,
                StateFinancialPeriod.period == period,
            )
        )

        if financial_period is not None and financial_period.status != "PENDING":
            raise FinanceConflict("Bieżący okres nie oczekuje na zatwierdzenie.")

        previous = _previous_budget(
            session, country.PANSTWO_ID, year, period
        )

        account = session.get(
            StateFinancialAccount,
            country.PANSTWO_ID,
        )

        reserve = _reserve_for_account(account, previous)
        from game.imf import due_amount
        imf_due = due_amount(session, country.PANSTWO_ID, (year, period))
        from game.admin_finance import tax_plan
        plan = tax_plan(session,country.PANSTWO_ID,_previous_plan(session, previous))

        if repeat_previous and previous is None:
            raise FinanceError("Nie ma poprzedniego planu do zachowania.")

        if not repeat_previous:
            if pit_rate is not None:
                plan["pit_rate"] = pit_rate
            if cit_rate is not None:
                plan["cit_rate"] = cit_rate
            if shares is not None:
                plan["shares"] = shares

        plan = tax_plan(session,country.PANSTWO_ID,plan)
        result = calculate_budget(
            economy(session, country.PANSTWO_ID)["gdp"],
            economy(session, country.PANSTWO_ID)["population"],
            reserve,
            plan["pit_rate"],
            plan["cit_rate"],
            plan["shares"],
            revenue_basis=_general_tax_basis(session,country.PANSTWO_ID),
            share=period_share(year, period),
            imf_due=imf_due,
        )

        from game.social_benefits import expectations,carryover
        result["benefits"]={"expected":expectations(session,country.PANSTWO_ID),"carry_in":carryover(session,previous)}
        # 16 Nov 2026: oczekiwania społeczne wobec środków na walkę z przestępczością (sektor służb specjalnych i porządkowych).
        from game.crime_funding import expectations as crime_expectations, CrimeFunding
        crime=crime_expectations(session,country.PANSTWO_ID)
        previous_crime=session.get(CrimeFunding,previous.id) if previous is not None else None
        result["crime"]={"expected":crime["expected"] if crime else None,"level":crime["level"] if crime else None,
                         "previous_paid":previous_crime.paid if previous_crime is not None else None}
        result.update({
            "approved": False,
            "country_id": country.PANSTWO_ID,
            "country_name": country.panstwo_nazwa,
            "year": year,
            "period": period,
            "has_previous": previous is not None,
            "basis_token": _basis_token(
                country, year, period, reserve, previous, imf_due
            ),
        })

        return result


def _get_period(session, country_id, year, period, now):
    row = session.scalar(
        select(StateFinancialPeriod)
        .where(
            StateFinancialPeriod.panstwo_id == country_id,
            StateFinancialPeriod.game_year == year,
            StateFinancialPeriod.period == period,
        )
        .with_for_update()
    )

    if row is None:
        starts, ends = period_bounds(year, period)

        row = StateFinancialPeriod(
            panstwo_id=country_id,
            game_year=year,
            period=period,
            starts_at_game=starts,
            ends_at_game=ends,
            status="PENDING",
            created_at=now,
        )

        session.add(row)
        session.flush()

    if row.status != "PENDING":
        raise FinanceConflict("Okres został już zakończony.")

    return row


def _post_transaction(session, account, budget, operation_type,
                      direction, amount, real_now, entenda_now,
                      category_code=None):
    with localcontext() as context:
        context.prec = 64

        before = account.reserve_balance

        after = (
            before + amount
            if direction == "CREDIT"
            else before - amount
        )

        after = money(after, "Saldo po operacji")
        sequence = account.last_transaction_sequence + 1

        operation_key = (
            f"budget:{budget.id}:{operation_type}:"
            f"{category_code or '-'}"
        )

        session.add(
            StateFinancialTransaction(
                panstwo_id=account.panstwo_id,
                budget_id=budget.id,
                operation_key=operation_key,
                sequence_number=sequence,
                operation_type=operation_type,
                direction=direction,
                category_code=category_code,
                amount=amount,
                balance_before=before,
                balance_after=after,
                created_at=real_now,
                game_datetime=entenda_now,
            )
        )

        account.reserve_balance = after
        account.last_transaction_sequence = sequence


def approve_in_transaction(
    session,
    country,
    year,
    period,
    *,
    user_id,
    repeat_previous,
    automatic_reason=None,
    pit_rate=None,
    cit_rate=None,
    shares=None,
    expected_basis=None,
    benefits=None,
    crime_funding=None,
):
    """Wspólny mechanizm księgowania.

    Nie wykonuje commit.

    Wywołujący musi utrzymywać blokadę rekordu Panstwo oraz przydziału
    państwa. Scheduler musi dodatkowo sprawdzić swoją dzierżawę i token
    koordynatora w tej samej transakcji.
    """

    if automatic_reason not in (None, "PERIOD_CLOSE", "STARTUP_RECOVERY"):
        raise FinanceError("Nieprawidłowa przyczyna automatyzacji.")

    automatic = automatic_reason is not None

    if automatic:
        if user_id is not None or not repeat_previous:
            raise FinanceError("Nieprawidłowe automatyczne zatwierdzenie.")
    elif user_id is None:
        raise FinancePermissionError("Brak użytkownika zatwierdzającego.")

    # Idempotencja: zwróć istniejący wynik bez kolejnego naliczenia.
    existing = _existing_budget(
        session, country.PANSTWO_ID, year, period
    )

    if existing is not None:
        return {
            "budget_id": existing.id,
            "already_approved": True,
        }

    captured_game_time = game_now()
    captured_real_time = utc_now()

    current_key = period_key(captured_game_time)
    _, ends_at = period_bounds(year, period)

    if automatic_reason == "PERIOD_CLOSE":
        if ends_at > captured_game_time:
            raise FinanceConflict("Półrocze jeszcze się nie zakończyło.")
    elif (year, period) != current_key:
        raise FinanceConflict(
            "Zmienił się okres budżetowy. Odśwież formularz budżetu."
        )

    _validate_categories(session)

    previous = _previous_budget(
        session, country.PANSTWO_ID, year, period
    )

    if repeat_previous and previous is None:
        raise FinanceError(
            "Pierwszy budżet musi zostać zatwierdzony ręcznie."
        )

    account = session.scalar(
        select(StateFinancialAccount)
        .where(StateFinancialAccount.panstwo_id == country.PANSTWO_ID)
        .with_for_update()
    )

    reserve = _reserve_for_account(account, previous)
    from game.imf import due_amount
    imf_due = due_amount(session, country.PANSTWO_ID, (year, period))

    if not automatic:
        actual_basis = _basis_token(
            country, year, period, reserve, previous, imf_due
        )

        if (
            not isinstance(expected_basis, str)
            or not hmac.compare_digest(expected_basis, actual_basis)
        ):
            raise FinanceConflict(
                "Dane państwa lub rezerwa zmieniły się. Odśwież podgląd."
            )

    if repeat_previous:
        from game.admin_finance import tax_plan
        plan = tax_plan(session,country.PANSTWO_ID,_previous_plan(session, previous))
    else:
        if pit_rate is None or shares is None:
            raise FinanceError("Nie przekazano kompletnego planu.")

        plan = {
            "pit_rate": pit_rate,
            "cit_rate": cit_rate,
            "shares": shares,
        }

    from game.admin_finance import tax_plan
    plan = tax_plan(session,country.PANSTWO_ID,plan)
    calculation = calculate_budget(
        economy(session, country.PANSTWO_ID)["gdp"],
        economy(session, country.PANSTWO_ID)["population"],
        reserve,
        plan["pit_rate"],
        plan["cit_rate"],
        plan["shares"],
        revenue_basis=_general_tax_basis(session,country.PANSTWO_ID),
            share=period_share(year, period),
            imf_due=imf_due,
    )

    financial_period = _get_period(
        session,
        country.PANSTWO_ID,
        year,
        period,
        captured_real_time,
    )

    if account is None:
        account = StateFinancialAccount(
            panstwo_id=country.PANSTWO_ID,
            reserve_balance=ZERO,
            last_transaction_sequence=0,
            created_at=captured_real_time,
            updated_at=captured_real_time,
        )
        session.add(account)
        session.flush()

    if previous is None:
        approval_mode = "FIRST"
    elif automatic:
        approval_mode = "AUTO_REPEAT"
    elif repeat_previous:
        approval_mode = "MANUAL_REPEAT"
    else:
        approval_mode = "MANUAL_NEW"

    budget = StateBudget(
        financial_period_id=financial_period.id,
        panstwo_id=country.PANSTWO_ID,
        game_year=year,
        period=period,
        previous_budget_id=previous.id if previous else None,
        opening_reserve=calculation["opening_reserve"],
        tax_total=calculation["tax_total"],
        budget_total=calculation["budget_total"],
        imf_collection=calculation["imf_collection"],
        expenditure_total=calculation["expenditure_total"],
        closing_reserve=calculation["closing_reserve"],
        approval_mode=approval_mode,
        automatic_reason=automatic_reason,
        approved_by_user_id=user_id,
        approved_at=captured_real_time,
        approved_game_date=captured_game_time,
        calculation_version=CALCULATION_VERSION,
    )

    session.add(budget)
    session.flush()

    from game.general_tax import apply_tax_penalty
    penalty_result=apply_tax_penalty(session,country.PANSTWO_ID,calculation["revenue_basis"],calculation["pit_rate"],captured_real_time)

    session.add(
        StateTaxAssessment(
            budget_id=budget.id,
            panstwo_id=country.PANSTWO_ID,
            game_year=year,
            period=period,
            pit_rate=calculation["pit_rate"],
            cit_rate=calculation["cit_rate"],
            gdp_snapshot=calculation["gdp"],
            population_snapshot=calculation["population"],
            gdp_per_capita_snapshot=calculation["gdp_per_capita"],
            annual_pit=calculation["annual_pit"],
            annual_cit=calculation["annual_cit"],
            half_year_pit=calculation["half_year_pit"],
            half_year_cit=calculation["half_year_cit"],
            total_amount=calculation["tax_total"],
            basis_captured_at=captured_real_time,
            basis_game_datetime=captured_game_time,
            assessed_at=captured_real_time,
            assessed_game_datetime=captured_game_time,
            general_tax_basis={'basis':calculation['revenue_basis'],'components':calculation['revenue_components'],'tax_penalty':penalty_result},
            calculation_version=CALCULATION_VERSION,
        )
    )

    for code in CATEGORY_CODES:
        session.add(
            StateBudgetAllocation(
                budget_id=budget.id,
                category_code=code,
                share_percent=calculation["shares"][code],
                amount=calculation["allocations"][code],
            )
        )

    from game.social_benefits import record_payments
    record_payments(session,budget,previous,calculation["allocations"]["social_policy"],benefits,repeat_previous)
    from game.crime_funding import record_funding
    record_funding(session,budget,previous,calculation["allocations"]["security_services"],crime_funding,repeat_previous)

    _post_transaction(
        session, account, budget,
        "TAX_GENERAL", "CREDIT",
        calculation["half_year_pit"],
        captured_real_time, captured_game_time,
    )

    # 18 Nov 2026: odsetki MFW (5% za cykl) naliczane przy zatwierdzeniu budżetu — przed ewentualnym pobraniem zaległości
    # (due_amount liczył już dług z odsetkami za ten cykl).
    from game.imf import accrue_interest
    accrue_interest(session, country.PANSTWO_ID, (year, period))

    if calculation["imf_collection"] > 0:
        _post_transaction(
            session, account, budget,
            "IMF_COLLECTION", "DEBIT",
            calculation["imf_collection"],
            captured_real_time, captured_game_time,
        )
        from game.imf import record_collection
        record_collection(session, country.PANSTWO_ID, budget, calculation["imf_collection"], captured_game_time)

    for code in EXPENDITURE_CODES:
        _post_transaction(
            session, account, budget,
            "BUDGET_ALLOCATION", "DEBIT",
            calculation["allocations"][code],
            captured_real_time, captured_game_time,
            category_code=code,
        )

    if account.reserve_balance != calculation["closing_reserve"]:
        raise FinanceError("Saldo końcowe nie odpowiada rezerwie.")

    account.last_budget_id = budget.id
    account.updated_at = captured_real_time

    financial_period.status = "APPROVED"
    financial_period.resolved_at = captured_real_time
    financial_period.last_attempt_at = captured_real_time
    financial_period.last_error = None

    session.flush()

    return {
        "budget_id": budget.id,
        "already_approved": False,
    }


def approve_manual_budget(
    user_id,
    *,
    year,
    period,
    expected_basis,
    repeat_previous=False,
    pit_rate=None,
    cit_rate=None,
    shares=None,
    benefits=None,
    crime_funding=None,
):
    """Publiczna operacja ręcznego zatwierdzenia.

    Osobna sesja zapewnia, że commit nie zapisze przypadkowych zmian
    zgromadzonych wcześniej w flaskowym db.session.
    """

    period_bounds(year, period)

    with Session(db.engine, expire_on_commit=False) as session:
        with session.begin():
            country = _country_for_user(
                session,
                user_id,
                lock=True,
            )

            result = approve_in_transaction(
                session,
                country,
                year,
                period,
                user_id=user_id,
                repeat_previous=repeat_previous,
                pit_rate=pit_rate,
                cit_rate=cit_rate,
                shares=shares,
                expected_basis=expected_basis,
                benefits=benefits,
                crime_funding=crime_funding,
            )

        return result