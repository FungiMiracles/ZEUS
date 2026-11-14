"""Wody terytorialne (UAT, 15 Nov 2026): wejścia obcych okrętów w wody terytorialne państwa."""
from extensions import db
from game.models import utc_now


class TerritorialIncursion(db.Model):
    """Jedno wejście okrętu w wody terytorialne obcego państwa (jedno powiadomienie, na razie bez konsekwencji)."""
    __tablename__ = 'game_territorial_incursions'
    id = db.Column(db.Integer, primary_key=True)
    vessel_id = db.Column(db.Integer, db.ForeignKey('game_military_vessels.id', ondelete='CASCADE'), nullable=False, index=True)
    vessel_country_id = db.Column(db.Integer, nullable=False, index=True)
    waters_country_id = db.Column(db.Integer, nullable=False, index=True)
    voyage_started_at = db.Column(db.DateTime, nullable=False)          # starts_at rejsu, w którym nastąpiło wejście
    entry_no = db.Column(db.Integer, nullable=False)                    # kolejne wejście w wody tego państwa w tym rejsie
    entered_at = db.Column(db.DateTime, nullable=False)                 # czas Entendy przekroczenia granicy wód
    point_x = db.Column(db.Double, nullable=False)
    point_y = db.Column(db.Double, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    __table_args__ = (db.UniqueConstraint('vessel_id', 'voyage_started_at', 'waters_country_id', 'entry_no', name='uq_territorial_incursion'),
                      {'mysql_engine': 'InnoDB'})
