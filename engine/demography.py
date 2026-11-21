# engine/demography.py

from datetime import datetime, date
from decimal import Decimal
from sqlalchemy.exc import IntegrityError
from extensions import db
from engine.clock import get_current_entenda_date
from engine.effects import (
    recompute_country_population,
    _get_region_total_population,
    _snapshot_region_state,
    log_region_state_change
)

from models import (
    Region,
    Miasto,
    Panstwo,
    RegionStateHistory,
    MiastoStateHistory,
    HistoriaPopulacjiPanstw,
    ZdarzeniaSystemowe,
    DictZdarzeniaSystemowe,
    Spoleczenstwo,
    Gospodarka,
    PKBPCStateHistory,
    RocznyPrzyrostStateHistory
)

POP_REGEN_SOURCE = "POP_REGEN"
SYSTEM_EVENT_KEY = "regeneracja_populacji"


# =====================================================
# HELPERS
# =====================================================

def _round_population(value):
    return int(round(value))


def _snapshot_city_population(miasto):
    return miasto.miasto_populacja or 0

def _get_population_system_event_definition():
    return (
        DictZdarzeniaSystemowe.query
        .filter_by(
            zdarzenie_systemowe_nazwa=SYSTEM_EVENT_KEY
        )
        .first()
    )

def _log_city_population_change(
    miasto,
    old_population,
    new_population,
    data_entenda
):

    if old_population == new_population:
        return

    entry = MiastoStateHistory(

        miasto_id=miasto.miasto_id,

        data_entenda=data_entenda,

        data_rzeczywista=datetime.now(),

        source=POP_REGEN_SOURCE,

        event_id=None,

        old_miasto_populacja=old_population,

        new_miasto_populacja=new_population,

        change_delta=(new_population - old_population)
    )

    db.session.add(entry)

# =====================================================
# REGION DEMOGRAPHY
# =====================================================

_NURSERY_CACHE = {}


def _nursery_bonus(country_id):
    """Dodatek żłobków do rocznego przyrostu (punkty procentowe, Decimal); błąd modułu miast nie blokuje demografii."""
    if country_id is None:
        return Decimal(0)
    if country_id not in _NURSERY_CACHE:
        try:
            from game.cities import nursery_growth_bonus
            from game.governance import controller_id
            _NURSERY_CACHE[country_id] = Decimal(str(nursery_growth_bonus(db.session, controller_id(db.session, country_id) or country_id)))
        except Exception:
            _NURSERY_CACHE[country_id] = Decimal(0)
    return _NURSERY_CACHE[country_id]


