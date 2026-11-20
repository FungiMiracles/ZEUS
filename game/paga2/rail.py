"""PAGA2 — kolej (19 Nov 2026).

Technologię („Transport kolejowy”) rozwija planer (cel tech:rail_transport w priorytetach infrastruktury i handlu).
Ten adapter, po opracowaniu technologii:
- odpowiada na wnioski sąsiadów o współfinansowanie linii (decyzja wymagana): przyjmuje, gdy relacja z wnioskującym
  jest co najmniej neutralna, nie trwa wojna, a udział mieści się w niewydanych środkach infrastruktury; inaczej odrzuca;
- buduje linie krajowe: łączy najludniejsze miasta spoza głównej sieci z najbliższym miastem tej sieci (bez sieci —
  z najbliższym własnym miastem), gdy zwrot kosztu z dochodów z kolei (PKB per capita × 0,01 × przyrost ludności
  największej spójnej sieci × średnia infrastruktura kolejowa / 100, na cykl) jest dostatecznie szybki; trasa
  przechodząca obok innego miasta jest dzielona (A→B, potem B→C). 20 Nov 2026: bonus liczy tylko spójną sieć
  (game.rail.main_network), więc oderwany odcinek nie daje dochodu i nie jest budowany.
O współfinansowaniu decyduje wyłącznie PAGA2 (model AI nie ma operacji kolejowych).
Wszystko przez ekran i endpointy gracza (/game/kolej/…).
"""
from math import hypot
from uuid import uuid5, NAMESPACE_URL
from game.paga2.engine import Adapter, register
from game.paga2.scoring import Option
from game.paga2.finance import result, relation_factor
from game.rail import main_network

MAX_BUILDING = 5          # jednocześnie budowane własne linie (najwyżej jedna nowa na przebieg)
CANDIDATES = 2            # wycen (zapytań) na przebieg
MAX_PAYBACK_CYCLES = 12   # przy przeciętnym konserwatyzmie fiskalnym (50)
ESTIMATE_FACTOR = 1.15    # trasa po lądzie dłuższa od odcinka prostego


def rail_screen(ctx):
    return (ctx.screen('rail') or {}).get('data') or {}


def decision_options(ctx, screen):
    options = []
    relations = ctx.situation.get('relations', {})
    wars = set(ctx.situation.get('at_war', []))
    available = ctx.available('infrastructure')
    for line in screen.get('lines') or []:
        if not line.get('awaitingMe'):
            continue
        other = line.get('initiatorId')
        share = float((line.get('shares') or {}).get(str(ctx.country_id), {}).get('cost') or 0)
        relation = (relations.get(other) or {}).get('relation_label') or 'neutralne'
        accept = other not in wars and relation_factor(relation) >= 0 and share <= available
        if accept:
            available -= share
        reason = ('wojna z wnioskującym' if other in wars else f'relacja „{relation}” gorsza niż neutralna' if relation_factor(relation) < 0
                  else 'udział mieści się w budżecie infrastruktury' if accept else 'brak środków w budżecie infrastruktury')
        options.append(Option(key=f'rail:{"accept" if accept else "reject"}:{line["id"]}', domain='economy', action='RAIL_ACCEPT' if accept else 'RAIL_REJECT',
                              label=f'{"Współfinansowanie" if accept else "Odmowa współfinansowania"} linii {line.get("cityAName")} – {line.get("cityBName")} ({line.get("initiator")})',
                              target=other, stance='friendly' if accept else 'neutral', base=5.0,
                              # decyzja wymagana: bez kosztu w ocenie (limity rozwagi nie mogą jej zablokować) — środki sprawdza gra
                              notes=[f'Udział: {share/1e9:.2f} MLD ROI; {reason}.'],
                              payload={'line_id': line['id'], 'group': f'rail:decide:{line["id"]}', 'required': True}))
    return options


def _edges(screen):
    """Linie ukończone i w budowie (po ukończeniu wejdą do sieci)."""
    return [(l['cityA'], l['cityB']) for l in screen.get('lines') or [] if l.get('status') == 'ACTIVE']


