import random
from datetime import datetime, timedelta
from engine.clock import get_current_entenda_date, ENTENDA_START
from engine.economy import (
    run_annual_growth_regeneration,
    run_annual_pkb_regeneration,
    run_annual_pkbpc_snapshot
)
from sqlalchemy import extract, func
from apscheduler.schedulers.background import BackgroundScheduler
import calendar
from extensions import db
from game.event_notifications import queue_generated_event
from models import Zdarzenie, Region, Panstwo, Miasto, RegionStateHistory, Spoleczenstwo, ZdarzeniaSystemowe, DictZdarzeniaSystemowe
from engine.selectors import select_regions, active_regions
from engine.template_selector import select_template
from engine.event_renderer import render_event_description
from engine.retention import wykonaj_retencje_zdarzen
from engine.demography import (apply_global_population_regeneration, run_annual_population_growth_regeneration)
from engine.effects import (
    apply_earthquake_effect,
    apply_train_disaster_effect,
    apply_road_disaster_effect,
    apply_flood_effect,
    apply_avalanche_effect,
    apply_volcano_effect,
    apply_coldwave_effect,
    apply_heatwave_effect,
    apply_region_regeneration,
    apply_building_fire_effect,
    apply_power_outage_effect,
    apply_air_disaster_effect,
    apply_social_riot_effect,
    apply_terror_attack_effect,
    apply_social_protest_effect,
    apply_law_effect,
    apply_high_air_pollution_effect,
    apply_patriotic_march_effect,
    apply_tsunami_effect,
    apply_new_invention_effect
)

#----------------------------------------------------------#

MAX_EVENTS_PER_DAY = 2
MAX_EVENTS_PER_WEEK = 5
MAX_EVENTS_PER_MONTH = 25
MAX_EVENTS_PER_REGION_PER_MONTH = 60

#----------------------------------------------------------#

scheduler = None

def start_event_scheduler(app):
    global scheduler

    scheduler = BackgroundScheduler()

    def events_job():
        with app.app_context():
            print("[ZEUS] events tick")
            generate_events()

    def retention_job():
        with app.app_context():
            print("[ZEUS] retention tick")
            wykonaj_retencje_zdarzen()

    scheduler.add_job(
        events_job,
        "interval",
        minutes=60
    )

    scheduler.add_job(
        retention_job,
        "cron",
        hour=0,
        minute=0
    )

    scheduler.start()

#----------------------------------------------------------#

def generate_events():

    from engine.clock import get_time_multiplier
    if get_time_multiplier() == 0:
        return 0

    current_entenda = get_current_entenda_date()

    run_annual_population_growth_regeneration(current_entenda)

    apply_yearly_regeneration_if_needed(current_entenda)

    run_annual_growth_regeneration()

    run_annual_pkb_regeneration()

    apply_global_population_regeneration()

    run_annual_pkbpc_snapshot()

    last_generated = get_last_generated_entenda_date()

    generated_total = 0

    current_month = datetime(last_generated.year, last_generated.month, 1)

    end_month = datetime(current_entenda.year, current_entenda.month, 1)

    while current_month <= end_month:

        created = generate_events_for_month(current_month)

        generated_total += created

        if current_month.month == 12:
            current_month = datetime(current_month.year + 1, 1, 1)
        else:
            current_month = datetime(current_month.year, current_month.month + 1, 1)

    print(f"[ZEUS] wygenerowano {generated_total} zdarzeń")

    return generated_total

#----------------------------------------------------------#

def apply_global_regeneration():

    regions = active_regions().all()

    for r in regions:
        apply_region_regeneration(r)

    db.session.commit()

    print("[ZEUS] wykonano rocznÄ… regeneracjÄ™ infrastruktury")

#----------------------------------------------------------#

def apply_yearly_regeneration_if_needed(current_entenda):

    if current_entenda.month != 12 or current_entenda.day != 28:
        return False

    dict_entry = (
        DictZdarzeniaSystemowe.query
        .filter_by(
            zdarzenie_systemowe_nazwa="regeneracja_regionow"
        )
        .first()
    )

    if not dict_entry:
        raise RuntimeError(
            "Brak słownika dla regeneracja_regionow"
        )

    existing_run = (
        ZdarzeniaSystemowe.query
        .filter_by(
            zdarzenie_systemowe_id=dict_entry.zdarzenie_systemowe_id,
            data_entenda=current_entenda
        )
        .first()
    )

    if existing_run:
        return False

    try:
        # lock ochronny
        db.session.add(
            ZdarzeniaSystemowe(
                zdarzenie_systemowe_id=dict_entry.zdarzenie_systemowe_id,
                data_entenda=current_entenda,
                data_rzeczywista=datetime.now(),
                opis=(
                    "System ZEUS pomyślnie dokonał rocznej "
                    "regeneracji infrastruktury wszystkich regionów Entendy."
                )
            )
        )

        db.session.flush()

        regions = active_regions().all()

        for region in regions:
            apply_region_regeneration(region)

        db.session.commit()

        print(
            f"[ZEUS] wykonano regenerację regionów "
            f"dla {current_entenda}"
        )

        return True

    except Exception:
        db.session.rollback()
        raise

#----------------------------------------------------------#

def apply_global_regeneration():

    regions = active_regions().all()

    for r in regions:
        apply_region_regeneration(r)

    db.session.commit()

    event_def = (
        DictZdarzeniaSystemowe.query
        .filter_by(
            zdarzenie_systemowe_nazwa="regeneracja_regionow"
        )
        .first()
    )

    if event_def:
        db.session.add(
            ZdarzeniaSystemowe(
                zdarzenie_systemowe_id=event_def.zdarzenie_systemowe_id,
                data_entenda=get_current_entenda_date(),
                data_rzeczywista=datetime.now()
            )
        )
        db.session.commit()

