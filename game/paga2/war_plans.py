"""PAGA2 — plany wojenne (administrator, 21 Nov 2026): wojna ofensywna tylko z celem, rozpoznaniem i środkami.

Plan wojenny (tabela game_paga2_war_plans, trwały po restarcie) przechodzi etapy:
  PLANNING → INTELLIGENCE → PREPARATION → READY → ACTIVE → NEGOTIATION → COMPLETED   (albo ABANDONED na każdym etapie).
- cel główny wynika z mechanizmów gry i da się go sprawdzić: zajęcie regionu sąsiada (okupacja lub aneksja regionu),
  zniszczenie rozpoznanych baz państwa odległego, wsparcie sojusznika (operacje przeciw jego wrogowi do końca jego wojny);
- gotowość w pięciu obszarach (potencjał bojowy, zdolność dotarcia, finanse, zaopatrzenie, rozpoznanie), każdy liczony
  jako min(1, posiadane / wymagane) dla celów konkretnego planu; wypowiedzenie wojny i dołączenie do wojny sojusznika
  wymagają ≥ 80% w KAŻDYM obszarze (twarda walidacja, niezależna od punktacji i charakteru państwa);
- rozpoznanie: udana misja wywiadu „bazy” w regionie celu nie starsza niż 90 dni Entendy, a cele muszą nadal istnieć;
- po wypowiedzeniu: pierwsza operacja jest decyzją wymaganą (wyzwalacz reakcji doraźnej przy najbliższym sprawdzeniu
  harmonogramu); 3 cykle bez skutecznej operacji → ponowna analiza celów, 6 cykli → negocjacje pokojowe;
- 180 dni Entendy po pokoju bez wojny ofensywnej z tym samym państwem (wyjątek: nowy atak, okupacja, aneksja z jego strony);
- 90 dni Entendy karencji na dobrowolne zmiany stosunków z tym samym państwem (wyjątki: wrogie działania tego państwa,
  zawarcie lub zerwanie sojuszu, wojna, okupacja).
Wszystkie terminy w czasie Entendy (ctx.now) — zmiana tempa zegara ich nie przesuwa. Ograniczenia dotyczą wyłącznie PAGA2.
Obrona, odbijanie własnych ziem i działania w trwającej wojnie nie wymagają progu gotowości.
"""
from datetime import timedelta
from sqlalchemy import select
from sqlalchemy.orm import Session
from extensions import db

READY_THRESHOLD=.8
INTEL_DAYS=90
OFFENSIVE_GRACE_DAYS=180
RELATION_LOCK_DAYS=90
IDLE_REVIEW=3
IDLE_NEGOTIATE=6
MAX_INTEL_ATTEMPTS=6           # misje rozpoznania bez skutku, po których plan jest porzucany
MAX_STALE_CYCLES=40            # przeglądy bez postępu przygotowań
MAX_FIRST_OPERATION_ATTEMPTS=5
LOSS_LIMIT=.5                  # siła spadła poniżej połowy siły z chwili wypowiedzenia → zmiana strategii / pokój
MIN_WAR_RESERVE=1_000_000_000  # minimalna rezerwa sił zbrojnych na uderzenia rakietowe (ROI)
ACTIVE_STAGES=('PLANNING','INTELLIGENCE','PREPARATION','READY','ACTIVE','NEGOTIATION')
PREPARING=('PLANNING','INTELLIGENCE','PREPARATION','READY')
AREAS={'combat':'potencjał bojowy','reach':'zdolność dotarcia do celu','finance':'zasoby finansowe','supply':'zaopatrzenie i uzupełnianie strat','intel':'rozpoznanie przeciwnika'}
STAGE_LABELS={'PLANNING':'planowanie','INTELLIGENCE':'rozpoznanie','PREPARATION':'przygotowanie','READY':'gotowość','ACTIVE':'wojna',
              'NEGOTIATION':'zakończenie konfliktu','COMPLETED':'zakończony','ABANDONED':'porzucony'}
GOAL_LABELS={'conquer_region':'zajęcie regionu','destroy_bases':'zniszczenie baz wojskowych','support_ally':'wsparcie sojusznika'}
ORDER=('egzystencjalniewrogie','wrogie','napiete','zle','chlodne','neutralne','dobre','przyjazne','partnerskie','partnerskiestrategiczne','sojusznicze')
HOSTILE_EVENT_KINDS=('WAR','BOMBARDMENT','HYBRID_DETECTED','UNATTRIBUTED_DAMAGE','LAND_ATTACK','RECAPTURE_ATTACK','OCCUPATION','ANNEXATION')
RELATION_EXCEPTION_KINDS=HOSTILE_EVENT_KINDS+('ALLIANCE_FORMED','ALLIANCE_BROKEN')
GRACE_EXCEPTION_KINDS=('WAR','BOMBARDMENT','LAND_ATTACK','OCCUPATION','ANNEXATION','RECAPTURE_ATTACK')
RELATION_ACTIONS=('RELATION_IMPROVE','RELATION_WORSEN','ALLIANCE')


