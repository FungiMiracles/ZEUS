"""Wycena towarów PAGA2 (gra nie ma cen referencyjnych).

Wartość jednostki = koszt wytworzenia: koszt kopalni lub fabryki rozłożony na roczną produkcję (spłata w rok)
plus wartość surowców wejściowych; korygowana medianą cen z ofert widocznych na rynku (gdy są co najmniej 2 oferty).
"""
from statistics import median
from game.industry_catalog import MINE_RULES,FACTORIES,POWER_PLANTS

AMMUNITION='interceptor_ammunition'
AMMUNITION_PRICE=15000.0       # cena zakupu amunicji przeciwrakietowej w grze (game/missile_defense.AMMUNITION_PRICE)
_cache={}


def cycles_per_year(days):return 12.0 if days=='month' else 365.0/float(days)


def recipe_for(code):
    for factory in FACTORIES.values():
        for level in factory['levels']:
            if level['product']==code:return level
    return None


def unit_value(code,_depth=0):
    """Koszt wytworzenia jednej jednostki (ROI)."""
    if code in _cache:return _cache[code]
    if code==AMMUNITION:value=AMMUNITION_PRICE
    elif code in MINE_RULES:
        label,tech,costs,outputs,days=MINE_RULES[code]
        value=costs[0]*1e9/(outputs[0]*cycles_per_year(days))
    else:
        rule=recipe_for(code)
        if rule is None or _depth>4:value=1e8
        else:
            per_year=rule['quantity']*cycles_per_year(rule['days'])
            value=rule['cost']/per_year+sum(unit_value(c,_depth+1)*amount for c,amount in rule['inputs'].items())/rule['quantity']
    _cache[code]=value
    return value


def market_factors(offers):
    """Dla każdego towaru mediana relacji: cena oferty / wartość jej ładunku wg kosztu wytworzenia."""
    ratios={}
    for offer in offers or []:
        cargo=offer.get('cargo') or {}
        base=sum(unit_value(c)*q for c,q in cargo.items() if q)
        try:price=float(offer.get('price') or 0)
        except (TypeError,ValueError):continue
        if base<=0 or price<=0:continue
        for code in cargo:ratios.setdefault(code,[]).append(price/base)
    return {code:median(values) for code,values in ratios.items() if len(values)>=2}


def reference(code,factors=None):
    """Wartość rynkowa jednostki: koszt wytworzenia × mediana rynku (ograniczona do 0,5–3×)."""
    factor=(factors or {}).get(code,1.0)
    return unit_value(code)*max(.5,min(3.0,factor))


def cargo_value(cargo,factors=None,weights=None):
    return sum(reference(code,factors)*qty*(weights or {}).get(code,1.0) for code,qty in (cargo or {}).items())


def consumption(holdings,days=60):
    """Zużycie surowców własnych fabryk i elektrowni w zadanym okresie (rezerwa operacyjna)."""
    need={}
    for factory in holdings.factories:
        if factory.get('health',0)<=0 or factory['kind'] not in FACTORIES or FACTORIES[factory['kind']].get('on_demand'):continue   # produkcja na zamówienie
        levels=FACTORIES[factory['kind']]['levels'];rule=levels[min(len(levels),max(1,factory.get('level',1)))-1]
        cycles=days/(30.0 if rule['days']=='month' else float(rule['days']))
        for code,amount in rule['inputs'].items():need[code]=need.get(code,0)+amount*cycles
    for plant in holdings.plants:
        rule=POWER_PLANTS.get(plant['kind'])
        if rule and rule['fuel'] and plant.get('health',0)>0:need[rule['fuel']]=need.get(rule['fuel'],0)+rule['amounts'][plant.get('level',1)-1]*days
    return {code:int(round(value)) for code,value in need.items()}
