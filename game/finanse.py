"""Trasy modułu finansów państwa.

Import modułu nie rejestruje tras i nie uruchamia schedulera.
Rejestracja nastąpi później przez init_finance_routes(app).
"""

import hmac
from datetime import date, datetime
from decimal import Decimal

from flask import (
    Blueprint,
    current_app,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session as browser_session,
    url_for,
)
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from extensions import db
from game.country_summary import country_summary as _country_summary
from game.models import GamePlayerCountry, GameUser
from models import Panstwo

from game.finance_models import (
    BudgetCategory,
    FinancialNotification,
    StateBudget,
    StateBudgetAllocation,
    StateFinancialPeriod,
    StateTaxAssessment,
)

from game.finance_service import (
    CATEGORY_CODES,
    FinanceConflict,
    FinanceError,
    FinancePermissionError,
    approve_manual_budget,
    preview_budget,
    utc_now,
)


finance_bp = Blueprint(
    "game_finance",
    __name__,
    url_prefix="/game/finanse",
)


def json_safe(value):
    """Kwoty przekazujemy jako tekst, bez konwersji na float."""

    if isinstance(value, Decimal):
        return format(value, "f")

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, dict):
        return {
            key: json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]

    return value


def _json_response(data, status=200):
    return jsonify(json_safe(data)), status


def _request_data():
    if not request.is_json:
        raise FinanceError("Oczekiwano danych w formacie JSON.")

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        raise FinanceError("Nieprawidłowe dane formularza.")

    return data


def _repeat_flag(data):
    value = data.get("repeat_previous", False)

    if not isinstance(value, bool):
        raise FinanceError(
            "repeat_previous musi mieć wartość true albo false."
        )

    return value


def _notice_data(notification, financial_period):
    from game.finance_service import period_label
    label = period_label(financial_period.game_year, financial_period.period)

    message = (
        "Z powodu przerwy w działaniu systemu ZEUS nie przeprowadzono "
        f"rozliczenia budżetu za {label}. "
        "Okres został pominięty. Nie naliczono za niego wpływów "
        "podatkowych ani nowych wydatków. Zachowano dotychczasową "
        "rezerwę budżetową."
    )

    return {
        "id": notification.id,
        "year": financial_period.game_year,
        "period": financial_period.period,
        "message": message,
        "created_at": notification.created_at,
        "displayed_at": notification.displayed_at,
    }


def _unseen_notifications(database_session, user_id):
    rows = database_session.execute(
        select(FinancialNotification, StateFinancialPeriod)
        .join(
            StateFinancialPeriod,
            StateFinancialPeriod.id
            == FinancialNotification.financial_period_id,
        )
        .where(
            FinancialNotification.user_id == user_id,
            FinancialNotification.displayed_at.is_(None),
        )
        .order_by(
            FinancialNotification.created_at,
            FinancialNotification.id,
        )
    ).all()

    return [
        _notice_data(notification, financial_period)
        for notification, financial_period in rows
    ]


