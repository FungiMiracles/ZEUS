import random
from datetime import datetime, timedelta
from engine.clock import get_current_entenda_date, ENTENDA_START
from sqlalchemy import extract
from apscheduler.schedulers.background import BackgroundScheduler
import calendar

from extensions import db
from models import Zdarzenie, Region, Panstwo, Miasto
from engine.selectors import select_regions

from engine.template_selector import select_template
from engine.event_renderer import render_event_description

from engine.effects import (
    apply_earthquake_effect,
    apply_train_disaster_effect,
    apply_road_disaster_effect,
    apply_flood_effect,
    apply_avalanche_effect,
    apply_volcano_effect,
    apply_coldwave_effect,
    apply_heatwave_effect
)

#----------------------------------------------------------#

MAX_EVENTS_PER_MONTH = 20

MAX_EVENTS_PER_REGION_PER_MONTH = 2

#----------------------------------------------------------#

def start_event_scheduler(app):

    scheduler = BackgroundScheduler()

    def job():
        with app.app_context():
            print("[ZEUS] scheduler tick")
            generate_events()

    scheduler.add_job(job, "interval", minutes=30)

    scheduler.start()

#----------------------------------------------------------#

def generate_events():

    current_entenda = get_current_entenda_date()

    last_generated = get_last_generated_entenda_date()

    generated_total = 0

    current_month = datetime(last_generated.year, last_generated.month, 1)

    end_month = datetime(current_entenda.year, current_entenda.month, 1)

    while current_month <= end_month:

        created = generate_events_for_month(current_month)

        generated_total += created

        # przejdź do następnego miesiąca
        if current_month.month == 12:
            current_month = datetime(current_month.year + 1, 1, 1)
        else:
            current_month = datetime(current_month.year, current_month.month + 1, 1)

    print(f"[ZEUS] wygenerowano {generated_total} zdarzeń")

    return generated_total

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
            (try_generate_heatwave, apply_heatwave_effect)
        ]

        random.shuffle(events)

        for generator, effect in events:

            event = generator(region, random_day_in_month(month_date))

            if event and region_events < MAX_EVENTS_PER_REGION_PER_MONTH and events_created < remaining:

                template = select_template(event.zdarzenie_typ, event.skala)

                if template:
                    event.opis_szablon_id = template.szablon_id
                    event.opis_wygenerowany = render_event_description(event, template.tresc)
                else:
                    event.opis_wygenerowany = None

                effect(region, event.skala, event.ilosc_ofiar)

                db.session.add(event)

                events_created += 1
                region_events += 1

                if region_events >= MAX_EVENTS_PER_REGION_PER_MONTH:
                    break

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

    # liczba dni w miesiącu
    days = calendar.monthrange(month_date.year, month_date.month)[1]

    # jeżeli to bieżący miesiąc symulacji
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

