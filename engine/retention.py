from datetime import datetime, timedelta

from extensions import db
from models import Zdarzenie, ZdarzeniaSystemowe
from engine.clock import get_current_entenda_date

MAKS_AKTYWNYCH_ZDARZEN = 10000
OKRES_RETENCJI_DNI = 90

def wykonaj_retencje_zdarzen():

    teraz = datetime.now()

    liczba_zarchiwizowanych = 0
    liczba_usunietych = 0

    # --------------------------------------------------
    # KROK 1 — ARCHIWIZACJA NADMIAROWYCH ZDARZEŃ
    # --------------------------------------------------

    aktywne_count = (
        Zdarzenie.query
        .filter_by(status="aktywne")
        .count()
    )

    if aktywne_count > MAKS_AKTYWNYCH_ZDARZEN:

        nadmiar = aktywne_count - MAKS_AKTYWNYCH_ZDARZEN

        najstarsze = (
            Zdarzenie.query
            .filter_by(status="aktywne")
            .order_by(Zdarzenie.data_entenda.asc())
            .limit(nadmiar)
            .all()
        )

        for zdarzenie in najstarsze:

            zdarzenie.status = "archiwalne"
            zdarzenie.data_archiwizacji = teraz
            zdarzenie.data_usuniecia = (
                teraz + timedelta(days=OKRES_RETENCJI_DNI)
            )

        liczba_zarchiwizowanych = len(najstarsze)

    # --------------------------------------------------
    # KROK 2 — USUWANIE ARCHIWALNYCH
    # --------------------------------------------------

    do_usuniecia = (
        Zdarzenie.query
        .filter(
            Zdarzenie.status == "archiwalne",
            Zdarzenie.data_usuniecia <= teraz,
            Zdarzenie.zdarzenie_typ.notin_(["nowa_ustawa", "globalny_kryzys_gospodarczy"])
        )
        .all()
    )

    liczba_usunietych = len(do_usuniecia)

    for zdarzenie in do_usuniecia:
        db.session.delete(zdarzenie)

    # --------------------------------------------------
    # KROK 3 — LOG SYSTEMOWY
    # --------------------------------------------------

    if liczba_zarchiwizowanych > 0:

        log = ZdarzeniaSystemowe(
            zdarzenie_systemowe_id=6,
            data_entenda=get_current_entenda_date(),
            data_rzeczywista=datetime.now(),
            opis=f"System ZEUS oznaczył jako archiwalne "
                f"{liczba_zarchiwizowanych} zdarzeń."
        )

        db.session.add(log)

    if liczba_usunietych > 0:

        log = ZdarzeniaSystemowe(
            zdarzenie_systemowe_id=7,
            data_entenda=get_current_entenda_date(),
            data_rzeczywista=datetime.now(),
            opis=f"System ZEUS usunął "
                 f"{liczba_usunietych} archiwalnych zdarzeń."
        )

        db.session.add(log)

    db.session.commit()
