"""Annual world series, using each country's last recorded value in a year."""
from sqlalchemy import select
from models import (HistoriaPopulacjiPanstw, PKBStateHistory,
                    RocznyPrzyrostStateHistory, RegionStateHistory, Region, Panstwo, ProcentWzrostuStateHistory)


def annual_country_values(session, model, value_column):
    rows = session.execute(select(model.panstwo_id, model.data_entenda, value_column)
                           .join(Panstwo, Panstwo.PANSTWO_ID == model.panstwo_id)
                           .order_by(model.data_entenda, model.id)).all()
    years = {}
    for country_id, when, value in rows:
        years.setdefault(when.year, {})[country_id] = value
    return years


def world_chart(session, kind):
    series, coverage = {}, {}
    description = 'Suma ostatnich zapisów rocznych państw. Lata bez danych pozostają puste.'
    populations = annual_country_values(session, HistoriaPopulacjiPanstw, HistoriaPopulacjiPanstw.panstwo_populacja) if kind in ('populacja', 'pkbpc', 'przyrost_ludnosci') else {}
    gdps = annual_country_values(session, PKBStateHistory, PKBStateHistory.new_pkb) if kind in ('pkb', 'pkbpc', 'wzrost_pkb') else {}
    if kind in ('populacja', 'pkb'):
        for year, records in (populations if kind == 'populacja' else gdps).items():
            values = [value for value in records.values() if value is not None]
            series[year] = sum(values) if values else None
            coverage[year] = len(values)
    elif kind == 'pkbpc':
        description = 'Łączne PKB podzielone przez łączną ludność. Oba zbiory muszą obejmować te same państwa w danym roku.'
        for year in populations.keys() | gdps.keys():
            pop, gdp = populations.get(year, {}), gdps.get(year, {})
            complete = bool(pop) and pop.keys() == gdp.keys() and all(v is not None for v in [*pop.values(), *gdp.values()])
            total = sum(pop.values()) if complete else 0
            series[year] = round(sum(gdp.values()) / total, 2) if total > 0 else None
            coverage[year] = len(pop) if complete else 0
    elif kind == 'wzrost_pkb':
        description = 'Średnia ostatnich zapisów rocznego współczynnika wzrostu PKB, ważona PKB państw z tego samego roku. Niekompletne pary danych pozostają puste.'
        rates = annual_country_values(session, ProcentWzrostuStateHistory, ProcentWzrostuStateHistory.new_wzrost)
        for year in rates.keys() | gdps.keys():
            weights, rate = gdps.get(year, {}), rates.get(year, {})
            complete = bool(weights) and weights.keys() == rate.keys() and all(v is not None for v in [*weights.values(), *rate.values()]) and all(v >= 0 for v in weights.values())
            total = sum(weights.values()) if complete else 0
            series[year] = float(round(sum(weights[id] * rate[id] for id in weights) / total, 4)) if total > 0 else None
            coverage[year] = len(weights) if total > 0 else 0
    elif kind == 'przyrost_ludnosci':
        description = 'Średni roczny procent zmiany ludności, ważony populacją państw z tego samego roku. Niekompletne pary danych pozostają puste.'
        rates = annual_country_values(session, RocznyPrzyrostStateHistory, RocznyPrzyrostStateHistory.new_roczny_przyrost)
        for year in rates.keys() | populations.keys():
            pop, rate = populations.get(year, {}), rates.get(year, {})
            complete = bool(pop) and pop.keys() == rate.keys() and all(v is not None for v in [*pop.values(), *rate.values()])
            total = sum(pop.values()) if complete else 0
            series[year] = round(sum(pop[id] * rate[id] for id in pop) / total, 4) if total > 0 else None
            coverage[year] = len(pop) if complete else 0
    else:
        description = 'Średnia zapisanych regionalnych wskaźników infrastruktury z 31 grudnia; infrastruktura portowa obejmuje regiony z dostępem do portów.'
        h = RegionStateHistory
        rows = session.execute(select(h, Region.region_polozenie_id).join(Region, Region.region_id == h.region_id)
                               .join(Panstwo, Panstwo.PANSTWO_ID == Region.panstwo_id)
                               .where(h.data_entenda.is_not(None))
                               .order_by(h.data_entenda, h.id)).all()
        latest = {}
        for row, location in rows:
            if (row.data_entenda.month, row.data_entenda.day) == (12, 31):
                latest[(row.data_entenda.year, row.region_id)] = (row, location)
        indicators = {}
        for (year, _), (row, location) in latest.items():
            values = [row.old_kolej, row.old_drogi, row.old_energia, row.old_mieszkania]
            if location and location != 1:
                values.append(row.old_porty)
            indicators.setdefault(year, []).extend(value for value in values if value is not None)
        for year, values in indicators.items():
            series[year] = round(sum(values) / len(values), 2) if values else None
    titles = {'populacja': ('Populacja świata', 'population'), 'pkb': ('PKB świata', 'pkb'),
              'pkbpc': ('PKB per capita świata', 'pkbpc'),
              'przyrost_ludnosci': ('Roczny procent zmiany ludności świata', 'population_growth_pct'),
              'wzrost_pkb': ('Roczny procent wzrostu PKB świata', 'gdp_growth_pct'),
              'infrastruktura': ('Infrastruktura świata', 'infra')}
    title, unit = titles[kind]
    years = list(range(min([2995, *series]), max([3035, *series]) + 1))
    return {'success': True, 'title': title, 'unit': unit, 'labels': years,
            'values': [series.get(year) for year in years], 'description': description,
            'countryCounts': [coverage.get(year) for year in years]}