# ---------------- czyste reguły (testowane bez bazy) ----------------

def ratio(have,need):
    """Stopień pokrycia potrzeby (0–1); brak potrzeby = pełne pokrycie."""
    try:have=float(have or 0);need=float(need or 0)
    except (TypeError,ValueError):return 0.0
    if need<=0:return 1.0
    return max(0.0,min(1.0,have/need))


def readiness(areas):
    """(najsłabszy obszar 0–1, braki): [opis obszaru poniżej progu 80%]."""
    values={k:float((v or {}).get('ratio',0)) for k,v in (areas or {}).items()}
    if not values:return 0.0,['brak oceny gotowości']
    short=[f'{AREAS.get(k,k)}: {round(100*v)}% (wymagane {round(100*READY_THRESHOLD)}%)' for k,v in values.items() if v<READY_THRESHOLD]
    return min(values.values()),short


def declare_blockers(areas,*,targets,intel_fresh,relation,grace_until,now):
    """Twarde warunki wypowiedzenia wojny ofensywnej przez PAGA2 — lista powodów blokady (pusta = można rozważyć)."""
    reasons=[]
    level,short=readiness(areas)
    if short:reasons.append('Gotowość poniżej 80%: '+'; '.join(short)+'.')
    if not targets:reasons.append('Brak konkretnego, istniejącego celu militarnego.')
    if not intel_fresh:reasons.append(f'Brak aktualnego rozpoznania celów (udana misja wywiadu nie starsza niż {INTEL_DAYS} dni Entendy).')
    if relation not in ORDER[:4]:reasons.append(f'Stosunki „{relation}” nie pozwalają wypowiedzieć wojny (wymagane złe lub gorsze).')
    if grace_until is not None and now is not None and now<grace_until:reasons.append(f'Okres ochronny po pokoju do {grace_until:%d.%m.%Y} (Entenda).')
    return reasons


def rank(relation):return ORDER.index(relation) if relation in ORDER else ORDER.index('neutralne')


def join_blockers(areas,*,requester_relation,enemy_relation,threat,hostile_from,targets,intel_fresh):
    """Warunki przystąpienia do wojny sojusznika (A — możliwości, B — relacje z proszącym, C — nastawienie do przeciwnika)."""
    reasons=[]
    level,short=readiness(areas)
    if short:reasons.append('A. Możliwości militarne poniżej 80% potrzeb własnego udziału: '+'; '.join(short)+'.')
    if not targets or not intel_fresh:reasons.append('A. Brak rozpoznanych, istniejących celów do pierwszej operacji.')
    if rank(requester_relation)<rank('przyjazne'):reasons.append(f'B. Relacje z państwem proszącym („{requester_relation}”) słabsze niż przyjazne.')
    hostile=rank(enemy_relation)<=rank('zle') or (threat or 0)>=60 or (hostile_from or 0)>0
    if not hostile:reasons.append(f'C. Brak wrogości wobec przeciwnika (stosunki „{enemy_relation}”, zagrożenie {threat or 0}, wrogie działania: {hostile_from or 0}).')
    if rank(enemy_relation)>=rank('dobre'):reasons.append(f'C. Zbyt dobre stosunki z przeciwnikiem („{enemy_relation}”).')
    return reasons


def lock_until(changes,events,other,now,*,days=RELATION_LOCK_DAYS):
    """Koniec karencji zmian stosunków z `other` albo None. changes=[(państwo, czas gry)] — własne dobrowolne zmiany;
    events=[(rodzaj, sprawca, czas gry, strony)] — zdarzenie po zmianie znosi karencję."""
    if now is None:return None
    last=max((at for target,at in changes if target==other and at is not None and at>now-timedelta(days=days)),default=None)
    if last is None:return None
    for kind,actor,at,parties in events:
        if at is None or at<=last:continue
        if kind in RELATION_EXCEPTION_KINDS and (actor==other or other in (parties or [])):return None
    return last+timedelta(days=days)


def grace_until(peace_dates,events,other,now,*,days=OFFENSIVE_GRACE_DAYS):
    """Koniec okresu ochronnego (180 dni Entendy po pokoju) albo None; wrogie działanie tego państwa po pokoju go znosi."""
    signed=peace_dates.get(other)
    if signed is None or now is None or now>=signed+timedelta(days=days):return None
    for kind,actor,at,parties in events:
        if actor==other and at is not None and at>signed and kind in GRACE_EXCEPTION_KINDS:return None
    return signed+timedelta(days=days)


