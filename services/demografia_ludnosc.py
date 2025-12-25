from sqlalchemy import func
from models import Panstwo, Region, Miasto
from extensions import db


def format_populacja(n):
    if n is None:
        return "—"
    if n >= 1_000_000:
        return f"{round(n / 1_000_000, 2)} mln"
    if n >= 1_000:
        return f"{round(n / 1_000, 1)} tys."
    return str(n)


def licz_dane_kontynentu(kontynent):

    panstwa = Panstwo.query.filter_by(kontynent=kontynent).all()
    if not panstwa:
        return None

    panstwo_ids = [p.PANSTWO_ID for p in panstwa]

    # ===== POPULACJA =====
    populacja = sum(p.panstwo_populacja or 0 for p in panstwa)

    # ===== POWIERZCHNIA =====
    powierzchnia = sum(p.panstwo_powierzchnia or 0 for p in panstwa)
    gestosc = round(populacja / powierzchnia, 2) if powierzchnia else None

    # ===== REGIONY =====
    regiony_count = (
        db.session.query(func.count(Region.region_id))
        .filter(Region.panstwo_id.in_(panstwo_ids))
        .scalar()
    ) or 0

    # ===== MIASTA =====
    miasta_count = (
        db.session.query(func.count(Miasto.miasto_id))
        .join(Region, Miasto.region_id == Region.region_id)
        .filter(Region.panstwo_id.in_(panstwo_ids))
        .scalar()
    ) or 0

    # ===== LUDNOŚĆ MIEJSKA =====
    ludnosc_miejska = (
        db.session.query(func.coalesce(func.sum(Miasto.miasto_populacja), 0))
        .join(Region, Miasto.region_id == Region.region_id)
        .filter(Region.panstwo_id.in_(panstwo_ids))
        .scalar()
    ) or 0

    urbanizacja = (
        round((ludnosc_miejska / populacja) * 100, 2)
        if populacja else None
    )

    # ===== ŚREDNIE =====
    srednia_panstwo = round(populacja / len(panstwa), 0) if panstwa else None
    srednia_region = (
        round(populacja / regiony_count, 0)
        if regiony_count else None
    )

    # ===== TOP 5 MIAST =====
    top_miasta_raw = (
        db.session.query(Miasto.miasto_nazwa, Miasto.miasto_populacja)
        .join(Region, Miasto.region_id == Region.region_id)
        .filter(Region.panstwo_id.in_(panstwo_ids))
        .order_by(Miasto.miasto_populacja.desc())
        .limit(5)
        .all()
    )

    top_miasta = [
        {
            "miasto_nazwa": m.miasto_nazwa,
            "miasto_populacja": format_populacja(m.miasto_populacja)
        }
        for m in top_miasta_raw
    ]

    return {
        "typ": "kontynent",
        "nazwa": kontynent,
        "populacja": populacja,
        "powierzchnia": powierzchnia,
        "gestosc": gestosc,
        "regiony": regiony_count,
        "miasta": miasta_count,
        "urbanizacja_pct": urbanizacja,
        "srednia_panstwo": srednia_panstwo,
        "srednia_region": srednia_region,
        "top_miasta": top_miasta,
    }