def network_gain(screen, a, b):
    """Przyrost ludności największej spójnej sieci po dodaniu linii a–b (jak bonus budżetowy, 20 Nov 2026)."""
    population = {c['id']: int(c.get('population') or 0) for c in screen.get('cities') or [] if c.get('own')}
    edges = _edges(screen)
    return main_network(edges + [(a, b)], population)[1] - main_network(edges, population)[1]


def candidates(ctx, screen):
    """Najludniejsze własne miasta spoza głównej sieci, każde z najbliższym miastem tej sieci (bez sieci — z najbliższym
    innym własnym miastem); szacunek długości trasy i przyrostu ludności sieci."""
    own = [c for c in screen.get('cities') or [] if c.get('own')]
    if len(own) < 2:
        return []
    lines = [l for l in screen.get('lines') or [] if l.get('status') in ('ACTIVE', 'PENDING')]
    population = {c['id']: int(c.get('population') or 0) for c in own}
    core = main_network(_edges(screen), population)[0]
    linked = {frozenset((l['cityA'], l['cityB'])) for l in lines}
    km = float(screen.get('kmPerUnit') or 1)
    result_list = []
    for city in sorted((c for c in own if c['id'] not in core), key=lambda c: -c['population'])[:8]:
        others = [o for o in own if o['id'] != city['id'] and frozenset((city['id'], o['id'])) not in linked
                  and (not core or o['id'] in core)]
        if not others:
            continue
        target = min(others, key=lambda o: hypot(o['point'][0] - city['point'][0], o['point'][1] - city['point'][1]))
        distance = hypot(target['point'][0] - city['point'][0], target['point'][1] - city['point'][1]) * km * ESTIMATE_FACTOR
        gain = network_gain(screen, city['id'], target['id'])
        if gain <= 0:
            continue
        result_list.append((gain / max(distance, 1), city, target, gain))
    return sorted(result_list, key=lambda item: -item[0])[:CANDIDATES]


INTERMEDIATE_KM = 20      # miasto leżące tak blisko trasy jest „po drodze”


