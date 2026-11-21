"""PAGA2 — obiekty miejskie (21 Nov 2026).

Adapter buduje obiekty w miastach przez ekran i endpointy gracza (/game/miasta/…), kierując się priorytetami państwa:
- „Rozwój państwa opiekuńczego” (welfare): kliniki, szpitale, żłobki, szkoły;
- „Rozwój infrastruktury” (infrastructure): komunikacja autobusowa, tramwajowa, metro (i monumenty);
- „Rozwój produkcji i technologii” (production) oraz badań (research): szkoły i uniwersytety (poziom edukacji
  powyżej 50 przyspiesza rozwój technologii);
oraz wskaźnikiem prospołeczności (cecha prosociality) — wyższa wartość sprzyja ochronie zdrowia, żłobkom i edukacji.

Zasady ostrożności:
- najwyżej MAX_BUILDING budów naraz i jedna nowa budowa w przebiegu (grupa 'city:build');
- koszt budowy najwyżej 50% niewydanych środków sektora (bez sięgania po rezerwę budżetową);
- utrzymanie: roczne koszty obiektów sektora (z nowym) / 4 nie więcej niż 35% środków sektora na początku przebiegu —
  inaczej przy zatwierdzeniu budżetu groziłaby likwidacja obiektów z braku środków;
- miasto: największa liczba mieszkańców bez dostępu do danej usługi (obiekty w budowie liczą się jak gotowe);
- kratka: pierwsza wolna na planie 8×8.
"""
from uuid import uuid5, NAMESPACE_URL
from game.paga2.engine import Adapter, register
from game.paga2.scoring import Option
from game.paga2.finance import result

PATH = '/game/miasta/zmien'
MAX_BUILDING = 2
COST_SHARE = .5
UPKEEP_SHARE = .35
MAX_NURSERIES = 20       # więcej żłobków nie zwiększa przyrostu (limit +0,20%)
MAX_MONUMENTS = 3
SERVICE = {'clinic': 'health', 'hospital': 'health', 'school': 'school', 'university': 'university', 'tram': 'transport', 'bus': 'transport', 'metro': 'transport'}
# minimalna liczba mieszkańców bez dostępu, przy której obiekt ma sens (≈ 80% jego pojemności)
MIN_UNSERVED = {'clinic': 20_000, 'hospital': 1_000_000, 'school': 40_000, 'university': 400_000, 'tram': 240_000, 'bus': 120_000, 'metro': 800_000}
EFFECTS = {
    'clinic': ({'welfare': 1.0}, {'prosociality': .8, 'fiscal_conservatism': .1}),
    'hospital': ({'welfare': 1.0, 'financial_stability': -.1}, {'prosociality': .8, 'ambition': .2}),
    'nursery': ({'welfare': .8}, {'prosociality': .7}),
    'school': ({'welfare': .5, 'research': .5, 'production': .5}, {'prosociality': .4}),
    'university': ({'research': .9, 'production': .7, 'welfare': .2}, {'prosociality': .2, 'ambition': .3}),
    'bus': ({'infrastructure': 1.0, 'welfare': .3}, {'prosociality': .2, 'fiscal_conservatism': .1}),
    'tram': ({'infrastructure': 1.0, 'welfare': .3}, {'prosociality': .2}),
    'metro': ({'infrastructure': 1.0, 'welfare': .3, 'financial_stability': -.2}, {'ambition': .4}),
    'monument': ({'infrastructure': .2, 'welfare': .2}, {'ambition': .4}),
}


def city_screen(ctx):
    return (ctx.screen('cities') or {}).get('data') or {}


def _free_cell(city, size):
    taken = {int(b.get('cell')) for b in city.get('buildings') or []}
    return next((cell for cell in range(size * size) if cell not in taken), None)