def _apply_region_demography(region, data_entenda):

    # ==========================================
    # SNAPSHOT REGION BEFORE
    # ==========================================

    old_region_state = _snapshot_region_state(region)

    old_region_population = _get_region_total_population(region)

    # ==========================================
    # SNAPSHOT CITIES BEFORE
    # ==========================================

    city_old_values = {}

    for miasto in region.miasta:
        city_old_values[miasto.miasto_id] = (
            _snapshot_city_population(miasto)
        )

    # ==========================================
    # RURAL GROWTH
    # ==========================================

    rural_population = (
        region.region_ludnosc_pozamiejska or 0
    )

    rural_growth_pct = (
        region.roczny_przyrost_wies_pct or 0
    )

    # 21 Nov 2026: żłobki (game.cities) — +0,01 pkt proc. rocznego przyrostu za każdy żłobek w kraju, najwyżej +0,20
    nursery_bonus = _nursery_bonus(region.panstwo_id)
    rural_growth_pct = rural_growth_pct + nursery_bonus

    rural_growth = _round_population(
        rural_population * (rural_growth_pct / 100)
    )

    new_rural_population = max(
        rural_population + rural_growth,
        0
    )

    region.region_ludnosc_pozamiejska = (
        new_rural_population
    )

    # ==========================================
    # CITY GROWTH
    # ==========================================

    miasta = list(region.miasta)

    total_city_population = sum(
        (m.miasto_populacja or 0)
        for m in miasta
    )

    city_growth_pct = (
        region.roczny_przyrost_miasto_pct or 0
    ) + nursery_bonus

    city_growth_total = _round_population(
        total_city_population
        * (city_growth_pct / 100)
    )

    distributed_growth = 0

    largest_city = None

    if miasta:

        largest_city = max(
            miasta,
            key=lambda m: m.miasto_populacja or 0
        )

    for miasto in miasta:

        city_pop = miasto.miasto_populacja or 0

        if total_city_population <= 0:
            growth = 0
        else:
            share = city_pop / total_city_population

            growth = _round_population(
                city_growth_total * share
            )

        miasto.miasto_populacja = max(
            city_pop + growth,
            0
        )

        distributed_growth += growth

    # ==========================================
    # ROUNDING DIFFERENCE
    # ==========================================

    remainder = (
        city_growth_total - distributed_growth
    )

    if largest_city and remainder != 0:

        largest_city.miasto_populacja = max(
            (largest_city.miasto_populacja or 0)
            + remainder,
            0
        )

    # ==========================================
    # URBANIZATION
    # ==========================================

    current_city_population = sum(
        (m.miasto_populacja or 0)
        for m in miasta
    )

    urbanization_pct = (
        region.roczna_urbanizacja_pct or 0
    )

    if urbanization_pct != 0 and miasta:

        current_rural = (
            region.region_ludnosc_pozamiejska or 0
        )

        if urbanization_pct > 0:

            transfer_total = _round_population(
                current_rural * (urbanization_pct / 100)
            )

            transfer_total = min(
                transfer_total,
                current_rural
            )

        elif urbanization_pct < 0:

            transfer_total = _round_population(
                current_city_population
                * (abs(urbanization_pct) / 100)
            )

            transfer_total = min(
                transfer_total,
                total_city_population
            )

        else:
            transfer_total = 0

        total_city_population = sum(
            (m.miasto_populacja or 0)
            for m in miasta
        )

        distributed_transfer = 0

        largest_city = max(
            miasta,
            key=lambda m: m.miasto_populacja or 0
        )

        for miasto in miasta:

            city_pop = miasto.miasto_populacja or 0

            if total_city_population <= 0:
                transfer = 0
            else:
                share = (
                    city_pop / total_city_population
                )

                transfer = _round_population(
                    transfer_total * share
                )

            if urbanization_pct > 0:
                # wieś -> miasta

                miasto.miasto_populacja += transfer

            else:
                # miasta -> wieś

                transfer = min(
                    transfer,
                    miasto.miasto_populacja or 0
                )

                miasto.miasto_populacja -= transfer

            distributed_transfer += transfer

        remainder = (
            transfer_total - distributed_transfer
        )

        if remainder != 0:

            if urbanization_pct > 0:

                largest_city.miasto_populacja += remainder

            else:

                removable = min(
                    remainder,
                    largest_city.miasto_populacja or 0
                )

                largest_city.miasto_populacja -= removable

                remainder = removable

        if urbanization_pct > 0:

            region.region_ludnosc_pozamiejska = max(
                current_rural - transfer_total,
                0
            )

        else:

            region.region_ludnosc_pozamiejska = (
                current_rural + transfer_total
            )

    # ==========================================
    # SNAPSHOT REGION AFTER
    # ==========================================

    new_region_state = _snapshot_region_state(region)

    new_region_population = (
        _get_region_total_population(region)
    )

    log_region_state_change(
        region=region,
        old_values=old_region_state,
        new_values=new_region_state,
        source=POP_REGEN_SOURCE,
        data_entenda=data_entenda,
        old_population=old_region_population,
        new_population=new_region_population,
        event_id=None
    )

    # ==========================================
    # SNAPSHOT CITIES AFTER
    # ==========================================

    for miasto in miasta:

        old_pop = city_old_values.get(
            miasto.miasto_id,
            0
        )

        new_pop = (
            miasto.miasto_populacja or 0
        )

        _log_city_population_change(
            miasto=miasto,
            old_population=old_pop,
            new_population=new_pop,
            data_entenda=data_entenda
        )

