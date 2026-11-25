"""Obiekty miejskie — etap 1 (administrator, 21 Nov 2026).

Zakładka „Miasta” na ekranie „Infrastruktura i energetyka”: mapa państwa z miastami (ikona MIASTO.svg, stolica na złoto),
okno zarządzania miastem z budżetami sektorów, katalogiem obiektów i siatką 8×8 kratek (przeciągnij obiekt na kratkę
albo — na telefonie — kliknij obiekt, potem kratkę).

Zasady:
- budowa: koszt z niewydanych środków sektora finansującego obiekt w bieżącym okresie; brakującą część pokrywa rezerwa
  budżetowa (gracz widzi podział w oknie potwierdzenia); jedna budowla na kratkę;
- utrzymanie: przy zatwierdzeniu budżetu (game.finance_service.approve_in_transaction) roczne koszty obiektów działających
  na koniec poprzedniego okresu, przeliczone na jego długość (kwartał — ¼, półrocze — ½), są pobierane z budżetów sektorów
  za poprzedni okres (od 25 Nov 2026; wcześniej z góry za bieżący); brakującą część
  pokrywa rezerwa budżetowa, a gdy i jej brakuje — obiekty sektora przechodzą (od najtańszego w utrzymaniu) w status
  „Niedofinansowany”, aż koszt zmieści się w środkach: obiekt zostaje, ale nie daje efektów i nie jest opłacany; przy
  kolejnym zatwierdzeniu budżetu odzyskuje finansowanie, jeśli wystarczy środków (21 Nov 2026; wcześniej likwidacja);
- likwidacja przez gracza: zwrot 25% kosztu budowy do budżetu sektora, z którego obiekt był finansowany (bieżący okres);
- efekty (liczone z działających obiektów w miastach państwa; obsłużeni mieszkańcy w mieście nie więcej niż ludność
  miasta): zdrowie publiczne +1 za każdy 1 mln objętych opieką (klinika, szpital); poziom edukacji +1 za każdy 1 mln
  objętych edukacją szkolną i osobno +1 za każdy 1 mln objętych edukacją wyższą; zadowolenie społeczne +1 za każde 2 mln
  objętych komunikacją publiczną (tramwaj, autobus, metro); spójność społeczna i tożsamość narodowa +1 za każdy monument;
  roczny przyrost ludności +0,01 pkt proc. za każdy żłobek (najwyżej +0,20) — engine.demography;
- poziom edukacji powyżej 50 skraca czas rozwoju technologii o (poziom / 5)% — game.research_timing.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4
from flask import Blueprint, jsonify, request
from sqlalchemy import select, func, inspect
from sqlalchemy.orm import Session
from extensions import db
from models import Miasto, Panstwo, Spoleczenstwo
from game.models import utc_now
from game.finance_service import FinanceError, FinanceConflict, _country_for_user, game_now, period_key, period_months
from game.budget_transfers import precise
from game.governance import controlled_ids
from game.city_models import CityBuilding, CityExpense, CityEffectState

cities_bp = Blueprint('game_cities', __name__, url_prefix='/game/miasta')

GRID = 8
CELLS = GRID * GRID
REFUND_SHARE = Decimal('0.25')
MLN = 1_000_000

SECTORS = {'healthcare': 'Ochrona zdrowia', 'education': 'Edukacja', 'infrastructure': 'Infrastruktura',
           'social_policy': 'Polityka socjalna i prorodzinna'}
GROUPS = {'health': 'Ochrona zdrowia', 'education': 'Edukacja', 'transport': 'Komunikacja miejska', 'social': 'Żłobki', 'culture': 'Monumenty'}

# kod: (nazwa, ikona, koszt, dni budowy, roczne utrzymanie, obsługiwani mieszkańcy, sektor, grupa, opis efektu)
CATALOG = {
    'clinic': ('Klinika', 'CLINIC.svg', 25 * MLN, 14, 5 * MLN, 25_000, 'healthcare', 'health',
               'Każdy 1 mln obywateli objętych opieką zdrowotną: zdrowie publiczne +1.'),
    'hospital': ('Szpital', 'SZPITAL.svg', 400 * MLN, 30, 50 * MLN, 1_250_000, 'healthcare', 'health',
                 'Każdy 1 mln obywateli objętych opieką zdrowotną: zdrowie publiczne +1.'),
    'nursery': ('Żłobek', 'NURSERY.svg', 15 * MLN, 14, 3 * MLN, None, 'social_policy', 'social',
                'Każdy żłobek w kraju: roczny przyrost ludności +0,01% (łącznie najwyżej +0,20%).'),
    'school': ('Szkoła', 'SZKOŁA.svg', 50 * MLN, 28, 12 * MLN, 50_000, 'education', 'education',
               'Każdy 1 mln obywateli objętych edukacją szkolną: poziom edukacji +1.'),
    'university': ('Uniwersytet', 'UNIWERSYTET.svg', 500 * MLN, 90, 70 * MLN, 500_000, 'education', 'education',
                   'Każdy 1 mln obywateli objętych edukacją wyższą: poziom edukacji +1.'),
    'tram': ('Komunikacja tramwajowa', 'TRAMWAJ.svg', 250 * MLN, 60, 30 * MLN, 300_000, 'infrastructure', 'transport',
             'Każde 2 mln obywateli objętych komunikacją publiczną: zadowolenie społeczne +1.'),
    'bus': ('Komunikacja autobusowa', 'AUTOBUS.svg', 50 * MLN, 21, 15 * MLN, 150_000, 'infrastructure', 'transport',
            'Każde 2 mln obywateli objętych komunikacją publiczną: zadowolenie społeczne +1.'),
    'metro': ('Metro', 'METRO.svg', 1500 * MLN, 120, 150 * MLN, 1_000_000, 'infrastructure', 'transport',
              'Każde 2 mln obywateli objętych komunikacją publiczną: zadowolenie społeczne +1.'),
    'monument': ('Monument', 'MONUMENT.svg', 200 * MLN, 60, 5 * MLN, None, 'infrastructure', 'culture',
                 'Każdy monument w kraju: spójność społeczna i tożsamość narodowa +1.'),
}
NURSERY_BONUS = Decimal('0.01')       # punkt procentowy rocznego przyrostu za żłobek
NURSERY_BONUS_MAX = Decimal('0.20')
EFFECT_FIELDS = {'zdrowie_publiczne': 'Zdrowie publiczne', 'poziom_edukacji': 'Poziom edukacji', 'zadowolenie_spoleczne': 'Zadowolenie społeczne',
                 'spojnosc_spoleczna': 'Spójność społeczna', 'tozsamosc_narodowa': 'Tożsamość narodowa'}


def rule(kind):
    item = CATALOG.get(kind)
    if item is None:
        raise FinanceError('Nieznany rodzaj obiektu miejskiego.')
    label, icon, cost, days, upkeep, served, sector, group, effect = item
    return {'kind': kind, 'label': label, 'icon': icon, 'cost': Decimal(cost), 'days': days, 'maintenance': Decimal(upkeep),
            'served': served, 'sector': sector, 'group': group, 'effect': effect}


def tables_ready(session):
    return inspect(session.connection()).has_table(CityBuilding.__tablename__)


def _money(value):
    return Decimal(value).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)


def _own_ids(session, country):
    return list(controlled_ids(session, country)) or [country]


def own_cities(session, country, with_points=True):
    """Miasta państwa (także kontrolowanych terytoriów) widoczne na mapie."""
    from game.military_geography import city_point
    rows = session.execute(select(Miasto.miasto_id, Miasto.miasto_nazwa, Miasto.miasto_kod, Miasto.miasto_populacja, Miasto.region_id, Miasto.miasto_typ_id)
                           .where(Miasto.panstwo_id.in_(_own_ids(session, country)), Miasto.czy_na_mapie == 'TAK').order_by(Miasto.miasto_id)).all()
    result = []
    for row in rows:
        point = city_point(row.miasto_id) if with_points else None
        if with_points and point is None:
            continue
        result.append({'id': row.miasto_id, 'name': row.miasto_nazwa, 'code': row.miasto_kod, 'population': int(row.miasto_populacja or 0),
                       'regionId': row.region_id, 'capital': row.miasto_typ_id == 1,
                       'point': [float(point[0]), float(point[1])] if point else None})
    return result


def _buildings(session, city_ids, *, lock=False):
    if not city_ids or not tables_ready(session):
        return []
    query = select(CityBuilding).where(CityBuilding.miasto_id.in_(list(city_ids)), CityBuilding.removed_at.is_(None)).order_by(CityBuilding.id)
    return list(session.scalars(query.with_for_update() if lock else query))


def operational(building, now):
    return building.removed_at is None and building.ready_at <= now


def effective(building, now):
    """Obiekt daje efekty: działa i nie jest niedofinansowany."""
    return operational(building, now) and getattr(building, 'underfunded_at', None) is None


# ---------- efekty ----------

def coverage(session, country, now=None, cities=None, buildings=None):
    """Obsłużeni mieszkańcy miast (w mieście nie więcej niż jego ludność) i wynikające z nich efekty."""
    now = now or game_now()
    cities = cities if cities is not None else own_cities(session, country, with_points=False)
    population = {c['id']: c['population'] for c in cities}
    buildings = buildings if buildings is not None else _buildings(session, population.keys())
    served = {}
    counts = {kind: 0 for kind in CATALOG}
    for b in buildings:
        if b.miasto_id not in population or not effective(b, now):
            continue
        counts[b.kind] += 1
        amount = CATALOG[b.kind][5] or 0
        key = {'clinic': 'health', 'hospital': 'health', 'school': 'school', 'university': 'university',
               'tram': 'transport', 'bus': 'transport', 'metro': 'transport'}.get(b.kind)
        if key:
            served.setdefault(b.miasto_id, {}).setdefault(key, 0)
            served[b.miasto_id][key] += amount
    total = {'health': 0, 'school': 0, 'university': 0, 'transport': 0, 'education': 0}
    for city_id, values in served.items():
        pop = population[city_id]
        for key in ('health', 'school', 'university', 'transport'):
            total[key] += min(pop, values.get(key, 0))
        total['education'] += min(pop, values.get('school', 0) + values.get('university', 0))
    urban = sum(population.values())
    percent = lambda value: round(100 * value / urban, 1) if urban else 0.0
    nurseries = counts['nursery']
    targets = {'zdrowie_publiczne': total['health'] // MLN,
               'poziom_edukacji': total['school'] // MLN + total['university'] // MLN,
               'zadowolenie_spoleczne': total['transport'] // (2 * MLN),
               'spojnosc_spoleczna': counts['monument'], 'tozsamosc_narodowa': counts['monument']}
    return {'urbanPopulation': urban, 'served': total, 'counts': counts,
            'percent': {'education': percent(total['education']), 'health': percent(total['health']), 'transport': percent(total['transport'])},
            'nurseryBonus': min(NURSERY_BONUS_MAX, NURSERY_BONUS * nurseries), 'targets': targets}


def nursery_growth_bonus(session, country, now=None):
    """Dodatek do rocznego przyrostu ludności (punkty procentowe) — engine.demography."""
    if not tables_ready(session):
        return Decimal(0)
    return coverage(session, country, now)['nurseryBonus']


def sync_effects(session, country, now=None):
    """Doprowadza wskaźniki społeczne do stanu wynikającego z działających obiektów (dodaje tylko różnicę)."""
    if not tables_ready(session):
        return {}
    targets = coverage(session, country, now)['targets']
    state = session.get(CityEffectState, country, with_for_update=True)
    applied = dict(state.applied or {}) if state else {}
    if all(int(applied.get(field, 0)) == int(value) for field, value in targets.items()):
        return applied
    society = session.scalar(select(Spoleczenstwo).where(Spoleczenstwo.panstwo_id == country).with_for_update())
    if society is None:
        return applied
    for field, target in targets.items():
        wanted = int(target) - int(applied.get(field, 0))
        if not wanted:
            continue
        current = int(getattr(society, field) or 0)
        updated = max(0, min(100, current + wanted))
        setattr(society, field, updated)
        applied[field] = int(applied.get(field, 0)) + (updated - current)   # przy granicy 0–100 dodawana jest tylko część
    if state is None:
        session.add(CityEffectState(panstwo_id=country, applied=applied, updated_at=utc_now()))
    else:
        state.applied, state.updated_at = applied, utc_now()
    session.flush()
    return applied


def education_level(session, country):
    return int(session.scalar(select(Spoleczenstwo.poziom_edukacji).where(Spoleczenstwo.panstwo_id == country)) or 0)


# ---------- powiadomienia i ukończenie budów ----------

def notify(session, country, text):
    from game.paga_ai_actor import country_user_id
    from game.forum_models import GameNotification
    owner = country_user_id(session, country)
    if owner is not None:
        session.add(GameNotification(user_id=owner, notification_type='SYSTEM', system_text='Miasta: ' + text, created_at=utc_now()))


def _city_names(session, ids):
    return dict(session.execute(select(Miasto.miasto_id, Miasto.miasto_nazwa).where(Miasto.miasto_id.in_(list(ids) or [0]))).all())


def settle(session, country=None, now=None):
    """Powiadomienia o ukończonych budowach i aktualizacja efektów (bez commit)."""
    if not tables_ready(session):
        return
    now = now or game_now()
    query = select(CityBuilding).where(CityBuilding.removed_at.is_(None), CityBuilding.completed_notified.is_(False), CityBuilding.ready_at <= now)
    if country is not None:
        city_ids = select(Miasto.miasto_id).where(Miasto.panstwo_id.in_(_own_ids(session, country)))
        query = query.where(CityBuilding.miasto_id.in_(city_ids))
    due = list(session.scalars(query.order_by(CityBuilding.id).with_for_update(skip_locked=True)))
    owners = {}
    if due:
        names = _city_names(session, {b.miasto_id for b in due})
        city_owner = dict(session.execute(select(Miasto.miasto_id, Miasto.panstwo_id).where(Miasto.miasto_id.in_({b.miasto_id for b in due}))).all())
        from game.governance import controller_id
        for building in due:
            building.completed_notified = True
            owner = controller_id(session, city_owner.get(building.miasto_id)) or building.panstwo_id
            owners[owner] = True
            notify(session, owner, f'zakończono budowę obiektu „{CATALOG[building.kind][0]}” w mieście {names.get(building.miasto_id, "")}.')
    for owner in ({country} if country is not None else set()) | set(owners):
        sync_effects(session, owner, now)
    session.flush()


def run_tick(app):
    """Harmonogram infrastruktury: ukończone budowy wszystkich państw (także PAGA2) i ich efekty."""
    with app.app_context():
        with Session(db.engine) as session, session.begin():
            if tables_ready(session):
                settle(session, None, game_now())


# ---------- budżet ----------

def current_budget(session, country, now=None, lock=False):
    from game.finance_models import StateBudget
    year, period = period_key(now or game_now())
    query = select(StateBudget).where(StateBudget.panstwo_id == country, StateBudget.game_year == year, StateBudget.period == period)
    return session.scalar(query.with_for_update() if lock else query)


def sector_funds(session, budget):
    from game.budget_transfers import sector_balances
    if budget is None:
        return {code: Decimal(0) for code in SECTORS}
    balances = sector_balances(session, budget)
    return {code: balances.get(code, {}).get('remaining', Decimal(0)) for code in SECTORS}


def spent_by_sector(session, budget_id):
    """{sektor: kwota z budżetu}, kwota z rezerwy — dla game.budget_transfers (sector_balances, infrastructure_balance)."""
    if not tables_ready(session):
        return {}, Decimal(0)
    rows = session.execute(select(CityExpense.sector, func.coalesce(func.sum(CityExpense.amount), 0), func.coalesce(func.sum(CityExpense.reserve_amount), 0))
                           .where(CityExpense.budget_id == budget_id).group_by(CityExpense.sector)).all()
    return {sector: Decimal(amount or 0) for sector, amount, _ in rows}, sum((Decimal(reserve or 0) for _, _, reserve in rows), Decimal(0))


def reserve_spent(session, budget_id):
    """Rezerwa budżetowa wydana na obiekty miejskie w danym budżecie (kontrola salda w finance_service)."""
    if not tables_ready(session):
        return Decimal(0)
    return Decimal(session.scalar(select(func.coalesce(func.sum(CityExpense.reserve_amount), 0)).where(CityExpense.budget_id == budget_id)) or 0)


def upkeep_summary(session, country, now=None):
    """Roczne utrzymanie działających obiektów miast z rozbiciem na okres budżetowy (ekran „Podatki i budżet”)."""
    now = now or game_now()
    year, period = period_key(now)
    months = period_months(year, period)
    cities = own_cities(session, country, with_points=False)
    annual = {'education': Decimal(0), 'health': Decimal(0), 'transport': Decimal(0), 'social': Decimal(0), 'culture': Decimal(0)}
    for b in _buildings(session, [c['id'] for c in cities]):
        if operational(b, now):
            annual[CATALOG[b.kind][7]] += Decimal(b.maintenance)
    period_word = 'kwartał' if months == 3 else 'półrocze'
    return {'periodMonths': months, 'periodLabel': period_word,
            'items': [{'code': code, 'label': label, 'annual': str(_money(annual[code])), 'period': str(_money(annual[code] * months / 12))}
                      for code, label in (('education', 'Edukacja'), ('health', 'Ochrona zdrowia'), ('transport', 'Komunikacja miejska'))],
            'other': [{'code': code, 'label': label, 'annual': str(_money(annual[code])), 'period': str(_money(annual[code] * months / 12))}
                      for code, label in (('social', 'Żłobki'), ('culture', 'Monumenty')) if annual[code]]}


def maintenance_due(session, country, months, now=None):
    """25 Nov 2026: {sektor: kwota} utrzymania obiektów istniejących teraz (na koniec poprzedniego okresu) za `months`
    miesięcy — ochrona zdrowia (kliniki, szpitale), edukacja (szkoły, uniwersytety), infrastruktura (komunikacja miejska,
    monumenty), polityka socjalna (żłobki). Bez blokad — podgląd budżetu."""
    result = {code: Decimal(0) for code in SECTORS}
    if not months or not tables_ready(session):
        return result
    now = now or game_now()
    cities = own_cities(session, country, with_points=False)
    for b in _buildings(session, [c['id'] for c in cities]):
        if operational(b, now):
            result[b.sector] += Decimal(b.maintenance)
    return {code: _money(amount * Decimal(months) / 12) for code, amount in result.items()}


def charge_maintenance(session, country, budget, account, now, months=None):
    """Utrzymanie obiektów przy zatwierdzeniu budżetu (w transakcji księgowania, bez commit).
    25 Nov 2026: pobierane za poprzedni okres (`months` — jego długość; 0 — okres już opłacony z góry, wtedy obiekty
    tylko odzyskują finansowanie)."""
    if not tables_ready(session):
        return
    if session.scalar(select(CityExpense.id).where(CityExpense.budget_id == budget.id, CityExpense.kind == 'maintenance').limit(1)):
        return
    settle(session, country, now)
    cities = own_cities(session, country, with_points=False)
    names = {c['id']: c['name'] for c in cities}
    buildings = [b for b in _buildings(session, names.keys(), lock=True) if operational(b, now)]
    if not buildings:
        return
    scale = Decimal(period_months(budget.game_year, budget.period) if months is None else months) / 12
    funds = sector_funds(session, budget)
    changed = False
    for sector in SECTORS:
        items = sorted([b for b in buildings if b.sector == sector], key=lambda b: (Decimal(b.maintenance), Decimal(b.cost), b.id))
        if not items:
            continue
        funded = list(items)                       # niedofinansowane obiekty próbują odzyskać finansowanie
        cost = lambda: _money(sum((Decimal(b.maintenance) for b in funded), Decimal(0)) * scale)
        available = Decimal(funds.get(sector) or 0)
        # Brak środków w sektorze i rezerwie — status „Niedofinansowany” od najtańszego w utrzymaniu.
        while funded and cost() > available + Decimal(account.reserve_balance or 0):
            funded.pop(0)
        for b in items:
            now_under = b not in funded
            if now_under and b.underfunded_at is None:
                b.underfunded_at = now; changed = True
                notify(session, country, f'obiekt „{CATALOG[b.kind][0]}” w mieście {names.get(b.miasto_id, "")} jest niedofinansowany: brak środków na utrzymanie '
                                         f'(budżet: {SECTORS[sector].lower()}, rezerwa budżetowa). Obiekt nie daje efektów do czasu odzyskania finansowania.')
            elif not now_under and b.underfunded_at is not None:
                b.underfunded_at = None; changed = True
                notify(session, country, f'obiekt „{CATALOG[b.kind][0]}” w mieście {names.get(b.miasto_id, "")} odzyskał finansowanie i znów działa.')
        total = cost()
        if total <= 0:
            continue
        from_budget = min(total, available)
        from_reserve = total - from_budget
        if from_reserve:
            account.reserve_balance = _money(Decimal(account.reserve_balance) - from_reserve)
        session.add(CityExpense(panstwo_id=country, budget_id=budget.id, kind='maintenance', sector=sector, amount=from_budget, reserve_amount=from_reserve, created_at=utc_now()))
    session.flush()
    if changed:
        sync_effects(session, country, now)


# ---------- budowa i likwidacja ----------

def _cell(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < CELLS:
        raise FinanceError('Wybierz kratkę na planie miasta.')
    return value


def _owned_city(session, country, city_id):
    from game.military_service import natural
    city_id = natural(city_id, 'Miasto', 1)
    city = next((c for c in own_cities(session, country, with_points=False) if c['id'] == city_id), None)
    if city is None:
        raise FinanceError('Miasto nie należy do państwa.')
    return city


def quote(session, country, data, now=None):
    item = rule(data.get('kind'))
    city = _owned_city(session, country, data.get('city_id'))
    cell = _cell(data.get('cell'))
    if any(b.cell == cell for b in _buildings(session, [city['id']])):
        raise FinanceError('Ta kratka jest już zajęta.')
    budget = current_budget(session, country, now)
    if budget is None:
        raise FinanceError('Najpierw zatwierdź budżet bieżącego okresu.')
    from game.finance_models import StateFinancialAccount
    account = session.get(StateFinancialAccount, country)
    available = Decimal(sector_funds(session, budget)[item['sector']])
    reserve = Decimal(account.reserve_balance if account else 0)
    from_budget = min(item['cost'], available)
    from_reserve = item['cost'] - from_budget
    return {**{k: (str(v) if isinstance(v, Decimal) else v) for k, v in item.items()}, 'cityId': city['id'], 'cityName': city['name'], 'cell': cell,
            'sectorLabel': SECTORS[item['sector']], 'available': str(_money(available)), 'reserve': str(_money(reserve)),
            'fromBudget': str(_money(from_budget)), 'fromReserve': str(_money(from_reserve)), 'affordable': from_reserve <= reserve}


@precise
def build(user_id, data):
    from game.mining_service import request_key
    key = request_key(data.get('request_id'))
    with Session(db.engine) as session, session.begin():
        country = _country_for_user(session, user_id, lock=True).PANSTWO_ID
        session.scalar(select(Panstwo.PANSTWO_ID).where(Panstwo.PANSTWO_ID == country).with_for_update())
        if not tables_ready(session):
            raise FinanceError('Obiekty miejskie nie są jeszcze dostępne.')
        existing = session.scalar(select(CityBuilding).where(CityBuilding.panstwo_id == country, CityBuilding.request_id == key))
        if existing:
            return building_data(existing, game_now())
        now = game_now()
        current = quote(session, country, data, now)
        if data.get('expected_cost') is not None and str(data.get('expected_cost')) != current['cost']:
            raise FinanceConflict('Koszt budowy zmienił się. Sprawdź wycenę ponownie.')
        if not current['affordable']:
            raise FinanceError(f'Za mało środków: budżet sektora „{current["sectorLabel"]}” i rezerwa budżetowa łącznie nie pokrywają kosztu budowy.')
        from game.finance_models import StateFinancialAccount
        budget = current_budget(session, country, now, lock=True)
        account = session.scalar(select(StateFinancialAccount).where(StateFinancialAccount.panstwo_id == country).with_for_update())
        from_budget, from_reserve = Decimal(current['fromBudget']), Decimal(current['fromReserve'])
        if from_reserve:
            if account is None or Decimal(account.reserve_balance) < from_reserve:
                raise FinanceError('Za mało środków w rezerwie budżetowej.')
            account.reserve_balance = _money(Decimal(account.reserve_balance) - from_reserve)
        item = rule(current['kind'])
        building = CityBuilding(panstwo_id=country, miasto_id=current['cityId'], kind=item['kind'], cell=current['cell'], cost=item['cost'],
                                maintenance=item['maintenance'], sector=item['sector'], starts_at=now, ready_at=now + timedelta(days=item['days']),
                                user_id=user_id, request_id=key)
        session.add(building)
        session.flush()
        session.add(CityExpense(panstwo_id=country, budget_id=budget.id, building_id=building.id, kind='build', sector=item['sector'],
                                amount=from_budget, reserve_amount=from_reserve, created_at=utc_now()))
        session.flush()
        return building_data(building, now)


@precise
def demolish(user_id, data):
    from game.military_service import natural
    building_id = natural(data.get('building_id'), 'Obiekt', 1)
    with Session(db.engine) as session, session.begin():
        country = _country_for_user(session, user_id, lock=True).PANSTWO_ID
        session.scalar(select(Panstwo.PANSTWO_ID).where(Panstwo.PANSTWO_ID == country).with_for_update())
        building = session.scalar(select(CityBuilding).where(CityBuilding.id == building_id).with_for_update())
        own = {c['id']: c for c in own_cities(session, country, with_points=False)}
        if building is None or building.removed_at is not None or building.miasto_id not in own:
            raise FinanceError('Obiekt nie istnieje albo nie należy do państwa.')
        now = game_now()
        refund = _money(Decimal(building.cost) * REFUND_SHARE)
        budget = current_budget(session, country, now, lock=True)
        if budget is not None:
            session.add(CityExpense(panstwo_id=country, budget_id=budget.id, building_id=building.id, kind='refund', sector=building.sector,
                                    amount=-refund, reserve_amount=0, created_at=utc_now()))
        else:                                   # bez zatwierdzonego budżetu okresu nie ma dokąd zwrócić środków
            refund = Decimal('0.00')
        building.removed_at, building.removal_reason = now, 'demolished'
        session.flush()
        sync_effects(session, country, now)
        notify(session, country, f'zlikwidowano obiekt „{CATALOG[building.kind][0]}” w mieście {own[building.miasto_id]["name"]}; '
                                 f'zwrot {refund:,.0f} ROI do budżetu: {SECTORS[building.sector].lower()}.'.replace(',', ' '))
        return {'id': building.id, 'refund': str(refund), 'sector': building.sector}


# ---------- stan dla ekranu, PAGA2 i administratora ----------

def building_data(b, now):
    total = (b.ready_at - b.starts_at).total_seconds()
    progress = 100 if b.ready_at <= now else max(0, min(99, int((now - b.starts_at).total_seconds() / total * 100))) if total > 0 else 0
    return {'id': b.id, 'cityId': b.miasto_id, 'kind': b.kind, 'label': CATALOG[b.kind][0], 'cell': b.cell, 'cost': str(b.cost),
            'maintenance': str(b.maintenance), 'sector': b.sector, 'completed': b.ready_at <= now, 'progress': progress,
            'underfunded': getattr(b, 'underfunded_at', None) is not None,
            'startsAt': b.starts_at.isoformat() + 'Z', 'readyAt': b.ready_at.isoformat() + 'Z', 'refund': str(_money(Decimal(b.cost) * REFUND_SHARE))}


def catalog_data():
    return [{**{k: (str(v) if isinstance(v, Decimal) else v) for k, v in rule(kind).items()}, 'sectorLabel': SECTORS[CATALOG[kind][6]]} for kind in CATALOG]


def state(session, country, now=None):
    now = now or game_now()
    ready = tables_ready(session)
    cities = own_cities(session, country)
    buildings = _buildings(session, [c['id'] for c in cities]) if ready else []
    cov = coverage(session, country, now, cities=cities, buildings=buildings)
    budget = current_budget(session, country, now)
    from game.finance_models import StateFinancialAccount
    account = session.get(StateFinancialAccount, country)
    per_city = {}
    for b in buildings:
        per_city.setdefault(b.miasto_id, []).append(building_data(b, now))
    from game.research_timing import education_bonus
    return {'available': ready, 'countryId': country, 'grid': GRID, 'gameNow': now.isoformat() + 'Z',
            'funds': {code: str(_money(value)) for code, value in sector_funds(session, budget).items()}, 'sectors': SECTORS,
            'hasBudget': budget is not None, 'reserve': str(_money(Decimal(account.reserve_balance if account else 0))),
            'catalog': catalog_data(), 'refundShare': str(REFUND_SHARE),
            'cities': [{**c, 'buildings': per_city.get(c['id'], [])} for c in cities],
            'coverage': {'percent': cov['percent'], 'served': cov['served'], 'urbanPopulation': cov['urbanPopulation'], 'counts': cov['counts'],
                         'nurseryBonus': str(cov['nurseryBonus']), 'effects': {EFFECT_FIELDS[k]: v for k, v in cov['targets'].items()}},
            'education': education_level(session, country), 'researchBonus': education_bonus(education_level(session, country)),
            'upkeep': upkeep_summary(session, country, now) if ready else None}


def admin_cities(session, country):
    """WIKI → Stan państwa PAGA: obiekty postawione w miastach państwa."""
    if not tables_ready(session):
        return []
    now = game_now()
    cities = own_cities(session, country, with_points=False)
    per_city = {}
    for b in _buildings(session, [c['id'] for c in cities]):
        per_city.setdefault(b.miasto_id, []).append(building_data(b, now))
    return [{'id': c['id'], 'name': c['name'], 'population': c['population'], 'capital': c['capital'], 'buildings': per_city[c['id']]}
            for c in sorted(cities, key=lambda c: (-c['population'], c['id'])) if c['id'] in per_city]


def page_config(country_id):
    """Konfiguracja okna miasta (static/js/game_cities.js) — zakładka „Miasta” i mapa „Świat”; None, gdy moduł niedostępny."""
    from flask import current_app, session as browser, url_for
    import secrets
    if 'game_cities' not in current_app.blueprints:
        return None
    try:
        with Session(db.engine) as orm:
            with orm.begin():
                if not tables_ready(orm):
                    return None
                settle(orm, country_id)
            data = state(orm, country_id)
    except Exception:
        current_app.logger.exception('Miasta: konfiguracja okna miasta')
        return None
    browser.setdefault('game_csrf_token', secrets.token_urlsafe(32))
    icon = lambda name: url_for('static', filename='icons/' + name)
    return {**data, 'stateUrl': url_for('game_cities.state_view'), 'quoteUrl': url_for('game_cities.quote_view'), 'changeUrl': url_for('game_cities.change_view'),
            'previewUrl': url_for('game_cities.preview_view', city_id=0), 'csrf': browser['game_csrf_token'],
            'countriesUrl': url_for('region_sovereignty.country_boundaries'), 'cityIcon': icon('MIASTO.svg'), 'craneIcon': icon('PRACE BUDOWLANE.svg'),
            'icons': {item['kind']: icon(item['icon']) for item in data['catalog']},
            'sectorIcons': {'healthcare': icon('SZPITAL.svg'), 'education': icon('SZKOŁA.svg'), 'infrastructure': icon('INFRASTRUKTURA.svg'),
                            'social_policy': icon('NURSERY.svg'), 'reserve': icon('SKRZYNIA.svg')}}


def preview(session, country, city_id, now=None):
    """Podgląd obiektów dowolnego miasta (mapa „Świat”): bez budżetów; edycja tylko dla miasta własnego państwa."""
    from game.governance import controller_id
    now = now or game_now()
    row = session.get(Miasto, city_id)
    if row is None:
        return None
    owner = controller_id(session, row.panstwo_id) or row.panstwo_id
    buildings = _buildings(session, [city_id]) if tables_ready(session) else []
    return {'id': row.miasto_id, 'name': row.miasto_nazwa, 'population': int(row.miasto_populacja or 0), 'capital': row.miasto_typ_id == 1,
            'own': owner == country, 'country': session.scalar(select(Panstwo.panstwo_nazwa).where(Panstwo.PANSTWO_ID == owner)) or '',
            'buildings': [building_data(b, now) for b in buildings]}


# ---------- trasy HTTP ----------

def _player():
    from game.forum import player
    from game.military import csrf_valid
    user, country = player()
    if user is None:
        return None, None, (jsonify(error='Zaloguj się ponownie.'), 401)
    if request.method == 'POST' and not csrf_valid():
        return None, None, (jsonify(error='Sesja formularza wygasła. Odśwież stronę.'), 403)
    return user, country, None


@cities_bp.get('/stan')
def state_view():
    user, country, error = _player()
    if error:
        return error
    with Session(db.engine) as session:
        with session.begin():
            settle(session, country.PANSTWO_ID)
        response = jsonify(state(session, country.PANSTWO_ID))
    response.headers['Cache-Control'] = 'no-store'
    return response


@cities_bp.get('/podglad/<int:city_id>')
def preview_view(city_id):
    user, country, error = _player()
    if error:
        return error
    with Session(db.engine) as session:
        data = preview(session, country.PANSTWO_ID, city_id)
    if data is None:
        return jsonify(error='Nie znaleziono miasta.'), 404
    response = jsonify(city=data)
    response.headers['Cache-Control'] = 'no-store'
    return response


@cities_bp.post('/wycena')
def quote_view():
    user, country, error = _player()
    if error:
        return error
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error='Nieprawidłowe dane.'), 400
    try:
        with Session(db.engine) as session:
            return jsonify(quote(session, country.PANSTWO_ID, data))
    except FinanceError as exc:
        return jsonify(error=str(exc)), 400


@cities_bp.post('/zmien')
def change_view():
    user, country, error = _player()
    if error:
        return error
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error='Nieprawidłowe dane.'), 400
    db.session.rollback()
    try:
        if data.get('action') == 'build':
            return jsonify(ok=True, building=build(user.id, data))
        if data.get('action') == 'demolish':
            return jsonify(ok=True, result=demolish(user.id, data))
        return jsonify(error='Nieprawidłowa operacja.'), 400
    except FinanceConflict as exc:
        return jsonify(error=str(exc)), 409
    except FinanceError as exc:
        return jsonify(error=str(exc)), 400


def new_request_id():
    return str(uuid4())