def _approved_details(database_session, budget_id, country_id):
    budget = database_session.scalar(
        select(StateBudget).where(
            StateBudget.id == budget_id,
            StateBudget.panstwo_id == country_id,
        )
    )

    if budget is None:
        raise FinanceError("Nie znaleziono zatwierdzonego budżetu.")

    assessment = database_session.scalar(
        select(StateTaxAssessment).where(
            StateTaxAssessment.budget_id == budget.id
        )
    )

    allocations = database_session.scalars(
        select(StateBudgetAllocation).where(
            StateBudgetAllocation.budget_id == budget.id
        )
    ).all()

    from game.budget_categories import complete,normalize
    if assessment is None or not complete(allocations):
        raise FinanceError("Historia budżetu ma niekompletne dane.")

    from game.budget_transfers import sector_balances,public_trust,TRANSFER_TRUST_THRESHOLD,defensive_war
    from game.finance_service import game_now,period_key
    balances=sector_balances(database_session,budget)
    trust=public_trust(database_session,budget.panstwo_id)
    from game.social_benefits import details
    from game.crime_funding import details as crime_details
    return {
        "benefits":details(database_session,budget),
        "crime":crime_details(database_session,budget),
        "balances":balances,
        "revenue_basis":(assessment.general_tax_basis or {}).get("basis"),
        "revenue_components":(assessment.general_tax_basis or {}).get("components"),
        "tax_penalty":(assessment.general_tax_basis or {}).get("tax_penalty",{}).get("penalty",0),
        "can_transfer":(budget.game_year,budget.period)==period_key(game_now()),
        # Sector-to-sector transfers need public trust above the threshold; the reserve is not affected (10 Nov 2026).
        "public_trust":trust,"transfer_trust_threshold":TRANSFER_TRUST_THRESHOLD,
        "sector_transfers_allowed":True,   # 21 Nov 2026: próg zaufania zniesiony
        # 17 Nov 2026: w wojnie obronnej przesunięcia do sił zbrojnych nie wymagają progu zaufania.
        "defense_transfers_allowed":defensive_war(database_session,budget.panstwo_id) if (budget.game_year,budget.period)==period_key(game_now()) else False,
        "approved": True,
        "budget_id": budget.id,
        "year": budget.game_year,
        "period": budget.period,
        "approval_mode": budget.approval_mode,
        "automatic_reason": budget.automatic_reason,
        "approved_at": budget.approved_at,
        "approved_game_date": budget.approved_game_date,
        "gdp": assessment.gdp_snapshot,
        "population": assessment.population_snapshot,
        "gdp_per_capita": assessment.gdp_per_capita_snapshot,
        "pit_rate": assessment.pit_rate,
        "cit_rate": assessment.cit_rate,
        "annual_pit": assessment.annual_pit+assessment.annual_cit,
        "annual_cit": assessment.annual_cit,
        "half_year_pit": assessment.half_year_pit+assessment.half_year_cit,
        "half_year_cit": assessment.half_year_cit,
        "tax_total": budget.tax_total,
        "opening_reserve": budget.opening_reserve,
        "budget_total": budget.budget_total,
        "imf_collection": getattr(budget, "imf_collection", 0) or 0,
        "rail_income": getattr(budget, "rail_income", 0) or 0,
        "air_income": getattr(budget, "air_income", 0) or 0,
        "expenditure_total": budget.expenditure_total,
        "closing_reserve": budget.closing_reserve,
        "shares": normalize((row.category_code,row.share_percent) for row in allocations),
        "allocations": normalize((row.category_code,row.amount) for row in allocations),
    }


@finance_bp.before_request
def require_finance_user():
    user_id = browser_session.get("game_user_id")

    if (
        not isinstance(user_id, int)
        or isinstance(user_id, bool)
        or user_id <= 0
    ):
        if request.endpoint == "game_finance.page":
            return redirect(url_for("wejscie"))

        return _json_response(
            {"ok": False, "error": "Zaloguj się ponownie."},
            401,
        )

    with Session(db.engine) as database_session:
        user = database_session.get(GameUser, user_id)

        if user is None or not user.is_active:
            raise FinancePermissionError(
                "Konto nie istnieje albo jest nieaktywne."
            )

        from game.finance_service import _country_for_user
        country=_country_for_user(database_session,user_id)
        g.finance_user_id=user.id
        g.finance_country_id=country.PANSTWO_ID

    if request.method == "POST":
        expected = browser_session.get("game_csrf_token")
        provided = request.headers.get("X-CSRF-Token", "")

        if (
            not isinstance(expected, str)
            or not expected
            or not hmac.compare_digest(
                expected.encode("utf-8"),
                provided.encode("utf-8"),
            )
        ):
            return _json_response(
                {
                    "ok": False,
                    "error": (
                        "Sesja formularza wygasła. "
                        "Odśwież stronę i spróbuj ponownie."
                    ),
                },
                403,
            )


