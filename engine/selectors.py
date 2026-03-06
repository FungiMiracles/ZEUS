import random
from models import Region


def region_weight(region):
    """
    Wylicza wagę regionu jako potencjalnego miejsca zdarzenia.
    """
    pop = region.region_populacja or 0
    infra_r = region.region_stan_infra_drogowej or 100
    infra_k = region.region_stan_infra_kolejowej or 100
    seismic = region.region_sejsmicznosc or 0

    # większa populacja = większa szansa
    pop_factor = pop / 1_000_000

    # gorsza infrastruktura zwiększa ryzyko
    infra_factor = (200 - infra_r - infra_k) / 100

    # sejsmiczność zwiększa wagę
    seismic_factor = seismic / 100

    weight = 1 + pop_factor + infra_factor + seismic_factor

    return max(weight, 0.1)


def select_regions(limit=20):
    """
    Zwraca listę regionów wybranych losowo według wag.
    """
    regions = Region.query.all()

    weights = [region_weight(r) for r in regions]

    selected = random.choices(
        regions,
        weights=weights,
        k=min(limit, len(regions))
    )

    return selected