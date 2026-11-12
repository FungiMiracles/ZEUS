"""Read the public simulation date; only WIKI Wszechmocny may change it."""
import hmac
from flask import Blueprint, jsonify, request, session, abort
from engine.clock import get_clock_snapshot, set_clock_speed, ClockError, clock_enabled
from permissions import wymaga_roli
from routes_auth import HASLA_ROLE

clock_bp = Blueprint('entenda_clock', __name__)


@clock_bp.get('/wiki/zegar')
def state():
    response = jsonify(get_clock_snapshot())
    response.headers['Cache-Control'] = 'no-store'
    return response


@clock_bp.post('/wiki/zegar/tempo')
@wymaga_roli('wszechmocny')
def change_speed():
    if not clock_enabled():
        abort(404)
    expected = session.get('clock_csrf', '')
    supplied = request.headers.get('X-CSRF-Token', '')
    if not expected or not hmac.compare_digest(expected.encode(), supplied.encode()):
        abort(403)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error='Nieprawidłowe dane zegara.'), 400
    password = data.get('password')
    if not isinstance(password, str) or not hmac.compare_digest(
            password.encode(), HASLA_ROLE['wszechmocny'].encode()):
        return jsonify(error='Nieprawidłowe hasło do roli wszechmocny.'), 403
    try:
        result = set_clock_speed(data.get('multiplier'), data.get('revision'),
            session.get('username') or session.get('user_id') or 'Administrator WIKI')
    except ClockError as error:
        return jsonify(error=str(error), clock=get_clock_snapshot()), 409
    response = jsonify(result)
    response.headers['Cache-Control'] = 'no-store'
    return response
