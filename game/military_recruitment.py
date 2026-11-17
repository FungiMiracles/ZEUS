"""Rekrutacja żołnierzy do służby czynnej (16 Nov 2026).

- Gracz i PAGA2 rekrutują żołnierzy sił lądowych, morskich i powietrznych w module „Siły zbrojne”. Rekrutowani
  trafiają do służby czynnej (pola wojska_*_ilosc tabeli „wojsko”); stamtąd istniejącym mechanizmem przydziela się
  ich do garnizonów baz. Służba czynna = rezerwa (nieprzydzieleni) + garnizony baz + armie lądowe w operacjach.
- Rekrutacja jest darmowa. Utrzymanie: PKB per capita × 0,01 za żołnierza na okres rozliczeniowy, z budżetu sił
  zbrojnych. Opłatę nalicza się raz na okres, przy pierwszym rozliczeniu utrzymania po zatwierdzeniu budżetu, od
  liczby żołnierzy w tym momencie, bez rekrutów z bieżącego okresu (soldiers_recruited) — rekrutacja w trakcie okresu
  nic nie kosztuje do następnego okresu, także gdy opłata jest naliczana dopiero po rekrutacji, a zwolnienie
  obniża koszt dopiero od następnego okresu. Opłata za żołnierzy ma pierwszeństwo przed utrzymaniem sprzętu i baz.
- Gdy budżetu zabraknie, gra zwalnia żołnierzy, na których nie stać państwa: najpierw z rezerwy, potem
  proporcjonalnie z garnizonów baz — i powiadamia gracza / państwo PAGA2.
- Liczebność armii (suma trzech rodzajów sił) nie może przekroczyć 30% ludności w wieku 18–64.
- Zwolnić można wyłącznie żołnierzy z rezerwy (przydzielonych do baz najpierw wycofuje się z garnizonu).
"""
from decimal import Decimal, ROUND_DOWN
from sqlalchemy import select
from sqlalchemy.orm import Session
from extensions import db
from game.finance_service import FinanceError, game_now

SOLDIER_FIELDS = {'land': 'wojska_ladowe_ilosc', 'naval': 'wojska_morskie_ilosc', 'air': 'wojska_powietrzne_ilosc'}
BRANCH_LABELS = {'land': 'Wojska lądowe', 'naval': 'Marynarka wojenna', 'air': 'Siły powietrzne'}
FEE_SHARE = Decimal('0.01')        # część PKB per capita za żołnierza na okres rozliczeniowy
ARMY_LIMIT = Decimal('0.30')       # limit armii: 30% ludności w wieku 18–64
MAX_CHANGE = 10_000_000            # jednorazowo najwyżej tylu żołnierzy


def fmt(value):
    return f'{int(value):,}'.replace(',', ' ')


def soldier_rate(session, country_id):
    """Opłata za jednego żołnierza na okres rozliczeniowy: PKB per capita × 0,01 (ROI, do grosza)."""
    from game.land_war import gdp_per_capita
    return (gdp_per_capita(session, country_id) * FEE_SHARE).quantize(Decimal('0.01'))


def working_population(session, country_id):
    """Ludność w wieku 18–64 (struktura wieku z WIKI); None, gdy administrator jej nie ustalił."""
    from game.population_structure import structure_data
    try:
        data = structure_data(session, country_id)
    except FinanceError:
        return None
    return next((group['count'] for group in data['groups'] if group['key'] == 'working'), None)


def army_limit(session, country_id):
    working = working_population(session, country_id)
    return None if working is None else int((Decimal(working) * ARMY_LIMIT).to_integral_value(rounding=ROUND_DOWN))


def totals(army):
    return {branch: int((getattr(army, field) or 0) if army is not None else 0) for branch, field in SOLDIER_FIELDS.items()}


def assigned(session, country_id, bases=None):
    """Żołnierze przydzieleni (garnizony baz i armie lądowe w operacjach) według rodzaju sił."""
    from game.military_models import MilitaryBase
    from game.land_war import deployed_counts
    if bases is None:
        bases = list(session.scalars(select(MilitaryBase).where(MilitaryBase.panstwo_id == country_id)))
    result = {branch: 0 for branch in SOLDIER_FIELDS}
    for base in bases:
        if base.kind in result:
            result[base.kind] += int((base.garrison or {}).get('soldiers', 0))
    result['land'] += int(deployed_counts(session, country_id).get(SOLDIER_FIELDS['land'], 0))
    return result