#----------------------------------------------------------#

def get_week_event_count(date):
    year, week, _ = date.isocalendar()

    return (
        db.session.query(Zdarzenie)
        .filter(extract("year", Zdarzenie.data_entenda) == year)
        .filter(func.week(Zdarzenie.data_entenda, 1) == week)
        .count()
    )

#----------------------------------------------------------#

def generate_events_for_month(month_date):

    month_events = get_month_event_count(month_date)

    if month_events >= MAX_EVENTS_PER_MONTH:
        return 0

    remaining = MAX_EVENTS_PER_MONTH - month_events

    events_created = 0

    regions = select_regions(300)

    for region in regions:

        region_events = get_region_month_event_count(region.region_id, month_date)

        if region_events >= MAX_EVENTS_PER_REGION_PER_MONTH:
            continue

        if events_created >= remaining:
            break

        events = [
            (try_generate_earthquake, apply_earthquake_effect),
            (try_generate_train_disaster, apply_train_disaster_effect),
            (try_generate_road_disaster, apply_road_disaster_effect),
            (try_generate_flood, apply_flood_effect),
            (try_generate_avalanche, apply_avalanche_effect),
            (try_generate_volcano, apply_volcano_effect),
            (try_generate_coldwave, apply_coldwave_effect),
            (try_generate_heatwave, apply_heatwave_effect),
            (try_generate_building_fire, None),
            (try_generate_power_outage, apply_power_outage_effect),
            (try_generate_air_disaster, apply_air_disaster_effect),
            (try_generate_social_riot, apply_social_riot_effect),
            (try_generate_terror_attack, apply_terror_attack_effect),
            (try_generate_social_protest, apply_social_protest_effect),
            (try_generate_new_law, apply_law_effect),
            (try_generate_wildfire, None),
            (try_generate_high_pollution, apply_high_air_pollution_effect),
            (try_generate_new_invention, apply_new_invention_effect),
            (try_generate_patriotic_march, apply_patriotic_march_effect),
            (try_generate_tsunami, apply_tsunami_effect)
        ]

        random.shuffle(events)

        for generator, effect in events:

            target_date = random_day_in_month(month_date)
            event = generator(region, target_date)

            if event:
                print(f"[EVENT] {event.zdarzenie_typ}")

            week_count = get_week_event_count(target_date)
            day_count = get_day_event_count(event.data_entenda) if event else 0

            if event:
                print(
                    f"[CHECK] "
                    f"week={week_count}/{MAX_EVENTS_PER_WEEK} "
                    f"day={day_count}/{MAX_EVENTS_PER_DAY} "
                    f"region={region_events}/{MAX_EVENTS_PER_REGION_PER_MONTH} "
                    f"created={events_created}/{remaining}"
                )

            if event and week_count >= MAX_EVENTS_PER_WEEK:
                print("[SKIP] WEEK LIMIT")
                continue

            if event and day_count >= MAX_EVENTS_PER_DAY:
                print("[SKIP] DAY LIMIT")
                continue

            if event and region_events < MAX_EVENTS_PER_REGION_PER_MONTH and events_created < remaining:

                print("[ADD] Dodaję zdarzenie")

                template = select_template(
                    event_type=event.zdarzenie_typ,
                    scale=event.skala,
                    variant=event.wariant,
                    panstwo_id=event.panstwo_id,
                    target_date=event.data_entenda
                )

                if template:
                    event.opis_szablon_id = template.szablon_id
                    event.opis_wygenerowany = render_event_description(event, template.tresc)
                else:
                    event.opis_wygenerowany = None

                db.session.add(event)
                db.session.flush()

                if effect and not getattr(event, "effect_applied", False):

                    db.session.add(event)
                    db.session.flush()

                    effect(
                        region=region,
                        scale=event.skala,
                        victims=event.ilosc_ofiar,
                        data_entenda=event.data_entenda,
                        event=event,
                        event_id=event.zdarzenie_id
                    )

                    event.effect_applied = True

                queue_generated_event(event)

                events_created += 1
                print(f"[COUNT] events_created={events_created}")
                region_events += 1

                if region_events >= MAX_EVENTS_PER_REGION_PER_MONTH:
                    break

        if region_events < MAX_EVENTS_PER_REGION_PER_MONTH and events_created < remaining:

                target_date = random_day_in_month(month_date)

                event = try_generate_wildfire(region, target_date)

                if event:

                    if get_week_event_count(target_date) >= MAX_EVENTS_PER_WEEK:
                        continue

                    if get_day_event_count(event.data_entenda) >= MAX_EVENTS_PER_DAY:
                        continue

                    template = select_template(event.zdarzenie_typ, event.skala)

                    if template:
                        event.opis_szablon_id = template.szablon_id
                        event.opis_wygenerowany = render_event_description(
                            event,
                            template.tresc
                        )

                    db.session.add(event)
                    db.session.flush()

                    queue_generated_event(event)

                    events_created += 1
                    region_events += 1

    db.session.commit()

    return events_created              
#----------------------------------------------------------#

def cooldown_block(event_type, region_id, current_entenda):

    six_months = current_entenda - timedelta(days=180)

    existing = (
        Zdarzenie.query
        .filter(Zdarzenie.zdarzenie_typ == event_type)
        .filter(Zdarzenie.region_id == region_id)
        .filter(Zdarzenie.data_entenda >= six_months)
        .first()
    )

    return existing is not None

#----------------------------------------------------------#

def random_day_in_month(month_date):

    current_entenda = get_current_entenda_date()

    # liczba dni w miesiÄ…cu
    days = calendar.monthrange(month_date.year, month_date.month)[1]

    # jeĹĽeli to bieĹĽÄ…cy miesiÄ…c symulacji
    if month_date.year == current_entenda.year and month_date.month == current_entenda.month:
        max_day = current_entenda.day
    else:
        max_day = days

    day = random.randint(1, max_day)

    return month_date.replace(day=day)