# =====================================================
# GLOBAL POPULATION REGENERATION
# =====================================================

def apply_global_population_regeneration():

    current_date = get_current_entenda_date()

    event_def = _get_population_system_event_definition()

    if not event_def:
        raise RuntimeError(
            "Brak definicji zdarzenia systemowego "
            "'regeneracja_populacji'."
        )

    # tylko 31 grudnia
    if not (
        current_date.month == 12
        and current_date.day == 31
    ):
        return False

    try:

        regions = Region.query.filter(Region.panstwo_id.in_(
            Panstwo.query.with_entities(Panstwo.PANSTWO_ID).filter(Panstwo.status == 'aktywne')
        )).all()

        _NURSERY_CACHE.clear()   # 21 Nov 2026: żłobki liczone od nowa przy każdym rocznym przeliczeniu

        for region in regions:

            _apply_region_demography(
                region=region,
                data_entenda=current_date
            )

        # ======================================
        # RECOMPUTE COUNTRIES
        # ======================================

        countries = Panstwo.query.all()

        for country in countries:

            old_population = country.panstwo_populacja or 0

            history_entry = HistoriaPopulacjiPanstw(
                panstwo_id=country.PANSTWO_ID,
                data_entenda=current_date,
                data_rzeczywista=datetime.now(),
                panstwo_populacja=old_population
            )

            db.session.add(history_entry)

            recompute_country_population(country.PANSTWO_ID)

        # ======================================
        # SYSTEM EVENT LOG
        # ======================================

        system_event = ZdarzeniaSystemowe(
            zdarzenie_systemowe_id=event_def.zdarzenie_systemowe_id,
            data_entenda=current_date,
            data_rzeczywista=datetime.now(),
            opis=(
                "System ZEUS pomyślnie wykonał roczne przeliczenie populacji wszystkich państw Entendy."
            )
        )

        db.session.add(system_event)

        db.session.commit()

        print(
            "[ZEUS] wykonano globalną "
            "regenerację populacji"
        )

        return True

    except IntegrityError:

        db.session.rollback()

        return False

    except Exception:

        db.session.rollback()

        raise

#----------------------------------------------------------#

