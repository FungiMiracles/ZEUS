"""PAGA2 — porty lotnicze (20 Nov 2026).

Technologię („Transport lotniczy”) rozwija planer (cel tech:air_transport w priorytetach infrastruktury i handlu).
Ten adapter, po opracowaniu technologii, buduje porty lotnicze przez ekran i endpointy gracza (/game/lotniska/…):
- najwyżej jedna budowa naraz i najwyżej MAX_AIRPORTS lotnisk państwa;
- miasto: najludniejsze dozwolone miasto bez lotniska (powyżej 100 000 mieszkańców; bez takich — największe miasto);
- warunki: komplet surowców i chipów w magazynie (1400 kamienia, 200 żelaza, 5 prostych chipów) oraz
  koszt (ludność × 100 ROI) nie większy niż 60% niewydanych środków infrastruktury;
- opłacalność: dochód z połączeń (każde czynne lotnisko świata daje co najmniej ludność miasta × 10 ROI na cykl) zwraca
  koszt w rozsądnej liczbie cykli zależnej od konserwatyzmu fiskalnego; pierwsze lotnisko świata (brak połączeń) —
  tylko gdy kosztuje najwyżej 20% środków infrastruktury;
- nazwa: domyślna „Port lotniczy {miasto} – {kod miasta}” (adapter nie podaje nazwy).
Zakup ofert handlowych drogą lotniczą obsługuje adapter handlu (game.paga2.trade). Połączeń PAGA2 nie zawiesza.
"""
from uuid import uuid5, NAMESPACE_URL
from game.paga2.engine import Adapter, register
from game.paga2.scoring import Option
from game.paga2.finance import result
from game.paga2.rail import trade_factor, trade_bonus, FAST_PAYBACK_CYCLES   # 22 Nov 2026: skłonność do handlu jak przy kolei

PATH = '/game/lotniska/zmien'
MAX_AIRPORTS = 3
MAX_PAYBACK_CYCLES = 12
FIRST_AIRPORT_SHARE = .2


def airport_screen(ctx):
    return (ctx.screen('airports') or {}).get('data') or {}


def candidate(screen):
    cities = [c for c in screen.get('cities') or [] if c.get('eligible') and not c.get('hasAirport')]
    return max(cities, key=lambda c: (int(c.get('population') or 0), -int(c['id']))) if cities else None


def build_options(ctx, screen):
    airports = screen.get('airports') or []
    # 22 Nov 2026: państwa skłonne do handlu budują więcej lotnisk (skłonność ≥ 75 → 4, ≤ 25 → 2)
    most = MAX_AIRPORTS + (1 if ctx.traits.get('trade_propensity', 50) >= 75 else -1 if ctx.traits.get('trade_propensity', 50) <= 25 else 0)
    if not screen.get('available') or len(airports) >= most or any(not a.get('completed') for a in airports):
        return []
    if any(int(m.get('have') or 0) < int(m.get('need') or 0) for m in screen.get('materials') or []):
        return []
    city = candidate(screen)
    if city is None:
        return []
    cost = float(city.get('cost') or 0)
    available = ctx.available('infrastructure')
    if cost <= 0 or cost > available * .6:
        return []
    others = max(0, int(screen.get('worldAirports') or 0) - sum(1 for a in airports if a.get('operational')))
    income = others * int(city.get('population') or 0) * float(screen.get('incomePerResident') or 10)
    conservatism = ctx.traits.get('fiscal_conservatism', 50)
    trade = trade_factor(ctx)
    limit = MAX_PAYBACK_CYCLES * (1.5 - conservatism / 100) * trade
    if income <= 0:
        if cost > available * FIRST_AIRPORT_SHARE * trade:
            return []
        payback, note = None, 'Brak innych lotnisk na świecie — połączenia powstaną, gdy zbudują je inne państwa.'
    else:
        payback = cost / income
        if payback > limit:
            return []
        note = f'Dochód z połączeń co najmniej {income/1e9:.2f} MLD na cykl, zwrot po {payback:.1f} cyklu(ach).'
    base = 3.0 + (max(0.0, (limit - payback) / limit) * 3 if payback is not None else 0.5) + trade_bonus(ctx)
    return [Option(key=f'airport:build:{city["id"]}', domain='economy', action='AIRPORT_BUILD',
                   label=f'Port lotniczy w mieście {city["name"]}',
                   effects={'infrastructure': .9, 'financial_stability': .4, 'trade': .5},
                   traits={'industrialism': .3, 'fiscal_conservatism': -.2, 'ambition': .3, 'trade_propensity': .6},
                   cost=cost, sector='infrastructure', base=base,
                   notes=[f'Koszt {cost/1e9:.2f} MLD ROI oraz surowce i chipy z magazynu. {note}'],
                   payload={'city_id': city['id'], 'expected_cost': city['cost'], 'group': 'airport:build',
                            'fast_payback': payback is not None and payback <= FAST_PAYBACK_CYCLES})]


def propose(ctx):
    screen = airport_screen(ctx)
    return build_options(ctx, screen) if screen else []


def execute(ctx, option):
    if option.action != 'AIRPORT_BUILD':
        return {'status': 400, 'error': 'Nieznana operacja lotniskowa.'}
    p = option.payload
    key = str(uuid5(NAMESPACE_URL, f'paga2:{ctx.request_key}:{option.key}'))
    status, data = ctx.call(PATH, json={'action': 'build', 'city_id': p['city_id'], 'expected_cost': p['expected_cost'], 'request_id': key})
    return result(status, data)


ADAPTER = register(Adapter(name='airports', modes=('CYCLIC',), propose=propose, execute=execute))
