"""Wskaźniki infrastruktury regionów państwa gracza."""

from game.governance import controlled_ids, controller_id
from flask import Blueprint, abort, redirect, render_template, session, url_for, request, jsonify
import hmac
import secrets
from game.infrastructure_models import InfrastructureProject
from game.infrastructure_service import complete_due, start_project, quote, region_population
from game.finance_service import FinanceError, game_now, period_key
from game.finance_models import StateBudget, StateBudgetAllocation, StateFinancialAccount
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.orm import lazyload

from extensions import db
from game.country_summary import country_summary, own_metropolitan_region_ids
from game.models import GamePlayerCountry, GameUser
from models import Panstwo, Region, Miasto


infrastructure_bp = Blueprint("game_infrastructure", __name__, url_prefix="/game/infrastruktura")


METRICS = (
    ("road", "Infrastruktura drogowa", "region_stan_infra_drogowej", "DROGA.svg"),
    ("rail", "Infrastruktura kolejowa", "region_stan_infra_kolejowej", "KOLEJ.svg"),
    ("energy", "Infrastruktura energetyczna", "region_stan_infra_energetycznej", "ENERGIA.svg"),
    ("housing", "Infrastruktura mieszkaniowa", "region_stan_infra_mieszkalnej", "MIESZKANIA.svg"),
    ("port", "Infrastruktura portowa", "region_stan_infra_portowej", "PORT.svg"),
    ("connection", "Poziom skomunikowania", "region_poziom_skomunikowania", "SKOMUNIKOWANIE.svg"),
)


def indicator(value):
    if value is None or not 0 <= value <= 100:
        return {"value": None, "color": "#7f8c8d"}
    # Progi infrastruktury: 90, 75, 60, 40.
    color = ("darkgreen" if value >= 90 else "green" if value >= 75 else
             "#f1c40f" if value >= 60 else "#e67e22" if value >= 40 else "#e74c3c")
    return {"value": value, "color": color}


@infrastructure_bp.get("")
def page():
    from game.forum import player
    user,country=player()
    if user is None:return redirect(url_for('wejscie'))


    complete_due(db.session, game_now(), country.PANSTWO_ID)
    session.setdefault('game_csrf_token', secrets.token_urlsafe(32))
    projects = db.session.scalars(select(InfrastructureProject).where(
        InfrastructureProject.panstwo_id == country.PANSTWO_ID,
        InfrastructureProject.completed_at.is_(None))).all()
    project_map = {}
    now = game_now()
    for project in projects:
        project_map.setdefault(str(project.region_id), {})[project.metric] = {
            'end': project.ends_at.strftime('%d.%m.%Y'), 'levels': project.levels,
            'progress': max(0, min(100, int((now - project.starts_at).total_seconds() / (project.ends_at - project.starts_at).total_seconds() * 100))),
        }
    region_objects = db.session.scalars(select(Region).options(lazyload("*")).where(Region.panstwo_id.in_(controlled_ids(db.session, country.PANSTWO_ID)))).all()
    details = {}
    for region in region_objects:
        population = region_population(db.session, region)
        details[str(region.region_id)] = {
            'population': population, 'coastal': region.region_polozenie_id not in (None, 1),
            'projects': project_map.get(str(region.region_id), {}),
            'quotes': {code: {'unit': str(quote(population, code)[0]), 'days': quote(population, code)[1]}
                       for code, _, _, _ in METRICS} if population > 0 else {},
        }
    year, period = period_key(now)
    budget = db.session.scalar(select(StateBudget).where(StateBudget.panstwo_id == country.PANSTWO_ID, StateBudget.game_year == year, StateBudget.period == period))
    funds = {}
    if budget:
        from game.budget_transfers import infrastructure_balance
        total,available=infrastructure_balance(db.session,budget)
        funds={code:str(available) for code,_,_,_ in METRICS}
    account = db.session.get(StateFinancialAccount, country.PANSTWO_ID)
    reserve = str(account.reserve_balance if account else 0)
    cities = db.session.execute(select(Miasto.miasto_id, Miasto.miasto_nazwa, Miasto.region_id).where(
        Miasto.panstwo_id.in_(controlled_ids(db.session, country.PANSTWO_ID)), Miasto.czy_na_mapie == 'TAK')).all()
    rows = db.session.execute(select(
        Region.region_id, Region.region_nazwa,
        *[getattr(Region, field) for _, _, field, _ in METRICS],
    ).where(Region.panstwo_id.in_(controlled_ids(db.session, country.PANSTWO_ID))).order_by(Region.region_id)).all()
    regions = {
        str(row.region_id): {
            "name": row.region_nazwa,
            **details[str(row.region_id)],
            "indicators": {code: indicator(getattr(row, field)) for code, _, field, _ in METRICS},
        } for row in rows
    }
    from game.foreign_mining import map_regions
    foreign_regions=map_regions(db.session,country.PANSTWO_ID)
    metrics = [{"code": code, "label": label, "icon": url_for("static", filename="icons/" + filename)}
               for code, label, _, filename in METRICS]
    from game.military_flights import calibration
    response = render_template(
        "game/infrastructure.html", game_user=user, game_country=country_summary(country),
        game_home_url=url_for("game_main_page"), game_logout_url=url_for("game_logout"),
        game_active_page="infrastructure", metrics=metrics,
        infrastructure_map={
            "coastUrl":'/game/obrona-panstwa/wybrzeze/0',"kmPerUnit":calibration(db.session).km_per_unit,
            "funds": funds, "reserve": reserve, "csrf": session["game_csrf_token"], "startUrl": url_for("game_infrastructure.expand"),
            "metropolitanRegionIds": own_metropolitan_region_ids(country.PANSTWO_ID),
            "countryId": country.PANSTWO_ID, "regions": regions, "foreignRegions": foreign_regions, "metrics": metrics,
            "cities": {str(city.miasto_id): {"name": city.miasto_nazwa, "regionId": str(city.region_id)} for city in cities},
            "citiesUrl": url_for("static", filename="maps/entenda_miasta.geojson"),
            "constructionIcon": url_for("static", filename="icons/PRACE BUDOWLANE.svg"),
            "expandButtonIcon": url_for("static", filename="icons/PRACE BUDOWLANE 2.svg"),
            "countriesUrl": url_for('region_sovereignty.country_boundaries'),
            "regionsUrl": url_for("static", filename="maps/entenda_regiony.geojson"),
        },
    )
    db.session.commit()
    return response