def review_war(*,idle,operations_since,goal_done,power_now,power_start,at_war):
    """Przegląd trwającej wojny: (nowy etap, licznik bezczynności, notatka)."""
    if not at_war:return 'COMPLETED',idle,'Wojna zakończona.'
    if goal_done:return 'NEGOTIATION',0,'Cel główny osiągnięty — ocena zawarcia pokoju.'
    if power_start and power_now is not None and power_now<LOSS_LIMIT*power_start:
        return 'NEGOTIATION',idle,f'Straty: siła {power_now:.0f} wobec {power_start:.0f} na początku wojny — zmiana strategii, obrona i rozważenie pokoju.'
    idle=0 if operations_since else idle+1
    if idle>=IDLE_NEGOTIATE:return 'NEGOTIATION',idle,f'{idle} cykli bez skutecznej operacji — rozważenie pokoju lub zmiany strategii.'
    if idle==IDLE_REVIEW:return 'ACTIVE',idle,f'{idle} cykle bez skutecznej operacji — ponowna analiza celów.'
    return 'ACTIVE',idle,None


def peace_adjustment(*,goal_done,near_goal,superiority,occupied_recoverable,idle,losses):
    """Korekta oceny pokoju z planu wojennego: (premia do pokoju, uwagi). Dodatnia = za pokojem."""
    value=0.0;notes=[]
    if goal_done:value+=10;notes.append('Cel główny wojny osiągnięty.')
    if idle>=IDLE_NEGOTIATE:value+=8;notes.append('Dalsze działania nie przynoszą postępów.')
    if losses:value+=6;notes.append('Straty przekroczyły akceptowalny poziom.')
    if near_goal and not goal_done:value-=8;notes.append('Cel główny jest blisko — przedwczesny pokój.')
    if superiority and not goal_done:value-=6;notes.append('Wyraźna przewaga militarna.')
    if occupied_recoverable:value-=6;notes.append('Przeciwnik okupuje nasze terytorium, a jego odzyskanie jest realne.')
    return value,notes


# ---------------- dane z bazy ----------------

def _table_ready(session):
    from game.paga2.models import Paga2WarPlan,table_ready
    return table_ready(session,Paga2WarPlan)


def plans(session,country_id,*,active_only=True):
    from game.paga2.models import Paga2WarPlan
    if not _table_ready(session):return []
    query=select(Paga2WarPlan).where(Paga2WarPlan.country_id==country_id)
    if active_only:query=query.where(Paga2WarPlan.stage.in_(ACTIVE_STAGES))
    return list(session.scalars(query.order_by(Paga2WarPlan.id)))


def active_plans(ctx):
    """Plany w toku państwa (czytane raz na przebieg; po zmianie — ctx._war_plans=None)."""
    if getattr(ctx,'_war_plans',None) is None:
        try:
            with Session(db.engine) as session:
                rows=plans(session,ctx.country_id)
                for row in rows:session.expunge(row)
        except Exception:rows=[]   # brak bazy lub tabeli (np. przed migracją) — brak planów
        ctx._war_plans=rows
    return ctx._war_plans


def plan_for(ctx,enemy):return next((p for p in active_plans(ctx) if p.enemy_id==enemy),None)


def note(plan,text,now):
    plan.history=list(plan.history or [])+[{'at':now.isoformat()+'Z' if now else None,'text':text}]


def save(plan_id,**changes):
    """Zapis zmian planu (osobna transakcja); historia przez klucz 'note'."""
    from game.paga2.models import Paga2WarPlan,utc_now
    with Session(db.engine) as session,session.begin():
        row=session.get(Paga2WarPlan,plan_id,with_for_update=True)
        if row is None:return None
        text=changes.pop('note',None);now=changes.pop('now',None)
        for key,value in changes.items():setattr(row,key,value)
        if text:note(row,text,now)
        if row.stage in ('COMPLETED','ABANDONED'):row.active_key=None;row.finished_at=row.finished_at or utc_now()
        row.updated_at=utc_now()
        return row.id


