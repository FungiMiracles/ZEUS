"""Wspólne dane paska państwa na ekranach gry."""

from game.governance import economy
from models import Panstwo
from game.governance import controlled_ids, controller_id
from flask import url_for
from sqlalchemy import select

from extensions import db
from models import Region


def country_summary(country):
    if country is None:
        return {
            "id": None, "nazwa": "Brak państwa", "skrot": "", "flaga": "",
            "populacja": None, "pkb": None, "pkb_per_capita": None, "pkb_per_capita_label": None,
            "infrastruktura": None,
        }

    # Ta sama średnia co w panelu państwa: dostępne wskaźniki regionów,
    # z infrastrukturą portową tylko dla regionów o odpowiednim położeniu.
    rows = db.session.execute(select(
        Region.region_polozenie_id,
        Region.region_stan_infra_kolejowej,
        Region.region_stan_infra_drogowej,
        Region.region_stan_infra_energetycznej,
        Region.region_stan_infra_mieszkalnej,
        Region.region_stan_infra_portowej,
    ).where(Region.panstwo_id.in_(controlled_ids(db.session, country.PANSTWO_ID)))).all()
    values = []
    for position, rail, road, energy, housing, port in rows:
        indicators = [rail, road, energy, housing]
        if position and position != 1:
            indicators.append(port)
        values.extend(value for value in indicators if value is not None)

    totals = economy(db.session, country.PANSTWO_ID)
    population, gdp = totals["population"], totals["gdp"]
    per_capita = int(gdp // population) if gdp is not None and population and population > 0 else None
    from game.money_display import format_thousands
    return {
        "id": country.PANSTWO_ID,
        "nazwa": country.panstwo_nazwa,
        "pelna_nazwa": getattr(country, "panstwo_pelna_nazwa", None) or country.panstwo_nazwa,
        "territories": list(db.session.scalars(select(Panstwo.panstwo_nazwa).where(Panstwo.PANSTWO_ID.in_(controlled_ids(db.session, country.PANSTWO_ID)), Panstwo.PANSTWO_ID != country.PANSTWO_ID).order_by(Panstwo.panstwo_nazwa))),
        "skrot": country.panstwo_kod or "",
        "flaga": url_for("static", filename="flags/" + (country.panstwo_nazwa or "").replace(" ", "_") + ".jpg"),
        "populacja": population,
        "pkb": gdp,
        "pkb_per_capita": per_capita,
        "pkb_per_capita_label": format_thousands(per_capita) if per_capita is not None else None,   # 15 Nov 2026: w tysiącach ROI
        "infrastruktura": round(sum(values) / len(values), 1) if values else None,
    }


def metropolitan_region_ids(country_id):
    """Regiony używane do rysowania i kadrowania mapy państwa gracza."""
    return [str(region_id) for region_id in db.session.scalars(select(Region.region_id).where(
        Region.panstwo_id.in_(controlled_ids(db.session, country_id)), Region.terytorium_zamorskie.is_(False)
    ).order_by(Region.region_id))]


def own_metropolitan_region_ids(country_id):
    """Only the country's own mainland, excluding dependent countries."""
    return [str(id) for id in db.session.scalars(select(Region.region_id).where(
        Region.panstwo_id == country_id, Region.terytorium_zamorskie.is_(False)
    ).order_by(Region.region_id))]
