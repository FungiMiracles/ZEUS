"""Operacje panelu administratora PAGA2 (zakładki: PAGA2, Konfiguracja, Historia decyzji, Stan państwa).

Administrator widzi pełne dane państwa; ograniczenie do informacji jawnych dotyczy wyłącznie algorytmu (view.py).
"""
from datetime import timedelta
from sqlalchemy import select,func,or_
from sqlalchemy.orm import lazyload
from models import Panstwo
from game.paga2 import catalog
from game.paga2.models import Paga2Control,Paga2Profile,Paga2ProfileRevision,Paga2Decision,Paga2RandomDraw,utc_now

INTERVAL_RANGE=(5,10080)
PAGE=25


class AdminError(ValueError):pass
class AdminConflict(AdminError):pass


def stamp(value):return value.isoformat()+'Z' if value else None


def catalog_data():
    return {'categories':{key:{'label':item['label'],'description':item['description'],'future':item.get('future',[])} for key,item in catalog.CATEGORIES.items()},
            'priorities':catalog.PRIORITIES,'traits':catalog.TRAITS,'maxCategories':catalog.MAX_CATEGORIES,'relationships':catalog.RELATIONSHIPS}


def human_ids(session):
    from game.models import GamePlayerCountry
    return set(session.scalars(select(GamePlayerCountry.panstwo_id)))


# ---------------- zakładka PAGA2: państwa i profile ----------------

def countries_overview(session):
    """Lista aktywnych państw do mapy i listy wyboru, ze stanem profilu PAGA2."""
    profiles={row.panstwo_id:row for row in session.scalars(select(Paga2Profile))}
    humans=human_ids(session)
    result=[]
    for id,name,sovereign in session.execute(select(Panstwo.PANSTWO_ID,Panstwo.panstwo_nazwa,Panstwo.czy_suwerenny).where(Panstwo.status=='aktywne').order_by(Panstwo.panstwo_nazwa)):
        profile=profiles.get(id)
        status='human' if id in humans else 'none' if profile is None else 'active' if profile.autonomy_enabled else 'profile'
        result.append({'id':id,'name':name,'sovereign':sovereign=='TAK','status':status,'migrated':bool(profile and profile.source=='migrated'),
                       'categories':profile.categories if profile else []})
    return result


def profile_data(row):
    if row is None:
        return {'revision':0,'categories':[],'priorities':[],'traits':catalog.default_profile(),'autonomyEnabled':False,'source':None,'updatedAt':None,'actor':None}
    traits=catalog.default_profile(row.traits)
    return {'revision':row.revision,'categories':list(row.categories or []),'priorities':list(row.priorities or []),'traits':traits,
            'autonomyEnabled':bool(row.autonomy_enabled),'source':row.source,'updatedAt':stamp(row.updated_at),'actor':row.actor}


def country_header(session,country_id):
    row=session.execute(select(Panstwo.PANSTWO_ID,Panstwo.panstwo_nazwa,Panstwo.panstwo_pelna_nazwa,Panstwo.czy_suwerenny).where(Panstwo.PANSTWO_ID==country_id,Panstwo.status=='aktywne')).first()
    if row is None:raise LookupError(country_id)
    return {'id':row[0],'name':row[1],'fullName':row[2] or row[1],'sovereign':row[3]=='TAK','human':country_id in human_ids(session)}


def save_profile(session,country_id,data,actor):
    """Zapis profilu z kontrolą wersji. Synchronizuje flagę autonomii dotychczasowej konfiguracji PAGA."""
    if not isinstance(data,dict):raise AdminError('Nieprawidłowe dane profilu.')
    categories,priorities,traits=catalog.validate_profile(data)
    autonomy=data.get('autonomyEnabled')
    if type(autonomy) is not bool:raise AdminError('Autonomia musi mieć wartość Włączona lub Wyłączona.')
    if type(data.get('revision')) is not int:raise AdminError('Nieprawidłowa wersja profilu.')
    country=session.scalar(select(Panstwo).options(lazyload('*')).where(Panstwo.PANSTWO_ID==country_id,Panstwo.status=='aktywne').with_for_update())
    if country is None:raise AdminError('Nie znaleziono aktywnego państwa.')
    if autonomy and country_id in human_ids(session):raise AdminError('Państwo ma gracza ludzkiego — nie można włączyć autonomii PAGA2.')
    if autonomy and country.czy_suwerenny!='TAK':raise AdminError('Państwo niesuwerenne nie może być zarządzane autonomicznie.')
    row=session.scalar(select(Paga2Profile).where(Paga2Profile.panstwo_id==country_id).with_for_update())
    if data['revision']!=(row.revision if row else 0):raise AdminConflict('Profil zmieniono w innym oknie. Wybierz państwo ponownie, aby wczytać aktualne dane.')
    now=utc_now();actor=str(actor)[:120]
    if row is None:row=Paga2Profile(panstwo_id=country_id,revision=0);session.add(row)
    row.categories=categories;row.priorities=priorities;row.traits=traits;row.autonomy_enabled=autonomy
    row.source='admin';row.revision+=1;row.updated_at=now;row.actor=actor
    session.add(Paga2ProfileRevision(panstwo_id=country_id,revision=row.revision,actor=actor,created_at=now,
                                     configuration={'categories':categories,'priorities':priorities,'traits':traits,'autonomyEnabled':autonomy}))
    # Dotychczasowa konfiguracja PAGA zachowuje tę samą flagę, aby wszystkie moduły widziały jedno źródło decyzji.
    from game.paga import PagaConfiguration
    legacy=session.get(PagaConfiguration,country_id)
    if legacy is not None:legacy.autonomy_enabled=autonomy;legacy.draft_autonomy_enabled=None
    session.flush()
    return profile_data(row)


