# engine/effects.py
import random
from datetime import datetime
from models import (
    RegionalDataChange,
    Panstwo,
    Miasto,
    Region,
    RegionStateHistory,
    MiastoStateHistory,
    Spoleczenstwo,
    SpoleczenstwoStateHistory
)
from extensions import db
from engine.clock import get_current_entenda_date
from sqlalchemy import func

MIN_INFRA = 10

def _snapshot_region_state(region):
    return {
        "drogi": region.region_stan_infra_drogowej,
        "kolej": region.region_stan_infra_kolejowej,
        "energia": region.region_stan_infra_energetycznej,
        "mieszkania": region.region_stan_infra_mieszkalnej,
        "porty": region.region_stan_infra_portowej,
    }

def _get_region_total_population(region):

    miasta_pop = sum(
        (m.miasto_populacja or 0)
        for m in region.miasta
    )

    return (
        (region.region_ludnosc_pozamiejska or 0)
        + miasta_pop
    )

def _with_state_logging(region, source, fn, data_entenda, event_id=None):

    old_values = _snapshot_region_state(region)

    old_population = _get_region_total_population(region)

    try:
        result = fn()
    except Exception:
        raise

    db.session.flush()

    new_values = _snapshot_region_state(region)

    new_population = _get_region_total_population(region)

    log_region_state_change(
        region=region,
        old_values=old_values,
        new_values=new_values,
        source=source,
        data_entenda=data_entenda,
        old_population=old_population,
        new_population=new_population,
        event_id=event_id
    )

    return result

def _degrade(value, damage):
    if value is None:
        return value

    new_val = int(value - damage)
    return max(new_val, MIN_INFRA)

def _regenerate(value, percent):
    if value is None or percent is None:
        return value

    new_val = value + (value * percent / 100)
    return min(int(new_val), 100)

def _delta(a, b):
    return (a or 0) - (b or 0)

def _clamp_social(value):
    if value is None:
        return 0
    return max(0, min(100, int(value)))

def recompute_country_population(panstwo_id):

    # suma populacji miast w państwie
    miasta_pop = (
        db.session.query(
            func.coalesce(func.sum(Miasto.miasto_populacja), 0)
        )
        .join(Region, Miasto.region_id == Region.region_id)
        .filter(Region.panstwo_id == panstwo_id)
        .scalar()
    )

    # suma ludności pozamiejskiej regionów
    rural_pop = (
        db.session.query(
            func.coalesce(func.sum(Region.region_ludnosc_pozamiejska), 0)
        )
        .filter(Region.panstwo_id == panstwo_id)
        .scalar()
    )

    total_population = int(miasta_pop or 0) + int(rural_pop or 0)

    country = Panstwo.query.get(panstwo_id)

    if country:
        country.panstwo_populacja = total_population

def apply_region_regeneration(region):

    data_entenda = get_current_entenda_date()

    def _logic():
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

    # snapshot przed zmianą
    old = _snapshot_region_state(region)

    #poprawka — przekazujemy data_entenda
    _with_state_logging(region, "REGEN", _logic, data_entenda)

    # snapshot po zmianie
    new = _snapshot_region_state(region)

    log_region_change(
        region=region,
        data_entenda=data_entenda,
        source="REGEN",
        delta_drogi=_delta(new["drogi"], old["drogi"]),
        delta_kolej=_delta(new["kolej"], old["kolej"]),
        delta_energia=_delta(new["energia"], old["energia"]),
        delta_mieszkania=_delta(new["mieszkania"], old["mieszkania"]),
        delta_porty=_delta(new["porty"], old["porty"]),
    )

def _apply_population_loss(region, victims, event=None):

    if not victims or victims <= 0:
        return

    # =====================================================
    # ZDARZENIA MIEJSKIE
    # =====================================================

    CITY_EVENTS = {
        "fala_upalu",
        "pozar_budynku",
        "katastrofa_w_ruchu_ladowym",
        "atak_terrorystyczny"
    }

    if (
        event
        and event.zdarzenie_typ
        and event.zdarzenie_typ in CITY_EVENTS
        and event.miasto_id
    ):

        miasto = Miasto.query.get(event.miasto_id)

        if miasto and miasto.miasto_populacja is not None:

            old_pop = miasto.miasto_populacja

            new_pop = max(
                old_pop - victims,
                0
            )

            miasto.miasto_populacja = new_pop

            snapshot = MiastoStateHistory(

                miasto_id=miasto.miasto_id,

                data_entenda=get_current_entenda_date(),

                data_rzeczywista=datetime.now(),

                source="EVENT",

                event_id=event.zdarzenie_id if event else None,

                old_miasto_populacja=old_pop,

                new_miasto_populacja=new_pop,

                change_delta=(new_pop - old_pop)
            )

            db.session.add(snapshot)

            recompute_country_population(region.panstwo_id)

            return

    # =====================================================
    # DOMYŚLNIE — LUDNOŚĆ POZAMIEJSKA
    # =====================================================

    if region.region_ludnosc_pozamiejska is None:
        return

    region.region_ludnosc_pozamiejska = max(
        region.region_ludnosc_pozamiejska - victims,
        0
    )

    recompute_country_population(region.panstwo_id)

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
        data_rzeczywista=datetime.now(),
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

def log_region_state_change(
    region,
    old_values: dict,
    new_values: dict,
    source,
    data_entenda,
    old_population=None,
    new_population=None,
    event_id=None
):


    # sprawdzamy czy cokolwiek się realnie zmieniło
    infra_changed = any(
        (old_values[key] or 0) != (new_values[key] or 0)
        for key in old_values
    )

    population_changed = (
        (old_population or 0) != (new_population or 0)
    )

    if not infra_changed and not population_changed:
        return

    entry = RegionStateHistory(
        region_id=region.region_id,
        event_id=event_id,
        data_entenda=data_entenda,
        data_rzeczywista=datetime.now(),
        source=source,

        old_ludnosc=old_population,
        new_ludnosc=new_population,

        # DROGI
        old_drogi=old_values["drogi"],
        new_drogi=new_values["drogi"],

        # KOLEJ
        old_kolej=old_values["kolej"],
        new_kolej=new_values["kolej"],

        # ENERGIA
        old_energia=old_values["energia"],
        new_energia=new_values["energia"],

        # MIESZKANIA
        old_mieszkania=old_values["mieszkania"],
        new_mieszkania=new_values["mieszkania"],

        # PORTY
        old_porty=old_values["porty"],
        new_porty=new_values["porty"],
    )

    db.session.add(entry)

