"""Finansowanie walki z przestępczością (16 Nov 2026) — oczekiwania społeczne wobec budżetu służb specjalnych i porządkowych.

Zasady (decyzja administratora):
- oczekiwana kwota na okres budżetowy = populacja × poziom przestępczości, zaokrąglona do setek milionów ROI,
- gracz (i PAGA2) ustala kwotę przy zatwierdzaniu budżetu; środki pochodzą z sektora „Służby specjalne i porządkowe”,
- rozliczenie następuje w tym samym okresie, tydzień Entendy przed datą zatwierdzenia kolejnego budżetu (końcem okresu):
  niedofinansowanie do 35% → przestępczość +1, powyżej 35% do 60% → +2, powyżej 60% → +3;
  nadwyżka do 5% → bez zmian, powyżej 5% do 20% → −1, powyżej 20% → −2,
- gracz otrzymuje powiadomienie o wzroście lub spadku przestępczości.
"""
from datetime import timedelta
from decimal import Decimal,ROUND_HALF_UP,localcontext
from functools import wraps
from sqlalchemy import select
from sqlalchemy.orm import lazyload
from extensions import db

ROUNDING=Decimal('100000000')   # setki milionów ROI
SETTLE_BEFORE_END=timedelta(days=7)   # tydzień Entendy przed kolejnym budżetem


def precise(function):
    @wraps(function)
    def wrapped(*args,**kwargs):
        with localcontext() as context:
            context.prec=64
            return function(*args,**kwargs)
    return wrapped


class CrimeFunding(db.Model):
    __tablename__='game_crime_funding'
    budget_id=db.Column(db.BigInteger,db.ForeignKey('game_state_budgets.id'),primary_key=True)
    panstwo_id=db.Column(db.Integer,db.ForeignKey('panstwa.PANSTWO_ID'),nullable=False,index=True)
    expected=db.Column(db.Numeric(40,2),nullable=False)
    paid=db.Column(db.Numeric(40,2),nullable=False)
    crime_level=db.Column(db.Integer)          # poziom przestępczości przy zatwierdzeniu budżetu
    settled_at=db.Column(db.DateTime)          # czas gry rozliczenia (NULL = jeszcze nie rozliczono)
    effect=db.Column(db.SmallInteger)          # zmiana przestępczości wynikająca z finansowania
    old_level=db.Column(db.Integer)
    new_level=db.Column(db.Integer)


def crime_level(session,country_id):
    from models import Spoleczenstwo
    return session.scalar(select(Spoleczenstwo.przestepczosc).where(Spoleczenstwo.panstwo_id==country_id).order_by(Spoleczenstwo.spoleczenstwo_id.desc()).limit(1))


@precise
def expected_amount(population,level):
    """[populacja] × [poziom przestępczości], zaokrąglone do setek milionów."""
    if population is None or level is None:return None
    value=Decimal(int(population))*Decimal(int(level))
    return ((value/ROUNDING).quantize(Decimal('1'),rounding=ROUND_HALF_UP)*ROUNDING).quantize(Decimal('0.01'))


def expectations(session,country_id):
    from game.finance_service import economy
    level=crime_level(session,country_id)
    population=economy(session,country_id)['population']
    amount=expected_amount(population,level)
    if amount is None:return None
    return {'expected':amount,'level':int(level)}


@precise
def effect(paid,expected):
    """Zmiana poziomu przestępczości (dodatnia = wzrost) wynikająca z finansowania w okresie."""
    paid,expected=Decimal(paid),Decimal(expected)
    if expected<=0:return 0
    if paid<expected:
        gap=(expected-paid)/expected
        if gap<=Decimal('.35'):return 1
        if gap<=Decimal('.60'):return 2
        return 3
    surplus=(paid-expected)/expected
    if surplus<=Decimal('.05'):return 0
    if surplus<=Decimal('.20'):return -1
    return -2


def details(session,budget):
    if budget is None:return None
    row=session.get(CrimeFunding,budget.id)
    if row is None:return None
    return {'expected':row.expected,'paid':row.paid,'level':row.crime_level,'settled':row.settled_at is not None,
            'effect':row.effect,'old_level':row.old_level,'new_level':row.new_level}


