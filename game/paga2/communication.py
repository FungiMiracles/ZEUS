"""PAGA2 — inicjowanie wpisów na forum międzynarodowym i wiadomości prywatnych.

Algorytm decyduje, CZY i KIEDY państwo zabiera głos oraz do kogo (okazje: atak na nasze państwo, atak na sojusznika,
wojna w innym regionie, nasza oferta handlowa, zmiana stosunków, wydarzenie z generatora zdarzeń). Treść pisze model AI
(zadanie forum_announcement / private_initiative) zgodnie z polityką PAGA2. Bez włączonych modeli AI okazje są pomijane.
"""
from datetime import timedelta
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from extensions import db
from game.paga2.engine import Adapter,register
from game.paga2.scoring import Option

DAILY_LIMIT=3
RECENT_DAYS=7


def llm_control(session):
    from game.paga_ai_models import PagaAiControl
    control=session.get(PagaAiControl,1)
    return control if control is not None and control.enabled else None


def already(session,country_id,key):
    from game.paga_ai_models import PagaAiJob
    return session.scalar(select(PagaAiJob.id).where(PagaAiJob.country_id==country_id,PagaAiJob.trigger==key[:100])) is not None


def used_today(session,country_id):
    from game.paga_ai_models import PagaAiJob
    from game.paga2.models import utc_now
    return session.scalar(select(func.count(PagaAiJob.id)).where(PagaAiJob.country_id==country_id,PagaAiJob.source=='paga2',PagaAiJob.created_at>=utc_now()-timedelta(days=1))) or 0


def recent_actions(ctx):
    from game.paga2.memory import executed_actions
    with Session(db.engine) as session:return executed_actions(session,ctx.country_id,since=ctx.now-timedelta(days=RECENT_DAYS) if ctx.now else None,limit=50)


