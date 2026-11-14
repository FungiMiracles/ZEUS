"""Transactional WIKI region secession/reintegration, with auditable country IDs."""
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

from flask import current_app
from sqlalchemy import select, func, text
from sqlalchemy.orm import Session, lazyload, deferred

from extensions import db
from models import Panstwo, Region, Miasto


class SecessionError(ValueError):
    pass


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class RegionSecession(db.Model):
    __tablename__ = 'wiki_region_secessions'
    id = db.Column(db.Integer, primary_key=True)
    region_id = db.Column(db.Integer, db.ForeignKey('regiony.region_id'), nullable=False, index=True)
    source_country_id = db.Column(db.Integer, db.ForeignKey('panstwa.PANSTWO_ID'), nullable=False)
    new_country_id = db.Column(db.Integer, db.ForeignKey('panstwa.PANSTWO_ID'), nullable=False, unique=True)
    capital_city_id = db.Column(db.Integer, db.ForeignKey('miasta.miasto_id'))
    original_capital_type = db.Column(db.Integer)
    flag_snapshot = deferred(db.Column(db.LargeBinary(length=16777215)))
    map_snapshot = deferred(db.Column(db.LargeBinary(length=16777215)))
    map_mime = db.Column(db.String(50))
    original_overseas = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    actor = db.Column(db.String(120), nullable=False)
    request_id = db.Column(db.String(36), nullable=False, unique=True)
    rejoined_country_id = db.Column(db.Integer, db.ForeignKey('panstwa.PANSTWO_ID'))
    rejoined_at = db.Column(db.DateTime)
    rejoined_by = db.Column(db.String(120))
    rejoin_request_id = db.Column(db.String(36), unique=True)


