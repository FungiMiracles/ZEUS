"""Międzynarodowy Fundusz Walutowy (18 Nov 2026): roczna pula, pożyczki państw i ruchy środków.

Ruchy 'disbursement' (+) i 'repayment' (−) zmieniają rezerwę budżetową państwa poza budżetem — wchodzą do
niezgodności rezerwy liczonej w finance_service._reserve_for_account (jak pożyczki między państwami). Ruch
'collection' to przymusowe ściągnięcie długu przy zatwierdzeniu budżetu: jest częścią samego budżetu
(game_state_budgets.imf_collection i transakcja IMF_COLLECTION), więc do tej niezgodności nie wchodzi.
"""
from extensions import db
from game.models import utc_now


class ImfFundYear(db.Model):
    """Pula MFW na rok gry (10 bln ROI). `lent` — suma pożyczek wypłaconych w tym roku (spłaty puli nie odnawiają)."""
    __tablename__ = 'game_imf_fund_years'
    game_year = db.Column(db.Integer, primary_key=True, autoincrement=False)
    pool = db.Column(db.Numeric(30, 2), nullable=False)
    lent = db.Column(db.Numeric(30, 2), nullable=False, default=0)
    __table_args__ = (db.CheckConstraint('pool >= 0 AND lent >= 0 AND lent <= pool', name='ck_imf_fund_year'), {'mysql_engine': 'InnoDB'})


class ImfLoan(db.Model):
    """Wniosek o pożyczkę w MFW i — po pozytywnej decyzji — sama pożyczka.

    status: 'active' (dług do spłaty), 'repaid' (spłacona), 'rejected' (odmowa; amount = wnioskowana kwota, outstanding = 0).
    Termin: zatwierdzenie budżetu okresu (due_year, due_period) = 4 cykle budżetowe po okresie wypłaty.
    """
    __tablename__ = 'game_imf_loans'
    id = db.Column(db.Integer, primary_key=True)
    borrower_id = db.Column(db.Integer, db.ForeignKey('panstwa.PANSTWO_ID'), nullable=False, index=True)
    requested_by = db.Column(db.Integer, db.ForeignKey('game_users.id'))
    amount = db.Column(db.Numeric(30, 2), nullable=False)
    outstanding = db.Column(db.Numeric(30, 2), nullable=False, default=0)
    status = db.Column(db.String(16), nullable=False)
    reason = db.Column(db.String(400))
    pool_year = db.Column(db.Integer, nullable=False)
    start_year = db.Column(db.Integer, nullable=False)
    start_period = db.Column(db.SmallInteger, nullable=False)
    due_year = db.Column(db.Integer, nullable=False)
    due_period = db.Column(db.SmallInteger, nullable=False)
    capacity = db.Column(db.Numeric(30, 2), nullable=False, default=0)
    # 18 Nov 2026: odsetki — stopa za cykl budżetowy (pożyczki sprzed zmiany: 0), suma naliczonych odsetek i ostatni
    # okres naliczenia (odsetki naliczane przy zatwierdzeniu budżetu każdego kolejnego okresu, od pozostałego długu).
    interest_rate = db.Column(db.Numeric(6, 4), nullable=False, default=0, server_default='0')
    interest = db.Column(db.Numeric(30, 2), nullable=False, default=0, server_default='0')
    interest_year = db.Column(db.Integer)
    interest_period = db.Column(db.SmallInteger)
    request_id = db.Column(db.String(36), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    created_game_at = db.Column(db.DateTime, nullable=False)
    repaid_game_at = db.Column(db.DateTime)
    __table_args__ = (
        db.UniqueConstraint('borrower_id', 'request_id', name='uq_imf_loan_request'),
        db.CheckConstraint("amount > 0 AND outstanding >= 0 AND interest >= 0 AND interest_rate >= 0 AND outstanding <= amount + interest AND status IN ('active','repaid','rejected') "
                           "AND (status <> 'active' OR outstanding > 0) AND (status = 'active' OR outstanding = 0)", name='ck_imf_loan_values'),
        db.Index('ix_imf_loan_due', 'borrower_id', 'status', 'due_year', 'due_period'),
        {'mysql_engine': 'InnoDB'})


class ImfMovement(db.Model):
    __tablename__ = 'game_imf_movements'
    id = db.Column(db.Integer, primary_key=True)
    loan_id = db.Column(db.Integer, db.ForeignKey('game_imf_loans.id'), nullable=False, index=True)
    panstwo_id = db.Column(db.Integer, db.ForeignKey('panstwa.PANSTWO_ID'), nullable=False, index=True)
    budget_id = db.Column(db.BigInteger, db.ForeignKey('game_state_budgets.id'), index=True)
    stage = db.Column(db.String(16), nullable=False)
    amount = db.Column(db.Numeric(30, 2), nullable=False)
    request_id = db.Column(db.String(64), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    game_datetime = db.Column(db.DateTime, nullable=False)
    __table_args__ = (
        db.UniqueConstraint('loan_id', 'stage', 'request_id', name='uq_imf_movement'),
        db.CheckConstraint("(stage = 'disbursement' AND amount > 0) OR (stage IN ('repayment','collection') AND amount < 0)", name='ck_imf_movement'),
        {'mysql_engine': 'InnoDB'})
