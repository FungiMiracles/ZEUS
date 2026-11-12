"""Wiedza modeli AI (forum, wiadomości, pożyczki) o państwie prowadzonym przez PAGA2.

Modele nie podejmują decyzji państwa — mówią w jego imieniu. Dostają więc profil PAGA2, sytuację, ostatnie decyzje,
aktywne plany i stosunek do rozmówcy, aby wypowiedzi były zgodne z rzeczywistą polityką i zmianami w państwie.
"""
from datetime import timedelta
from sqlalchemy import select
from game.paga2 import catalog

RULE=('Decyzje państwa (gospodarka, dyplomacja, wojsko) podejmuje algorytm PAGA2. Mów zgodnie z jego profilem, decyzjami i planami; '
      'nie obiecuj działań z nimi sprzecznych. Możesz je uzasadniać i negocjować w ich duchu.')


def notable_traits(traits):
    """Cechy wyraźnie odbiegające od przeciętnej (≥70 lub ≤30) — to one nadają państwu charakter wypowiedzi."""
    items=sorted(((abs(value-50),key,value) for key,value in traits.items() if value>=70 or value<=30),reverse=True)[:6]
    return {catalog.TRAITS[key]:value for _,key,value in items}


def recent_decisions(session,country_id,now,limit=5):
    from game.paga2.models import Paga2Decision
    since=now-timedelta(days=60) if now else None
    query=select(Paga2Decision).where(Paga2Decision.country_id==country_id,Paga2Decision.status=='EXECUTED')
    if since is not None:query=query.where(Paga2Decision.game_at>=since)
    result=[]
    for row in session.scalars(query.order_by(Paga2Decision.id.desc()).limit(limit*2)):
        for item in (row.result or {}).get('wykonane',[]):
            result.append({'data':row.game_at.isoformat()[:10] if row.game_at else None,'działanie':(item.get('label') or '')[:90]})
        if len(result)>=limit:break
    return result[:limit]


def stance_towards(session,country_id,other_id,now):
    """Stosunek do rozmówcy: relacja, stan, powiązanie historyczne, zaufanie/zagrożenie i działania wobec nas."""
    if not other_id:return None
    from game.paga2.situation import own_relations
    from game.paga2.memory import history_with
    from game.paga_relationships import country_preferences
    from game.autonomy_models import AutonomyAssessment
    relation=own_relations(session,country_id).get(other_id) or {}
    link=next((item for item in country_preferences(session,country_id) if item['country_id']==other_id),None)
    assessment=session.get(AutonomyAssessment,(country_id,other_id))
    history=history_with(session,country_id,other_id,now) if now else {'hostile_from':0,'hostile_to':0}
    return {'państwo_id':other_id,'relacja':relation.get('relation_label'),'stan':relation.get('state_label'),
            'powiązanie_historyczne':(link or {}).get('status'),'rola':(link or {}).get('role'),
            'zaufanie':round(assessment.trust) if assessment else None,'zagrożenie':round(assessment.threat) if assessment else None,
            'ich_wrogie_działania_wobec_nas':history.get('hostile_from'),'nasze_wrogie_działania_wobec_nich':history.get('hostile_to')}


def policy(session,country_id,now,*,other_id=None):
    """Blok kontekstu dla modelu AI; None, gdy państwo nie ma profilu PAGA2."""
    from game.paga2.models import Paga2Profile,Paga2Plan,table_ready
    if not table_ready(session,Paga2Profile):return None
    profile=session.get(Paga2Profile,country_id)
    if profile is None:return None
    from game.paga2.situation import assess
    from game.paga2.planner import goal_label
    traits=catalog.default_profile(profile.traits)
    situation=assess(session,country_id,now)
    from models import Panstwo
    names=dict(session.execute(select(Panstwo.PANSTWO_ID,Panstwo.panstwo_nazwa)).all())
    plans=[goal_label(row.goal) for row in session.scalars(select(Paga2Plan).where(Paga2Plan.country_id==country_id,Paga2Plan.status=='ACTIVE'))] if table_ready(session,Paga2Plan) else []
    return {'zasada':RULE,
            'ogólny_charakter':[catalog.CATEGORIES[c]['label'] for c in profile.categories or [] if c in catalog.CATEGORIES],
            'priorytety_od_najważniejszego':[catalog.PRIORITIES[p] for p in profile.priorities or [] if p in catalog.PRIORITIES][:5],
            'wyraziste_cechy':notable_traits(traits),
            'sytuacja':{'poziom':situation['label'],'wojna_z':[names.get(i,i) for i in situation['at_war']][:5],'sojusznicy':[names.get(i,i) for i in situation['allies']][:5],
                        'okupowane_nasze_regiony':len(situation['occupied_regions'])},
            'ostatnie_decyzje_PAGA2':recent_decisions(session,country_id,now),
            'aktywne_plany':plans[:3],
            **({'stosunek_do_rozmówcy':stance_towards(session,country_id,other_id,now)} if other_id else {})}


def loan_limits(session,country_id,now):
    """Twarde granice decyzji o udzieleniu pożyczki wyliczone przez PAGA2."""
    from game.paga2.finance import loan_capacity
    capacity=loan_capacity(session,country_id,now)
    return {'maksymalna_kwota_ROI':capacity['max_loan'],'rezerwa_ROI':capacity['reserve'],'potrzeby_planów_ROI':capacity['planned_needs'],
            'zatrzymana_część_rezerwy':capacity['kept_share'],'poziom_bezpieczeństwa':capacity['security_level'],
            'zasada':'Przyjmij tylko kwotę ≤ maksymalna_kwota_ROI (wyższą ZEUS zablokuje). W tych granicach decydujesz sam.'}