@finance_bp.after_request
def prevent_finance_caching(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@finance_bp.errorhandler(FinanceError)
def handle_finance_error(error):
    if isinstance(error, FinancePermissionError):
        status = 403
    elif isinstance(error, FinanceConflict):
        status = 409
    else:
        status = 400

    return _json_response(
        {"ok": False, "error": str(error)},
        status,
    )


@finance_bp.errorhandler(SQLAlchemyError)
def handle_database_error(error):
    current_app.logger.exception(
        "Błąd bazy danych w module finansów."
    )

    return _json_response(
        {
            "ok": False,
            "error": (
                "Nie udało się wykonać operacji finansowej. "
                "Odśwież stronę, aby sprawdzić stan budżetu."
            ),
        },
        500,
    )


@finance_bp.get("")
def page():
    finance_state = None
    finance_error = None

    try:
        finance_state = preview_budget(g.finance_user_id)
    except FinanceError as error:
        finance_error = str(error)

    with Session(db.engine) as database_session:
        user = database_session.get(
            GameUser,
            g.finance_user_id,
        )

        country = database_session.get(
            Panstwo,
            g.finance_country_id,
        )

        if user is None or country is None:
            raise FinancePermissionError(
                "Nie znaleziono użytkownika lub państwa."
            )

        if finance_state and finance_state.get("approved"):
            finance_state = _approved_details(
                database_session,
                finance_state["budget_id"],
                country.PANSTWO_ID,
            )

        categories = [
            {
                "code": row.code,
                "name": "Badania i rozwój" if row.code=="research" else row.name_pl,
                "is_reserve": row.is_reserve,
            }
            for row in database_session.scalars(
                select(BudgetCategory).where(BudgetCategory.code.in_(CATEGORY_CODES))
                .order_by(BudgetCategory.display_order)
            ).all()
        ]

        history_rows = database_session.execute(
            select(StateFinancialPeriod, StateBudget)
            .outerjoin(
                StateBudget,
                StateBudget.financial_period_id
                == StateFinancialPeriod.id,
            )
            .where(
                StateFinancialPeriod.panstwo_id == country.PANSTWO_ID
            )
            .order_by(
                StateFinancialPeriod.game_year.desc(),
                StateFinancialPeriod.period.desc(),
            )
        ).all()

        history = [
            {
                "year": financial_period.game_year,
                "period": financial_period.period,
                "status": financial_period.status,
                "skip_reason": financial_period.skip_reason,
                "skip_details": financial_period.skip_details,
                "budget_id": budget.id if budget else None,
                "approval_mode": budget.approval_mode if budget else None,
                "tax_total": budget.tax_total if budget else None,
                "opening_reserve": (
                    budget.opening_reserve if budget else None
                ),
                "closing_reserve": (
                    budget.closing_reserve if budget else None
                ),
            }
            for financial_period, budget in history_rows
        ]

        notifications = _unseen_notifications(
            database_session,
            user.id,
        )

        from game.civic_models import CountryTaxPolicy
        policy=database_session.get(CountryTaxPolicy,country.PANSTWO_ID)
        context = {
            "finance_tax_policy":{'pit_rate':str(policy.pit_rate),'cit_rate':str(policy.cit_rate)} if policy else None,
            "game_user": {"id": user.id, "username": user.username},
            "game_country": _country_summary(country),
            "game_home_url": url_for("game_main_page"),
            "game_logout_url": url_for("game_logout"),
            "game_active_page": "finance",
            "finance_state": json_safe(finance_state),
            "finance_error": finance_error,
            "finance_categories": categories,
            "finance_history": json_safe(history),
            "finance_notifications": json_safe(notifications),
            "city_upkeep": _city_upkeep(database_session, country.PANSTWO_ID),
        }

    return render_template(
        "game/finanse.html",
        **context,
    )


def _city_upkeep(database_session, country_id):
    """21 Nov 2026: roczne utrzymanie obiektów miejskich (edukacja, ochrona zdrowia, komunikacja miejska) i jego część
    w bieżącym okresie budżetowym — game.cities.upkeep_summary."""
    try:
        from game.cities import tables_ready, upkeep_summary
        if not tables_ready(database_session):
            return None
        return upkeep_summary(database_session, country_id)
    except Exception:
        current_app.logger.exception("Miasta: utrzymanie na ekranie budżetu")
        return None


@finance_bp.post("/podglad")
def preview():
    data = _request_data()

    result = preview_budget(
        g.finance_user_id,
        pit_rate=data.get("pit_rate"),
        cit_rate=0,
        shares=data.get("shares"),
        repeat_previous=_repeat_flag(data),
    )

    return _json_response({
        "ok": True,
        "state": result,
    })


@finance_bp.post("/zatwierdz")
def approve():
    data = _request_data()

    year = data.get("year")
    period = data.get("period")

    if (
        not isinstance(year, int)
        or isinstance(year, bool)
        or not isinstance(period, int)
        or isinstance(period, bool)
    ):
        raise FinanceError("Nieprawidłowy rok lub okres budżetowy.")

    basis_token = data.get("basis_token")

    if not isinstance(basis_token, str) or len(basis_token) != 64:
        raise FinanceError(
            "Brak aktualnego podglądu. Przelicz budżet ponownie."
        )

    result = approve_manual_budget(
        g.finance_user_id,
        year=year,
        period=period,
        expected_basis=basis_token,
        benefits=data.get("benefits"),
        crime_funding=data.get("crime_funding"),
        repeat_previous=_repeat_flag(data),
        pit_rate=data.get("pit_rate"),
        cit_rate=0,
        shares=data.get("shares"),
    )

    return _json_response({
        "ok": True,
        "budget_id": result["budget_id"],
        "already_approved": result["already_approved"],
        "redirect_url": url_for("game_main_page"),
    })


@finance_bp.get("/historia/<int:budget_id>")
def budget_history(budget_id):
    with Session(db.engine) as database_session:
        result = _approved_details(
            database_session,
            budget_id,
            g.finance_country_id,
        )

    return _json_response({
        "ok": True,
        "state": result,
    })


@finance_bp.get("/powiadomienia")
def notifications():
    with Session(db.engine) as database_session:
        rows = _unseen_notifications(
            database_session,
            g.finance_user_id,
        )

    return _json_response({
        "ok": True,
        "notifications": rows,
    })


@finance_bp.post("/powiadomienia/<int:notification_id>/wyswietlono")
def notification_displayed(notification_id):
    with Session(db.engine) as database_session:
        with database_session.begin():
            notification = database_session.scalar(
                select(FinancialNotification)
                .where(
                    FinancialNotification.id == notification_id,
                    FinancialNotification.user_id == g.finance_user_id,
                )
                .with_for_update()
            )

            if notification is None:
                return _json_response(
                    {
                        "ok": False,
                        "error": "Nie znaleziono powiadomienia.",
                    },
                    404,
                )

            if notification.displayed_at is None:
                notification.displayed_at = max(
                    utc_now(),
                    notification.created_at,
                )

    return _json_response({"ok": True})


def init_finance_routes(app):
    app.register_blueprint(finance_bp)

def build_panel_finance_context(user_id):
    """Dane modala i powiadomień dla głównego panelu gry."""

    finance_state = None
    finance_error = None

    try:
        finance_state = preview_budget(user_id)
    except FinancePermissionError:
        raise
    except FinanceError as error:
        finance_error = str(error)

    with Session(db.engine) as database_session:
        categories = [
            {
                "code": row.code,
                "name": "Badania i rozwój" if row.code=="research" else row.name_pl,
                "is_reserve": row.is_reserve,
            }
            for row in database_session.scalars(
                select(BudgetCategory).where(BudgetCategory.code.in_(CATEGORY_CODES))
                .order_by(BudgetCategory.display_order)
            ).all()
        ]

        notifications = _unseen_notifications(
            database_session,
            user_id,
        )

    return {
        "finance_state": json_safe(finance_state),
        "finance_error": finance_error,
        "finance_required": (
            finance_state is None
            or not finance_state.get("approved", False)
        ),
        "finance_categories": categories,
        "finance_notifications": json_safe(notifications),
    }

@finance_bp.post('/przesun')
def transfer():
    from game.budget_transfers import transfer_funds
    budget_id=transfer_funds(g.finance_user_id,_request_data())
    with Session(db.engine) as database_session:
        state=_approved_details(database_session,budget_id,g.finance_country_id)
    return _json_response({'ok':True,'state':state})