def create(ctx,enemy,*,kind,reason,goal,stage,ally=None,extra=None,assessment=None,first_operation=False,power=None):
    """Nowy plan (jeden w toku na parę państw — unikalny active_key). Zwraca id albo None, gdy plan już istnieje."""
    from sqlalchemy.exc import IntegrityError
    from game.paga2.models import Paga2WarPlan
    key=f'{ctx.country_id}:{enemy}'
    try:
        with Session(db.engine) as session,session.begin():
            row=Paga2WarPlan(country_id=ctx.country_id,enemy_id=enemy,kind=kind,ally_id=ally,stage=stage,active_key=key,reason=reason,goal=goal,
                             extra_goals=extra or [],targets=[],assessment=assessment or {},readiness=0.0,shortfalls=[],history=[],
                             first_operation_pending=first_operation,power_at_start=power,declared_at=ctx.now if stage=='ACTIVE' else None,game_created_at=ctx.now)
            note(row,f'Utworzenie planu ({GOAL_LABELS.get(goal.get("type"),goal.get("type"))}): {reason}',ctx.now)
            session.add(row);session.flush();ctx._war_plans=None
            return row.id
    except IntegrityError:
        return None


def fresh_missions(session,country_id,enemy,now,*,region=None):
    """Udane misje rozpoznania baz państwa `enemy` nie starsze niż INTEL_DAYS dni Entendy."""
    from game.intelligence_models import IntelligenceMission
    query=select(IntelligenceMission).where(IntelligenceMission.panstwo_id==country_id,IntelligenceMission.target_country_id==enemy,
                                            IntelligenceMission.kind.in_(('bases','silos')),IntelligenceMission.success.is_(True),
                                            IntelligenceMission.completed_at.is_not(None),IntelligenceMission.ends_at>=now-timedelta(days=INTEL_DAYS))
    if region is not None:query=query.where(IntelligenceMission.region_id==region)
    return list(session.scalars(query))


def pending_mission(session,country_id,enemy):
    from game.intelligence_models import IntelligenceMission
    return session.scalar(select(IntelligenceMission.id).where(IntelligenceMission.panstwo_id==country_id,IntelligenceMission.target_country_id==enemy,
                                                               IntelligenceMission.completed_at.is_(None)).limit(1)) is not None


def peace_dates(session,country_id):
    """{państwo: czas Entendy ostatniego pokoju po wojnie kinetycznej} (dziennik zmian stosunków)."""
    from models import AudytStosunki
    from game.diplomacy_service import dictionaries
    _,states,_=dictionaries(session)
    from sqlalchemy import or_
    rows=session.execute(select(AudytStosunki.id,AudytStosunki.panstwo_id,AudytStosunki.panstwo_id2,AudytStosunki.data_zmiany_entenda).where(
        or_(AudytStosunki.panstwo_id==country_id,AudytStosunki.panstwo_id2==country_id),AudytStosunki.stan_id==states['pokoj']).order_by(AudytStosunki.id)).all()
    result={}
    for id,a,b,signed in rows:
        previous=session.scalar(select(AudytStosunki.stan_id).where(AudytStosunki.panstwo_id==a,AudytStosunki.panstwo_id2==b,AudytStosunki.id<id).order_by(AudytStosunki.id.desc()).limit(1))
        if previous!=states['wojnakinetyczna'] or signed is None:continue
        other=b if a==country_id else a
        if other not in result or signed>result[other]:result[other]=signed
    return result


def events_since(ctx,days=OFFENSIVE_GRACE_DAYS+30):
    """Zdarzenia świata widoczne dla państwa: [(rodzaj, sprawca, czas gry, strony)]."""
    if getattr(ctx,'_plan_events',None) is None:
        from datetime import datetime
        from game.paga2.memory import visible_events
        try:
            with Session(db.engine) as session:
                rows=visible_events(session,ctx.country_id,since=ctx.now-timedelta(days=days) if ctx.now else None,limit=800)
                ctx._plan_events=[(e.kind,e.actor_id,e.occurred_at,(e.payload or {}).get('parties') or [e.actor_id,e.target_id]) for e in rows]
        except Exception:ctx._plan_events=[]
    return ctx._plan_events


def offensive_grace(ctx,other):
    if getattr(ctx,'_peace_dates',None) is None:
        try:
            with Session(db.engine) as session:ctx._peace_dates=peace_dates(session,ctx.country_id)
        except Exception:ctx._peace_dates={}
    return grace_until(ctx._peace_dates,events_since(ctx),other,ctx.now)


def relation_changes(ctx):
    """Własne dobrowolne zmiany stosunków PAGA2 (z historii decyzji): [(państwo, czas gry, kierunek)]."""
    if getattr(ctx,'_relation_changes',None) is None:
        from game.paga2.models import Paga2Decision
        result=[]
        try:
            with Session(db.engine) as session:
                query=select(Paga2Decision).where(Paga2Decision.country_id==ctx.country_id,Paga2Decision.status=='EXECUTED',Paga2Decision.game_at>=ctx.now-timedelta(days=365))
                for row in session.scalars(query.order_by(Paga2Decision.id.desc()).limit(800)):
                    for item in (row.result or {}).get('wykonane',[]):
                        action=item.get('action');payload=item.get('payload') or {}
                        if action in RELATION_ACTIONS or (action=='PROPOSAL_ACCEPT' and payload.get('relation_change')):
                            direction=-1 if action=='RELATION_WORSEN' else 1
                            result.append((item.get('target'),row.game_at,direction))
        except Exception:result=[]
        ctx._relation_changes=result
    return ctx._relation_changes


