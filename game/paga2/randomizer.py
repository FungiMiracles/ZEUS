"""Moduł losujący PAGA2: rozstrzyga konflikty, gdy algorytm nie potrafi wybrać między opcjami.

Każde wywołanie jest zapisywane (game_paga2_random_draws), co daje licznik dla panelu administratora.
"""
from random import SystemRandom
from sqlalchemy import select,func
from game.paga2.models import Paga2RandomDraw

TIE_MARGIN=2.0   # opcje różniące się o mniej niż tyle punktów uznajemy za nierozstrzygnięte
_random=SystemRandom()


def tied(scored,margin=TIE_MARGIN):
    """Z listy (klucz, punkty) zwraca opcje w odległości <margin od najlepszej."""
    if not scored:return []
    best=max(score for _,score in scored)
    return [(key,score) for key,score in scored if best-score<margin]


def draw(session,country_id,candidates,*,reason,decision_key=None,rng=None):
    """Losuje jeden klucz z candidates (lista str albo (str, punkty)); zapisuje wywołanie i zwraca wybrany klucz."""
    keys=[item[0] if isinstance(item,(tuple,list)) else item for item in candidates]
    if not keys:raise ValueError('Randomizer wymaga co najmniej jednej opcji.')
    chosen=(rng or _random).choice(keys)
    session.add(Paga2RandomDraw(country_id=country_id,decision_key=(decision_key or '')[:160] or None,reason=str(reason)[:200],
                                candidates=[list(item) if isinstance(item,(tuple,list)) else item for item in candidates],chosen=str(chosen)[:120]))
    session.flush()
    return chosen


def resolve(session,country_id,scored,*,reason,decision_key=None,margin=TIE_MARGIN,rng=None):
    """Zwraca (klucz, czy_losowano). Losuje tylko przy remisie w granicy marginesu."""
    top=tied(scored,margin)
    if not top:return None,False
    if len(top)==1:return top[0][0],False
    return draw(session,country_id,top,reason=reason,decision_key=decision_key,rng=rng),True


def calls(session,country_id=None,since=None):
    query=select(func.count(Paga2RandomDraw.id))
    if country_id is not None:query=query.where(Paga2RandomDraw.country_id==country_id)
    if since is not None:query=query.where(Paga2RandomDraw.created_at>=since)
    return session.scalar(query) or 0
