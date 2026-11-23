"""Lokalizacja magazynu państwa (22 Nov 2026).

* Po zatwierdzeniu pierwszego budżetu gracz musi w oknie z mapą wskazać miasto, w którym fizycznie znajduje się magazyn
  jego państwa (okno wraca, dopóki wybór nie zostanie zapisany; gdy państwo utraci kontrolę nad miastem — także).
* Lokalizację można później zmienić (ekran handlu → „Zmień lokalizację magazynu”).
* Państwa PAGA2 wybierają magazyn same (game.paga2.warehouse) — według skłonności do handlu (port, kolej, lotnisko)
  i ostrożności (stolica); do wyboru, tak jak gracz, mają magazyn w stolicy.
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


def warehouse_city(session, country_id):
    """Miasto magazynu do transportu: wybrane miasto, a bez wyboru — stolica państwa. Państwa PAGA2 wybierają magazyn
    same (game.paga2.warehouse), do tego czasu obowiązuje stolica."""
    city = chosen_city(session, country_id)
    if city is not None:
        return city
    from game.trade_service import capital_city
    return capital_city(session, country_id)


def screen_state(session, country_id):
    """22 Nov 2026: stan dla ekranu/PAGA2 — miasta państwa z cechami ważnymi dla magazynu (port, lotnisko, sieć kolejowa)."""
    from game.airports import own_operational
    from game.rail import network
    cities = candidate_cities(session, country_id)
    ports = set(session.scalars(select(Miasto.miasto_id).where(Miasto.miasto_id.in_([c['id'] for c in cities] or [0]), Miasto.czy_portowe == 'TAK')))
    airports = {a.miasto_id for a in own_operational(session, country_id)}
    rail = network(session, country_id)[0]
    row = session.get(Warehouse, country_id)
    for city in cities:
        city.update(port=city['id'] in ports, airport=city['id'] in airports, rail=city['id'] in rail)
    return {'cities': cities, 'current': chosen_city(session, country_id),
            'chosenAt': row.chosen_at.isoformat() + 'Z' if row is not None and row.chosen_at else None}


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


def foreign_markers(session, country_id):
    """23 Nov 2026: magazyny innych państw na mapie „Świat” (filtr „Magazyny”) — tylko lokalizacje zapisane przez państwa
    (gracz albo PAGA2) i nadal ważne (miasto pod kontrolą państwa, z punktem na mapie)."""
    from models import Panstwo
    from game.military_geography import city_point
    rows = session.execute(select(Warehouse.panstwo_id, Warehouse.miasto_id, Panstwo.panstwo_nazwa, Miasto.miasto_nazwa)
                           .join(Panstwo, Panstwo.PANSTWO_ID == Warehouse.panstwo_id).join(Miasto, Miasto.miasto_id == Warehouse.miasto_id)
                           .where(Warehouse.panstwo_id != country_id)).all()
    icon = url_for('static', filename='icons/MAGAZYN.svg')
    result = []
    for owner, city_id, country_name, city_name in rows:
        if not _valid(session, owner, city_id):
            continue
        point = city_point(city_id)
        result.append({'countryId': owner, 'country': country_name, 'cityId': city_id, 'name': city_name, 'point': [point[0], point[1]], 'icon': icon,
                       'flag': url_for('static', filename='flags/' + (country_name or '').replace(' ', '_') + '.jpg')})
    return result


def modal_config(session, country_id, required_now):
    return {'required': bool(required_now), 'csrf': web_session.get('game_csrf_token', ''), 'saveUrl': url_for('game_warehouse.save'),
            'regionsUrl': url_for('static', filename='maps/entenda_regiony.geojson'), 'icon': url_for('static', filename='icons/MAGAZYN.svg'),
            'cities': candidate_cities(session, country_id), 'current': chosen_city(session, country_id)}


@warehouse_bp.get('/stan')
def state():
    from game.forum import player
    user, country = player()
    if user is None or country is None:
        return jsonify(error='Zaloguj się ponownie.'), 401
    data = screen_state(db.session, country.PANSTWO_ID)
    db.session.rollback()
    response = jsonify(data)
    response.headers['Cache-Control'] = 'no-store'
    return response


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
