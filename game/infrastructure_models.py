"""Trwałe zlecenia rozbudowy i ich źródła finansowania."""
from extensions import db


class InfrastructureProject(db.Model):
    __tablename__ = 'game_infrastructure_projects'
    id = db.Column(db.Integer, primary_key=True)
    panstwo_id = db.Column(db.Integer, nullable=False, index=True)
    region_id = db.Column(db.Integer, nullable=False, index=True)
    budget_id = db.Column(db.BigInteger, nullable=False, index=True)
    metric = db.Column(db.String(24), nullable=False)
    levels = db.Column(db.Integer, nullable=False)
    cost = db.Column(db.Numeric(30, 2), nullable=False)
    budget_spent = db.Column(db.Numeric(30, 2), nullable=False)
    reserve_spent = db.Column(db.Numeric(30, 2), nullable=False)
    starts_at = db.Column(db.DateTime, nullable=False)
    ends_at = db.Column(db.DateTime, nullable=False)
    completed_at = db.Column(db.DateTime)
    __table_args__ = (
        db.CheckConstraint('levels > 0 AND levels <= 100'),
        db.CheckConstraint("metric IN ('road', 'rail', 'energy', 'housing', 'port')"),
        db.CheckConstraint('ends_at > starts_at'),
        db.CheckConstraint('cost >= 0 AND budget_spent >= 0 AND reserve_spent >= 0 AND cost = budget_spent + reserve_spent'),
        {'mysql_engine': 'InnoDB'},
    )
