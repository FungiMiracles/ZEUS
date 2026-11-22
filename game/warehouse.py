"""Lokalizacja magazynu państwa (22 Nov 2026).

* Po zatwierdzeniu pierwszego budżetu gracz musi w oknie z mapą wskazać miasto, w którym fizycznie znajduje się magazyn
  jego państwa (okno wraca, dopóki wybór nie zostanie zapisany; gdy państwo utraci kontrolę nad miastem — także).
* Lokalizację można później zmienić (ekran handlu → „Zmień lokalizację magazynu”).
* Państwa AI (PAGA2) nie wybierają ręcznie — ich magazyn jest w największym własnym mieście portowym (bez portu: w stolicy);
  gracz, dopóki nie wybierze, ma magazyn w stolicy.
* Magazyn jest punktem nadania i odbioru towarów w handlu (game.trade_routes); ikona MAGAZYN.svg obok miasta jest
  widoczna tylko dla państwa-właściciela na mapach: panel państwa, świat, handel.
"""
from flask import Blueprint, jsonify, request, session as web_session, url_for
from sqlalchemy import select
from sqlalchemy.orm import Session, lazyload
from extensions import db
from models import Miasto
from game.models import utc_now
from game.finance_service import FinanceError

warehouse_bp = Blueprint('game_warehouse', __name__, url_prefix='/game/magazyn')


