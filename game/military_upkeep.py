"""Utrzymanie wojska rozliczane przy zatwierdzeniu budżetu (UAT, 23 Nov 2026; od 25 Nov 2026 — za poprzedni kwartał).

Zasady zatwierdzone przez administratora:
* Utrzymanie liczy się od POSIADANEGO wojska, bez względu na rozmieszczenie (baza, rezerwa, armia w operacji):
  żołnierze w służbie czynnej (PKB per capita × 0,01 za żołnierza na okres), sprzęt (UPKEEP_RATES za półrocze),
  silosy (500 mln ROI) i rakiety z głowicą nuklearną (650 mln ROI), dopłata za sprzęt w bazach za granicą (2× stawka).
  W okresie kwartalnym stawki sprzętu, silosów i głowic są o połowę niższe (stawka za żołnierza jest już „na okres”).
* 25 Nov 2026: budżet sił zbrojnych pokrywa utrzymanie za POPRZEDNI kwartał. Gra liczy całe wojsko posiadane w tym kwartale —
  także sprzęt i żołnierzy, których państwo pozbyło się przed jego końcem (zniszczenie, sprzedaż, zwolnienie): dla każdej
  pozycji większa z liczb — stan z początku kwartału (zapisany w budżecie jako `snapshot`) albo stan z końca kwartału
  (chwila zatwierdzenia kolejnego budżetu).
* Kwota jest pobierana przy zatwierdzeniu budżetu z przydziału sił zbrojnych; brakującą część pokrywa rezerwa budżetowa
  (przydział rezerwy zmniejsza się, przydział sił zbrojnych rośnie). W formularzu gracz widzi przydział pomniejszony o tę
  kwotę — przy zbyt małym udziale (także 0%) na minusie.
* Gdy nie starcza i rezerwy, gra pobiera tyle, ile jest, i demobilizuje proporcjonalnie to, na co państwa nie stać:
  zwalnia żołnierzy i likwiduje sprzęt (najpierw z rezerwy, potem z garnizonów baz — bez jednostek w misjach),
  rozbraja głowice (najpierw z magazynu) i wyłącza silosy do następnego okresu.
* Wszystko, co trafia do budżetu, jest ustalane PRZED jego zapisem — zatwierdzonych budżetów nie wolno zmieniać
  (wyzwalacz bazy trg_gsb_no_update). Do 25 Nov 2026 dopisanie wyniku demobilizacji po zapisie blokowało zatwierdzanie.
* Przejście: budżety sprzed 25 Nov 2026 (calculation_version < 6) opłaciły utrzymanie swojego okresu z góry albo w trakcie
  okresu, więc przy pierwszym budżecie według nowej zasady za poprzedni okres nic nie jest pobierane.
* Dla budżetów z military_upkeep IS NOT NULL utrzymanie nie jest naliczane z budżetu sił zbrojnych w trakcie okresu
  (reconcile_maintenance); nowe budżety zapisują military_upkeep = 0 (kwota jest w przydziale sił zbrojnych).
"""
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from sqlalchemy import select
from game.military_models import MilitaryBase

SILO_UPKEEP = Decimal('500000000')
LABELS = {'soldiers': 'Żołnierze', 'tanks': 'Czołgi', 'armored': 'Wozy opancerzone', 'launchers': 'Wyrzutnie rakiet',
          'fighters': 'Myśliwce', 'warships': 'Okręty wojenne', 'submarines': 'Okręty podwodne', 'silos': 'Silosy atomowe',
          'warheads': 'Rakiety z głowicą nuklearną', 'abroad': 'Dopłata za bazy za granicą'}


def _money(value):
    return Decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def equipment_codes():
    from game.military_service import UPKEEP_RATES, RESOURCES
    return [code for code, rate in UPKEEP_RATES.items() if rate and code not in ('soldiers', 'warheads') and RESOURCES.get(code, (None, None))[1]]


ARREARS_VERSION = 6   # wersja obliczeń budżetu, od której utrzymanie jest rozliczane za poprzedni okres


def holdings(session, country_id):
    """{kod: liczba} wojska posiadanego teraz (bez względu na rozmieszczenie)."""
    from game.military_service import RESOURCES
    from game.governance import army_for_country
    from game.military_recruitment import totals
    from game.nuclear import total as warheads_total
    army = army_for_country(session, country_id)
    counts = {'soldiers': sum(totals(army).values()) if army is not None else 0}
    for code in equipment_codes():
        counts[code] = int(getattr(army, RESOURCES[code][1]) or 0) if army is not None else 0
    bases = session.scalars(select(MilitaryBase).where(MilitaryBase.panstwo_id == country_id))
    counts['silos'] = sum(1 for base in bases if base.kind == 'nuclear')
    counts['warheads'] = int(warheads_total(session, country_id) or 0)
    return counts


