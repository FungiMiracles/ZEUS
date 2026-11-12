"""Kopia zdarzenia i skutków niezależna od retencji generatora."""
from extensions import db
from game.models import utc_now


class GeneratedEventSnapshot(db.Model):
    __tablename__ = "game_generated_event_snapshots"

    id = db.Column(db.Integer, primary_key=True)
    source_event_id = db.Column(db.Integer, nullable=False)
    country_id = db.Column(db.Integer, nullable=False)
    country_name = db.Column(db.String(255), nullable=False)
    region_name = db.Column(db.String(255), nullable=False)
    event_type = db.Column(db.String(64), nullable=False)
    content = db.Column(db.Text, nullable=False)
    effects = db.Column(db.JSON, nullable=False)
    entenda_date = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)

    __table_args__ = (
        db.UniqueConstraint("source_event_id", name="uq_generated_event_source"),
    )