#----------------------------------------------------------#

def get_region_month_event_count(region_id, date):

    return (
        db.session.query(Zdarzenie)
        .filter(Zdarzenie.region_id == region_id)
        .filter(extract("year", Zdarzenie.data_entenda) == date.year)
        .filter(extract("month", Zdarzenie.data_entenda) == date.month)
        .count()
    )

#----------------------------------------------------------#

def get_day_event_count(date):

    return (
        db.session.query(Zdarzenie)
        .filter(Zdarzenie.data_entenda == date)
        .count()
    )

#----------------------------------------------------------#

def get_random_valid_city(region_id):
    return (
        Miasto.query
        .filter_by(region_id=region_id)
        .filter(~func.lower(Miasto.miasto_nazwa).like("miasto techniczne%"))
        .order_by(func.rand())
        .first()
    )

#----------------------------------------------------------#

def compute_victims(region, victims_range, severity="medium"):

    base = random.randint(*victims_range)

    miasta_pop = sum(
        (m.miasto_populacja or 0)
        for m in region.miasta
    )

    rural_pop = region.region_ludnosc_pozamiejska or 0

    pop = miasta_pop + rural_pop

    # zabezpieczenie
    pop = max(pop, 1)

    scaling_map = {
        "low": 0.25,
        "medium": 0.65,
        "high": 0.80
    }

    exponent = scaling_map.get(severity, 0.65)

    factor = (pop / 1_000_000) ** exponent

    victims = int(base * factor)

    caps = {
        "low": 50,
        "medium": 500,
        "high": 50000
    }

    victims = min(victims, caps.get(severity, 500))

    return max(victims, 0)

#----------------------------------------------------------#

def get_last_generated_entenda_date():

    last = (
        db.session.query(Zdarzenie)
        .order_by(Zdarzenie.data_entenda.desc())
        .first()
    )

    if last and last.data_entenda:
        return last.data_entenda

    return ENTENDA_START

#----------------------------------------------------------#

def get_month_event_count(date):

    return (
        db.session.query(Zdarzenie)
        .filter(extract("year", Zdarzenie.data_entenda) == date.year)
        .filter(extract("month", Zdarzenie.data_entenda) == date.month)
        .count()
    )

#----------------------------------------------------------#

def is_summer(region, month):
    if region.polkula == "NORTH":
        return 4 <= month <= 9
    elif region.polkula == "SOUTH":
        return month >= 10 or month <= 3
    return True  # brak danych → brak ograniczeń


def is_winter(region, month):
    if region.polkula == "NORTH":
        return month >= 10 or month <= 3
    elif region.polkula == "SOUTH":
        return 4 <= month <= 9
    return True

#----------------------------------------------------------#

def try_generate_earthquake(region, target_date):

    s = region.region_sejsmicznosc or 0

    if s <= 0:
        return None

    if cooldown_block("trzesienie_ziemi", region.region_id, target_date):
        return None

    if s < 20:
        prob = 0.0001
        scale = 1
        victims_range = (0,3)

    elif s < 40:
        prob = 0.0008
        scale = 2
        victims_range = (1,8)

    elif s < 60:
        prob = 0.0016
        scale = 3
        victims_range = (3,15)

    elif s < 80:
        prob = 0.0023
        scale = 4
        victims_range = (26,500)

    else:
        prob = 0.0017
        scale = 5
        victims_range = (501,10000)

    if random.random() > prob:
        return None

    victims = compute_victims(region, victims_range)

    miasto = get_random_valid_city(region.region_id)

    if not miasto:
        return None

    return Zdarzenie(
        zdarzenie_typ="trzesienie_ziemi",
        panstwo_id=region.panstwo_id,
        region_id=region.region_id,
        miasto_id=miasto.miasto_id,
        skala=scale,
        ilosc_ofiar=victims,
        data_rzeczywista=datetime.now(),
        data_entenda=target_date
    )

#----------------------------------------------------------#

def try_generate_train_disaster(region, target_date):

    infra = region.region_stan_infra_kolejowej or 100

    if infra >= 90:
        return None

    if cooldown_block("katastrofa_kolejowa", region.region_id, target_date):
        return None

    if infra > 80:
        prob = 0.0001
        scale = 1
        victims_range = (0,1)

    elif infra > 65:
        prob = 0.0005
        scale = 2
        victims_range = (1,3)

    elif infra > 50:
        prob = 0.0007
        scale = 3
        victims_range = (3,8)

    elif infra > 30:
        prob = 0.0015
        scale = 4
        victims_range = (5,15)

    else:
        prob = 0.0018
        scale = 5
        victims_range = (10,35)

    if random.random() > prob:
        return None

    victims = compute_victims(region, victims_range, severity="low")
    victims = min(victims, 120)

    miasto = get_random_valid_city(region.region_id)

    if not miasto:
        return None

    return Zdarzenie(
        zdarzenie_typ="katastrofa_kolejowa",
        panstwo_id=region.panstwo_id,
        region_id=region.region_id,
        miasto_id=miasto.miasto_id,
        skala=scale,
        ilosc_ofiar=victims,
        data_rzeczywista=datetime.now(),
        data_entenda=target_date
    )

#----------------------------------------------------------#

