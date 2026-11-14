"""PAGA2 — straty wojenne i odstraszenie (13 Nov 2026).

a) Straty poniesione w bieżącej wojnie z danym państwem (zniszczone bazy, fabryki, elektrownie i infrastruktura —
   z zapisów ataków MilitaryFlight, także uderzeń atomowych) zwiększają skłonność do przyjęcia lub wysunięcia
   propozycji pokoju albo zawieszenia broni.
b) Państwo, które zawarło pokój po wojnie z dużymi stratami, jest potem mniej skłonne do atakowania byłego przeciwnika
   i jego sojuszników (kara malejąca w ciągu 3 lat Entendy). Okresy wojen — z audytu stosunków (bez nowych tabel).
"""
from datetime import datetime, date, timedelta
from sqlalchemy import select, or_, and_

WAR_STATE = 'wojnakinetyczna'
WEIGHTS = {'bases': 3.0, 'factories': 2.0, 'power': 2.0}
INFRA_PER_POINT = 0.2           # punkt wskaźnika infrastruktury regionu
HEAVY_LOSSES = 10.0             # od tylu punktów strat pokój „po ciężkiej wojnie” odstrasza od kolejnej
DETERRENCE_YEARS = 3
ALLY_SHARE = 0.7                # sojusznicy byłego przeciwnika — 70% kary
LOSS_PEACE_MAX = 25.0           # 14 Nov 2026: limit premii za straty (było 16 — ciężkie straty przestawały skłaniać do pokoju)
NUCLEAR_PEACE = 25.0            # 13 Nov 2026: przeciwnik użył broni atomowej — drastyczna skłonność do pokoju
NUCLEAR_PEACE_EXTRA = 5.0       # za każde kolejne odpalenie
NUCLEAR_PEACE_MAX = 40.0
PACTS = ('partnerskie', 'partnerskiestrategiczne', 'sojusznicze')


def _as_datetime(value):
    if value is None or isinstance(value, datetime):
        return value
    return datetime(value.year, value.month, value.day) if isinstance(value, date) else value


def war_periods(session, a, b):
    """Okresy wojny pary państw: [(początek, koniec albo None, stan po wojnie)] w czasie gry, z audytu stosunków."""
    from models import AudytStosunki
    from game.diplomacy_service import dictionaries
    _, states, _ = dictionaries(session)
    war = states[WAR_STATE]
    names = {id: key for key, id in states.items()}
    a, b = sorted((a, b))
    rows = session.execute(select(AudytStosunki.stan_id, AudytStosunki.data_zmiany_entenda).where(
        AudytStosunki.panstwo_id == a, AudytStosunki.panstwo_id2 == b).order_by(AudytStosunki.id)).all()
    periods, start = [], None
    for state, moment in rows:
        moment = _as_datetime(moment)
        if state == war and start is None:
            start = moment
        elif state != war and start is not None:
            periods.append((start, moment, names.get(state)))
            start = None
    if start is not None:
        periods.append((start, None, None))
    return periods


def losses(session, victim, attacker, start, end=None):
    """Zniszczenia poniesione przez `victim` w atakach państwa `attacker` w okresie [start, end)."""
    from game.military_models import MilitaryFlight
    query = select(MilitaryFlight.damage).where(MilitaryFlight.panstwo_id == attacker, MilitaryFlight.target_country_id == victim,
                                                MilitaryFlight.impacted_at.is_not(None))
    if start is not None:
        query = query.where(MilitaryFlight.impact_at >= start)
    if end is not None:
        query = query.where(MilitaryFlight.impact_at < end)
    result = {'bases': 0, 'factories': 0, 'power': 0, 'infrastructure': 0}
    for (damage,) in session.execute(query):
        damage = damage or {}
        result['bases'] += 1 if damage.get('baseDestroyed') else 0
        result['factories'] += 1 if damage.get('factoryDestroyed') else 0
        result['power'] += 1 if damage.get('powerDestroyed') else 0
        result['infrastructure'] += int(damage.get('infrastructurePoints') or 0)
        if damage.get('nuclear'):
            destroyed = damage.get('destroyed') or {}
            for key in ('bases', 'factories', 'power'):
                result[key] += int(destroyed.get(key) or 0)
            result['infrastructure'] += sum(int(v or 0) for v in (damage.get('infrastructureLoss') or {}).values())
    return result