@infrastructure_bp.post('/rozbuduj')
def expand():
    user_id = session.get('game_user_id')
    user = db.session.get(GameUser, user_id) if type(user_id) is int else None
    if user is None or not user.is_active:
        return jsonify(error='Zaloguj się ponownie.'), 401
    expected = session.get('game_csrf_token', '')
    supplied = request.headers.get('X-CSRF-Token', '')
    if not expected or not hmac.compare_digest(expected.encode(), supplied.encode()):
        return jsonify(error='Nieprawidłowy token formularza. Odśwież stronę.'), 403
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify(error='Nieprawidłowe dane formularza.'), 400
    if type(data.get('region_id')) is not int or type(data.get('use_reserve', False)) is not bool:
        return jsonify(error='Nieprawidłowe dane formularza.'), 400
    try:
        start_project(user_id, data['region_id'], data.get('metric'), data.get('levels'), data.get('use_reserve', False))
    except FinanceError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(ok=True)


# Road building was removed from the game (administrator decision, 10 Nov 2026). Existing roads stay in the data;
# the WIKI administrator road builder (routes_civic_admin) is unchanged.


@infrastructure_bp.get('/obiekty/stan')
def industry_state():
    from game.forum import player
    from game.industry_service import industry_state as get_state
    from game.research_service import settle_production
    user,country=player()
    if user is None:return jsonify(error='Zaloguj się ponownie.'),401
    settle_production(db.session,country.PANSTWO_ID)
    data=get_state(db.session,country.PANSTWO_ID);db.session.commit()
    response=jsonify(data);response.headers['Cache-Control']='no-store';return response


@infrastructure_bp.post('/obiekty/zmien')
def industry_change():
    from game.forum import player
    from game.military import csrf_valid
    from game.industry_service import change_industry
    user,country=player()
    if user is None:return jsonify(error='Zaloguj się ponownie.'),401
    if not csrf_valid():return jsonify(error='Sesja formularza wygasła.'),403
    data=request.get_json(silent=True)
    if not isinstance(data,dict):return jsonify(error='Nieprawidłowe dane.'),400
    user_id=user.id;db.session.rollback()
    try:
        if data.get('category')=='mine' and data.get('action')=='build':
            from game.mining_service import build_mine
            result=build_mine(user_id,{**data,'resource':data.get('kind')})
        else:result=change_industry(user_id,data)
        return jsonify(ok=True,id=result)
    except FinanceError as error:return jsonify(error=str(error)),400
