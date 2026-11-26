"""Trasy satelitów szpiegowskich (26 Nov 2026): stan warstwy map, wyniesienie na orbitę, misje rozpoznawcze."""
from flask import Blueprint, jsonify, request
from extensions import db
from game.forum import player
from game.finance_service import FinanceError, game_now

satellites_bp = Blueprint('game_satellites', __name__, url_prefix='/game/satelity')


@satellites_bp.get('/stan')
def state():
    from game.satellites import screen_config, mission_list
    user, country = player()
    if user is None or country is None:
        return jsonify(error='Zaloguj się ponownie.'), 401
    try:
        data = screen_config(db.session, country.PANSTWO_ID, game_now())
        data['reports'] = mission_list(db.session, country.PANSTWO_ID)
    finally:
        db.session.rollback()
    response = jsonify(data)
    response.headers['Cache-Control'] = 'no-store'
    return response


def _action(handler):
    from game.military import csrf_valid
    user, country = player()
    if user is None:
        return jsonify(error='Zaloguj się ponownie.'), 401
    if not csrf_valid():
        return jsonify(error='Sesja formularza wygasła. Odśwież stronę.'), 403
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error='Nieprawidłowe dane formularza.'), 400
    user_id = user.id
    db.session.rollback()
    try:
        return jsonify(ok=True, **handler(user_id, data))
    except FinanceError as exc:
        return jsonify(error=str(exc)), 400


@satellites_bp.post('/wystrzel')
def launch_view():
    from game.satellites import launch
    def handler(user_id, data):
        satellite_id, seconds = launch(user_id, data)
        return {'id': satellite_id, 'seconds': seconds, 'message': 'Satelita szpiegowski został wyniesiony na orbitę.'}
    return _action(handler)


@satellites_bp.post('/rozbuduj')
def upgrade_view():
    from game.satellites import upgrade, mission_speed
    def handler(user_id, data):
        level = upgrade(user_id, data)
        return {'level': level, 'message': f'Satelita rozbudowany do poziomu {level} — przelot w misji {mission_speed(level)} km/h Entendy.'}
    return _action(handler)


@satellites_bp.post('/anuluj-misje')
def cancel_view():
    from game.satellites import cancel_mission
    return _action(lambda user_id, data: {'id': cancel_mission(user_id, data), 'message': 'Misja anulowana. Satelita wraca do swobodnego dryfu; koszt misji nie jest zwracany.'})


@satellites_bp.post('/misja')
def mission_view():
    from game.satellites import order_mission
    return _action(lambda user_id, data: {'id': order_mission(user_id, data),
                                          'message': 'Satelita zmienia kurs i leci nad wybrane państwo. Raport otrzymasz po dotarciu nad jego terytorium.'})
