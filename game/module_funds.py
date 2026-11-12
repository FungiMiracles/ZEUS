"""Shared "module funds" container: money available to the current game module plus the budget reserve (10 Nov 2026).

Read-only. Sector assignment agreed with the administrator; trade and diplomacy show the reserve only.
"""
from decimal import Decimal
from flask import session as browser
from sqlalchemy import select
from sqlalchemy.orm import Session
from extensions import db

MODULE_SECTORS={'infrastructure':'infrastructure','defense':'armed_forces','war':'armed_forces','army':'armed_forces',
                'intelligence':'security_services','research':'research','environment':'environment','demography':'social_policy','society':'social_policy',
                'trade':None,'diplomacy':None}
LABELS={'infrastructure':'budżet infrastruktury','armed_forces':'budżet sił zbrojnych','security_services':'budżet służb specjalnych',
        'research':'budżet badań','environment':'budżet środowiska','social_policy':'budżet polityki społecznej'}


def module_funds(page):
    if page not in MODULE_SECTORS:return None
    user_id=browser.get('game_user_id')
    if not user_id:return None
    from game.models import GamePlayerCountry
    from game.finance_models import StateBudget,StateFinancialAccount
    from game.finance_service import game_now,period_key
    from game.governance import controller_id
    try:
        with Session(db.engine) as session:
            country=session.scalar(select(GamePlayerCountry.panstwo_id).where(GamePlayerCountry.user_id==user_id))
            if country is None:return None
            country=controller_id(session,country) or country
            account=session.get(StateFinancialAccount,country)
            reserve=account.reserve_balance if account else Decimal(0)
            code=MODULE_SECTORS[page];available=None;approved=True
            if code:
                year,period=period_key(game_now())
                budget=session.scalar(select(StateBudget).where(StateBudget.panstwo_id==country,StateBudget.game_year==year,StateBudget.period==period))
                if budget is None:approved=False
                else:
                    from game.budget_transfers import sector_balances
                    available=sector_balances(session,budget)[code]['remaining']
            return {'label':LABELS.get(code),'available':str(available) if available is not None else None,'reserve':str(reserve),'approved':approved,'sector':code}
    except Exception:
        return None


def register(app):
    app.jinja_env.globals['module_funds']=module_funds