def try_generate_road_disaster(region, target_date):

    infra = region.region_stan_infra_drogowej or 100

    if infra >= 90:
        return None

    if cooldown_block("katastrofa_w_ruchu_ladowym", region.region_id, target_date):
        return None

    if infra > 80:
        prob = 0.0003
        scale = 1
        victims_range = (0,1)

    elif infra > 65:
        prob = 0.0010
        scale = 2
        victims_range = (2,5)

    elif infra > 50:
        prob = 0.0018
        scale = 3
        victims_range = (5,8)

    elif infra > 30:
        prob = 0.0022
        scale = 4
        victims_range = (9,12)

    else:
        prob = 0.0030
        scale = 5
        victims_range = (13,18)

    if random.random() > prob:
        return None

    victims = compute_victims(region, victims_range, severity="low")

    miasto = get_random_valid_city(region.region_id)

    if not miasto:
        return None

    return Zdarzenie(
        zdarzenie_typ="katastrofa_w_ruchu_ladowym",
        panstwo_id=region.panstwo_id,
        region_id=region.region_id,
        miasto_id=miasto.miasto_id,
        skala=scale,
        ilosc_ofiar=victims,
        data_rzeczywista=datetime.now(),
        data_entenda=target_date
    )

#----------------------------------------------------------#

def try_generate_flood(region, target_date):

    s = region.region_ryzyko_powodzi or 0

    if s <= 0:
        return None

    if cooldown_block("powodz", region.region_id, target_date):
        return None

    if s < 20:
        prob = 0.001
        scale = 1
        victims_range = (0,1)

    elif s < 40:
        prob = 0.002
        scale = 2
        victims_range = (2,15)

    elif s < 60:
        prob = 0.003
        scale = 3
        victims_range = (16,40)

    elif s < 80:
        prob = 0.0035
        scale = 4
        victims_range = (41,100)

    else:
        prob = 0.004
        scale = 5
        victims_range = (101,1000)

    if random.random() > prob:
        return None

    victims = compute_victims(region, victims_range)

    miasto = get_random_valid_city(region.region_id)

    if not miasto:
        return None

    return Zdarzenie(
        zdarzenie_typ="powodz",
        panstwo_id=region.panstwo_id,
        region_id=region.region_id,
        miasto_id=miasto.miasto_id,
        skala=scale,
        ilosc_ofiar=victims,
        data_rzeczywista=datetime.now(),
        data_entenda=target_date
    )

#----------------------------------------------------------#

def try_generate_avalanche(region, target_date):

    s = region.region_ryzyko_lawin or 0

    if s <= 0:
        return None

    if cooldown_block("lawina", region.region_id, target_date):
        return None

    if s < 20:
        prob = 0.001
        scale = 1
        victims_range = (0,1)

    elif s < 40:
        prob = 0.0015
        scale = 2
        victims_range = (1,2)

    elif s < 60:
        prob = 0.002
        scale = 3
        victims_range = (1,7)

    elif s < 80:
        prob = 0.003
        scale = 4
        victims_range = (4,10)

    else:
        prob = 0.0035
        scale = 5
        victims_range = (1,15)

    if random.random() > prob:
        return None

    victims = compute_victims(region, victims_range)

    miasto = get_random_valid_city(region.region_id)

    if not miasto:
        return None

    return Zdarzenie(
        zdarzenie_typ="lawina",
        panstwo_id=region.panstwo_id,
        region_id=region.region_id,
        miasto_id=miasto.miasto_id,
        skala=scale,
        ilosc_ofiar=victims,
        data_rzeczywista=datetime.now(),
        data_entenda=target_date
    )

#----------------------------------------------------------#

def try_generate_volcano(region, target_date):

    s = region.region_aktywny_wulkan or 0

    if s <= 0:
        return None

    if cooldown_block("erupcja_wulkanu", region.region_id, target_date):
        return None

    if s < 20:
        prob = 0.00005
        scale = 1
        victims_range = (0,5)

    elif s < 40:
        prob = 0.0001
        scale = 2
        victims_range = (6,30)

    elif s < 60:
        prob = 0.00015
        scale = 3
        victims_range = (15,100)

    elif s < 80:
        prob = 0.0002
        scale = 4
        victims_range = (50,500)

    else:
        prob = 0.0003
        scale = 5
        victims_range = (200,5000)

    if random.random() > prob:
        return None

    victims = compute_victims(region, victims_range)

    miasto = get_random_valid_city(region.region_id)

    if not miasto:
        return None

    return Zdarzenie(
        zdarzenie_typ="erupcja_wulkanu",
        panstwo_id=region.panstwo_id,
        region_id=region.region_id,
        miasto_id=miasto.miasto_id,
        skala=scale,
        ilosc_ofiar=victims,
        data_rzeczywista=datetime.now(),
        data_entenda=target_date
    )

#----------------------------------------------------------#

def try_generate_coldwave(region, target_date):

    if not is_winter(region, target_date.month):
        return None

    s = region.region_ryzyko_mrozu or 0

    if s <= 0:
        return None

    if cooldown_block("fala_mrozu", region.region_id, target_date):
        return None

    if s < 20:
        prob = 0.0005
        scale = 1
        victims_range = (0,1)

    elif s < 40:
        prob = 0.001
        scale = 2
        victims_range = (2,5)

    elif s < 60:
        prob = 0.0015
        scale = 3
        victims_range = (6,10)

    elif s < 80:
        prob = 0.0025
        scale = 4
        victims_range = (11,20)

    else:
        prob = 0.003
        scale = 5
        victims_range = (21,100)

    if random.random() > prob:
        return None

    victims = compute_victims(region, victims_range)

    miasto = get_random_valid_city(region.region_id)

    if not miasto:
        return None

    return Zdarzenie(
        zdarzenie_typ="fala_mrozu",
        panstwo_id=region.panstwo_id,
        region_id=region.region_id,
        miasto_id=miasto.miasto_id,
        skala=scale,
        ilosc_ofiar=victims,
        data_rzeczywista=datetime.now(),
        data_entenda=target_date
    )

#----------------------------------------------------------#

