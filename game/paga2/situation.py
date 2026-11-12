"""Ocena sytuacji geopolitycznej państwa PAGA2 i jej wpływ na wagę priorytetów.

Źródła: własne stosunki dyplomatyczne (widoczne na ekranie dyplomacji gracza), jawne zdarzenia i własna pamięć,
okupacje widoczne na mapie. Stan wojny przesuwa wagę ku bezpieczeństwu (np. armia ważniejsza niż środowisko).
"""
from datetime import timedelta
from sqlalchemy import select,or_
from models import Stosunki,DictStosunkiRelacja,DictStosunkiStan
from services.natural_resources import normalized

ALLIED=('sojusznicze','partnerskie','partnerskiestrategiczne')
HOSTILE=('zle','wrogie','egzystencjalniewrogie')
# Mnożniki wagi priorytetów w zależności od poziomu zagrożenia.
MULTIPLIERS={
    'peace':{},
    'threat':{'defensive_army':1.6,'intelligence':1.4,'alliances':1.3,'offensive_army':1.2,'environment':.8,'welfare':.9},
    'war':{'defensive_army':2.5,'offensive_army':1.8,'intelligence':1.5,'alliances':1.5,'conquest':1.3,'environment':.35,'welfare':.6,'trade':.7,'research':.8,'infrastructure':.8},
}
LEVELS={'peace':'pokój','threat':'zagrożenie','war':'wojna'}


def own_relations(session,country_id):
    names=dict(session.execute(select(DictStosunkiRelacja.relacja_id,DictStosunkiRelacja.relacja_nazwa)).all())
    states=dict(session.execute(select(DictStosunkiStan.stan_id,DictStosunkiStan.stan_nazwa)).all())
    result={}
    for a,b,relation,state in session.execute(select(Stosunki.PANSTWO_ID,Stosunki.PANSTWO_ID2,Stosunki.relacja_id,Stosunki.stan_id).where(or_(Stosunki.PANSTWO_ID==country_id,Stosunki.PANSTWO_ID2==country_id))):
        other=b if a==country_id else a
        result[other]={'relation':normalized(names.get(relation,'') or ''),'relation_label':names.get(relation),'state':normalized(states.get(state,'') or ''),'state_label':states.get(state)}
    return result


def assess(session,country_id,now,*,world=None,memory=None,relationships=None):
    relations=own_relations(session,country_id)
    at_war=sorted(other for other,row in relations.items() if row['state']=='wojnakinetyczna')
    allies=sorted(other for other,row in relations.items() if row['relation'] in ALLIED)
    hostile=sorted(other for other,row in relations.items() if row['relation'] in HOSTILE)
    recent=[]
    if memory:
        limit=(now-timedelta(days=30)).isoformat() if now else ''
        recent=[e for e in memory.get('actions_against_us',[]) if e['kind']!='DIPLOMATIC_PROPOSAL' and (e.get('at') or '')>=limit]
    occupied=dict((world or {}).get('occupied_by_others',{}))
    threats=sorted(other for other,p in ((memory or {}).get('perception') or {}).items() if p.get('threat',0)>=60)
    level='war' if at_war or occupied else 'threat' if recent or threats or (hostile and set(hostile)&set((world or {}).get('neighbor_countries',[]))) else 'peace'
    return {'level':level,'label':LEVELS[level],'at_war':at_war,'allies':allies,'hostile':hostile,'threats':threats,
            'recent_attacks':recent[:10],'occupied_regions':occupied,'relations':relations,'multipliers':MULTIPLIERS[level]}
