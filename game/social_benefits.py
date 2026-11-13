"""Half-year benefit snapshots and durable annual settlements (ZEUS-GAME-0002)."""
from decimal import Decimal,localcontext
from functools import wraps
from sqlalchemy import select
from sqlalchemy.orm import lazyload
from extensions import db

KINDS=('children','seniors')


def precise(function):
    @wraps(function)
    def wrapped(*args,**kwargs):
        with localcontext() as context:
            context.prec=64
            return function(*args,**kwargs)
    return wrapped

class BenefitPayment(db.Model):
    __tablename__='game_benefit_payments'
    budget_id=db.Column(db.BigInteger,db.ForeignKey('game_state_budgets.id'),primary_key=True)
    kind=db.Column(db.String(16),primary_key=True)
    expected=db.Column(db.Numeric(40,2),nullable=False)
    paid=db.Column(db.Numeric(40,2),nullable=False)
    carry_in=db.Column(db.Numeric(40,2),nullable=False,default=0)

class MissedBenefitPeriod(db.Model):
    __tablename__='game_missed_benefit_periods'
    panstwo_id=db.Column(db.Integer,db.ForeignKey('panstwa.PANSTWO_ID'),primary_key=True)
    game_year=db.Column(db.Integer,primary_key=True)
    period=db.Column(db.SmallInteger,primary_key=True)
    expected=db.Column(db.JSON,nullable=False)


class BenefitSettlement(db.Model):
    __tablename__='game_benefit_settlements'
    panstwo_id=db.Column(db.Integer,db.ForeignKey('panstwa.PANSTWO_ID'),primary_key=True)
    game_year=db.Column(db.Integer,primary_key=True)
    effects=db.Column(db.JSON,nullable=False)


@precise
def expectations(session,country_id,year=None,period=None):
    from game.population_structure import structure_data
    from game.finance_service import economy,money
    data=structure_data(session,country_id)
    if not data['groups']:return None
    basis=economy(session,country_id)
    population=basis['population']
    if population is None or basis['gdp'] is None:return None
    per_capita=Decimal(basis['gdp'])/Decimal(population) if population else Decimal(0)
    # 13 Nov 2026: 2,5% PKB per capita na osobę w półroczu; w kwartale połowa (roczne świadczenia bez zmian)
    from game.finance_service import period_key,period_months,game_now
    if year is None or period is None:year,period=period_key(game_now())
    rate=Decimal('.025')*Decimal(period_months(year,period))/6
    return {g['key']:money(Decimal(g['count'] or 0)*per_capita*rate) for g in data['groups'] if g['key'] in KINDS}


@precise
def details(session,budget):
    rows=list(session.scalars(select(BenefitPayment).where(BenefitPayment.budget_id==budget.id)))
    if not rows:return None
    return {'expected':{r.kind:r.expected for r in rows},'paid':{r.kind:r.paid for r in rows},'carry_in':sum((r.carry_in for r in rows),Decimal(0))}


@precise
def carryover(session,previous):
    if previous is None:return Decimal(0)
    from game.budget_transfers import sector_balances
    return sector_balances(session,previous)['social_policy']['remaining']


@precise
def record_payments(session,budget,previous,allocation,raw,repeat):
    from game.finance_service import FinanceError,money,decimal_value
    if raw is not None and (not isinstance(raw,dict) or set(raw)-set(KINDS)):
        raise FinanceError('Nieprawidłowe kwoty świadczeń.')
    expected=expectations(session,budget.panstwo_id,budget.game_year,budget.period)
    if expected is None:
        if raw and any(decimal_value(v,'Świadczenie') for v in raw.values()):raise FinanceError('Uzupełnij strukturę wieku ludności przed wypłatą świadczeń.')
        carry=carryover(session,previous)
        for k in KINDS:session.add(BenefitPayment(budget_id=budget.id,kind=k,expected=0,paid=0,carry_in=carry if k=='children' else 0))
        return
    old=details(session,previous) if previous else None
    if repeat:raw=old['paid'] if old else {}
    raw=raw if raw is not None else {}
    if not isinstance(raw,dict) or set(raw)-set(KINDS):raise FinanceError('Nieprawidłowe kwoty świadczeń.')
    paid={k:money(raw.get(k,0)) for k in KINDS}
    for k in KINDS:
        if paid[k]<0 or paid[k]!=decimal_value(raw.get(k,0),'Świadczenie'):raise FinanceError('Podaj nieujemne kwoty świadczeń z dokładnością do grosza.')
    carry=carryover(session,previous)
    available=allocation+carry
    if repeat and sum(paid.values())>available:
        total=sum(paid.values());paid['children']=money(available*paid['children']/total);paid['seniors']=available-paid['children']
    if sum(paid.values())>available:raise FinanceError('Świadczenia przekraczają dostępny budżet polityki socjalnej.')
    for k in KINDS:session.add(BenefitPayment(budget_id=budget.id,kind=k,expected=expected[k],paid=paid[k],carry_in=carry if k=='children' else 0))


