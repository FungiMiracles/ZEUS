"""Utrata suwerenności po aneksji regionu stołecznego (UAT, 11 Nov 2026).

Zasady zatwierdzone przez administratora:
* aneksja regionu ze stolicą (miasto typu 1) kończy niepodległość państwa;
* wszystkie regiony i miasta pokonanego państwa zmieniają panstwo_id na anektującego;
* cały majątek przechodzi do anektującego: bazy z garnizonami, okręty, obrona przeciwrakietowa, oddziały lądowe,
  zasoby wojska (Wojsko), elektrownie, fabryki, kopalnie, drogi i magazyn surowców;
* konto gracza pozostaje aktywne, ale działa tylko forum i wiadomości prywatne (oraz konto); pozostałe funkcje państwa są zablokowane.
Historia wydatków, budżety i skarbiec pokonanego państwa nie są przenoszone (zostają jako archiwum).
"""
from sqlalchemy import select, update
from models import Panstwo, Region, Miasto, Wojsko
from game.land_war_models import LandArmy, Occupation, SovereigntyLoss

LOST_TEXT = ('Twoje państwo utraciło suwerenność w wyniku aneksji zbrojnej. Nie możesz zarządzać już jego infrastrukturą, '
             'budżetem ani armią. Twoja historia się skończyła…')
# Poza forum i wiadomościami gracz zachowuje wylogowanie i zarządzanie kontem.
ALLOWED_BLUEPRINTS = {'game_forum', 'game_messages', 'game_account'}
ALLOWED_ENDPOINTS = {'game_logout', 'static', 'wejscie'}
# Zasoby wojska sumowane przy przejęciu (poziomy wyszkolenia i procent PKB zostają przy anektującym).
ARMY_SKIP = {'ID', 'panstwo_id', 'procent_PKB', 'wyszkolenie_ladowe', 'wyszkolenie_morskie', 'wyszkolenie_powietrzne'}


def lost(session, country_id):
    if country_id is None:
        return None
    return session.get(SovereigntyLoss, country_id)


def require_sovereign(session, country_id):
    from game.finance_service import FinancePermissionError
    if lost(session, country_id) is not None:
        raise FinancePermissionError(LOST_TEXT)


def _asset_models():
    from game.military_models import MilitaryBase, MilitaryVessel, MissileDefense
    from game.industry_models import PowerPlant
    from game.research_models import AmmunitionFactory
    from game.commerce_models import Mine
    from game.civic_models import Road
    from game.radar_models import Radar
    return {'radars': Radar, 'bases': MilitaryBase, 'vessels': MilitaryVessel, 'missile_defenses': MissileDefense, 'power_plants': PowerPlant,
            'factories': AmmunitionFactory, 'mines': Mine, 'roads': Road}


def _move_army_totals(session, defeated, annexer):
    old = session.scalar(select(Wojsko).where(Wojsko.panstwo_id == defeated).with_for_update())
    if old is None:
        return {}
    new = session.scalar(select(Wojsko).where(Wojsko.panstwo_id == annexer).with_for_update())
    if new is None:
        new = Wojsko(panstwo_id=annexer)
        session.add(new)
    moved = {}
    for column in Wojsko.__table__.columns:
        name = column.key
        if name in ARMY_SKIP:
            continue
        count = int(getattr(old, name) or 0)
        if count:
            setattr(new, name, int(getattr(new, name) or 0) + count)
            moved[name] = count
        setattr(old, name, 0)
    return moved


def _move_resources(session, defeated, annexer):
    from game.commerce_models import ResourceStock
    moved = {}
    for row in session.scalars(select(ResourceStock).where(ResourceStock.panstwo_id == defeated).with_for_update()):
        if not row.quantity:
            continue
        target = session.get(ResourceStock, (annexer, row.resource), with_for_update=True)
        if target is None:
            target = ResourceStock(panstwo_id=annexer, resource=row.resource, quantity=0)
            session.add(target)
        target.quantity = int(target.quantity or 0) + int(row.quantity)
        moved[row.resource] = int(row.quantity)
        row.quantity = 0
    return moved


