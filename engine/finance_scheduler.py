"""Koordynator okresów budżetowych ZEUS.

Import modułu nie uruchamia schedulera.

Uruchomienie następuje dopiero po jawnym wywołaniu
start_finance_scheduler(app).
"""

import os
import socket
import uuid
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from extensions import db
from game.models import GamePlayerCountry
from models import Panstwo

from game.finance_models import (
    FinanceSchedulerState,
    FinancialNotification,
    StateFinancialAccount,
    StateFinancialPeriod,
)

from game.finance_service import (
    FinanceError,
    ZERO,
    _get_period,
    _previous_budget,
    _reserve_for_account,
    approve_in_transaction,
    game_now,
    period_key,
)


JOB_KEY = "state_finance"
HEARTBEAT_SECONDS = 60
RECOVERY_SECONDS = 300
LEASE_SECONDS = 120


class CoordinatorLost(FinanceError):
    """Proces utracił prawo wykonywania zadania finansowego."""


def database_now(session):
    return session.scalar(select(func.utc_timestamp(6)))


def next_period(key):
    # 13 Nov 2026: półrocza do 1 października 3001, potem kwartały (game.finance_service.next_period_key)
    from game.finance_service import next_period_key
    return next_period_key(key)


def period_keys(first, last):
    key = first

    while key <= last:
        yield key
        key = next_period(key)


def coordinator_owner():
    return (
        f"{socket.gethostname()[:20]}:"
        f"{os.getpid()}:"
        f"{uuid.uuid4().hex[:16]}"
    )


def _claim_coordinator(owner):
    """Przejmuje lub odnawia dzierżawę.

    Sprawdzenie przerwy odbywa się przed nadpisaniem heartbeat.
    """

    with Session(db.engine, expire_on_commit=False) as session:
        with session.begin():
            state = session.scalar(
                select(FinanceSchedulerState)
                .where(FinanceSchedulerState.job_key == JOB_KEY)
                .with_for_update()
            )

            if state is None:
                raise FinanceError(
                    "Brak rekordu state_finance w "
                    "game_finance_scheduler_state."
                )

            if (
                state.heartbeat_interval_seconds != HEARTBEAT_SECONDS
                or state.recovery_threshold_seconds != RECOVERY_SECONDS
            ):
                raise FinanceError(
                    "Nieprawidłowa konfiguracja koordynatora finansów."
                )

            now = database_now(session)

            live_lease = (
                state.lease_expires_at is not None
                and state.lease_expires_at > now
            )

            if live_lease and state.coordinator_id != owner:
                return None

            first_start = state.service_started_at is None

            if (
                not first_start
                and (
                    state.service_started_game_datetime is None
                    or state.last_heartbeat_at is None
                )
            ):
                raise FinanceError(
                    "Niekompletny stan uruchomionego koordynatora."
                )

            interrupted_recovery = state.recovery_status in (
                "RUNNING",
                "FAILED",
            )

            long_pause = (
                not first_start
                and now - state.last_heartbeat_at
                > timedelta(seconds=RECOVERY_SECONDS)
            )

            recovery = interrupted_recovery or long_pause

            if first_start:
                if state.recovery_status != "IDLE":
                    raise FinanceError(
                        "Nieprawidłowy stan pierwszego uruchomienia."
                    )

                state.service_started_at = now
                state.service_started_game_datetime = game_now()

                # Brak poprzedniego heartbeat oznacza pierwsze
                # uruchomienie, a nie awarię.
                recovery = False

            if state.coordinator_id != owner or not live_lease:
                state.fencing_token += 1

            if recovery:
                if not interrupted_recovery:
                    state.recovery_id = uuid.uuid4().hex
                    state.recovery_started_at = now

                state.recovery_status = "RUNNING"
                state.recovery_completed_at = None

            state.coordinator_id = owner
            state.last_heartbeat_at = now
            state.lease_expires_at = now + timedelta(
                seconds=LEASE_SECONDS
            )

            return {
                "token": state.fencing_token,
                "recovery": recovery,
                "service_start": state.service_started_game_datetime,
            }


def _heartbeat(session, owner, token):
    """Blokada koordynatora obowiązuje do końca transakcji."""

    state = session.scalar(
        select(FinanceSchedulerState)
        .where(FinanceSchedulerState.job_key == JOB_KEY)
        .with_for_update()
    )

    now = database_now(session)

    if (
        state is None
        or state.coordinator_id != owner
        or state.fencing_token != token
        or state.lease_expires_at is None
        or state.lease_expires_at <= now
    ):
        raise CoordinatorLost(
            "Proces utracił dzierżawę koordynatora finansów."
        )

    state.last_heartbeat_at = now
    state.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)

    return state


