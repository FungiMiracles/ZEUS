"""Historia przynależności regionów (23 Nov 2026) — podstawa wyzwalania regionów spod aneksji.

Każda zmiana państwa regionu w grze zapisuje wiersz: aneksja regionu (ANNEX), utrata suwerenności — region przechodzi
hurtem do anektującego (SOVEREIGNTY), przywrócenie regionu dawnemu państwu albo jego wskrzeszenie (RESTORE).
Dla danych sprzed migracji historię odtwarza migracja (migrations/sql/region_history_20261123.py) z zakończonych
okupacji regionów i z pierwotnej mapy regionów (static/maps/entenda_regiony.geojson).

„Dawny właściciel” regionu to państwo, od którego obecny właściciel przejął region w ostatniej zmianie.
"""
from sqlalchemy import select, inspect
from extensions import db
from game.models import utc_now

KINDS = ('ANNEX', 'SOVEREIGNTY', 'RESTORE')


class RegionTransfer(db.Model):
    __tablename__ = 'game_region_transfers'
    id = db.Column(db.Integer, primary_key=True)
    region_id = db.Column(db.Integer, db.ForeignKey('regiony.region_id'), nullable=False, index=True)
    from_country_id = db.Column(db.Integer, db.ForeignKey('panstwa.PANSTWO_ID'), nullable=False)
    to_country_id = db.Column(db.Integer, db.ForeignKey('panstwa.PANSTWO_ID'), nullable=False, index=True)
    kind = db.Column(db.String(12), nullable=False)
    occupation_id = db.Column(db.Integer, db.ForeignKey('game_occupations.id'), nullable=True)
    actor_country_id = db.Column(db.Integer, nullable=True)        # RESTORE: państwo, które wyzwoliło region
    details = db.Column(db.JSON)
    game_at = db.Column(db.DateTime, nullable=False)                # czas Entendy
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    __table_args__ = (db.CheckConstraint("kind IN ('ANNEX','SOVEREIGNTY','RESTORE')", name='ck_region_transfer_kind'),
                      {'mysql_engine': 'InnoDB'})


def ready(session):
    """Tabela istnieje (przed migracją region_history_20261123 historia nie jest zapisywana)."""
    try:
        return inspect(session.connection()).has_table(RegionTransfer.__tablename__)
    except Exception:
        return False


def record(session, region_id, source, target, kind, moment, occupation_id=None, actor=None, details=None):
    if source is None or target is None or source == target or not ready(session):
        return None
    row = RegionTransfer(region_id=region_id, from_country_id=source, to_country_id=target, kind=kind, occupation_id=occupation_id,
                         actor_country_id=actor, details=details, game_at=moment)
    session.add(row)
    session.flush()
    return row


def former_owner(session, region_id, holder):
    """Państwo, od którego `holder` przejął region (ostatnia zmiana przynależności); None — brak historii."""
    if not ready(session):
        return None
    row = session.scalar(select(RegionTransfer).where(RegionTransfer.region_id == region_id)
                         .order_by(RegionTransfer.game_at.desc(), RegionTransfer.id.desc()).limit(1))
    if row is None or row.to_country_id != holder or row.from_country_id == holder:
        return None
    return row.from_country_id


def update_details(session, region_id, details):
    """Uzupełnia szczegóły ostatniego wpisu historii regionu (np. archiwum utraty suwerenności przy wskrzeszeniu państwa)."""
    if not ready(session):
        return
    row = session.scalar(select(RegionTransfer).where(RegionTransfer.region_id == region_id)
                         .order_by(RegionTransfer.game_at.desc(), RegionTransfer.id.desc()).limit(1))
    if row is not None:
        row.details = {**(row.details or {}), **details}
        session.flush()