# =====================================================
# ZMIANY W STABILNOŚCI SPOŁECZNEJ
# =====================================================

def apply_social_stability_penalty(
    region,
    scale,
    data_entenda,
    event_id=None
):

    penalty_map = {
        4: -1,
        5: -2
    }

    delta = penalty_map.get(scale)

    if not delta:
        return

    sp = Spoleczenstwo.query.filter_by(
        panstwo_id=region.panstwo_id
    ).first()

    if not sp:
        return

    old_stabilnosc = sp.stabilnosc_spoleczna

    sp.stabilnosc_spoleczna = _clamp_social(
        (sp.stabilnosc_spoleczna or 0) + delta
    )

    db.session.add(
        SpoleczenstwoStateHistory(
            panstwo_id=region.panstwo_id,
            data_entenda=data_entenda,
            data_rzeczywista=datetime.now(),
            source="EVENT",
            event_id=event_id,

            old_stabilnosc=old_stabilnosc,
            new_stabilnosc=sp.stabilnosc_spoleczna
        )
    )

# =====================================================
# TRZĘSIENIE ZIEMI
# =====================================================

def apply_earthquake_effect(region, scale, victims, data_entenda, event=None, event_id=None):

    old_state = _snapshot_region_state(region)
    old_pop = _get_region_total_population(region)

    def _logic():
        _apply_population_loss(region, victims, event)

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
            scale * random.randint(1, 3)
        )

    _with_state_logging(region, "EVENT", _logic, data_entenda, event_id=event_id)

    apply_social_stability_penalty(
        region=region,
        scale=scale,
        data_entenda=data_entenda,
        event_id=event_id
    )

    new_state = _snapshot_region_state(region)
    new_pop = _get_region_total_population(region)

    log_region_change(
        region=region,
        data_entenda=data_entenda,
        source="EVENT",
        delta_ludnosc=new_pop - old_pop,
        delta_drogi=_delta(new_state["drogi"], old_state["drogi"]),
        delta_kolej=_delta(new_state["kolej"], old_state["kolej"]),
        delta_energia=_delta(new_state["energia"], old_state["energia"]),
        delta_mieszkania=_delta(new_state["mieszkania"], old_state["mieszkania"]),
        event_id=event_id,
    )

# =====================================================
# KATASTROFA KOLEJOWA
# =====================================================

def apply_train_disaster_effect(region, scale, victims, data_entenda, event=None, event_id=None):

    old_state = _snapshot_region_state(region)
    old_pop = _get_region_total_population(region)

    def _logic():
        _apply_population_loss(region, victims, event)

        damage = int(scale * random.uniform(0.5, 1))

        region.region_stan_infra_kolejowej = _degrade(
            region.region_stan_infra_kolejowej,
            damage
        )

    _with_state_logging(region, "EVENT", _logic, data_entenda, event_id=event_id)

    new_state = _snapshot_region_state(region)
    new_pop = _get_region_total_population(region)

    log_region_change(
        region=region,
        data_entenda=data_entenda,
        source="EVENT",
        delta_ludnosc=new_pop - old_pop,
        delta_drogi=_delta(new_state["drogi"], old_state["drogi"]),
        delta_kolej=_delta(new_state["kolej"], old_state["kolej"]),
        delta_energia=_delta(new_state["energia"], old_state["energia"]),
        delta_mieszkania=_delta(new_state["mieszkania"], old_state["mieszkania"]),
        event_id=event_id,
    )


# =====================================================
# KATASTROFA DROGOWA
# =====================================================

def apply_road_disaster_effect(region, scale, victims, data_entenda, event=None, event_id=None):

    old_state = _snapshot_region_state(region)
    old_pop = _get_region_total_population(region)

    def _logic():
        _apply_population_loss(region, victims, event)

        damage = int(scale * random.uniform(0.5, 1))

        region.region_stan_infra_drogowej = _degrade(
            region.region_stan_infra_drogowej,
            damage
        )

    _with_state_logging(region, "EVENT", _logic, data_entenda, event_id=event_id)

    apply_social_stability_penalty(
        region=region,
        scale=scale,
        data_entenda=data_entenda,
        event_id=event_id
    )

    new_state = _snapshot_region_state(region)
    new_pop = _get_region_total_population(region)

    log_region_change(
        region=region,
        data_entenda=data_entenda,
        source="EVENT",
        delta_ludnosc=new_pop - old_pop,
        delta_drogi=_delta(new_state["drogi"], old_state["drogi"]),
        delta_kolej=_delta(new_state["kolej"], old_state["kolej"]),
        delta_energia=_delta(new_state["energia"], old_state["energia"]),
        delta_mieszkania=_delta(new_state["mieszkania"], old_state["mieszkania"]),
        event_id=event_id,
    )
    
# =====================================================
# POWÓDŹ
# =====================================================
    
