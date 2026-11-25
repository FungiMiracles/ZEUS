"""Drogi świata i finanse gry w panelu administratora WIKI."""
import hmac,secrets
from uuid import uuid4
from flask import Blueprint,abort,request,session,jsonify,render_template,redirect,url_for,flash
from sqlalchemy import select
from sqlalchemy.orm import lazyload
from extensions import db
from permissions import wymaga_roli
from models import Panstwo,Region,Miasto
from game.civic_models import Road,TreasuryAdjustment,CountryTaxPolicy
from game.finance_models import StateBudget,StateFinancialAccount,StateTaxAssessment
from game.finance_service import FinanceError

wiki_civic_bp=Blueprint('wiki_civic',__name__,url_prefix='/admin')


def token():
    session.setdefault('wiki_civic_csrf',secrets.token_urlsafe(32));return session['wiki_civic_csrf']


def validate():
    supplied=request.headers.get('X-CSRF-Token','') or request.form.get('csrf_token','')
    if not session.get('wiki_civic_csrf') or not hmac.compare_digest(session['wiki_civic_csrf'].encode(),supplied.encode()):abort(403,description='Sesja formularza wygasła.')


def actor():return str(session.get('username') or session.get('user_id') or 'Administrator WIKI')[:120]


@wiki_civic_bp.get('/drogi')
@wymaga_roli('wszechmocny')
def roads_page():
    countries=dict(db.session.execute(select(Panstwo.PANSTWO_ID,Panstwo.panstwo_nazwa).order_by(Panstwo.panstwo_nazwa)).all())
    return render_template('admin_roads.html',road_config={
        'admin':True,'csrf':token(),'countries':{str(id):name for id,name in countries.items()},
        'countryId':request.args.get('country_id',type=int) or next(iter(countries),0),
        'cities':{str(id):{'name':name,'regionId':str(region),'population':population,'capital':city_type==1} for id,name,region,population,city_type in db.session.execute(select(Miasto.miasto_id,Miasto.miasto_nazwa,Miasto.region_id,Miasto.miasto_populacja,Miasto.miasto_typ_id).where(Miasto.czy_na_mapie=='TAK'))},
        'regionOwners':{str(id):owner for id,owner in db.session.execute(select(Region.region_id,Region.panstwo_id))},
        'regionsUrl':url_for('static',filename='maps/entenda_regiony.geojson'),
        'citiesUrl':url_for('static',filename='maps/entenda_miasta.geojson'),
        'stateUrl':url_for('wiki_civic.roads_state'),'quoteUrl':url_for('wiki_civic.roads_change',operation='wycena'),'buildUrl':url_for('wiki_civic.roads_change',operation='buduj')})


@wiki_civic_bp.get('/drogi/stan')
@wymaga_roli('wszechmocny')
def roads_state():
    from game.roads import road_data
    response=jsonify(roads=[road_data(road) for road in db.session.scalars(select(Road).order_by(Road.id))]);response.headers['Cache-Control']='no-store';return response


@wiki_civic_bp.post('/drogi/<operation>')
@wymaga_roli('wszechmocny')
def roads_change(operation):
    from game.roads import quote_road,build_road
    validate();data=request.get_json(silent=True)
    if not isinstance(data,dict) or type(data.get('country_id')) is not int:return jsonify(error='Wybierz państwo.'),400
    try:
        if operation in ('ulepsz','ulepsz-wycena'):
            from game.road_projects import upgrade_road
            result=upgrade_road(None,data,admin_country_id=data['country_id'],admin_actor=actor(),preview=operation=='ulepsz-wycena')
            return jsonify(**({'quote':result} if operation=='ulepsz-wycena' else {'road':result}))
        if operation=='wycena':return jsonify(quote=quote_road(db.session,data['country_id'],data,admin=True))
        if operation=='buduj':return jsonify(road=build_road(None,data,admin_country_id=data['country_id'],admin_actor=actor()))
    except FinanceError as exc:return jsonify(error=str(exc)),400
    return jsonify(error='Nieprawidłowa operacja.'),404


@wiki_civic_bp.route('/gospodarka/<int:country_id>/budzet',methods=['GET','POST'])
@wymaga_roli('wszechmocny')
def budget(country_id):
    from game.admin_finance import adjust
    from game.budget_transfers import sector_balances
    from game.budget_categories import CODES
    from game.finance_models import BudgetCategory
    country=db.session.scalar(select(Panstwo).options(lazyload('*')).where(Panstwo.PANSTWO_ID==country_id))
    if country is None:abort(404)
    error=None
    if request.method=='POST':
        validate()
        try:
            data={name:request.form.get(name) for name in ('request_id','category','amount','reason')}
            if request.form.get('change_taxes'):data['taxes']={'pit_rate':request.form.get('pit_rate')}
            adjust(country_id,data,actor());flash('Zapisano korektę finansów państwa.','success');return redirect(url_for('wiki_civic.budget',country_id=country_id),code=303)
        except FinanceError as exc:error=str(exc)
    account=db.session.get(StateFinancialAccount,country_id)
    plan=db.session.get(StateBudget,account.last_budget_id) if account and account.last_budget_id else None
    policy=db.session.get(CountryTaxPolicy,country_id)
    assessment=db.session.scalar(select(StateTaxAssessment).where(StateTaxAssessment.budget_id==plan.id)) if plan else None
    return render_template('admin_state_budget.html',country=country,account=account,plan=plan,balances=sector_balances(db.session,plan) if plan else {},
        categories=list(db.session.execute(select(BudgetCategory.code,BudgetCategory.name_pl).where(BudgetCategory.code.in_(CODES)).order_by(BudgetCategory.display_order))),tax_policy=policy or assessment,csrf=token(),request_id=request.form.get('request_id') or str(uuid4()),error=error,
        changes=list(db.session.scalars(select(TreasuryAdjustment).where(TreasuryAdjustment.panstwo_id==country_id).order_by(TreasuryAdjustment.id.desc()).limit(50)))) ,400 if error else 200


