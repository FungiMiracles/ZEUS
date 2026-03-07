import random
from datetime import datetime, timedelta
from engine.clock import get_current_entenda_date, ENTENDA_START
from sqlalchemy import extract
from apscheduler.schedulers.background import BackgroundScheduler

from extensions import db
from models import Zdarzenie, Region
from engine.selectors import select_regions

from engine.effects import (
    apply_earthquake_effect,
    apply_train_disaster_effect,
    apply_road_disaster_effect
)

MAX_EVENTS_PER_MONTH = 200

def start_event_scheduler(app):

    scheduler = BackgroundScheduler()

    def job():
        with app.app_context():
            print("[ZEUS] scheduler tick")
            generate_events()
            db.session.commit()

    scheduler.add_job(job, "interval", seconds=30)

    scheduler.start()

def generate_events():

    current_entenda = get_current_entenda_date()

    last_generated = get_last_generated_entenda_date()

    generated_total = 0

    while last_generated < current_entenda:

        created = generate_events_for_day(last_generated)

        generated_total += created

        last_generated += timedelta(days=1)

    print(f"[ZEUS] wygenerowano {generated_total} zdarzeń")

    return generated_total

def generate_events_for_day(target_date):

    month_events = get_month_event_count(target_date)

    if month_events >= MAX_EVENTS_PER_MONTH:
        return 0

    remaining = MAX_EVENTS_PER_MONTH - month_events

    events_created = 0

    regions = select_regions(30)

    for region in regions:

        if events_created >= remaining:
            break

        event = try_generate_earthquake(region, target_date)

        if event:
            apply_earthquake_effect(region, event.skala, event.ilosc_ofiar)

            db.session.add(event)

            events_created += 1
            continue

        event = try_generate_train_disaster(region, target_date)

        if event:
            apply_train_disaster_effect(region, event.skala, event.ilosc_ofiar)

            db.session.add(event)

            events_created += 1
            continue

        event = try_generate_road_disaster(region, target_date)

        if event:
            apply_road_disaster_effect(region, event.skala, event.ilosc_ofiar)

            db.session.add(event)

            events_created += 1

    return events_created

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

def try_generate_earthquake(region, target_date):

    s = region.region_sejsmicznosc or 0

    if s <= 0:
        return None

    if cooldown_block("trzesienie_ziemi", region.region_id, target_date):
        return None

    if s < 20:
        prob = 1
        scale = 1
        victims_range = (0,5)

    elif s < 40:
        prob = 2
        scale = 2
        victims_range = (6,30)

    elif s < 60:
        prob = 3
        scale = 3
        victims_range = (31,100)

    elif s < 80:
        prob = 4
        scale = 4
        victims_range = (101,1000)

    else:
        prob = 5
        scale = 5
        victims_range = (1001,10000)

    if random.random() > prob:
        return None

    victims = compute_victims(region, victims_range)

    return Zdarzenie(
        zdarzenie_typ="trzesienie_ziemi",
        region_id=region.region_id,
        skala=scale,
        ilosc_ofiar=victims,
        data_rzeczywista=datetime.utcnow(),
        data_entenda=target_date
    )

def try_generate_train_disaster(region, target_date):

    infra = region.region_stan_infra_kolejowej or 100

    if infra >= 90:
        return None

    if cooldown_block("katastrofa_kolejowa", region.region_id, target_date):
        return None

    if infra > 80:
        prob = 1
        scale = 1
        victims_range = (0,1)

    elif infra > 65:
        prob = 2
        scale = 2
        victims_range = (2,10)

    elif infra > 50:
        prob = 3
        scale = 3
        victims_range = (11,30)

    elif infra > 30:
        prob = 4
        scale = 4
        victims_range = (31,50)

    else:
        prob = 0.0005
        scale = 5
        victims_range = (51,200)

    if random.random() > prob:
        return None

    victims = compute_victims(region, victims_range)

    return Zdarzenie(
        zdarzenie_typ="katastrofa_kolejowa",
        region_id=region.region_id,
        skala=scale,
        ilosc_ofiar=victims,
        data_rzeczywista=datetime.utcnow(),
        data_entenda=target_date
    )

def try_generate_road_disaster(region, target_date):

    infra = region.region_stan_infra_drogowej or 100

    if infra >= 90:
        return None

    if cooldown_block("katastrofa_w_ruchu_ladowym", region.region_id, target_date):
        return None

    if infra > 80:
        prob = 1
        scale = 1
        victims_range = (0,1)

    elif infra > 65:
        prob = 1
        scale = 2
        victims_range = (2,5)

    elif infra > 50:
        prob = 1
        scale = 3
        victims_range = (5,10)

    elif infra > 30:
        prob = 1
        scale = 4
        victims_range = (11,15)

    else:
        prob = 1
        scale = 5
        victims_range = (16,20)

    if random.random() > prob:
        return None

    victims = compute_victims(region, victims_range)

    return Zdarzenie(
        zdarzenie_typ="katastrofa_w_ruchu_ladowym",
        region_id=region.region_id,
        skala=scale,
        ilosc_ofiar=victims,
        data_rzeczywista=datetime.utcnow(),
        data_entenda=target_date
    )

def compute_victims(region, victims_range):

    base = random.randint(*victims_range)

    pop = region.region_populacja or 0

    factor = (pop / 1_000_000) ** 0.65

    victims = int(base * factor)

    return max(victims, 0)

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

def get_month_event_count(date):

    return (
        db.session.query(Zdarzenie)
        .filter(extract("year", Zdarzenie.data_entenda) == date.year)
        .filter(extract("month", Zdarzenie.data_entenda) == date.month)
        .count()
    )