class Warehouse(db.Model):
    __tablename__ = 'game_warehouses'
    panstwo_id = db.Column(db.Integer, db.ForeignKey('panstwa.PANSTWO_ID'), primary_key=True)
    miasto_id = db.Column(db.Integer, db.ForeignKey('miasta.miasto_id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('game_users.id'))
    chosen_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    __table_args__ = ({'mysql_engine': 'InnoDB'},)


def candidate_cities(session, country_id):
    """Miasta na mapie pod kontrolą państwa (z punktem na mapie) — możliwe lokalizacje magazynu."""
    from game.governance import controlled_ids
    from game.military_geography import city_point
    rows = session.scalars(select(Miasto).options(lazyload('*')).where(Miasto.panstwo_id.in_(controlled_ids(session, country_id)),
                                                                     Miasto.czy_na_mapie == 'TAK').order_by(Miasto.miasto_nazwa))
    result = []
    for city in rows:
        point = city_point(city.miasto_id)
        if point is None:
            continue
        result.append({'id': city.miasto_id, 'name': city.miasto_nazwa, 'point': [point[0], point[1]], 'capital': city.miasto_typ_id == 1,
                       'population': int(city.miasto_populacja or 0), 'regionId': city.region_id})
    return result


def _valid(session, country_id, city_id):
    from game.governance import controller_id
    from game.military_geography import city_point
    if city_id is None:
        return False
    city = session.scalar(select(Miasto).options(lazyload('*')).where(Miasto.miasto_id == city_id))
    return city is not None and city.czy_na_mapie == 'TAK' and controller_id(session, city.panstwo_id) == country_id and city_point(city_id) is not None


def chosen_city(session, country_id):
    """Miasto magazynu wybrane przez państwo (None — brak wyboru albo miasto nie jest już pod kontrolą państwa)."""
    row = session.get(Warehouse, country_id)
    return row.miasto_id if row is not None and _valid(session, country_id, row.miasto_id) else None


def is_ai(session, country_id):
    """Państwo prowadzone przez PAGA (tożsamość AI)."""
    from sqlalchemy import inspect
    from game.paga_ai_models import PagaAiIdentity
    if not inspect(session.connection()).has_table(PagaAiIdentity.__tablename__):
        return False
    return session.scalar(select(PagaAiIdentity.country_id).where(PagaAiIdentity.country_id == country_id)) is not None


def port_city(session, country_id):
    """22 Nov 2026: magazyn PAGA2 — największe własne miasto portowe na mapie (bez portu: stolica)."""
    from game.governance import controller_id
    from game.trade_service import ports, capital_city
    own = [city for city in ports(session) if controller_id(session, city.panstwo_id) == country_id]
    if own:
        return max(own, key=lambda city: (int(city.miasto_populacja or 0), -city.miasto_id)).miasto_id
    return capital_city(session, country_id)


def warehouse_city(session, country_id):
    """Miasto magazynu do transportu: wybrane miasto; bez wyboru — PAGA2: największe własne miasto portowe,
    gracz: stolica państwa."""
    city = chosen_city(session, country_id)
    if city is not None:
        return city
    if is_ai(session, country_id):
        return port_city(session, country_id)
    from game.trade_service import capital_city
    return capital_city(session, country_id)


def assign_ai_warehouses(session):
    """Zapisuje magazyny państw PAGA2 w miastach portowych (bez ważnego wyboru albo z magazynem poza portem)."""
    from game.paga_ai_models import PagaAiIdentity
    from game.trade_service import ports
    port_ids = {city.miasto_id for city in ports(session)}
    changed = []
    for country_id in session.scalars(select(PagaAiIdentity.country_id).order_by(PagaAiIdentity.country_id)):
        current = chosen_city(session, country_id)
        if current is not None and current in port_ids:
            continue
        city = port_city(session, country_id)
        if city is None:
            continue
        row = session.get(Warehouse, country_id)
        if row is None:
            row = Warehouse(panstwo_id=country_id)
            session.add(row)
        row.miasto_id, row.user_id, row.chosen_at = city, None, utc_now()
        changed.append((country_id, city))
    session.flush()
    return changed


def required(session, country_id):
    """Gracz musi wskazać magazyn: zatwierdził już budżet, a wyboru brak lub miasto przestało należeć do państwa."""
    from game.finance_models import StateBudget
    if country_id is None or chosen_city(session, country_id) is not None:
        return False
    if not candidate_cities(session, country_id):
        return False
    return session.scalar(select(StateBudget.id).where(StateBudget.panstwo_id == country_id).limit(1)) is not None


def choose(user_id, country_id, city_id):
    if type(city_id) is not int or city_id < 1:
        raise FinanceError('Wybierz miasto na mapie.')
    with Session(db.engine) as session, session.begin():
        if not _valid(session, country_id, city_id):
            raise FinanceError('Magazyn można umieścić tylko w mieście własnego państwa.')
        row = session.get(Warehouse, country_id, with_for_update=True)
        if row is None:
            row = Warehouse(panstwo_id=country_id)
            session.add(row)
        row.miasto_id = city_id
        row.user_id = user_id
        row.chosen_at = utc_now()
        return city_id


def marker(session, country_id):
    """Dane ikony magazynu na mapach (tylko dla państwa-właściciela)."""
    from game.military_geography import city_point
    if country_id is None:
        return None
    city_id = chosen_city(session, country_id)
    if city_id is None:
        return None
    point = city_point(city_id)
    name = session.scalar(select(Miasto.miasto_nazwa).where(Miasto.miasto_id == city_id))
    return {'cityId': city_id, 'name': name, 'point': [point[0], point[1]], 'icon': url_for('static', filename='icons/MAGAZYN.svg')}


def modal_config(session, country_id, required_now):
    return {'required': bool(required_now), 'csrf': web_session.get('game_csrf_token', ''), 'saveUrl': url_for('game_warehouse.save'),
            'regionsUrl': url_for('static', filename='maps/entenda_regiony.geojson'), 'icon': url_for('static', filename='icons/MAGAZYN.svg'),
            'cities': candidate_cities(session, country_id), 'current': chosen_city(session, country_id)}


@warehouse_bp.post('/lokalizacja')
def save():
    import hmac
    from game.forum import player
    user, country = player()
    if user is None or country is None:
        return jsonify(error='Zaloguj się ponownie.'), 401
    expected = web_session.get('game_csrf_token', '')
    if not expected or not hmac.compare_digest(expected, request.headers.get('X-CSRF-Token', '')):
        return jsonify(error='Nieprawidłowy token formularza.'), 403
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error='Nieprawidłowe dane formularza.'), 400
    try:
        city_id = choose(user.id, country.PANSTWO_ID, data.get('city_id'))
    except FinanceError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(ok=True, cityId=city_id, message='Zapisano lokalizację magazynu.')
