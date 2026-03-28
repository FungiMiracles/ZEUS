# engine/effects.py

import random
from datetime import datetime
from models import RegionalDataChange
from extensions import db
from engine.clock import get_current_entenda_date

MIN_INFRA = 10

def _degrade(value, damage):
    if value is None:
        return value

    new_val = value - damage
    return max(new_val, MIN_INFRA)

def _regenerate(value, percent):
    if value is None or percent is None:
        return value

    new_val = value + (value * percent / 100)
    return min(int(new_val), 100)

def apply_region_regeneration(region):

    # 🟡 stare wartości
    old_drogi = region.region_stan_infra_drogowej or 0
    old_kolej = region.region_stan_infra_kolejowej or 0
    old_energia = region.region_stan_infra_energetycznej or 0
    old_mieszkania = region.region_stan_infra_mieszkalnej or 0
    old_porty = region.region_stan_infra_portowej or 0

    # 🔧 regeneracja (Twoja logika)
    region.region_stan_infra_drogowej = _regenerate(
        region.region_stan_infra_drogowej,
        region.procreg_infra_drogowa
    )

    region.region_stan_infra_kolejowej = _regenerate(
        region.region_stan_infra_kolejowej,
        region.procreg_infra_kolejowa
    )

    region.region_stan_infra_energetycznej = _regenerate(
        region.region_stan_infra_energetycznej,
        region.procreg_infra_energetyczna
    )

    region.region_stan_infra_mieszkalnej = _regenerate(
        region.region_stan_infra_mieszkalnej,
        region.procreg_infra_mieszkaniowa
    )

    if region.region_polozenie_id == 2:
        region.region_stan_infra_portowej = _regenerate(
            region.region_stan_infra_portowej,
            region.procreg_infra_portowa
        )

    # 🔵 delta
    delta_drogi = (region.region_stan_infra_drogowej or 0) - old_drogi
    delta_kolej = (region.region_stan_infra_kolejowej or 0) - old_kolej
    delta_energia = (region.region_stan_infra_energetycznej or 0) - old_energia
    delta_mieszkania = (region.region_stan_infra_mieszkalnej or 0) - old_mieszkania
    delta_porty = (region.region_stan_infra_portowej or 0) - old_porty

    # 🟢 log
    log_region_change(
        region=region,
        data_entenda=get_current_entenda_date(),
        source="REGEN",
        delta_drogi=delta_drogi,
        delta_kolej=delta_kolej,
        delta_energia=delta_energia,
        delta_mieszkania=delta_mieszkania,
        delta_porty=delta_porty
    )

def _apply_population_loss(region, victims):

    if region.region_ludnosc_pozamiejska is None:
        return

    region.region_ludnosc_pozamiejska = max(region.region_ludnosc_pozamiejska - victims, 0)

def log_region_change(
    region,
    data_entenda,
    source,
    event_id=None,
    delta_ludnosc=0,
    delta_drogi=0,
    delta_kolej=0,
    delta_energia=0,
    delta_mieszkania=0,
    delta_porty=0
):

    if all(v == 0 for v in [
        delta_ludnosc,
        delta_drogi,
        delta_kolej,
        delta_energia,
        delta_mieszkania,
        delta_porty
    ]):
        return

    change = RegionalDataChange(
        region_id=region.region_id,
        data_entenda=data_entenda,
        data_rzeczywista=datetime.utcnow(),
        source=source,
        event_id=event_id,

        delta_ludnosc_pozamiejska=delta_ludnosc,
        delta_infra_drogowa=delta_drogi,
        delta_infra_kolejowa=delta_kolej,
        delta_infra_energetyczna=delta_energia,
        delta_infra_mieszkaniowa=delta_mieszkania,
        delta_infra_portowa=delta_porty
    )

    db.session.add(change)

# =====================================================
# TRZĘSIENIE ZIEMI
# =====================================================

