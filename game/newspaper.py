"""Gazeta „Entenda News” (28 Nov 2026) — ekran „Wydarzenia”.

Raz na miesiąc Entendy ZEUS zbiera fakty z minionego miesiąca (wyłącznie dane jawne, widoczne dla wszystkich państw):

- najważniejsze wydarzenie: wypowiedzenie lub zakończenie wojny, zawieszenie broni, wyniesienie satelity na orbitę,
  pozyskanie broni atomowej, utrata niepodległości (kolejne wydarzenia tej rangi trafiają na początek mniejszych newsów),
- mniejsze newsy: opracowane technologie, nowe linie kolejowe, nowe lotniska, pozwolenia na bazy w obcym państwie,
- statystyki miesiąca: kontakty handlowe, wydobycie surowców, pożyczki z MFW.

Teksty pisze model AI odpowiedzialny za wpisy na forum (Groq, zastępczo Gemini — PAGA MULTI-AI). Model dostaje tylko
zebrane fakty i nie może dodawać nowych. Gdy modele są wyłączone albo trzykrotnie zawiodą, wydanie ukazuje się z tekstem
przygotowanym przez ZEUS. Daty z czasem gry (wojny, satelity, kolej, lotniska, MFW, utrata niepodległości) liczone są
w oknie miesiąca; zmiany bez daty gry (technologie, broń atomowa, pozwolenia na bazy, wydobycie) — z porównania
migawki stanu świata z migawką poprzedniego wydania (pierwsze wydanie nie ma bazy porównania).
"""
from datetime import datetime,timedelta
from decimal import Decimal
from flask import Blueprint,render_template,redirect,url_for,request,abort
from sqlalchemy import select,func,or_
from sqlalchemy.orm import Session
from extensions import db
from game.models import utc_now

MONTHS=('styczeń','luty','marzec','kwiecień','maj','czerwiec','lipiec','sierpień','wrzesień','październik','listopad','grudzień')
MONTHS_GEN=('stycznia','lutego','marca','kwietnia','maja','czerwca','lipca','sierpnia','września','października','listopada','grudnia')
MAX_ATTEMPTS=3
RETRY_MINUTES=20
MAIN_PRIORITY=('SOVEREIGNTY_LOST','WAR_STARTED','NUCLEAR','WAR_ENDED','CEASEFIRE','SATELLITE')
MINOR_ORDER=('TECHNOLOGY','RAIL','AIRPORT','BASE_PERMIT')
MAX_MINOR=12
MAX_PER_KIND=4   # mniejsze newsy jednego rodzaju (np. kolej) nie wypierają pozostałych
TEXT_LIMITS={'title':160,'body':1800}


class NewspaperIssue(db.Model):
    __tablename__='game_newspaper_issues'
    id=db.Column(db.Integer,primary_key=True)
    game_year=db.Column(db.Integer,nullable=False)
    game_month=db.Column(db.SmallInteger,nullable=False)
    period_start=db.Column(db.DateTime,nullable=False)
    period_end=db.Column(db.DateTime,nullable=False)
    status=db.Column(db.String(16),nullable=False,default='PENDING')       # PENDING / PUBLISHED
    facts=db.Column(db.JSON,nullable=False)
    snapshot=db.Column(db.JSON,nullable=False)
    content=db.Column(db.JSON)
    author=db.Column(db.String(16))                                          # AI / ZEUS
    provider=db.Column(db.String(32))
    model=db.Column(db.String(80))
    attempts=db.Column(db.Integer,nullable=False,default=0)
    next_attempt_at=db.Column(db.DateTime)
    error=db.Column(db.String(500))
    created_at=db.Column(db.DateTime,nullable=False,default=utc_now)
    published_at=db.Column(db.DateTime)
    __table_args__=(db.UniqueConstraint('game_year','game_month',name='uq_newspaper_month'),
                    db.CheckConstraint("status IN ('PENDING','PUBLISHED')",name='ck_newspaper_status'),{'mysql_engine':'InnoDB'})


