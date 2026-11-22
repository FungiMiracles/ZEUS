"""Pasek wskaźników społecznych pod menu gry (22 Nov 2026).

Kolor kontenera wynika z progów wskaźnika, a strzałka z kierunku dwóch ostatnich zmian. Zmiany wartości
tabeli `spoleczenstwo` zapisują się w `game_society_trends` przez nasłuch ORM (before_flush), więc obejmują
wszystkie moduły — także te, które nie dopisują wierszy do `spoleczenstwo_state_history`.
"""
import weakref
from datetime import datetime, timezone

from sqlalchemy import event, inspect as sa_inspect, select, text
from sqlalchemy.orm import Session

from extensions import db

# (pole w Spoleczenstwo, etykieta, czy wysoka wartość jest dobra)
INDICATORS = (
    ('stabilnosc_spoleczna', 'Stabilność społeczna', True),
    ('zadowolenie_spoleczne', 'Zadowolenie społeczne', True),
    ('poziom_edukacji', 'Edukacja', True),
    ('zdrowie_publiczne', 'Zdrowie', True),
    ('przestepczosc', 'Przestępczość', False),
    ('radykalizacja_spoleczna', 'Radykalizacja', False),
    ('nierownosci_spoleczne', 'Nierówności społeczne', False),
    ('zaufanie_do_wladzy', 'Zaufanie do władzy', True),
)
FIELDS = tuple(field for field, _, _ in INDICATORS)
# Kolumny historii odpowiadające polom (seed trendów z spoleczenstwo_state_history).
HISTORY_COLUMNS = {
    'stabilnosc_spoleczna': 'stabilnosc', 'zadowolenie_spoleczne': 'zadowolenie', 'poziom_edukacji': 'edukacja',
    'zdrowie_publiczne': 'zdrowie_publiczne', 'przestepczosc': 'przestepczosc', 'radykalizacja_spoleczna': 'radykalizacja',
    'nierownosci_spoleczne': 'nierownosci', 'zaufanie_do_wladzy': 'zaufanie',
}


class GameSocietyTrend(db.Model):
    """Dwie ostatnie zmiany wskaźnika (znak zmiany: +1 / -1)."""
    __tablename__ = 'game_society_trends'
    panstwo_id = db.Column(db.Integer, db.ForeignKey('panstwa.PANSTWO_ID', ondelete='CASCADE'), primary_key=True)
    field = db.Column(db.String(40), primary_key=True)
    last_delta = db.Column(db.SmallInteger, nullable=False)
    prev_delta = db.Column(db.SmallInteger)
    updated_at = db.Column(db.DateTime, nullable=False)


def tone(value, good_high):
    """Progi (22 Nov 2026): dobre wskaźniki ≥70 zielony, 40–69 żółty, <40 czerwony; szkodliwe <30 zielony,
    30–59 żółty, >70 czerwony, 60–70 neutralny."""
    if value is None:
        return 'neutral'
    if good_high:
        return 'good' if value >= 70 else 'warn' if value >= 40 else 'bad'
    return 'bad' if value > 70 else 'warn' if 30 <= value < 60 else 'good' if value < 30 else 'neutral'


def trend(last_delta, prev_delta):
    """'up' — obie ostatnie zmiany wzrostowe, 'down' — obie spadkowe, 'mixed' — wzrost i spadek.
    Przy jednej zarejestrowanej zmianie decyduje jej kierunek; bez zmian — brak oznaczenia."""
    deltas = [d for d in (last_delta, prev_delta) if d]
    if not deltas:
        return None
    if all(d > 0 for d in deltas):
        return 'up'
    if all(d < 0 for d in deltas):
        return 'down'
    return 'mixed'


