from datetime import datetime
from sqlalchemy.exc import IntegrityError
from extensions import db
from engine.clock import get_current_entenda_date
from models import (
    Panstwo,
    Gospodarka,
    PKBStateHistory,
    ZdarzeniaSystemowe,
    DictZdarzeniaSystemowe,
    PKBPCStateHistory,
    HistoriaPopulacjiPanstw,
    Spoleczenstwo,
    Region,
    Zdarzenie,
    ProcentWzrostuStateHistory
)

PKB_REGEN_SOURCE = "PKB_REGEN"
PKBPC_REGEN_SOURCE = "PKBPC_REGEN"

def _get_previous_population_snapshot(panstwo_id, entenda_date):
    """
    Pobiera ostatni snapshot populacji sprzed bieżącej daty Entendy.
    """
    return (
        HistoriaPopulacjiPanstw.query
        .filter(
            HistoriaPopulacjiPanstw.panstwo_id == panstwo_id,
            HistoriaPopulacjiPanstw.data_entenda < entenda_date
        )
        .order_by(
            HistoriaPopulacjiPanstw.data_entenda.desc(),
            HistoriaPopulacjiPanstw.id.desc()
        )
        .first()
    )

def _log_pkbpc_snapshot(entenda_date, event_def):
    log = ZdarzeniaSystemowe(
        zdarzenie_systemowe_id=event_def.zdarzenie_systemowe_id,
        data_entenda=entenda_date,
        data_rzeczywista=datetime.now(),
        opis="System ZEUS pomyślnie zapisał roczny snapshot PKB per capita wszystkich państw Entendy."
    )

    db.session.add(log)

def run_annual_pkbpc_snapshot():
    """
    Coroczny snapshot PKB per capita.
    Uruchamiany 31 grudnia po regeneracji populacji.
    """
    entenda_date = get_current_entenda_date()

    if entenda_date.month != 1 or entenda_date.day != 1:
        return

    event_def = (
        DictZdarzeniaSystemowe.query
        .filter_by(zdarzenie_systemowe_nazwa=PKBPC_SYSTEM_EVENT_KEY)
        .first()
    )

    if not event_def:
        raise RuntimeError(
            "Brak definicji zdarzenia systemowego 'regeneracja_pkbpc'."
        )

    try:
        panstwa = Panstwo.query.all()

        for panstwo in panstwa:
            if not panstwo.panstwo_PKB:
                continue

            if not panstwo.panstwo_populacja:
                continue

            old_population_snapshot = _get_previous_population_snapshot(
                panstwo.PANSTWO_ID,
                entenda_date
            )

            if not old_population_snapshot:
                continue

            old_population = old_population_snapshot.panstwo_populacja
            new_population = panstwo.panstwo_populacja

            if old_population <= 0 or new_population <= 0:
                continue

            old_pkbpc = round(panstwo.panstwo_PKB / old_population)
            new_pkbpc = round(panstwo.panstwo_PKB / new_population)

            history = PKBPCStateHistory(
                panstwo_id=panstwo.PANSTWO_ID,
                data_entenda=entenda_date,
                data_rzeczywista=datetime.now(),
                source=PKBPC_REGEN_SOURCE,
                event_id=None,
                old_pkbpc=old_pkbpc,
                new_pkbpc=new_pkbpc,
                change_delta=(new_pkbpc - old_pkbpc)
            )

            db.session.add(history)

        _log_pkbpc_snapshot(entenda_date, event_def)

        db.session.commit()

    except IntegrityError:
        db.session.rollback()
        raise

    except Exception:
        db.session.rollback()
        raise

# ============================================================
# WZROST PKB REGENERATION
# ============================================================

WZROST_REGEN_SOURCE_AFTER = "WZROST_REGEN"
WZROST_SYSTEM_EVENT_KEY = "regeneracja_wzrostu_pkb"