def nuclear_strikes(session, victim, attacker, start):
    """Liczba rakiet z głowicą nuklearną odpalonych przez `attacker` w `victim` od początku wojny (także przechwyconych)."""
    from sqlalchemy import func
    from game.military_models import MilitaryFlight
    query = select(func.coalesce(func.sum(MilitaryFlight.missiles), 0)).where(MilitaryFlight.panstwo_id == attacker, MilitaryFlight.target_country_id == victim,
                                                                              MilitaryFlight.is_nuclear.is_(True))
    if start is not None:
        query = query.where(MilitaryFlight.starts_at >= start)
    return int(session.scalar(query) or 0)


def score(loss):
    return sum(WEIGHTS[key] * loss.get(key, 0) for key in WEIGHTS) + INFRA_PER_POINT * loss.get('infrastructure', 0)


def current_war(ctx, other):
    """(punkty strat, straty, dni wojny) w trwającej wojnie z państwem `other` — dla oceny pokoju."""
    cache = getattr(ctx, '_war_losses', None)
    if cache is None:
        cache = ctx._war_losses = {}
    if other in cache:
        return cache[other]
    from sqlalchemy.orm import Session
    from extensions import db
    value = (0.0, {}, 0)
    try:
        with Session(db.engine) as session:
            periods = war_periods(session, ctx.country_id, other)
            if periods and periods[-1][1] is None:
                start = periods[-1][0]
                loss = losses(session, ctx.country_id, other, start)
                loss['nuclear'] = nuclear_strikes(session, ctx.country_id, other, start)
                days = max(0, (ctx.now - start).days) if ctx.now and start else 0
                value = (score(loss), loss, days)
    except Exception:
        value = (0.0, {}, 0)
    cache[other] = value
    return value


def peace_bonus(ctx, other):
    """Premia do pokoju/zawieszenia broni: straty w wojnie (ważone niską tolerancją strat) i zmęczenie wojną."""
    points, loss, days = current_war(ctx, other)
    tolerance = ctx.traits.get('loss_tolerance', 50)
    from_losses = min(LOSS_PEACE_MAX, points * (0.5 + (100 - tolerance) / 100))
    weariness = min(4.0, days / 60)
    strikes = (loss or {}).get('nuclear', 0)
    nuclear = min(NUCLEAR_PEACE_MAX, NUCLEAR_PEACE + NUCLEAR_PEACE_EXTRA * (strikes - 1)) if strikes else 0.0   # poza limitem strat
    return 1.0 + from_losses + weariness + nuclear, loss, days


def deterrence_map(ctx):
    """{państwo: kara} — byli przeciwnicy z wojen zakończonych pokojem/rozejmem przy ciężkich stratach i ich sojusznicy."""
    cached = getattr(ctx, '_deterrence', None)
    if cached is not None:
        return cached
    from sqlalchemy.orm import Session
    from extensions import db
    from models import AudytStosunki, Stosunki, DictStosunkiRelacja
    from services.natural_resources import normalized
    result = {}
    try:
        with Session(db.engine) as session:
            me = ctx.country_id
            others = {a if b == me else b for a, b in session.execute(select(AudytStosunki.panstwo_id, AudytStosunki.panstwo_id2).where(
                or_(AudytStosunki.panstwo_id == me, AudytStosunki.panstwo_id2 == me)).distinct())}
            enemies = {}
            for other in others:
                penalty = 0.0
                for start, end, after in war_periods(session, me, other):
                    if end is None or after == WAR_STATE:
                        continue
                    points = score(losses(session, me, other, start, end))
                    if points < HEAVY_LOSSES:
                        continue
                    age = (ctx.now - end).days if ctx.now else 0
                    decay = max(0.0, 1 - age / (365 * DETERRENCE_YEARS))
                    penalty = max(penalty, min(15.0, points) * decay)
                if penalty > 0:
                    enemies[other] = penalty
            result.update(enemies)
            if enemies:
                pacts = {id for id, name in session.execute(select(DictStosunkiRelacja.relacja_id, DictStosunkiRelacja.relacja_nazwa)) if normalized(name) in PACTS}
                for a, b in session.execute(select(Stosunki.PANSTWO_ID, Stosunki.PANSTWO_ID2).where(Stosunki.relacja_id.in_(pacts or {0}),
                                                                                                    or_(Stosunki.PANSTWO_ID.in_(enemies), Stosunki.PANSTWO_ID2.in_(enemies)))):
                    for enemy, ally in ((a, b), (b, a)):
                        if enemy in enemies and ally != me:
                            result[ally] = max(result.get(ally, 0.0), ALLY_SHARE * enemies[enemy])
    except Exception:
        result = {}
    ctx._deterrence = result
    return result


def deterrence(ctx, other):
    return deterrence_map(ctx).get(other, 0.0)