def player_budget_rows():
    """25 Nov 2026: państwa graczy ludzkich i stan budżetu bieżącego okresu (wymuszenie zatwierdzenia przez administratora)."""
    from game.models import GameUser, GamePlayerCountry
    from game.paga_ai_models import PagaAiIdentity
    from game.finance_models import StateFinancialPeriod
    from game.finance_service import game_now, period_key, period_label, _previous_budget
    year, period = period_key(game_now())
    rows = db.session.execute(
        select(GamePlayerCountry.panstwo_id, Panstwo.panstwo_nazwa, Panstwo.czy_suwerenny, GameUser.username, GameUser.is_active)
        .join(GameUser, GameUser.id == GamePlayerCountry.user_id)
        .join(Panstwo, Panstwo.PANSTWO_ID == GamePlayerCountry.panstwo_id)
        .where(GameUser.id.not_in(select(PagaAiIdentity.user_id)))
        .order_by(Panstwo.panstwo_nazwa)).all()
    result = []
    for country_id, name, sovereign, username, active in rows:
        budget = db.session.scalar(select(StateBudget).where(StateBudget.panstwo_id == country_id, StateBudget.game_year == year, StateBudget.period == period))
        financial = db.session.scalar(select(StateFinancialPeriod.status).where(StateFinancialPeriod.panstwo_id == country_id, StateFinancialPeriod.game_year == year,
                                                                                 StateFinancialPeriod.period == period))
        previous = _previous_budget(db.session, country_id, year, period)
        assessment = db.session.scalar(select(StateTaxAssessment).where(StateTaxAssessment.budget_id == previous.id)) if previous else None
        result.append({'country_id': country_id, 'country': name, 'player': username, 'active': bool(active), 'sovereign': sovereign == 'TAK',
                       'approved': budget is not None, 'approval_mode': budget.approval_mode if budget else None,
                       'pending': budget is None and financial in (None, 'PENDING') and sovereign == 'TAK',
                       'previous': period_label(previous.game_year, previous.period) if previous else None,
                       'previous_tax': assessment.pit_rate if assessment else None})
    return period_label(year, period), result


@wiki_civic_bp.get('/budzety-graczy')
@wymaga_roli('wszechmocny')
def player_budgets():
    label, rows = player_budget_rows()
    return render_template('admin_player_budgets.html', period=label, rows=rows, csrf=token())


@wiki_civic_bp.post('/budzety-graczy/wymus')
@wymaga_roli('wszechmocny')
def force_player_budgets():
    """Wymusza zatwierdzenie budżetu bieżącego okresu: jednego państwa (country_id) albo wszystkich oczekujących (all=1).
    Gra przyjmuje podatek i podział budżetu z poprzedniego okresu (game.finance_service.force_approve_budget)."""
    from flask import current_app
    from game.finance_service import force_approve_budget
    validate()
    _, rows = player_budget_rows()
    pending = {row['country_id']: row for row in rows if row['pending']}
    if request.form.get('all'):
        targets = list(pending)
    else:
        country_id = request.form.get('country_id', type=int)
        if country_id not in pending:
            flash('Budżet tego państwa nie oczekuje na zatwierdzenie.', 'error')
            return redirect(url_for('wiki_civic.player_budgets'), code=303)
        targets = [country_id]
    if not targets:
        flash('Żadne państwo gracza nie oczekuje na zatwierdzenie budżetu.', 'success')
        return redirect(url_for('wiki_civic.player_budgets'), code=303)
    done, failed = [], []
    for country_id in targets:
        name = pending[country_id]['country']
        try:
            result = force_approve_budget(country_id, actor())
            done.append(name)
            current_app.logger.info('WIKI: administrator %s wymusił zatwierdzenie budżetu państwa #%s (%s) — %s, budżet #%s.',
                                    actor(), country_id, name, result['label'], result['budget_id'])
        except FinanceError as exc:
            failed.append(f'{name}: {exc}')
        except Exception:
            current_app.logger.exception('WIKI: wymuszenie zatwierdzenia budżetu państwa #%s nie powiodło się.', country_id)
            failed.append(f'{name}: błąd systemu — szczegóły w dzienniku serwera')
    if done:
        flash('Zatwierdzono budżet: ' + ', '.join(done) + '.', 'success')
    for message in failed:
        flash('Nie zatwierdzono — ' + message, 'error')
    return redirect(url_for('wiki_civic.player_budgets'), code=303)