def tables_ready(session):
    from sqlalchemy import inspect
    try:return 'game_newspaper_issues' in inspect(session.get_bind()).get_table_names()
    except Exception:return False


def month_start(moment):return datetime(moment.year,moment.month,1)


def previous_month(moment):
    """(początek, koniec) miesiąca Entendy poprzedzającego `moment`."""
    end=month_start(moment);start=month_start(end-timedelta(days=1))
    return start,end


def month_label(year,month):return f'{MONTHS[month-1]} {year}'


# ---------------- migawka stanu świata ----------------

def snapshot(session,now):
    """Stan do porównania z następnym wydaniem: opracowane technologie, broń atomowa, aktywne pozwolenia na bazy, złoża."""
    from game.research_models import ResearchAccount
    from game.research_timing import developed
    from game.industry_catalog import TECHNOLOGIES
    from game.commerce_models import ResourceStock
    from game.nuclear import STOCK_CODE
    result={'at':now.isoformat(),'technologies':{},'nuclear':{},'permits':[],'deposits':{}}
    for account in session.scalars(select(ResearchAccount)):
        nodes=[node for node in TECHNOLOGIES if developed(account.nodes or {},account.timers,node,now)]
        if nodes:result['technologies'][str(account.panstwo_id)]=sorted(nodes)
    for country,quantity in session.execute(select(ResourceStock.panstwo_id,ResourceStock.quantity).where(ResourceStock.resource==STOCK_CODE)):
        result['nuclear'][str(country)]=int(quantity or 0)
    try:
        from game.base_permits import BasePermit
        result['permits']=[[p.id,p.host_country_id,p.guest_country_id,p.region_id] for p in session.scalars(select(BasePermit).where(BasePermit.status=='ACTIVE').order_by(BasePermit.id))]
    except Exception:result['permits']=[]
    result['deposits']=deposits(session)
    return result


def deposits(session):
    """{kod surowca: łączne złoże w regionach} — wyłącznie surowce wydobywane w kopalniach."""
    from models import RegionZasob
    from game.industry_catalog import MINE_RULES
    try:
        from game.mining_service import resource_ids
        ids=resource_ids(session)
    except Exception:return {}
    totals=dict(session.execute(select(RegionZasob.zasob_id,func.coalesce(func.sum(RegionZasob.zloze_ilosc),0)).group_by(RegionZasob.zasob_id)).all())
    return {code:int(totals.get(ids[code],0) or 0) for code in MINE_RULES if code in ids}


# ---------------- fakty miesiąca ----------------

def collect_facts(session,start,end,previous,current):
    from models import Panstwo
    names={id:name for id,name in session.execute(select(Panstwo.PANSTWO_ID,Panstwo.panstwo_nazwa))}
    name=lambda id:names.get(int(id),f'państwo {id}') if id is not None else 'nieznane państwo'
    events=[]
    events+=_diplomacy(session,start,end,name)
    events+=_satellites(session,start,end,name)
    events+=_sovereignty(session,start,end,name)
    events+=_rail(session,start,end,name)
    events+=_airports(session,start,end,name)
    events+=_technologies(session,start,end,previous,current,name)
    if previous:
        events+=_nuclear(previous,current,name)
        events+=_permits(session,previous,current,name)
    main=sorted([e for e in events if e['kind'] in MAIN_PRIORITY],key=lambda e:(MAIN_PRIORITY.index(e['kind']),e.get('at') or ''))
    minor=sorted([e for e in events if e['kind'] in MINOR_ORDER],key=lambda e:(MINOR_ORDER.index(e['kind']),e.get('at') or ''))
    used={};limited=[]
    for item in minor:
        used[item['kind']]=used.get(item['kind'],0)+1
        if used[item['kind']]<=MAX_PER_KIND:limited.append(item)
    minor=limited
    lead=main[0] if main else None
    others=(main[1:]+minor)[:MAX_MINOR]
    for index,item in enumerate(([lead] if lead else [])+others,start=1):item['id']=index
    return {'month':month_label(start.year,start.month),'period':[start.isoformat(),end.isoformat()],'lead':lead,'news':others,
            'stats':statistics(session,start,end,previous,current,name),'baseline':bool(previous)}


