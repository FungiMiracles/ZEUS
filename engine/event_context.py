from models import Panstwo, Region, Miasto

def get_capital_name(panstwo_id):

    if not panstwo_id:
        return None

    capital = (
        Miasto.query
        .filter_by(panstwo_id=panstwo_id, miasto_typ_id=1)
        .limit(1).first()
    )

    if capital:
        return capital.miasto_nazwa

    return None

def build_event_context(event):

    panstwo_nazwa = None
    region_nazwa = None
    miasto_nazwa = None
    stolica = get_capital_name(event.panstwo_id)

    if event.panstwo_id:
        p = Panstwo.query.get(event.panstwo_id)
        if p:
            panstwo_nazwa = p.panstwo_nazwa

    if event.region_id:
        r = Region.query.get(event.region_id)
        if r:
            region_nazwa = r.region_nazwa

    if event.miasto_id:
        m = Miasto.query.get(event.miasto_id)
        if m:
            miasto_nazwa = m.miasto_nazwa

    return {
        "panstwo_nazwa": panstwo_nazwa,
        "region_nazwa": region_nazwa,
        "miasto_nazwa": miasto_nazwa,
        "stolica": stolica,
        "skala": event.skala,
        "ilosc_ofiar": event.ilosc_ofiar
    }

