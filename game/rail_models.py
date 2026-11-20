"""Kolej (19 Nov 2026): linie kolejowe między miastami i wydatki na ich budowę.

Linia łączy dwa miasta (`city_a_id` — miasto inicjatora, `city_b_id` — miasto docelowe, własne albo bezpośredniego
sąsiada). Linia krajowa startuje od razu (status ACTIVE); linia międzynarodowa czeka na zgodę sąsiada na współfinansowanie
(PENDING → ACTIVE albo REJECTED / CANCELLED). Linia ACTIVE jest ukończona, gdy minie `ready_at` (czas gry).
"""
from extensions import db
from game.models import utc_now

STATUSES = ('PENDING', 'ACTIVE', 'REJECTED', 'CANCELLED')


class RailLine(db.Model):
    __tablename__ = 'game_rail_lines'
    id = db.Column(db.Integer, primary_key=True)
    initiator_id = db.Column(db.Integer, db.ForeignKey('panstwa.PANSTWO_ID'), nullable=False, index=True)
    partner_id = db.Column(db.Integer, db.ForeignKey('panstwa.PANSTWO_ID'), index=True)
    city_a_id = db.Column(db.Integer, nullable=False, index=True)
    city_b_id = db.Column(db.Integer, nullable=False, index=True)
    path = db.Column(db.JSON, nullable=False)
    distance_km = db.Column(db.Numeric(16, 3), nullable=False)
    cost = db.Column(db.Numeric(30, 2), nullable=False)
    shares = db.Column(db.JSON, nullable=False)          # {"<państwo>": {"countryId", "distanceKm", "cost"}}
    build_days = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(16), nullable=False)
    starts_at = db.Column(db.DateTime)                   # czas gry rozpoczęcia budowy
    ready_at = db.Column(db.DateTime)                    # czas gry ukończenia
    user_id = db.Column(db.Integer, db.ForeignKey('game_users.id'))
    request_id = db.Column(db.String(36), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    resolved_at = db.Column(db.DateTime)
    __table_args__ = (db.UniqueConstraint('initiator_id', 'request_id', name='uq_rail_line_request'),
                      db.CheckConstraint("status IN ('PENDING','ACTIVE','REJECTED','CANCELLED') AND distance_km > 0 AND cost >= 0 "
                                         "AND build_days >= 1 AND city_a_id <> city_b_id", name='ck_rail_line_values'),
                      {'mysql_engine': 'InnoDB'})


class RailExpense(db.Model):
    """Udział państwa w koszcie linii, pobrany z budżetu infrastruktury (game.budget_transfers.infrastructure_balance)."""
    __tablename__ = 'game_rail_expenses'
    id = db.Column(db.Integer, primary_key=True)
    line_id = db.Column(db.Integer, db.ForeignKey('game_rail_lines.id'), nullable=False, index=True)
    panstwo_id = db.Column(db.Integer, db.ForeignKey('panstwa.PANSTWO_ID'), nullable=False, index=True)
    budget_id = db.Column(db.BigInteger, db.ForeignKey('game_state_budgets.id'), nullable=False, index=True)
    amount = db.Column(db.Numeric(30, 2), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    __table_args__ = (db.UniqueConstraint('line_id', 'panstwo_id', name='uq_rail_expense_line_country'),
                      db.CheckConstraint('amount >= 0', name='ck_rail_expense_amount'), {'mysql_engine': 'InnoDB'})