def apply_earthquake_effect(region, scale, victims):

    old_pop = region.region_ludnosc_pozamiejska or 0

    _apply_population_loss(region, victims)

    new_pop = region.region_ludnosc_pozamiejska or 0
    delta_ludnosc = new_pop - old_pop

    old_drogi = region.region_stan_infra_drogowej or 0
    old_kolej = region.region_stan_infra_kolejowej or 0
    old_energia = region.region_stan_infra_energetycznej or 0
    old_mieszkania = region.region_stan_infra_mieszkalnej or 0

    damage_base = int(scale * random.uniform(0.5, 1))

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

    # 🔵 policz zmiany
    delta_drogi = (region.region_stan_infra_drogowej or 0) - old_drogi
    delta_kolej = (region.region_stan_infra_kolejowej or 0) - old_kolej
    delta_energia = (region.region_stan_infra_energetycznej or 0) - old_energia
    delta_mieszkania = (region.region_stan_infra_mieszkalnej or 0) - old_mieszkania

    log_region_change(
        region=region,
        data_entenda=get_current_entenda_date(),
        source="EVENT",
        delta_ludnosc=delta_ludnosc,
        delta_drogi=delta_drogi,
        delta_kolej=delta_kolej,
        delta_energia=delta_energia,
        delta_mieszkania=delta_mieszkania
    )

# =====================================================
# KATASTROFA KOLEJOWA
# =====================================================

def apply_train_disaster_effect(region, scale, victims):

    old_pop = region.region_ludnosc_pozamiejska or 0

    _apply_population_loss(region, victims)

    new_pop = region.region_ludnosc_pozamiejska or 0
    delta_ludnosc = new_pop - old_pop

    old_drogi = region.region_stan_infra_drogowej or 0
    old_kolej = region.region_stan_infra_kolejowej or 0
    old_energia = region.region_stan_infra_energetycznej or 0
    old_mieszkania = region.region_stan_infra_mieszkalnej or 0

    damage = int(scale * random.uniform(0.5, 1))

    region.region_stan_infra_kolejowej = _degrade(
        region.region_stan_infra_kolejowej,
        damage
    )

    # 🔵 policz zmiany
    delta_drogi = (region.region_stan_infra_drogowej or 0) - old_drogi
    delta_kolej = (region.region_stan_infra_kolejowej or 0) - old_kolej
    delta_energia = (region.region_stan_infra_energetycznej or 0) - old_energia
    delta_mieszkania = (region.region_stan_infra_mieszkalnej or 0) - old_mieszkania

    log_region_change(
        region=region,
        data_entenda=get_current_entenda_date(),
        source="EVENT",
        delta_ludnosc=delta_ludnosc,
        delta_drogi=delta_drogi,
        delta_kolej=delta_kolej,
        delta_energia=delta_energia,
        delta_mieszkania=delta_mieszkania
    )


# =====================================================
# KATASTROFA DROGOWA
# =====================================================

def apply_road_disaster_effect(region, scale, victims):

    old_pop = region.region_ludnosc_pozamiejska or 0

    _apply_population_loss(region, victims)

    new_pop = region.region_ludnosc_pozamiejska or 0
    delta_ludnosc = new_pop - old_pop

    old_drogi = region.region_stan_infra_drogowej or 0
    old_kolej = region.region_stan_infra_kolejowej or 0
    old_energia = region.region_stan_infra_energetycznej or 0
    old_mieszkania = region.region_stan_infra_mieszkalnej or 0

    damage = int(scale * random.uniform(0.5, 1))

    region.region_stan_infra_drogowej = _degrade(
        region.region_stan_infra_drogowej,
        damage
    )

    # 🔵 policz zmiany
    delta_drogi = (region.region_stan_infra_drogowej or 0) - old_drogi
    delta_kolej = (region.region_stan_infra_kolejowej or 0) - old_kolej
    delta_energia = (region.region_stan_infra_energetycznej or 0) - old_energia
    delta_mieszkania = (region.region_stan_infra_mieszkalnej or 0) - old_mieszkania

    log_region_change(
        region=region,
        data_entenda=get_current_entenda_date(),
        source="EVENT",
        delta_ludnosc=delta_ludnosc,
        delta_drogi=delta_drogi,
        delta_kolej=delta_kolej,
        delta_energia=delta_energia,
        delta_mieszkania=delta_mieszkania
    )
    
# =====================================================
# POWÓDŹ
# =====================================================
    