def current_record(session, country_id, now=None):
    from game.finance_service import period_key
    from game.military_models import MilitaryMaintenance
    year, period = period_key(now or game_now())
    return session.scalar(select(MilitaryMaintenance).where(MilitaryMaintenance.panstwo_id == country_id,
                                                            MilitaryMaintenance.game_year == year, MilitaryMaintenance.period == period))


def period_record(session, country_id):
    """Rekord utrzymania bieżącego okresu (blokada do zapisu); tworzony, gdy go jeszcze nie ma."""
    from game.finance_service import period_key
    from game.military_models import MilitaryMaintenance
    year, period = period_key(game_now())
    record = session.scalar(select(MilitaryMaintenance).where(MilitaryMaintenance.panstwo_id == country_id, MilitaryMaintenance.game_year == year,
                                                              MilitaryMaintenance.period == period).with_for_update())
    if record is None:
        record = MilitaryMaintenance(panstwo_id=country_id, game_year=year, period=period, amount=0, soldier_count=0, soldier_rate=0,
                                     soldier_fee=0, soldiers_recruited=0)
        session.add(record); session.flush()
    return record


def summary(session, country_id, army=None, bases=None, now=None):
    """Stan służby czynnej i opłat — dla ekranów „Siły zbrojne”, „Obrona państwa”, panelu wojennego i PAGA2."""
    from game.governance import army_for_country
    if army is None:
        army = army_for_country(session, country_id)
    total = totals(army)
    used = assigned(session, country_id, bases)
    rate = soldier_rate(session, country_id)
    record = current_record(session, country_id, now)
    count = sum(total.values())
    return {
        'branches': {branch: {'label': BRANCH_LABELS[branch], 'total': total[branch], 'assigned': min(total[branch], used[branch]),
                              'reserve': max(0, total[branch] - used[branch])} for branch in SOLDIER_FIELDS},
        'total': count, 'limit': army_limit(session, country_id), 'rate': str(rate),
        'periodFee': str((record.soldier_fee or 0) if record is not None else 0),
        'periodSoldiers': int((record.soldier_count or 0) if record is not None else 0),
        'assessed': record is not None and record.soldiers_assessed_at is not None,
        'nextFee': str((rate * count).quantize(Decimal('0.01'))),
    }


def change(session, country_id, action, branch, count):
    """Rekrutacja (action='recruit') albo zwolnienie z rezerwy (action='dismiss'). Zwraca nowe podsumowanie."""
    from game.governance import army_for_country
    if action not in ('recruit', 'dismiss'):
        raise FinanceError('Nieznana operacja.')
    if branch not in SOLDIER_FIELDS:
        raise FinanceError('Wybierz rodzaj sił zbrojnych.')
    if type(count) is not int or count < 1 or count > MAX_CHANGE:
        raise FinanceError(f'Liczba żołnierzy musi być liczbą całkowitą od 1 do {fmt(MAX_CHANGE)}.')
    army = army_for_country(session, country_id, lock=True)
    if army is None:
        raise FinanceError('Brak danych o siłach zbrojnych państwa.')
    field = SOLDIER_FIELDS[branch]
    current = totals(army)
    if action == 'recruit':
        limit = army_limit(session, country_id)
        if limit is None:
            raise FinanceError('Administrator musi najpierw ustalić strukturę wieku ludności tego państwa w WIKI.')
        if sum(current.values()) + count > limit:
            free = max(0, limit - sum(current.values()))
            raise FinanceError(f'Liczebność armii nie może przekroczyć 30% ludności w wieku 18–64 ({fmt(limit)} żołnierzy). '
                               f'Można jeszcze zrekrutować {fmt(free)}.')
        setattr(army, field, current[branch] + count)
        # 16 Nov 2026: rekruci z bieżącego okresu nie są wliczani do opłaty aż do następnego okresu (także gdy opłata
        # zostanie naliczona dopiero po rekrutacji).
        record = period_record(session, country_id)
        if record.soldiers_assessed_at is None:
            record.soldiers_recruited = int(record.soldiers_recruited or 0) + count
    else:
        reserve = max(0, current[branch] - assigned(session, country_id)[branch])
        if count > reserve:
            raise FinanceError(f'{BRANCH_LABELS[branch]}: w rezerwie jest {fmt(reserve)} żołnierzy. Żołnierzy przydzielonych do baz '
                               'najpierw wycofaj z garnizonu.')
        setattr(army, field, current[branch] - count)
        # Zwolnienie przed naliczeniem opłaty dotyczy najpierw rekrutów z tego okresu (nie są już zwolnieni z opłaty).
        record = period_record(session, country_id)
        if record.soldiers_assessed_at is None and record.soldiers_recruited:
            record.soldiers_recruited = max(0, int(record.soldiers_recruited) - count)
    session.flush()
    return summary(session, country_id, army)