DISASTER_EVENT_TYPES = {
    "powodz",
    "trzesienie_ziemi",
    "przerwa_w_dost_prod",
    "fala_mrozu",
    "fala_upalu"
}

DISASTER_PENALTIES = {
    3: 0.15,
    4: 0.35,
    5: 0.65
}


def _get_growth_system_event_definition():
    return (
        DictZdarzeniaSystemowe.query
        .filter_by(zdarzenie_systemowe_nazwa=WZROST_SYSTEM_EVENT_KEY)
        .first()
    )

def _log_growth_regeneration(entenda_date, event_def):
    log = ZdarzeniaSystemowe(
        zdarzenie_systemowe_id=event_def.zdarzenie_systemowe_id,
        data_entenda=entenda_date,
        data_rzeczywista=datetime.now(),
        opis="System ZEUS pomyślnie dokonał roczne przeliczenie procentu wzrostu PKB wszystkich państw Entendy."
    )

    db.session.add(log)


def _calculate_infra_score(panstwo_id):
    regions = (
        Region.query
        .filter_by(panstwo_id=panstwo_id)
        .all()
    )

    region_scores = []

    for region in regions:
        values = [
            region.region_poziom_skomunikowania,
            region.region_stan_infra_kolejowej,
            region.region_stan_infra_drogowej,
            region.region_stan_infra_energetycznej,
            region.region_stan_infra_portowej
        ]

        if any(v is None for v in values):
            continue

        region_avg = sum(values) / 5.0
        region_scores.append(region_avg)

    if not region_scores:
        return None

    avg_infra = sum(region_scores) / len(region_scores)

    return avg_infra / 100.0


def _calculate_social_score(spoleczenstwo):
    required = [
        spoleczenstwo.stabilnosc_spoleczna,
        spoleczenstwo.poziom_edukacji,
        spoleczenstwo.przestepczosc
    ]

    if any(v is None for v in required):
        return None

    return (
        (
            spoleczenstwo.stabilnosc_spoleczna +
            spoleczenstwo.poziom_edukacji -
            spoleczenstwo.przestepczosc
        ) / 200.0
    )


def _calculate_disaster_penalty(panstwo_id, entenda_date):
    events = (
        Zdarzenie.query
        .filter(
            Zdarzenie.panstwo_id == panstwo_id,
            db.extract("year", Zdarzenie.data_entenda) == entenda_date.year,
            Zdarzenie.zdarzenie_typ.in_(DISASTER_EVENT_TYPES)
        )
        .all()
    )

    penalty = 0.0

    for event in events:
        if event.skala is None:
            continue

        if event.skala < 3:
            continue

        if event.skala >= 5:
            penalty += DISASTER_PENALTIES[5]
        elif event.skala == 4:
            penalty += DISASTER_PENALTIES[4]
        elif event.skala == 3:
            penalty += DISASTER_PENALTIES[3]

    return min(penalty, 3.0)


def _save_growth_snapshot(
    panstwo_id,
    entenda_date,
    source,
    old_growth,
    new_growth
):
    history = ProcentWzrostuStateHistory(
        panstwo_id=panstwo_id,
        data_entenda=entenda_date,
        data_rzeczywista=datetime.now(),
        source=source,
        event_id=None,
        old_wzrost=old_growth,
        new_wzrost=new_growth,
        change_delta=round(new_growth - old_growth, 4)
    )

    db.session.add(history)

