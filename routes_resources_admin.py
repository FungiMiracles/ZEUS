"""Panel przydziału surowców w WIKI, wyłącznie dla Wszechmocnego."""
import hmac
import secrets
from decimal import Decimal, ROUND_HALF_UP

from flask import abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy import select
from sqlalchemy.orm import lazyload
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from models import CountryMiningSettings, DictZasob, Panstwo, Region, RegionZasob
from permissions import wymaga_roli
from services.natural_resources import (
    integer_value, MAX_QUANTITY, RESOURCES, ResourceError, deposits_for_country, field_name,
    resource_dictionary, save_allocations, INCREASE_PERCENTAGES,
)


def csrf_token():
    token = session.get("wiki_resources_csrf")
    if not isinstance(token, str) or not token:
        token = secrets.token_urlsafe(32)
        session["wiki_resources_csrf"] = token
    return token


def validate_csrf():
    expected = session.get("wiki_resources_csrf")
    provided = request.form.get("csrf_token", "")
    if not isinstance(expected, str) or not expected or not hmac.compare_digest(expected.encode(), provided.encode()):
        abort(400, description="Sesja formularza wygasła. Odśwież panel.")


def render_panel(country_id, error=None, status=200, form=None, generated=False):
    submitted = request.form if form is None else form
    search = request.args.get("q", "").strip()[:255]
    query = select(Panstwo.PANSTWO_ID, Panstwo.panstwo_nazwa).order_by(Panstwo.panstwo_nazwa, Panstwo.PANSTWO_ID)
    if search:
        query = query.where(Panstwo.panstwo_nazwa.contains(search, autoescape=True))
    countries = db.session.execute(query).all()
    country = None
    regions = []
    values = {}
    technology, version = "0", "0"
    configuration_ok = True
    if country_id is not None:
        country = db.session.execute(select(Panstwo.PANSTWO_ID, Panstwo.panstwo_nazwa).where(Panstwo.PANSTWO_ID == country_id)).first()
        if country is None:
            abort(404)
        if all(row.PANSTWO_ID != country_id for row in countries):
            countries.append(country)
        regions = db.session.execute(select(Region.region_id, Region.region_nazwa).where(
            Region.panstwo_id == country_id,
        ).order_by(Region.region_nazwa, Region.region_id)).all()
        settings = db.session.get(CountryMiningSettings, country_id)
        technology, version = (str(settings.technology), str(settings.version)) if settings else ("0", "0")
        try:
            dictionary = resource_dictionary()
            existing = deposits_for_country(country_id, dictionary)
            for region in regions:
                for code, _ in RESOURCES:
                    row = existing.get((region.region_id, dictionary[code]))
                    values[field_name(region.region_id, code)] = str(row.zloze_ilosc or 0) if row else "0"
        except ResourceError as problem:
            configuration_ok = False
            error, status = str(problem), problem.status
        if request.method == "POST":
            technology = submitted.get("technology", "")
            version = submitted.get("version", "")
            for region in regions:
                for code, _ in RESOURCES:
                    name = field_name(region.region_id, code)
                    if name in submitted:
                        values[name] = submitted[name]
    suggested_technology = None
    if country:
        from game.country_summary import country_summary
        country_obj = db.session.scalar(select(Panstwo).where(Panstwo.PANSTWO_ID == country_id).options(lazyload("*")))
        average = country_summary(country_obj)["infrastruktura"]
        if average is not None:
            suggested_technology = int(Decimal(str(average)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    selected_region = request.args.get("region_id", submitted.get("region_id", ""))
    region_index = db.session.execute(select(Region.region_id, Region.region_nazwa, Region.panstwo_id)).all()
    map_deposits = {}
    for region_id, name, unit, quantity in db.session.execute(
        select(RegionZasob.region_id, DictZasob.zasob_nazwa, DictZasob.zasob_jednostka, RegionZasob.zloze_ilosc)
        .join(DictZasob, DictZasob.zasob_id == RegionZasob.zasob_id)
        .where(RegionZasob.zloze_ilosc > 0).order_by(DictZasob.zasob_id)
    ):
        map_deposits.setdefault(region_id, []).append({'name': name, 'unit': unit or '', 'quantity': str(quantity)})
    return render_template(
        "admin_natural_resources.html", countries=countries, country=country,
        regions=regions, resources=RESOURCES, values=values, technology=technology,
        version=version, search=search, error=error, configuration_ok=configuration_ok,
        suggested_technology=suggested_technology, selected_region=selected_region,
        region_index={str(r.region_id): {"name": r.region_nazwa, "countryId": r.panstwo_id, "hasMinerals": bool(map_deposits.get(r.region_id)), "deposits": map_deposits.get(r.region_id, [])} for r in region_index},
        country_names={str(c.PANSTWO_ID): c.panstwo_nazwa for c in countries},
        generated=generated or submitted.get("action") == "bulk",
        resource_csrf=csrf_token(), max_quantity=MAX_QUANTITY, field_name=field_name,
        increase_percentages=INCREASE_PERCENTAGES, submitted=submitted,
    ), status


def init_resources_admin_routes(app):
    @app.route("/admin/surowce-naturalne", methods=["GET", "POST"])
    @wymaga_roli("wszechmocny")
    def admin_natural_resources():
        raw_id = request.args.get("country_id", "")
        if not raw_id:
            selected = request.args.get("region_id", "")
            if selected.isascii() and selected.isdecimal() and len(selected) <= 10:
                owner = db.session.scalar(select(Region.panstwo_id).where(Region.region_id == int(selected)))
                if owner is None:
                    abort(404)
                raw_id = str(owner)
        if raw_id and (not raw_id.isascii() or not raw_id.isdecimal() or len(raw_id) > 10):
            abort(400)
        country_id = int(raw_id) if raw_id else None
        if country_id is not None and not 1 <= country_id <= 2147483647:
            abort(400)
        if request.method == "GET":
            return render_panel(country_id)
        validate_csrf()
        if country_id is None or request.form.get("country_id") != str(country_id):
            abort(400)
        try:
            if request.form.get("action") == "generate":
                code = request.form.get("resource")
                if code not in dict(RESOURCES):
                    raise ResourceError("Wybierz surowiec.")
                minimum = integer_value(request.form.get("minimum", ""), MAX_QUANTITY, "Minimum")
                maximum = integer_value(request.form.get("maximum", ""), MAX_QUANTITY, "Maksimum")
                if minimum > maximum:
                    raise ResourceError("Minimum nie może być większe od maksimum.")
                # Podgląd w formularzu; generowanie nie zmienia bazy danych.
                from werkzeug.datastructures import MultiDict
                preview = MultiDict(request.form)
                region_ids = db.session.scalars(select(Region.region_id).where(Region.panstwo_id == country_id)).all()
                for region_id in region_ids:
                    preview[field_name(region_id, code)] = str(minimum + secrets.randbelow(maximum - minimum + 1))
                return render_panel(country_id, form=preview, generated=True)
            save_allocations(country_id, request.form)
            db.session.commit()
        except ResourceError as problem:
            db.session.rollback()
            if problem.status == 404:
                abort(404)
            return render_panel(country_id, error=str(problem), status=problem.status)
        except SQLAlchemyError:
            db.session.rollback()
            return render_panel(country_id, error="Nie udało się zapisać danych. Żadna zmiana nie została zatwierdzona. Spróbuj ponownie.", status=503)
        flash("Zatwierdzono wartości surowców naturalnych.", "success")
        return redirect(url_for("admin_natural_resources", country_id=country_id, region_id=request.args.get("region_id", ""), q=request.args.get("q", "")[:255]), code=303)