def society_strip(session, country_id):
    from models import Spoleczenstwo
    society = session.scalar(select(Spoleczenstwo).where(Spoleczenstwo.panstwo_id == country_id)
                             .order_by(Spoleczenstwo.spoleczenstwo_id.desc()).limit(1))
    if society is None:
        return []
    trends = {}
    if _table_ready(session.get_bind()):
        trends = {row.field: row for row in session.scalars(select(GameSocietyTrend).where(GameSocietyTrend.panstwo_id == country_id))}
    items = []
    for field, label, good_high in INDICATORS:
        value = getattr(society, field)
        row = trends.get(field)
        items.append({'field': field, 'label': label, 'value': value, 'tone': tone(value, good_high),
                      'trend': trend(row.last_delta, row.prev_delta) if row else None})
    return items


# --- zapis zmian -----------------------------------------------------------------------------------------
_ready = weakref.WeakKeyDictionary()   # silnik → czy tabela istnieje (bez migracji nasłuch nic nie zapisuje)


def _table_ready(bind):
    engine = getattr(bind, 'engine', bind)
    if engine not in _ready:
        _ready[engine] = sa_inspect(engine).has_table(GameSocietyTrend.__tablename__)
    return _ready[engine]


def _upsert_sql(dialect):
    if dialect == 'mysql':
        # MySQL wykonuje przypisania od lewej — prev_delta dostaje poprzednie last_delta.
        return text('INSERT INTO game_society_trends (panstwo_id, field, last_delta, prev_delta, updated_at) '
                    'VALUES (:country, :field, :delta, NULL, :now) ON DUPLICATE KEY UPDATE '
                    'prev_delta = last_delta, last_delta = VALUES(last_delta), updated_at = VALUES(updated_at)')
    return text('INSERT INTO game_society_trends (panstwo_id, field, last_delta, prev_delta, updated_at) '
                'VALUES (:country, :field, :delta, NULL, :now) ON CONFLICT (panstwo_id, field) DO UPDATE SET '
                'prev_delta = game_society_trends.last_delta, last_delta = excluded.last_delta, updated_at = excluded.updated_at')


def _record_changes(session, flush_context, instances):
    from models import Spoleczenstwo
    changes = []
    for obj in session.dirty:
        if not isinstance(obj, Spoleczenstwo) or obj.panstwo_id is None:
            continue
        state = sa_inspect(obj)
        for field in FIELDS:
            history = state.attrs[field].history
            if not (history.added and history.deleted):
                continue
            old, new = history.deleted[0], history.added[0]
            if old is None or new is None or new == old:
                continue
            changes.append({'country': obj.panstwo_id, 'field': field, 'delta': 1 if new > old else -1})
    if not changes:
        return
    connection = session.connection()
    if not _table_ready(connection.engine):
        return
    statement = _upsert_sql(connection.dialect.name)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for change in changes:
        connection.execute(statement, {**change, 'now': now})


def install():
    if not event.contains(Session, 'before_flush', _record_changes):
        event.listen(Session, 'before_flush', _record_changes)


def seed_from_history(connection):
    """Odtwarza dwie ostatnie zmiany z spoleczenstwo_state_history (dla migracji). Zwraca liczbę wierszy."""
    columns = ', '.join(f'old_{HISTORY_COLUMNS[f]} AS o_{f}, new_{HISTORY_COLUMNS[f]} AS n_{f}' for f in FIELDS)
    rows = connection.execute(text(f'SELECT panstwo_id, {columns} FROM spoleczenstwo_state_history '
                                   'ORDER BY panstwo_id, data_rzeczywista DESC, id DESC')).mappings()
    found = {}
    for row in rows:
        for field in FIELDS:
            old, new = row[f'o_{field}'], row[f'n_{field}']
            if old is None or new is None or new == old:
                continue
            deltas = found.setdefault((row['panstwo_id'], field), [])
            if len(deltas) < 2:
                deltas.append(1 if new > old else -1)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for (country, field), deltas in found.items():
        connection.execute(GameSocietyTrend.__table__.insert().values(
            panstwo_id=country, field=field, last_delta=deltas[0], prev_delta=deltas[1] if len(deltas) > 1 else None, updated_at=now))
    return len(found)