def run_annual_growth_regeneration():
    """
    Coroczna regeneracja wzrostu PKB.
    Uruchamiana wyłącznie 29 grudnia czasu Entendy.
    """
    entenda_date = get_current_entenda_date()

    if entenda_date.month != 12 or entenda_date.day != 29:
        return

    event_def = _get_growth_system_event_definition()

    if not event_def:
        raise RuntimeError(
            "Brak definicji zdarzenia systemowego "
            "'regeneracja_wzrostu_pkb'."
        )

    try:
        panstwa = Panstwo.query.all()

        for panstwo in panstwa:
            gospodarka = (
                Gospodarka.query
                .filter_by(panstwo_id=panstwo.PANSTWO_ID)
                .first()
            )

            if not gospodarka:
                continue

            if gospodarka.wzrost_pkb is None:
                continue

            spoleczenstwo = (
                Spoleczenstwo.query
                .filter_by(panstwo_id=panstwo.PANSTWO_ID)
                .first()
            )

            if not spoleczenstwo:
                continue

            infra = _calculate_infra_score(panstwo.PANSTWO_ID)
            if infra is None:
                continue

            social = _calculate_social_score(spoleczenstwo)
            if social is None:
                continue

            current_growth = float(gospodarka.wzrost_pkb)

            target_growth = (infra * 4.0) + (social * 2.0)

            base_growth = (
                current_growth +
                ((target_growth - current_growth) * 0.15)
            )

            penalty = _calculate_disaster_penalty(
                panstwo.PANSTWO_ID,
                entenda_date
            )

            final_growth = round(base_growth - penalty, 2)

            gospodarka.wzrost_pkb = final_growth

            _save_growth_snapshot(
                panstwo_id=panstwo.PANSTWO_ID,
                entenda_date=entenda_date,
                source=WZROST_REGEN_SOURCE_AFTER,
                old_growth=current_growth,
                new_growth=final_growth
            )

        _log_growth_regeneration(entenda_date, event_def)

        db.session.commit()

    except IntegrityError:
        db.session.rollback()
        raise

    except Exception:
        db.session.rollback()
        raise


# ============================================================
# PKB REGENERATION
# ============================================================

SYSTEM_EVENT_KEY = "regeneracja_pkb"


def _get_system_event_definition():
    return (
        DictZdarzeniaSystemowe.query
        .filter_by(zdarzenie_systemowe_nazwa=SYSTEM_EVENT_KEY)
        .first()
    )

def run_annual_pkb_regeneration():
    entenda_date = get_current_entenda_date()

    if entenda_date.month != 12 or entenda_date.day != 30:
        return

    event_def = _get_system_event_definition()

    if not event_def:
        raise RuntimeError(
            "Brak definicji zdarzenia systemowego 'regeneracja_pkb'."
        )

    try:
        panstwa = (
            db.session.query(Panstwo, Gospodarka)
            .join(
                Gospodarka,
                Gospodarka.panstwo_id == Panstwo.PANSTWO_ID
            )
            .all()
        )

        for panstwo, gospodarka in panstwa:
            if panstwo.panstwo_PKB is None:
                continue

            if gospodarka.wzrost_pkb is None:
                continue

            old_pkb = int(panstwo.panstwo_PKB)
            growth_pct = float(gospodarka.wzrost_pkb)

            new_pkb = round(
                old_pkb * (1 + (growth_pct / 100.0))
            )

            delta = new_pkb - old_pkb

            history = PKBStateHistory(
                panstwo_id=panstwo.PANSTWO_ID,
                data_entenda=entenda_date,
                data_rzeczywista=datetime.now(),
                source=PKB_REGEN_SOURCE,
                event_id=None,
                old_pkb=old_pkb,
                new_pkb=new_pkb,
                change_delta=delta
            )

            db.session.add(history)

            panstwo.panstwo_PKB = new_pkb

        
        system_event = ZdarzeniaSystemowe(
            zdarzenie_systemowe_id=event_def.zdarzenie_systemowe_id,
            data_entenda=entenda_date,
            data_rzeczywista=datetime.now(),
            opis="System ZEUS pomyślnie wykonał roczne przeliczenie PKB wszystkich państw Entendy."
        )

        db.session.add(system_event)

        db.session.commit()

    except IntegrityError:
        db.session.rollback()
        raise

    except Exception:
        db.session.rollback()
        raise


# ============================================================
# PKB PER CAPITA SNAPSHOT
# ============================================================

PKBPC_SYSTEM_EVENT_KEY = "regeneracja_pkbpc"

