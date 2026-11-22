"""Widok państwa PAGA2: dokładnie to, co widzi gracz tego państwa na swoich ekranach.

Każda sekcja to ekran gracza (JSON albo dozwolone klucze kontekstu szablonu HTML).
Informacje o innych państwach pochodzą wyłącznie z ekranów jawnych i z raportów wywiadu (sekcja intelligence).
"""
from sqlalchemy.orm import Session
from extensions import db
from game.paga2.gateway import call,plain

# nazwa: (ścieżka, metoda, klucze kontekstu szablonu dla stron HTML)
SOURCES={
    'finance':('/game/finanse','GET',('finance_state','finance_categories','finance_error','finance_history','game_country')),
    'army':('/game/sily-zbrojne','GET',('army','active','military_budget_total','interceptor_ammunition','training','recruitment')),
    'military':('/game/panel-wojenny/stan','GET',None),
    'infrastructure':('/game/infrastruktura/obiekty/stan','GET',None),
    'mining':('/game/handel/wydobycie/stan','GET',None),
    'trade':('/game/handel/stan','GET',None),
    'research':('/game/badania/stan','GET',None),
    'intelligence':('/game/wywiad-wojskowy/stan','GET',None),
    'loans':('/game/pozyczki/stan','GET',None),
    'imf':('/game/mfw/stan','GET',None),   # 18 Nov 2026: Międzynarodowy Fundusz Walutowy
    'rail':('/game/kolej/stan','GET',None),   # 19 Nov 2026: kolej (zakładka „Komunikacja”)
    'airports':('/game/lotniska/stan','GET',None),   # 20 Nov 2026: porty lotnicze
    'warehouse':('/game/magazyn/stan','GET',None),   # 22 Nov 2026: lokalizacja magazynu państwa
    'cities':('/game/miasta/stan','GET',None),   # 21 Nov 2026: obiekty miejskie (zakładka „Miasta”)
    'diplomacy':('/game/dyplomacja','GET',('diplomacy_map','diplomacy_proposals')),
    'environment':('/game/srodowisko','GET',('metrics','environment_map')),
    'demography':('/game/demografia','GET',('history','metrics','age_structure','demographic_map','game_country')),
    'society':('/game/spoleczenstwo','GET',('indicators','benefit_expectations','benefit_year','benefit_half')),
    'events':('/game/stan/zdarzenia','GET',None),
    'generated_events':('/game/wydarzenia','GET',('rows','effects','count')),
    'world_news':('/game/dyplomacja/wiadomosci-swiatowe','GET',None),
    'notifications':('/game/forum/powiadomienia','GET',None),
}


# Własne rekordy ORM, które ekran gracza pokazuje jego państwu (konwertowane do kolumn).
OWN_TABLES={'army':frozenset({'wojsko'})}


def read(app,actor,name):
    path,method,keep=SOURCES[name]
    status,data=call(app,actor,path,method=method,keep=keep,own=OWN_TABLES.get(name,frozenset()))
    return {'status':status,'data':plain(data) if status<400 else None,'error':(data or {}).get('error') if status>=400 and isinstance(data,dict) else None}


def snapshot(app,actor,sections=None,*,now=None):
    """Pełny obraz państwa do decyzji: ekrany gracza, geografia świata i pamięć."""
    from game.paga2.geography import World
    from game.paga2.memory import recall
    result={'country_id':actor.country_id,'screens':{}}
    for name in sections or SOURCES:
        try:result['screens'][name]=read(app,actor,name)
        except Exception as error:  # jeden ekran nie blokuje pozostałych
            app.logger.exception('PAGA2: odczyt ekranu %s państwa %s',name,actor.country_id)
            result['screens'][name]={'status':500,'data':None,'error':type(error).__name__}
    with Session(db.engine) as session:
        result['world']=World(session).summary(actor.country_id)
        if now is not None:result['memory']=recall(session,actor.country_id,now)
    return result