@precise
def record_funding(session,budget,previous,allocation,raw,repeat):
    """Zapisuje kwotę na walkę z przestępczością w zatwierdzanym budżecie (bez commit)."""
    from game.finance_service import FinanceError,money,decimal_value
    allocation=Decimal(allocation or 0)
    data=expectations(session,budget.panstwo_id)
    expected=data['expected'] if data else Decimal('0.00')
    old=session.get(CrimeFunding,previous.id) if previous is not None else None
    if repeat or raw is None:
        # Powtórzenie planu kopiuje poprzednią kwotę; gdy jej brak (budżety sprzed wprowadzenia zasady
        # lub klient bez pola), przyjmujemy oczekiwania społeczne. Kwota nie może przekroczyć sektora.
        paid=money(old.paid) if (repeat and old is not None) else expected
        paid=min(paid,max(Decimal(0),allocation)).quantize(Decimal('0.01'))
    else:
        paid=money(raw)
        if paid<0 or paid!=decimal_value(raw,'Walka z przestępczością'):raise FinanceError('Podaj nieujemną kwotę na walkę z przestępczością z dokładnością do grosza.')
        if paid>allocation:raise FinanceError('Środki na walkę z przestępczością przekraczają budżet służb specjalnych i porządkowych.')
    session.add(CrimeFunding(budget_id=budget.id,panstwo_id=budget.panstwo_id,expected=expected,paid=paid,
                             crime_level=data['level'] if data else None))
    return paid


def _billions(value):
    from game.money_display import format_money
    return format_money(value)


def notification_text(row,label):
    gap=''
    if row.expected and row.expected>0:
        ratio=(Decimal(row.paid)-Decimal(row.expected))/Decimal(row.expected)*100
        gap=(f' (niedofinansowanie {abs(ratio):.0f}%)' if ratio<0 else f' (nadwyżka {ratio:.0f}%)').replace('.',',')
    change='wzrósł' if row.new_level>row.old_level else 'spadł'
    return (f'Walka z przestępczością — {label}: przeznaczono {_billions(row.paid)} wobec oczekiwanych przez społeczeństwo '
            f'{_billions(row.expected)}{gap}. Poziom przestępczości {change} o {abs(row.new_level-row.old_level)} pkt '
            f'(z {row.old_level} do {row.new_level}).')


@precise
def settle_due(session,now):
    """Rozlicza finansowanie okresów, dla których minął termin (tydzień Entendy przed końcem okresu). Bez commit."""
    from game.finance_models import StateBudget
    from game.finance_service import period_bounds,period_label
    from game.forum_models import GameNotification
    from game.paga_ai_actor import country_user_id
    from game.models import utc_now
    from models import Spoleczenstwo
    rows=session.execute(select(CrimeFunding,StateBudget.game_year,StateBudget.period).join(StateBudget,StateBudget.id==CrimeFunding.budget_id)
                         .where(CrimeFunding.settled_at.is_(None)).order_by(StateBudget.game_year,StateBudget.period,CrimeFunding.budget_id)).all()
    settled=0
    for row,year,period in rows:
        _,end=period_bounds(year,period)
        if now<end-SETTLE_BEFORE_END:continue
        row=session.scalar(select(CrimeFunding).where(CrimeFunding.budget_id==row.budget_id,CrimeFunding.settled_at.is_(None)).with_for_update())
        if row is None:continue
        delta=effect(row.paid,row.expected)
        society=session.scalar(select(Spoleczenstwo).options(lazyload('*')).where(Spoleczenstwo.panstwo_id==row.panstwo_id)
                               .order_by(Spoleczenstwo.spoleczenstwo_id.desc()).limit(1).with_for_update())
        old=society.przestepczosc if society is not None else None
        new=max(0,min(100,(old or 0)+delta)) if society is not None else None
        if society is not None:society.przestepczosc=new
        row.settled_at=now;row.effect=delta;row.old_level=old;row.new_level=new
        if society is not None and old is not None and new!=old:
            owner=country_user_id(session,row.panstwo_id)
            if owner is not None:
                session.add(GameNotification(user_id=owner,notification_type='SYSTEM',created_at=utc_now(),
                                             system_text=notification_text(row,period_label(year,period))[:1000]))
        settled+=1
    if settled:session.flush()
    return settled