def change_for_user(user_id, data):
    from game.finance_service import _country_for_user
    with Session(db.engine) as session, session.begin():
        country = _country_for_user(session, user_id, lock=True)
        return change(session, country.PANSTWO_ID, data.get('action'), data.get('branch'), data.get('count'))


def _share(amounts, need):
    """Rozkład `need` proporcjonalnie do `amounts` (metoda największych reszt, nie więcej niż dana pozycja)."""
    pool = sum(amounts.values())
    if need >= pool:
        return dict(amounts)
    if need <= 0 or pool <= 0:
        return {key: 0 for key in amounts}
    exact = {key: Decimal(value) * need / pool for key, value in amounts.items()}
    taken = {key: int(value) for key, value in exact.items()}
    for key in sorted(exact, key=lambda k: (-(exact[k] - taken[k]), str(k)))[:need - sum(taken.values())]:
        taken[key] += 1
    return taken


def release(session, country_id, army, bases, need):
    """Zwolnienie `need` żołnierzy: najpierw rezerwa (proporcjonalnie między rodzajami sił), potem garnizony baz.
    Zwraca liczbę zwolnionych według rodzaju sił."""
    total = totals(army)
    used = assigned(session, country_id, bases)
    reserve = {branch: max(0, total[branch] - used[branch]) for branch in SOLDIER_FIELDS}
    fired = _share(reserve, need)
    left = need - sum(fired.values())
    garrisons = {base.id: int((base.garrison or {}).get('soldiers', 0)) for base in bases if base.kind in SOLDIER_FIELDS and (base.garrison or {}).get('soldiers')}
    if left > 0 and garrisons:
        cut = _share(garrisons, left)
        for base in bases:
            if cut.get(base.id):
                base.garrison = {**base.garrison, 'soldiers': garrisons[base.id] - cut[base.id]}
                fired[base.kind] += cut[base.id]
    for branch, count in fired.items():
        if count:
            setattr(army, SOLDIER_FIELDS[branch], max(0, total[branch] - count))
    return fired


def assess(session, country_id, record, army, bases, affordable, budget, now, notify):
    """Opłata za żołnierzy w bieżącym okresie (naliczana raz, po zatwierdzeniu budżetu). Zwraca kwotę opłaty."""
    if record.soldiers_assessed_at is not None:
        return Decimal(record.soldier_fee or 0)
    if budget is None or army is None:
        return Decimal(0)       # budżet niezatwierdzony — opłata zostanie naliczona przy pierwszym rozliczeniu po zatwierdzeniu
    from game.models import utc_now
    rate = soldier_rate(session, country_id)
    recruited = int(record.soldiers_recruited or 0)            # rekruci z bieżącego okresu — bez opłaty do następnego okresu
    count = max(0, sum(totals(army).values()) - recruited)
    if rate > 0 and Decimal(count) * rate > affordable:
        keep = int((max(Decimal(0), affordable) / rate).to_integral_value(rounding=ROUND_DOWN))
        fired = release(session, country_id, army, bases, count - keep)
        count = max(0, sum(totals(army).values()) - recruited)
        details = ', '.join(f'{BRANCH_LABELS[b].lower()}: {fmt(n)}' for b, n in fired.items() if n)
        notify(f'Brak środków w budżecie sił zbrojnych na utrzymanie żołnierzy ({rate} ROI za żołnierza na okres). '
               f'Zwolniono {fmt(sum(fired.values()))} żołnierzy ({details}).')
    fee = (Decimal(count) * rate).quantize(Decimal('0.01'))
    record.soldier_count, record.soldier_rate, record.soldier_fee, record.soldiers_assessed_at = count, rate, fee, utc_now()
    return fee
