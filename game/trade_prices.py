"""Granice ceny jednostki towaru w handlu (12 Nov 2026).

Minimum: koszt własny — koszt kopalni/fabryki rozłożony na roczną produkcję (tańszy z wariantów: poziom 1 albo
poziom 3 z sumą kosztów rozbudowy), bez technologii; obniżony o 5%.
Maksimum: koszt wytworzenia u kupującego bez technologii — poziom 1 plus pełna ścieżka badań (punkt rozwoju po
cenie gry) rozłożone na rok produkcji; podwyższone o 10%.
Wyroby: koszt fabryki rozłożony na roczną produkcję plus surowce wejściowe liczone tą samą granicą.
Każda granica jest zaokrąglana do pełnych milionów ROI (minimum ≥ 1 MLN).
"""
from decimal import Decimal
from functools import lru_cache
from math import floor,ceil
from game.industry_catalog import MINE_RULES,FACTORIES,TECHNOLOGIES

MIN_FACTOR=0.95
MAX_FACTOR=1.10
MLN=1_000_000
MIN_PRICE=MLN                      # najniższa cena oferty: 1 MLN ROI


def _point_price():
    from game.research_service import POINT_PRICE
    return float(POINT_PRICE)


def _cycles(days):return 12.0 if days=='month' else 365.0/float(days)


def _chain(code):
    total=0
    while code:
        rule=TECHNOLOGIES[code];total+=rule['cost'];code=rule['parent']
    return total*_point_price()


def _recipe(code):
    for factory in FACTORIES.values():
        for level in factory['levels']:
            if level['product']==code:return level
    return None


def _bound(code,upper,depth=0):
    if code in MINE_RULES:
        label,tech,costs,outputs,days=MINE_RULES[code];n=_cycles(days)
        if upper:return (costs[0]*1e9+_chain(tech))/(outputs[0]*n)
        return min(costs[0]*1e9/(outputs[0]*n),sum(costs)*1e9/(outputs[2]*n))
    rule=_recipe(code)
    if rule is None or depth>5:return None
    per_year=rule['quantity']*_cycles(rule['days'])
    plant=rule['cost']+(_chain(rule['technologies'][0]) if upper else 0)
    inputs=0.0
    for item,amount in rule['inputs'].items():
        value=_bound(item,upper,depth+1)
        if value is None:return None
        inputs+=value*amount
    return plant/per_year+inputs/rule['quantity']


@lru_cache(maxsize=None)
def unit_limits(code):
    """(minimum, maksimum) ceny 1 jednostki w ROI albo None, gdy towar nie ma reguły produkcji."""
    low,high=_bound(code,False),_bound(code,True)
    if low is None or high is None:return None
    minimum=max(MIN_PRICE,floor(low*MIN_FACTOR/MLN)*MLN)
    maximum=max(minimum,ceil(high*MAX_FACTOR/MLN)*MLN)
    return minimum,maximum


def all_limits(codes):
    return {code:{'min':str(limits[0]),'max':str(limits[1])} for code in codes if (limits:=unit_limits(code))}


def check_price(code,quantity,price):
    """Błąd (tekst) albo None. price — łączna cena pakietu w ROI."""
    price=Decimal(price)
    if price<MIN_PRICE:return 'Najniższa cena oferty to 1 MLN ROI.'
    limits=unit_limits(code)
    if limits is None:return None
    low,high=limits
    if price<Decimal(low)*quantity or price>Decimal(high)*quantity:
        return (f'Cena poza dozwolonym zakresem: {fmt(low)}–{fmt(high)} ROI za 1 jednostkę, '
                f'czyli {fmt(low*quantity)}–{fmt(high*quantity)} ROI za {quantity} jedn.')
    return None


def check_offer(cargo,price):
    """Reguły oferty: jeden rodzaj towaru i cena jednostki w granicach. Zwraca tekst błędu albo None."""
    if len(cargo)>1:return 'Oferta może obejmować tylko jeden rodzaj towaru.'
    [(code,quantity)]=cargo.items()
    return check_price(code,quantity,price)


def clamp(code,quantity,price):
    limits=unit_limits(code)
    if limits is None:return max(Decimal(MIN_PRICE),Decimal(price))
    return min(max(Decimal(price),Decimal(limits[0])*quantity),Decimal(limits[1])*quantity)


def fmt(value):
    value=Decimal(value)
    if value>=Decimal(1_000_000_000):return f'{value/Decimal(1_000_000_000):.1f}'.replace('.',',')+' MLD'
    return f'{value/Decimal(MLN):.0f} MLN'