def relation_lock(ctx,other):
    return lock_until([(t,at) for t,at,_ in relation_changes(ctx)],events_since(ctx),other,ctx.now)


def consistency_penalty(ctx,other,direction):
    """Kara za odwrócenie kierunku polityki wobec państwa (ostatni rok, bez zdarzeń uzasadniających): rośnie z przewidywalnością."""
    last=max(((at,d) for t,at,d in relation_changes(ctx) if t==other and at is not None),default=None)
    if last is None or last[1]==direction:return 0.0
    if any(kind in RELATION_EXCEPTION_KINDS and (actor==other or other in (parties or [])) and at and at>last[0] for kind,actor,at,parties in events_since(ctx)):return 0.0
    return 3.0+8.0*ctx.traits.get('predictability',50)/100


# ---------------- ocena gotowości planu ----------------

def _weighted(units):
    from game.land_war import WEIGHTS
    return sum(int((units or {}).get(u,0))*WEIGHTS[u] for u in WEIGHTS)


def assess(ctx,plan,forces,screen,config):
    """Cele militarne i gotowość w pięciu obszarach dla planu; zwraca (targets, areas, notes, intel_fresh, extra)."""
    from game.paga2 import war
    from game.land_war import UNIT_COST,WEIGHTS
    enemy=plan.enemy_id;goal=plan.goal or {};kind=goal.get('type')
    notes=[];areas={}
    with Session(db.engine) as session:
        missions=fresh_missions(session,ctx.country_id,enemy,ctx.now,region=goal.get('region_id') if kind=='conquer_region' else None)
    known={int(i) for m in missions for i in ((m.report or {}).get('base_ids') or [])}
    intel_fresh=bool(missions)
    bases=[b for b in screen.get('bases',[]) if b.get('countryId')==enemy and (b.get('health') is None or b.get('health')>0) and b.get('position')]
    stock=war._stock(screen)
    if kind=='conquer_region':
        region=str(goal.get('region_id'))
        targets=[{'kind':'base','id':b['id'],'region':str(b.get('regionId')),'label':f'baza #{b["id"]}','level':b.get('level'),'point':b['position']}
                 for b in bases if str(b.get('regionId'))==region and b['id'] in known]
        targets+=[{'kind':'city','id':int(i),'region':region,'label':c.get('name') or f'miasto #{i}','point':c.get('point')}
                  for i,c in (config.get('cities') or {}).items() if c.get('countryId')==enemy and str(c.get('regionId'))==region and c.get('point')]
        land=[b for b in forces.bases if b.kind=='land' and b.health>0 and getattr(b,'operational',True) and b.map_x is not None and (b.garrison or {}).get('soldiers',0)>0]
        point=next((t['point'] for t in targets if t.get('point')),None)
        base=min(land,key=lambda b:war.km(ctx,[b.map_x,b.map_y],point) or 1e9) if land and point else (land[0] if land else None)
        training=(forces.army or {}).get('wyszkolenie_ladowe') or 100
        ours=_weighted(base.garrison)*training/100 if base else 0.0
        margin=1.2+.6*(100-ctx.traits.get('loss_tolerance',50))/100
        defense=max([war.battle_estimate(ctx,t['kind'],t.get('level'),t['id'],screen,enemy) for t in targets] or [2500.0])
        need=defense*margin
        areas['combat']={'have':round(ours),'need':round(need),'ratio':ratio(ours,need)}
        neighbors=set(ctx.world_summary().get('neighbor_countries',[]))
        offense=war.offense_means(forces,screen)
        reach=1.0 if enemy in neighbors and base is not None and (offense.get('tanks') or offense.get('armored')) else 0.0
        areas['reach']={'have':reach,'need':1,'ratio':reach}
        if not reach:notes.append('Brak granicy lądowej albo obsadzonej bazy lądowej z czołgami lub wozami opancerzonymi.')
        scale=min(1.0,need*1.15/ours) if ours else 1.0
        cost=float(sum(UNIT_COST[u]*int((base.garrison or {}).get(u,0)*scale) for u in WEIGHTS)) if base else float(need*10000)
        areas['finance']={'have':round(forces.budget_available),'need':round(cost),'ratio':ratio(forces.budget_available,cost)}
        reserve=sum(int((forces.free or {}).get(u,0))*WEIGHTS[u] for u in WEIGHTS if u!='soldiers')+int((forces.free_soldiers or {}).get('land',0))
        areas['supply']={'have':round(reserve),'need':round(.25*need),'ratio':ratio(reserve,.25*need)}
        areas['intel']={'have':1 if intel_fresh else 0,'need':1,'ratio':1.0 if intel_fresh else 0.0}
        extra={'base_id':base.id if base else None}
    else:   # destroy_bases i support_ally: uderzenia na rozpoznane bazy przeciwnika
        targets=[{'kind':'base','id':b['id'],'region':str(b.get('regionId')),'label':f'baza #{b["id"]}','point':b['position']} for b in bases if b['id'] in known][:3]
        reach_means=war.reach_means(ctx,forces,screen,enemy) if enemy not in set(ctx.world_summary().get('neighbor_countries',[])) else {**war.reach_means(ctx,forces,screen,enemy),**war.offense_means(forces,screen)}
        missiles=sum(v for k,v in reach_means.items() if k in ('short','medium','long'))
        fighters=reach_means.get('fighters',0)
        defended={(d.get('targetKind'),d.get('targetId')) for d in screen.get('defenses',[]) if d.get('countryId')==enemy}
        need=sum(war.salvo(ctx,max(1,missiles),('base',t['id']) in defended) for t in targets) or 12
        have=missiles if (missiles and (reach_means.keys()&{'short','medium','long'})) else 0
        areas['combat']={'have':have,'need':need,'ratio':ratio(have,need)}
        reach=1.0 if reach_means else 0.0
        areas['reach']={'have':reach,'need':1,'ratio':reach}
        if not reach:notes.append('Brak środków ataku na odległość (rakiety w zasięgu, myśliwce, okręty).')
        areas['finance']={'have':round(forces.budget_available),'need':MIN_WAR_RESERVE,'ratio':ratio(forces.budget_available,MIN_WAR_RESERVE)}
        total=sum(stock.values())
        areas['supply']={'have':total,'need':2*need,'ratio':ratio(total,2*need)}
        areas['intel']={'have':len(targets),'need':1,'ratio':1.0 if targets and intel_fresh else 0.0}
        extra={'fighters':fighters}
    own,foe=war.strength(ctx,enemy)
    notes.append(f'Siły ogółem: własne {own or 0:.0f}, przeciwnika {foe or 0:.0f}.')
    return targets,areas,notes,intel_fresh,{**extra,'own':own,'enemy':foe}


