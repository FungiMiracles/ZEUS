"""Wskaźniki środowiskowe państwa i jego regionów (wyłącznie odczyt)."""

from game.governance import controlled_ids, controller_id
from flask import Blueprint, abort, redirect, render_template, session, url_for
from sqlalchemy import select
from sqlalchemy.orm import lazyload

from extensions import db
from game.country_summary import country_summary, metropolitan_region_ids
from game.models import GamePlayerCountry, GameUser
from models import Panstwo, Region


environment_bp = Blueprint("game_environment", __name__, url_prefix="/game/srodowisko")
METRICS = (
    ("air", "Zanieczyszczenie powietrza", "region_zanieczyszczenie_powietrza"),
    ("degradation", "Degradacja środowiska", "region_degradacja_srodowiska"),
)


def valid_indicator(value):
    return value if value is not None and 0 <= value <= 100 else None


def generated_points(session, region_ids):
    """Points currently added to the country's regions: air pollution by power plants, degradation by factories."""
    from sqlalchemy import func
    from game.industry_models import PowerPlant
    from game.research_models import AmmunitionFactory
    if not region_ids:return {"air": 0, "degradation": 0}
    air = session.scalar(select(func.coalesce(func.sum(PowerPlant.pollution_points), 0)).where(PowerPlant.region_id.in_(region_ids), PowerPlant.removed_at.is_(None))) or 0
    degradation = session.scalar(select(func.coalesce(func.sum(AmmunitionFactory.degradation_points), 0)).where(AmmunitionFactory.region_id.in_(region_ids), AmmunitionFactory.removed_at.is_(None))) or 0
    return {"air": int(air), "degradation": int(degradation)}


@environment_bp.get("")
def page():
    from game.forum import player
    user,country=player()
    if user is None:return redirect(url_for('wejscie'))


    rows = db.session.execute(select(
        Region.region_id, Region.region_nazwa,
        Region.region_zanieczyszczenie_powietrza, Region.region_degradacja_srodowiska,
    ).where(Region.panstwo_id.in_(controlled_ids(db.session, country.PANSTWO_ID))).order_by(Region.region_id)).all()
    regions = {
        str(row.region_id): {
            "name": row.region_nazwa,
            **{code: valid_indicator(getattr(row, field)) for code, _, field in METRICS},
        } for row in rows
    }
    generated = generated_points(db.session, [int(id) for id in regions])
    metrics = []
    for code, label, _ in METRICS:
        values = [region[code] for region in regions.values() if region[code] is not None]
        metrics.append({
            "code": code, "label": label, "known": len(values), "total": len(rows),
            "value": f"{sum(values) / len(values):.1f}".replace(".", ",") if values else None,
            "generated": generated[code],
        })

    return render_template(
        "game/srodowisko.html", game_user=user, game_country=country_summary(country),
        game_home_url=url_for("game_main_page"), game_logout_url=url_for("game_logout"),
        game_active_page="environment", metrics=metrics,
        environment_map={
            "metropolitanRegionIds": metropolitan_region_ids(country.PANSTWO_ID),
            "countryId": country.PANSTWO_ID, "regions": regions,
            "metrics": {code: label for code, label, _ in METRICS},
            "countriesUrl": url_for('region_sovereignty.country_boundaries'),
            "regionsUrl": url_for("static", filename="maps/entenda_regiony.geojson"),
        },
    )