def _settle_war(session, defeated, annexer, moment):
    """Armies and occupations of / against the defeated country after the transfer of its territory."""
    from game import land_war
    # Occupations of the annexer on the defeated country's objects end: the objects now belong to the annexer.
    for row in session.scalars(select(Occupation).where(Occupation.owner_id == defeated, Occupation.occupier_id == annexer,
                                                      Occupation.status.in_(['ACTIVE', 'PENDING', 'DECLINED'])).with_for_update()):
        row.status = 'ANNEXED' if row.status == 'ACTIVE' else 'ENDED'
        row.ended_at = moment
        if row.kind == 'base' and row.base_id:
            from game.military_models import MilitaryBase
            base = session.get(MilitaryBase, row.base_id, with_for_update=True)
            if base is not None:
                land_war.merge_into_base(session, base, land_war._occupiers(session, 'base', base.id), annexer)
        elif row.kind == 'city' and row.city_id:
            for army in land_war._occupiers(session, 'city', row.city_id):
                army.status, army.role, army.target_country_id = 'DEFENDING', 'city_defense', annexer
    # The defeated country's occupations of the annexer end (objects return to the annexer); others pass to the annexer.
    for row in session.scalars(select(Occupation).where(Occupation.occupier_id == defeated,
                                                      Occupation.status.in_(['ACTIVE', 'PENDING', 'DECLINED'])).with_for_update()):
        if row.owner_id == annexer:
            row.status = 'ENDED'
            row.ended_at = moment
        else:
            row.occupier_id = annexer
    # Third countries keep occupying what used to be the defeated country's — now the annexer's.
    session.execute(update(Occupation).where(Occupation.owner_id == defeated, Occupation.status.in_(['ACTIVE', 'PENDING', 'DECLINED']))
                    .values(owner_id=annexer).execution_options(synchronize_session=False))
    armies = {'withdrawn': 0, 'transferred': 0}
    for army in session.scalars(select(LandArmy).where(LandArmy.panstwo_id == defeated, LandArmy.status.in_(land_war.LIVE)).with_for_update()):
        released = army.status == 'MARCHING'
        if army.status == 'OCCUPYING':
            # Still an occupation (now the annexer's)? Otherwise it was the annexer's own object and ended above.
            column = Occupation.base_id if army.target_kind == 'base' else Occupation.city_id
            object_id = army.target_base_id if army.target_kind == 'base' else army.target_city_id
            released = session.scalar(select(Occupation.id).where(Occupation.kind == army.target_kind, column == object_id,
                                                                  Occupation.occupier_id == annexer, Occupation.status == 'ACTIVE')) is None
        if released:
            # Marching or homeless armies dissolve into the free pool (their units were moved with the army totals).
            army.status, army.resolved_at = 'WITHDRAWN', moment
            for unit in land_war.UNITS:
                setattr(army, unit, 0)
            armies['withdrawn'] += 1
        else:
            army.panstwo_id, army.user_id = annexer, None
            if army.target_country_id == defeated:
                army.target_country_id = annexer
            armies['transferred'] += 1
    for army in session.scalars(select(LandArmy).where(LandArmy.target_country_id == defeated, LandArmy.status == 'MARCHING').with_for_update()):
        if army.panstwo_id == annexer:
            land_war._return_home(session, army)
        else:
            army.target_country_id = annexer
    return armies


def lose_sovereignty(session, defeated, annexer, capital_region_id, occupation_id, moment):
    """The annexer takes over the whole country of `defeated` (inside the annexation transaction)."""
    from game import land_war
    if lost(session, defeated) is not None:
        return
    transferred = {}
    transferred['regions'] = session.execute(update(Region).where(Region.panstwo_id == defeated).values(panstwo_id=annexer)
                                             .execution_options(synchronize_session=False)).rowcount
    transferred['cities'] = session.execute(update(Miasto).where(Miasto.panstwo_id == defeated).values(panstwo_id=annexer)
                                            .execution_options(synchronize_session=False)).rowcount
    transferred['army'] = _move_army_totals(session, defeated, annexer)
    for label, model in _asset_models().items():
        transferred[label] = session.execute(update(model).where(model.panstwo_id == defeated).values(panstwo_id=annexer)
                                             .execution_options(synchronize_session=False)).rowcount
    transferred['resources'] = _move_resources(session, defeated, annexer)
    session.flush()
    session.expire_all()
    transferred['land_armies'] = _settle_war(session, defeated, annexer, moment)
    # 14 Nov 2026: the whole remaining GDP follows the territory; population and area are recounted from regions and cities.
    remaining = session.scalar(select(Panstwo.panstwo_PKB).where(Panstwo.PANSTWO_ID == defeated)) or 0
    transferred['gdp'] = land_war.transfer_gdp(session, defeated, annexer, remaining, moment)
    land_war.recount_country(session, annexer)
    land_war.recount_country(session, defeated)
    session.flush()
    session.add(SovereigntyLoss(panstwo_id=defeated, annexed_by=annexer, capital_region_id=capital_region_id,
                                occupation_id=occupation_id, transferred=transferred, lost_at=moment))
    session.flush()
    who = land_war.names(session, defeated, annexer)
    land_war.notify(session, defeated, LOST_TEXT)
    land_war.notify(session, annexer, f'Anektowaliśmy region stołeczny państwa {who.get(defeated, "przeciwnika")}. Państwo utraciło suwerenność — '
                                      'jego terytorium, armia i majątek przeszły pod nasze zwierzchnictwo.')
    return transferred


# ---------------- web: blocking and banner ----------------

def user_country_lost(session, user_id):
    from game.models import GamePlayerCountry
    country_id = session.scalar(select(GamePlayerCountry.panstwo_id).where(GamePlayerCountry.user_id == user_id))
    return lost(session, country_id) is not None


def register(app):
    from flask import request, session as web_session, redirect, url_for, jsonify, has_request_context
    from extensions import db

    def current_lost():
        if not has_request_context():
            return False
        user_id = web_session.get('game_user_id')
        if type(user_id) is not int:
            return False
        try:
            return user_country_lost(db.session, user_id)
        except Exception:
            db.session.rollback()
            return False

    @app.before_request
    def sovereignty_guard():
        if request.endpoint is None or not request.path.startswith('/game'):
            return None
        if request.blueprint in ALLOWED_BLUEPRINTS or request.endpoint in ALLOWED_ENDPOINTS:
            return None
        if not current_lost():
            return None
        wants_page = request.method == 'GET' and request.accept_mimetypes.best_match(['text/html', 'application/json']) == 'text/html'
        if wants_page:
            return redirect(url_for('game_forum.page'), code=303)
        return jsonify(error=LOST_TEXT), 403

    @app.context_processor
    def sovereignty_banner():
        return {'game_sovereignty_lost': current_lost(), 'game_sovereignty_text': LOST_TEXT}
