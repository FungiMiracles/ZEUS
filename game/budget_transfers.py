from game.paga_ai_actor import country_user_id
"""Bieżące salda sektorów i atomowe przesunięcia wolnych środków."""
from decimal import Decimal,localcontext
from functools import wraps
from uuid import UUID
from sqlalchemy import select,func,case
from sqlalchemy.orm import Session
from extensions import db
from game.budget_categories import canonical,normalize,INFRASTRUCTURE_LEGACY
from game.finance_models import BudgetTransfer,StateBudget,StateBudgetAllocation,StateFinancialAccount
from game.finance_service import (CATEGORY_CODES,FinanceError,FinanceConflict,_country_for_user,game_now,period_key,money,decimal_value,utc_now)


def precise(function):
    @wraps(function)
    def wrapped(*args,**kwargs):
        with localcontext() as context:
            context.prec=64
            return function(*args,**kwargs)
    return wrapped


@precise
def transfer_delta(session,budget_id,category):
    return session.scalar(select(func.coalesce(func.sum(case((BudgetTransfer.destination==category,BudgetTransfer.amount),else_=0)-case((BudgetTransfer.source==category,BudgetTransfer.amount),else_=0)),0)).where(BudgetTransfer.budget_id==budget_id)) or Decimal(0)


@precise
def effective_allocation(session,budget_id,category):
    codes=[category]
    if category=='infrastructure':codes+=list(INFRASTRUCTURE_LEGACY)
    elif category=='social_policy':codes+=['family_policy']
    original=session.scalar(select(func.coalesce(func.sum(StateBudgetAllocation.amount),0)).where(StateBudgetAllocation.budget_id==budget_id,StateBudgetAllocation.category_code.in_(codes))) or Decimal(0)
    from game.civic_models import TreasuryAdjustment
    admin=session.scalar(select(func.coalesce(func.sum(TreasuryAdjustment.amount),0)).where(TreasuryAdjustment.budget_id==budget_id,TreasuryAdjustment.category.in_(codes))) or Decimal(0)
    return original+admin+sum((transfer_delta(session,budget_id,code) for code in codes),Decimal(0))