def apply_flood_effect(region, scale, victims, data_entenda, event=None, event_id=None):

    old_state = _snapshot_region_state(region)
    old_pop = _get_region_total_population(region)

    def _logic():
        _apply_population_loss(region, victims, event)

        damage = int(scale * random.uniform(1.0, 1.8))

        region.region_stan_infra_drogowej = _degrade(region.region_stan_infra_drogowej, damage)
        region.region_stan_infra_kolejowej = _degrade(region.region_stan_infra_kolejowej, damage)
        region.region_stan_infra_mieszkalnej = _degrade(region.region_stan_infra_mieszkalnej, damage)

    _with_state_logging(region, "EVENT", _logic, data_entenda, event_id=event_id)

    apply_social_stability_penalty(
        region=region,
        scale=scale,
        data_entenda=data_entenda,
        event_id=event_id
    )

    new_state = _snapshot_region_state(region)
    new_pop = _get_region_total_population(region)

    log_region_change(
        region=region,
        data_entenda=data_entenda,
        source="EVENT",
        delta_ludnosc=new_pop - old_pop,
        delta_drogi=_delta(new_state["drogi"], old_state["drogi"]),
        delta_kolej=_delta(new_state["kolej"], old_state["kolej"]),
        delta_energia=_delta(new_state["energia"], old_state["energia"]),
        delta_mieszkania=_delta(new_state["mieszkania"], old_state["mieszkania"]),
        event_id=event_id,
    )

# =====================================================
# LAWINA
# =====================================================

def apply_avalanche_effect(region, scale, victims, data_entenda, event=None, event_id=None):

    old_state = _snapshot_region_state(region)
    old_pop = _get_region_total_population(region)

    def _logic():
        _apply_population_loss(region, victims, event)

        damage = int(scale * random.uniform(0.4, 0.7))

        region.region_stan_infra_mieszkalnej = _degrade(
            region.region_stan_infra_mieszkalnej,
            damage
        )

    _with_state_logging(region, "EVENT", _logic, data_entenda, event_id=event_id)

    new_state = _snapshot_region_state(region)
    new_pop = _get_region_total_population(region)

    log_region_change(
        region=region,
        data_entenda=data_entenda,
        source="EVENT",
        delta_ludnosc=new_pop - old_pop,
        delta_drogi=_delta(new_state["drogi"], old_state["drogi"]),
        delta_kolej=_delta(new_state["kolej"], old_state["kolej"]),
        delta_energia=_delta(new_state["energia"], old_state["energia"]),
        delta_mieszkania=_delta(new_state["mieszkania"], old_state["mieszkania"]),
        event_id=event_id,
    )

# =====================================================
# ERUPCJA WULKANU
# =====================================================

def apply_volcano_effect(region, scale, victims, data_entenda, event=None, event_id=None):

    old_state = _snapshot_region_state(region)
    old_pop = _get_region_total_population(region)

    def _logic():
        _apply_population_loss(region, victims, event)

        damage = int(scale * random.uniform(0.5, 1))

        region.region_stan_infra_drogowej = _degrade(region.region_stan_infra_drogowej, damage)
        region.region_stan_infra_kolejowej = _degrade(region.region_stan_infra_kolejowej, damage)
        region.region_stan_infra_mieszkalnej = _degrade(region.region_stan_infra_mieszkalnej, damage)

    _with_state_logging(region, "EVENT", _logic, data_entenda, event_id=event_id)

    new_state = _snapshot_region_state(region)
    new_pop = _get_region_total_population(region)

    log_region_change(
        region=region,
        data_entenda=data_entenda,
        source="EVENT",
        delta_ludnosc=new_pop - old_pop,
        delta_drogi=_delta(new_state["drogi"], old_state["drogi"]),
        delta_kolej=_delta(new_state["kolej"], old_state["kolej"]),
        delta_energia=_delta(new_state["energia"], old_state["energia"]),
        delta_mieszkania=_delta(new_state["mieszkania"], old_state["mieszkania"]),
        event_id=event_id,
    )

# =====================================================
# FALA MROZU
# =====================================================

def apply_coldwave_effect(region, scale, victims, data_entenda, event=None, event_id=None):

    old_state = _snapshot_region_state(region)
    old_pop = _get_region_total_population(region)

    def _logic():
        _apply_population_loss(region, victims, event)

        damage = int(scale * random.uniform(0.6, 0.9))

        region.region_stan_infra_drogowej = _degrade(region.region_stan_infra_drogowej, damage)
        region.region_stan_infra_energetycznej = _degrade(region.region_stan_infra_energetycznej, damage)
        region.region_stan_infra_mieszkalnej = _degrade(region.region_stan_infra_mieszkalnej, damage)

    _with_state_logging(region, "EVENT", _logic, data_entenda, event_id=event_id)

    new_state = _snapshot_region_state(region)
    new_pop = _get_region_total_population(region)

    log_region_change(
        region=region,
        data_entenda=data_entenda,
        source="EVENT",
        delta_ludnosc=new_pop - old_pop,
        delta_drogi=_delta(new_state["drogi"], old_state["drogi"]),
        delta_kolej=_delta(new_state["kolej"], old_state["kolej"]),
        delta_energia=_delta(new_state["energia"], old_state["energia"]),
        delta_mieszkania=_delta(new_state["mieszkania"], old_state["mieszkania"]),
        event_id=event_id,
    )

# =====================================================
# FALA UPAŁU
# =====================================================

def apply_heatwave_effect(region, scale, victims, data_entenda, event=None, event_id=None):

    old_state = _snapshot_region_state(region)
    old_pop = _get_region_total_population(region)

    def _logic():
        _apply_population_loss(region, victims, event)

        damage = int(scale * random.uniform(0.4, 0.8))

        region.region_stan_infra_energetycznej = _degrade(region.region_stan_infra_energetycznej, damage)
        region.region_stan_infra_mieszkalnej = _degrade(region.region_stan_infra_mieszkalnej, damage)
        region.region_stan_infra_drogowej = _degrade(region.region_stan_infra_drogowej, damage)

    _with_state_logging(region, "EVENT", _logic, data_entenda, event_id=event_id)

    new_state = _snapshot_region_state(region)
    new_pop = _get_region_total_population(region)

    log_region_change(
        region=region,
        data_entenda=data_entenda,
        source="EVENT",
        delta_ludnosc=new_pop - old_pop,
        delta_drogi=_delta(new_state["drogi"], old_state["drogi"]),
        delta_kolej=_delta(new_state["kolej"], old_state["kolej"]),
        delta_energia=_delta(new_state["energia"], old_state["energia"]),
        delta_mieszkania=_delta(new_state["mieszkania"], old_state["mieszkania"]),
        event_id=event_id,
    )