def _distance_to_path(point, path):
    best = float('inf')
    for a, b in zip(path, path[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = dx * dx + dy * dy
        t = 0.0 if not length else max(0.0, min(1.0, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length))
        best = min(best, hypot(point[0] - (a[0] + t * dx), point[1] - (a[1] + t * dy)))
    return best


def _along(point, path):
    """Odległość wzdłuż trasy do rzutu punktu (do wyboru miasta po drodze najbliższego początkowi)."""
    walked, best = 0.0, (float('inf'), 0.0)
    for a, b in zip(path, path[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = hypot(dx, dy)
        t = 0.0 if not length else max(0.0, min(1.0, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / (length * length)))
        distance = hypot(point[0] - (a[0] + t * dx), point[1] - (a[1] + t * dy))
        if distance < best[0]:
            best = (distance, walked + t * length)
        walked += length
    return best[1]


def staged_quote(ctx, screen, city, target, depth=3):
    """19 Nov 2026: bez linii „bez sensu” — gdy trasa A→C przechodzi obok miasta B (≤ 20 km), budujemy najpierw A→B
    (potem B→C w kolejnym przebiegu). Zwraca (wycena, miasto docelowe) albo (None, None)."""
    km = float(screen.get('kmPerUnit') or 1)
    own = [c for c in screen.get('cities') or [] if c.get('own')]
    linked = {frozenset((l['cityA'], l['cityB'])) for l in screen.get('lines') or [] if l.get('status') in ('ACTIVE', 'PENDING')}
    for _ in range(depth):
        status, quote = ctx.call('/game/kolej/wycena', json={'city_a': city['id'], 'city_b': target['id']})
        if status >= 400 or not isinstance(quote, dict) or quote.get('partnerId'):
            return None, None
        path = quote['path']
        between = [c for c in own if c['id'] not in (city['id'], target['id']) and frozenset((city['id'], c['id'])) not in linked
                   and _distance_to_path(c['point'], path) * km <= INTERMEDIATE_KM]
        if not between:
            return quote, target
        target = min(between, key=lambda c: _along(c['point'], path))
    return None, None


def build_options(ctx, screen):
    lines = screen.get('lines') or []
    if sum(1 for l in lines if l.get('own') and l.get('status') == 'ACTIVE' and not l.get('completed')) >= MAX_BUILDING:
        return []
    gdp_pc = float(screen.get('gdpPerCapita') or 0)
    if gdp_pc <= 0:
        return []
    conservatism = ctx.traits.get('fiscal_conservatism', 50)
    limit = MAX_PAYBACK_CYCLES * (1.5 - conservatism / 100)      # 50 → 12 cykli, 90 → 7,2, 10 → 16,8
    available = ctx.available('infrastructure')
    options = []
    core = main_network(_edges(screen), {c['id']: int(c.get('population') or 0) for c in screen.get('cities') or [] if c.get('own')})[0]
    for _, city, target, gain in candidates(ctx, screen):
        # 20 Nov 2026: od strony sieci — miasto „po drodze” dochodzi do sieci (sieć→B, potem B→A), a nie tworzy oderwanego odcinka
        if target['id'] in core:
            city, target = target, city
        quote, target = staged_quote(ctx, screen, city, target)
        if quote is None:
            continue
        gain = network_gain(screen, city['id'], target['id'])
        if gain <= 0:
            continue
        cost = float(quote['cost'])
        income = gdp_pc * 0.01 * gain * float(screen.get('railInfrastructure') or 0) / 100   # jak bonus budżetowy
        payback = cost / income if income else float('inf')
        if payback > limit or cost > available * .6:
            continue
        options.append(Option(key=f'rail:build:{city["id"]}:{target["id"]}', domain='economy', action='RAIL_BUILD',
                              label=f'Linia kolejowa {city["name"]} – {target["name"]} ({float(quote["distanceKm"]):.0f} km)',
                              effects={'infrastructure': .9, 'financial_stability': .5, 'trade': .3},
                              traits={'industrialism': .4, 'fiscal_conservatism': -.2, 'ambition': .2},
                              cost=cost, sector='infrastructure', base=3.0 + max(0.0, (limit - payback) / limit) * 3,
                              notes=[f'Koszt {cost/1e9:.2f} MLD ROI, dochody z kolei +{income/1e9:.2f} MLD na cykl, zwrot po {payback:.1f} cyklu(ach).'],
                              payload={'city_a': city['id'], 'city_b': target['id'], 'expected_cost': quote['cost'], 'group': 'rail:build'}))
    return options


def propose(ctx):
    """Decyzje o współfinansowaniu zapadają zawsze (także bez własnej technologii i w przebiegach natychmiastowych po
    powiadomieniu); budowa — tylko w przebiegu cyklicznym i po opracowaniu technologii."""
    screen = rail_screen(ctx)
    options = decision_options(ctx, screen)
    if screen.get('available') and getattr(ctx, 'mode', 'CYCLIC') == 'CYCLIC':
        options += build_options(ctx, screen)
    return options


def execute(ctx, option):
    p = option.payload
    if option.action in ('RAIL_ACCEPT', 'RAIL_REJECT'):
        status, data = ctx.call('/game/kolej/zmien', json={'action': 'accept' if option.action == 'RAIL_ACCEPT' else 'reject', 'line_id': p['line_id']})
        return result(status, data)
    if option.action == 'RAIL_BUILD':
        key = str(uuid5(NAMESPACE_URL, f'paga2:{ctx.request_key}:{option.key}'))
        status, data = ctx.call('/game/kolej/zmien', json={'action': 'build', 'city_a': p['city_a'], 'city_b': p['city_b'],
                                                          'expected_cost': p['expected_cost'], 'request_id': key})
        return result(status, data)
    return {'status': 400, 'error': 'Nieznana operacja kolejowa.'}


ADAPTER = register(Adapter(name='rail', modes=('CYCLIC', 'IMMEDIATE'), propose=propose, execute=execute))