def goal_done(ctx,plan,targets):
    """Czy cel główny jest osiągnięty (sprawdzalny w grze)."""
    kind=(plan.goal or {}).get('type')
    if kind=='conquer_region':
        from game.land_war_models import Occupation
        from models import Region
        from game.governance import controller_id
        region=(plan.goal or {}).get('region_id')
        with Session(db.engine) as session:
            row=session.get(Region,region)
            if row is not None and controller_id(session,row.panstwo_id)==ctx.country_id:return True
            return session.scalar(select(Occupation.id).where(Occupation.region_id==region,Occupation.occupier_id==ctx.country_id,Occupation.kind=='region',
                                                              Occupation.status.in_(('ACTIVE','PENDING'))).limit(1)) is not None
    if kind=='destroy_bases':
        wanted=set((plan.goal or {}).get('target_ids') or [])
        alive={t['id'] for t in targets}
        return bool(wanted) and not (wanted&alive)
    if kind=='support_ally':
        return (plan.ally_id is not None and plan.enemy_id not in _wars_of(plan.ally_id)) or (plan.operations or 0)>=3
    return False


def _wars_of(country):
    from game.paga2.situation import own_relations
    with Session(db.engine) as session:
        return {other for other,row in own_relations(session,country).items() if row.get('state')=='wojnakinetyczna'}


def choose_goal(ctx,enemy,forces):
    """Cel główny: sąsiad — zajęcie najbliższego regionu przeciwnika; państwo odległe — zniszczenie rozpoznanych baz."""
    neighbors=set(ctx.world_summary().get('neighbor_countries',[]))
    if enemy in neighbors:
        from game.paga2.intelligence import target_regions
        regions=target_regions(ctx,enemy)
        if regions:return {'type':'conquer_region','region_id':regions[0],'label':f'Zajęcie regionu {regions[0]} państwa {enemy}'}
    return {'type':'destroy_bases','target_ids':[],'label':f'Zniszczenie baz wojskowych państwa {enemy}'}


# ---------------- przegląd planów w przebiegu (moduł wojny) ----------------