def _diplomacy(session,start,end,name):
    from models import AudytStosunki,DictStosunkiStan
    from services.natural_resources import normalized
    states={id:normalized(label or '') for id,label in session.execute(select(DictStosunkiStan.stan_id,DictStosunkiStan.stan_nazwa))}
    result=[];seen=set()
    for audit in session.scalars(select(AudytStosunki).where(AudytStosunki.data_zmiany_entenda>=start,AudytStosunki.data_zmiany_entenda<end).order_by(AudytStosunki.id)):
        before_id=session.scalar(select(AudytStosunki.stan_id).where(AudytStosunki.panstwo_id==audit.panstwo_id,AudytStosunki.panstwo_id2==audit.panstwo_id2,AudytStosunki.id<audit.id).order_by(AudytStosunki.id.desc()).limit(1))
        before=states.get(before_id,'pokoj') if before_id is not None else 'pokoj';after=states.get(audit.stan_id,'')
        war=lambda value:value.startswith('wojna')
        a,b=name(audit.panstwo_id),name(audit.panstwo_id2)
        if war(after) and not war(before):kind,text='WAR_STARTED',f'{a} i {b}: wypowiedzenie wojny — rozpoczęła się wojna.'
        elif after=='zawieszeniebroni' and before!='zawieszeniebroni':kind,text='CEASEFIRE',f'{a} i {b}: zawieszenie broni.'
        elif (war(before) or before in ('zawieszeniebroni','okupacja')) and after=='pokoj':kind,text='WAR_ENDED',f'{a} i {b}: zakończenie wojny, zawarto pokój.'
        else:continue
        key=(kind,tuple(sorted((audit.panstwo_id,audit.panstwo_id2))))
        if key in seen:continue
        seen.add(key)
        result.append({'kind':kind,'countries':[a,b],'at':audit.data_zmiany_entenda.isoformat(),'fact':text})
    return result


def _satellites(session,start,end,name):
    from game.satellites import tables_ready as satellites_ready
    if not satellites_ready(session):return []
    from game.satellite_models import SpySatellite
    counts={}
    for country,at in session.execute(select(SpySatellite.panstwo_id,SpySatellite.launched_at).where(SpySatellite.launched_at>=start,SpySatellite.launched_at<end)):
        item=counts.setdefault(country,[0,at]);item[0]+=1;item[1]=min(item[1],at)
    def what(n):return 'satelitę szpiegowskiego' if n==1 else f'{n} satelity szpiegowskie' if n%10 in (2,3,4) and n%100 not in (12,13,14) else f'{n} satelitów szpiegowskich'
    return [{'kind':'SATELLITE','countries':[name(country)],'at':at.isoformat(),'count':n,'fact':f'Państwo {name(country)} wyniosło na orbitę {what(n)}.'}
            for country,(n,at) in counts.items()]


def _sovereignty(session,start,end,name):
    from game.land_war_models import SovereigntyLoss
    try:rows=list(session.scalars(select(SovereigntyLoss).where(SovereigntyLoss.lost_at>=start,SovereigntyLoss.lost_at<end)))
    except Exception:return []
    return [{'kind':'SOVEREIGNTY_LOST','countries':[name(row.panstwo_id),name(row.annexed_by)],'at':row.lost_at.isoformat(),
             'fact':f'Państwo {name(row.panstwo_id)} utraciło niepodległość — region stołeczny anektowało państwo {name(row.annexed_by)}.'} for row in rows]


