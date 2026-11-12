from datetime import timedelta
from extensions import db
from models import (
    Przywodztwo,
    Panstwo,
    DictPrzywodcaTyp
)

from engine.clock import get_current_entenda_date


def get_expired_leaders():

    today = get_current_entenda_date()

    typy = (
        DictPrzywodcaTyp.query
        .order_by(DictPrzywodcaTyp.przywodca_typ)
        .all()
    )

    results = []

    for country in Panstwo.query.all():

        last_leader = (
            Przywodztwo.query
            .filter_by(panstwo_id=country.PANSTWO_ID)
            .order_by(Przywodztwo.data_entenda_do.desc())
            .first()
        )

        if last_leader is None:

            if country.kadencja_przywodcy is None:
                continue

            results.append({
                "panstwo_id": country.PANSTWO_ID,
                "is_first_leader": True,
                "panstwo_nazwa": country.panstwo_nazwa,
                "panstwo_pelna_nazwa": country.panstwo_pelna_nazwa,
                "ustroj": country.ustroj.ustroj_nazwa if country.ustroj else None,
                "flaga": f"/static/flags/{country.panstwo_nazwa.replace(' ', '_')}.jpg",
                "kadencja": country.kadencja_przywodcy,
                "manual_date":
                    country.kadencja_przywodcy is None,
                "new_start_date": today.isoformat(),
                "typy": [
                    {
                        "id": t.id,
                        "nazwa": t.przywodca_typ
                    }
                    for t in typy
                ],
            })
            continue

        print("TYPE:", type(last_leader.data_entenda_do))
        print("VALUE:", last_leader.data_entenda_do)
        print("TODAY TYPE:", type(today))
        print("TODAY:", today)

        if last_leader.data_entenda_do < today:

            results.append({
                "panstwo_id": country.PANSTWO_ID,
                "is_first_leader": False,
                "panstwo_nazwa": country.panstwo_nazwa,
                "panstwo_pelna_nazwa": country.panstwo_pelna_nazwa,
                "ustroj": country.ustroj.ustroj_nazwa if country.ustroj else None,
                "flaga": f"/static/flags/{country.panstwo_nazwa.replace(' ', '_')}.jpg",
                "kadencja": country.kadencja_przywodcy,
                "manual_date":
                    country.kadencja_przywodcy is None,
                "new_start_date": (
                    last_leader.data_entenda_do
                    + timedelta(days=1)
                ).isoformat(),

                "previous_leader": {
                    "typ": last_leader.typ.przywodca_typ,
                    "imie": last_leader.przywodca_imie,
                    "nazwisko": last_leader.przywodca_nazwisko,
                    "data_od": last_leader.data_entenda_od.isoformat(),
                    "data_do": last_leader.data_entenda_do.isoformat()
                },

                "typy": [
                    {
                        "id": t.id,
                        "nazwa": t.przywodca_typ
                    }
                    for t in typy
                ],
            })

    return results