def occasions(ctx,names):
    """(klucz, rodzaj zadania, adresat, opis, efekty, cechy, bazowa ocena)."""
    s=ctx.situation;allies=set(s.get('allies',[]));result=[]
    limit=(ctx.now-timedelta(days=RECENT_DAYS)).isoformat() if ctx.now else ''
    label=lambda id:names.get(id,f'państwo {id}')
    for item in ctx.triggers:
        kind=item.get('kind')
        if kind in ('war_declared','land_invasion','under_attack','occupation','annexation','hybrid_detected'):
            result.append((f'paga2:attack:{item.get("source")}:{item.get("id")}','forum_announcement',None,
                           f'Nasze państwo padło ofiarą: {item.get("label")}. Szczegóły: {item.get("text","")[:200]}',
                           {'defensive_army':.6,'alliances':.5},{'provocation':.4,'secrecy':-.6,'agreeableness':-.2},6.0))
        elif kind=='generated_event':
            result.append((f'paga2:event:{item.get("id")}','forum_announcement',None,f'Wydarzenie w świecie: {item.get("text","")[:220]}',
                           {'alliances':.2},{'ambition':.4,'secrecy':-.6,'solidarity':.3},-4.0))
    t=ctx.traits
    # Próba odbicia terytorium z rąk naszego państwa (jesteśmy okupantem).
    for event in ctx.memory.get('actions_against_us',[]):
        if event.get('kind')!='RECAPTURE_ATTACK' or (event.get('at') or '')<limit:continue
        owner=event.get('actor');outcome='odbiło' if event.get('won') else 'nie zdołało odbić'
        tone='wezwij do rozmów i zaproponuj rozwiązanie dyplomatyczne' if t.get('agreeableness',50)>=60 else 'podkreśl, że utrzymamy kontrolę nad zajętym terytorium' if t.get('provocation',50)>=60 or t.get('expansionism',50)>=60 else 'zajmij wyważone stanowisko'
        result.append((f'paga2:recapture-us:{event["id"]}','forum_announcement',None,f'Państwo {label(owner)} próbowało odzyskać zajęty przez nas obiekt ({event.get("object")}) i {outcome} go. Stanowisko PAGA2: {tone}.',
                       {'defensive_army':.5,'conquest':.3},{'provocation':.4,'secrecy':-.5},3.0))
        if t.get('agreeableness',50)>=60 and owner:
            result.append((f'paga2:recapture-talks:{event["id"]}','private_initiative',owner,f'Po próbie odbicia {event.get("object")} zaproponuj państwu {label(owner)} rozmowy o zakończeniu sporu terytorialnego.',
                           {'welfare':.4,'alliances':.4},{'agreeableness':.8,'strategic_flexibility':.4},1.0))
    for event in ctx.memory.get('world_conflicts',[]):
        if (event.get('at') or '')<limit:continue
        target=event.get('target');actor=event.get('actor')
        if event['kind']=='RECAPTURE_ATTACK':
            # Okupowane państwo (actor) odbija swoje terytorium z rąk okupanta (target): stanowisko zależy od relacji z obiema stronami.
            side=recapture_side(ctx,actor,target)
            if side is None:continue
            supported,opposed,why=side
            outcome='z powodzeniem' if event.get('won') else 'bez powodzenia'
            text=f'Państwo {label(actor)} próbowało ({outcome}) odbić swoje terytorium ({event.get("object")}) okupowane przez {label(target)}. Stanowisko PAGA2: {why}.'
            result.append((f'paga2:recapture:{event["id"]}','forum_announcement',None,text,{'alliances':.8},{'solidarity':.6,'interventionism':.5,'alliance_loyalty':.5,'secrecy':-.5},1.0))
            if supported in allies:
                result.append((f'paga2:recapture-pm:{event["id"]}','private_initiative',supported,text+' Wyraź poparcie dla sojusznika.',{'alliances':1.0},{'alliance_loyalty':.9,'solidarity':.5},2.0))
            continue
        if target in allies:
            result.append((f'paga2:ally:{event["id"]}','forum_announcement',None,f'Atak ({event["kind"]}) państwa {label(actor)} na naszego sojusznika {label(target)}.',
                           {'alliances':1.0,'defensive_army':.3},{'alliance_loyalty':.9,'solidarity':.6,'secrecy':-.5,'interventionism':.4},2.0))
            result.append((f'paga2:ally-pm:{event["id"]}','private_initiative',target,f'Wsparcie dla sojusznika {label(target)} po ataku ({event["kind"]}) ze strony {label(actor)}.',
                           {'alliances':1.0},{'alliance_loyalty':.9,'solidarity':.7},2.0))
        elif event['kind']=='WAR':
            result.append((f'paga2:war:{event["id"]}','forum_announcement',None,f'Wojna między {label(actor)} a {label(target)}.',
                           {'alliances':.3},{'interventionism':.8,'solidarity':.4,'isolationism':-.7,'secrecy':-.4},-3.0))
    for index,(action,target,at) in enumerate(recent_actions(ctx)):
        stamp=at.isoformat() if at else str(index)
        if action=='TRADE_OFFER':
            result.append((f'paga2:offer:{stamp}','forum_announcement',None,'Nasze państwo wystawiło ofertę sprzedaży towarów na rynku międzynarodowym — zachęć do zakupu.',
                           {'trade':1.0},{'trade_propensity':.8,'secrecy':-.3},0.0))
        elif action in ('RELATION_IMPROVE','ALLIANCE') and target:
            result.append((f'paga2:relation:{action}:{target}:{stamp}','private_initiative',target,f'Nasze państwo zaproponowało państwu {label(target)} lepsze stosunki ({action}). Wyjaśnij intencje.',
                           {'alliances':.8},{'agreeableness':.5,'solidarity':.3},1.0))
        elif action in ('RELATION_WORSEN','WAR') and target:
            result.append((f'paga2:hostile:{action}:{target}:{stamp}','forum_announcement',None,f'Nasze państwo {"wypowiedziało wojnę" if action=="WAR" else "pogorszyło stosunki z"} {label(target)}. Uzasadnij decyzję.',
                           {'conquest':.4,'alliances':.2},{'provocation':.6,'secrecy':-.5},2.0 if action=='WAR' else -1.0))
    return result


