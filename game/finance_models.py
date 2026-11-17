"""Modele finansów państwa.

Zgodne ze schematem entenda_uat_db przekazanym w SHOW CREATE TABLE.

Ten moduł wyłącznie deklaruje modele.
Nie tworzy tabel, nie wykonuje migracji i nie zapisuje danych.
"""

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
)
from sqlalchemy.dialects.mysql import DATETIME, VARCHAR

from extensions import db


def ascii_string(length):
    return VARCHAR(
        length,
        charset="ascii",
        collation="ascii_bin",
    )


class BudgetCategory(db.Model):
    __tablename__ = "game_budget_categories"

    code = db.Column(ascii_string(48), primary_key=True)
    name_pl = db.Column(db.String(120), nullable=False)
    display_order = db.Column(db.SmallInteger, nullable=False)
    is_reserve = db.Column(
        db.Boolean,
        nullable=False,
        server_default=db.text("0"),
    )

    __table_args__ = (
        UniqueConstraint(
            "display_order",
            name="uq_gbc_display_order",
        ),
        CheckConstraint(
            "display_order BETWEEN 1 AND 64",
            name="ck_gbc_display_order",
        ),
        CheckConstraint(
            "(code = 'reserve' AND is_reserve = 1) OR "
            "(code <> 'reserve' AND is_reserve = 0)",
            name="ck_gbc_reserve",
        ),
    )


class StateFinancialPeriod(db.Model):
    __tablename__ = "game_state_financial_periods"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    panstwo_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "panstwa.PANSTWO_ID",
            name="fk_gsfp_country",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        nullable=False,
    )

    game_year = db.Column(db.Integer, nullable=False)
    period = db.Column(db.SmallInteger, nullable=False)

    starts_at_game = db.Column(DATETIME(), nullable=False)
    ends_at_game = db.Column(DATETIME(), nullable=False)

    status = db.Column(
        ascii_string(16),
        nullable=False,
        server_default=db.text("'PENDING'"),
    )

    skip_reason = db.Column(ascii_string(32))
    skip_details = db.Column(db.Text)
    reserve_at_skip = db.Column(db.Numeric(30, 2))

    created_at = db.Column(DATETIME(fsp=6), nullable=False)
    resolved_at = db.Column(DATETIME(fsp=6))

    last_attempt_at = db.Column(DATETIME(fsp=6))
    last_error = db.Column(db.Text)

    __table_args__ = (
        UniqueConstraint(
            "panstwo_id",
            "game_year",
            "period",
            name="uq_gsfp_country_period",
        ),
        UniqueConstraint(
            "id",
            "panstwo_id",
            "game_year",
            "period",
            name="uq_gsfp_identity",
        ),
        Index(
            "ix_gsfp_pending",
            "status",
            "ends_at_game",
        ),
        CheckConstraint(
            "game_year BETWEEN 1 AND 9998",
            name="ck_gsfp_year",
        ),
        # 13 Nov 2026: półrocza (1–2) do 1 października 3001, potem kwartały (1–4); granice okresów liczy
        # game.finance_service.period_bounds — w bazie tylko spójność dat.
        CheckConstraint(
            "period IN (1, 2, 3, 4)",
            name="ck_gsfp_period",
        ),
        CheckConstraint(
            "ends_at_game > starts_at_game",
            name="ck_gsfp_dates",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'APPROVED', 'SKIPPED')",
            name="ck_gsfp_status",
        ),
        CheckConstraint(
            """
            (
                status = 'PENDING'
                AND resolved_at IS NULL
                AND skip_reason IS NULL
                AND skip_details IS NULL
                AND reserve_at_skip IS NULL
            )
            OR
            (
                status = 'APPROVED'
                AND resolved_at IS NOT NULL
                AND skip_reason IS NULL
                AND skip_details IS NULL
                AND reserve_at_skip IS NULL
            )
            OR
            (
                status = 'SKIPPED'
                AND resolved_at IS NOT NULL
                AND skip_reason IN (
                    'SYSTEM_DOWNTIME',
                    'NO_PREVIOUS_PLAN'
                )
                AND skip_details IS NOT NULL
                AND reserve_at_skip IS NOT NULL
                AND reserve_at_skip >= 0
            )
            """,
            name="ck_gsfp_resolution",
        ),
    )