def apply_flood_effect(region, scale, victims):

    old_pop = region.region_ludnosc_pozamiejska or 0

    _apply_population_loss(region, victims)

    new_pop = region.region_ludnosc_pozamiejska or 0
    delta_ludnosc = new_pop - old_pop

    old_drogi = region.region_stan_infra_drogowej or 0
    old_kolej = region.region_stan_infra_kolejowej or 0
    old_energia = region.region_stan_infra_energetycznej or 0
    old_mieszkania = region.region_stan_infra_mieszkalnej or 0

    damage = int(scale * random.uniform(0.5, 1))

    region.region_stan_infra_drogowej = _degrade(
        region.region_stan_infra_drogowej,
        damage
    )

    region.region_stan_infra_kolejowej = _degrade(
        region.region_stan_infra_kolejowej,
        damage
    )

    region.region_stan_infra_mieszkalnej = _degrade(
        region.region_stan_infra_mieszkalnej,
        damage
    )

    # 🔵 policz zmiany
    delta_drogi = (region.region_stan_infra_drogowej or 0) - old_drogi
    delta_kolej = (region.region_stan_infra_kolejowej or 0) - old_kolej
    delta_energia = (region.region_stan_infra_energetycznej or 0) - old_energia
    delta_mieszkania = (region.region_stan_infra_mieszkalnej or 0) - old_mieszkania

    log_region_change(
        region=region,
        data_entenda=get_current_entenda_date(),
        source="EVENT",
        delta_ludnosc=delta_ludnosc,
        delta_drogi=delta_drogi,
        delta_kolej=delta_kolej,
        delta_energia=delta_energia,
        delta_mieszkania=delta_mieszkania
    )

# =====================================================
# LAWINA
# =====================================================

def apply_avalanche_effect(region, scale, victims):

    old_pop = region.region_ludnosc_pozamiejska or 0

    _apply_population_loss(region, victims)

    new_pop = region.region_ludnosc_pozamiejska or 0
    delta_ludnosc = new_pop - old_pop

    old_drogi = region.region_stan_infra_drogowej or 0
    old_kolej = region.region_stan_infra_kolejowej or 0
    old_energia = region.region_stan_infra_energetycznej or 0
    old_mieszkania = region.region_stan_infra_mieszkalnej or 0

    damage = int(scale * random.uniform(0.4, 0.7))

    region.region_stan_infra_mieszkalnej = _degrade(
        region.region_stan_infra_mieszkalnej,
        damage
    )

    # 🔵 policz zmiany
    delta_drogi = (region.region_stan_infra_drogowej or 0) - old_drogi
    delta_kolej = (region.region_stan_infra_kolejowej or 0) - old_kolej
    delta_energia = (region.region_stan_infra_energetycznej or 0) - old_energia
    delta_mieszkania = (region.region_stan_infra_mieszkalnej or 0) - old_mieszkania

    log_region_change(
        region=region,
        data_entenda=get_current_entenda_date(),
        source="EVENT",
        delta_ludnosc=delta_ludnosc,
        delta_drogi=delta_drogi,
        delta_kolej=delta_kolej,
        delta_energia=delta_energia,
        delta_mieszkania=delta_mieszkania
    )

# =====================================================
# ERUPCJA WULKANU
# =====================================================

def apply_volcano_effect(region, scale, victims):

    old_pop = region.region_ludnosc_pozamiejska or 0

    _apply_population_loss(region, victims)

    new_pop = region.region_ludnosc_pozamiejska or 0
    delta_ludnosc = new_pop - old_pop

    old_drogi = region.region_stan_infra_drogowej or 0
    old_kolej = region.region_stan_infra_kolejowej or 0
    old_energia = region.region_stan_infra_energetycznej or 0
    old_mieszkania = region.region_stan_infra_mieszkalnej or 0

    damage = int(scale * random.uniform(0.5, 1))

    region.region_stan_infra_drogowej = _degrade(
        region.region_stan_infra_drogowej,
        damage
    )

    region.region_stan_infra_kolejowej = _degrade(
        region.region_stan_infra_kolejowej,
        damage
    )

    region.region_stan_infra_mieszkalnej = _degrade(
        region.region_stan_infra_mieszkalnej,
        damage
    )

    # 🔵 policz zmiany
    delta_drogi = (region.region_stan_infra_drogowej or 0) - old_drogi
    delta_kolej = (region.region_stan_infra_kolejowej or 0) - old_kolej
    delta_energia = (region.region_stan_infra_energetycznej or 0) - old_energia
    delta_mieszkania = (region.region_stan_infra_mieszkalnej or 0) - old_mieszkania

    log_region_change(
        region=region,
        data_entenda=get_current_entenda_date(),
        source="EVENT",
        delta_ludnosc=delta_ludnosc,
        delta_drogi=delta_drogi,
        delta_kolej=delta_kolej,
        delta_energia=delta_energia,
        delta_mieszkania=delta_mieszkania
    )