@precise
def sector_balances(session,budget):
    from game.infrastructure_models import InfrastructureProject
    from game.military_models import MilitaryExpense,MilitaryMaintenance,MissileDefenseExpense
    from game.intelligence_models import IntelligenceExpense
    from game.commerce_models import MiningExpense,TradeReserveMovement
    approved=normalize(session.execute(select(StateBudgetAllocation.category_code,StateBudgetAllocation.amount).where(StateBudgetAllocation.budget_id==budget.id)).all())
    adjustments={code:Decimal(0) for code in CATEGORY_CODES}
    for row in session.scalars(select(BudgetTransfer).where(BudgetTransfer.budget_id==budget.id)):
        adjustments[canonical(row.source)]-=row.amount;adjustments[canonical(row.destination)]+=row.amount
    from game.civic_models import Road,RoadInvestment,TreasuryAdjustment
    for category,amount in session.execute(select(TreasuryAdjustment.category,func.sum(TreasuryAdjustment.amount)).where(TreasuryAdjustment.budget_id==budget.id).group_by(TreasuryAdjustment.category)):
        adjustments[canonical(category)]+=amount
    from game.research_models import ResearchExpense,AmmunitionFactory
    spent={code:Decimal(0) for code in CATEGORY_CODES}
    from game.social_benefits import details
    benefits=details(session,budget)
    if benefits:
        adjustments['social_policy']+=benefits['carry_in']
        spent['social_policy']=sum(benefits['paid'].values(),Decimal(0))
    spent['research']=session.scalar(select(func.coalesce(func.sum(ResearchExpense.amount),0)).where(ResearchExpense.budget_id==budget.id)) or Decimal(0)
    spent['infrastructure']=session.scalar(select(func.coalesce(func.sum(AmmunitionFactory.cost),0)).where(AmmunitionFactory.budget_id==budget.id)) or Decimal(0)
    spent['infrastructure']+=session.scalar(select(func.coalesce(func.sum(Road.cost),0)).where(Road.budget_id==budget.id)) or Decimal(0)
    spent['infrastructure']+=session.scalar(select(func.coalesce(func.sum(RoadInvestment.amount),0)).where(RoadInvestment.budget_id==budget.id)) or Decimal(0)
    for metric,amount in session.execute(select(InfrastructureProject.metric,func.sum(InfrastructureProject.budget_spent)).where(InfrastructureProject.budget_id==budget.id).group_by(InfrastructureProject.metric)):
        code='infrastructure'
        if code in spent:spent[code]+=amount
    spent['reserve']=session.scalar(select(func.coalesce(func.sum(InfrastructureProject.reserve_spent),0)).where(InfrastructureProject.budget_id==budget.id)) or Decimal(0)
    for model in (MilitaryExpense,MissileDefenseExpense,MilitaryMaintenance):
        spent['armed_forces']+=session.scalar(select(func.coalesce(func.sum(model.amount),0)).where(model.budget_id==budget.id)) or Decimal(0)
    from game.land_war import spent as land_war_spent
    from game.military_training import spent as training_spent
    from game.radar import spent as radar_spent
    spent['armed_forces']+=land_war_spent(session,budget.id)+training_spent(session,budget.id)+radar_spent(session,budget.id)
    spent['security_services']=session.scalar(select(func.coalesce(func.sum(IntelligenceExpense.amount),0)).where(IntelligenceExpense.budget_id==budget.id)) or Decimal(0)
    from game.crime_funding import CrimeFunding   # 16 Nov 2026: środki na walkę z przestępczością
    spent['security_services']+=session.scalar(select(func.coalesce(func.sum(CrimeFunding.paid),0)).where(CrimeFunding.budget_id==budget.id)) or Decimal(0)
    spent['infrastructure']+=session.scalar(select(func.coalesce(func.sum(MiningExpense.amount),0)).where(MiningExpense.budget_id==budget.id)) or Decimal(0)
    # 19 Nov 2026: budowa linii kolejowych (game.rail) — także w saldach sektorów (ekran budżetu, PAGA2)
    from sqlalchemy import inspect as _inspect
    from game.rail_models import RailExpense
    if _inspect(session.connection()).has_table(RailExpense.__tablename__):
        spent['infrastructure']+=session.scalar(select(func.coalesce(func.sum(RailExpense.amount),0)).where(RailExpense.budget_id==budget.id)) or Decimal(0)
    from game.industry_models import IndustryMovement
    # Industry operations are charged to their sector (filters: environment, since 10 Nov 2026).
    for sector,amount in session.execute(select(IndustryMovement.sector,func.sum(IndustryMovement.amount)).where(IndustryMovement.budget_id==budget.id).group_by(IndustryMovement.sector)):
        spent[canonical(sector or 'infrastructure')]+=amount or Decimal(0)
    receipts=session.scalar(select(func.coalesce(func.sum(TradeReserveMovement.amount),0)).where(TradeReserveMovement.budget_id==budget.id,TradeReserveMovement.panstwo_id==budget.panstwo_id,TradeReserveMovement.amount>0)) or Decimal(0)
    spent['reserve']-=session.scalar(select(func.coalesce(func.sum(TradeReserveMovement.amount),0)).where(TradeReserveMovement.budget_id==budget.id,TradeReserveMovement.panstwo_id==budget.panstwo_id,TradeReserveMovement.amount<0)) or Decimal(0)
    from game.loan_models import LoanMovement
    receipts+=session.scalar(select(func.coalesce(func.sum(LoanMovement.amount),0)).where(LoanMovement.budget_id==budget.id,LoanMovement.panstwo_id==budget.panstwo_id,LoanMovement.amount>0)) or Decimal(0)
    spent['reserve']-=session.scalar(select(func.coalesce(func.sum(LoanMovement.amount),0)).where(LoanMovement.budget_id==budget.id,LoanMovement.panstwo_id==budget.panstwo_id,LoanMovement.amount<0)) or Decimal(0)
    # 18 Nov 2026: pożyczki MFW — wypłata zasila rezerwę, dobrowolna spłata ją zmniejsza (pobranie przy zatwierdzeniu
    # budżetu, etap 'collection', jest już ujęte w samym budżecie: imf_collection).
    from game.imf import ready as imf_ready
    if imf_ready(session):
        from game.imf_models import ImfMovement
        imf=lambda condition:session.scalar(select(func.coalesce(func.sum(ImfMovement.amount),0)).where(ImfMovement.budget_id==budget.id,ImfMovement.panstwo_id==budget.panstwo_id,
                                                                                                       ImfMovement.stage.in_(('disbursement','repayment')),condition)) or Decimal(0)
        receipts+=imf(ImfMovement.amount>0)
        spent['reserve']-=imf(ImfMovement.amount<0)
    return {code:{'approved':approved.get(code,Decimal(0)),'adjustment':adjustments[code],
                  'allocated':approved.get(code,Decimal(0))+adjustments[code]+(receipts if code=='reserve' else 0),'spent':spent[code],
                  'remaining':max(Decimal(0),approved.get(code,Decimal(0))+adjustments[code]+(receipts if code=='reserve' else 0)-spent[code])} for code in CATEGORY_CODES}