def try_generate_heatwave(region, target_date):

    if not is_summer(region, target_date.month):
        return None

    s = region.region_ryzyko_upalu or 0

    if s <= 0:
        return None

    if cooldown_block("fala_upalu", region.region_id, target_date):
        return None

    if s < 20:
        prob = 0.0003
        scale = 1
        victims_range = (0,1)

    elif s < 40:
        prob = 0.0007
        scale = 2
        victims_range = (1,5)

    elif s < 60:
        prob = 0.0010
        scale = 3
        victims_range = (6,15)

    elif s < 80:
        prob = 0.0012
        scale = 4
        victims_range = (16,30)

    else:
        prob = 0.0017
        scale = 5
        victims_range = (31,50)

    if random.random() > prob:
        return None

    victims = compute_victims(region, victims_range)

    miasto = get_random_valid_city(region.region_id)

    if not miasto:
        return None

    return Zdarzenie(
        zdarzenie_typ="fala_upalu",
        panstwo_id=region.panstwo_id,
        region_id=region.region_id,
        miasto_id=miasto.miasto_id,
        skala=scale,
        ilosc_ofiar=victims,
        data_rzeczywista=datetime.now(),
        data_entenda=target_date
    )

#----------------------------------------------------------#

def try_generate_wildfire(region, target_date):

    if not (
        region.region_typ_nadrz_id == 8 or
        region.region_typ_podrz_id == 17
    ):
        return None

    heatwave = (
        db.session.query(Zdarzenie)
        .filter(Zdarzenie.region_id == region.region_id)
        .filter(Zdarzenie.zdarzenie_typ == "fala_upalu")
        .filter(Zdarzenie.skala >= 4)
        .filter(extract("year", Zdarzenie.data_entenda) == target_date.year)
        .filter(extract("month", Zdarzenie.data_entenda) == target_date.month)
        .filter(Zdarzenie.data_entenda <= target_date)
        .order_by(Zdarzenie.skala.desc())
        .first()
    )

    if not heatwave:
        return None

    if cooldown_block("pozar_lasu", region.region_id, target_date):
        return None

    prob = 0.03

    if random.random() > prob:
        return None

    victims = 0
    scale = heatwave.skala

    miasto = get_random_valid_city(region.region_id)

    if not miasto:
        return None

    return Zdarzenie(
        zdarzenie_typ="pozar_lasu",
        panstwo_id=region.panstwo_id,
        region_id=region.region_id,
        miasto_id=miasto.miasto_id,
        skala=scale,
        ilosc_ofiar=victims,
        data_rzeczywista=datetime.now(),
        data_entenda=target_date
    )

#----------------------------------------------------------#

def try_generate_building_fire(region, target_date):

    infra = region.region_stan_infra_mieszkalnej or 100

    # brak sensu przy bardzo dobrej infrastrukturze
    if infra >= 90:
        return None

    if cooldown_block("pozar_budynku", region.region_id, target_date):
        return None

    # skala + prawdopodobieĹ„stwo + ofiary
    if infra > 80:
        prob = 0.0010
        scale = 1
        victims_range = (0, 0)

    elif infra > 65:
        prob = 0.0020
        scale = 2
        victims_range = (0, 1)

    elif infra > 50:
        prob = 0.0030
        scale = 3
        victims_range = (0, 2)

    elif infra > 30:
        prob = 0.0035
        scale = 4
        victims_range = (0, 4)

    else:
        prob = 0.0040
        scale = 5
        victims_range = (0, 10)

    if random.random() > prob:
        return None

    victims = compute_victims(region, victims_range)

    # miasto (TwĂłj standard)
    miasto = get_random_valid_city(region.region_id)

    if not miasto:
        return None

    return Zdarzenie(
        zdarzenie_typ="pozar_budynku",
        panstwo_id=region.panstwo_id,
        region_id=region.region_id,
        miasto_id=miasto.miasto_id,
        skala=scale,
        ilosc_ofiar=victims,
        data_rzeczywista=datetime.now(),
        data_entenda=target_date
    )

#----------------------------------------------------------#

def try_generate_power_outage(region, target_date):

    infra = region.region_stan_infra_energetycznej or 100

    if infra >= 90:
        return None

    if cooldown_block("przerwa_w_dost_prod", region.region_id, target_date):
        return None

    # skala + prawdopodobieĹ„stwo + ofiary
    if infra > 80:
        prob = 0.000
        scale = 1
        victims_range = (0, 0)

    elif infra > 65:
        prob = 0.001
        scale = 2
        victims_range = (0, 0)

    elif infra > 50:
        prob = 0.0010
        scale = 3
        victims_range = (0, 0)

    elif infra > 30:
        prob = 0.0020
        scale = 4
        victims_range = (1, 5)

    else:
        prob = 0.0030
        scale = 5
        victims_range = (3, 20)

    if random.random() > prob:
        return None

    victims = compute_victims(region, victims_range, severity="low")

    miasto = get_random_valid_city(region.region_id)

    if not miasto:
        return None

    return Zdarzenie(
        zdarzenie_typ="przerwa_w_dost_prod",
        panstwo_id=region.panstwo_id,
        region_id=region.region_id,
        miasto_id=miasto.miasto_id,
        skala=scale,
        ilosc_ofiar=victims,
        data_rzeczywista=datetime.now(),
        data_entenda=target_date
    )

#----------------------------------------------------------#

def try_generate_air_disaster(region, target_date):

    if cooldown_block("katastrofa_lotnicza", region.region_id, target_date):
        return None

    prob = 0.00002
    scale = 5
    victims_range = (250, 400)

    if random.random() > prob:
        return None

    victims = random.randint(250, 400)

    miasto = get_random_valid_city(region.region_id)

    miasto_id = miasto.miasto_id if miasto else None

    return Zdarzenie(
        zdarzenie_typ="katastrofa_lotnicza",
        panstwo_id=region.panstwo_id,
        region_id=region.region_id,
        miasto_id=miasto_id,
        skala=scale,
        ilosc_ofiar=victims,
        data_rzeczywista=datetime.now(),
        data_entenda=target_date
    )

