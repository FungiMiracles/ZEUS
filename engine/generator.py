import random
from datetime import datetime, timedelta

from extensions import db
from models import Zdarzenie, Region
from engine.selectors import select_regions

from engine.effects import (
    apply_earthquake_effect,
    apply_train_disaster_effect,
    apply_road_disaster_effect
)

MAX_EVENTS_PER_MONTH = 12

def generate_events():

    events_created = 0

    regions = select_regions(30)

    for region in regions:

        if events_created >= MAX_EVENTS_PER_MONTH:
            break

        event = try_generate_earthquake(region)

        if event:
            apply_earthquake_effect(region, event.skala, event.ilosc_ofiar)
            db.session.add(event)
            events_created += 1
            continue

        event = try_generate_train_disaster(region)

        if event:
            apply_train_disaster_effect(region, event.skala, event.ilosc_ofiar)
            db.session.add(event)
            events_created += 1
            continue

        event = try_generate_road_disaster(region)

        if event:
            apply_road_disaster_effect(region, event.skala, event.ilosc_ofiar)
            db.session.add(event)
            events_created += 1
            continue

    print(f"[ZEUS] wygenerowano {events_created} zdarzeń")

    return events_created

def cooldown_block(event_type, region_id):

    six_months = datetime.utcnow() - timedelta(days=180)

    existing = (
        Zdarzenie.query
        .filter(Zdarzenie.zdarzenie_typ == event_type)
        .filter(Zdarzenie.region_id == region_id)
        .filter(Zdarzenie.data_rzeczywista >= six_months)
        .first()
    )

    return existing is not None

def try_generate_earthquake(region):

    s = region.region_sejsmicznosc or 0

    if s <= 0:
        return None

    if cooldown_block("trzesienie_ziemi", region.region_id):
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

    return Zdarzenie(
        zdarzenie_typ="trzesienie_ziemi",
        region_id=region.region_id,
        skala=scale,
        ilosc_ofiar=victims,
        data_rzeczywista=datetime.utcnow()
    )

def try_generate_train_disaster(region):

    infra = region.region_stan_infra_kolejowej or 100

    if infra >= 90:
        return None

    if cooldown_block("katastrofa_kolejowa", region.region_id):
        return None

    if infra > 80:
        prob = 0.005
        scale = 1
        victims_range = (0,1)

    elif infra > 65:
        prob = 0.003
        scale = 2
        victims_range = (2,10)

    elif infra > 50:
        prob = 0.0025
        scale = 3
        victims_range = (11,30)

    elif infra > 30:
        prob = 0.0015
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
        data_rzeczywista=datetime.utcnow()
    )

def try_generate_road_disaster(region):

    infra = region.region_stan_infra_drogowej or 100

    if infra >= 90:
        return None

    if cooldown_block("katastrofa_w_ruchu_ladowym", region.region_id):
        return None

    if infra > 80:
        prob = 0.005
        scale = 1
        victims_range = (0,1)

    elif infra > 65:
        prob = 0.003
        scale = 2
        victims_range = (2,5)

    elif infra > 50:
        prob = 0.0025
        scale = 3
        victims_range = (5,10)

    elif infra > 30:
        prob = 0.0015
        scale = 4
        victims_range = (11,15)

    else:
        prob = 0.0005
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
        data_rzeczywista=datetime.utcnow()
    )

def compute_victims(region, victims_range):

    base = random.randint(*victims_range)

    pop = region.region_populacja or 0

    factor = (pop / 1_000_000) ** 0.65

    victims = int(base * factor)

    return max(victims, 0)