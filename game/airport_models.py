"""Transport lotniczy (administrator, 20 Nov 2026): porty lotnicze w miastach, wydatki na ich budowę i zawieszone połączenia.

Lotnisko powstaje w mieście państwa (game.airports): budowa trwa 14 dni Entendy (`starts_at` → `ready_at`, czas gry).
Lotnisko z `ready_at <= teraz`, `health > 0` i bez `removed_at` jest czynne. Połączenia lotnicze tworzą się automatycznie
między wszystkimi czynnymi lotniskami świata; właściciel lotniska może czasowo zawiesić połączenie z wybranym lotniskiem
(wiersz w `game_air_route_suspensions`) — połączenie jest nieczynne, gdy zawiesi je którakolwiek strona.
Zniszczone lotnisko (życie 0 po ataku) dostaje `removed_at` — w tym mieście można zbudować nowe.
"""
from extensions import db
from game.models import utc_now


class Airport(db.Model):
    __tablename__ = 'game_airports'
    id = db.Column(db.Integer, primary_key=True)
    panstwo_id = db.Column(db.Integer, db.ForeignKey('panstwa.PANSTWO_ID'), nullable=False, index=True)
    miasto_id = db.Column(db.Integer, db.ForeignKey('miasta.miasto_id'), nullable=False, index=True)
    region_id = db.Column(db.Integer, nullable=False, index=True)
    name = db.Column(db.String(60), nullable=False)
    map_x = db.Column(db.Double, nullable=False)
    map_y = db.Column(db.Double, nullable=False)
    cost = db.Column(db.Numeric(30, 2), nullable=False)          # część pieniężna: ludność miasta × 100 ROI
    materials = db.Column(db.JSON, nullable=False)               # zużyte surowce i chipy {kod: ilość}
    health = db.Column(db.Integer, nullable=False, default=100, server_default=db.text('100'))
    starts_at = db.Column(db.DateTime, nullable=False)           # czas gry rozpoczęcia budowy
    ready_at = db.Column(db.DateTime, nullable=False, index=True)  # czas gry ukończenia
    removed_at = db.Column(db.DateTime)                          # zniszczenie (czas gry)
    renamed_at = db.Column(db.DateTime)                          # ostatnia zmiana nazwy (czas gry) — najwyżej raz na rok Entendy
    user_id = db.Column(db.Integer, db.ForeignKey('game_users.id'))
    request_id = db.Column(db.String(36), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    __table_args__ = (db.UniqueConstraint('panstwo_id', 'request_id', name='uq_airport_request'),
                      db.CheckConstraint('health BETWEEN 0 AND 100 AND cost >= 0 AND ready_at > starts_at', name='ck_airport_values'),
                      {'mysql_engine': 'InnoDB'})


class AirportExpense(db.Model):
    """Koszt pieniężny lotniska pobrany z budżetu infrastruktury (game.budget_transfers.infrastructure_balance)."""
    __tablename__ = 'game_airport_expenses'
    id = db.Column(db.Integer, primary_key=True)
    airport_id = db.Column(db.Integer, db.ForeignKey('game_airports.id'), nullable=False, unique=True)
    panstwo_id = db.Column(db.Integer, db.ForeignKey('panstwa.PANSTWO_ID'), nullable=False, index=True)
    budget_id = db.Column(db.BigInteger, db.ForeignKey('game_state_budgets.id'), nullable=False, index=True)
    amount = db.Column(db.Numeric(30, 2), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    __table_args__ = (db.CheckConstraint('amount >= 0', name='ck_airport_expense_amount'), {'mysql_engine': 'InnoDB'})


class AirRouteSuspension(db.Model):
    """Połączenie `airport_id` → `other_id` zawieszone przez właściciela `airport_id` (odwracalne — usunięcie wiersza)."""
    __tablename__ = 'game_air_route_suspensions'
    airport_id = db.Column(db.Integer, db.ForeignKey('game_airports.id'), primary_key=True)
    other_id = db.Column(db.Integer, db.ForeignKey('game_airports.id'), primary_key=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    __table_args__ = (db.CheckConstraint('airport_id <> other_id', name='ck_air_route_pair'), {'mysql_engine': 'InnoDB'})