def rates(session, country_id, year, period):
    """{kod: stawka utrzymania za okres (year, period)}."""
    from game.military_service import UPKEEP_RATES
    from game.finance_service import period_months
    from game.military_recruitment import soldier_rate
    scale = Decimal(period_months(year, period)) / 6
    result = {'soldiers': Decimal(soldier_rate(session, country_id))}
    for code in equipment_codes():
        result[code] = Decimal(UPKEEP_RATES[code]) * scale
    result['silos'] = SILO_UPKEEP * scale
    result['warheads'] = Decimal(UPKEEP_RATES['warheads']) * scale
    return result


def assess(session, country_id, year, period, counts=None):
    """{'total', 'items': {kod: {'label','count','rate','amount'}}} — utrzymanie wojska na okres (year, period);
    `counts` — liczby do naliczenia (domyślnie stan posiadania teraz)."""
    from game.military_service import UPKEEP_RATES
    from game.finance_service import period_months
    from game.base_permits import own_region_ids, ABROAD_UPKEEP
    counts = holdings(session, country_id) if counts is None else counts
    rate = rates(session, country_id, year, period)
    items = {}
    for code in ('soldiers', *equipment_codes(), 'silos', 'warheads'):
        count, value = int(counts.get(code) or 0), rate[code]
        if count > 0 and value > 0:
            items[code] = {'label': LABELS[code], 'count': count, 'rate': str(_money(value)), 'amount': _money(Decimal(count) * value)}
    scale = Decimal(period_months(year, period)) / 6
    bases = list(session.scalars(select(MilitaryBase).where(MilitaryBase.panstwo_id == country_id)))
    own = own_region_ids(session, country_id)
    surcharge = sum((Decimal(count) * UPKEEP_RATES.get(resource, 0) * (ABROAD_UPKEEP - 1) * scale
                     for base in bases if base.region_id is not None and base.region_id not in own
                     for resource, count in (base.garrison or {}).items() if resource != 'warheads' and UPKEEP_RATES.get(resource)), Decimal(0))
    if surcharge > 0:
        items['abroad'] = {'label': LABELS['abroad'], 'count': None, 'rate': None, 'amount': _money(surcharge)}
    return {'total': _money(sum((item['amount'] for item in items.values()), Decimal(0))), 'items': items}


def due_for_previous(session, country_id, previous):
    """Utrzymanie za okres poprzedniego budżetu (25 Nov 2026). Dla każdej pozycji większa liczba: stan z początku okresu
    (`snapshot` zapisany w poprzednim budżecie) albo stan obecny. Budżet sprzed zasady (wersja < 6) opłacił swój okres
    inaczej — wtedy nic nie jest należne (`prepaid`)."""
    if previous is None or int(previous.calculation_version or 0) < ARREARS_VERSION:
        return {'total': _money(0), 'items': {}, 'prepaid': previous is not None, 'period': None}
    counts = holdings(session, country_id)
    for code, count in ((previous.military_upkeep_details or {}).get('snapshot') or {}).items():
        if code in counts:
            counts[code] = max(counts[code], int(count or 0))
    result = assess(session, country_id, previous.game_year, previous.period, counts)
    return {**result, 'prepaid': False, 'period': [previous.game_year, previous.period]}


def serializable(assessment):
    return {**{key: value for key, value in assessment.items() if key not in ('total', 'items')}, 'total': str(assessment['total']),
            'items': {code: {**item, 'amount': str(item['amount'])} for code, item in assessment['items'].items()}}


