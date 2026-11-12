from game.paga_ai_actor import country_user_id
"""Pożyczki państwowe: akceptacja, jawne uzupełnienie rezerwy i spłata."""
from decimal import Decimal
from uuid import uuid5,NAMESPACE_URL
from flask import Blueprint,request,jsonify,url_for
from sqlalchemy import select,func,or_
from sqlalchemy.orm import Session
from extensions import db
from models import Panstwo
from game.models import GamePlayerCountry,GameUser,utc_now
from game.forum_models import GameNotification
from game.finance_models import StateFinancialAccount,StateBudget,BudgetTransfer,BudgetCategory
from game.finance_service import FinanceError,FinanceConflict,_country_for_user,decimal_value,money,game_now,period_key,CATEGORY_CODES
from game.budget_transfers import precise,sector_balances
from game.mining_service import request_key
from game.loan_models import StateLoan,LoanMovement
from game.trade_service import account_for
from game.governance import controller_id

loans_bp=Blueprint('game_loans',__name__,url_prefix='/game/pozyczki')


@precise
def loan_delta(session,country_id,budget_id):
    condition=LoanMovement.budget_id.is_(None) if budget_id is None else LoanMovement.budget_id==budget_id
    return session.scalar(select(func.coalesce(func.sum(LoanMovement.amount),0)).where(LoanMovement.panstwo_id==country_id,condition)) or Decimal(0)


def notify(session,country_id,text):
    owner=country_user_id(session,country_id)
    if owner is not None:session.add(GameNotification(user_id=owner,notification_type='SYSTEM',system_text='Pożyczka: '+text,created_at=utc_now()))


@precise
def request_loan(user_id,data):
    from game.military_service import natural
    key=request_key(data.get('request_id'));amount=money(data.get('amount'))
    if amount<=0 or decimal_value(data.get('amount'),'Kwota')!=amount:raise FinanceError('Podaj dodatnią kwotę z najwyżej dwoma miejscami po przecinku.')
    lender=natural(data.get('lender_id'),'Państwo finansujące',1)
    with Session(db.engine) as session,session.begin():
        borrower=_country_for_user(session,user_id).PANSTWO_ID
        list(session.scalars(select(Panstwo.PANSTWO_ID).where(Panstwo.PANSTWO_ID.in_(sorted({borrower,lender}))).order_by(Panstwo.PANSTWO_ID).with_for_update()))
        existing=session.scalar(select(StateLoan).where(StateLoan.borrower_id==borrower,StateLoan.request_id==key))
        if existing:
            if (existing.lender_id,existing.amount)!=(lender,amount):raise FinanceConflict('Identyfikator wniosku został już użyty.')
            return existing.id
        active=session.scalar(select(GameUser.id).join(GamePlayerCountry).where(GamePlayerCountry.panstwo_id==lender,GameUser.is_active.is_(True)))
        from game.paga_ai_actor import configured
        if active is None and configured():
            from game.diplomacy_service import npc_eligible
            active=True if npc_eligible(session,lender) else None
        if lender==borrower or controller_id(session,lender)!=lender or active is None:raise FinanceError('Wybierz inne państwo zarządzane przez aktywnego gracza.')
        loan=StateLoan(borrower_id=borrower,lender_id=lender,requested_by=user_id,amount=amount,request_id=key,status='pending')
        session.add(loan);session.flush()
        name=session.scalar(select(Panstwo.panstwo_nazwa).where(Panstwo.PANSTWO_ID==borrower))
        notify(session,lender,f'{name} prosi o {amount} ROI. Zaakceptuj lub odrzuć w panelu budżetu.');return loan.id