def request_key(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise SecessionError('Sesja formularza jest nieprawidłowa. Odśwież stronę.')


def positive_id(value):
    if isinstance(value, bool):
        raise SecessionError('Wybierz poprawne państwo.')
    try:
        number = int(value)
        if str(number) != str(value) or not 1 <= number <= 2147483647:
            raise ValueError
        return number
    except (TypeError, ValueError):
        raise SecessionError('Wybierz poprawne państwo.')


def asset_path(folder, name):
    root = (Path(current_app.static_folder) / folder).resolve()
    path = root / (name.replace(' ', '_') + '.jpg')
    if path.parent.resolve() != root:
        raise SecessionError('Nazwa państwa zawiera niedozwolone znaki.')
    return path


def country_name(value):
    name = str(value or '').strip()
    if not name or len(name) > 200 or any(ord(c) < 32 for c in name) or any(c in name for c in '/\\') or name in ('.', '..'):
        raise SecessionError('Podaj nazwę nowego państwa (1–200 znaków, bez ukośników).')
    return name


def _totals(session, country_id):
    rural = session.scalar(select(func.sum(Region.region_ludnosc_pozamiejska)).where(Region.panstwo_id == country_id)) or 0
    urban = session.scalar(select(func.sum(Miasto.miasto_populacja)).where(Miasto.panstwo_id == country_id)) or 0
    areas = list(session.scalars(select(Region.region_powierzchnia).where(Region.panstwo_id == country_id)))
    country = session.get(Panstwo, country_id)
    country.panstwo_populacja = int(rural + urban)
    country.panstwo_powierzchnia = sum(areas) if all(area is not None for area in areas) else None


def _create_asset(path, contents, created):
    if contents is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        created.append(path)
        stream.write(contents)


@contextmanager
def _secession_lock():
    # Country names have no unique index in the legacy schema. Serialize new
    # declarations across workers without changing that existing constraint.
    if db.engine.dialect.name != 'mysql':
        yield
        return
    with db.engine.connect() as connection:
        acquired = connection.scalar(text("SELECT GET_LOCK('zeus-wiki-region-secession', 5)"))
        if acquired != 1:
            raise SecessionError('Trwa inna secesja. Spróbuj ponownie za chwilę.')
        try:
            yield
        finally:
            connection.execute(text("SELECT RELEASE_LOCK('zeus-wiki-region-secession')"))


def secede(region_id, data, actor):
    with _secession_lock():
        return _secede(region_id, data, actor)


def _secede(region_id, data, actor):
    key = request_key(data.get('request_id'))
    expected_country_id = positive_id(data.get('expected_country_id'))
    name = country_name(data.get('country_name'))
    created = []
    try:
        with Session(db.engine) as session, session.begin():
            parent = session.scalar(select(Panstwo).options(lazyload('*')).where(Panstwo.PANSTWO_ID == expected_country_id).with_for_update())
            if parent is None:
                raise SecessionError('Nie znaleziono dotychczasowego państwa.')
            region = session.scalar(select(Region).options(lazyload('*')).where(Region.region_id == region_id).with_for_update())
            if region is None:
                raise SecessionError('Nie znaleziono regionu.')
            replay = session.scalar(select(RegionSecession).where(RegionSecession.request_id == key))
            if replay:
                if replay.region_id == region_id and replay.source_country_id == expected_country_id and replay.rejoined_at is None:
                    return replay.new_country_id
                raise SecessionError('Identyfikator operacji został już użyty.')
            if region.panstwo_id != expected_country_id:
                raise SecessionError('Przynależność regionu zmieniła się. Odśwież stronę.')
            if session.scalar(select(RegionSecession.id).where(RegionSecession.region_id == region_id, RegionSecession.rejoined_at.is_(None))):
                raise SecessionError('Ten region ogłosił już niepodległość. Możesz ponownie przyłączyć go do państwa.')
            if session.scalar(select(Panstwo.PANSTWO_ID).where(func.lower(Panstwo.panstwo_nazwa) == name.lower())
                              .execution_options(include_deleted_countries=True)):
                raise SecessionError('Państwo o tej nazwie już istnieje. Podaj inną nazwę.')
            flag_path, map_path = asset_path('flags', name), asset_path('maps', name)
            if flag_path.exists() or map_path.exists():
                raise SecessionError('Istnieją już pliki państwa o tej nazwie. Podaj inną nazwę.')
            cities = list(session.scalars(select(Miasto).options(lazyload('*')).where(Miasto.region_id == region_id).with_for_update()))
            if any(city.panstwo_id != parent.PANSTWO_ID for city in cities):
                raise SecessionError('Przynależność miast jest niezgodna z regionem. Popraw ją przed secesją.')
            capitals = [city for city in cities if city.miasto_typ_id in (1, 2)]
            if len(capitals) > 1:
                raise SecessionError('Region ma więcej niż jedną stolicę. Wskaż jedną stolicę regionu przed secesją.')
            capital = capitals[0] if capitals else None
            original_type = capital.miasto_typ_id if capital else None
            source_flag = asset_path('flags', parent.panstwo_nazwa)
            flag = source_flag.read_bytes() if source_flag.is_file() else None
            image = bytes(region.region_mapa) if region.region_mapa else None
            child = Panstwo(panstwo_nazwa=name, panstwo_pelna_nazwa=name,
                            kontynent_id=parent.kontynent_id, panstwo_waluta=parent.panstwo_waluta,
                            panstwo_jezyk=parent.panstwo_jezyk, panstwo_religia=parent.panstwo_religia,
                            czy_suwerenny='TAK', zwierzch_panstwo_id=None, panstwo_PKB=None)
            session.add(child)
            session.flush()
            child.panstwo_kod = 'SEC' + str(child.PANSTWO_ID)
            event = RegionSecession(region_id=region_id, source_country_id=parent.PANSTWO_ID,
                new_country_id=child.PANSTWO_ID, capital_city_id=capital.miasto_id if capital else None,
                original_capital_type=original_type, flag_snapshot=flag, map_snapshot=image,
                map_mime=region.region_mapa_mime if image else None,
                original_overseas=bool(region.terytorium_zamorskie), actor=str(actor)[:120], request_id=key)
            session.add(event)
            region.panstwo_id = child.PANSTWO_ID
            region.terytorium_zamorskie = False
            for city in cities:
                city.panstwo_id = child.PANSTWO_ID
            if capital:
                capital.miasto_typ_id = 1
            session.flush()
            _totals(session, parent.PANSTWO_ID)
            _totals(session, child.PANSTWO_ID)
            _create_asset(flag_path, flag, created)
            _create_asset(map_path, image, created)
            session.flush()
            result = child.PANSTWO_ID
        return result
    except Exception:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        raise


def rejoin(region_id, data, actor):
    key = request_key(data.get('request_id'))
    expected = positive_id(data.get('expected_country_id'))
    target_id = positive_id(data.get('target_country_id'))
    with Session(db.engine) as session, session.begin():
        owners = {c.PANSTWO_ID: c for c in session.scalars(select(Panstwo).options(lazyload('*'))
            .where(Panstwo.PANSTWO_ID.in_(sorted([expected, target_id]))).order_by(Panstwo.PANSTWO_ID).with_for_update())}
        region = session.scalar(select(Region).options(lazyload('*')).where(Region.region_id == region_id).with_for_update())
        if region is None:
            raise SecessionError('Nie znaleziono regionu.')
        replay = session.scalar(select(RegionSecession).where(RegionSecession.rejoin_request_id == key))
        if replay:
            if replay.region_id == region_id and replay.rejoined_country_id == target_id:
                return target_id
            raise SecessionError('Identyfikator operacji został już użyty.')
        if region.panstwo_id != expected or target_id == expected:
            raise SecessionError('Wybierz inne państwo lub odśwież zmienione dane regionu.')
        event = session.scalar(select(RegionSecession).where(RegionSecession.region_id == region_id,
            RegionSecession.new_country_id == expected, RegionSecession.rejoined_at.is_(None)).with_for_update())
        if event is None:
            raise SecessionError('Region nie ma aktywnej secesji.')
        target = owners.get(target_id)
        if target is None or target.czy_suwerenny != 'TAK':
            raise SecessionError('Wybierz istniejące, suwerenne państwo.')
        cities = list(session.scalars(select(Miasto).options(lazyload('*')).where(Miasto.region_id == region_id).with_for_update()))
        if any(city.panstwo_id != expected for city in cities):
            raise SecessionError('Przynależność miast jest niezgodna z regionem.')
        has_capital = session.scalar(select(Miasto.miasto_id).where(Miasto.panstwo_id == target_id, Miasto.miasto_typ_id == 1).limit(1)) is not None
        region.panstwo_id = target_id
        region.terytorium_zamorskie = event.original_overseas if target_id == event.source_country_id else False
        for city in cities:
            city.panstwo_id = target_id
            if city.miasto_typ_id == 1:
                if city.miasto_id == event.capital_city_id and event.original_capital_type == 2:
                    city.miasto_typ_id = 2
                elif has_capital:
                    city.miasto_typ_id = 2
                else:
                    has_capital = True
        event.rejoined_country_id = target_id
        event.rejoined_at = utc_now()
        event.rejoined_by = str(actor)[:120]
        event.rejoin_request_id = key
        session.flush()
        _totals(session, expected)
        _totals(session, target_id)
        if (not session.scalar(select(Region.region_id).where(Region.panstwo_id == expected).limit(1))
                and not session.scalar(select(Miasto.miasto_id).where(Miasto.panstwo_id == expected).limit(1))):
            owners[expected].status = 'usunięte'
        return target_id


def country_boundaries_data(country_data, region_data, owners, merged=None):
    """Apply recorded region ownership to a map response, without rewriting files.

    `owners` maps a region_id to its current country; `merged` maps a country that lost its sovereignty
    to the country that took over its whole territory (14 Nov 2026: annexation)."""
    from shapely.geometry import shape, mapping
    from shapely import make_valid
    from shapely.ops import unary_union
    merged = merged or {}
    if merged:
        def current(id):
            seen = set()
            while id in merged and id not in seen:
                seen.add(id)
                id = merged[id]
            return id
        features = []
        for feature in country_data['features']:
            id = feature.get('properties', {}).get('panstwo_id')
            if id in merged:
                feature = {**feature, 'properties': {**feature['properties'], 'panstwo_id': current(id)}}
            features.append(feature)
        country_data = {**country_data, 'features': features}
    if not owners:
        if not merged:
            return country_data
        owners = {}
    def land(geometry):
        if geometry.geom_type == 'Polygon':
            return [geometry]
        return [polygon for child in getattr(geometry, 'geoms', []) for polygon in land(child)]
    moved = {}
    for feature in region_data['features']:
        id = feature.get('properties', {}).get('region_id')
        if id in owners and feature.get('geometry'):
            moved.setdefault(id, []).extend(land(make_valid(shape(feature['geometry']))))
    if not moved and not merged:
        return country_data
    mask = unary_union([polygon for polygons in moved.values() for polygon in polygons]) if moved else None
    groups, unchanged = {}, []
    for feature in country_data['features']:
        id = feature.get('properties', {}).get('panstwo_id')
        if id is None or not feature.get('geometry'):
            unchanged.append(feature)
            continue
        geometry = make_valid(shape(feature['geometry']))
        if mask is not None:
            geometry = geometry.difference(mask)
        groups.setdefault(id, []).extend(land(geometry))
    for region_id, polygons in moved.items():
        groups.setdefault(owners[region_id], []).extend(polygons)
    features = unchanged + [dict(type='Feature', properties={'panstwo_id':id}, geometry=mapping(unary_union(parts)))
                            for id, parts in groups.items() if parts]
    return {**country_data, 'features':features}
