"""Bilateral restrictions for ammunition and protected port access."""
from sqlalchemy import select,or_,and_
from models import Stosunki,DictStosunkiRelacja,DictStosunkiStan
from services.natural_resources import normalized

ALLIED={'sojusznicze','partnerskie','partnerskiestrategiczne'}
HOSTILE={'zle','wrogie','egzystencjalniewrogie'}


def pair_labels(session,a,b,*,lock=False):
    actual=session() if callable(session) else session
    token=actual.get_transaction();cached=actual.info.get('trade_pair_labels')
    pair=tuple(sorted((a,b)))
    if not lock and token is not None and cached and cached[0] is token and pair in cached[1]:return cached[1][pair]
    query=select(Stosunki.relacja_id,Stosunki.stan_id).where(or_(and_(Stosunki.PANSTWO_ID==a,Stosunki.PANSTWO_ID2==b),and_(Stosunki.PANSTWO_ID==b,Stosunki.PANSTWO_ID2==a)))
    if lock:query=query.with_for_update()
    rows=list(session.execute(query))
    relations=dict(session.execute(select(DictStosunkiRelacja.relacja_id,DictStosunkiRelacja.relacja_nazwa)).all())
    states=dict(session.execute(select(DictStosunkiStan.stan_id,DictStosunkiStan.stan_nazwa)).all())
    result=[(normalized(relations.get(relation,'')),normalized(states.get(state,''))) for relation,state in rows]
    if not lock:
        token=actual.get_transaction()
        if not cached or cached[0] is not token:cached=(token,{})
        cached[1][pair]=result;actual.info['trade_pair_labels']=cached
    return result


def allied(session,a,b,*,lock=False):
    return any(relation in ALLIED for relation,state in pair_labels(session,a,b,lock=lock))


def ammunition_allowed(session,a,b,*,lock=False):
    return not any(relation in HOSTILE or state=='wojnahybrydowa' or state.startswith('okupacja') or state.startswith('wojnakinetyczna') for relation,state in pair_labels(session,a,b,lock=lock))


def allied_country_ids(session,country_id):
    rows=session.execute(select(Stosunki.PANSTWO_ID,Stosunki.PANSTWO_ID2,DictStosunkiRelacja.relacja_nazwa).join(DictStosunkiRelacja,DictStosunkiRelacja.relacja_id==Stosunki.relacja_id).where(or_(Stosunki.PANSTWO_ID==country_id,Stosunki.PANSTWO_ID2==country_id)))
    return sorted({b if a==country_id else a for a,b,label in rows if normalized(label) in ALLIED})