@precise
def settle_loan(user_id,data):
    from game.military_service import natural,reconcile_maintenance
    id=natural(data.get('loan_id'),'Pożyczka',1);action=data.get('action')
    if action not in ('accept','reject','cancel','repay'):raise FinanceError('Nieprawidłowa decyzja.')
    with Session(db.engine) as session,session.begin():
        own=_country_for_user(session,user_id).PANSTWO_ID
        preview=session.get(StateLoan,id)
        if preview is None or own not in (preview.borrower_id,preview.lender_id):raise FinanceError('Nie znaleziono własnej pożyczki.')
        ids=sorted({preview.borrower_id,preview.lender_id})
        list(session.scalars(select(Panstwo.PANSTWO_ID).where(Panstwo.PANSTWO_ID.in_(ids)).order_by(Panstwo.PANSTWO_ID).with_for_update()))
        loan=session.scalar(select(StateLoan).where(StateLoan.id==id).with_for_update().execution_options(populate_existing=True))
        expected_owner=loan.borrower_id if action in ('cancel','repay') else loan.lender_id
        if own!=expected_owner:raise FinanceError('Ta decyzja należy do drugiej strony pożyczki.')
        final={'accept':'accepted','reject':'rejected','cancel':'cancelled','repay':'repaid'}[action]
        if loan.status==final or action=='accept' and loan.status=='repaid':return loan.id
        if loan.status!=('accepted' if action=='repay' else 'pending'):raise FinanceConflict('Stan pożyczki zmienił się. Odśwież listę.')
        if action in ('reject','cancel'):
            loan.status=final;loan.resolved_at=utc_now()
            notify(session,loan.borrower_id if action=='reject' else loan.lender_id,f'Wniosek #{id} na {loan.amount} ROI został '+('odrzucony.' if action=='reject' else 'wycofany.'));return id
        payer=loan.borrower_id if action=='repay' else loan.lender_id
        receiver=loan.lender_id if action=='repay' else loan.borrower_id
        accounts={country:account_for(session,country) for country in ids}
        account=accounts[payer];gap=max(Decimal(0),loan.amount-account.reserve_balance)
        if data.get('expected_gap') is not None and money(data['expected_gap'])!=gap:raise FinanceConflict('Stan rezerwy zmienił się. Odśwież listę i ponownie sprawdź kwotę uzupełnienia.')
        if gap:
            source=data.get('funding_category')
            if source not in CATEGORY_CODES or source=='reserve':raise FinanceError(f'Brakuje {gap} ROI w rezerwie. Wybierz sektor budżetu, z którego świadomie przesuniesz brakującą kwotę.')
            budget=session.get(StateBudget,account.last_budget_id) if account.last_budget_id else None
            if budget is None or (budget.game_year,budget.period)!=period_key(game_now()):raise FinanceError('Nie ma bieżącego budżetu do uzupełnienia rezerwy.')
            if source=='armed_forces':reconcile_maintenance(session,payer)
            if sector_balances(session,budget)[source]['remaining']<gap:raise FinanceError('Wybrany sektor nie ma wystarczającej ilości niewydanych środków.')
            key=str(uuid5(NAMESPACE_URL,f'loan-funding:{loan.id}:{action}:{budget.id}'))
            session.add(BudgetTransfer(budget_id=budget.id,user_id=user_id,source=source,destination='reserve',amount=gap,request_id=key,created_at=utc_now(),game_datetime=game_now()))
            account.reserve_balance+=gap
        for country,amount in ((payer,-loan.amount),(receiver,loan.amount)):
            target=accounts[country];target.reserve_balance=money(target.reserve_balance+amount);target.updated_at=utc_now()
            session.add(LoanMovement(loan_id=id,panstwo_id=country,budget_id=target.last_budget_id,amount=amount,stage='repayment' if action=='repay' else 'disbursement'))
        loan.status=final;loan.resolved_at=utc_now()
        for country in ids:notify(session,country,f'Pożyczka #{id}, {loan.amount} ROI: '+('spłacona. Środki wróciły do rezerwy wierzyciela.' if action=='repay' else 'zaakceptowana. Środki przekazano między rezerwami państw.'))
        return id


@precise
def loan_state(session,country_id):
    names=dict(session.execute(select(Panstwo.PANSTWO_ID,Panstwo.panstwo_nazwa)).all())
    active=set(session.scalars(select(GamePlayerCountry.panstwo_id).join(GameUser).where(GameUser.is_active.is_(True))))
    from game.paga_ai_actor import configured
    if configured():
        from game.autonomy_engine import eligible_ids
        active.update(eligible_ids(session))
    account=session.get(StateFinancialAccount,country_id);reserve=account.reserve_balance if account else Decimal(0)
    budget=session.get(StateBudget,account.last_budget_id) if account and account.last_budget_id else None
    options=[]
    if budget and (budget.game_year,budget.period)==period_key(game_now()):
        from game.military_service import reconcile_maintenance
        reconcile_maintenance(session,country_id)
        balances=sector_balances(session,budget)
        labels=dict(session.execute(select(BudgetCategory.code,BudgetCategory.name_pl)).all())
        options=[{'code':code,'label':labels.get(code,code),'available':str(balances[code]['remaining'])} for code in CATEGORY_CODES if code!='reserve']
    items=[]
    for loan in session.scalars(select(StateLoan).where(or_(StateLoan.borrower_id==country_id,StateLoan.lender_id==country_id)).order_by(StateLoan.id.desc()).limit(200)):
        items.append({'id':loan.id,'borrowerId':loan.borrower_id,'lenderId':loan.lender_id,'borrower':names.get(loan.borrower_id,''),'lender':names.get(loan.lender_id,''),'amount':str(loan.amount),'status':loan.status,'ownRequest':loan.borrower_id==country_id,'gap':str(max(Decimal(0),loan.amount-reserve)),'createdAt':loan.created_at.isoformat()+'Z'})
    return {'countryId':country_id,'reserve':str(reserve),'loans':items,'fundingOptions':options,'countries':{str(id):name for id,name in names.items() if id!=country_id and id in active and controller_id(session,id)==id}}


@loans_bp.get('/stan')
def state():
    from game.forum import player
    user,country=player()
    if user is None:return jsonify(error='Zaloguj się ponownie.'),401
    data=loan_state(db.session,country.PANSTWO_ID);db.session.commit();response=jsonify(data);response.headers['Cache-Control']='no-store';return response


@loans_bp.post('/zmien')
def change():
    from game.forum import player
    from game.military import csrf_valid
    user,country=player()
    if user is None:return jsonify(error='Zaloguj się ponownie.'),401
    if not csrf_valid():return jsonify(error='Sesja formularza wygasła. Odśwież stronę.'),403
    data=request.get_json(silent=True)
    if not isinstance(data,dict):return jsonify(error='Nieprawidłowe dane.'),400
    try:id=request_loan(user.id,data) if data.get('action')=='request' else settle_loan(user.id,data)
    except FinanceError as exc:return jsonify(error=str(exc)),400
    return jsonify(ok=True,id=id)
