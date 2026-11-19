"""Międzynarodowy Fundusz Walutowy (18 Nov 2026).

Zasady (administrator, zmiana 18 Nov 2026 po analizie tempa gry):
- pula MFW: 1 000 MLD ROI na rok gry; spłaty nie odnawiają puli bieżącego roku; jedno państwo najwyżej 10% puli rocznie;
- odsetki: 5% za każdy cykl budżetowy od pozostałego długu (naliczane przy zatwierdzeniu budżetu kolejnych okresów);
- zdolność kredytowa = 25% transzy podatkowej ostatniego zatwierdzonego budżetu − dług w MFW − niespłacone pożyczki
  od innych państw; najwyżej jedna aktywna pożyczka — nowa dopiero po spłacie poprzedniej;
- wniosek ponad zdolność, limit państwa albo pozostałą pulę jest odrzucany od razu;
- wypłata trafia do rezerwy budżetowej państwa; spłata (całość lub część) z rezerwy — ekran „Podatki i budżet”;
- termin spłaty: 4 cykle budżetowe po okresie wypłaty; przy zatwierdzeniu budżetu okresu, w którym mija termin
  (i każdego następnego, dopóki dług zostaje), MFW pobiera zaległość przed podziałem środków — najwyżej 65%
  środków budżetu (rezerwa początkowa + transza podatkowa); resztę pobiera z kolejnego budżetu.
"""
from decimal import Decimal, ROUND_DOWN
from flask import Blueprint, jsonify, request, redirect, url_for, render_template
from sqlalchemy import select, func, or_, and_
from sqlalchemy.orm import Session
from extensions import db
from models import Panstwo
from game.models import utc_now
from game.forum_models import GameNotification
from game.finance_models import StateFinancialAccount, StateBudget
from game.finance_service import (FinanceError, FinanceConflict, _country_for_user, decimal_value, money, game_now,
                                  period_key, next_period_key, period_label)
from game.budget_transfers import precise
from game.mining_service import request_key
from game.imf_models import ImfFundYear, ImfLoan, ImfMovement

imf_bp = Blueprint('game_imf', __name__, url_prefix='/game/mfw')

ANNUAL_POOL = Decimal('1000000000000.00')    # 1 000 MLD ROI na rok gry
CAPACITY_SHARE = Decimal('0.25')             # 25% transzy podatkowej ostatniego budżetu
COUNTRY_SHARE = Decimal('0.10')              # jedno państwo: najwyżej 10% rocznej puli
INTEREST_RATE = Decimal('0.05')              # 5% za cykl budżetowy
COLLECTION_SHARE = Decimal('0.65')
REPAYMENT_CYCLES = 4
CITY_NAME = 'Port Loyab'                     # siedziba MFW na mapie świata
CENT = Decimal('0.01')
ZERO = Decimal('0.00')
_READY = set()


def ready(session):
    """Czy tabele MFW istnieją (przed migracją budżety działają jak dotąd)."""
    from sqlalchemy import inspect
    key = id(session.get_bind())
    if key in _READY:
        return True
    if inspect(session.connection()).has_table(ImfLoan.__tablename__):
        if session.get_bind().dialect.name == 'mysql':   # w testach (SQLite) id silnika może się powtórzyć
            _READY.add(key)
        return True
    return False


def due_key(key):
    for _ in range(REPAYMENT_CYCLES):
        key = next_period_key(key)
    return key


def _due_filter(key):
    year, period = key
    return or_(ImfLoan.due_year < year, and_(ImfLoan.due_year == year, ImfLoan.due_period <= period))


def notify(session, country_id, text):
    from game.paga_ai_actor import country_user_id
    owner = country_user_id(session, country_id)
    if owner is not None:
        session.add(GameNotification(user_id=owner, notification_type='SYSTEM', system_text='MFW: ' + text, created_at=utc_now()))


def outstanding(session, country_id):
    if not ready(session):
        return ZERO
    return session.scalar(select(func.coalesce(func.sum(ImfLoan.outstanding), 0)).where(
        ImfLoan.borrower_id == country_id, ImfLoan.status == 'active')) or ZERO


def state_debt(session, country_id):
    """Niespłacone pożyczki od innych państw (zaakceptowane, jeszcze nie spłacone)."""
    from game.loan_models import StateLoan
    return session.scalar(select(func.coalesce(func.sum(StateLoan.amount), 0)).where(
        StateLoan.borrower_id == country_id, StateLoan.status == 'accepted')) or ZERO


