"""Audytowane korekty sald i stawek podatkowych przez WIKI."""
from decimal import Decimal
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from extensions import db
from models import Panstwo
from game.civic_models import TreasuryAdjustment,CountryTaxPolicy
from game.finance_models import StateBudget,StateFinancialAccount
from game.finance_service import FinanceError,FinanceConflict,game_now,period_key,money,percentage,decimal_value,CATEGORY_CODES,utc_now
from game.mining_service import request_key
from game.budget_transfers import precise


@precise
def adjustment_delta(session,country_id,budget_id,category='reserve'):
    condition=TreasuryAdjustment.budget_id.is_(None) if budget_id is None else TreasuryAdjustment.budget_id==budget_id
    return session.scalar(select(func.coalesce(func.sum(TreasuryAdjustment.amount),0)).where(TreasuryAdjustment.panstwo_id==country_id,condition,TreasuryAdjustment.category==category)) or Decimal(0)


def tax_plan(session,country_id,plan):
    policy=session.get(CountryTaxPolicy,country_id)
    return {**plan,'pit_rate':policy.pit_rate,'cit_rate':Decimal(0)} if policy else plan


@precise
def adjust(country_id,data,actor):
    key=request_key(data.get('request_id'));category=data.get('category','reserve')
    if not isinstance(category,str) or category not in CATEGORY_CODES:raise FinanceError('Wybierz sektor budżetu.')
    amount=decimal_value(data.get('amount','0'),'Korekta')
    if abs(amount)>=Decimal('1e27') or amount.quantize(Decimal('.01'))!=amount:raise FinanceError('Podaj kwotę z najwyżej dwoma miejscami po przecinku.')
    reason=data.get('reason')
    if not isinstance(reason,str) or not 3<=len(reason.strip())<=500:raise FinanceError('Podaj uzasadnienie zmiany (3–500 znaków).')
    taxes=data.get('taxes');after=None
    if taxes is not None:
        if not isinstance(taxes,dict):raise FinanceError('Nieprawidłowe stawki podatków.')
        after={'pit_rate':str(percentage(taxes.get('pit_rate'),'Podatek ogólny')),'cit_rate':'0.00'}
    if not amount and after is None:raise FinanceError('Podaj korektę środków lub nowe stawki podatków.')
    with Session(db.engine) as session,session.begin():
        if session.scalar(select(Panstwo.PANSTWO_ID).where(Panstwo.PANSTWO_ID==country_id).with_for_update()) is None:raise FinanceError('Nie znaleziono państwa.')
        existing=session.scalar(select(TreasuryAdjustment).where(TreasuryAdjustment.request_id==key))
        if existing:
            if (existing.panstwo_id,existing.category,existing.amount,existing.reason,existing.policy_after)!=(country_id,category,amount,reason.strip(),after):raise FinanceConflict('Identyfikator korekty został już użyty.')
            return existing.id
        account=session.scalar(select(StateFinancialAccount).where(StateFinancialAccount.panstwo_id==country_id).with_for_update())
        budget=session.get(StateBudget,account.last_budget_id) if account and account.last_budget_id else None
        if category!='reserve' and (budget is None or (budget.game_year,budget.period)!=period_key(game_now())):raise FinanceError('Sektory można korygować tylko w zatwierdzonym budżecie bieżącego okresu budżetowego.')
        if amount<0:
            if category=='reserve':available=account.reserve_balance if account else Decimal(0)
            else:
                from game.budget_transfers import sector_balances
                if category=='armed_forces':
                    from game.military_service import reconcile_maintenance
                    reconcile_maintenance(session,country_id)
                available=sector_balances(session,budget)[category]['remaining']
            if -amount>available:raise FinanceError('Korekta przekracza niewydane środki. Saldo nie może być ujemne.')
        if category=='reserve' and amount:
            if account is None:
                account=StateFinancialAccount(panstwo_id=country_id,reserve_balance=0,last_transaction_sequence=0,created_at=utc_now(),updated_at=utc_now());session.add(account)
            account.reserve_balance=money(account.reserve_balance+amount);account.updated_at=utc_now()
        before=None
        if after is not None:
            policy=session.get(CountryTaxPolicy,country_id)
            if policy:before={'pit_rate':str(policy.pit_rate),'cit_rate':str(policy.cit_rate)}
            else:policy=CountryTaxPolicy(panstwo_id=country_id,version=0);session.add(policy)
            policy.pit_rate=Decimal(after['pit_rate']);policy.cit_rate=Decimal(after['cit_rate']);policy.version+=1
        row=TreasuryAdjustment(panstwo_id=country_id,budget_id=budget.id if budget else None,category=category,amount=amount,admin_actor=actor,reason=reason.strip(),request_id=key,policy_before=before,policy_after=after)
        session.add(row);session.flush();return row.id
