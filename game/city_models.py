"""Obiekty miejskie — etap 1 (administrator, 21 Nov 2026), logika w game.cities.

- `CityBuilding` — obiekt postawiony na kratce (0–63) siatki 8×8 miasta. Budowa trwa od `starts_at` do `ready_at`
  (czas gry); obiekt działa (efekty, utrzymanie), gdy `ready_at <= teraz` i `removed_at IS NULL`. Likwidacja przez
  gracza (`removal_reason='demolished'`, zwrot 25% kosztu budowy). Brak środków na utrzymanie: do 21 Nov 2026 likwidacja
  (`'unfunded'`), od 21 Nov 2026 status „Niedofinansowany” (`underfunded_at`) — obiekt zostaje, nie daje efektów
  i odzyskuje finansowanie przy kolejnym zatwierdzeniu budżetu, jeśli wystarczy środków.
- `CityExpense` — ruchy pieniężne obiektów miejskich w budżecie okresu: budowa ('build'), utrzymanie przy zatwierdzeniu
  budżetu ('maintenance') i zwrot przy likwidacji ('refund', kwota ujemna). `amount` obciąża sektor `sector`,
  `reserve_amount` — rezerwę budżetową (game.budget_transfers.sector_balances).
- `CityEffectState` — efekty obiektów faktycznie dodane do wskaźników społecznych państwa (spoleczenstwo); przy każdej
  zmianie dodawana jest tylko różnica, więc efekty zlikwidowanych obiektów są odejmowane.
"""
from extensions import db
from game.models import utc_now


class CityBuilding(db.Model):
    __tablename__ = 'game_city_buildings'
    id = db.Column(db.Integer, primary_key=True)
    panstwo_id = db.Column(db.Integer, db.ForeignKey('panstwa.PANSTWO_ID'), nullable=False, index=True)
    miasto_id = db.Column(db.Integer, db.ForeignKey('miasta.miasto_id'), nullable=False, index=True)
    kind = db.Column(db.String(16), nullable=False)
    cell = db.Column(db.SmallInteger, nullable=False)
    cost = db.Column(db.Numeric(30, 2), nullable=False)            # koszt budowy (ROI)
    maintenance = db.Column(db.Numeric(30, 2), nullable=False)     # roczny koszt utrzymania (ROI)
    sector = db.Column(db.String(32), nullable=False)              # sektor budżetu finansujący budowę i utrzymanie
    starts_at = db.Column(db.DateTime, nullable=False)
    ready_at = db.Column(db.DateTime, nullable=False, index=True)
    completed_notified = db.Column(db.Boolean, nullable=False, default=False, server_default=db.text('0'))
    removed_at = db.Column(db.DateTime)
    removal_reason = db.Column(db.String(16))
    underfunded_at = db.Column(db.DateTime)   # 21 Nov 2026: „Niedofinansowany” — obiekt istnieje, ale nie daje efektów
    user_id = db.Column(db.Integer, db.ForeignKey('game_users.id'))
    request_id = db.Column(db.String(36), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    __table_args__ = (db.UniqueConstraint('panstwo_id', 'request_id', name='uq_city_building_request'),
                      db.Index('ix_city_building_city_cell', 'miasto_id', 'cell'),
                      db.CheckConstraint('cell BETWEEN 0 AND 63 AND cost >= 0 AND maintenance >= 0 AND ready_at > starts_at', name='ck_city_building_values'),
                      db.CheckConstraint("kind IN ('clinic','hospital','nursery','school','university','tram','bus','metro','monument')", name='ck_city_building_kind'),
                      db.CheckConstraint("removal_reason IS NULL OR removal_reason IN ('demolished','unfunded','lost')", name='ck_city_building_removal'),
                      {'mysql_engine': 'InnoDB'})


class CityExpense(db.Model):
    __tablename__ = 'game_city_expenses'
    id = db.Column(db.Integer, primary_key=True)
    panstwo_id = db.Column(db.Integer, db.ForeignKey('panstwa.PANSTWO_ID'), nullable=False, index=True)
    budget_id = db.Column(db.BigInteger, db.ForeignKey('game_state_budgets.id'), nullable=False, index=True)
    building_id = db.Column(db.Integer, db.ForeignKey('game_city_buildings.id'))
    kind = db.Column(db.String(16), nullable=False)
    sector = db.Column(db.String(32), nullable=False)
    amount = db.Column(db.Numeric(30, 2), nullable=False)          # część z budżetu sektora (zwrot: ujemna)
    reserve_amount = db.Column(db.Numeric(30, 2), nullable=False, default=0, server_default=db.text('0'))
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    __table_args__ = (db.CheckConstraint("kind IN ('build','maintenance','refund')", name='ck_city_expense_kind'),
                      db.CheckConstraint('reserve_amount >= 0', name='ck_city_expense_reserve'),
                      {'mysql_engine': 'InnoDB'})


class CityEffectState(db.Model):
    __tablename__ = 'game_city_effects'
    panstwo_id = db.Column(db.Integer, db.ForeignKey('panstwa.PANSTWO_ID'), primary_key=True)
    applied = db.Column(db.JSON, nullable=False)                   # {pole spoleczenstwo: dodana wartość}
    updated_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    __table_args__ = ({'mysql_engine': 'InnoDB'},)
