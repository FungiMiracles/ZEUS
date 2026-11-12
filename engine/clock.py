"""Persistent UAT simulation clock; changing speed never changes its current date."""
from datetime import datetime
from flask import current_app, has_app_context
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.dialects.mysql import DATETIME
from extensions import db

TIME_MULTIPLIER = 12  # Legacy/default speed, before persistent UAT controls are enabled.
ENTENDA_START = datetime(2990, 1, 1)
REAL_START = datetime(2025, 11, 28)
ALLOWED_SPEEDS = (0, 6, 12, 24, 36)


class SimulationClock(db.Model):
    __tablename__ = 'wiki_simulation_clock'
    id = db.Column(db.Integer, primary_key=True, autoincrement=False)
    real_anchor = db.Column(db.DateTime().with_variant(DATETIME(fsp=6), 'mysql'), nullable=False)
    entenda_anchor = db.Column(db.DateTime().with_variant(DATETIME(fsp=6), 'mysql'), nullable=False)
    multiplier = db.Column(db.Integer, nullable=False, default=12)
    revision = db.Column(db.Integer, nullable=False, default=0)
    actor = db.Column(db.String(120))
    __table_args__ = (
        db.CheckConstraint('id = 1 AND multiplier IN (0,6,12,24,36) AND revision >= 0', name='ck_simulation_clock'),
        {'mysql_engine': 'InnoDB'},
    )


class ClockError(ValueError):
    pass


def clock_enabled():
    return has_app_context() and current_app.config.get('ENTENDA_CLOCK_CONTROL_ENABLED', False)


def clock_description(speed):
    if speed == 0:
        return 'Czas symulacji w Entendzie jest zatrzymany.'
    return (f'Czas w Entendzie płynie {speed} razy szybciej niż czas rzeczywisty: '
        f'1 godzina Entendy to {60/speed:g} minut rzeczywistych, '
        f'a doba Entendy to {24/speed:g} godziny rzeczywiste.')


def _snapshot(row, now):
    moment = row.entenda_anchor + (now - row.real_anchor) * row.multiplier
    return dict(entenda=moment.isoformat(), multiplier=row.multiplier,
        revision=row.revision, description=clock_description(row.multiplier))


def get_clock_snapshot():
    if clock_enabled():
        # A separate short session avoids interfering with caller transactions.
        with Session(db.engine) as session:
            row = session.get(SimulationClock, 1)
            if row is None:
                raise ClockError('Zegar symulacji nie został zainicjalizowany.')
            return _snapshot(row, datetime.now())
    now = datetime.now()
    moment = ENTENDA_START + (now - REAL_START) * TIME_MULTIPLIER
    return dict(entenda=moment.isoformat(), multiplier=TIME_MULTIPLIER,
        revision=0, description=clock_description(TIME_MULTIPLIER))


def get_time_multiplier():
    return get_clock_snapshot()['multiplier']


def set_clock_speed(speed, revision, actor):
    if not clock_enabled():
        raise ClockError('Sterowanie zegarem jest dostępne wyłącznie w UAT.')
    if type(speed) is not int or speed not in ALLOWED_SPEEDS or type(revision) is not int:
        raise ClockError('Wybierz poprawne tempo zegara.')
    with Session(db.engine) as session, session.begin():
        row = session.scalar(select(SimulationClock).where(SimulationClock.id == 1).with_for_update())
        if row is None:
            raise ClockError('Zegar symulacji nie został zainicjalizowany.')
        if row.revision != revision:
            raise ClockError('Tempo zegara zmieniło się. Spróbuj ponownie po odświeżeniu zegara.')
        now = datetime.now()  # Read after obtaining the row lock.
        row.entenda_anchor = row.entenda_anchor + (now - row.real_anchor) * row.multiplier
        row.real_anchor = now
        row.multiplier = speed
        row.revision += 1
        row.actor = str(actor)[:120]
        return _snapshot(row, now)


def get_current_entenda_datetime():
    return datetime.fromisoformat(get_clock_snapshot()['entenda'])


def get_current_entenda_date():
    return get_current_entenda_datetime().date()


def get_entenda_year():
    return get_current_entenda_date().year


def get_entenda_month():
    return get_current_entenda_date().month


def get_entenda_day():
    return get_current_entenda_date().day
