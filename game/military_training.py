"""Szkolenie sił zbrojnych: zakup poziomów wyszkolenia (0–1000) z budżetu sił zbrojnych (11 Nov 2026).

Koszt podniesienia o 1 poziom: siły lądowe 1,5 MLD, morskie 1,7 MLD, powietrzne 1,9 MLD ROI.
"""
from decimal import Decimal
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from extensions import db
from game.finance_service import FinanceError,game_now
from game.land_war_models import TrainingExpense
from models import Wojsko

MAX_LEVEL=1000
BRANCHES={'land':('wyszkolenie_ladowe','Siły lądowe',Decimal('1500000000')),
          'naval':('wyszkolenie_morskie','Siły morskie',Decimal('1700000000')),
          'air':('wyszkolenie_powietrzne','Siły powietrzne',Decimal('1900000000'))}
ARMY_FIELDS={'wojska_ladowe_ilosc':'land','wojska_morskie_ilosc':'naval','wojska_powietrzne_ilosc':'air'}


def spent(session,budget_id):
    return session.scalar(select(func.coalesce(func.sum(TrainingExpense.amount),0)).where(TrainingExpense.budget_id==budget_id)) or Decimal(0)


def levels(army):
    return {branch:(getattr(army,field) if army is not None and getattr(army,field) is not None else 100) for branch,(field,_,_) in BRANCHES.items()}


def train(user_id,data):
    from game.finance_service import _country_for_user
    from game.land_war import natural,request_key
    from game.military_service import military_budget
    branch=data.get('branch')
    if branch not in BRANCHES:raise FinanceError('Wybierz rodzaj sił zbrojnych.')
    field,label,price=BRANCHES[branch]
    count=natural(data.get('levels'),'Liczba poziomów',1);key=request_key(data.get('request_id'))
    with Session(db.engine) as session,session.begin():
        country=_country_for_user(session,user_id,lock=True);own=country.PANSTWO_ID
        existing=session.scalar(select(TrainingExpense).where(TrainingExpense.panstwo_id==own,TrainingExpense.request_id==key))
        if existing is not None:
            if (existing.branch,existing.levels)!=(branch,count):raise FinanceError('Identyfikator operacji został już wykorzystany.')
            return existing.level_after
        army=session.scalar(select(Wojsko).where(Wojsko.panstwo_id==own).with_for_update())
        if army is None:raise FinanceError('Brak danych o siłach zbrojnych państwa.')
        current=getattr(army,field) if getattr(army,field) is not None else 100
        if current+count>MAX_LEVEL:raise FinanceError(f'{label}: maksymalny poziom wyszkolenia to {MAX_LEVEL} (obecnie {current}).')
        cost=price*count
        budget,_,available=military_budget(session,own)
        if budget is None:raise FinanceError('Brak zatwierdzonego budżetu na bieżący okres budżetowy.')
        if available<cost:raise FinanceError('Za mało środków w budżecie sił zbrojnych na szkolenie.')
        setattr(army,field,current+count)
        session.add(TrainingExpense(panstwo_id=own,user_id=user_id,budget_id=budget.id,branch=branch,levels=count,level_after=current+count,amount=cost,request_id=key,game_at=game_now()))
        return current+count
