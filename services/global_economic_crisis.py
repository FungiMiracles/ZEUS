"""Atomic, once-per-Entenda-year economic crisis initiated by WIKI admins."""
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from extensions import db
from engine.clock import get_current_entenda_datetime
from models import Panstwo, Gospodarka, Zdarzenie, ProcentWzrostuStateHistory

EVENT_TYPE = 'globalny_kryzys_gospodarczy'
LEVELS = {
    'deep': dict(label='głęboki', percent=75, scale=3),
    'medium': dict(label='średni', percent=50, scale=2),
    'mild': dict(label='niewielki', percent=25, scale=1),
}


class GlobalEconomicCrisis(db.Model):
    __tablename__ = 'wiki_global_economic_crises'
    year = db.Column(db.Integer, primary_key=True)
    level = db.Column(db.String(10), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey('zdarzenia.zdarzenie_id'), nullable=False, unique=True)
    actor = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    __table_args__ = (db.CheckConstraint("level IN ('deep','medium','mild')", name='ck_global_crisis_level'),
        {'mysql_engine': 'InnoDB'})


class CrisisError(ValueError):
    pass


def current_crisis(year):
    return db.session.get(GlobalEconomicCrisis, year)


def reduced_growth(value, percent):
    value = Decimal(value)
    return (value - abs(value) * Decimal(percent) / 100).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)


def generate_crisis(level, expected_year, actor):
    if level not in LEVELS:
        raise CrisisError('Wybierz poziom kryzysu.')
    now = get_current_entenda_datetime()
    if str(expected_year) != str(now.year):
        raise CrisisError('Rok Entendy zmienił się. Odśwież Generator Zdarzeń.')
    spec = LEVELS[level]
    try:
        with Session(db.engine) as session, session.begin():
            if session.get(GlobalEconomicCrisis, now.year):
                raise CrisisError('W tym roku Entendy wygenerowano już globalny kryzys gospodarczy.')
            event = Zdarzenie(zdarzenie_typ=EVENT_TYPE, zdarzenie_kategoria='gospodarcze',
                data_entenda=now, data_rzeczywista=datetime.now(), skala=spec['scale'],
                status='aktywne', wariant=level, effect_applied=True, ilosc_ofiar=0)
            session.add(event)
            session.flush()
            session.add(GlobalEconomicCrisis(year=now.year, level=level,
                event_id=event.zdarzenie_id, actor=str(actor)[:120]))
            # The year primary key is the cross-worker concurrency guard. Flush
            # it before changing any country; a losing request rolls back fully.
            session.flush()
            countries = list(session.scalars(select(Panstwo.PANSTWO_ID)
                .where(Panstwo.status == 'aktywne').order_by(Panstwo.PANSTWO_ID).with_for_update()))
            economies = list(session.scalars(select(Gospodarka)
                .where(Gospodarka.panstwo_id.in_(countries))
                .order_by(Gospodarka.panstwo_id, Gospodarka.gospodarka_id).with_for_update()))
            changes = []
            affected = set()
            for economy in economies:
                if economy.wzrost_pkb is None:
                    continue
                old = Decimal(economy.wzrost_pkb)
                new = reduced_growth(old, spec['percent'])
                if abs(new) > Decimal('99999999.99'):
                    raise CrisisError('Wynik kryzysu przekracza dopuszczalny zakres wzrostu PKB. Nie zapisano zmian.')
                economy.wzrost_pkb = new
                affected.add(economy.panstwo_id)
                changes.append(dict(country_id=economy.panstwo_id, economy_id=economy.gospodarka_id,
                    old=str(old), new=str(new)))
                session.add(ProcentWzrostuStateHistory(panstwo_id=economy.panstwo_id,
                    data_entenda=now.date(), data_rzeczywista=datetime.now(),
                    source='GLOBAL_CRISIS', event_id=event.zdarzenie_id,
                    old_wzrost=old, new_wzrost=new, change_delta=new-old))
            if not changes:
                raise CrisisError('Brak państw z zapisanym wzrostem PKB. Nie wygenerowano kryzysu.')
            event.opis_wygenerowany = (
                f'{spec["label"].capitalize()} globalny kryzys gospodarczy. '
                f'Obniżono współczynnik wzrostu PKB o {spec["percent"]}% jego wartości bezwzględnej '
                f'w {len(affected)} państwach. Ujemny wzrost uległ pogłębieniu. '
                f'Pominięto {len(countries)-len(affected)} państw bez danych wzrostu PKB.')
            event.payload_json = dict(level=level, reduction_percent=spec['percent'],
                year=now.year, actor=str(actor)[:120], affected_countries=len(affected),
                missing_countries=len(countries)-len(affected), changes=changes)
            return event.zdarzenie_id
    except IntegrityError as error:
        # Check independently after rollback so genuine persistence errors are
        # not misreported as a duplicate-year attempt.
        with Session(db.engine) as check:
            if check.get(GlobalEconomicCrisis, now.year):
                raise CrisisError('W tym roku Entendy wygenerowano już globalny kryzys gospodarczy.') from error
        raise