# =====================================================
# POŻAR BUDYNKU
# =====================================================


def apply_building_fire_effect(region, scale, victims, data_entenda, event=None, event_id=None):

    old_state = _snapshot_region_state(region)
    old_pop = _get_region_total_population(region)

    def _logic():
        _apply_population_loss(region, victims, event)

        damage_map = {
            1: 0.0,
            2: 0.002,
            3: 0.003,
            4: 0.004,
            5: 0.005
        }

        max_damage_pct = damage_map.get(scale, 0)
        damage_pct = max_damage_pct * random.uniform(0.5, 1.0)

        damage_value = (region.region_stan_infra_mieszkalnej or 0) * damage_pct

        region.region_stan_infra_mieszkalnej = _degrade(
            region.region_stan_infra_mieszkalnej,
            damage_value
        )

    _with_state_logging(region, "EVENT", _logic, data_entenda, event_id=event_id)

    new_state = _snapshot_region_state(region)
    new_pop = _get_region_total_population(region)

    log_region_change(
        region=region,
        data_entenda=data_entenda,
        source="EVENT",
        delta_ludnosc=new_pop - old_pop,
        delta_drogi=0,
        delta_kolej=0,
        delta_energia=0,
        delta_mieszkania=new_state["mieszkania"] - old_state["mieszkania"],
        event_id=event_id,
    )

# =====================================================
# PRZERWA W DOSTAWIE PRĄDU
# =====================================================

def apply_power_outage_effect(region, scale, victims, data_entenda, event=None, event_id=None):

    old_pop = _get_region_total_population(region)

    def _logic():
        _apply_population_loss(region, victims, event)

    _with_state_logging(region, "EVENT", _logic, data_entenda, event_id=event_id)

    apply_social_stability_penalty(
        region=region,
        scale=scale,
        data_entenda=data_entenda,
        event_id=event_id
    )

    new_pop = _get_region_total_population(region)

    log_region_change(
        region=region,
        data_entenda=data_entenda,
        source="EVENT",
        delta_ludnosc=new_pop - old_pop,
        delta_drogi=0,
        delta_kolej=0,
        delta_energia=0,
        delta_mieszkania=0,
        event_id=event_id,
    )

# =====================================================
# KATASTROFA LOTNICZA
# =====================================================

def apply_air_disaster_effect(region, scale, victims, data_entenda, event=None, event_id=None):

    old_pop = _get_region_total_population(region)

    def _logic():
        _apply_population_loss(region, victims, event)

    _with_state_logging(region, "EVENT", _logic, data_entenda, event_id=event_id)

    new_pop = _get_region_total_population(region)

    log_region_change(
        region=region,
        data_entenda=data_entenda,
        source="EVENT",
        delta_ludnosc=new_pop - old_pop,
        delta_drogi=0,
        delta_kolej=0,
        delta_energia=0,
        delta_mieszkania=0,
        event_id=event_id,
    )

# =====================================================
# ZAMIESZKI
# =====================================================

def apply_social_riot_effect(
    region,
    scale,
    victims,
    data_entenda,
    event=None,
    event_id=None
):

    old_pop = _get_region_total_population(region)

    sp = Spoleczenstwo.query.filter_by(
        panstwo_id=region.panstwo_id
    ).first()

    if not sp:
        return

    snapshot = {
        "old_przestepczosc": sp.przestepczosc,
        "old_radykalizacja": sp.radykalizacja_spoleczna,
        "old_spojnosc": sp.spojnosc_spoleczna,
        "old_zadowolenie": sp.zadowolenie_spoleczne
    }

    def _logic():
        _apply_population_loss(region, victims, event)

        if scale == 1:
            return

        elif scale == 2:
            return

        elif scale == 3:
            sp.przestepczosc = _clamp_social((sp.przestepczosc or 0) + 1)
            sp.radykalizacja_spoleczna = _clamp_social((sp.radykalizacja_spoleczna or 0) + 1)
            sp.spojnosc_spoleczna = _clamp_social((sp.spojnosc_spoleczna or 0) - 1)
            sp.zadowolenie_spoleczne = _clamp_social((sp.zadowolenie_spoleczne or 0) - 1)

        elif scale == 4:
            sp.przestepczosc = _clamp_social((sp.przestepczosc or 0) + 1)
            sp.radykalizacja_spoleczna = _clamp_social((sp.radykalizacja_spoleczna or 0) + 2)
            sp.spojnosc_spoleczna = _clamp_social((sp.spojnosc_spoleczna or 0) - 2)
            sp.zadowolenie_spoleczne = _clamp_social((sp.zadowolenie_spoleczne or 0) - 1)

        elif scale == 5:
            sp.przestepczosc = _clamp_social((sp.przestepczosc or 0) + 2)
            sp.radykalizacja_spoleczna = _clamp_social((sp.radykalizacja_spoleczna or 0) + 2)
            sp.spojnosc_spoleczna = _clamp_social((sp.spojnosc_spoleczna or 0) - 2)
            sp.zadowolenie_spoleczne = _clamp_social((sp.zadowolenie_spoleczne or 0) - 2)

    _with_state_logging(
        region,
        "EVENT",
        _logic,
        data_entenda,
        event_id=event_id
    )

    db.session.add(
        SpoleczenstwoStateHistory(
            panstwo_id=region.panstwo_id,
            data_entenda=data_entenda,
            data_rzeczywista=datetime.now(),
            source="EVENT",
            event_id=event_id,

            old_przestepczosc=snapshot["old_przestepczosc"],
            new_przestepczosc=sp.przestepczosc,

            old_radykalizacja=snapshot["old_radykalizacja"],
            new_radykalizacja=sp.radykalizacja_spoleczna,

            old_spojnosc=snapshot["old_spojnosc"],
            new_spojnosc=sp.spojnosc_spoleczna,

            old_zadowolenie=snapshot["old_zadowolenie"],
            new_zadowolenie=sp.zadowolenie_spoleczne
        )
    )

    new_pop = _get_region_total_population(region)

    log_region_change(
        region=region,
        data_entenda=data_entenda,
        source="EVENT",
        delta_ludnosc=new_pop - old_pop,
        event_id=event_id
    )

