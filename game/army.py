"""Siły zbrojne państwa przypisanego do zalogowanego gracza."""

from game.governance import army_for_country, controller_id, controlled_ids
from flask import Blueprint, abort, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import select
from sqlalchemy.orm import lazyload

from extensions import db
from game.country_summary import country_summary
from game.models import GamePlayerCountry, GameUser
from models import Panstwo, Wojsko
from game.military_models import MilitaryBase
from game.military_service import active_counts, military_budget
from game.military_flights import MISSILE_FLIGHT, FIGHTER_SPEED
from game.military_navy import VESSEL_SPEED


army_bp = Blueprint("game_army", __name__, url_prefix="/game/sily-zbrojne")


@army_bp.get("")
def page():
    from game.forum import player
    user,country=player()
    if user is None:return redirect(url_for('wejscie'))


    army = army_for_country(db.session, country.PANSTWO_ID)
    active = active_counts(list(db.session.scalars(select(MilitaryBase).where(MilitaryBase.panstwo_id == country.PANSTWO_ID))),db.session,country.PANSTWO_ID)
    budget,total,available = military_budget(db.session,country.PANSTWO_ID)
    from game.research_service import settle_production
    stock=settle_production(db.session,country.PANSTWO_ID);ammunition=stock.ammunition if stock else 0
    weapon_parameters = {
        field: {'range': (MISSILE_FLIGHT[kind][0], MISSILE_FLIGHT[kind][1]),
                'speed': MISSILE_FLIGHT[kind][2], 'flying': True}
        for field, kind in [('rakiety_krotkiego_zasiegu', 'short'),
                            ('rakiety_sredniego_zasiegu', 'medium'),
                            ('rakiety_dalekiego_zasiegu', 'long')]
    }
    weapon_parameters.update({
        'mysliwce_ilosc': {'speed': FIGHTER_SPEED, 'flying': True},
        'okrety_wojenne_ilosc': {'speed': VESSEL_SPEED, 'flying': False},
        'okrety_podwodne_ilosc': {'speed': VESSEL_SPEED, 'flying': False},
    })
    import secrets
    session.setdefault('game_csrf_token',secrets.token_urlsafe(32))
    from game.military_training import BRANCHES,ARMY_FIELDS,MAX_LEVEL,levels
    training={'levels':levels(army),'prices':{branch:str(price) for branch,(_,_,price) in BRANCHES.items()},'labels':{branch:label for branch,(_,label,_) in BRANCHES.items()},
              'max':MAX_LEVEL,'available':str(available),'url':url_for('game_army.train'),'csrf':session['game_csrf_token']}
    from game.military_recruitment import summary as recruitment_summary
    recruitment=recruitment_summary(db.session,country.PANSTWO_ID,army)
    recruitment.update(url=url_for('game_army.recruit'),csrf=session['game_csrf_token'])
    rendered=render_template(
        "game/army.html", game_user=user, game_country=country_summary(country),
        game_home_url=url_for("game_main_page"), game_logout_url=url_for("game_logout"),
        game_active_page="army", army=army, weapon_parameters=weapon_parameters, active=active, military_budget_total=total,interceptor_ammunition=ammunition,
        training=training,training_fields=ARMY_FIELDS,recruitment=recruitment,
        nuclear_total=__import__('game.nuclear',fromlist=['total']).total(db.session,country.PANSTWO_ID),
        satellites=__import__('game.satellites',fromlist=['summary']).summary(db.session,country.PANSTWO_ID),   # 26 Nov 2026
    )
    db.session.commit()
    return rendered



@army_bp.post("/wyszkol")
def train():
    """Podniesienie poziomu wyszkolenia sił lądowych, morskich albo powietrznych (budżet sił zbrojnych)."""
    from game.forum import player
    from game.military import csrf_valid
    from game.finance_service import FinanceError
    from game.military_training import train as buy_training
    user,country=player()
    if user is None:return jsonify(error='Zaloguj się ponownie.'),401
    if not csrf_valid():return jsonify(error='Sesja formularza wygasła. Odśwież stronę.'),403
    data=request.get_json(silent=True)
    if not isinstance(data,dict):return jsonify(error='Nieprawidłowe dane.'),400
    db.session.rollback()
    try:level=buy_training(user.id,data)
    except FinanceError as exc:return jsonify(error=str(exc)),400
    return jsonify(ok=True,level=level)


@army_bp.post("/rekrutacja")
def recruit():
    """16 Nov 2026: rekrutacja żołnierzy do służby czynnej albo zwolnienie z rezerwy (JSON: action, branch, count)."""
    from game.forum import player
    from game.military import csrf_valid
    from game.finance_service import FinanceError
    from game.military_recruitment import change_for_user
    user,country=player()
    if user is None:return jsonify(error='Zaloguj się ponownie.'),401
    if not csrf_valid():return jsonify(error='Sesja formularza wygasła. Odśwież stronę.'),403
    data=request.get_json(silent=True)
    if not isinstance(data,dict):return jsonify(error='Nieprawidłowe dane.'),400
    db.session.rollback()
    try:result=change_for_user(user.id,data)
    except FinanceError as exc:return jsonify(error=str(exc)),400
    return jsonify(ok=True,recruitment=result)