# =====================================================
# FALA MROZU
# =====================================================

def apply_coldwave_effect(region, scale, victims):

    old_pop = region.region_ludnosc_pozamiejska or 0

    _apply_population_loss(region, victims)

    new_pop = region.region_ludnosc_pozamiejska or 0
    delta_ludnosc = new_pop - old_pop

    old_drogi = region.region_stan_infra_drogowej or 0
    old_kolej = region.region_stan_infra_kolejowej or 0
    old_energia = region.region_stan_infra_energetycznej or 0
    old_mieszkania = region.region_stan_infra_mieszkalnej or 0

    damage = int(scale * random.uniform(0.6, 0.9))

    region.region_stan_infra_drogowej = _degrade(
        region.region_stan_infra_drogowej,
        damage
    )

    region.region_stan_infra_energetycznej = _degrade(
        region.region_stan_infra_energetycznej,
        damage
    )    

    region.region_stan_infra_mieszkalnej = _degrade(
        region.region_stan_infra_mieszkalnej,
        damage
    )

    # 🔵 policz zmiany
    delta_drogi = (region.region_stan_infra_drogowej or 0) - old_drogi
    delta_kolej = (region.region_stan_infra_kolejowej or 0) - old_kolej
    delta_energia = (region.region_stan_infra_energetycznej or 0) - old_energia
    delta_mieszkania = (region.region_stan_infra_mieszkalnej or 0) - old_mieszkania

    log_region_change(
        region=region,
        data_entenda=get_current_entenda_date(),
        source="EVENT",
        delta_ludnosc=delta_ludnosc,
        delta_drogi=delta_drogi,
        delta_kolej=delta_kolej,
        delta_energia=delta_energia,
        delta_mieszkania=delta_mieszkania
    )

# =====================================================
# FALA UPAŁU
# =====================================================

def apply_heatwave_effect(region, scale, victims):

    old_pop = region.region_ludnosc_pozamiejska or 0

    _apply_population_loss(region, victims)

    new_pop = region.region_ludnosc_pozamiejska or 0
    delta_ludnosc = new_pop - old_pop

    old_drogi = region.region_stan_infra_drogowej or 0
    old_kolej = region.region_stan_infra_kolejowej or 0
    old_energia = region.region_stan_infra_energetycznej or 0
    old_mieszkania = region.region_stan_infra_mieszkalnej or 0

    damage = int(scale * random.uniform(0.8, 1.1))

    region.region_stan_infra_energetycznej = _degrade(
        region.region_stan_infra_energetycznej,
        damage
    ) 

    region.region_stan_infra_mieszkalnej = _degrade(
        region.region_stan_infra_mieszkalnej,
        damage
    )

    region.region_stan_infra_drogowej = _degrade(
        region.region_stan_infra_drogowej,
        damage
    )

    # 🔵 policz zmiany
    delta_drogi = (region.region_stan_infra_drogowej or 0) - old_drogi
    delta_kolej = (region.region_stan_infra_kolejowej or 0) - old_kolej
    delta_energia = (region.region_stan_infra_energetycznej or 0) - old_energia
    delta_mieszkania = (region.region_stan_infra_mieszkalnej or 0) - old_mieszkania

    log_region_change(
        region=region,
        data_entenda=get_current_entenda_date(),
        source="EVENT",
        delta_ludnosc=delta_ludnosc,
        delta_drogi=delta_drogi,
        delta_kolej=delta_kolej,
        delta_energia=delta_energia,
        delta_mieszkania=delta_mieszkania
    )