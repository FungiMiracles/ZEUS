"""Atomic research spending and production in complete Entenda days."""
from datetime import timedelta
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import Session
from extensions import db
from models import Panstwo,Region
from game.finance_service import FinanceError,FinanceConflict,_country_for_user,game_now,period_key
from game.finance_models import StateBudget
from game.budget_transfers import precise,sector_balances
from game.admin_finance import request_key
from game.military_service import natural
from game.research_models import ResearchAccount,ResearchExpense,ResearchInvestment,AmmunitionFactory

POINT_PRICE=400000000
FACTORY_PRICE=2000000000
from game.industry_catalog import TECHNOLOGIES
LEVELS={key:[rule['cost']] for key,rule in TECHNOLOGIES.items()}


def node_state(points,node):
    level=0;rest=points
    for cost in LEVELS[node]:
        if rest<cost:break
        level+=1;rest-=cost
    return {'invested':points,'level':level,'progress':rest,'required':LEVELS[node][level] if level<len(LEVELS[node]) else 0,'maximum':level==len(LEVELS[node])}


def account_for(session,country_id):
    # All writers lock the sovereign country before calling this helper.
    row=session.get(ResearchAccount,country_id)
    if row is None:row=ResearchAccount(panstwo_id=country_id,points=0,ammunition=0,nodes={});session.add(row);session.flush()
    return row


def settle_production(session,country_id,now=None,*,resolve_attacks=True):
    now=now or game_now()
    if resolve_attacks:
        from game.military_flights import complete_flights
        complete_flights(session,now,country_id=country_id)
    from game.industry_service import settle_industry
    return settle_industry(session,country_id,now)


def budget_for(session,country,category,cost):
    year,period=period_key(game_now())
    budget=session.scalar(select(StateBudget).where(StateBudget.panstwo_id==country,StateBudget.game_year==year,StateBudget.period==period).with_for_update())
    if budget is None or sector_balances(session,budget)[category]['remaining']<cost:raise FinanceError('Za mało środków w budżecie bieżącego półrocza.')
    return budget


@precise
def change_research(user_id,data):
    key=request_key(data.get('request_id'));action=data.get('action')
    if action=='factory':
        from game.industry_service import change_industry
        return change_industry(user_id,{**data,'action':'build','category':'factory','kind':'interceptor_ammo','level':1})
    with Session(db.engine) as session,session.begin():
        country=_country_for_user(session,user_id).PANSTWO_ID
        session.scalar(select(Panstwo.PANSTWO_ID).where(Panstwo.PANSTWO_ID==country).with_for_update())
        account=account_for(session,country)
        if action=='buy':
            count=natural(data.get('count'),'Punkty rozwoju',1);cost=Decimal(count)*POINT_PRICE
            existing=session.scalar(select(ResearchExpense).where(ResearchExpense.panstwo_id==country,ResearchExpense.request_id==key))
            if existing:
                if existing.points!=count:raise FinanceConflict('Identyfikator zakupu został już użyty.')
                return
            if data.get('expected_point_price')!=POINT_PRICE:raise FinanceConflict('Cena punktu rozwoju zmieniła się. Odśwież stronę przed zakupem.')
            if account.points+count>9223372036854775807:raise FinanceError('Przekroczony limit punktów.')
            budget=budget_for(session,country,'research',cost)
            account.points+=count;session.add(ResearchExpense(panstwo_id=country,budget_id=budget.id,amount=cost,points=count,request_id=key))
        elif action=='invest':
            node=data.get('node');count=natural(data.get('count'),'Punkty do zainwestowania',1)
            if node not in LEVELS:raise FinanceError('Ten kierunek badań jest czasowo niedostępny.')
            existing=session.scalar(select(ResearchInvestment).where(ResearchInvestment.panstwo_id==country,ResearchInvestment.request_id==key))
            if existing:
                if (existing.node,existing.points)!=(node,count):raise FinanceConflict('Identyfikator inwestycji został już użyty.')
                return
            nodes=dict(account.nodes)
            parent=TECHNOLOGIES[node]['parent']
            if parent and node_state(nodes.get(parent,0),parent)['level']<1:raise FinanceError('Najpierw opracuj technologię: '+TECHNOLOGIES[parent]['label']+'.')
            current=nodes.get(node,0);state=node_state(current,node)
            if count>account.points:raise FinanceError('Za mało punktów rozwoju.')
            if state['maximum'] or count>state['required']-state['progress']:raise FinanceError('Możesz uzupełnić punkty do najbliższego poziomu.')
            nodes[node]=current+count;account.nodes=nodes;account.points-=count
            session.add(ResearchInvestment(panstwo_id=country,node=node,points=count,request_id=key))
        elif action=='factory':
            raise FinanceError('Budowę fabryk przeniesiono do modułu Infrastruktura i energetyka.')
        else:raise FinanceError('Nieprawidłowa operacja badawcza.')