TRANSFER_TRUST_THRESHOLD=65


def public_trust(session,country_id):
    from models import Spoleczenstwo
    return session.scalar(select(Spoleczenstwo.zaufanie_do_wladzy).where(Spoleczenstwo.panstwo_id==country_id).order_by(Spoleczenstwo.spoleczenstwo_id.desc()).limit(1))


def trust_message(trust):
    """Wording set by the administrator (10 Nov 2026); shown in red when a sector transfer is refused."""
    return f'Społeczeństwo nie ufa władzy wystarczająco ({trust}/100), by pozwolić na swobodne modyfikowanie budżetu i przesuwanie środków między sektorami.'


def defensive_war(session,country_id):
    """17 Nov 2026 (decyzja administratora): wojna obronna na własnym terytorium — państwo prowadzi wojnę kinetyczną z państwem,
    które okupuje jego bazy, miasta lub regiony albo prowadzi na nie armię. Wtedy przesunięcia DO sektora sił zbrojnych
    nie wymagają progu zaufania do władzy (obrona nie może czekać na kolejny budżet)."""
    from sqlalchemy.exc import SQLAlchemyError
    from game.land_war_models import LandArmy,Occupation
    from game.diplomacy_service import at_war,dictionaries,DiplomacyError
    try:
        enemies=set(session.scalars(select(Occupation.occupier_id).where(Occupation.owner_id==country_id,Occupation.status=='ACTIVE')))
        enemies|=set(session.scalars(select(LandArmy.panstwo_id).where(LandArmy.target_country_id==country_id,LandArmy.panstwo_id!=country_id,
                                                                     LandArmy.status.in_(['MARCHING','OCCUPYING']))))
        enemies.discard(country_id)
        if not enemies:return False
        _,states,neutral=dictionaries(session)
        return any(at_war(session,country_id,enemy,states,neutral) for enemy in enemies)
    except (SQLAlchemyError,DiplomacyError):return False   # brak danych wojennych nie może blokować finansów


def transfer_needs_trust(session,country_id,source,destination):
    """Próg zaufania dotyczy przesunięć między sektorami; nie dotyczy rezerwy ani — w wojnie obronnej — zasilenia sił zbrojnych."""
    if 'reserve' in (source,destination):return False
    return not (destination=='armed_forces' and defensive_war(session,country_id))


def defense_transfer_message():
    return 'Wojna obronna: przesunięcia do sektora sił zbrojnych są dozwolone bez względu na zaufanie do władzy.'


def require_public_trust(session,country_id):
    """Moving money between budget sectors needs public trust in the government above 65 (administrator, 10 Nov 2026).
    Transfers to or from the budget reserve are not affected; missing data does not block (no data is not low trust)."""
    trust=public_trust(session,country_id)
    if trust is not None and trust<=TRANSFER_TRUST_THRESHOLD:
        raise FinanceError(trust_message(trust))