def _country_ids():
    with Session(db.engine) as session:
        return list(
            session.scalars(
                select(GamePlayerCountry.panstwo_id)
                .order_by(GamePlayerCountry.panstwo_id)
            ).all()
        )


def _first_period(country_id, service_start, current):
    """Nie tworzy fikcyjnych okresów sprzed rozpoczęcia gry.

    Państwo bez zapisanych okresów zaczyna od bieżącego półrocza.
    """

    with Session(db.engine) as session:
        row = session.scalar(
            select(StateFinancialPeriod)
            .where(StateFinancialPeriod.panstwo_id == country_id)
            .order_by(
                StateFinancialPeriod.game_year,
                StateFinancialPeriod.period,
            )
            .limit(1)
        )

        if row is None:
            return current

        first = max(
            (row.game_year, row.period),
            period_key(service_start),
        )

        if first > current:
            raise FinanceError(
                f"Państwo {country_id} ma okres z przyszłości."
            )

        return first


def _skip_period(
    session,
    financial_period,
    assignment,
    previous,
    reason,
    now,
):
    account = session.scalar(
        select(StateFinancialAccount)
        .where(
            StateFinancialAccount.panstwo_id
            == financial_period.panstwo_id
        )
        .with_for_update()
    )

    reserve = _reserve_for_account(account, previous)

    financial_period.status = "SKIPPED"
    financial_period.skip_reason = reason
    financial_period.reserve_at_skip = reserve
    financial_period.resolved_at = now
    financial_period.last_attempt_at = now
    financial_period.last_error = None

    if reason == "SYSTEM_DOWNTIME":
        financial_period.skip_details = (
            "Przerwa w działaniu koordynatora ponad 300 sekund. "
            "Półrocze zakończyło się przed odzyskaniem obsługi. "
            "Nie naliczono podatków ani nowych wydatków. "
            "Zachowano istniejącą rezerwę."
        )

        notification = session.scalar(
            select(FinancialNotification).where(
                FinancialNotification.financial_period_id
                == financial_period.id,
                FinancialNotification.user_id == assignment.user_id,
                FinancialNotification.notification_type
                == "PERIOD_SKIPPED_DOWNTIME",
            )
        )

        if notification is None:
            session.add(
                FinancialNotification(
                    financial_period_id=financial_period.id,
                    user_id=assignment.user_id,
                    notification_type="PERIOD_SKIPPED_DOWNTIME",
                    created_at=now,
                )
            )
    else:
        financial_period.skip_details = (
            "Półrocze zakończyło się bez pierwszego "
            "samodzielnie zatwierdzonego planu budżetowego."
        )

    from game.social_benefits import record_missed_period
    record_missed_period(session,financial_period.panstwo_id,financial_period.game_year,financial_period.period)

    # Pominięcie nie zmienia rachunku i nie tworzy operacji.
    if reserve < ZERO:
        raise FinanceError("Nieprawidłowa rezerwa państwa.")


def _process_period(
    session,
    country_id,
    year,
    half,
    current,
    recovery,
):
    assignment = session.scalar(
        select(GamePlayerCountry)
        .where(GamePlayerCountry.panstwo_id == country_id)
        .with_for_update()
    )

    if assignment is None:
        return

    country = session.scalar(
        select(Panstwo)
        .where(Panstwo.PANSTWO_ID == country_id)
        .with_for_update()
    )

    if country is None:
        raise FinanceError(
            f"Brak państwa przypisanego graczowi: {country_id}."
        )

    existing = session.scalar(
        select(StateFinancialPeriod)
        .where(
            StateFinancialPeriod.panstwo_id == country_id,
            StateFinancialPeriod.game_year == year,
            StateFinancialPeriod.period == half,
        )
        .with_for_update()
    )

    if existing is not None and existing.status in (
        "APPROVED",
        "SKIPPED",
    ):
        return

    now = database_now(session)

    financial_period = _get_period(
        session,
        country_id,
        year,
        half,
        now,
    )

    previous = _previous_budget(
        session,
        country_id,
        year,
        half,
    )

    key = (year, half)
    expired = key < current

    if expired:
        if previous is None:
            _skip_period(
                session,
                financial_period,
                assignment,
                previous,
                "NO_PREVIOUS_PLAN",
                now,
            )
            return

        if recovery:
            _skip_period(
                session,
                financial_period,
                assignment,
                previous,
                "SYSTEM_DOWNTIME",
                now,
            )
            return

        # Normalne zamknięcie albo krótki restart:
        # jedna transza za właśnie zakończony okres.
        approve_in_transaction(
            session,
            country,
            year,
            half,
            user_id=None,
            repeat_previous=True,
            automatic_reason="PERIOD_CLOSE",
        )
        return

    if recovery and previous is not None:
        # Szczególna reguła odzyskiwania:
        # bieżące półrocze rozliczamy teraz, nawet jeśli nadal trwa.
        approve_in_transaction(
            session,
            country,
            year,
            half,
            user_id=None,
            repeat_previous=True,
            automatic_reason="STARTUP_RECOVERY",
        )

    # Przy zwykłym przebiegu bieżący okres pozostaje PENDING.
    # Bez poprzedniego planu zawsze czekamy na pierwszy budżet gracza.


