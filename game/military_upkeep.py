"""Utrzymanie wojska pobierane z budżetu przed jego podziałem (UAT, 23 Nov 2026).

Zasady zatwierdzone przez administratora:
* Utrzymanie liczy się od POSIADANEGO wojska, bez względu na rozmieszczenie (baza, rezerwa, armia w operacji):
  żołnierze w służbie czynnej (PKB per capita × 0,01 za żołnierza na okres), sprzęt (UPKEEP_RATES za półrocze),
  silosy (500 mln ROI) i rakiety z głowicą nuklearną (650 mln ROI), dopłata za sprzęt w bazach za granicą (2× stawka).
  W okresie kwartalnym stawki sprzętu, silosów i głowic są o połowę niższe (stawka za żołnierza jest już „na okres”).
* Kwota jest pobierana przy zatwierdzeniu budżetu — po spłacie zaległości w MFW, przed podziałem środków (mniej do podziału).
  Stan wojska liczy się z chwili zatwierdzenia: rekruci i zakupy z bieżącego okresu płacą od następnego, za straty
  w trakcie okresu nie ma zwrotu.
* Gdy środków nie starcza, gra pobiera tyle, ile jest, i demobilizuje proporcjonalnie to, na co państwa nie stać:
  zwalnia żołnierzy i likwiduje sprzęt (najpierw z rezerwy, potem z garnizonów baz — bez jednostek w misjach),
  rozbraja głowice (najpierw z magazynu) i wyłącza silosy do następnego okresu.
* Nowa zasada obowiązuje od budżetów zatwierdzonych po wdrożeniu (StateBudget.military_upkeep IS NOT NULL);
  dla takich budżetów utrzymanie nie jest już naliczane z budżetu sił zbrojnych w trakcie okresu (reconcile_maintenance).
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


def assess(session, country_id, year, period):
    """{'total', 'items': {kod: {'label','count','rate','amount'}}} — utrzymanie posiadanego wojska na okres (year, period)."""
    from game.military_service import UPKEEP_RATES, RESOURCES
    from game.finance_service import period_months
    from game.governance import army_for_country
    from game.military_recruitment import totals, soldier_rate
    from game.nuclear import total as warheads_total
    from game.base_permits import own_region_ids, ABROAD_UPKEEP
    scale = Decimal(period_months(year, period)) / 6
    army = army_for_country(session, country_id)
    items = {}

    def add(code, count, rate):
        count = int(count or 0)
        if count > 0 and rate > 0:
            items[code] = {'label': LABELS[code], 'count': count, 'rate': str(_money(rate)), 'amount': _money(Decimal(count) * rate)}

    soldiers = sum(totals(army).values()) if army is not None else 0
    add('soldiers', soldiers, soldier_rate(session, country_id))
    for code in equipment_codes():
        add(code, getattr(army, RESOURCES[code][1]) or 0 if army is not None else 0, Decimal(UPKEEP_RATES[code]) * scale)
    bases = list(session.scalars(select(MilitaryBase).where(MilitaryBase.panstwo_id == country_id)))
    add('silos', sum(1 for base in bases if base.kind == 'nuclear'), SILO_UPKEEP * scale)
    add('warheads', warheads_total(session, country_id), Decimal(UPKEEP_RATES['warheads']) * scale)
    own = own_region_ids(session, country_id)
    surcharge = sum((Decimal(count) * UPKEEP_RATES.get(resource, 0) * (ABROAD_UPKEEP - 1) * scale
                     for base in bases if base.region_id is not None and base.region_id not in own
                     for resource, count in (base.garrison or {}).items() if resource != 'warheads' and UPKEEP_RATES.get(resource)), Decimal(0))
    if surcharge > 0:
        items['abroad'] = {'label': LABELS['abroad'], 'count': None, 'rate': None, 'amount': _money(surcharge)}
    return {'total': _money(sum((item['amount'] for item in items.values()), Decimal(0))), 'items': items}


def serializable(assessment):
    return {'total': str(assessment['total']),
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


def settle(session, country_id, budget, assessment, collected, moment):
    """Po pobraniu utrzymania przy zatwierdzeniu budżetu: demobilizacja niedoboru albo ponowne włączenie silosów;
    rozliczenie okresu (MilitaryMaintenance) bez kosztów w budżecie sił zbrojnych."""
    from game.military_models import MilitaryMaintenance
    from game.models import utc_now
    due = assessment['total']
    collected = Decimal(collected or 0)
    result = {}
    if due > 0 and collected < due:
        result = demobilize(session, country_id, assessment, collected / due, moment)
        _notify(session, country_id, f'Środki budżetu nie wystarczyły na utrzymanie wojska (należne {_fmt(due)} ROI, pobrano {_fmt(collected)} ROI). '
                                     f'Przeprowadzono proporcjonalną demobilizację — {summary_text(result) or "bez zmian"}.')
    else:
        enable_silos(session, country_id)
    budget.military_upkeep_details = {**(budget.military_upkeep_details or {}), 'demobilized': result}
    record = session.scalar(select(MilitaryMaintenance).where(MilitaryMaintenance.panstwo_id == country_id, MilitaryMaintenance.game_year == budget.game_year,
                                                              MilitaryMaintenance.period == budget.period).with_for_update())
    if record is None:
        record = MilitaryMaintenance(panstwo_id=country_id, game_year=budget.game_year, period=budget.period, amount=0)
        session.add(record)
    soldiers = assessment['items'].get('soldiers')
    record.budget_id, record.amount, record.assessed_at = budget.id, Decimal(0), utc_now()
    record.soldier_count = soldiers['count'] if soldiers else 0
    record.soldier_rate = Decimal(soldiers['rate']) if soldiers else Decimal(0)
    record.soldier_fee = soldiers['amount'] if soldiers else Decimal(0)
    record.soldiers_assessed_at = utc_now()
    session.flush()
    return result


def upfront(session, country_id, now=None):
    """Bieżący budżet państwa rozlicza utrzymanie z góry (zatwierdzony po 23 Nov 2026)."""
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