def recapture_side(ctx,owner,occupier):
    """(popierane, przeciwne, uzasadnienie) albo None, gdy państwo nie ma powodu zabierać głosu."""
    s=ctx.situation;t=ctx.traits;allies=set(s.get('allies',[]));hostile=set(s.get('hostile',[]))|set(s.get('at_war',[]))
    if owner in allies and occupier not in allies:return owner,occupier,'popieramy sojusznika w odzyskaniu jego ziem'
    if occupier in allies and owner not in allies:return occupier,owner,'stoimy po stronie sojusznika; wzywamy do zaprzestania ataków'
    if occupier in hostile and owner not in hostile:return owner,occupier,'okupacja przez państwo nam wrogie jest nieuprawniona — popieramy odzyskanie ziem'
    if owner in hostile and occupier not in hostile:return occupier,owner,'atak państwa nam wrogiego destabilizuje region'
    engaged=t.get('solidarity',50)>=60 or t.get('interventionism',50)>=60
    if not engaged:return None
    trust_owner=ctx.perception(owner).get('trust',50);trust_occupier=ctx.perception(occupier).get('trust',50)
    if trust_owner>=trust_occupier+15:return owner,occupier,'zajęte ziemie powinny wrócić do prawowitego właściciela'
    return None,None,'wzywamy obie strony do rozmów pokojowych'


def propose(ctx):
    from models import Panstwo
    with Session(db.engine) as session:
        if llm_control(session) is None or used_today(session,ctx.country_id)>=DAILY_LIMIT:return []
        names=dict(session.execute(select(Panstwo.PANSTWO_ID,Panstwo.panstwo_nazwa)).all())
        items=[item for item in occasions(ctx,names) if not already(session,ctx.country_id,item[0])]
    options=[]
    for key,kind,target,text,effects,traits,base in items[:12]:
        options.append(Option(key=f'comm:{key}',domain='communication',action='FORUM_POST' if kind=='forum_announcement' else 'PM_INITIATE',
                              label=('Wpis na forum: ' if kind=='forum_announcement' else f'Wiadomość do {names.get(target,target)}: ')+text[:120],
                              target=target,stance='friendly' if kind=='private_initiative' else 'neutral',effects=effects,traits=traits,base=base,
                              payload={'kind':kind,'key':key,'text':text,'target':target,'group':'communication'}))
    return options


def execute(ctx,option):
    """Zlecenie napisania treści modelowi AI (zadanie w kolejce PAGA AI); samo PAGA2 nie publikuje tekstu."""
    from game.paga_ai_tasks import enqueue
    from game.paga_ai_actor import country_user_id
    from models import Panstwo
    p=option.payload
    with Session(db.engine) as session,session.begin():
        control=llm_control(session)
        if control is None:return {'status':409,'error':'Modele AI są wyłączone.'}
        context={'cel':('Opublikuj na forum międzynarodowym wpis' if p['kind']=='forum_announcement' else 'Napisz wiadomość prywatną')+
                       ' w imieniu państwa. Okazja wskazana przez PAGA2: '+p['text'],'źródło':'PAGA2','okazja':p['text']}
        if p['kind']=='private_initiative':
            user=country_user_id(session,p['target'])
            if user is None:return {'status':409,'error':'Adresat nie ma aktywnego gracza ani tożsamości PAGA.'}
            context.update(target_country_id=p['target'],recipient_user_id=user,target_country_name=session.scalar(select(Panstwo.panstwo_nazwa).where(Panstwo.PANSTWO_ID==p['target'])))
        task=enqueue(session,ctx.country_id,p['kind'],p['key'],control.revision,source='paga2',context=context)
        if task is None:return {'status':409,'error':'To zadanie już istnieje.'}
        return {'status':200,'task_id':task.id}


ADAPTER=register(Adapter(name='communication',modes=('CYCLIC','IMMEDIATE'),propose=propose,execute=execute))