def _rail(session,start,end,name):
    """Ukończone linie kolejowe — jeden news na państwo budujące (z partnerami współfinansującymi)."""
    from game.rail_models import RailLine
    from models import Miasto
    try:rows=list(session.scalars(select(RailLine).where(RailLine.status=='ACTIVE',RailLine.ready_at>=start,RailLine.ready_at<end).order_by(RailLine.ready_at)))
    except Exception:return []
    cities={id:label for id,label in session.execute(select(Miasto.miasto_id,Miasto.miasto_nazwa).where(Miasto.miasto_id.in_({r.city_a_id for r in rows}|{r.city_b_id for r in rows})))} if rows else {}
    groups={}
    for line in rows:
        item=groups.setdefault(line.initiator_id,{'lines':[],'partners':[],'km':0,'at':line.ready_at})
        km=round(float(line.distance_km or 0));item['km']+=km
        item['lines'].append(f'{cities.get(line.city_a_id,"miasto")} – {cities.get(line.city_b_id,"miasto")} ({km} km)')
        if line.partner_id and name(line.partner_id) not in item['partners']:item['partners'].append(name(line.partner_id))
    result=[]
    for country,item in groups.items():
        n=len(item['lines']);what='linię kolejową' if n==1 else f'{n} linie kolejowe' if n%10 in (2,3,4) and n%100 not in (12,13,14) else f'{n} linii kolejowych'
        text=f'Państwo {name(country)} ukończyło {what}: '+', '.join(item['lines'][:6])+(f' i {n-6} innych' if n>6 else '')+f' — łącznie {item["km"]} km.'
        if item['partners']:text+=' Współfinansowanie: '+', '.join(item['partners'])+'.'
        result.append({'kind':'RAIL','countries':[name(country),*item['partners']],'at':item['at'].isoformat(),'km':item['km'],'fact':text})
    return result


def _airports(session,start,end,name):
    from game.airport_models import Airport
    from models import Miasto
    try:rows=list(session.execute(select(Airport,Miasto.miasto_nazwa).outerjoin(Miasto,Miasto.miasto_id==Airport.miasto_id).where(Airport.ready_at>=start,Airport.ready_at<end,Airport.removed_at.is_(None))))
    except Exception:return []
    return [{'kind':'AIRPORT','countries':[name(airport.panstwo_id)],'at':airport.ready_at.isoformat(),
             'fact':f'Państwo {name(airport.panstwo_id)} otworzyło port lotniczy „{airport.name}” w mieście {city or "—"}.'} for airport,city in rows]


def _technologies(session,start,end,previous,current,name):
    """Technologie opracowane w miesiącu: koniec czasu rozwoju w oknie miesiąca (czas gry) oraz — gdy jest migawka
    poprzedniego wydania — technologie opracowane bez czasu rozwoju (porównanie migawek)."""
    from game.industry_catalog import TECHNOLOGIES
    from game.research_models import ResearchAccount
    from game.research_timing import funded,ready_at
    found={}
    for account in session.scalars(select(ResearchAccount)):
        for node in TECHNOLOGIES:
            ready=ready_at(account.timers,node)
            if ready is not None and start<=ready<end and funded(account.nodes or {},node):found.setdefault(str(account.panstwo_id),[]).append(node)
    if previous:
        for country,nodes in (current.get('technologies') or {}).items():
            before=set((previous.get('technologies') or {}).get(country,[]))
            for node in nodes:
                if node not in before and node not in found.get(country,[]):found.setdefault(country,[]).append(node)
    result=[]
    for country,nodes in found.items():
        labels=[TECHNOLOGIES[node]['label'] for node in nodes if node in TECHNOLOGIES]
        if not labels:continue
        result.append({'kind':'TECHNOLOGY','countries':[name(country)],'technologies':labels,
                       'fact':f'Państwo {name(country)} opracowało technologi{"ę" if len(labels)==1 else "e"}: '+', '.join(f'„{label}”' for label in labels)+'.'})
    return result


def _nuclear(previous,current,name):
    before=previous.get('nuclear') or {}
    return [{'kind':'NUCLEAR','countries':[name(country)],'fact':f'Państwo {name(country)} pozyskało broń atomową — pierwsze rakiety z głowicą nuklearną.'}
            for country,count in (current.get('nuclear') or {}).items() if count>0 and int(before.get(country,0) or 0)<=0]


