from models import ZdarzenieSzablon
from extensions import db

def select_template(event_type, scale):

    template = (
        db.session.query(ZdarzenieSzablon)
        .filter_by(
            zdarzenie_typ=event_type,
            skala=scale,
            aktywny=True
        )
        .order_by(db.func.rand())
        .first()
    )

    return template