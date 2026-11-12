import random
from models import Region, Panstwo


def active_regions():
    return Region.query.filter(Region.panstwo_id.in_(
        Panstwo.query.with_entities(Panstwo.PANSTWO_ID).filter(Panstwo.status == 'aktywne')
    ))

def region_weight(region):

    # =========================================
    # POPULACJA
    # =========================================

    miasta_pop = sum(
        (m.miasto_populacja or 0)
        for m in region.miasta
    )

    rural_pop = region.region_ludnosc_pozamiejska or 0

    total_pop = miasta_pop + rural_pop

    pop_factor = total_pop / 1_000_000

    # =========================================
    # INFRASTRUKTURA
    # =========================================

    infra_values = [
    region.region_stan_infra_drogowej,
    region.region_stan_infra_kolejowej,
    region.region_stan_infra_energetycznej,
    region.region_stan_infra_mieszkalnej,
    region.region_stan_infra_portowej
    ]

    infra_values = [v for v in infra_values if v is not None]

    infra_avg = sum(infra_values) / len(infra_values) if infra_values else 100

    infra_factor = (100 - infra_avg) / 35

    # =========================================
    # ZAGROŻENIA NATURALNE
    # =========================================

    seismic_factor = (region.region_sejsmicznosc or 0) / 120

    flood_factor = (region.region_ryzyko_powodzi or 0) / 140

    avalanche_factor = (region.region_ryzyko_lawin or 0) / 180

    frost_factor = (region.region_ryzyko_mrozu or 0) / 180

    heat_factor = (region.region_ryzyko_upalu or 0) / 180

    volcano_factor = (region.region_aktywny_wulkan or 0) / 150

    # =========================================
    # BONUSY ŚRODOWISKOWE
    # =========================================

    forest_bonus = 0

    if (
        region.region_typ_nadrz_id == 8 or
        region.region_typ_podrz_id == 17
    ):
        forest_bonus = 0.2

    coastal_bonus = 0

    if region.region_polozenie_id == 2:
        coastal_bonus = 0.15

    # =========================================
    # FINALNA WAGA
    # =========================================

    weight = (
        1
        + pop_factor
        + infra_factor
        + seismic_factor
        + flood_factor
        + avalanche_factor
        + frost_factor
        + heat_factor
        + volcano_factor
        + forest_bonus
        + coastal_bonus
    )

    return max(weight, 0.1)


def select_regions(limit=20):

    regions = active_regions().all()

    weighted = []

    for r in regions:

        w = region_weight(r)

        score = random.random() ** (1 / (w + 0.0001))

        weighted.append((score, r))

    weighted.sort(reverse=True)

    return [r for _, r in weighted[:limit]]