def _permits(session,previous,current,name):
    from models import Region
    old={row[0] for row in previous.get('permits') or []}
    new=[row for row in current.get('permits') or [] if row[0] not in old]
    regions={id:label for id,label in session.execute(select(Region.region_id,Region.region_nazwa).where(Region.region_id.in_([row[3] for row in new])))} if new else {}
    return [{'kind':'BASE_PERMIT','countries':[name(host),name(guest)],
             'fact':f'Państwo {name(host)} zezwoliło państwu {name(guest)} na budowę bazy wojskowej w regionie {regions.get(region,"—")}.'} for _,host,guest,region in new]


def statistics(session,start,end,previous,current,name):
    from game.commerce_models import TradeShipment,Mine
    from game.industry_catalog import MINE_RULES
    from services.natural_resources import RESOURCES
    labels=dict(RESOURCES)
    shipments=list(session.execute(select(TradeShipment.seller_id,TradeShipment.buyer_id).where(TradeShipment.starts_at>=start,TradeShipment.starts_at<end)))
    pairs={}
    for seller,buyer in shipments:
        if seller==buyer:continue
        key=tuple(sorted((seller,buyer)));pairs[key]=pairs.get(key,0)+1
    partners={}
    for (a,b),n in pairs.items():
        for country in (a,b):partners[country]=partners.get(country,0)+n
    trade={'shipments':len(shipments),'pairs':len(pairs),
           'top_pairs':[{'countries':[name(a),name(b)],'shipments':n} for (a,b),n in sorted(pairs.items(),key=lambda item:-item[1])[:3]],
           'most_active':[{'country':name(c),'shipments':n} for c,n in sorted(partners.items(),key=lambda item:-item[1])[:3]]}
    days=max(1,(end-start).days)
    active={}
    for mine in session.scalars(select(Mine).where(Mine.health>0,Mine.removed_at.is_(None),Mine.ready_at<end)):
        item=active.setdefault(mine.resource,{'mines':0,'estimate':0});item['mines']+=1
        item['estimate']+=MINE_RULES.get(mine.resource,(None,None,None,[0,0,0]))[3][max(0,min(2,(mine.level or 1)-1))]*days
    extracted={}
    if previous and previous.get('deposits'):
        for code,amount in (current.get('deposits') or {}).items():
            change=int(previous['deposits'].get(code,amount))-int(amount)
            if change>0:extracted[code]=change
    source='zmiana złóż' if extracted else 'szacunek'
    mining=[{'resource':labels.get(code,code),'amount':extracted.get(code,item['estimate']) if extracted else item['estimate'],'mines':item['mines']}
            for code,item in active.items()]
    for code,amount in extracted.items():
        if code not in active:mining.append({'resource':labels.get(code,code),'amount':amount,'mines':0})
    mining=sorted([m for m in mining if m['amount']>0],key=lambda m:-m['amount'])[:8]
    from game.imf_models import ImfLoan
    loans=list(session.execute(select(ImfLoan.borrower_id,ImfLoan.amount).where(ImfLoan.status!='rejected',ImfLoan.created_game_at>=start,ImfLoan.created_game_at<end)))
    total=sum((Decimal(amount) for _,amount in loans),Decimal(0))
    imf={'loans':len(loans),'total_bln':float(round(total/Decimal(1000000000),1)),'borrowers':sorted({name(b) for b,_ in loans})}
    return {'trade':trade,'mining':{'source':source,'items':mining},'imf':imf}


# ---------------- teksty ----------------

def fallback_content(facts):
    """Tekst przygotowany przez ZEUS (bez modelu AI) — wyłącznie z faktów."""
    lead=facts.get('lead')
    content={'headline':'Entenda News','lead':None,'news':[],'stats':None}
    if lead:
        content['lead']={'id':lead['id'],'title':_title(lead),'body':lead['fact']+' Redakcja „Entenda News” będzie śledzić dalszy rozwój wydarzeń.'}
    for item in facts.get('news',[]):content['news'].append({'id':item['id'],'title':_title(item),'body':item['fact']})
    content['stats']={'title':f'Miesiąc w liczbach — {facts.get("month")}','body':stats_text(facts.get('stats') or {})}
    return content