def run_annual_population_growth_regeneration(current_date):

    event_def = (
        DictZdarzeniaSystemowe.query
        .filter_by(
            zdarzenie_systemowe_nazwa="regeneracja_przyrostu"
        )
        .first()
    )

    if not event_def:
        raise RuntimeError(
            "Brak definicji zdarzenia systemowego "
            "'regeneracja_przyrostu'."
        )

    already_done = ZdarzeniaSystemowe.query.filter_by(
        zdarzenie_systemowe_id=event_def.zdarzenie_systemowe_id,
        data_entenda=current_date
    ).first()

    if already_done:
        print("[POPULATION] Regeneracja już wykonana.")
        return False

    if not (
        current_date.month == 12
        and current_date.day == 27
    ):
        print(f"[POPULATION] Zła data: {current_date}")
        return False

    try:

        panstwa = Panstwo.query.all()

        for panstwo in panstwa:

            regiony = Region.query.filter_by(
                panstwo_id=panstwo.PANSTWO_ID
            ).all()

            if not regiony:
                continue

            old_avg = calculate_country_population_growth(regiony)

            spoleczenstwo = Spoleczenstwo.query.filter_by(
                panstwo_id=panstwo.PANSTWO_ID
            ).first()

            gospodarka = Gospodarka.query.filter_by(
                panstwo_id=panstwo.PANSTWO_ID
            ).first()

            if not spoleczenstwo or not gospodarka:
                continue

            pkbpc_date = date(current_date.year, 1, 1)

            pkbpc = (
                PKBPCStateHistory.query
                .filter_by(
                    panstwo_id=panstwo.PANSTWO_ID,
                    data_entenda=pkbpc_date
                )
                .first()
            )

            pkb_per_capita = pkbpc.new_pkbpc if pkbpc else None

            delta = Decimal(str(calculate_population_growth_delta(
                spoleczenstwo,
                gospodarka,
                pkb_per_capita
            )))

            for region in regiony:

                if region.roczny_przyrost_miasto_pct is not None:
                    region.roczny_przyrost_miasto_pct = round(
                        region.roczny_przyrost_miasto_pct + delta,
                        2
                    )

                if region.roczny_przyrost_wies_pct is not None:
                    region.roczny_przyrost_wies_pct = round(
                        region.roczny_przyrost_wies_pct + delta,
                        2
                    )

            new_avg = calculate_country_population_growth(regiony)

            history = RocznyPrzyrostStateHistory(
                panstwo_id=panstwo.PANSTWO_ID,
                old_roczny_przyrost=old_avg,
                new_roczny_przyrost=new_avg,
                data_entenda=current_date,
                data_rzeczywista=datetime.now()
            )

            db.session.add(history)

            print(
                f"[POPULATION] {panstwo.panstwo_nazwa}: "
                f"{old_avg}% -> {new_avg}% "
                f"(Δ {delta:+.2f})"
            )

        system_event = ZdarzeniaSystemowe(
            zdarzenie_systemowe_id=event_def.zdarzenie_systemowe_id,
            data_entenda=current_date,
            data_rzeczywista=datetime.now(),
            opis=(
                "System ZEUS pomyślnie wykonał regenerację "
                "rocznego przyrostu ludności wszystkich państw Entendy."
            )
        )

        db.session.add(system_event)

        db.session.commit()

        print("[POPULATION] Zakończono regenerację rocznego przyrostu ludności.")

        return True

    except IntegrityError:

        db.session.rollback()

        return False

    except Exception:

        db.session.rollback()

        raise
    
#----------------------------------------------------------#

def calculate_country_population_growth(regiony):
    miasto_values = [
        r.roczny_przyrost_miasto_pct
        for r in regiony
        if r.roczny_przyrost_miasto_pct is not None
    ]

    wies_values = [
        r.roczny_przyrost_wies_pct
        for r in regiony
        if r.roczny_przyrost_wies_pct is not None
    ]

    if miasto_values and wies_values:
        return round(
            (
                (sum(miasto_values) / len(miasto_values))
                +
                (sum(wies_values) / len(wies_values))
            ) / 2,
            2
        )

    return None

#----------------------------------------------------------#

def calculate_population_growth_delta(
    spoleczenstwo,
    gospodarka,
    pkb_per_capita
):

    delta = Decimal("0")

    zdrowie = spoleczenstwo.zdrowie_publiczne or 0
    edukacja = spoleczenstwo.poziom_edukacji or 0
    stabilnosc = spoleczenstwo.stabilnosc_spoleczna or 0

    if zdrowie >= 80:
        delta += Decimal("0.03")
    elif zdrowie < 40:
        delta -= Decimal("0.03")

    if edukacja >= 80:
        delta -= Decimal("0.02")
    elif edukacja < 40:
        delta += Decimal("0.02")

    if stabilnosc >= 80:
        delta += Decimal("0.02")
    elif stabilnosc < 40:
        delta -= Decimal("0.02")

    if pkb_per_capita is not None:
        if pkb_per_capita >= 70000:
            delta -= Decimal("0.03")
        elif pkb_per_capita <= 10000:
            delta += Decimal("0.03")

    return delta.quantize(Decimal("0.01"))

#----------------------------------------------------------#