#----------------------------------------------------------#

def try_generate_social_riot(region, target_date):

    if cooldown_block("zamieszki_spol", region.region_id, target_date):
        return None

    sp = Spoleczenstwo.query.filter_by(
        panstwo_id=region.panstwo_id
    ).first()

    if not sp:
        return None

    wspol_stabil_spolecznej = (
        (sp.stabilnosc_spoleczna or 0)
        + (sp.zadowolenie_spoleczne or 0)
        + (sp.zaufanie_do_wladzy or 0)
    ) / 100

    if 1.3 <= wspol_stabil_spolecznej <= 1.4:
        scale = 1
        victims_range = (0, 0)
        prob = 0.014

    elif 1.1 <= wspol_stabil_spolecznej <= 1.2:
        scale = 2
        victims_range = (0, 0)
        prob = 0.025

    elif 0.8 <= wspol_stabil_spolecznej <= 1.0:
        scale = 3
        victims_range = (0, 2)
        prob = 0.050

    elif 0.6 <= wspol_stabil_spolecznej <= 0.7:
        scale = 4
        victims_range = (0, 8)
        prob = 0.090

    elif 0 <= wspol_stabil_spolecznej <= 0.5:
        scale = 5
        victims_range = (5, 20)
        prob = 0.140

    else:
        return None

    if random.random() > prob:
        return None

    miasto = get_random_valid_city(region.region_id)

    if not miasto:
        return None

    victims = random.randint(*victims_range)

    return Zdarzenie(
        zdarzenie_typ="zamieszki_spol",
        panstwo_id=region.panstwo_id,
        region_id=region.region_id,
        miasto_id=miasto.miasto_id,
        skala=scale,
        ilosc_ofiar=victims,
        data_rzeczywista=datetime.now(),
        data_entenda=target_date
    )

#----------------------------------------------------------#

def try_generate_terror_attack(region, target_date):

    if cooldown_block("atak_terrorystyczny", region.region_id, target_date):
        return None

    sp = Spoleczenstwo.query.filter_by(
        panstwo_id=region.panstwo_id
    ).first()

    if not sp:
        return None

    wspol_terroru = (
        (sp.radykalizacja_spoleczna or 0)
        + (sp.napiecia_religijne or 0)
        + (sp.napiecia_etniczne or 0)
        + (sp.napiecia_klasowe or 0)
        + (sp.przestepczosc or 0)
        + (100 - (sp.zaufanie_do_wladzy or 0))
        + (100 - (sp.spojnosc_spoleczna or 0))
    ) / 100

    if 3.1 <= wspol_terroru <= 3.5:
        scale = 1
        victims_range = (0, 3)
        prob = 0.001

    elif 3.6 <= wspol_terroru <= 4.0:
        scale = 2
        victims_range = (4, 10)
        prob = 0.002

    elif 4.1 <= wspol_terroru <= 4.5:
        scale = 3
        victims_range = (11, 18)
        prob = 0.0025

    elif 4.6 <= wspol_terroru <= 5.0:
        scale = 4
        victims_range = (19, 50)
        prob = 0.0025

    elif 5.1 <= wspol_terroru <= 7.0:
        scale = 5
        victims_range = (20, 200)
        prob = 0.005

    else:
        return None

    if random.random() > prob:
        return None

    miasto = get_random_valid_city(region.region_id)

    if not miasto:
        return None

    victims = random.randint(*victims_range)

    return Zdarzenie(
        zdarzenie_typ="atak_terrorystyczny",
        panstwo_id=region.panstwo_id,
        region_id=region.region_id,
        miasto_id=miasto.miasto_id,
        skala=scale,
        ilosc_ofiar=victims,
        data_rzeczywista=datetime.now(),
        data_entenda=target_date
    )

#----------------------------------------------------------#