def try_generate_earthquake(region, target_date):

    s = region.region_sejsmicznosc or 0

    if s <= 0:
        return None

    if cooldown_block("trzesienie_ziemi", region.region_id, target_date):
        return None

    if s < 20:
        prob = 0.001
        scale = 1
        victims_range = (0,5)

    elif s < 40:
        prob = 0.002
        scale = 2
        victims_range = (6,30)

    elif s < 60:
        prob = 0.003
        scale = 3
        victims_range = (31,100)

    elif s < 80:
        prob = 0.0035
        scale = 4
        victims_range = (101,1000)

    else:
        prob = 0.004
        scale = 5
        victims_range = (1001,10000)

    if random.random() > prob:
        return None

    victims = compute_victims(region, victims_range)

    miasto = (
        Miasto.query
        .filter_by(region_id=region.region_id)
        .order_by(db.func.rand())
        .first()
    )

    return Zdarzenie(
        zdarzenie_typ="trzesienie_ziemi",
        panstwo_id=region.panstwo_id,
        region_id=region.region_id,
        miasto_id=miasto.miasto_id if miasto else None,
        skala=scale,
        ilosc_ofiar=victims,
        data_rzeczywista=datetime.utcnow(),
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
        prob = 0.0003
        scale = 1
        victims_range = (0,1)

    elif infra > 65:
        prob = 0.0008
        scale = 2
        victims_range = (2,10)

    elif infra > 50:
        prob = 0.0025
        scale = 3
        victims_range = (11,30)

    elif infra > 30:
        prob = 0.003
        scale = 4
        victims_range = (31,50)

    else:
        prob = 0.005
        scale = 5
        victims_range = (51,200)

    if random.random() > prob:
        return None

    victims = compute_victims(region, victims_range)

    miasto = (
        Miasto.query
        .filter_by(region_id=region.region_id)
        .order_by(db.func.rand())
        .first()
    )

    return Zdarzenie(
        zdarzenie_typ="katastrofa_kolejowa",
        panstwo_id=region.panstwo_id,
        region_id=region.region_id,
        miasto_id=miasto.miasto_id if miasto else None,
        skala=scale,
        ilosc_ofiar=victims,
        data_rzeczywista=datetime.utcnow(),
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
        prob = 0.0005
        scale = 1
        victims_range = (0,1)

    elif infra > 65:
        prob = 0.0015
        scale = 2
        victims_range = (2,5)

    elif infra > 50:
        prob = 0.0025
        scale = 3
        victims_range = (5,10)

    elif infra > 30:
        prob = 0.003
        scale = 4
        victims_range = (11,15)

    else:
        prob = 0.005
        scale = 5
        victims_range = (16,20)

    if random.random() > prob:
        return None

    victims = compute_victims(region, victims_range)

    miasto = (
        Miasto.query
        .filter_by(region_id=region.region_id)
        .order_by(db.func.rand())
        .first()
    )

    return Zdarzenie(
        zdarzenie_typ="katastrofa_w_ruchu_ladowym",
        panstwo_id=region.panstwo_id,
        region_id=region.region_id,
        miasto_id=miasto.miasto_id if miasto else None,
        skala=scale,
        ilosc_ofiar=victims,
        data_rzeczywista=datetime.utcnow(),
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
        victims_range = (16,80)

    elif s < 80:
        prob = 0.0035
        scale = 4
        victims_range = (81,300)

    else:
        prob = 0.004
        scale = 5
        victims_range = (301,950)

    if random.random() > prob:
        return None

    victims = compute_victims(region, victims_range)

    miasto = (
        Miasto.query
        .filter_by(region_id=region.region_id)
        .order_by(db.func.rand())
        .first()
    )

    return Zdarzenie(
        zdarzenie_typ="powodz",
        panstwo_id=region.panstwo_id,
        region_id=region.region_id,
        miasto_id=miasto.miasto_id if miasto else None,
        skala=scale,
        ilosc_ofiar=victims,
        data_rzeczywista=datetime.utcnow(),
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
        victims_range = (2,10)

    elif s < 60:
        prob = 0.002
        scale = 3
        victims_range = (11,15)

    elif s < 80:
        prob = 0.003
        scale = 4
        victims_range = (16,20)

    else:
        prob = 0.0035
        scale = 5
        victims_range = (21,30)

    if random.random() > prob:
        return None

    victims = compute_victims(region, victims_range)

    miasto = (
        Miasto.query
        .filter_by(region_id=region.region_id)
        .order_by(db.func.rand())
        .first()
    )

    return Zdarzenie(
        zdarzenie_typ="lawina",
        panstwo_id=region.panstwo_id,
        region_id=region.region_id,
        miasto_id=miasto.miasto_id if miasto else None,
        skala=scale,
        ilosc_ofiar=victims,
        data_rzeczywista=datetime.utcnow(),
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
        prob = 0.0005
        scale = 1
        victims_range = (0,5)

    elif s < 40:
        prob = 0.001
        scale = 2
        victims_range = (6,15)

    elif s < 60:
        prob = 0.0015
        scale = 3
        victims_range = (16,25)

    elif s < 80:
        prob = 0.0025
        scale = 4
        victims_range = (26,45)

    else:
        prob = 0.003
        scale = 5
        victims_range = (46,60)

    if random.random() > prob:
        return None

    victims = compute_victims(region, victims_range)

    miasto = (
        Miasto.query
        .filter_by(region_id=region.region_id)
        .order_by(db.func.rand())
        .first()
    )

    return Zdarzenie(
        zdarzenie_typ="erupcja_wulkanu",
        panstwo_id=region.panstwo_id,
        region_id=region.region_id,
        miasto_id=miasto.miasto_id if miasto else None,
        skala=scale,
        ilosc_ofiar=victims,
        data_rzeczywista=datetime.utcnow(),
        data_entenda=target_date
    )

#----------------------------------------------------------#

def try_generate_coldwave(region, target_date):

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
        victims_range = (11,50)

    else:
        prob = 0.003
        scale = 5
        victims_range = (51,200)

    if random.random() > prob:
        return None

    victims = compute_victims(region, victims_range)

    miasto = (
        Miasto.query
        .filter_by(region_id=region.region_id)
        .order_by(db.func.rand())
        .first()
    )

    return Zdarzenie(
        zdarzenie_typ="fala_mrozu",
        panstwo_id=region.panstwo_id,
        region_id=region.region_id,
        miasto_id=miasto.miasto_id if miasto else None,
        skala=scale,
        ilosc_ofiar=victims,
        data_rzeczywista=datetime.utcnow(),
        data_entenda=target_date
    )

#----------------------------------------------------------#

def try_generate_heatwave(region, target_date):

    s = region.region_ryzyko_upalu or 0

    if s <= 0:
        return None

    if cooldown_block("fala_upalu", region.region_id, target_date):
        return None

    if s < 20:
        prob = 0.0005
        scale = 1
        victims_range = (0,0)

    elif s < 40:
        prob = 0.001
        scale = 2
        victims_range = (1,5)

    elif s < 60:
        prob = 0.0015
        scale = 3
        victims_range = (6,15)

    elif s < 80:
        prob = 0.0025
        scale = 4
        victims_range = (16,30)

    else:
        prob = 0.003
        scale = 5
        victims_range = (31,70)

    if random.random() > prob:
        return None

    victims = compute_victims(region, victims_range)

    miasto = (
        Miasto.query
        .filter_by(region_id=region.region_id)
        .order_by(db.func.rand())
        .first()
    )

    return Zdarzenie(
        zdarzenie_typ="fala_upalu",
        panstwo_id=region.panstwo_id,
        region_id=region.region_id,
        miasto_id=miasto.miasto_id if miasto else None,
        skala=scale,
        ilosc_ofiar=victims,
        data_rzeczywista=datetime.utcnow(),
        data_entenda=target_date
    )

#----------------------------------------------------------#

def compute_victims(region, victims_range):

    base = random.randint(*victims_range)

    pop = region.region_populacja or 0

    factor = (pop / 1_000_000) ** 0.65

    victims = int(base * factor)

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

    from engine.clock import ENTENDA_START
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