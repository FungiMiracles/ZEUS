# engine/effects.py

import random

MIN_INFRA = 10


def _degrade(value, damage):
    """
    Obniża wartość infrastruktury, ale nigdy poniżej MIN_INFRA.
    """
    if value is None:
        return value

    new_val = value - damage
    return max(new_val, MIN_INFRA)


def _apply_population_loss(region, victims):
    """
    Aktualizuje populację regionu o liczbę ofiar.
    """
    if region.region_populacja is None:
        return

    region.region_populacja = max(region.region_populacja - victims, 0)


# =====================================================
# TRZĘSIENIE ZIEMI
# =====================================================

def apply_earthquake_effect(region, scale, victims):

    _apply_population_loss(region, victims)

    # uszkodzenia infrastruktury zależne od skali
    damage_base = scale * random.randint(2, 5)

    region.region_stan_infra_drogowej = _degrade(
        region.region_stan_infra_drogowej,
        damage_base
    )

    region.region_stan_infra_kolejowej = _degrade(
        region.region_stan_infra_kolejowej,
        damage_base
    )

    region.region_stan_infra_energetycznej = _degrade(
        region.region_stan_infra_energetycznej,
        scale * random.randint(2, 4)
    )

    region.region_stan_infra_mieszkalnej = _degrade(
        region.region_stan_infra_mieszkalnej,
        scale * random.randint(3, 6)
    )


# =====================================================
# KATASTROFA KOLEJOWA
# =====================================================

def apply_train_disaster_effect(region, scale, victims):

    _apply_population_loss(region, victims)

    damage = scale * random.randint(1, 3)

    region.region_stan_infra_kolejowej = _degrade(
        region.region_stan_infra_kolejowej,
        damage
    )


# =====================================================
# KATASTROFA DROGOWA
# =====================================================

def apply_road_disaster_effect(region, scale, victims):

    _apply_population_loss(region, victims)

    damage = scale * random.randint(1, 2)

    region.region_stan_infra_drogowej = _degrade(
        region.region_stan_infra_drogowej,
        damage
    )