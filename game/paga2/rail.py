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
22 Nov 2026: PAGA2 sama występuje z wnioskami o linie do sąsiadów (international_options; +10% dochodów z kolei za
każde obce państwo w sieci), a inwestycje o zwrocie do 4 cykli nie podlegają limitowi jednej akcji.
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
FAST_PAYBACK_CYCLES = 4   # 22 Nov 2026: szybszy zwrot zwalnia z limitu jednej akcji (game.paga2.scoring.check_resources)
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


def trade_factor(ctx):
    """22 Nov 2026: skłonność do handlu wydłuża akceptowany czas zwrotu inwestycji w transport (kolej łączy magazyny,
    porty i lotniska): 0 → ×0,6, 50 → ×1,0, 100 → ×1,4."""
    return 0.6 + 0.8 * ctx.traits.get('trade_propensity', 50) / 100


def trade_bonus(ctx):
    """Premia oceny inwestycji w transport: (skłonność do handlu − 50) / 25 (−2 … +2)."""
    return (ctx.traits.get('trade_propensity', 50) - 50) / 25


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
    trade = trade_factor(ctx)
    limit = MAX_PAYBACK_CYCLES * (1.5 - conservatism / 100) * trade   # 50/50 → 12 cykli; skłonność do handlu 90 → ×1,32 (game.paga2.rail.trade_factor)
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
                              traits={'industrialism': .4, 'fiscal_conservatism': -.2, 'ambition': .2, 'trade_propensity': .6},
                              cost=cost, sector='infrastructure', base=3.0 + max(0.0, (limit - payback) / limit) * 3 + trade_bonus(ctx),
                              notes=[f'Koszt {cost/1e9:.2f} MLD ROI, dochody z kolei +{income/1e9:.2f} MLD na cykl, zwrot po {payback:.1f} cyklu(ach).',
                                     f'Skłonność do handlu {ctx.traits.get("trade_propensity", 50)}: limit zwrotu ×{trade:.2f}.'],
                              payload={'city_a': city['id'], 'city_b': target['id'], 'expected_cost': quote['cost'], 'group': 'rail:build',
                                       'fast_payback': payback <= FAST_PAYBACK_CYCLES}))
    return options


INTERNATIONAL_CANDIDATES = 2   # wycen linii międzynarodowych na przebieg