def profile_history(session,country_id,limit=10):
    return [{'revision':row.revision,'actor':row.actor,'at':stamp(row.created_at),'configuration':row.configuration}
            for row in session.scalars(select(Paga2ProfileRevision).where(Paga2ProfileRevision.panstwo_id==country_id).order_by(Paga2ProfileRevision.revision.desc()).limit(limit))]


# ---------------- zakładka Konfiguracja PAGA2 ----------------

def control_row(session,*,lock=False):
    query=select(Paga2Control).where(Paga2Control.id==1).execution_options(populate_existing=True)
    if lock:query=query.with_for_update()
    row=session.scalar(query)
    if row is None:raise AdminError('Brak konfiguracji PAGA2. Wykonaj migrację UAT.')
    return row


def control_data(session):
    row=control_row(session)
    from game.paga2 import randomizer
    now=utc_now()
    names=dict(session.execute(select(Panstwo.PANSTWO_ID,Panstwo.panstwo_nazwa)).all())
    per_country=[{'countryId':id,'country':names.get(id),'calls':count} for id,count in session.execute(
        select(Paga2RandomDraw.country_id,func.count(Paga2RandomDraw.id)).group_by(Paga2RandomDraw.country_id).order_by(func.count(Paga2RandomDraw.id).desc()).limit(10))]
    recent=[{'id':draw.id,'countryId':draw.country_id,'country':names.get(draw.country_id),'reason':draw.reason,'candidates':draw.candidates,'chosen':draw.chosen,'at':stamp(draw.created_at)}
            for draw in session.scalars(select(Paga2RandomDraw).order_by(Paga2RandomDraw.id.desc()).limit(20))]
    active=session.scalar(select(func.count()).select_from(Paga2Profile).where(Paga2Profile.autonomy_enabled.is_(True)))
    return {'enabled':row.enabled,'intervalMinutes':row.interval_minutes,'revision':row.revision,'lastCycleAt':stamp(row.last_cycle_at),
            'updatedAt':stamp(row.updated_at),'actor':row.actor,'intervalRange':list(INTERVAL_RANGE),'autonomousCountries':active,
            'randomizer':{'total':randomizer.calls(session),'last24h':randomizer.calls(session,since=now-timedelta(hours=24)),
                          'last7d':randomizer.calls(session,since=now-timedelta(days=7)),'perCountry':per_country,'recent':recent}}


def save_control(session,data,actor):
    if not isinstance(data,dict) or type(data.get('enabled')) is not bool or type(data.get('revision')) is not int:raise AdminError('Nieprawidłowe ustawienia PAGA2.')
    interval=data.get('intervalMinutes')
    if type(interval) is not int or not INTERVAL_RANGE[0]<=interval<=INTERVAL_RANGE[1]:
        raise AdminError(f'Częstotliwość: liczba całkowita od {INTERVAL_RANGE[0]} do {INTERVAL_RANGE[1]} minut.')
    row=control_row(session,lock=True)
    if row.revision!=data['revision']:raise AdminConflict('Konfigurację PAGA2 zmieniono w innym oknie. Odśwież zakładkę.')
    row.enabled=data['enabled'];row.interval_minutes=interval;row.revision+=1;row.updated_at=utc_now();row.actor=str(actor)[:120]
    session.flush()
    return control_data(session)


# ---------------- zakładka Historia decyzji ----------------