@precise
def credit(session, country_id):
    account = session.get(StateFinancialAccount, country_id)
    budget = session.get(StateBudget, account.last_budget_id) if account and account.last_budget_id else None
    base = (budget.tax_total * CAPACITY_SHARE).quantize(CENT, rounding=ROUND_DOWN) if budget else ZERO
    imf, states = outstanding(session, country_id), state_debt(session, country_id)
    return {'budget': budget, 'base': base, 'imf': imf, 'states': states, 'capacity': max(ZERO, base - imf - states),
            'reserve': account.reserve_balance if account else ZERO}


def country_limit(pool):
    return (pool * COUNTRY_SHARE).quantize(CENT, rounding=ROUND_DOWN)


def borrowed_in_year(session, country_id, year):
    return session.scalar(select(func.coalesce(func.sum(ImfLoan.amount), 0)).where(
        ImfLoan.borrower_id == country_id, ImfLoan.pool_year == year, ImfLoan.status != 'rejected')) or ZERO


# ---------------- odsetki (5% za cykl budżetowy) ----------------

def _cycles_between(start, key):
    steps = 0
    while start < key and steps < 40:
        start = next_period_key(start)
        steps += 1
    return steps


def projected(loan, key):
    """(dług, odsetki do naliczenia) po naliczeniu odsetek za cykle do okresu `key` włącznie — bez zapisu."""
    rate = Decimal(loan.interest_rate or 0)
    if loan.status != 'active' or rate <= 0 or loan.interest_year is None:
        return loan.outstanding, ZERO
    value, added = loan.outstanding, ZERO
    for _ in range(_cycles_between((loan.interest_year, loan.interest_period), key)):
        step = (value * rate).quantize(CENT)
        value += step
        added += step
    return value, added


@precise
def accrue_interest(session, country_id, key):
    """Nalicza odsetki aktywnych pożyczek państwa za cykle do okresu `key` (przy zatwierdzeniu budżetu tego okresu)."""
    if not ready(session):
        return ZERO
    total = ZERO
    for loan in session.scalars(select(ImfLoan).where(ImfLoan.borrower_id == country_id, ImfLoan.status == 'active').with_for_update()):
        value, added = projected(loan, key)
        if added > 0:
            loan.outstanding, loan.interest = value, loan.interest + added
            total += added
        if loan.interest_year is not None and (loan.interest_year, loan.interest_period) < key:
            loan.interest_year, loan.interest_period = key
    if total > 0:
        notify(session, country_id, f'naliczono odsetki {total} ROI ({INTEREST_RATE * 100:.0f}% za cykl budżetowy od pozostałego długu).')
    return total


def fund_year(session, year, lock=False):
    query = select(ImfFundYear).where(ImfFundYear.game_year == year)
    row = session.scalar(query.with_for_update() if lock else query)
    if row is None and lock:
        row = ImfFundYear(game_year=year, pool=ANNUAL_POOL, lent=ZERO)
        session.add(row)
        session.flush()
    return row


def _amount(value):
    amount = money(value)
    if amount <= 0 or decimal_value(value, 'Kwota') != amount:
        raise FinanceError('Podaj dodatnią kwotę z najwyżej dwoma miejscami po przecinku.')
    return amount


def _lock_country(session, country_id):
    session.scalar(select(Panstwo.PANSTWO_ID).where(Panstwo.PANSTWO_ID == country_id).with_for_update())