def _remove_equipment(session, country_id, army, bases, code, count, now):
    """Likwiduje `count` sztuk sprzętu: najpierw z rezerwy, potem proporcjonalnie z garnizonów (bez jednostek w misjach)."""
    from game.military_service import RESOURCES, active_counts
    from game.military_navy import busy_vessels
    from game.military_flights import busy_fighters
    field = RESOURCES[code][1]
    owned = int(getattr(army, field) or 0)
    free = max(0, owned - active_counts(bases, session, country_id).get(field, 0))
    removed = min(count, free)
    left = count - removed
    if left > 0:
        holders = []
        for base in bases:
            have = int((base.garrison or {}).get(code, 0) or 0)
            busy = busy_vessels(session, base.id, code) if code in ('warships', 'submarines') else busy_fighters(session, base.id, now) if code == 'fighters' else 0
            if have - busy > 0:
                holders.append((base, have, have - busy))
        pool = sum(spare for _, _, spare in holders)
        for base, have, spare in holders:
            if left <= 0 or pool <= 0:
                break
            cut = min(spare, left, -(-left * spare // pool))
            base.garrison = {**base.garrison, code: have - cut}
            left -= cut
            removed += cut
    setattr(army, field, max(0, owned - removed))
    return removed


def demobilize(session, country_id, assessment, ratio, now):
    """Proporcjonalna demobilizacja tego, na co nie starczyło środków (ratio = pobrane / należne). Zwraca {kod: liczba}."""
    from game.governance import army_for_country
    from game.military_recruitment import release
    from game import nuclear
    ratio = max(Decimal(0), min(Decimal(1), Decimal(ratio)))
    army = army_for_country(session, country_id, lock=True)
    bases = list(session.scalars(select(MilitaryBase).where(MilitaryBase.panstwo_id == country_id).order_by(MilitaryBase.id).with_for_update()))
    cut = lambda count: int(count) - int((Decimal(int(count)) * ratio).to_integral_value(rounding=ROUND_DOWN))
    result = {}
    items = assessment['items']
    if 'soldiers' in items and army is not None:
        need = cut(items['soldiers']['count'])
        if need:
            result['soldiers'] = sum(release(session, country_id, army, bases, need).values())
    for code in equipment_codes():
        if code in items and army is not None:
            need = cut(items[code]['count'])
            if need:
                result[code] = _remove_equipment(session, country_id, army, bases, code, need, now)
    if 'warheads' in items:
        need = cut(items['warheads']['count'])
        if need:
            stored = max(0, nuclear.total(session, country_id) - nuclear.loaded(session, country_id))
            from_silos = max(0, need - stored)
            for base in bases:
                if from_silos <= 0:
                    break
                if base.kind == 'nuclear' and (base.garrison or {}).get('warheads'):
                    take = min(from_silos, int(base.garrison['warheads']))
                    base.garrison = {**base.garrison, 'warheads': int(base.garrison['warheads']) - take}
                    from_silos -= take
            nuclear.change_total(session, country_id, -need)
            result['warheads'] = need
    silos = [base for base in bases if base.kind == 'nuclear']
    disabled = cut(len(silos)) if 'silos' in items else 0
    for index, base in enumerate(silos):
        base.operational = index >= disabled
    if disabled:
        result['silos'] = disabled
    session.flush()
    return result


def enable_silos(session, country_id):
    """Pełne utrzymanie opłacone — silosy wyłączone z braku środków w poprzednim okresie wracają do pracy."""
    for base in session.scalars(select(MilitaryBase).where(MilitaryBase.panstwo_id == country_id, MilitaryBase.kind == 'nuclear').with_for_update()):
        base.operational = True


def summary_text(result):
    return ', '.join(f'{LABELS[code].lower()}: {count}' for code, count in result.items() if count)


def collect(session, country_id, due, collected, moment):
    """Przed zapisem budżetu: przy niedoborze proporcjonalna demobilizacja obecnego wojska, przy pełnej zapłacie ponowne
    włączenie silosów. Zwraca {kod: liczba zdemobilizowanych}."""
    total = Decimal(due['total'])
    collected = Decimal(collected or 0)
    if total > 0 and collected < total:
        from game.finance_service import game_now, period_key
        current = assess(session, country_id, *period_key(moment or game_now()))
        result = demobilize(session, country_id, current, collected / total, moment)
        _notify(session, country_id, f'Środki budżetu nie wystarczyły na utrzymanie wojska za poprzedni okres (należne {_fmt(total)} ROI, '
                                     f'pobrano {_fmt(collected)} ROI). Przeprowadzono proporcjonalną demobilizację — {summary_text(result) or "bez zmian"}.')
        return result
    enable_silos(session, country_id)
    return {}


def record(session, country_id, budget, due, collected):
    """Po zapisie budżetu: rozliczenie okresu (MilitaryMaintenance) — pobrana kwota jest wydatkiem sektora sił zbrojnych."""
    from game.military_models import MilitaryMaintenance
    from game.models import utc_now
    record = session.scalar(select(MilitaryMaintenance).where(MilitaryMaintenance.panstwo_id == country_id, MilitaryMaintenance.game_year == budget.game_year,
                                                              MilitaryMaintenance.period == budget.period).with_for_update())
    if record is None:
        record = MilitaryMaintenance(panstwo_id=country_id, game_year=budget.game_year, period=budget.period, amount=0)
        session.add(record)
    soldiers = due['items'].get('soldiers')
    record.budget_id, record.amount, record.assessed_at = budget.id, _money(collected or 0), utc_now()
    record.soldier_count = soldiers['count'] if soldiers else 0
    record.soldier_rate = Decimal(soldiers['rate']) if soldiers else Decimal(0)
    record.soldier_fee = Decimal(soldiers['amount']) if soldiers else Decimal(0)
    record.soldiers_assessed_at = utc_now()
    session.flush()
    return record


def upfront(session, country_id, now=None):
    """Bieżący budżet państwa rozlicza utrzymanie przy zatwierdzeniu (zatwierdzony po 23 Nov 2026) — w trakcie okresu
    reconcile_maintenance nic nie nalicza."""
    from game.finance_models import StateBudget
    from game.finance_service import game_now, period_key
    year, period = period_key(now or game_now())
    value = session.execute(select(StateBudget.military_upkeep).where(StateBudget.panstwo_id == country_id, StateBudget.game_year == year,
                                                                      StateBudget.period == period)).first()
    return value is not None and value[0] is not None


def _fmt(value):
    return f'{Decimal(value):,.2f}'.replace(',', ' ').replace('.', ',')


def _notify(session, country_id, text):
    from game.paga_ai_actor import country_user_id
    from game.forum_models import GameNotification
    from game.models import utc_now
    owner = country_user_id(session, country_id)
    if owner is not None:
        session.add(GameNotification(user_id=owner, notification_type='SYSTEM', system_text=text[:1000], created_at=utc_now()))