# =====================================================
# ATAK TERRORYSTYCZNY
# =====================================================

def apply_terror_attack_effect(
    region,
    scale,
    victims,
    data_entenda,
    event=None,
    event_id=None
):

    old_pop = _get_region_total_population(region)

    sp = Spoleczenstwo.query.filter_by(
        panstwo_id=region.panstwo_id
    ).first()

    if not sp:
        return

    snapshot = {
        "old_stabilnosc": sp.stabilnosc_spoleczna,
        "old_spojnosc": sp.spojnosc_spoleczna,
        "old_radykalizacja": sp.radykalizacja_spoleczna,
        "old_otwartosc": sp.otwartosc_spoleczna
    }

    def _logic():
        _apply_population_loss(region, victims, event)

        if scale == 1:
            sp.radykalizacja_spoleczna = _clamp_social(
                (sp.radykalizacja_spoleczna or 0) + 1
            )
            sp.otwartosc_spoleczna = _clamp_social(
                (sp.otwartosc_spoleczna or 0) - 1
            )

        elif scale == 2:
            sp.stabilnosc_spoleczna = _clamp_social(
                (sp.stabilnosc_spoleczna or 0) - 1
            )
            sp.spojnosc_spoleczna = _clamp_social(
                (sp.spojnosc_spoleczna or 0) - 1
            )
            sp.radykalizacja_spoleczna = _clamp_social(
                (sp.radykalizacja_spoleczna or 0) + 1
            )
            sp.otwartosc_spoleczna = _clamp_social(
                (sp.otwartosc_spoleczna or 0) - 1
            )

        elif scale == 3:
            sp.stabilnosc_spoleczna = _clamp_social(
                (sp.stabilnosc_spoleczna or 0) - 2
            )
            sp.spojnosc_spoleczna = _clamp_social(
                (sp.spojnosc_spoleczna or 0) - 1
            )
            sp.radykalizacja_spoleczna = _clamp_social(
                (sp.radykalizacja_spoleczna or 0) + 2
            )
            sp.otwartosc_spoleczna = _clamp_social(
                (sp.otwartosc_spoleczna or 0) - 2
            )

        elif scale == 4:
            sp.stabilnosc_spoleczna = _clamp_social(
                (sp.stabilnosc_spoleczna or 0) - 3
            )
            sp.spojnosc_spoleczna = _clamp_social(
                (sp.spojnosc_spoleczna or 0) - 2
            )
            sp.radykalizacja_spoleczna = _clamp_social(
                (sp.radykalizacja_spoleczna or 0) + 2
            )
            sp.otwartosc_spoleczna = _clamp_social(
                (sp.otwartosc_spoleczna or 0) - 2
            )

        elif scale == 5:
            sp.stabilnosc_spoleczna = _clamp_social(
                (sp.stabilnosc_spoleczna or 0) - 4
            )
            sp.spojnosc_spoleczna = _clamp_social(
                (sp.spojnosc_spoleczna or 0) - 3
            )
            sp.radykalizacja_spoleczna = _clamp_social(
                (sp.radykalizacja_spoleczna or 0) + 3
            )
            sp.otwartosc_spoleczna = _clamp_social(
                (sp.otwartosc_spoleczna or 0) - 3
            )

    _with_state_logging(
        region,
        "EVENT",
        _logic,
        data_entenda,
        event_id=event_id
    )

    db.session.add(
        SpoleczenstwoStateHistory(
            panstwo_id=region.panstwo_id,
            data_entenda=data_entenda,
            data_rzeczywista=datetime.now(),
            source="EVENT",
            event_id=event_id,

            old_stabilnosc=snapshot["old_stabilnosc"],
            new_stabilnosc=sp.stabilnosc_spoleczna,

            old_spojnosc=snapshot["old_spojnosc"],
            new_spojnosc=sp.spojnosc_spoleczna,

            old_radykalizacja=snapshot["old_radykalizacja"],
            new_radykalizacja=sp.radykalizacja_spoleczna,

            old_otwartosc=snapshot["old_otwartosc"],
            new_otwartosc=sp.otwartosc_spoleczna
        )
    )

    new_pop = _get_region_total_population(region)

    log_region_change(
        region=region,
        data_entenda=data_entenda,
        source="EVENT",
        delta_ludnosc=new_pop - old_pop,
        event_id=event_id
    )

# =====================================================
# PROTEST SPOŁECZNY
# =====================================================

def apply_social_protest_effect(
    region,
    scale,
    victims,
    data_entenda,
    event=None,
    event_id=None
):

    sp = Spoleczenstwo.query.filter_by(
        panstwo_id=region.panstwo_id
    ).first()

    if not sp:
        return

    snapshot = {
        "old_swiadomosc": sp.swiadomosc_spoleczna,
        "old_spojnosc": sp.spojnosc_spoleczna,
        "old_zadowolenie": sp.zadowolenie_spoleczne
    }

    def _logic():

        if scale == 1:
            return

        elif scale == 2:
            sp.swiadomosc_spoleczna = _clamp_social(
                (sp.swiadomosc_spoleczna or 0) + 1
            )
            sp.spojnosc_spoleczna = _clamp_social(
                (sp.spojnosc_spoleczna or 0) + 1
            )

        elif scale == 3:
            sp.swiadomosc_spoleczna = _clamp_social(
                (sp.swiadomosc_spoleczna or 0) + 1
            )
            sp.spojnosc_spoleczna = _clamp_social(
                (sp.spojnosc_spoleczna or 0) + 1
            )

        elif scale == 4:
            sp.swiadomosc_spoleczna = _clamp_social(
                (sp.swiadomosc_spoleczna or 0) + 2
            )
            sp.spojnosc_spoleczna = _clamp_social(
                (sp.spojnosc_spoleczna or 0) + 2
            )
            sp.zadowolenie_spoleczne = _clamp_social(
                (sp.zadowolenie_spoleczne or 0) - 1
            )

        elif scale == 5:
            sp.swiadomosc_spoleczna = _clamp_social(
                (sp.swiadomosc_spoleczna or 0) + 2
            )
            sp.spojnosc_spoleczna = _clamp_social(
                (sp.spojnosc_spoleczna or 0) + 2
            )
            sp.zadowolenie_spoleczne = _clamp_social(
                (sp.zadowolenie_spoleczne or 0) - 1
            )

    _logic()

    db.session.add(
        SpoleczenstwoStateHistory(
            panstwo_id=region.panstwo_id,
            data_entenda=data_entenda,
            data_rzeczywista=datetime.now(),
            source="EVENT",
            event_id=event_id,

            old_swiadomosc=snapshot["old_swiadomosc"],
            new_swiadomosc=sp.swiadomosc_spoleczna,

            old_spojnosc=snapshot["old_spojnosc"],
            new_spojnosc=sp.spojnosc_spoleczna,

            old_zadowolenie=snapshot["old_zadowolenie"],
            new_zadowolenie=sp.zadowolenie_spoleczne
        )
    )