def build_options(ctx, screen):
    if not screen.get('available') or not screen.get('hasBudget'):
        return []
    cities = screen.get('cities') or []
    buildings = [b for c in cities for b in c.get('buildings') or []]
    if sum(1 for b in buildings if not b.get('completed')) >= MAX_BUILDING:
        return []
    catalog = {item['kind']: item for item in screen.get('catalog') or []}
    if not catalog:
        return []
    size = int(screen.get('grid') or 8)
    upkeep = {}
    for b in buildings:
        upkeep[b.get('sector')] = upkeep.get(b.get('sector'), 0.0) + float(b.get('maintenance') or 0)
    counts = {}
    for b in buildings:
        counts[b.get('kind')] = counts.get(b.get('kind'), 0) + 1
    options = []
    for kind, item in catalog.items():
        sector, cost, yearly = item['sector'], float(item['cost']), float(item['maintenance'])
        available = ctx.available(sector)
        if cost <= 0 or cost > available * COST_SHARE:
            continue
        if (upkeep.get(sector, 0.0) + yearly) / 4 > ctx.sector_start(sector) * UPKEEP_SHARE:
            continue
        best = None
        for city in cities:
            cell = _free_cell(city, size)
            if cell is None:
                continue
            population = int(city.get('population') or 0)
            if kind in SERVICE:
                served = sum(int(catalog[b['kind']].get('served') or 0) for b in city.get('buildings') or []
                             if SERVICE.get(b.get('kind')) == SERVICE[kind] and b.get('kind') in catalog)
                unserved = population - served
                if unserved < MIN_UNSERVED[kind] or (kind == 'metro' and population < 1_500_000):
                    continue
                value = min(unserved, int(item.get('served') or 0))
            elif kind == 'nursery':
                if counts.get('nursery', 0) >= MAX_NURSERIES or population < 100_000 or any(b.get('kind') == 'nursery' for b in city.get('buildings') or []):
                    continue
                value = population
            else:   # monument — w stolicy (albo największym mieście), najwyżej kilka w państwie
                if counts.get('monument', 0) >= MAX_MONUMENTS or any(b.get('kind') == 'monument' for b in city.get('buildings') or []):
                    continue
                value = population * (2 if city.get('capital') else 1)
            if best is None or value > best[0]:
                best = (value, city, cell)
        if best is None:
            continue
        value, city, cell = best
        prosocial = ctx.traits.get('prosociality', 50) / 100
        effects, traits = EFFECTS[kind]
        base = 2.0 + (min(2.0, value / max(1.0, cost / 25_000)) if kind in SERVICE else .8)
        if kind in ('clinic', 'hospital', 'nursery', 'school'):
            base += prosocial
        options.append(Option(key=f'city:build:{kind}:{city["id"]}', domain='economy', action='CITY_BUILD',
                              label=f'{item["label"]} w mieście {city["name"]}', effects=effects, traits=traits,
                              cost=cost, sector=sector, base=base,
                              notes=[f'Koszt {cost/1e6:.0f} mln ROI, utrzymanie {yearly/1e6:.0f} mln ROI rocznie ({item.get("sectorLabel", sector)}). {item.get("effect", "")}'],
                              payload={'kind': kind, 'city_id': city['id'], 'cell': cell, 'expected_cost': item['cost'], 'group': 'city:build'}))
    return options


def propose(ctx):
    screen = city_screen(ctx)
    return build_options(ctx, screen) if screen else []


def execute(ctx, option):
    if option.action != 'CITY_BUILD':
        return {'status': 400, 'error': 'Nieznana operacja miejska.'}
    p = option.payload
    key = str(uuid5(NAMESPACE_URL, f'paga2:{ctx.request_key}:{option.key}'))
    status, data = ctx.call(PATH, json={'action': 'build', 'kind': p['kind'], 'city_id': p['city_id'], 'cell': p['cell'],
                                        'expected_cost': p['expected_cost'], 'request_id': key})
    return result(status, data)


ADAPTER = register(Adapter(name='cities', modes=('CYCLIC',), propose=propose, execute=execute))