def try_generate_new_law(region, target_date):

    stolica = (
        Miasto.query
        .filter_by(
            panstwo_id=region.panstwo_id,
            miasto_typ_id=1
        )
        .first()
    )

    if not stolica:
        print("[LAW] Brak stolicy")
        return None

    if stolica.region_id != region.region_id:
        print("[LAW] Nie jest regionem stołecznym")
        return None

    existing = (
        Zdarzenie.query
        .filter(Zdarzenie.zdarzenie_typ == "nowa_ustawa")
        .filter(Zdarzenie.panstwo_id == region.panstwo_id)
        .filter(
            Zdarzenie.data_entenda >= target_date - timedelta(days=15),
            Zdarzenie.data_entenda <= target_date + timedelta(days=15)
        )
        .first()
    )

    if existing:
        print("[LAW] Cooldown")
        return None

    sp = Spoleczenstwo.query.filter_by(
        panstwo_id=region.panstwo_id
    ).first()

    if not sp:
        print("[LAW] Brak społeczeństwa")
        return None

    regiony = Region.query.filter_by(
        panstwo_id=region.panstwo_id
    ).all()

    # ==========================================
    # ŚREDNIE INFRASTRUKTURY PAŃSTWA
    # ==========================================

    kolej_values = [
        r.region_stan_infra_kolejowej
        for r in regiony
        if r.region_stan_infra_kolejowej is not None
    ]

    drogi_values = [
        r.region_stan_infra_drogowej
        for r in regiony
        if r.region_stan_infra_drogowej is not None
    ]

    energia_values = [
        r.region_stan_infra_energetycznej
        for r in regiony
        if r.region_stan_infra_energetycznej is not None
    ]

    mieszkania_values = [
        r.region_stan_infra_mieszkalnej
        for r in regiony
        if r.region_stan_infra_mieszkalnej is not None
    ]

    porty_values = [
        r.region_stan_infra_portowej
        for r in regiony
        if (
            r.region_polozenie_id is not None
            and r.region_polozenie_id != 1
            and r.region_stan_infra_portowej is not None
        )
    ]

    degradacja_values = [
        r.region_degradacja_srodowiska
        for r in regiony
        if r.region_degradacja_srodowiska is not None
    ]

    degradacja_avg = (
        round(sum(degradacja_values) / len(degradacja_values), 1)
        if degradacja_values else None
    )

    zanieczyszczenie_values = [
        r.region_zanieczyszczenie_powietrza
        for r in regiony
        if r.region_zanieczyszczenie_powietrza is not None
    ]

    zanieczyszczenie_avg = (
        round(sum(zanieczyszczenie_values) / len(zanieczyszczenie_values), 1)
        if zanieczyszczenie_values else None
    )

    infra_kolejowa_avg = (
        round(sum(kolej_values) / len(kolej_values), 1)
        if kolej_values else None
    )

    infra_drogowa_avg = (
        round(sum(drogi_values) / len(drogi_values), 1)
        if drogi_values else None
    )

    infra_energetyczna_avg = (
        round(sum(energia_values) / len(energia_values), 1)
        if energia_values else None
    )

    infra_mieszkalna_avg = (
        round(sum(mieszkania_values) / len(mieszkania_values), 1)
        if mieszkania_values else None
    )

    infra_portowa_avg = (
        round(sum(porty_values) / len(porty_values), 1)
        if porty_values else None
    )

    # ==========================================
    # ŚREDNI PRZYROST NATURALNY PAŃSTWA
    # ==========================================

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
        przyrost_avg = round(
            (
                sum(miasto_values) / len(miasto_values)
                +
                sum(wies_values) / len(wies_values)
            ) / 2,
            2
        )
    else:
        przyrost_avg = None

    wspol_reform = (
        (sp.zaufanie_do_wladzy or 0)
        + (sp.spojnosc_spoleczna or 0)
    ) / 100

    if wspol_reform <= 0.8:
        print(f"[LAW] Współczynnik reform = {wspol_reform}")
        return None

    if random.random() > 0.005:
        print("[LAW] Nie trafiono losowania")
        return None
    
    possible_variants = []

    # ===================================================
    # WARIANTY BEZ KRYTERIÓW
    # ===================================================

    possible_variants.append("NU005")
    possible_variants.append("NU006")
    possible_variants.append("NU007")
    possible_variants.append("NU008")
    possible_variants.append("NU011")

    # ===================================================
    # KRYTERIA SPOŁECZNE
    # ===================================================

    if (sp.przestepczosc or 0) > 50 \
            and (sp.spozycie_alkoholu or 0) > 60:
        possible_variants.append("NU018")

    if (sp.otwartosc_spoleczna or 0) > 70:
        possible_variants.append("NU001")

    if (sp.otwartosc_spoleczna or 0) > 70:
        possible_variants.append("NU002")

    if (sp.otwartosc_spoleczna or 0) > 75:
        possible_variants.append("NU003")
    
    if (sp.otwartosc_spoleczna or 0) > 75:
        possible_variants.append("NU004")

    if degradacja_avg is not None and degradacja_avg > 40:
        possible_variants.append("NU007")

    if degradacja_avg is not None and degradacja_avg > 40:
        possible_variants.append("NU009")

    if degradacja_avg is not None and degradacja_avg > 40:
        possible_variants.append("NU010")
    
    if infra_kolejowa_avg is not None and infra_kolejowa_avg < 50:
        possible_variants.append("NU020")
    
    if infra_drogowa_avg is not None and infra_drogowa_avg < 50:
        possible_variants.append("NU021")
    
    if infra_energetyczna_avg is not None and infra_energetyczna_avg < 50:
        possible_variants.append("NU022")
    
    if infra_portowa_avg is not None and infra_portowa_avg < 50:
        possible_variants.append("NU023")
    
    if infra_mieszkalna_avg is not None and infra_mieszkalna_avg < 50:
        possible_variants.append("NU024")
    
    if przyrost_avg is not None and przyrost_avg < -0.10:
        possible_variants.append("NU025")

    if not possible_variants:
        print("[LAW] Brak wariantów")
        return None

    variant = random.choice(possible_variants)

    existing = (
        Zdarzenie.query
        .filter_by(
            zdarzenie_typ="nowa_ustawa",
            panstwo_id=region.panstwo_id,
            wariant=variant
        )
        .filter(
            Zdarzenie.data_entenda >= target_date - timedelta(days=365)
        )
        .first()
    )

    if existing:
        print(f"[LAW] Wariant {variant} był już w ostatnim roku")
        return None

    stolica = (
        Miasto.query
        .filter_by(
            panstwo_id=region.panstwo_id,
            miasto_typ_id=1
        )
        .first()
    )

    return Zdarzenie(
        zdarzenie_typ="nowa_ustawa",
        panstwo_id=region.panstwo_id,
        region_id=stolica.region_id,
        miasto_id=stolica.miasto_id,
        skala=None,
        ilosc_ofiar=0,
        data_rzeczywista=datetime.now(),
        data_entenda=target_date,
        wariant=variant
    )

#----------------------------------------------------------#

def try_generate_social_protest(region, target_date):

    if cooldown_block("protest_spol", region.region_id, target_date):
        return None

    sp = Spoleczenstwo.query.filter_by(
        panstwo_id=region.panstwo_id
    ).first()

    if not sp:
        return None

    wspol_stabil_spolecznej = (
        (sp.stabilnosc_spoleczna or 0)
        + (sp.zadowolenie_spoleczne or 0)
        + (sp.zaufanie_do_wladzy or 0)
    ) / 100

    if 2.3 <= wspol_stabil_spolecznej <= 2.4:
        scale = 1

    elif 2.1 <= wspol_stabil_spolecznej <= 2.2:
        scale = 2

    elif 1.8 <= wspol_stabil_spolecznej <= 2.0:
        scale = 3

    elif 1.7 <= wspol_stabil_spolecznej <= 1.8:
        scale = 4

    elif 1.5 <= wspol_stabil_spolecznej <= 1.6:
        scale = 5

    else:
        return None

    prob = 0.005

    if random.random() > prob:
        return None

    miasto = get_random_valid_city(region.region_id)

    if not miasto:
        return None

    return Zdarzenie(
        zdarzenie_typ="protest_spol",
        panstwo_id=region.panstwo_id,
        region_id=region.region_id,
        miasto_id=miasto.miasto_id,
        skala=scale,
        ilosc_ofiar=0,
        data_rzeczywista=datetime.now(),
        data_entenda=target_date
    )