def _clamp_regiony(value):
    return max(0, min(100, value))


def _clamp_social(value):
    return max(0, min(100, value))

def apply_law_effect(
    region,
    scale,
    victims,
    data_entenda,
    event=None,
    event_id=None
):

    if not event:
        return

    sp = Spoleczenstwo.query.filter_by(
        panstwo_id=region.panstwo_id
    ).first()

    if not sp:
        return

    snapshot = {
        "old_stabilnosc": sp.stabilnosc_spoleczna,
        "old_zadowolenie": sp.zadowolenie_spoleczne,
        "old_nierownosci": sp.nierownosci_spoleczne,
        "old_edukacja": sp.poziom_edukacji,
        "old_swiadomosc": sp.swiadomosc_spoleczna,
        "old_zaufanie": sp.zaufanie_do_wladzy,
        "old_napiecia_religijne": sp.napiecia_religijne,
        "old_napiecia_etniczne": sp.napiecia_etniczne,
        "old_napiecia_klasowe": sp.napiecia_klasowe,
        "old_przestepczosc": sp.przestepczosc,
        "old_radykalizacja": sp.radykalizacja_spoleczna,
        "old_spojnosc": sp.spojnosc_spoleczna,
        "old_tozsamosc": sp.tozsamosc_narodowa,
        "old_konserwatyzm": sp.konserwatyzm_spoleczny,
        "old_otwartosc": sp.otwartosc_spoleczna,
        "old_alkohol": sp.spozycie_alkoholu,
        "old_narkotyki": sp.spozycie_narkotykow,
        "old_zdrowie": sp.zdrowie_publiczne
    }

    if event.wariant == "NU006":

        sp.nierownosci_spoleczne = _clamp_social(
            (sp.nierownosci_spoleczne or 0)
            + random.randint(1, 4)
        )

    elif event.wariant == "NU018":

        sp.przestepczosc = _clamp_social(
            (sp.przestepczosc or 0)
            - random.randint(2, 10)
        )

        sp.spozycie_alkoholu = _clamp_social(
            (sp.spozycie_alkoholu or 0)
            - random.randint(2, 10)
        )

    regiony = Region.query.filter_by(
        panstwo_id=event.panstwo_id
    ).all()

    for r in regiony:

        if event.wariant == "NU026":

            old_degradacja = r.region_degradacja_srodowiska or 0
            old_powietrze = r.region_zanieczyszczenie_powietrza or 0

            r.region_degradacja_srodowiska = _clamp_regiony(
                old_degradacja - random.randint(2, 7)
            )

            r.region_zanieczyszczenie_powietrza = _clamp_regiony(
                old_powietrze - random.randint(1, 4)
            )

            db.session.add(
                RegionStateHistory(
                    region_id=r.region_id,
                    data_entenda=event.data_entenda,
                    data_rzeczywista=datetime.now(),
                    source="EVENT",
                    event_id=event.zdarzenie_id,
                    old_degradacja_srodowiska=old_degradacja,
                    new_degradacja_srodowiska=r.region_degradacja_srodowiska,
                    old_zanieczyszczenie_powietrza=old_powietrze,
                    new_zanieczyszczenie_powietrza=r.region_zanieczyszczenie_powietrza
                )
            )

        elif event.wariant == "NU007":

            old_degradacja = r.region_degradacja_srodowiska or 0

            r.region_degradacja_srodowiska = _clamp_regiony(
                old_degradacja - random.randint(1, 8)
            )

            db.session.add(
                RegionStateHistory(
                    region_id=r.region_id,
                    data_entenda=event.data_entenda,
                    data_rzeczywista=datetime.now(),
                    source="EVENT",
                    event_id=event.zdarzenie_id,
                    old_degradacja_srodowiska=old_degradacja,
                    new_degradacja_srodowiska=r.region_degradacja_srodowiska
                )
            )
        
        elif event.wariant == "NU008":

            old_degradacja = r.region_degradacja_srodowiska or 0

            r.region_degradacja_srodowiska = _clamp_regiony(
                old_degradacja + random.randint(1, 3)
            )

            db.session.add(
                RegionStateHistory(
                    region_id=r.region_id,
                    data_entenda=event.data_entenda,
                    data_rzeczywista=datetime.now(),
                    source="EVENT",
                    event_id=event.zdarzenie_id,
                    old_degradacja_srodowiska=old_degradacja,
                    new_degradacja_srodowiska=r.region_degradacja_srodowiska
                )
            )
        
        elif event.wariant == "NU009":

            old_degradacja = r.region_degradacja_srodowiska or 0

            r.region_degradacja_srodowiska = _clamp_regiony(
                old_degradacja - random.randint(1, 3)
            )

            db.session.add(
                RegionStateHistory(
                    region_id=r.region_id,
                    data_entenda=event.data_entenda,
                    data_rzeczywista=datetime.now(),
                    source="EVENT",
                    event_id=event.zdarzenie_id,
                    old_degradacja_srodowiska=old_degradacja,
                    new_degradacja_srodowiska=r.region_degradacja_srodowiska
                )
            )
        
        elif event.wariant == "NU010":

            old_degradacja = r.region_degradacja_srodowiska or 0

            r.region_degradacja_srodowiska = _clamp_regiony(
                old_degradacja - random.randint(1, 3)
            )

            db.session.add(
                RegionStateHistory(
                    region_id=r.region_id,
                    data_entenda=event.data_entenda,
                    data_rzeczywista=datetime.now(),
                    source="EVENT",
                    event_id=event.zdarzenie_id,
                    old_degradacja_srodowiska=old_degradacja,
                    new_degradacja_srodowiska=r.region_degradacja_srodowiska
                )
            )
        
        elif event.wariant == "NU011":

            old_degradacja = r.region_degradacja_srodowiska or 0

            r.region_degradacja_srodowiska = _clamp_regiony(
                old_degradacja - 1
            )

            db.session.add(
                RegionStateHistory(
                    region_id=r.region_id,
                    data_entenda=event.data_entenda,
                    data_rzeczywista=datetime.now(),
                    source="EVENT",
                    event_id=event.zdarzenie_id,
                    old_degradacja_srodowiska=old_degradacja,
                    new_degradacja_srodowiska=r.region_degradacja_srodowiska
                )
            )

        elif event.wariant == "NU020":

            old = r.region_stan_infra_kolejowej or 0

            r.region_stan_infra_kolejowej = _clamp_regiony(
                old + random.randint(1, 15)
            )

            db.session.add(
                RegionStateHistory(
                    region_id=r.region_id,
                    data_entenda=event.data_entenda,
                    data_rzeczywista=datetime.now(),
                    source="EVENT",
                    event_id=event.zdarzenie_id,
                    old_kolej=old,
                    new_kolej=r.region_stan_infra_kolejowej
                )
            )

        elif event.wariant == "NU021":

            old = r.region_stan_infra_drogowej or 0

            r.region_stan_infra_drogowej = _clamp_regiony(
                old + random.randint(1, 8)
            )

            db.session.add(
                RegionStateHistory(
                    region_id=r.region_id,
                    data_entenda=event.data_entenda,
                    data_rzeczywista=datetime.now(),
                    source="EVENT",
                    event_id=event.zdarzenie_id,
                    old_drogi=old,
                    new_drogi=r.region_stan_infra_drogowej
                )
            )

        elif event.wariant == "NU022":

            old = r.region_stan_infra_energetycznej or 0

            r.region_stan_infra_energetycznej = _clamp_regiony(
                old + random.randint(1, 8)
            )

            db.session.add(
                RegionStateHistory(
                    region_id=r.region_id,
                    data_entenda=event.data_entenda,
                    data_rzeczywista=datetime.now(),
                    source="EVENT",
                    event_id=event.zdarzenie_id,
                    old_energia=old,
                    new_energia=r.region_stan_infra_energetycznej
                )
            )

        elif event.wariant == "NU023":

            if r.region_polozenie_id != 1 and r.region_stan_infra_portowej is not None:

                old = r.region_stan_infra_portowej or 0

                r.region_stan_infra_portowej = _clamp_regiony(
                    old + random.randint(1, 8)
                )

                db.session.add(
                    RegionStateHistory(
                        region_id=r.region_id,
                        data_entenda=event.data_entenda,
                        data_rzeczywista=datetime.now(),
                        source="EVENT",
                        event_id=event.zdarzenie_id,
                        old_porty=old,
                        new_porty=r.region_stan_infra_portowej
                    )
                )

        elif event.wariant == "NU024":

            old = r.region_stan_infra_mieszkalnej or 0

            r.region_stan_infra_mieszkalnej = _clamp_regiony(
                old + random.randint(1, 8)
            )

            db.session.add(
                RegionStateHistory(
                    region_id=r.region_id,
                    data_entenda=event.data_entenda,
                    data_rzeczywista=datetime.now(),
                    source="EVENT",
                    event_id=event.zdarzenie_id,
                    old_mieszkania=old,
                    new_mieszkania=r.region_stan_infra_mieszkalnej
                )
            )
        
    if event.wariant in ("NU006", "NU018"):

        db.session.add(
            SpoleczenstwoStateHistory(
                panstwo_id=region.panstwo_id,
                data_entenda=data_entenda,
                data_rzeczywista=datetime.now(),
                source="EVENT",
                event_id=event.zdarzenie_id,

                old_nierownosci=snapshot["old_nierownosci"],
                new_nierownosci=sp.nierownosci_spoleczne,

                old_przestepczosc=snapshot["old_przestepczosc"],
                new_przestepczosc=sp.przestepczosc,

                old_spozycie_alkoholu=snapshot["old_alkohol"],
                new_spozycie_alkoholu=sp.spozycie_alkoholu,
            )
        )
    