class StateBudget(db.Model):
    __tablename__ = "game_state_budgets"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    financial_period_id = db.Column(db.BigInteger, nullable=False)
    panstwo_id = db.Column(db.Integer, nullable=False)
    game_year = db.Column(db.Integer, nullable=False)
    period = db.Column(db.SmallInteger, nullable=False)

    previous_budget_id = db.Column(db.BigInteger)

    opening_reserve = db.Column(db.Numeric(30, 2), nullable=False)
    tax_total = db.Column(db.Numeric(30, 2), nullable=False)
    budget_total = db.Column(db.Numeric(30, 2), nullable=False)
    expenditure_total = db.Column(db.Numeric(30, 2), nullable=False)
    closing_reserve = db.Column(db.Numeric(30, 2), nullable=False)

    approval_mode = db.Column(ascii_string(20), nullable=False)
    automatic_reason = db.Column(ascii_string(24))

    approved_by_user_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "game_users.id",
            name="fk_gsb_approver",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
    )

    approved_at = db.Column(DATETIME(fsp=6), nullable=False)
    approved_game_date = db.Column(DATETIME(fsp=6), nullable=False)

    calculation_version = db.Column(
        db.SmallInteger,
        nullable=False,
        server_default=db.text("1"),
    )

    __table_args__ = (
        UniqueConstraint(
            "financial_period_id",
            name="uq_gsb_financial_period",
        ),
        UniqueConstraint(
            "panstwo_id",
            "game_year",
            "period",
            name="uq_gsb_country_period",
        ),
        UniqueConstraint(
            "id",
            "panstwo_id",
            "game_year",
            "period",
            name="uq_gsb_identity",
        ),
        UniqueConstraint(
            "id",
            "panstwo_id",
            name="uq_gsb_country_identity",
        ),
        Index(
            "ix_gsb_country_history",
            "panstwo_id",
            "game_year",
            "period",
        ),
        ForeignKeyConstraint(
            [
                "financial_period_id",
                "panstwo_id",
                "game_year",
                "period",
            ],
            [
                "game_state_financial_periods.id",
                "game_state_financial_periods.panstwo_id",
                "game_state_financial_periods.game_year",
                "game_state_financial_periods.period",
            ],
            name="fk_gsb_period",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["previous_budget_id", "panstwo_id"],
            [
                "game_state_budgets.id",
                "game_state_budgets.panstwo_id",
            ],
            name="fk_gsb_previous",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        CheckConstraint(
            """
            opening_reserve >= 0
            AND tax_total >= 0
            AND budget_total >= 0
            AND expenditure_total >= 0
            AND closing_reserve >= 0
            """,
            name="ck_gsb_amounts",
        ),
        CheckConstraint(
            """
            budget_total = opening_reserve + tax_total
            AND budget_total = expenditure_total + closing_reserve
            """,
            name="ck_gsb_balance",
        ),
        CheckConstraint(
            """
            approval_mode IN (
                'FIRST',
                'MANUAL_NEW',
                'MANUAL_REPEAT',
                'AUTO_REPEAT'
            )
            """,
            name="ck_gsb_mode",
        ),
        CheckConstraint(
            """
            (
                approval_mode = 'AUTO_REPEAT'
                AND approved_by_user_id IS NULL
                AND automatic_reason IS NOT NULL
                AND automatic_reason IN (
                    'PERIOD_CLOSE',
                    'STARTUP_RECOVERY'
                )
            )
            OR
            (
                approval_mode IN (
                    'FIRST',
                    'MANUAL_NEW',
                    'MANUAL_REPEAT'
                )
                AND approved_by_user_id IS NOT NULL
                AND automatic_reason IS NULL
            )
            """,
            name="ck_gsb_approval_source",
        ),
        CheckConstraint(
            """
            (
                approval_mode = 'FIRST'
                AND previous_budget_id IS NULL
            )
            OR
            (
                approval_mode <> 'FIRST'
                AND previous_budget_id IS NOT NULL
            )
            """,
            name="ck_gsb_previous_plan",
        ),
        CheckConstraint(
            "calculation_version >= 1",
            name="ck_gsb_calculation_version",
        ),
    )


class StateTaxAssessment(db.Model):
    __tablename__ = "game_state_tax_assessments"
    general_tax_basis=db.Column(db.JSON,nullable=True)

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    budget_id = db.Column(db.BigInteger, nullable=False)
    panstwo_id = db.Column(db.Integer, nullable=False)
    game_year = db.Column(db.Integer, nullable=False)
    period = db.Column(db.SmallInteger, nullable=False)

    pit_rate = db.Column(db.Numeric(5, 2), nullable=False)
    cit_rate = db.Column(db.Numeric(5, 2), nullable=False)

    gdp_snapshot = db.Column(db.Numeric(30, 2), nullable=False)
    population_snapshot = db.Column(db.BigInteger, nullable=False)
    gdp_per_capita_snapshot = db.Column(
        db.Numeric(38, 12),
        nullable=False,
    )

    annual_pit = db.Column(db.Numeric(38, 8), nullable=False)
    annual_cit = db.Column(db.Numeric(38, 8), nullable=False)

    half_year_pit = db.Column(db.Numeric(30, 2), nullable=False)
    half_year_cit = db.Column(db.Numeric(30, 2), nullable=False)
    total_amount = db.Column(db.Numeric(30, 2), nullable=False)

    basis_captured_at = db.Column(DATETIME(fsp=6), nullable=False)
    basis_game_datetime = db.Column(DATETIME(fsp=6), nullable=False)

    assessed_at = db.Column(DATETIME(fsp=6), nullable=False)
    assessed_game_datetime = db.Column(DATETIME(fsp=6), nullable=False)

    calculation_version = db.Column(
        db.SmallInteger,
        nullable=False,
        server_default=db.text("1"),
    )

    __table_args__ = (
        UniqueConstraint(
            "budget_id",
            name="uq_gsta_budget",
        ),
        UniqueConstraint(
            "panstwo_id",
            "game_year",
            "period",
            name="uq_gsta_country_period",
        ),
        ForeignKeyConstraint(
            ["budget_id", "panstwo_id", "game_year", "period"],
            [
                "game_state_budgets.id",
                "game_state_budgets.panstwo_id",
                "game_state_budgets.game_year",
                "game_state_budgets.period",
            ],
            name="fk_gsta_budget",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        CheckConstraint(
            """
            pit_rate BETWEEN 0 AND 100
            AND cit_rate BETWEEN 0 AND 100
            """,
            name="ck_gsta_rates",
        ),
        CheckConstraint(
            """
            gdp_snapshot >= 0
            AND population_snapshot > 0
            AND gdp_per_capita_snapshot >= 0
            """,
            name="ck_gsta_basis",
        ),
        CheckConstraint(
            """
            annual_pit >= 0
            AND annual_cit >= 0
            AND ((calculation_version < 4
                  AND annual_pit = gdp_snapshot * pit_rate / 200
                  AND annual_cit = gdp_snapshot * cit_rate / 200)
                 OR (calculation_version >= 4 AND cit_rate = 0
                     AND annual_cit = 0 AND general_tax_basis IS NOT NULL))
            """,
            name="ck_gsta_annual_amounts",
        ),
        CheckConstraint(
            """
            (((game_year > 3001 OR (game_year = 3001 AND period = 4))
              AND half_year_pit = ROUND(annual_pit / 4, 2)
              AND half_year_cit = ROUND(annual_cit / 4, 2))
             OR (NOT (game_year > 3001 OR (game_year = 3001 AND period = 4))
              AND half_year_pit = ROUND(annual_pit / 2, 2)
              AND half_year_cit = ROUND(annual_cit / 2, 2)))
            AND total_amount = half_year_pit + half_year_cit
            """,
            name="ck_gsta_half_year_amounts",
        ),
        CheckConstraint(
            "calculation_version >= 1",
            name="ck_gsta_calculation_version",
        ),
    )


class StateBudgetAllocation(db.Model):
    __tablename__ = "game_state_budget_allocations"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    budget_id = db.Column(
        db.BigInteger,
        db.ForeignKey(
            "game_state_budgets.id",
            name="fk_gsba_budget",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        nullable=False,
    )

    category_code = db.Column(
        ascii_string(48),
        db.ForeignKey(
            "game_budget_categories.code",
            name="fk_gsba_category",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        nullable=False,
    )

    share_percent = db.Column(db.Numeric(5, 2), nullable=False)
    amount = db.Column(db.Numeric(30, 2), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "budget_id",
            "category_code",
            name="uq_gsba_budget_category",
        ),
        CheckConstraint(
            "share_percent BETWEEN 0 AND 100",
            name="ck_gsba_share",
        ),
        CheckConstraint(
            "amount >= 0",
            name="ck_gsba_amount",
        ),
    )


class StateFinancialAccount(db.Model):
    __tablename__ = "game_state_financial_accounts"

    panstwo_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "panstwa.PANSTWO_ID",
            name="fk_gsfa_country",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        primary_key=True,
        autoincrement=False,
    )

    reserve_balance = db.Column(
        db.Numeric(30, 2),
        nullable=False,
        server_default=db.text("0"),
    )

    last_budget_id = db.Column(db.BigInteger)

    last_transaction_sequence = db.Column(
        db.BigInteger,
        nullable=False,
        server_default=db.text("0"),
    )

    created_at = db.Column(DATETIME(fsp=6), nullable=False)
    updated_at = db.Column(DATETIME(fsp=6), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["last_budget_id", "panstwo_id"],
            [
                "game_state_budgets.id",
                "game_state_budgets.panstwo_id",
            ],
            name="fk_gsfa_last_budget",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        CheckConstraint(
            "reserve_balance >= 0",
            name="ck_gsfa_balance",
        ),
        CheckConstraint(
            "last_transaction_sequence >= 0",
            name="ck_gsfa_sequence",
        ),
    )


class StateFinancialTransaction(db.Model):
    __tablename__ = "game_state_financial_transactions"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    panstwo_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "game_state_financial_accounts.panstwo_id",
            name="fk_gsft_account",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        nullable=False,
    )

    budget_id = db.Column(db.BigInteger, nullable=False)

    operation_key = db.Column(ascii_string(128), nullable=False)
    sequence_number = db.Column(db.BigInteger, nullable=False)

    operation_type = db.Column(ascii_string(24), nullable=False)
    direction = db.Column(ascii_string(8), nullable=False)

    category_code = db.Column(
        ascii_string(48),
        db.ForeignKey(
            "game_budget_categories.code",
            name="fk_gsft_category",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
    )

    amount = db.Column(db.Numeric(30, 2), nullable=False)
    balance_before = db.Column(db.Numeric(30, 2), nullable=False)
    balance_after = db.Column(db.Numeric(30, 2), nullable=False)

    created_at = db.Column(DATETIME(fsp=6), nullable=False)
    game_datetime = db.Column(DATETIME(fsp=6), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "operation_key",
            name="uq_gsft_operation_key",
        ),
        UniqueConstraint(
            "panstwo_id",
            "sequence_number",
            name="uq_gsft_country_sequence",
        ),
        Index(
            "ix_gsft_budget",
            "budget_id",
        ),
        ForeignKeyConstraint(
            ["budget_id", "panstwo_id"],
            [
                "game_state_budgets.id",
                "game_state_budgets.panstwo_id",
            ],
            name="fk_gsft_budget",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        CheckConstraint(
            "sequence_number > 0",
            name="ck_gsft_sequence",
        ),
        CheckConstraint(
            """
            amount >= 0
            AND balance_before >= 0
            AND balance_after >= 0
            """,
            name="ck_gsft_amounts",
        ),
        CheckConstraint(
            """
            (
                operation_type IN ('TAX_PIT', 'TAX_CIT', 'TAX_GENERAL')
                AND direction = 'CREDIT'
                AND category_code IS NULL
            )
            OR
            (
                operation_type = 'BUDGET_ALLOCATION'
                AND direction = 'DEBIT'
                AND category_code IS NOT NULL
                AND category_code <> 'reserve'
            )
            """,
            name="ck_gsft_operation",
        ),
        CheckConstraint(
            """
            (
                direction = 'CREDIT'
                AND balance_after = balance_before + amount
            )
            OR
            (
                direction = 'DEBIT'
                AND balance_after = balance_before - amount
            )
            """,
            name="ck_gsft_balance",
        ),
    )


class FinancialNotification(db.Model):
    __tablename__ = "game_financial_notifications"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    financial_period_id = db.Column(
        db.BigInteger,
        db.ForeignKey(
            "game_state_financial_periods.id",
            name="fk_gfn_period",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        nullable=False,
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "game_users.id",
            name="fk_gfn_user",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        nullable=False,
    )

    notification_type = db.Column(ascii_string(32), nullable=False)

    created_at = db.Column(DATETIME(fsp=6), nullable=False)
    displayed_at = db.Column(DATETIME(fsp=6))

    __table_args__ = (
        UniqueConstraint(
            "financial_period_id",
            "user_id",
            "notification_type",
            name="uq_gfn_period_user_type",
        ),
        Index(
            "ix_gfn_user_unseen",
            "user_id",
            "displayed_at",
            "created_at",
        ),
        CheckConstraint(
            "notification_type = 'PERIOD_SKIPPED_DOWNTIME'",
            name="ck_gfn_type",
        ),
        CheckConstraint(
            "displayed_at IS NULL OR displayed_at >= created_at",
            name="ck_gfn_displayed_at",
        ),
    )


class FinanceSchedulerState(db.Model):
    __tablename__ = "game_finance_scheduler_state"

    job_key = db.Column(ascii_string(64), primary_key=True)

    heartbeat_interval_seconds = db.Column(
        db.Integer,
        nullable=False,
        server_default=db.text("60"),
    )

    recovery_threshold_seconds = db.Column(
        db.Integer,
        nullable=False,
        server_default=db.text("300"),
    )

    coordinator_id = db.Column(ascii_string(64))
    lease_expires_at = db.Column(DATETIME(fsp=6))

    fencing_token = db.Column(
        db.BigInteger,
        nullable=False,
        server_default=db.text("0"),
    )

    last_heartbeat_at = db.Column(DATETIME(fsp=6))
    last_success_at = db.Column(DATETIME(fsp=6))
    last_success_game_datetime = db.Column(DATETIME(fsp=6))

    service_started_at = db.Column(DATETIME(fsp=6))
    service_started_game_datetime = db.Column(DATETIME(fsp=6))

    recovery_status = db.Column(
        ascii_string(16),
        nullable=False,
        server_default=db.text("'IDLE'"),
    )

    recovery_id = db.Column(ascii_string(64))
    recovery_started_at = db.Column(DATETIME(fsp=6))
    recovery_completed_at = db.Column(DATETIME(fsp=6))

    last_error = db.Column(db.Text)

    __table_args__ = (
        CheckConstraint(
            "heartbeat_interval_seconds = 60",
            name="ck_gfss_heartbeat",
        ),
        CheckConstraint(
            "recovery_threshold_seconds = 300",
            name="ck_gfss_recovery_threshold",
        ),
        CheckConstraint(
            "fencing_token >= 0",
            name="ck_gfss_fencing",
        ),
        CheckConstraint(
            """
            (
                coordinator_id IS NULL
                AND lease_expires_at IS NULL
            )
            OR
            (
                coordinator_id IS NOT NULL
                AND lease_expires_at IS NOT NULL
            )
            """,
            name="ck_gfss_lease",
        ),
        CheckConstraint(
            """
            recovery_status IN (
                'IDLE',
                'RUNNING',
                'COMPLETED',
                'FAILED'
            )
            """,
            name="ck_gfss_recovery_status",
        ),
        CheckConstraint(
            """
            (
                recovery_status = 'IDLE'
                AND recovery_id IS NULL
                AND recovery_started_at IS NULL
                AND recovery_completed_at IS NULL
            )
            OR
            (
                recovery_status IN ('RUNNING', 'FAILED')
                AND recovery_id IS NOT NULL
                AND recovery_started_at IS NOT NULL
                AND recovery_completed_at IS NULL
            )
            OR
            (
                recovery_status = 'COMPLETED'
                AND recovery_id IS NOT NULL
                AND recovery_started_at IS NOT NULL
                AND recovery_completed_at IS NOT NULL
                AND recovery_completed_at >= recovery_started_at
            )
            """,
            name="ck_gfss_recovery_identity",
        ),
    )

class BudgetTransfer(db.Model):
    """Przesunięcia uzupełniają zatwierdzony plan, bez zmieniania jego historii."""
    __tablename__ = 'game_budget_transfers'
    id = db.Column(db.Integer, primary_key=True)
    budget_id = db.Column(db.BigInteger, db.ForeignKey('game_state_budgets.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('game_users.id'), nullable=False)
    source = db.Column(db.String(48), nullable=False)
    destination = db.Column(db.String(48), nullable=False)
    amount = db.Column(db.Numeric(30,2), nullable=False)
    request_id = db.Column(db.String(36), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False)
    game_datetime = db.Column(db.DateTime, nullable=False)
    __table_args__ = (UniqueConstraint('user_id','request_id',name='uq_budget_transfer_request'),
        CheckConstraint('amount > 0 AND source <> destination',name='ck_budget_transfer_amount'),{'mysql_engine':'InnoDB'})