@precise
def request_loan(user_id, data):
    from game.trade_service import account_for
    key = request_key(data.get('request_id'))
    amount = _amount(data.get('amount'))
    with Session(db.engine) as session, session.begin():
        country = _country_for_user(session, user_id, lock=True).PANSTWO_ID
        _lock_country(session, country)
        existing = session.scalar(select(ImfLoan).where(ImfLoan.borrower_id == country, ImfLoan.request_id == key))
        if existing is not None:
            if existing.amount != amount:
                raise FinanceConflict('Identyfikator wniosku został już użyty.')
            return _decision(existing)
        now = game_now()
        start = period_key(now)
        due = due_key(start)
        fund = fund_year(session, now.year, lock=True)
        info = credit(session, country)
        account = account_for(session, country)
        remaining = fund.pool - fund.lent
        country_left = country_limit(fund.pool) - borrowed_in_year(session, country, now.year)
        reason = None
        if info['budget'] is None:
            reason = 'Państwo nie ma zatwierdzonego budżetu — MFW nie może ocenić zdolności kredytowej.'
        elif session.scalar(select(ImfLoan.id).where(ImfLoan.borrower_id == country, ImfLoan.status == 'active').limit(1)) is not None:
            reason = 'Państwo ma niespłaconą pożyczkę w MFW — nową można zaciągnąć dopiero po spłacie poprzedniej.'
        elif amount > info['capacity']:
            reason = (f'Kwota przekracza zdolność kredytową państwa ({info["capacity"]} ROI: 25% transzy podatkowej ostatniego budżetu '
                      f'{info["base"]} ROI pomniejszone o dług w MFW {info["imf"]} ROI i u innych państw {info["states"]} ROI).')
        elif amount > country_left:
            reason = f'Kwota przekracza roczny limit państwa w MFW (10% puli; pozostało {max(ZERO, country_left)} ROI w roku {now.year}).'
        elif amount > remaining:
            reason = f'MFW nie ma wystarczających środków w roku {now.year} (pozostało {remaining} ROI).'
        loan = ImfLoan(borrower_id=country, requested_by=user_id, amount=amount, outstanding=ZERO if reason else amount,
                       status='rejected' if reason else 'active', reason=reason, pool_year=now.year,
                       start_year=start[0], start_period=start[1], due_year=due[0], due_period=due[1],
                       capacity=info['capacity'], request_id=key, created_game_at=now,
                       interest_rate=INTEREST_RATE, interest=ZERO, interest_year=start[0], interest_period=start[1])
        session.add(loan)
        session.flush()
        if reason is None:
            fund.lent += amount
            account.reserve_balance = money(account.reserve_balance + amount)
            account.updated_at = utc_now()
            session.add(ImfMovement(loan_id=loan.id, panstwo_id=country, budget_id=account.last_budget_id, stage='disbursement',
                                    amount=amount, request_id=key, game_datetime=now))
            notify(session, country, f'przyznano pożyczkę #{loan.id} na {amount} ROI (wpłynęła do rezerwy budżetowej). '
                                     f'Odsetki: {INTEREST_RATE * 100:.0f}% za każdy cykl budżetowy od pozostałego długu. '
                                     f'Termin spłaty: zatwierdzenie budżetu za {period_label(*due)}.')
        else:
            notify(session, country, f'odrzucono wniosek o {amount} ROI. {reason}')
        return _decision(loan)


def _decision(loan):
    return {'id': loan.id, 'status': loan.status, 'reason': loan.reason, 'amount': str(loan.amount)}


@precise
def repay(user_id, data):
    """Spłata z rezerwy budżetowej: całość (amount='all') albo część; od pożyczek z najbliższym terminem."""
    from game.trade_service import account_for
    key = request_key(data.get('request_id'))
    with Session(db.engine) as session, session.begin():
        country = _country_for_user(session, user_id, lock=True).PANSTWO_ID
        _lock_country(session, country)
        account = account_for(session, country)
        if session.scalar(select(ImfMovement.id).where(ImfMovement.panstwo_id == country, ImfMovement.stage == 'repayment',
                                                       ImfMovement.request_id == key).limit(1)) is not None:
            return {'repaid': None, 'already': True}
        loans = list(session.scalars(select(ImfLoan).where(ImfLoan.borrower_id == country, ImfLoan.status == 'active')
                                     .order_by(ImfLoan.due_year, ImfLoan.due_period, ImfLoan.id).with_for_update()))
        total = sum((loan.outstanding for loan in loans), ZERO)
        if total <= 0:
            raise FinanceError('Państwo nie ma zadłużenia w MFW.')
        amount = total if data.get('amount') == 'all' else _amount(data.get('amount'))
        if amount > total:
            raise FinanceError(f'Kwota przekracza zadłużenie w MFW ({total} ROI).')
        if amount > account.reserve_balance:
            raise FinanceError(f'Za mało środków w rezerwie budżetowej ({account.reserve_balance} ROI). '
                               'Przesuń środki do rezerwy albo spłać mniejszą kwotę.')
        now = game_now()
        left = amount
        for loan in loans:
            if left <= 0:
                break
            part = min(loan.outstanding, left)
            loan.outstanding -= part
            left -= part
            if loan.outstanding == 0:
                loan.status, loan.repaid_game_at = 'repaid', now
            session.add(ImfMovement(loan_id=loan.id, panstwo_id=country, budget_id=account.last_budget_id, stage='repayment',
                                    amount=-part, request_id=key, game_datetime=now))
        account.reserve_balance = money(account.reserve_balance - amount)
        account.updated_at = utc_now()
        notify(session, country, f'spłacono {amount} ROI z rezerwy budżetowej. Pozostały dług: {total - amount} ROI.')
        return {'repaid': str(amount), 'remaining': str(total - amount)}


