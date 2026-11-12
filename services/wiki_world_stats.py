"""Population-weighted world structure and GDP comparison for the wiki."""
from datetime import date
from decimal import Decimal, ROUND_FLOOR
from sqlalchemy import select, func
from models import Panstwo, PKBStateHistory, Region, Miasto, Zdarzenie
from game.population_structure import PopulationStructure


def world_current_metrics(session):
    """Live aggregates for active countries; missing indicators are not zeroes."""
    population, gdp, gdp_count = session.execute(select(
        func.sum(Panstwo.panstwo_populacja), func.sum(Panstwo.panstwo_PKB),
        func.count(Panstwo.panstwo_PKB))).one()
    population = int(population or 0)
    urban = session.scalar(select(func.sum(Miasto.miasto_populacja))
        .join(Panstwo, Panstwo.PANSTWO_ID == Miasto.panstwo_id))
    city_populations = select(Miasto.region_id,
        func.sum(Miasto.miasto_populacja).label('urban')).group_by(Miasto.region_id).subquery()
    regions = session.execute(select(
        Region.region_ludnosc_pozamiejska, city_populations.c.urban,
        Region.roczny_przyrost_wies_pct, Region.roczny_przyrost_miasto_pct,
        Region.region_stan_infra_drogowej, Region.region_stan_infra_kolejowej,
        Region.region_stan_infra_energetycznej, Region.region_stan_infra_mieszkalnej,
        Region.region_stan_infra_portowej, Region.region_polozenie_id,
    ).join(Panstwo, Panstwo.PANSTWO_ID == Region.panstwo_id)
     .outerjoin(city_populations, city_populations.c.region_id == Region.region_id)).all()
    indicators = []
    growth_sum = Decimal(0)
    growth_population = 0
    for rural_pop, urban_pop, rural_rate, urban_rate, road, rail, energy, housing, port, location in regions:
        indicators.extend(value for value in (road, rail, energy, housing) if value is not None)
        if location and location != 1 and port is not None:
            indicators.append(port)
        for count, rate in [(rural_pop, rural_rate), (urban_pop, urban_rate)]:
            if count is not None and count > 0 and rate is not None:
                growth_sum += Decimal(str(rate)) * int(count)
                growth_population += int(count)
    return {
        'gdp_per_capita': Decimal(gdp) / population if population > 0 and gdp_count else None,
        'infrastructure': Decimal(sum(indicators)) / len(indicators) if indicators else None,
        'urbanization': Decimal(int(urban)) * 100 / population if population > 0 and urban is not None else None,
        'population_growth': growth_sum / growth_population if growth_population else None,
        'events': session.scalar(select(func.count(Zdarzenie.zdarzenie_id))) or 0,
    }


def world_population_structure(session):
    rows = session.execute(select(
        Panstwo.panstwo_populacja, PopulationStructure.children,
        PopulationStructure.working, PopulationStructure.seniors,
    ).outerjoin(PopulationStructure, PopulationStructure.panstwo_id == Panstwo.PANSTWO_ID)).all()
    total = covered = 0
    weights = [Decimal(0), Decimal(0), Decimal(0)]
    for population, *shares in rows:
        population = max(int(population or 0), 0)
        total += population
        if population and all(share is not None for share in shares):
            covered += population
            for i, share in enumerate(shares):
                weights[i] += population * share
    hundredths = [0, 0, 0]
    if covered:
        exact = [weight * 100 / covered for weight in weights]
        hundredths = [int(value.to_integral_value(rounding=ROUND_FLOOR)) for value in exact]
        for i in sorted(range(3), key=lambda i: (-(exact[i] - hundredths[i]), i))[:10000 - sum(hundredths)]:
            hundredths[i] += 1
    return {
        'groups': [dict(key=key, label=label, percent=value / 100) for key, label, value in zip(
            ('children', 'working', 'seniors'), ('0–17 lat', '18–64 lata', '65+ lat'), hundredths)],
        'population': str(total), 'coveredPopulation': str(covered),
        'coveragePercent': float(round(Decimal(covered) * 100 / total, 4)) if total else 0,
    }


def world_gdp(session, year):
    countries = dict(session.execute(select(Panstwo.PANSTWO_ID, Panstwo.panstwo_PKB)).all())
    current = sum(int(value or 0) for value in countries.values())
    history = session.execute(select(
        PKBStateHistory.panstwo_id, PKBStateHistory.new_pkb,
    ).where(
        PKBStateHistory.data_entenda >= date(year - 1, 1, 1),
        PKBStateHistory.data_entenda < date(year, 1, 1),
    ).order_by(PKBStateHistory.data_entenda, PKBStateHistory.id)).all()
    previous = dict(history)
    known = {id for id, value in countries.items() if value is not None}
    comparable = bool(known) and all(previous.get(id) is not None for id in known)
    prior = sum(int(previous[id]) for id in known) if comparable else None
    trend = None if prior is None else ('up' if current > prior else 'down' if current < prior else 'flat')
    result = {'total': current, 'previous': prior, 'trend': trend, 'previousYear': year - 1}
    # Before this year's annual recalculation, current GDP still equals last year's
    # closing snapshot. Show the latest completed annual change in that case.
    if trend == 'flat':
        annual = session.execute(select(
            PKBStateHistory.panstwo_id, PKBStateHistory.data_entenda,
            PKBStateHistory.old_pkb, PKBStateHistory.new_pkb,
        ).where(
            PKBStateHistory.source == 'PKB_REGEN',
            PKBStateHistory.data_entenda < date(year + 1, 1, 1),
        ).order_by(PKBStateHistory.data_entenda.desc(), PKBStateHistory.id.desc())).all()
        by_year = {}
        for row in annual:
            by_year.setdefault(row.data_entenda.year, {}).setdefault(row.panstwo_id, row)
        for annual_year, records in by_year.items():
            if not all(id in records and records[id].old_pkb is not None and records[id].new_pkb is not None for id in known):
                continue
            before = sum(int(records[id].old_pkb) for id in known)
            after = sum(int(records[id].new_pkb) for id in known)
            result.update(previous=before, previousYear=annual_year - 1, comparisonYear=annual_year,
                          trend='up' if after > before else 'down' if after < before else 'flat')
            break
    return result