def record_missed_period(session,country_id,year,half):
    from game.finance_models import StateBudget
    active=session.execute(select(StateBudget.game_year,StateBudget.period).join(BenefitPayment,StateBudget.id==BenefitPayment.budget_id).where(StateBudget.panstwo_id==country_id).order_by(StateBudget.game_year,StateBudget.period).limit(1)).first()
    if active is None or (year,half)<tuple(active) or session.get(MissedBenefitPeriod,(country_id,year,half)):return
    expected=expectations(session,country_id,year,half)
    if expected is not None:session.add(MissedBenefitPeriod(panstwo_id=country_id,game_year=year,period=half,expected={k:str(v) for k,v in expected.items()}))


@precise
def annual_effect(paid,expected):
    if expected<=0:return (0,0,0)
    ratio=paid/expected
    if ratio>=Decimal('1.2'):return (1,1,-1)
    if ratio>=Decimal('.95'):return (0,0,0)
    if ratio>=Decimal('.75'):return (-1,0,0)
    if ratio>=Decimal('.4'):return (-2,0,0)
    return (-2,-1,1)


@precise
def settle_years(session,country_id,current_year):
    from game.finance_models import StateBudget
    from models import Panstwo,Spoleczenstwo
    from game.finance_service import FinanceError
    session.scalar(select(Panstwo).options(lazyload('*')).where(Panstwo.PANSTWO_ID==country_id).with_for_update())
    years=list(session.scalars(select(StateBudget.game_year).join(BenefitPayment,BenefitPayment.budget_id==StateBudget.id).where(StateBudget.panstwo_id==country_id,StateBudget.game_year<current_year).distinct().order_by(StateBudget.game_year)))
    years=sorted(set(years)|set(session.scalars(select(MissedBenefitPeriod.game_year).where(MissedBenefitPeriod.panstwo_id==country_id,MissedBenefitPeriod.game_year<current_year))))
    for year in years:
        if session.get(BenefitSettlement,(country_id,year)):continue
        rows=list(session.scalars(select(BenefitPayment).join(StateBudget,StateBudget.id==BenefitPayment.budget_id).where(StateBudget.panstwo_id==country_id,StateBudget.game_year==year)))
        missed=list(session.scalars(select(MissedBenefitPeriod).where(MissedBenefitPeriod.panstwo_id==country_id,MissedBenefitPeriod.game_year==year)))
        effects={k:annual_effect(sum((r.paid for r in rows if r.kind==k),Decimal(0)),sum((r.expected for r in rows if r.kind==k),Decimal(0))+sum((Decimal(r.expected[k]) for r in missed),Decimal(0))) for k in KINDS}
        society=session.scalar(select(Spoleczenstwo).where(Spoleczenstwo.panstwo_id==country_id).with_for_update())
        if society is None:raise FinanceError('Brak wskaźników społecznych do rozliczenia świadczeń.')
        for i,field in enumerate(('zadowolenie_spoleczne','zaufanie_do_wladzy','nierownosci_spoleczne')):
            value=getattr(society,field)
            if value is None:raise FinanceError('Niekompletne wskaźniki społeczne do rozliczenia świadczeń.')
            setattr(society,field,max(0,min(100,value+sum(e[i] for e in effects.values()))))
        session.add(BenefitSettlement(panstwo_id=country_id,game_year=year,effects=effects));session.flush()
