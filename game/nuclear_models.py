"""Tabele rakiet z głowicą nuklearną (13 Nov 2026): zamówienia produkcji i strefy skażenia."""
from extensions import db
from game.models import utc_now


class NuclearOrder(db.Model):
    """Zamówienie konkretnej liczby rakiet w fabryce (produkcja kolejno, po 14 dni Entendy na sztukę)."""
    __tablename__ = 'game_nuclear_orders'
    id = db.Column(db.Integer, primary_key=True)
    panstwo_id = db.Column(db.Integer, db.ForeignKey('panstwa.PANSTWO_ID'), nullable=False, index=True)
    factory_id = db.Column(db.Integer, db.ForeignKey('game_ammunition_factories.id', ondelete='SET NULL'), nullable=True, index=True)
    quantity = db.Column(db.Integer, nullable=False)
    produced = db.Column(db.Integer, nullable=False, default=0, server_default=db.text('0'))
    started_at = db.Column(db.DateTime, nullable=False)          # czas gry
    status = db.Column(db.String(16), nullable=False, default='active', server_default='active')
    materials = db.Column(db.JSON, nullable=False)                 # surowce na jedną rakietę (pobrane przy zamówieniu za całą partię)
    request_id = db.Column(db.String(36), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    __table_args__ = (db.UniqueConstraint('panstwo_id', 'request_id', name='uq_nuclear_order_request'),
                      db.CheckConstraint("status IN ('active','done','cancelled','stopped')", name='ck_nuclear_order_status'),
                      db.CheckConstraint('quantity > 0 AND produced >= 0 AND produced <= quantity', name='ck_nuclear_order_counts'),
                      {'mysql_engine': 'InnoDB'})


class NuclearZone(db.Model):
    """Strefa skażenia po uderzeniu atomowym: promień 100 km, zakaz budowy przez 3 lata Entendy."""
    __tablename__ = 'game_nuclear_zones'
    id = db.Column(db.Integer, primary_key=True)
    attacker_id = db.Column(db.Integer, nullable=False, index=True)
    target_country_id = db.Column(db.Integer, nullable=True)
    region_id = db.Column(db.Integer, nullable=True)
    flight_id = db.Column(db.Integer, nullable=True, unique=True)
    x = db.Column(db.Double, nullable=False)
    y = db.Column(db.Double, nullable=False)
    radius_km = db.Column(db.Integer, nullable=False)
    created_game_at = db.Column(db.DateTime, nullable=False)
    until = db.Column(db.DateTime, nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    __table_args__ = ({'mysql_engine': 'InnoDB'},)
