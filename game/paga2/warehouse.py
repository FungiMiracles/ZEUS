"""PAGA2 — lokalizacja magazynu państwa (22 Nov 2026).

Państwo PAGA2 samo wybiera miasto magazynu (ekran /game/magazyn/stan, zapis /game/magazyn/lokalizacja — jak gracz).
Ocena miasta zależy od charakteru państwa:
- skłonność do handlu ceni miasta portowe (handel morski bez dowozu koleją), miasta w sieci kolejowej (kolej
  magazyn → magazyn, dowóz do portów i lotnisk) i miasta z lotniskiem;
- ostrożność (izolacjonizm, militaryzm) ceni stolicę — najlepiej bronione miasto;
- większe miasto ma niewielką przewagę.
Bez magazynu decyzja jest wymagana (jedna z najlepszych kandydatur — wybiera zwykła punktacja profilu). Wybrany magazyn
państwo zmienia najwyżej raz na RECONSIDER_DAYS dni Entendy i tylko wtedy, gdy inne miasto jest wyraźnie lepsze.
"""
from game.paga2.engine import Adapter, register
from game.paga2.scoring import Option
from game.paga2.finance import result

PATH = '/game/magazyn/lokalizacja'
CANDIDATES = 3
RECONSIDER_DAYS = 180
RECONSIDER_MARGIN = 2.0


def warehouse_screen(ctx):
    return (ctx.screen('warehouse') or {}).get('data') or {}


def value(ctx, city, largest):
    t = ctx.traits
    trade = t.get('trade_propensity', 50) / 100 * (3.0 * city.get('port', False) + 2.0 * city.get('rail', False) + 1.5 * city.get('airport', False))
    caution = (t.get('isolationism', 50) + t.get('militarism', 50)) / 200 * 2.5 * city.get('capital', False)
    size = int(city.get('population') or 0) / max(1, largest)
    return trade + caution + size


def describe(city):
    parts = [name for flag, name in (('capital', 'stolica'), ('port', 'port'), ('rail', 'sieć kolejowa'), ('airport', 'lotnisko')) if city.get(flag)]
    return ', '.join(parts) or 'miasto bez portu, kolei i lotniska'


def options_for(ctx, screen):
    cities = screen.get('cities') or []
    if not cities:
        return []
    largest = max(int(c.get('population') or 0) for c in cities)
    ranked = sorted(cities, key=lambda c: (-value(ctx, c, largest), -int(c.get('population') or 0), c['id']))
    current = screen.get('current')
    if current is None:
        chosen, required = ranked[:CANDIDATES], True
    else:
        from game.paga2.trade import recent_policy
        mine = next((c for c in cities if c['id'] == current), None)
        best = ranked[0]
        if mine is None or best['id'] == current or recent_policy(ctx, 'WAREHOUSE_SET', RECONSIDER_DAYS):
            return []
        if value(ctx, best, largest) - value(ctx, mine, largest) < RECONSIDER_MARGIN:
            return []
        chosen, required = [best], False
    options = []
    for city in chosen:
        score = value(ctx, city, largest)
        options.append(Option(key=f'warehouse:{city["id"]}', domain='trade', action='WAREHOUSE_SET',
                              label=f'Magazyn państwa w mieście {city["name"]} ({describe(city)})',
                              effects={'trade': .6 if (city.get('port') or city.get('rail')) else .2, 'defensive_army': .3 if city.get('capital') else 0},
                              traits={'trade_propensity': .7 if (city.get('port') or city.get('rail') or city.get('airport')) else -.2,
                                      'isolationism': .5 if city.get('capital') else -.1},
                              base=2.0 + score, notes=[f'Ocena lokalizacji {score:.2f}: {describe(city)}; ludność {int(city.get("population") or 0):,}.'.replace(',', ' ')],
                              payload={'city_id': city['id'], 'group': 'warehouse', 'required': required}))
    return options


def propose(ctx):
    screen = warehouse_screen(ctx)
    return options_for(ctx, screen) if screen else []


def execute(ctx, option):
    if option.action != 'WAREHOUSE_SET':
        return {'status': 400, 'error': 'Nieznana operacja magazynu.'}
    status, data = ctx.call(PATH, json={'city_id': option.payload['city_id']})
    return result(status, data)


ADAPTER = register(Adapter(name='warehouse', modes=('CYCLIC',), propose=propose, execute=execute))
