"""UAT WIKI actions for region secession and reintegration."""
import hmac, secrets
from uuid import uuid4
from flask import Blueprint, request, session, abort, redirect, url_for, flash, Response
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from extensions import db
from models import Panstwo
from permissions import wymaga_roli
from services.region_secession import RegionSecession, SecessionError, secede, rejoin

region_sovereignty_bp = Blueprint('region_sovereignty', __name__)


def form_context(region):
    if session.get('rola') != 'wszechmocny':
        return {}
    session.setdefault('wiki_secession_csrf', secrets.token_urlsafe(32))
    active = db.session.scalar(select(RegionSecession).where(
        RegionSecession.region_id == region.region_id,
        RegionSecession.new_country_id == region.panstwo_id,
        RegionSecession.rejoined_at.is_(None)))
    countries = db.session.execute(select(Panstwo.PANSTWO_ID, Panstwo.panstwo_nazwa)
        .where(Panstwo.PANSTWO_ID != region.panstwo_id, Panstwo.czy_suwerenny == 'TAK')
        .order_by(Panstwo.panstwo_nazwa, Panstwo.PANSTWO_ID)).all() if active else []
    return dict(secession_csrf=session['wiki_secession_csrf'], secession_request_id=str(uuid4()),
                region_secession=active, rejoin_countries=countries)


def _validate():
    supplied = request.form.get('csrf_token', '')
    expected = session.get('wiki_secession_csrf', '')
    if not expected or not hmac.compare_digest(supplied.encode(), expected.encode()):
        abort(403, description='Sesja formularza wygasła. Odśwież stronę.')


def _actor():
    return str(session.get('username') or session.get('user_id') or 'Administrator WIKI')[:120]


@region_sovereignty_bp.post('/region/<int:region_id>/niepodleglosc')
@wymaga_roli('wszechmocny')
def declare_independence(region_id):
    _validate()
    data = request.form.to_dict()
    db.session.rollback()
    try:
        country_id = secede(region_id, data, _actor())
        flash(f'Region ogłosił niepodległość. Utworzono państwo o ID {country_id}.', 'success')
    except (SecessionError, OSError, SQLAlchemyError) as error:
        if isinstance(error, SecessionError):
            message = str(error)
        else:
            message = 'Nie udało się zapisać secesji. Zmiany zostały wycofane.'
        flash(message, 'error')
    return redirect(url_for('region_form', region_id=region_id), code=303)


@region_sovereignty_bp.post('/region/<int:region_id>/przylacz')
@wymaga_roli('wszechmocny')
def rejoin_country(region_id):
    _validate()
    data = request.form.to_dict()
    db.session.rollback()
    try:
        target = rejoin(region_id, data, _actor())
        flash(f'Region został przyłączony do państwa o ID {target}.', 'success')
    except (SecessionError, SQLAlchemyError) as error:
        flash(str(error) if isinstance(error, SecessionError) else 'Nie udało się zapisać przyłączenia. Zmiany zostały wycofane.', 'error')
    return redirect(url_for('region_form', region_id=region_id), code=303)


@region_sovereignty_bp.get('/wiki/panstwo/<int:country_id>/mapa-po-secesji')
def country_map(country_id):
    if db.session.get(Panstwo, country_id) is None:
        abort(404)
    record = db.session.scalar(select(RegionSecession).where(RegionSecession.new_country_id == country_id))
    if record is None or not record.map_snapshot:
        abort(404)
    return Response(record.map_snapshot, mimetype=record.map_mime or 'image/jpeg',
                    headers={'Cache-Control': 'private, max-age=3600'})


@region_sovereignty_bp.get('/wiki/mapa/panstwa.geojson')
def country_boundaries():
    import json
    from pathlib import Path
    from flask import current_app, jsonify
    from models import Region
    from services.region_secession import country_boundaries_data
    from sqlalchemy import column, inspect, table
    # 14 Nov 2026: regions whose owner changed in the game (secession or armed annexation) are redrawn with their
    # current owner; a country that lost its sovereignty is drawn as part of the annexer. Lightweight table
    # constructs keep the WIKI map independent of the game models (the game tables may be absent in isolated setups).
    present = set(inspect(db.engine).get_table_names())
    changed = select(RegionSecession.region_id)
    if 'game_occupations' in present:
        occupations = table('game_occupations', column('region_id'), column('kind'), column('status'))
        changed = changed.union(select(occupations.c.region_id)
                                .where(occupations.c.kind == 'region', occupations.c.status == 'ANNEXED'))
    owners = dict(db.session.execute(select(Region.region_id, Region.panstwo_id)
        .where(Region.region_id.in_(changed), Region.panstwo_id.is_not(None))).all())
    merged = {}
    if 'game_sovereignty_losses' in present:
        losses = table('game_sovereignty_losses', column('panstwo_id'), column('annexed_by'))
        merged = dict(db.session.execute(select(losses.c.panstwo_id, losses.c.annexed_by)).all())
    maps = Path(current_app.static_folder) / 'maps'
    country_data = json.loads((maps/'entenda_panstwa.geojson').read_text())
    if owners or merged:
        region_data = json.loads((maps/'entenda_regiony.geojson').read_text()) if owners else {'features': []}
        country_data = country_boundaries_data(country_data, region_data, owners, merged)
    active_ids = set(db.session.scalars(select(Panstwo.PANSTWO_ID)))
    country_data['features'] = [feature for feature in country_data['features']
        if feature.get('properties', {}).get('panstwo_id') in active_ids]
    response = jsonify(country_data)
    response.headers['Cache-Control'] = 'no-store'
    return response