# =====================================================
# WYSOKIE ZANIECZYSZCZENIE POWIETRZA
# =====================================================

def apply_high_air_pollution_effect(
    region,
    scale,
    victims,
    data_entenda,
    event=None,
    event_id=None
):

    sp = Spoleczenstwo.query.filter_by(
        panstwo_id=region.panstwo_id
    ).first()

    if not sp:
        return

    old_health = sp.zdrowie_publiczne

    if scale == 1:
        delta = 0

    elif scale == 2:
        delta = 0

    elif scale == 3:
        delta = -1

    elif scale == 4:
        delta = -2

    else:
        delta = -3

    sp.zdrowie_publiczne = _clamp_social(
        (sp.zdrowie_publiczne or 0) + delta
    )

    db.session.add(
        SpoleczenstwoStateHistory(
            panstwo_id=region.panstwo_id,
            data_entenda=data_entenda,
            data_rzeczywista=datetime.now(),
            source="EVENT",
            event_id=event_id,

            old_zdrowie_publiczne=old_health,
            new_zdrowie_publiczne=sp.zdrowie_publiczne
        )
    )

# =====================================================
# MARSZ PATRIOTYCZNY
# =====================================================

def apply_patriotic_march_effect(
    region,
    scale,
    victims,
    data_entenda,
    event=None,
    event_id=None
):

    sp = Spoleczenstwo.query.filter_by(
        panstwo_id=region.panstwo_id
    ).first()

    if not sp:
        return

    old_identity = sp.tozsamosc_narodowa
    old_stability = sp.stabilnosc_spoleczna

    if scale == 1:
        delta_identity = 1
        delta_stability = 1

    elif scale == 2:
        delta_identity = 1
        delta_stability = 1

    elif scale == 3:
        delta_identity = 1
        delta_stability = 1

    elif scale == 4:
        delta_identity = 1
        delta_stability = 2

    else:
        delta_identity = 1
        delta_stability = 2

    sp.tozsamosc_narodowa = _clamp_social(
        (sp.tozsamosc_narodowa or 0) + delta_identity
    )

    sp.stabilnosc_spoleczna = _clamp_social(
        (sp.stabilnosc_spoleczna or 0) + delta_stability
    )

    db.session.add(
        SpoleczenstwoStateHistory(
            panstwo_id=region.panstwo_id,
            data_entenda=data_entenda,
            data_rzeczywista=datetime.now(),
            source="EVENT",
            event_id=event_id,

            old_tozsamosc=old_identity,
            new_tozsamosc=sp.tozsamosc_narodowa,
            old_stabilnosc=old_stability,
            new_stabilnosc=sp.stabilnosc_spoleczna
        )
    )