def international_options(ctx, screen):
    """22 Nov 2026: PAGA2 występuje z wnioskiem o współfinansowanie linii do sąsiada — łączy własną sieć z najbliższym
    miastem sąsiada, z którym nie ma jeszcze połączenia (relacja co najmniej neutralna, bez wojny). Wartość: +10%
    dochodów z kolei za każde obce państwo w sieci (game.rail.PARTNER_BONUS) oraz kolej w handlu (tranzyt, cła).
    Najwyżej jeden oczekujący wniosek naraz; koszt własny = udział w trasie po naszej stronie granicy."""
    from game.rail import PARTNER_BONUS
    lines = screen.get('lines') or []
    if any(l.get('own') and l.get('partnerId') and l.get('status') == 'PENDING' for l in lines):
        return []
    bonus = float(screen.get('bonus') or 0)
    if bonus <= 0:
        return []                     # bez własnej sieci premia za połączenie nic nie daje
    partners = set(screen.get('networkPartners') or [])
    base_income = bonus / (1 + float(PARTNER_BONUS) * len(partners))
    gain = base_income * float(PARTNER_BONUS)
    linked = {l.get('partnerId') if l.get('own') else l.get('initiatorId') for l in lines
              if l.get('partnerId') and l.get('status') in ('PENDING', 'ACTIVE')}
    relations = ctx.situation.get('relations', {})
    wars = set(ctx.situation.get('at_war', []))
    cities = screen.get('cities') or []
    core = set(screen.get('networkCities') or [])
    ours = [c for c in cities if c.get('own') and c['id'] in core]
    pairs = []
    for neighbor in screen.get('neighbors') or []:
        if neighbor in partners or neighbor in linked or neighbor in wars:
            continue
        relation = (relations.get(neighbor) or {}).get('relation_label') or 'neutralne'
        if relation_factor(relation) < 0:
            continue
        theirs = [c for c in cities if c.get('countryId') == neighbor]
        best = min(((hypot(b['point'][0] - a['point'][0], b['point'][1] - a['point'][1]), a, b) for a in ours for b in theirs), default=None, key=lambda item: item[0])
        if best:
            pairs.append((best[0], neighbor, best[1], best[2], relation))
    conservatism = ctx.traits.get('fiscal_conservatism', 50)
    trade = trade_factor(ctx)
    limit = MAX_PAYBACK_CYCLES * (1.5 - conservatism / 100) * trade
    available = ctx.available('infrastructure')
    options = []
    for _, neighbor, city, target, relation in sorted(pairs, key=lambda item: item[0])[:INTERNATIONAL_CANDIDATES]:
        status, quote = ctx.call('/game/kolej/wycena', json={'city_a': city['id'], 'city_b': target['id']})
        if status >= 400 or not isinstance(quote, dict) or quote.get('partnerId') != neighbor:
            continue
        cost = float(((quote.get('shares') or {}).get(str(ctx.country_id)) or {}).get('cost') or quote['cost'])
        payback = cost / gain if gain else float('inf')
        if payback > limit or cost > available * .6:
            continue
        name = (screen.get('countries') or {}).get(str(neighbor), f'państwo {neighbor}')
        options.append(Option(key=f'rail:international:{city["id"]}:{target["id"]}', domain='economy', action='RAIL_INTERNATIONAL', target=neighbor,
                              label=f'Wniosek o wspólną linię {city["name"]} – {target["name"]} ({name}, {float(quote["distanceKm"]):.0f} km)',
                              effects={'infrastructure': .8, 'trade': .7, 'alliances': .3, 'financial_stability': .3},
                              traits={'trade_propensity': .8, 'solidarity': .3, 'isolationism': -.6, 'industrialism': .3},
                              cost=cost, sector='infrastructure', stance='friendly',
                              base=2.0 + max(0.0, (limit - payback) / limit) * 3 + trade_bonus(ctx),
                              notes=[f'Nasz udział {cost/1e9:.2f} MLD ROI; połączenie z siecią sąsiada: +{gain/1e9:.2f} MLD dochodów z kolei na cykl '
                                     f'(+{int(PARTNER_BONUS*100)}%), zwrot po {payback:.1f} cyklu(ach). Relacja: {relation}. Budowa po akceptacji sąsiada.'],
                              payload={'city_a': city['id'], 'city_b': target['id'], 'expected_cost': quote['cost'], 'group': 'rail:international',
                                       'fast_payback': payback <= FAST_PAYBACK_CYCLES}))
    return options


def propose(ctx):
    """Decyzje o współfinansowaniu zapadają zawsze (także bez własnej technologii i w przebiegach natychmiastowych po
    powiadomieniu); budowa — tylko w przebiegu cyklicznym i po opracowaniu technologii."""
    screen = rail_screen(ctx)
    options = decision_options(ctx, screen)
    if screen.get('available') and getattr(ctx, 'mode', 'CYCLIC') == 'CYCLIC':
        options += build_options(ctx, screen) + international_options(ctx, screen)
    return options


def execute(ctx, option):
    p = option.payload
    if option.action in ('RAIL_ACCEPT', 'RAIL_REJECT'):
        status, data = ctx.call('/game/kolej/zmien', json={'action': 'accept' if option.action == 'RAIL_ACCEPT' else 'reject', 'line_id': p['line_id']})
        return result(status, data)
    if option.action in ('RAIL_BUILD', 'RAIL_INTERNATIONAL'):
        key = str(uuid5(NAMESPACE_URL, f'paga2:{ctx.request_key}:{option.key}'))
        status, data = ctx.call('/game/kolej/zmien', json={'action': 'build', 'city_a': p['city_a'], 'city_b': p['city_b'],
                                                          'expected_cost': p['expected_cost'], 'request_id': key})
        return result(status, data)
    return {'status': 400, 'error': 'Nieznana operacja kolejowa.'}


ADAPTER = register(Adapter(name='rail', modes=('CYCLIC', 'IMMEDIATE'), propose=propose, execute=execute))