TITLES={'WAR_STARTED':'Wybuch wojny','WAR_ENDED':'Koniec wojny','CEASEFIRE':'Zawieszenie broni','SATELLITE':'Satelita na orbicie',
        'NUCLEAR':'Nowe mocarstwo atomowe','SOVEREIGNTY_LOST':'Państwo traci niepodległość','TECHNOLOGY':'Postęp technologiczny',
        'RAIL':'Nowa linia kolejowa','AIRPORT':'Nowe lotnisko','BASE_PERMIT':'Obca baza za zgodą gospodarza'}


def _title(item):
    countries=item.get('countries') or []
    return TITLES.get(item['kind'],'Wydarzenie')+(': '+' – '.join(countries) if countries else '')


def _number(value):return f'{value:,}'.replace(',',' ')


def stats_text(stats):
    trade=stats.get('trade') or {};mining=stats.get('mining') or {};imf=stats.get('imf') or {}
    parts=[]
    if trade.get('shipments'):
        text=f'Handel: {_number(trade["shipments"])} dostaw między {_number(trade.get("pairs",0))} parami państw.'
        if trade.get('top_pairs'):text+=' Najaktywniejsze kontakty: '+'; '.join(f'{" – ".join(p["countries"])} ({p["shipments"]})' for p in trade['top_pairs'])+'.'
        parts.append(text)
    else:parts.append('Handel: w minionym miesiącu nie odnotowano dostaw między państwami.')
    if mining.get('items'):
        parts.append(('Wydobycie' if mining.get('source')=='zmiana złóż' else 'Wydobycie (szacunek wg czynnych kopalń)')+': '+', '.join(f'{m["resource"]} {_number(int(m["amount"]))}' for m in mining['items'][:6])+'.')
    else:parts.append('Wydobycie: brak czynnych kopalń.')
    if imf.get('loans'):parts.append(f'MFW udzielił {imf["loans"]} pożyczek na łącznie {str(imf["total_bln"]).replace(".",",")} mld ROI'+(' (' + ', '.join(imf['borrowers'])+')' if imf.get('borrowers') else '')+'.')
    else:parts.append('MFW nie udzielił w minionym miesiącu żadnej pożyczki.')
    return ' '.join(parts)


SYSTEM_PROMPT=('Jesteś redakcją gazety „Entenda News” — jedynego międzynarodowego dziennika fikcyjnego świata Entenda (gra strategiczna). '
               'Piszesz po polsku, rzeczowym, dziennikarskim stylem, w czasie przeszłym. Opierasz się WYŁĄCZNIE na przekazanych faktach: '
               'nie dodajesz państw, liczb, dat, przyczyn ani skutków, których nie ma w faktach; możesz je jedynie opisać i zestawić. '
               'Nie oceniasz politycznie żadnego państwa. Odpowiadasz wyłącznie obiektem JSON zgodnym ze schematem.')

SCHEMA={'type':'object','additionalProperties':False,'required':['lead','news','stats'],'properties':{
    'lead':{'type':['object','null'],'additionalProperties':False,'required':['title','body'],'properties':{'title':{'type':'string'},'body':{'type':'string'}}},
    'news':{'type':'array','items':{'type':'object','additionalProperties':False,'required':['id','title','body'],
            'properties':{'id':{'type':'integer'},'title':{'type':'string'},'body':{'type':'string'}}}},
    'stats':{'type':'object','additionalProperties':False,'required':['title','body'],'properties':{'title':{'type':'string'},'body':{'type':'string'}}}}}