def _complete_tick(owner, token, target_game_time, recovery):
    with Session(db.engine) as session:
        with session.begin():
            state = _heartbeat(session, owner, token)
            now = database_now(session)

            state.last_success_at = now
            state.last_success_game_datetime = target_game_time
            state.last_error = None

            if recovery:
                state.recovery_status = "COMPLETED"
                state.recovery_completed_at = now


def _record_failure(owner, token, recovery, error):
    with Session(db.engine) as session:
        with session.begin():
            state = session.scalar(
                select(FinanceSchedulerState)
                .where(FinanceSchedulerState.job_key == JOB_KEY)
                .with_for_update()
            )

            if (
                state is None
                or state.coordinator_id != owner
                or state.fencing_token != token
            ):
                return

            state.last_error = (
                f"{type(error).__name__}: {error}"
            )[:4000]

            if recovery:
                state.recovery_status = "FAILED"
                state.recovery_completed_at = None


def run_finance_tick(app, owner):
    """Jeden przebieg zadania.

    Każda zakończona transakcja jest trwała. Ponowienie pomija już
    rozliczone okresy, więc awaria nie powiela księgowania.
    """

    with app.app_context():
        claim = None

        try:
            claim = _claim_coordinator(owner)

            if claim is None:
                return

            token = claim["token"]
            recovery = claim["recovery"]
            target_game_time = game_now()
            from game.infrastructure_service import complete_due
            with Session(db.engine) as infrastructure_session, infrastructure_session.begin():
                complete_due(infrastructure_session, target_game_time)
            current = period_key(target_game_time)

            for country_id in _country_ids():
                first = _first_period(
                    country_id,
                    claim["service_start"],
                    current,
                )

                for year, half in period_keys(first, current):
                    with Session(
                        db.engine,
                        expire_on_commit=False,
                    ) as session:
                        with session.begin():
                            # Token jest sprawdzany w tej samej
                            # transakcji co księgowanie.
                            _heartbeat(session, owner, token)

                            _process_period(
                                session,
                                country_id,
                                year,
                                half,
                                current,
                                recovery,
                            )

                            # Odnowienie także po zakończeniu pracy.
                            _heartbeat(session, owner, token)

            from game.social_benefits import settle_years
            for country_id in _country_ids():
                with Session(db.engine) as session, session.begin():
                    _heartbeat(session,owner,token)
                    settle_years(session,country_id,target_game_time.year)

            # 16 Nov 2026: rozliczenie finansowania walki z przestępczością (tydzień Entendy przed kolejnym budżetem).
            from game.crime_funding import settle_due as settle_crime
            with Session(db.engine) as session, session.begin():
                _heartbeat(session,owner,token)
                settle_crime(session,target_game_time)

            _complete_tick(
                owner,
                token,
                target_game_time,
                recovery,
            )

        except CoordinatorLost:
            app.logger.warning(
                "Finanse: proces utracił koordynację."
            )

        except Exception as error:
            app.logger.exception(
                "Finanse: nieudany przebieg koordynatora."
            )

            if claim is not None:
                try:
                    _record_failure(
                        owner,
                        claim["token"],
                        claim["recovery"],
                        error,
                    )
                except Exception:
                    app.logger.exception(
                        "Finanse: nie udało się zapisać błędu."
                    )


def start_finance_scheduler(app):
    """Uruchamiane jawnie podczas późniejszej integracji aplikacji."""

    existing = app.extensions.get("game_finance_scheduler")

    if existing is not None:
        return existing

    owner = coordinator_owner()

    scheduler = BackgroundScheduler(timezone="UTC")

    scheduler.add_job(
        run_finance_tick,
        trigger="interval",
        seconds=HEARTBEAT_SECONDS,
        args=[app, owner],
        id="game_state_finance_tick",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
        next_run_time=datetime.now(timezone.utc),
    )

    app.extensions["game_finance_scheduler"] = scheduler

    try:
        scheduler.start()
    except Exception:
        app.extensions.pop("game_finance_scheduler", None)
        raise

    return scheduler