# =====================================================
# TSUNAMI
# =====================================================

def apply_tsunami_effect(
    region,
    scale,
    victims,
    data_entenda,
    event=None,
    event_id=None
):

    old_state = _snapshot_region_state(region)
    old_pop = _get_region_total_population(region)

    sp = Spoleczenstwo.query.filter_by(
        panstwo_id=region.panstwo_id
    ).first()

    if not sp:
        return

    snapshot = {
        "old_stabilnosc": sp.stabilnosc_spoleczna,
        "old_przestepczosc": sp.przestepczosc
    }

    damage_map = {
        1: (1, 1),
        2: (1, 3),
        3: (3, 10),
        4: (5, 15),
        5: (10, 30)
    }

    social_map = {
        1: (-1, 1),
        2: (-3, 2),
        3: (-7, 3),
        4: (-10, 4),
        5: (-15, 5)
    }

    def _logic():

        _apply_population_loss(region, victims, event)

        dmg = random.randint(*damage_map[scale])

        region.region_stan_infra_drogowej = _degrade(
            region.region_stan_infra_drogowej,
            dmg
        )

        region.region_stan_infra_kolejowej = _degrade(
            region.region_stan_infra_kolejowej,
            dmg
        )

        region.region_stan_infra_energetycznej = _degrade(
            region.region_stan_infra_energetycznej,
            dmg
        )

        region.region_stan_infra_mieszkalnej = _degrade(
            region.region_stan_infra_mieszkalnej,
            dmg
        )

        if region.region_polozenie_id == 2:
            region.region_stan_infra_portowej = _degrade(
                region.region_stan_infra_portowej,
                dmg
            )

        delta_stability, delta_crime = social_map[scale]

        sp.stabilnosc_spoleczna = _clamp_social(
            (sp.stabilnosc_spoleczna or 0) + delta_stability
        )

        sp.przestepczosc = _clamp_social(
            (sp.przestepczosc or 0) + delta_crime
        )

    _with_state_logging(
        region,
        "EVENT",
        _logic,
        data_entenda,
        event_id=event_id
    )

    db.session.add(
        SpoleczenstwoStateHistory(
            panstwo_id=region.panstwo_id,
            data_entenda=data_entenda,
            data_rzeczywista=datetime.now(),
            source="EVENT",
            event_id=event_id,

            old_stabilnosc=snapshot["old_stabilnosc"],
            new_stabilnosc=sp.stabilnosc_spoleczna,

            old_przestepczosc=snapshot["old_przestepczosc"],
            new_przestepczosc=sp.przestepczosc
        )
    )

    new_state = _snapshot_region_state(region)
    new_pop = _get_region_total_population(region)

    log_region_change(
        region=region,
        data_entenda=data_entenda,
        source="EVENT",
        delta_ludnosc=new_pop - old_pop,
        delta_drogi=_delta(new_state["drogi"], old_state["drogi"]),
        delta_kolej=_delta(new_state["kolej"], old_state["kolej"]),
        delta_energia=_delta(new_state["energia"], old_state["energia"]),
        delta_mieszkania=_delta(new_state["mieszkania"], old_state["mieszkania"]),
        delta_porty=_delta(new_state["porty"], old_state["porty"]),
        event_id=event_id
    )

# =====================================================
# NOWY WYNALAZZEK
# =====================================================

def apply_new_invention_effect(
    region,
    scale,
    victims,
    data_entenda,
    event=None,
    event_id=None
):

    sp = Spoleczenstwo.query.filter_by(
        panstwo_id=region.panstwo_id
    ).first()

    if not sp:
        return

    snapshot = {
        "old_edukacja": sp.poziom_edukacji,
        "old_otwartosc": sp.otwartosc_spoleczna
    }

    if scale in (1, 2):
        delta_education = 2
        delta_openness = 2
    else:
        delta_education = 1
        delta_openness = 1

    sp.poziom_edukacji = _clamp_social(
        (sp.poziom_edukacji or 0) + delta_education
    )

    sp.otwartosc_spoleczna = _clamp_social(
        (sp.otwartosc_spoleczna or 0) + delta_openness
    )

    db.session.add(
        SpoleczenstwoStateHistory(
            panstwo_id=region.panstwo_id,
            data_entenda=data_entenda,
            data_rzeczywista=datetime.now(),
            source="EVENT",
            event_id=event_id,

            old_edukacja=snapshot["old_edukacja"],
            new_edukacja=sp.poziom_edukacji,

            old_otwartosc=snapshot["old_otwartosc"],
            new_otwartosc=sp.otwartosc_spoleczna
        )
    )