def prompt(facts):
    import json
    brief={'miesiąc':facts.get('month'),
           'najważniejsze_wydarzenie':{'id':facts['lead']['id'],'fakt':facts['lead']['fact']} if facts.get('lead') else None,
           'mniejsze_newsy':[{'id':item['id'],'fakt':item['fact']} for item in facts.get('news',[])],
           'statystyki':facts.get('stats')}
    task=('Przygotuj wydanie gazety za miniony miesiąc. "lead": nagłówek (do 12 słów) i artykuł (3–5 zdań) o najważniejszym wydarzeniu '
          '(null, gdy go brak). "news": dla KAŻDEGO mniejszego newsa — to samo id, krótki tytuł i 1–3 zdania. '
          '"stats": tytuł i 3–5 zdań o statystykach (handel, wydobycie, pożyczki MFW) — tylko liczby z faktów.')
    return [{'role':'system','content':SYSTEM_PROMPT},{'role':'user','content':task+'\n\nFakty:\n'+json.dumps(brief,ensure_ascii=False,default=str)}]


def _clean(text,limit):
    text=' '.join(str(text or '').split())
    return text[:limit].rstrip()


def merge_ai(facts,answer):
    """Łączy odpowiedź modelu z faktami; brakujące lub błędne fragmenty uzupełnia tekst ZEUS."""
    base=fallback_content(facts)
    if not isinstance(answer,dict):raise ValueError('Odpowiedź modelu nie jest obiektem JSON.')
    lead=answer.get('lead')
    if base['lead'] and isinstance(lead,dict) and lead.get('title') and lead.get('body'):
        base['lead'].update(title=_clean(lead['title'],TEXT_LIMITS['title']),body=_clean(lead['body'],TEXT_LIMITS['body']))
    written={item.get('id'):item for item in answer.get('news') or [] if isinstance(item,dict)}
    for item in base['news']:
        text=written.get(item['id'])
        if text and text.get('title') and text.get('body'):item.update(title=_clean(text['title'],TEXT_LIMITS['title']),body=_clean(text['body'],TEXT_LIMITS['body']))
    stats=answer.get('stats')
    if isinstance(stats,dict) and stats.get('title') and stats.get('body'):
        base['stats'].update(title=_clean(stats['title'],TEXT_LIMITS['title']),body=_clean(stats['body'],TEXT_LIMITS['body']))
    return base


def ai_enabled(session):
    from game.paga_ai_models import PagaAiControl
    control=session.get(PagaAiControl,1)
    return control is not None and bool(control.enabled)


def write_with_ai(facts):
    """(treść, dostawca, model) — model forum (Groq, zastępczo Gemini). Wyjątek, gdy żaden model nie może odpowiedzieć."""
    from game.paga_ai_providers import route,generator,model_name
    with Session(db.engine) as session:provider,_,reason=route(session,'forum_reply')
    if provider not in ('groq','gemini'):raise RuntimeError(reason or 'Brak dostępnego modelu AI.')
    stats={}
    answer=generator(provider)(prompt(facts),schema=SCHEMA,stats=stats,max_tokens=1600)
    return merge_ai(facts,answer),provider,stats.get('model') or model_name(provider)


# ---------------- harmonogram ----------------

def ensure_issue(session,now):
    """Tworzy wydanie za miniony miesiąc (raz). Zwraca wydanie albo None (brak tabeli lub już istnieje)."""
    start,end=previous_month(now)
    if session.scalar(select(NewspaperIssue.id).where(NewspaperIssue.game_year==start.year,NewspaperIssue.game_month==start.month)):return None
    previous=session.scalar(select(NewspaperIssue).order_by(NewspaperIssue.period_start.desc()).limit(1))
    if previous is not None and previous.period_start>start:return None   # zegar cofnięty — nie odtwarzamy starszych wydań
    current=snapshot(session,now)
    facts=collect_facts(session,start,end,previous.snapshot if previous is not None else None,current)
    issue=NewspaperIssue(game_year=start.year,game_month=start.month,period_start=start,period_end=end,status='PENDING',facts=facts,snapshot=current,attempts=0,created_at=utc_now())
    session.add(issue);session.flush()
    return issue