# ---------------- rozliczenie przy zatwierdzeniu budżetu (finance_service.approve_in_transaction) ----------------

@precise
def reserve_delta(session, country_id, budget_id):
    """Wypłaty i dobrowolne spłaty MFW przypisane do budżetu (None = przed pierwszym budżetem)."""
    if not ready(session):
        return ZERO
    condition = ImfMovement.budget_id.is_(None) if budget_id is None else ImfMovement.budget_id == budget_id
    return session.scalar(select(func.coalesce(func.sum(ImfMovement.amount), 0)).where(
        ImfMovement.panstwo_id == country_id, ImfMovement.stage.in_(('disbursement', 'repayment')), condition)) or ZERO


@precise
def due_amount(session, country_id, key):
    """Zaległy dług (termin spłaty minął przy zatwierdzeniu budżetu okresu `key` lub wcześniej), z odsetkami za ten cykl."""
    if not ready(session):
        return ZERO
    loans = session.scalars(select(ImfLoan).where(ImfLoan.borrower_id == country_id, ImfLoan.status == 'active', _due_filter(key)))
    return sum((projected(loan, key)[0] for loan in loans), ZERO)


def collection_amount(due, available):
    """Ile MFW pobierze z budżetu: zaległość, najwyżej 65% środków budżetu."""
    if due <= 0 or available <= 0:
        return ZERO
    return min(due, (available * COLLECTION_SHARE).quantize(CENT, rounding=ROUND_DOWN))


@precise
def record_collection(session, country_id, budget, amount, now):
    """Rozdziela pobraną kwotę na zaległe pożyczki (od najstarszego terminu) i zapisuje ruchy 'collection'."""
    if amount <= 0:
        return
    key = (budget.game_year, budget.period)
    loans = list(session.scalars(select(ImfLoan).where(ImfLoan.borrower_id == country_id, ImfLoan.status == 'active', _due_filter(key))
                                 .order_by(ImfLoan.due_year, ImfLoan.due_period, ImfLoan.id).with_for_update()))
    left = amount
    for loan in loans:
        if left <= 0:
            break
        part = min(loan.outstanding, left)
        loan.outstanding -= part
        left -= part
        if loan.outstanding == 0:
            loan.status, loan.repaid_game_at = 'repaid', now
        session.add(ImfMovement(loan_id=loan.id, panstwo_id=country_id, budget_id=budget.id, stage='collection', amount=-part,
                                request_id=f'budget:{budget.id}', game_datetime=now))
    if left != 0:
        raise FinanceError('Niezgodność rozliczenia długu w MFW.')
    rest = due_amount(session, country_id, key)
    notify(session, country_id, f'przy zatwierdzeniu budżetu za {period_label(*key)} pobrano {amount} ROI zaległego długu'
                                + (f'. Pozostało do pobrania z kolejnego budżetu: {rest} ROI.' if rest > 0 else ' — zaległość spłacona.'))


# ---------------- dane ekranów ----------------

def _flag(name):
    return url_for('static', filename='flags/' + (name or '').replace(' ', '_') + '.jpg')