DOMAINS={'finance':'Podatki i budżet','economy':'Infrastruktura i energetyka','research':'Badania i rozwój','trade':'Handel',
         'diplomacy':'Dyplomacja','defense':'Obrona państwa','war':'Panel wojenny','intelligence':'Wywiad wojskowy',
         'army':'Siły zbrojne','communication':'Forum i wiadomości','planning':'Planowanie'}
STATUSES={'EXECUTED':'Wykonana','REJECTED':'Odrzucona przez grę','PASSIVE':'Bez działania','ERROR':'Błąd','PLANNED':'Zaplanowana'}
MODES={'CYCLIC':'Cykliczny','IMMEDIATE':'Doraźny','BUDGET':'Budżetowy'}


def decision_summary(row,names):
    return {'id':row.id,'countryId':row.country_id,'country':names.get(row.country_id),'mode':row.mode,'trigger':row.trigger,'domain':row.domain,
            'action':row.action,'targetId':row.target_id,'target':names.get(row.target_id) if row.target_id else None,'status':row.status,
            'score':row.score,'randomized':row.randomized,'gameAt':stamp(row.game_at),'createdAt':stamp(row.created_at),'error':row.error}


def decision_stats(session,filters):
    """14 Nov 2026: statystyki zdarzeń PAGA2 w zakładce Historia decyzji (filtry państwa, obszaru i trybu; status — w podziale)."""
    conditions=[]
    if filters.get('country'):conditions.append(Paga2Decision.country_id==filters['country'])
    if filters.get('domain'):conditions.append(Paga2Decision.domain==filters['domain'])
    if filters.get('mode'):conditions.append(Paga2Decision.mode==filters['mode'])
    count=lambda *extra:session.scalar(select(func.count(Paga2Decision.id)).where(*conditions,*extra)) or 0
    by_status=dict(session.execute(select(Paga2Decision.status,func.count(Paga2Decision.id)).where(*conditions).group_by(Paga2Decision.status)).all())
    since=utc_now().replace(tzinfo=None)-timedelta(hours=24)
    # Odrzucenia liczone na poziomie pojedynczych prób (decyzja może mieć kilka akcji, np. „VESSEL_SAIL+VESSEL_SAIL”).
    attempts={}
    for (options,) in session.execute(select(Paga2Decision.options).where(*conditions,Paga2Decision.status=='REJECTED')).yield_per(200):
        for option in options or []:
            if str(option.get('blocked') or '').startswith('Gra odrzuciła'):
                key=(option.get('domain'),option.get('action'));attempts[key]=attempts.get(key,0)+1
    rejected=[(domain,action,n) for (domain,action),n in sorted(attempts.items(),key=lambda item:-item[1])[:5]]
    domains=session.execute(select(Paga2Decision.domain,func.count(Paga2Decision.id)).where(*conditions).group_by(Paga2Decision.domain).order_by(func.count(Paga2Decision.id).desc())).all()
    return {'total':sum(by_status.values()),'byStatus':{key:int(by_status.get(key,0)) for key in STATUSES},
            'last24h':count(Paga2Decision.created_at>=since),'randomized':count(Paga2Decision.randomized.is_(True)),
            'countries':session.scalar(select(func.count(func.distinct(Paga2Decision.country_id))).where(*conditions)) or 0,
            'topRejected':[{'domain':domain,'action':action,'count':int(n)} for domain,action,n in rejected],
            'domains':[{'domain':domain,'count':int(n)} for domain,n in domains]}


def decisions(session,filters,page):
    query=select(Paga2Decision)
    if filters.get('country'):query=query.where(Paga2Decision.country_id==filters['country'])
    if filters.get('domain'):query=query.where(Paga2Decision.domain==filters['domain'])
    if filters.get('status'):query=query.where(Paga2Decision.status==filters['status'])
    if filters.get('mode'):query=query.where(Paga2Decision.mode==filters['mode'])
    page=max(1,min(10000,page))
    rows=list(session.scalars(query.order_by(Paga2Decision.id.desc()).offset((page-1)*PAGE).limit(PAGE+1)))
    names=dict(session.execute(select(Panstwo.PANSTWO_ID,Panstwo.panstwo_nazwa)).all())
    countries=[{'id':id,'name':names.get(id)} for id in session.scalars(select(Paga2Decision.country_id).distinct())]
    countries.sort(key=lambda item:item['name'] or '')
    return {'page':page,'hasMore':len(rows)>PAGE,'items':[decision_summary(row,names) for row in rows[:PAGE]],
            'countries':countries,'domains':DOMAINS,'statuses':STATUSES,'modes':MODES,'stats':decision_stats(session,filters)}