def review(ctx,forces,screen,config):
    """Przelicza plany w toku: etapy, gotowość, braki, bezczynność. Zwraca {plan_id: dane bieżące} dla modułów."""
    from game.paga2.war import WAR_RELATIONS
    state={}
    relations=ctx.situation.get('relations',{})
    at_war=set(ctx.situation.get('at_war',[]))
    for plan in active_plans(ctx):
        enemy=plan.enemy_id;row=relations.get(enemy) or {}
        relation=row.get('relation','neutralne')
        try:targets,areas,notes,intel_fresh,extra=assess(ctx,plan,forces,screen,config)
        except Exception as error:
            ctx.errors.append(f'plan wojenny {plan.id}: {type(error).__name__}: {error}'[:300]);continue
        level,short=readiness(areas)
        changes={'targets':targets,'assessment':{'areas':areas,'notes':notes,'own':extra.get('own'),'enemy':extra.get('enemy'),'base_id':extra.get('base_id'),'ops_seen':(plan.assessment or {}).get('ops_seen',plan.operations or 0)},
                 'readiness':round(level,3),'shortfalls':short,'now':ctx.now}
        stage=plan.stage;text=None;done=False
        lost=False
        try:
            from game.sovereignty import lost as sovereignty_lost
            with Session(db.engine) as session:lost=sovereignty_lost(session,enemy) is not None
        except Exception:pass
        if stage in PREPARING:
            if lost:stage,text='ABANDONED','Przeciwnik utracił suwerenność — plan bezprzedmiotowy.'
            elif rank(relation)>=rank('dobre') or enemy in ctx.situation.get('allies',[]):stage,text='ABANDONED',f'Stosunki z przeciwnikiem poprawiły się („{relation}”) — wojna nieuzasadniona.'
            elif enemy in at_war:
                stage,text='ACTIVE','Wojna z przeciwnikiem już trwa — plan przechodzi do realizacji.'
                changes.update(declared_at=plan.declared_at or ctx.now,first_operation_pending=True,power_at_start=plan.power_at_start or extra.get('own'))
                changes['assessment']['ops_seen']=plan.operations or 0
            elif not targets and (plan.goal or {}).get('type')=='destroy_bases' and intel_fresh:stage,text='ABANDONED','Brak istniejących celów militarnych po aktualnym rozpoznaniu.'
            elif areas.get('intel',{}).get('ratio',0)<1:
                if plan.intel_attempts>=MAX_INTEL_ATTEMPTS:stage,text='ABANDONED',f'{plan.intel_attempts} prób rozpoznania bez skutku — plan porzucony.'
                elif stage!='INTELLIGENCE':stage,text='INTELLIGENCE','Brak aktualnego rozpoznania celów — misje wywiadu.'
            elif short:
                improved=level>float(plan.readiness or 0)+1e-6
                stale=0 if improved else (plan.stale_cycles or 0)+(1 if ctx.mode=='CYCLIC' else 0)
                changes['stale_cycles']=stale
                if stale>=MAX_STALE_CYCLES:stage,text='ABANDONED',f'{stale} przeglądów bez postępu przygotowań — plan porzucony. Braki: '+'; '.join(short)
                elif stage!='PREPARATION':stage,text='PREPARATION','Przygotowanie: '+'; '.join(short)
            else:
                if stage!='READY':stage,text='READY','Wszystkie obszary gotowości ≥ 80% i aktualne rozpoznanie.'
                if relation not in WAR_RELATIONS:changes['shortfalls']=short+[f'stosunki „{relation}” — wypowiedzenie wojny wymaga złych lub gorszych']
            if (plan.goal or {}).get('type')=='destroy_bases' and targets and not (plan.goal or {}).get('target_ids'):
                changes['goal']={**plan.goal,'target_ids':[t['id'] for t in targets]}
        elif stage in ('ACTIVE','NEGOTIATION'):
            done=goal_done(ctx,plan,targets)
            if ctx.mode=='CYCLIC':
                seen=(plan.assessment or {}).get('ops_seen',0);since=(plan.operations or 0)-seen
                new,idle,text=review_war(idle=plan.idle_cycles or 0,operations_since=since,goal_done=done,power_now=extra.get('own'),
                                         power_start=plan.power_at_start,at_war=enemy in at_war)
                changes['assessment']['ops_seen']=plan.operations or 0
                changes['idle_cycles']=idle
                if new=='NEGOTIATION' and stage=='NEGOTIATION' and text==(plan.history or [{}])[-1].get('text'):text=None
                stage=new
            elif enemy not in at_war:stage,text='COMPLETED','Wojna zakończona.'
            if stage=='COMPLETED':
                changes['end_reason']=('Cel osiągnięty. ' if done else 'Cel nieosiągnięty. ')+f'Operacje: {plan.operations or 0}.'
        if stage!=plan.stage:changes['stage']=stage
        if stage=='ABANDONED':changes['end_reason']=text
        if text:changes['note']=text
        save(plan.id,**changes)
        state[plan.id]={'plan':plan,'stage':stage,'targets':targets,'areas':areas,'short':changes.get('shortfalls',short),'intel_fresh':intel_fresh,'relation':relation,
                        'goal_done':done,'extra':extra}
    ctx._war_plans=None
    ctx._plan_state=state
    return state


