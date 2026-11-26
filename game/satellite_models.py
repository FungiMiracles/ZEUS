"""Satelity szpiegowskie na orbicie i ich misje rozpoznawcze (26 Nov 2026, game.satellites).

Satelity wyprodukowane, a jeszcze niewyniesione, leżą w magazynie państwa (game_resource_stocks: spy_satellites).
"""
from extensions import db
from game.models import utc_now


class SpySatellite(db.Model):
    """Satelita wyniesiony na orbitę. Ruch po mapie to odcinek (from → to) w czasie gry (seg_start → seg_end):
    dryf w losowym kierunku (100 km/h Entendy) albo przelot nad państwo celu misji (500 km/h Entendy)."""
    __tablename__ = 'game_spy_satellites'
    id = db.Column(db.Integer, primary_key=True)
    panstwo_id = db.Column(db.Integer, db.ForeignKey('panstwa.PANSTWO_ID'), nullable=False, index=True)
    base_id = db.Column(db.Integer, db.ForeignKey('game_military_bases.id', ondelete='SET NULL'), nullable=True)
    status = db.Column(db.String(16), nullable=False, default='launching', server_default='launching')
    mode = db.Column(db.String(16), nullable=False, default='drift', server_default='drift')
    mission_id = db.Column(db.Integer, nullable=True)
    launched_at = db.Column(db.DateTime, nullable=False)       # czas gry rozpoczęcia wynoszenia
    orbit_at = db.Column(db.DateTime, nullable=False)          # czas gry osiągnięcia orbity (minuta czasu rzeczywistego)
    from_x = db.Column(db.Double, nullable=False)
    from_y = db.Column(db.Double, nullable=False)
    to_x = db.Column(db.Double, nullable=False)
    to_y = db.Column(db.Double, nullable=False)
    seg_start = db.Column(db.DateTime, nullable=False)
    seg_end = db.Column(db.DateTime, nullable=False)
    request_id = db.Column(db.String(36), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    __table_args__ = (db.UniqueConstraint('panstwo_id', 'request_id', name='uq_spy_satellite_request'),
                      db.CheckConstraint("status IN ('launching','orbit','lost')", name='ck_spy_satellite_status'),
                      db.CheckConstraint("mode IN ('drift','mission')", name='ck_spy_satellite_mode'),
                      db.CheckConstraint('seg_end >= seg_start', name='ck_spy_satellite_segment'),
                      {'mysql_engine': 'InnoDB'})


class SatelliteMission(db.Model):
    """Misja satelity nad wybranym państwem: rozpoznanie obiektów danego rodzaju na całym jego terytorium."""
    __tablename__ = 'game_satellite_missions'
    id = db.Column(db.Integer, primary_key=True)
    panstwo_id = db.Column(db.Integer, db.ForeignKey('panstwa.PANSTWO_ID'), nullable=False, index=True)
    satellite_id = db.Column(db.Integer, db.ForeignKey('game_spy_satellites.id', ondelete='CASCADE'), nullable=False, index=True)
    kind = db.Column(db.String(16), nullable=False)
    target_country_id = db.Column(db.Integer, nullable=False)
    target_name = db.Column(db.String(255), nullable=False)
    cost = db.Column(db.Numeric(30, 2), nullable=False)
    starts_at = db.Column(db.DateTime, nullable=False)
    arrives_at = db.Column(db.DateTime, nullable=False, index=True)
    completed_at = db.Column(db.DateTime)
    report = db.Column(db.JSON)
    notification_id = db.Column(db.Integer, db.ForeignKey('game_notifications.id', ondelete='SET NULL'), nullable=True)
    request_id = db.Column(db.String(36), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    __table_args__ = (db.UniqueConstraint('panstwo_id', 'request_id', name='uq_satellite_mission_request'),
                      db.CheckConstraint("kind IN ('bases','defenses','mines','power','silos')", name='ck_satellite_mission_kind'),
                      db.CheckConstraint('arrives_at >= starts_at', name='ck_satellite_mission_time'),
                      {'mysql_engine': 'InnoDB'})