def decision_detail(session,decision_id):
    row=session.get(Paga2Decision,decision_id)
    if row is None:raise LookupError(decision_id)
    names=dict(session.execute(select(Panstwo.PANSTWO_ID,Panstwo.panstwo_nazwa)).all())
    draws=[{'reason':d.reason,'candidates':d.candidates,'chosen':d.chosen,'at':stamp(d.created_at)} for d in session.scalars(select(Paga2RandomDraw).where(Paga2RandomDraw.decision_key==row.request_key))]
    return {**decision_summary(row,names),'options':row.options,'inputs':row.inputs,'result':row.result,'draws':draws}


# ---------------- zakładka Stan państwa PAGA ----------------

def _money(value):return float(value) if value is not None else None


def country_state(session,country_id):
    """Pełny obraz państwa dla administratora (odczyt, bez skutków w grze)."""
    from game.governance import controlled_ids
    from game.finance_models import StateBudget,StateBudgetAllocation,StateFinancialAccount
    from game.budget_overview import budget_overview,LABELS
    from game.military_models import MilitaryBase,MilitaryVessel,MissileDefense
    from game.commerce_models import Mine,ResourceStock
    from game.industry_models import PowerPlant
    from game.research_models import AmmunitionFactory,ResearchAccount
    from game.radar_models import Radar
    from game.intelligence_models import IntelligenceAgent
    from game.industry_catalog import TECHNOLOGIES
    from game.communication_models import PrivateMessage
    from models import Wojsko,Stosunki,DictStosunkiRelacja,DictStosunkiStan,Region
    header=country_header(session,country_id)
    names=dict(session.execute(select(Panstwo.PANSTWO_ID,Panstwo.panstwo_nazwa)).all())
    # finanse i budżet
    account=session.scalar(select(StateFinancialAccount).where(StateFinancialAccount.panstwo_id==country_id))
    budget=session.scalar(select(StateBudget).where(StateBudget.panstwo_id==country_id).order_by(StateBudget.game_year.desc(),StateBudget.period.desc()).limit(1))
    allocations=[]
    if budget is not None:
        allocations=[{'code':row.category_code,'label':LABELS.get(row.category_code,row.category_code),'share':_money(row.share_percent),'amount':_money(row.amount)}
                     for row in session.scalars(select(StateBudgetAllocation).where(StateBudgetAllocation.budget_id==budget.id))]
    try:overview=budget_overview(session,country_id)
    except Exception:overview={'items':[]}
    finance={'reserve':_money(account.reserve_balance) if account else None,
             'budget':None if budget is None else {'year':budget.game_year,'period':budget.period,'opening':_money(budget.opening_reserve),'tax':_money(budget.tax_total),
                                                    'total':_money(budget.budget_total),'expenditure':_money(budget.expenditure_total),'closing':_money(budget.closing_reserve),
                                                    'mode':budget.approval_mode,'approvedAt':stamp(budget.approved_at),'allocations':allocations},
             'remaining':[{'code':item['code'],'label':item['label'],'remaining':_money(item['remaining'])} for item in overview.get('items',[])]}
    # obiekty na mapie
    objects=[];counts={}
    def add(kind,label,rows,position=lambda r:(r.map_x,r.map_y),extra=lambda r:{}):
        items=list(rows);counts[kind]={'label':label,'count':len(items)}
        for row in items:
            x,y=position(row)
            objects.append({'kind':kind,'id':row.id,'regionId':getattr(row,'region_id',None),'x':x,'y':y,'health':getattr(row,'health',None),'level':getattr(row,'level',None),**extra(row)})
    for kind,label in (('land','Bazy lądowe'),('air','Bazy powietrzne'),('naval','Bazy morskie'),('nuclear','Silosy atomowe')):
        add('base_'+kind,label,session.scalars(select(MilitaryBase).where(MilitaryBase.panstwo_id==country_id,MilitaryBase.kind==kind)),extra=lambda r:{'name':r.name,'garrison':r.garrison})
    add('mine','Kopalnie',session.scalars(select(Mine).where(Mine.panstwo_id==country_id,Mine.removed_at.is_(None))),extra=lambda r:{'resource':r.resource})
    add('factory','Fabryki',session.scalars(select(AmmunitionFactory).where(AmmunitionFactory.panstwo_id==country_id,AmmunitionFactory.removed_at.is_(None))),extra=lambda r:{'product':r.kind})
    add('power','Elektrownie',session.scalars(select(PowerPlant).where(PowerPlant.panstwo_id==country_id,PowerPlant.removed_at.is_(None))),extra=lambda r:{'type':r.kind,'filter':r.air_filter})
    add('radar','Radary',session.scalars(select(Radar).where(Radar.panstwo_id==country_id)))
    vessels=list(session.scalars(select(MilitaryVessel).where(MilitaryVessel.panstwo_id==country_id)))
    counts['vessel']={'label':'Okręty na morzu','count':len(vessels)}
    counts['defense']={'label':'Obrony przeciwrakietowe','count':session.scalar(select(func.count()).select_from(MissileDefense).where(MissileDefense.panstwo_id==country_id))}
    counts['agent']={'label':'Agenci wywiadu','count':session.scalar(select(func.count()).select_from(IntelligenceAgent).where(IntelligenceAgent.panstwo_id==country_id,IntelligenceAgent.captured_at.is_(None)))}
    # technologie
    research=session.get(ResearchAccount,country_id)
    nodes=(research.nodes or {}) if research else {}
    from game.research_timing import developed as tech_developed
    from game.finance_service import game_now
    timers=(getattr(research,'timers',None) or {}) if research else {};moment=game_now()
    technologies=[{'code':code,'label':item['label'],'invested':int(nodes.get(code,0)),'cost':item['cost'],'developed':tech_developed(nodes,timers,code,moment)} for code,item in TECHNOLOGIES.items() if nodes.get(code)]
    # relacje
    relation_names=dict(session.execute(select(DictStosunkiRelacja.relacja_id,DictStosunkiRelacja.relacja_nazwa)).all())
    state_names=dict(session.execute(select(DictStosunkiStan.stan_id,DictStosunkiStan.stan_nazwa)).all())
    relations=[]
    for row in session.scalars(select(Stosunki).options(lazyload('*')).where(or_(Stosunki.PANSTWO_ID==country_id,Stosunki.PANSTWO_ID2==country_id))):
        other=row.PANSTWO_ID2 if row.PANSTWO_ID==country_id else row.PANSTWO_ID
        relations.append({'countryId':other,'country':names.get(other),'relation':relation_names.get(row.relacja_id),'state':state_names.get(row.stan_id)})
    relations.sort(key=lambda item:item['country'] or '')
    # siły zbrojne i surowce
    army=session.scalar(select(Wojsko).options(lazyload('*')).where(Wojsko.panstwo_id==country_id))
    forces={column.key:getattr(army,column.key) for column in Wojsko.__table__.columns if column.key not in ('panstwo_id',)} if army else {}
    stocks={row.resource:int(row.quantity) for row in session.scalars(select(ResourceStock).where(ResourceStock.panstwo_id==country_id))}
    # wiadomości prywatne
    messages=[{'id':m.id,'from':m.sender_country_name,'to':m.recipient_country_name,'outgoing':m.sender_country_id==country_id,'content':m.content,'at':stamp(m.created_at),'read':m.read_at is not None}
              for m in session.scalars(select(PrivateMessage).where(or_(PrivateMessage.sender_country_id==country_id,PrivateMessage.recipient_country_id==country_id)).order_by(PrivateMessage.id.desc()).limit(30))]
    regions=[{'id':id,'name':name} for id,name in session.execute(select(Region.region_id,Region.region_nazwa).where(Region.panstwo_id.in_(controlled_ids(session,country_id) or [country_id])).order_by(Region.region_nazwa))]
    profile=profile_data(session.get(Paga2Profile,country_id))
    from game.paga2.models import Paga2Plan,table_ready
    plans=[]
    if table_ready(session,Paga2Plan):
        from game.paga2.planner import goal_label
        from game.paga2.catalog import PRIORITIES
        for row in session.scalars(select(Paga2Plan).where(Paga2Plan.country_id==country_id).order_by(Paga2Plan.status!='ACTIVE',Paga2Plan.id.desc()).limit(20)):
            plans.append({'id':row.id,'goal':row.goal,'label':goal_label(row.goal),'priority':PRIORITIES.get(row.priority,row.priority),'status':row.status,
                          'reason':row.reason,'steps':row.steps,'createdAt':stamp(row.created_at),'updatedAt':stamp(row.updated_at),'finishedAt':stamp(row.finished_at)})
    return {'country':header,'profile':profile,'plans':plans,'finance':finance,'counts':counts,'objects':objects,'technologies':technologies,'researchPoints':int(research.points) if research else 0,
            'relations':relations,'army':forces,'stocks':stocks,'messages':messages,'regions':regions}