#----------------------------------------------------------#

def try_generate_high_pollution(region, target_date):

    p = region.region_zanieczyszczenie_powietrza or 0

    if p < 10:
        return None

    if cooldown_block("wys_zaniecz_powietrza", region.region_id, target_date):
        return None

    if p >= 10 and p <= 30:
        prob = 0.001
        scale = 1

    elif p > 30 and p <= 50:
        prob = 0.005
        scale = 2

    elif p > 50 and p <= 70:
        prob = 0.025
        scale = 3

    elif p > 70 and p <= 85:
        prob = 0.1
        scale = 4

    else:
        prob = 0.15
        scale = 5

    if random.random() > prob:
        return None

    victims = 0

    miasto = get_random_valid_city(region.region_id)

    if not miasto:
        return None

    return Zdarzenie(
        zdarzenie_typ="wys_zaniecz_powietrza",
        panstwo_id=region.panstwo_id,
        region_id=region.region_id,
        miasto_id=miasto.miasto_id,
        skala=scale,
        ilosc_ofiar=victims,
        data_rzeczywista=datetime.now(),
        data_entenda=target_date
    )

#----------------------------------------------------------#

def try_generate_new_invention(region, target_date):

    sp = Spoleczenstwo.query.filter_by(
        panstwo_id=region.panstwo_id
    ).first()

    if not sp:
        return None
	
    education = sp.poziom_edukacji or 0

    if education < 40:
        return None

    if cooldown_block("nowy_wynalazek", region.region_id, target_date):
        return None

    if education > 40 and education <= 50:
        prob = 0.0001
        scale = 1

    elif education > 50 and education <= 60:
        prob = 0.0005
        scale = 2
       
    elif education > 60 and education <= 70:
        prob = 0.0025
        scale = 3
        
    elif education > 70 and education <= 85:
        prob = 0.01
        scale = 4
        
    else:
        prob = 0.015
        scale = 5
        
    if random.random() > prob:
        return None

    victims = 0

    miasto = get_random_valid_city(region.region_id)

    if not miasto:
        return None

    return Zdarzenie(
        zdarzenie_typ="nowy_wynalazek",
        panstwo_id=region.panstwo_id,
        region_id=region.region_id,
        miasto_id=miasto.miasto_id,
        skala=scale,
        ilosc_ofiar=victims,
        data_rzeczywista=datetime.now(),
        data_entenda=target_date
    )

# =====================================================
# MARSZ PATRIOTYCZNY
# =====================================================

def try_generate_patriotic_march(region, target_date):

    sp = Spoleczenstwo.query.filter_by(
        panstwo_id=region.panstwo_id
    ).first()

    if not sp:
        return None
	
    toz_narod = sp.tozsamosc_narodowa or 0

    if toz_narod == 0:
        return None

    if cooldown_block("marsz_patriotyczny", region.region_id, target_date):
        return None

    if toz_narod > 0 and toz_narod <= 20:
        prob = 0.0005
        scale = 1

    elif toz_narod > 20 and toz_narod <= 40:
        prob = 0.001
        scale = 2
       
    elif toz_narod > 40 and toz_narod <= 60:
        prob = 0.0015
        scale = 3
        
    elif toz_narod > 60 and toz_narod <= 80:
        prob = 0.002
        scale = 4
        
    else:
        prob = 0.003
        scale = 5
        
    if random.random() > prob:
        return None

    victims = 0

    miasto = get_random_valid_city(region.region_id)

    if not miasto:
        return None

    return Zdarzenie(
        zdarzenie_typ="marsz_patriotyczny",
        panstwo_id=region.panstwo_id,
        region_id=region.region_id,
        miasto_id=miasto.miasto_id,
        skala=scale,
        ilosc_ofiar=victims,
        data_rzeczywista=datetime.now(),
        data_entenda=target_date
    )

#----------------------------------------------------------#

def try_generate_tsunami(region, target_date):

    sej = region.region_sejsmicznosc or 0

    if sej < 25:
        return None

    if cooldown_block("tsunami", region.region_id, target_date):
        return None
		
    if region.region_polozenie_id != 2:
	    return None

    if sej > 25 and sej <= 35:
        prob = 0.001
        scale = 1
        victims_range = (0,10)

    elif sej > 35 and sej <= 50:
        prob = 0.003
        scale = 2
        victims_range = (0,50)

    elif sej > 50 and sej <= 65:
        prob = 0.005
        scale = 3
        victims_range = (25,500)

    elif sej > 65 and sej <= 75:
        prob = 0.008
        scale = 4
        victims_range = (350,5000)

    else:
        prob = 0.004
        scale = 5
        victims_range = (1000,25000)

    if random.random() > prob:
        return None

    victims = compute_victims(region, victims_range, severity="high")

    miasto = get_random_valid_city(region.region_id)

    if not miasto:
        return None

    return Zdarzenie(
        zdarzenie_typ="tsunami",
        panstwo_id=region.panstwo_id,
        region_id=region.region_id,
        miasto_id=miasto.miasto_id,
        skala=scale,
        ilosc_ofiar=victims,
        data_rzeczywista=datetime.now(),
        data_entenda=target_date
    )