@precise
def imf_state(session, country_id):
    now = game_now()
    year = now.year
    names = dict(session.execute(select(Panstwo.PANSTWO_ID, Panstwo.panstwo_nazwa)).all())
    fund = fund_year(session, year)
    pool, lent = (fund.pool, fund.lent) if fund else (ANNUAL_POOL, ZERO)
    borrowers = {}
    for loan in session.scalars(select(ImfLoan).where(ImfLoan.status.in_(('active', 'repaid')),
                                                      or_(ImfLoan.status == 'active', ImfLoan.pool_year == year))):
        row = borrowers.setdefault(loan.borrower_id, {'countryId': loan.borrower_id, 'name': names.get(loan.borrower_id, ''),
                                                      'flag': _flag(names.get(loan.borrower_id)), 'borrowedYear': ZERO, 'outstanding': ZERO})
        if loan.pool_year == year:
            row['borrowedYear'] += loan.amount
        if loan.status == 'active':
            row['outstanding'] += loan.outstanding
    rows = sorted(borrowers.values(), key=lambda r: (-r['borrowedYear'], -r['outstanding'], r['name']))
    info = credit(session, country_id)
    key = period_key(now)
    own = []
    for loan in session.scalars(select(ImfLoan).where(ImfLoan.borrower_id == country_id).order_by(ImfLoan.id.desc()).limit(100)):
        own.append({'id': loan.id, 'amount': str(loan.amount), 'outstanding': str(loan.outstanding), 'status': loan.status,
                    'reason': loan.reason, 'due': period_label(loan.due_year, loan.due_period),
                    'overdue': loan.status == 'active' and (loan.due_year, loan.due_period) <= key,
                    'periodsLeft': _periods_between(key, (loan.due_year, loan.due_period)) if loan.status == 'active' else None,
                    'interestRate': str(Decimal(loan.interest_rate or 0) * 100), 'interest': str(loan.interest or ZERO),
                    'createdAt': loan.created_at.isoformat() + 'Z', 'createdGameAt': loan.created_game_at.isoformat() + 'Z'})
    active = any(item['status'] == 'active' for item in own)
    borrowed = borrowed_in_year(session, country_id, year)
    limit = country_limit(pool)
    max_loan = ZERO if active else max(ZERO, min(info['capacity'], pool - lent, limit - borrowed))
    return {'countryId': country_id, 'year': year, 'pool': str(pool), 'lent': str(lent), 'remaining': str(pool - lent),
            'borrowers': [{**r, 'borrowedYear': str(r['borrowedYear']), 'outstanding': str(r['outstanding'])} for r in rows],
            'credit': {'taxBase': str(info['budget'].tax_total if info['budget'] else ZERO), 'base': str(info['base']), 'imfDebt': str(info['imf']),
                       'stateDebt': str(info['states']), 'capacity': str(info['capacity']), 'maxLoan': str(max_loan),
                       'hasBudget': info['budget'] is not None, 'activeLoan': active,
                       'countryLimit': str(limit), 'countryBorrowed': str(borrowed), 'countryLeft': str(max(ZERO, limit - borrowed))},
            'reserve': str(info['reserve']), 'outstanding': str(info['imf']), 'dueNow': str(due_amount(session, country_id, key)),
            'loans': own, 'rules': {'capacityShare': '25', 'collectionShare': '65', 'cycles': REPAYMENT_CYCLES,
                                    'interestRate': str(INTEREST_RATE * 100), 'countryShare': '10'}}


def _periods_between(current, due):
    steps, key = 0, current
    while key < due and steps < 40:
        key = next_period_key(key)
        steps += 1
    return steps


def imf_city_id(session):
    from models import Miasto
    return session.scalar(select(Miasto.miasto_id).where(Miasto.miasto_nazwa == CITY_NAME).limit(1))


# ---------------- trasy ----------------

@imf_bp.get('')
def page():
    from game.forum import player
    from game.country_summary import country_summary
    user, country = player()
    if user is None:
        return redirect(url_for('wejscie'))
    response = render_template('game/imf.html', game_user=user, game_country=country_summary(country), game_home_url=url_for('game_main_page'),
                               game_logout_url=url_for('game_logout'), game_active_page='imf',
                               imf_config={'stateUrl': url_for('game_imf.state'), 'changeUrl': url_for('game_imf.change'),
                                           'financeUrl': url_for('game_finance.page'), 'countryId': country.PANSTWO_ID if country else None})
    db.session.rollback()
    return response


@imf_bp.get('/stan')
def state():
    from game.forum import player
    user, country = player()
    if user is None:
        return jsonify(error='Zaloguj się ponownie.'), 401
    data = imf_state(db.session, country.PANSTWO_ID)
    db.session.rollback()
    response = jsonify(data)
    response.headers['Cache-Control'] = 'no-store'
    return response


@imf_bp.post('/zmien')
def change():
    from game.forum import player
    from game.military import csrf_valid
    user, country = player()
    if user is None:
        return jsonify(error='Zaloguj się ponownie.'), 401
    if not csrf_valid():
        return jsonify(error='Sesja formularza wygasła. Odśwież stronę.'), 403
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or data.get('action') not in ('request', 'repay'):
        return jsonify(error='Nieprawidłowe dane.'), 400
    try:
        result = request_loan(user.id, data) if data['action'] == 'request' else repay(user.id, data)
    except FinanceError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(ok=True, **result)
