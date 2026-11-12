"""Demografia państwa przypisanego do zalogowanego gracza."""

from game.population_structure import structure_data
from game.governance import controlled_ids, economy
from datetime import date
from decimal import Decimal

from flask import (
    Blueprint, abort, redirect, render_template,
    session, url_for,
)
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from extensions import db
from game.country_summary import country_summary, metropolitan_region_ids
from engine.clock import get_current_entenda_date
from game.models import GameUser, GamePlayerCountry
from models import Panstwo, Region, Miasto, HistoriaPopulacjiPanstw


demography_bp = Blueprint(
    "game_demography",
    __name__,
    url_prefix="/game/demografia",
)


def number_text(value, digits=2):
    if value is None:
        return "—"

    return (
        f"{value:,.{digits}f}"
        .replace(",", "\u00a0")
        .replace(".", ",")
    )


@demography_bp.get("")
def page():
    from game.forum import player
    user,country=player()
    if user is None:return redirect(url_for('wejscie'))


    scope = controlled_ids(db.session, country.PANSTWO_ID)
    managed_regions = list(db.session.scalars(select(Region).options(selectinload(Region.miasta)).where(Region.panstwo_id.in_(scope))))
    managed_cities = list(db.session.scalars(select(Miasto).where(Miasto.panstwo_id.in_(scope))))
    totals = economy(db.session, country.PANSTWO_ID)

    rows = db.session.scalars(
        select(HistoriaPopulacjiPanstw)
        .where(
            HistoriaPopulacjiPanstw.panstwo_id.in_(scope),
            HistoriaPopulacjiPanstw.data_entenda >= date(2995, 1, 1),
            HistoriaPopulacjiPanstw.data_entenda < date(3011, 1, 1),
        )
        .order_by(
            HistoriaPopulacjiPanstw.data_entenda,
            HistoriaPopulacjiPanstw.data_rzeczywista,
            HistoriaPopulacjiPanstw.id,
        )
    ).all()

    by_year = {}
    for row in rows:
        by_year.setdefault(row.data_entenda.year, {})[row.panstwo_id] = int(row.panstwo_populacja)
    yearly = {year: sum(values.values()) for year, values in by_year.items() if set(values) == set(scope)}

    maximum = max(yearly.values(), default=0)
    history = [
        {
            "year": year,
            "population": yearly.get(year),
            "height": (
                yearly[year] / maximum * 100
                if year in yearly and maximum > 0 else 0
            ),
            "label": number_text(yearly.get(year), 0),
        }
        for year in range(2995, 3011)
    ]

    population = totals["population"]
    urban_population = sum(
        city.miasto_populacja or 0 for city in managed_cities
    )
    area = totals["area"]

    # Średnia ważona osobno dla populacji miejskiej i wiejskiej.
    # Jeśli brakuje stawki dla zamieszkanej grupy, nie pokazujemy
    # częściowej średniej jako średniej całego państwa.
    weighted_growth = Decimal("0")
    growth_population = 0
    growth_complete = True

    regions = {}
    for region in managed_regions:
        city_population = sum(
            city.miasto_populacja or 0 for city in region.miasta
        )
        rural_population = region.region_ludnosc_pozamiejska or 0

        for count, rate in (
            (city_population, region.roczny_przyrost_miasto_pct),
            (rural_population, region.roczny_przyrost_wies_pct),
        ):
            if count <= 0:
                continue
            if rate is None:
                growth_complete = False
                continue
            weighted_growth += Decimal(count) * Decimal(str(rate))
            growth_population += count

        regions[str(region.region_id)] = {
            "name": region.region_nazwa,
            "population": int(city_population + rural_population),
        }

    growth = (
        weighted_growth / Decimal(growth_population)
        if growth_complete and growth_population else None
    )

    current_year = get_current_entenda_date().year

    # Porównanie z ostatnim zapisem poprzedniego roku,
    # również gdy rok ten wypada poza zakresem wykresu.
    previous_rows = db.session.scalars(
        select(HistoriaPopulacjiPanstw)
        .where(
            HistoriaPopulacjiPanstw.panstwo_id.in_(scope),
            HistoriaPopulacjiPanstw.data_entenda >= date(
                current_year - 1, 1, 1
            ),
            HistoriaPopulacjiPanstw.data_entenda < date(current_year, 1, 1),
        )
        .order_by(
            HistoriaPopulacjiPanstw.data_entenda.desc(),
            HistoriaPopulacjiPanstw.data_rzeczywista.desc(),
            HistoriaPopulacjiPanstw.id.desc(),
        )
    ).all()

    previous_by_country = {}
    for row in previous_rows:
        previous_by_country.setdefault(row.panstwo_id, row.panstwo_populacja)
    previous_population = sum(previous_by_country.values()) if set(previous_by_country) == set(scope) else None
    trend = (
        1 if population > previous_population
        else -1 if population < previous_population
        else 0
    ) if population is not None and previous_population is not None else None

    urbanization = (
        Decimal(urban_population) / Decimal(population) * 100
        if population else None
    )
    density = (
        Decimal(population) / Decimal(area)
        if population is not None and area and area > 0 else None
    )

    metrics = [
        {
            "name": "Obecna populacja",
            "value": number_text(population, 0),
            "trend": trend,
            "trend_label": (
                "Wzrost względem poprzedniego roku" if trend == 1
                else "Spadek względem poprzedniego roku" if trend == -1
                else "Bez zmian względem poprzedniego roku" if trend == 0
                else "Brak danych z poprzedniego roku"
            ),
            "color": "",
        },
        {
            "name": "Średni przyrost naturalny",
            "value": (
                number_text(growth) + "%" if growth is not None else "—"
            ),
            "color": (
                "demo-positive" if growth is not None and growth > 0
                else "demo-negative" if growth is not None and growth < 0
                else ""
            ),
        },
        {
            "name": "Urbanizacja",
            "value": (
                number_text(urbanization) + "%"
                if urbanization is not None else "—"
            ),
        },
        {
            "name": "Gęstość zaludnienia",
            "value": (
                number_text(density) + " os./km²"
                if density is not None else "—"
            ),
        },
        {"name": "Liczba regionów", "value": len(managed_regions)},
        {"name": "Liczba miast", "value": len(managed_cities)},
    ]

    response = render_template(
        "game/demografia.html",
        game_user=user,
        game_country=country_summary(country),
        game_home_url=url_for("game_main_page"),
        game_logout_url=url_for("game_logout"),
        game_active_page="demography",
        history=history,
        metrics=metrics,age_structure=structure_data(db.session,country.PANSTWO_ID),
        demographic_map={
            "metropolitanRegionIds": metropolitan_region_ids(country.PANSTWO_ID),
            "countryId": country.PANSTWO_ID,
            "regions": regions,
            "cities": {
                str(city.miasto_id): {
                    "name": city.miasto_nazwa,
                    "population": city.miasto_populacja,
                    "regionId": str(city.region_id),
                }
                for city in managed_cities
            },
            "countriesUrl": url_for('region_sovereignty.country_boundaries'),
            "regionsUrl": url_for(
                "static", filename="maps/entenda_regiony.geojson"
            ),
            "citiesUrl": url_for(
                "static", filename="maps/entenda_miasta.geojson"
            ),
        },
    )
    return response, 200, {"Cache-Control": "no-store"}