def plan_state(ctx):
    return getattr(ctx,'_plan_state',None) or {}


def intel_requests(ctx):
    """Prośby planów o rozpoznanie: [(plan_id, przeciwnik, region)] — dla modułu wywiadu."""
    result=[]
    for plan in active_plans(ctx):
        if plan.stage not in ('PLANNING','INTELLIGENCE','PREPARATION','READY'):continue
        goal=plan.goal or {}
        with Session(db.engine) as session:
            fresh=fresh_missions(session,ctx.country_id,plan.enemy_id,ctx.now,region=goal.get('region_id') if goal.get('type')=='conquer_region' else None)
            busy=pending_mission(session,ctx.country_id,plan.enemy_id)
        if fresh or busy or plan.intel_attempts>=MAX_INTEL_ATTEMPTS:continue
        result.append((plan.id,plan.enemy_id,goal.get('region_id') if goal.get('type')=='conquer_region' else None))
    return result


def register_operation(ctx,enemy,label):
    """Skuteczna operacja wojskowa przeciw państwu z planu: licznik, data, historia, koniec „pierwszej operacji”."""
    plan=plan_for(ctx,enemy)
    if plan is None or plan.stage not in ('ACTIVE','NEGOTIATION'):return
    save(plan.id,operations=(plan.operations or 0)+1,last_operation_at=ctx.now,first_operation_pending=False,idle_cycles=0,
         note=f'Operacja: {label}.',now=ctx.now)
    ctx._war_plans=None


def first_operation_triggers(session,country_id):
    """Wyzwalacze reakcji doraźnej: plany po wypowiedzeniu wojny bez pierwszej operacji (limit prób)."""
    from game.paga2.models import Paga2WarPlan
    if not _table_ready(session):return []
    rows=list(session.scalars(select(Paga2WarPlan).where(Paga2WarPlan.country_id==country_id,Paga2WarPlan.stage=='ACTIVE',
                                                       Paga2WarPlan.first_operation_pending.is_(True),Paga2WarPlan.first_operation_attempts<MAX_FIRST_OPERATION_ATTEMPTS)))
    result=[]
    for row in rows:
        row.first_operation_attempts=(row.first_operation_attempts or 0)+1
        result.append({'kind':'war_plan_operation','label':'pierwsza operacja planu wojennego','source':'plan wojenny','id':-row.id,'from':row.enemy_id,
                       'text':f'Plan wojenny #{row.id}: wypowiedziano wojnę — pierwsza operacja (próba {row.first_operation_attempts}).','attempt':row.first_operation_attempts,'plan_id':row.id})
    return result


def admin_view(session,country_id,names=None):
    """WIKI → Stan państwa PAGA: plany wojenne (także zakończone, ostatnie 20)."""
    from game.paga2.models import Paga2WarPlan
    if not _table_ready(session):return []
    rows=list(session.scalars(select(Paga2WarPlan).where(Paga2WarPlan.country_id==country_id).order_by(Paga2WarPlan.id.desc()).limit(20)))
    stamp=lambda v:v.isoformat()+'Z' if v else None
    return [{'id':r.id,'enemyId':r.enemy_id,'enemy':(names or {}).get(r.enemy_id),'kind':r.kind,'allyId':r.ally_id,'ally':(names or {}).get(r.ally_id),
             'stage':r.stage,'stageLabel':STAGE_LABELS.get(r.stage,r.stage),'reason':r.reason,'goal':r.goal,'extraGoals':r.extra_goals,'targets':r.targets,
             'areas':(r.assessment or {}).get('areas',{}),'areaLabels':AREAS,'notes':(r.assessment or {}).get('notes',[]),'readiness':r.readiness,'shortfalls':r.shortfalls,
             'operations':r.operations,'idleCycles':r.idle_cycles,'intelAttempts':r.intel_attempts,'history':r.history,'endReason':r.end_reason,
             'declaredAt':stamp(r.declared_at),'lastOperationAt':stamp(r.last_operation_at),'createdAt':stamp(r.game_created_at),'finishedAt':stamp(r.finished_at)} for r in rows]
