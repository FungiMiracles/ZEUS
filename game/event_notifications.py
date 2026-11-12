"""Tworzenie powiadomienia w transakcji generatora, bez własnego commit."""
from sqlalchemy import select
from sqlalchemy.orm import lazyload

from extensions import db
from game.event_models import GeneratedEventSnapshot
from game.forum_models import GameNotification
from game.models import GamePlayerCountry, GameUser, utc_now
from models import Panstwo, Region, RegionStateHistory, SpoleczenstwoStateHistory

REGION_EFFECTS = (
    ("Ludność", "ludnosc"), ("Drogi", "drogi"), ("Kolej", "kolej"),
    ("Energia", "energia"), ("Mieszkania", "mieszkania"), ("Porty", "porty"),
    ("Degradacja środowiska", "degradacja_srodowiska"),
    ("Zanieczyszczenie powietrza", "zanieczyszczenie_powietrza"),
)
SOCIAL_EFFECTS = (
    ("Stabilność", "stabilnosc"), ("Zadowolenie", "zadowolenie"),
    ("Nierówności", "nierownosci"), ("Edukacja", "edukacja"),
    ("Świadomość", "swiadomosc"), ("Zaufanie", "zaufanie"),
    ("Napięcia religijne", "napiecia_religijne"), ("Napięcia etniczne", "napiecia_etniczne"),
    ("Napięcia klasowe", "napiecia_klasowe"), ("Przestępczość", "przestepczosc"),
    ("Radykalizacja", "radykalizacja"), ("Spójność", "spojnosc"),
    ("Tożsamość", "tozsamosc"), ("Konserwatyzm", "konserwatyzm"),
    ("Otwartość", "otwartosc"), ("Spożycie alkoholu", "spozycie_alkoholu"),
    ("Spożycie narkotyków", "spozycie_narkotykow"), ("Zdrowie publiczne", "zdrowie_publiczne"),
)


def event_effects(event_id):
    totals = {}
    for model, fields in [(RegionStateHistory, REGION_EFFECTS), (SpoleczenstwoStateHistory, SOCIAL_EFFECTS)]:
        rows = db.session.scalars(select(model).where(model.event_id == event_id).options(lazyload("*"))).all()
        for row in rows:
            for label, field in fields:
                old, new = getattr(row, "old_" + field), getattr(row, "new_" + field)
                if old is not None and new is not None:
                    totals[label] = totals.get(label, 0) + (new - old)
    return [{"label": label, "value": int(value) if value == int(value) else float(value), "suffix": ""}
            for label, value in totals.items() if value != 0]


def queue_generated_event(event):
    db.session.flush()
    if db.session.scalar(select(GeneratedEventSnapshot.id).where(GeneratedEventSnapshot.source_event_id == event.zdarzenie_id)):
        return
    from game.paga_ai_actor import country_user_id
    owner = country_user_id(db.session,event.panstwo_id)
    if owner is None:
        return
    country_name = db.session.scalar(select(Panstwo.panstwo_nazwa).where(Panstwo.PANSTWO_ID == event.panstwo_id)) or ""
    region_name = db.session.scalar(select(Region.region_nazwa).where(Region.region_id == event.region_id)) or ""
    now = utc_now()
    snapshot = GeneratedEventSnapshot(
        source_event_id=event.zdarzenie_id, country_id=event.panstwo_id,
        country_name=country_name, region_name=region_name, event_type=event.zdarzenie_typ,
        content=event.opis_wygenerowany or f"Zdarzenie: {event.zdarzenie_typ}. Brak opisu zdarzenia.",
        effects=event_effects(event.zdarzenie_id), entenda_date=event.data_entenda, created_at=now,
    )
    db.session.add(snapshot)
    db.session.flush()
    db.session.add(GameNotification(user_id=owner, generated_event_id=snapshot.id,
                                    notification_type="GENERATED_EVENT", created_at=now))