def publish(issue,content,*,author,provider=None,model=None):
    issue.content=content;issue.author=author;issue.provider=provider;issue.model=model
    issue.status='PUBLISHED';issue.published_at=utc_now();issue.next_attempt_at=None


def run_tick(app):
    from game.finance_service import game_now
    with app.app_context():
        with Session(db.engine) as session,session.begin():
            if not tables_ready(session):return
            ensure_issue(session,game_now())
        with Session(db.engine) as session:
            pending=list(session.scalars(select(NewspaperIssue.id).where(NewspaperIssue.status=='PENDING').order_by(NewspaperIssue.id)))
        for issue_id in pending:
            try:process(issue_id)
            except Exception as exc:app.logger.warning('Entenda News: wydanie %s pominięte: %s',issue_id,f'{type(exc).__name__}: {exc}'[:300])


def process(issue_id,*,writer=None):
    """Próba napisania wydania przez model AI; po MAX_ATTEMPTS nieudanych próbach albo przy wyłączonych modelach — tekst ZEUS."""
    writer=writer or write_with_ai
    with Session(db.engine) as session:
        issue=session.get(NewspaperIssue,issue_id)
        if issue is None or issue.status!='PENDING' or (issue.next_attempt_at and issue.next_attempt_at>utc_now()):return None
        facts=issue.facts;enabled=ai_enabled(session)
    result=error=None
    if enabled:
        try:result=writer(facts)
        except Exception as exc:
            from game.paga_ai_providers import scrub
            error=scrub(exc)[:500]
    with Session(db.engine) as session,session.begin():
        issue=session.get(NewspaperIssue,issue_id,with_for_update=True)
        if issue.status!='PENDING':return issue.status
        if result is not None:
            content,provider,model=result;publish(issue,content,author='AI',provider=provider,model=model)
        else:
            issue.attempts=(issue.attempts or 0)+(1 if enabled else 0);issue.error=error or ('Modele AI są wyłączone.' if not enabled else None)
            if not enabled or issue.attempts>=MAX_ATTEMPTS:publish(issue,fallback_content(issue.facts),author='ZEUS')
            else:issue.next_attempt_at=utc_now()+timedelta(minutes=RETRY_MINUTES)
        return issue.status


# ---------------- ekran ----------------

newspaper_bp=Blueprint('game_newspaper',__name__,url_prefix='/game')


@newspaper_bp.get('/wydarzenia')
def page():
    from game.forum import player
    from game.country_summary import country_summary
    user,country=player()
    if user is None:return redirect(url_for('wejscie'))
    issues=[];issue=None
    if tables_ready(db.session):
        issues=list(db.session.execute(select(NewspaperIssue.id,NewspaperIssue.game_year,NewspaperIssue.game_month).where(NewspaperIssue.status=='PUBLISHED').order_by(NewspaperIssue.period_start.desc()).limit(24)))
        wanted=request.args.get('wydanie',type=int)
        if wanted:
            issue=db.session.scalar(select(NewspaperIssue).where(NewspaperIssue.id==wanted,NewspaperIssue.status=='PUBLISHED'))
            if issue is None:abort(404)
        elif issues:issue=db.session.get(NewspaperIssue,issues[0].id)
    from game.finance_service import game_now
    now=game_now()
    return render_template('game/newspaper.html',issue=issue,issues=[{'id':row.id,'label':month_label(row.game_year,row.game_month)} for row in issues],
                           label=month_label(issue.game_year,issue.game_month) if issue else None,
                           edition_date=f'1 {MONTHS_GEN[issue.period_end.month-1]} {issue.period_end.year}' if issue else None,
                           next_label=f'1 {MONTHS_GEN[(now.month)%12]} {now.year+(1 if now.month==12 else 0)}',
                           game_user=user,game_country=country_summary(country),game_home_url=url_for('game_main_page'),game_logout_url=url_for('game_logout'),game_active_page='events')
