import random
from datetime import timedelta

from models import (
    Zdarzenie,
    ZdarzenieSzablon
)

from extensions import db


def select_template(
    event_type,
    scale,
    variant=None,
    panstwo_id=None,
    target_date=None
):

    query = (
        db.session.query(ZdarzenieSzablon)
        .filter_by(
            zdarzenie_typ=event_type,
            aktywny=True
        )
    )

    if variant:
        query = query.filter_by(wariant=variant)
    else:
        query = query.filter_by(skala=scale)

    templates = query.all()

    available = []

    for template in templates:

        if (
            event_type == "nowa_ustawa"
            and panstwo_id is not None
            and target_date is not None
        ):

            existing = (
                Zdarzenie.query
                .filter(
                    Zdarzenie.panstwo_id == panstwo_id,
                    Zdarzenie.opis_szablon_id == template.szablon_id,
                    Zdarzenie.data_entenda >= target_date - timedelta(days=180)
                )
                .first()
            )

            if existing:
                continue

        available.append(template)

    if not available:
        return None

    return random.choice(available)