@wiki_civic_bp.get('/struktura-ludnosci')
@wymaga_roli('wszechmocny')
def population_page():
    from game.population_structure import PopulationStructure
    from services.wiki_world_stats import world_population_structure
    countries=dict(db.session.execute(select(Panstwo.PANSTWO_ID,Panstwo.panstwo_nazwa).order_by(Panstwo.panstwo_nazwa)).all())
    return render_template('admin_population_structure.html',population_config={'csrf':token(),'stateUrl':url_for('wiki_civic.population_state',country_id=0),'saveUrl':url_for('wiki_civic.population_save'),
        'countries':{str(id):name for id,name in countries.items()},'countryId':request.args.get('country_id',type=int),
        'structuredCountries':list(db.session.scalars(select(PopulationStructure.panstwo_id))),
        'worldStructure':world_population_structure(db.session),
        'countriesUrl':url_for('region_sovereignty.country_boundaries')})


@wiki_civic_bp.get('/struktura-ludnosci/stan/<int:country_id>')
@wymaga_roli('wszechmocny')
def population_state(country_id):
    from game.population_structure import structure_data
    try:
        data=structure_data(db.session,country_id);data['population']=str(data['population']) if data['population'] is not None else None;return jsonify(data)
    except FinanceError as exc:return jsonify(error=str(exc)),404


@wiki_civic_bp.post('/struktura-ludnosci/zapisz')
@wymaga_roli('wszechmocny')
def population_save():
    from game.population_structure import save_structure
    validate();data=request.get_json(silent=True)
    if not isinstance(data,dict) or type(data.get('country_id')) is not int:return jsonify(error='Wybierz państwo.'),400
    try:
        result=save_structure(db.session,data['country_id'],data,actor());db.session.commit()
        from services.wiki_world_stats import world_population_structure
        result['worldStructure']=world_population_structure(db.session)
        result['population']=str(result['population']) if result['population'] is not None else None
        return jsonify(result)
    except FinanceError as exc:db.session.rollback();return jsonify(error=str(exc)),400


# 16 Nov 2026: konta graczy ludzkich — zmiana hasła przez administratora WIKI (bez kont technicznych PAGA).
def human_players():
    from game.models import GameUser, GamePlayerCountry
    from game.paga_ai_models import PagaAiIdentity
    technical = select(PagaAiIdentity.user_id)
    rows = db.session.execute(
        select(GameUser, Panstwo.panstwo_nazwa)
        .outerjoin(GamePlayerCountry, GamePlayerCountry.user_id == GameUser.id)
        .outerjoin(Panstwo, Panstwo.PANSTWO_ID == GamePlayerCountry.panstwo_id)
        .where(GameUser.id.not_in(technical), GameUser.password_hash.is_not(None))
        .order_by(GameUser.username_normalized)).all()
    return [{'id': user.id, 'username': user.username, 'email': user.email, 'country': country, 'active': bool(user.is_active),
             'created_at': user.created_at, 'last_login_at': user.last_login_at} for user, country in rows]


@wiki_civic_bp.get('/konta-graczy')
@wymaga_roli('wszechmocny')
def player_accounts():
    from game.passwords import PASSWORD_MIN, PASSWORD_MAX
    return render_template('admin_player_accounts.html', players=human_players(), csrf=token(), password_min=PASSWORD_MIN, password_max=PASSWORD_MAX)


@wiki_civic_bp.post('/konta-graczy/<int:user_id>/haslo')
@wymaga_roli('wszechmocny')
def player_password(user_id):
    from werkzeug.security import generate_password_hash
    from game.models import GameUser, utc_now
    from game.passwords import password_error
    from game.forum_models import GameNotification
    validate()
    if user_id not in {player['id'] for player in human_players()}:
        abort(404)
    password, confirm = request.form.get('password'), request.form.get('password_confirm')
    if (error := password_error(password)):
        flash(error, 'error'); return redirect(url_for('wiki_civic.player_accounts', _anchor=f'gracz-{user_id}'))
    if password != confirm:
        flash('Podane hasła nie są identyczne.', 'error'); return redirect(url_for('wiki_civic.player_accounts', _anchor=f'gracz-{user_id}'))
    user = db.session.scalar(select(GameUser).where(GameUser.id == user_id).with_for_update())
    user.password_hash = generate_password_hash(password)
    db.session.add(GameNotification(user_id=user.id, notification_type='SYSTEM', created_at=utc_now(),
                                    system_text='Administrator zmienił hasło do Twojego konta. Jeśli to nie Ty o to prosiłeś, skontaktuj się z administratorem.'))
    db.session.commit()
    from flask import current_app
    current_app.logger.info('WIKI: administrator %s zmienił hasło konta gracza #%s (%s).', actor(), user.id, user.username)
    flash(f'Zmieniono hasło gracza {user.username}.', 'success')
    return redirect(url_for('wiki_civic.player_accounts', _anchor=f'gracz-{user_id}'))
