"""Radary (technologia „Rozpoznanie radarowe”, UAT, 11 Nov 2026)."""
from extensions import db
from game.models import utc_now


class Radar(db.Model):
    __tablename__ = 'game_radars'
    id = db.Column(db.Integer, primary_key=True)
    panstwo_id = db.Column(db.Integer, db.ForeignKey('panstwa.PANSTWO_ID'), nullable=False, index=True)
    region_id = db.Column(db.Integer, db.ForeignKey('regiony.region_id'), nullable=False, index=True)
    map_x = db.Column(db.Double, nullable=False)
    map_y = db.Column(db.Double, nullable=False)
    level = db.Column(db.Integer, nullable=False, default=1)
    health = db.Column(db.Integer, nullable=False, default=100, server_default=db.text('100'))
    request_id = db.Column(db.String(36), nullable=False)
    created_game_at = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    __table_args__ = (db.UniqueConstraint('panstwo_id', 'request_id', name='uq_radar_request'),
                      db.CheckConstraint('level BETWEEN 1 AND 3', name='ck_radar_level'),
                      db.CheckConstraint('health BETWEEN 0 AND 100', name='ck_radar_health'),
                      {'mysql_engine': 'InnoDB'})


class RadarExpense(db.Model):
    """Koszt budowy i rozbudowy radaru (budżet sił zbrojnych)."""
    __tablename__ = 'game_radar_expenses'
    id = db.Column(db.Integer, primary_key=True)
    panstwo_id = db.Column(db.Integer, nullable=False, index=True)
    budget_id = db.Column(db.BigInteger, db.ForeignKey('game_state_budgets.id'), nullable=False, index=True)
    radar_id = db.Column(db.Integer, db.ForeignKey('game_radars.id', ondelete='SET NULL'), nullable=True)
    level = db.Column(db.Integer, nullable=False)
    amount = db.Column(db.Numeric(30, 2), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    __table_args__ = (db.CheckConstraint('amount >= 0', name='ck_radar_expense'), {'mysql_engine': 'InnoDB'})


class RadarDetection(db.Model):
    """Jedno powiadomienie o wykryciu lotu dla jednego państwa."""
    __tablename__ = 'game_radar_detections'
    id = db.Column(db.Integer, primary_key=True)
    panstwo_id = db.Column(db.Integer, nullable=False, index=True)
    flight_id = db.Column(db.Integer, db.ForeignKey('game_military_flights.id', ondelete='CASCADE'), nullable=False)
    radar_id = db.Column(db.Integer, db.ForeignKey('game_radars.id', ondelete='SET NULL'), nullable=True)
    detected_at = db.Column(db.DateTime, nullable=False)                    # czas Entendy wejścia w zasięg
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    __table_args__ = (db.UniqueConstraint('panstwo_id', 'flight_id', name='uq_radar_detection'), {'mysql_engine': 'InnoDB'})