@precise
def transfer_funds(user_id,data):
    source,destination=data.get('source'),data.get('destination')
    if not isinstance(source,str) or not isinstance(destination,str) or source not in CATEGORY_CODES or destination not in CATEGORY_CODES or source==destination:
        raise FinanceError('Wybierz dwa różne sektory budżetu.')
    amount=money(data.get('amount'))
    if amount<=0 or decimal_value(data.get('amount'),'Kwota')!=amount:raise FinanceError('Podaj dodatnią kwotę z najwyżej dwoma miejscami po przecinku.')
    try:request_id=str(UUID(data.get('request_id')))
    except (ValueError,TypeError,AttributeError):raise FinanceError('Nieprawidłowy identyfikator przesunięcia.') from None
    with Session(db.engine) as session,session.begin():
        country=_country_for_user(session,user_id,lock=True)
        budget_id=data.get('budget_id')
        if isinstance(budget_id,bool) or not isinstance(budget_id,int):raise FinanceError('Nieprawidłowy budżet.')
        budget=session.scalar(select(StateBudget).where(StateBudget.id==budget_id,StateBudget.panstwo_id==country.PANSTWO_ID).with_for_update())
        if budget is None:raise FinanceError('Nie znaleziono budżetu państwa gracza.')
        if (budget.game_year,budget.period)!=period_key(game_now()):raise FinanceConflict('Można przesuwać środki wyłącznie w bieżącym okresie budżetowym.')
        if transfer_needs_trust(session,country.PANSTWO_ID,source,destination):require_public_trust(session,country.PANSTWO_ID)
        existing=session.scalar(select(BudgetTransfer).where(BudgetTransfer.user_id==user_id,BudgetTransfer.request_id==request_id))
        if existing is not None:
            if (existing.budget_id,existing.source,existing.destination,existing.amount)!=(budget.id,source,destination,amount):raise FinanceConflict('Identyfikator przesunięcia został już wykorzystany.')
            return budget.id
        # Reconcile recurring commitments before testing available military funds.
        from game.military_service import reconcile_maintenance
        if source=='armed_forces':reconcile_maintenance(session,country.PANSTWO_ID,game_now())
        balances=sector_balances(session,budget)
        if amount>balances[source]['remaining']:raise FinanceError('Za mało niewydanych środków w wybranym sektorze.')
        if 'reserve' in (source,destination):
            account=session.scalar(select(StateFinancialAccount).where(StateFinancialAccount.panstwo_id==country.PANSTWO_ID).with_for_update())
            if account is None or account.last_budget_id!=budget.id:raise FinanceConflict('Rachunek rezerwy nie odpowiada bieżącemu budżetowi.')
            if source=='reserve' and amount>account.reserve_balance:raise FinanceError('Za mało środków w rezerwie.')
            account.reserve_balance+=amount if destination=='reserve' else -amount
        session.add(BudgetTransfer(budget_id=budget.id,user_id=user_id,source=source,destination=destination,amount=amount,request_id=request_id,created_at=utc_now(),game_datetime=game_now()))
        session.flush()
        if destination=='armed_forces':reconcile_maintenance(session,country.PANSTWO_ID,game_now())
        return budget.id


@precise
def infrastructure_balance(session,budget):
    from game.infrastructure_models import InfrastructureProject
    from game.commerce_models import MiningExpense
    from game.civic_models import Road,RoadInvestment
    from game.research_models import AmmunitionFactory
    total=effective_allocation(session,budget.id,'infrastructure')
    spent=sum((session.scalar(select(func.coalesce(func.sum(column),0)).where(model.budget_id==budget.id)) or Decimal(0) for model,column in [(InfrastructureProject,InfrastructureProject.budget_spent),(MiningExpense,MiningExpense.amount),(Road,Road.cost),(RoadInvestment,RoadInvestment.amount),(AmmunitionFactory,AmmunitionFactory.cost)]),Decimal(0))
    from game.industry_models import IndustryMovement
    spent+=session.scalar(select(func.coalesce(func.sum(IndustryMovement.amount),0)).where(IndustryMovement.budget_id==budget.id,IndustryMovement.sector=='infrastructure')) or Decimal(0)
    # 19 Nov 2026: budowa linii kolejowych (game.rail) — przed migracją tabeli brak wydatków.
    from sqlalchemy import inspect as _inspect
    from game.rail_models import RailExpense
    if _inspect(session.connection()).has_table(RailExpense.__tablename__):
        spent+=session.scalar(select(func.coalesce(func.sum(RailExpense.amount),0)).where(RailExpense.budget_id==budget.id)) or Decimal(0)
    return total,max(Decimal(0),total-spent)


@precise
def refund_retired_diplomacy(session,country_id,now):
    """One-time, auditable refund; keep approved snapshots untouched."""
    from uuid import uuid5,NAMESPACE_URL
    from models import Panstwo
    from game.models import GamePlayerCountry
    session.scalar(select(Panstwo.PANSTWO_ID).where(Panstwo.PANSTWO_ID==country_id).with_for_update())
    account=session.scalar(select(StateFinancialAccount).where(StateFinancialAccount.panstwo_id==country_id).with_for_update())
    if account is None or account.last_budget_id is None:return Decimal(0)
    key=str(uuid5(NAMESPACE_URL,f'entenda:budget-consolidation:2026-10-25:{account.last_budget_id}'))
    if session.scalar(select(BudgetTransfer.id).where(BudgetTransfer.budget_id==account.last_budget_id,BudgetTransfer.request_id==key)):return Decimal(0)
    available=effective_allocation(session,account.last_budget_id,'diplomacy')
    if available<=0:return Decimal(0)
    owner=country_user_id(session,country_id)
    if owner is None:raise FinanceError('Nie można zapisać zwrotu dyplomacji: brak właściciela państwa.')
    account.reserve_balance=money(account.reserve_balance+available)
    account.updated_at=utc_now()
    session.add(BudgetTransfer(budget_id=account.last_budget_id,user_id=owner,source='diplomacy',destination='reserve',amount=available,request_id=key,created_at=utc_now(),game_datetime=now))
    session.flush()
    return available
