"""PAGA2 — reakcja na wykryte próby sabotażu (28 Nov 2026).

Państwo PAGA2 zna sprawcę sabotażu tylko wtedy, gdy jego kontrwywiad go ustalił (poziom ochrony 6–7) albo schwytano
obcego agenta — zdarzenie HYBRID_DETECTED w dzienniku autonomii (game.autonomy_memory). Na tej podstawie:

- odnotowuje próby wg sprawcy (liczba, udane / nieudane, rodzaj, ostatnia data) — record(),
- koryguje stosunki: presja na pogorszenie rośnie z liczbą prób i rewanżyzmem; dobre dotychczasowe stosunki, zaufanie
  i historyczny sojusz łagodzą reakcję na pojedynczą próbę, historyczna wrogość i niskie zaufanie ją wzmacniają —
  relation_pressure(), relation_steps(),
- przy wysokim rewanżyzmie odpowiada podobnym aktem sabotażu, biorąc pod uwagę budżet służb, dostępnych agentów
  i siłę zbrojną sprawcy — retaliation_terms(),
- może opublikować wpis na forum o próbie sabotażu (game.paga2.communication).
"""
from datetime import timedelta,datetime

WINDOW_DAYS=365
REVENGE_LEVEL=60          # od tej wartości cechy „rewanżyzm” państwo odpowiada sabotażem
FEARLESS_REVENGE=85       # przy takim rewanżyzmie nie odstrasza nawet znacznie silniejszy sprawca
MAX_STRENGTH_RATIO=3.0    # sprawca ponad 3× silniejszy militarnie odstrasza od odwetu
FRIENDLY=('dobre','przyjazne','partnerskie','partnerskiestrategiczne','sojusznicze')
HOSTILE=('zle','napiete','wrogie','egzystencjalniewrogie')


def _parse(value):
    try:return datetime.fromisoformat(value) if value else None
    except (TypeError,ValueError):return None


def record(ctx):
    """{sprawca: {'count','successful','failed','kinds','last_kind','last_at','first_at','event_ids'}} — próby z ostatniego roku."""
    if getattr(ctx,'_sabotage',None) is not None:return ctx._sabotage
    limit=(ctx.now-timedelta(days=WINDOW_DAYS)).isoformat() if ctx.now else ''
    result={}
    for event in sorted(ctx.memory.get('actions_against_us',[]),key=lambda e:(e.get('at') or '',e.get('id') or 0)):
        if event.get('kind')!='HYBRID_DETECTED' or not event.get('actor') or (event.get('at') or '')<limit:continue
        item=result.setdefault(event['actor'],{'count':0,'successful':0,'failed':0,'kinds':[],'last_kind':None,'last_at':None,'first_at':event.get('at'),'event_ids':[]})
        item['count']+=1
        if event.get('success'):item['successful']+=1
        else:item['failed']+=1
        if event.get('operation'):item['kinds'].append(event['operation']);item['last_kind']=event['operation']
        item['last_at']=event.get('at');item['event_ids'].append(event.get('id'))
    ctx._sabotage=result
    return result


def summary(ctx):
    """Zwięzły zapis dla kontekstu decyzji i modeli AI (bez danych niejawnych innych państw)."""
    return [{'państwo':other,'próby':item['count'],'udane':item['successful'],'nieudane':item['failed'],'ostatnia':item['last_at'],'rodzaj':item['last_kind']}
            for other,item in record(ctx).items()]


def relation_pressure(ctx,other):
    """Premia (pkt) do pogorszenia stosunków z państwem, które próbowało sabotażu; 0, gdy brak prób."""
    item=record(ctx).get(other)
    if not item:return 0.0
    t=ctx.traits;n=item['count']
    value=3.0+2.5*min(4,n-1)+min(3,item['successful'])
    relation=((ctx.situation.get('relations') or {}).get(other) or {}).get('relation','neutralne')
    link=(ctx.relationships.get(other) or {}).get('status')
    trust=ctx.perception(other).get('trust',50)
    friendly_past=relation in FRIENDLY or link=='historical_ally' or trust>=65 or ctx.history(other).get('friendly',0)>0
    if friendly_past and n==1:value*=.6          # pojedynczy incydent z państwem dotąd przyjaznym — wyważona reakcja
    if link=='historical_hostile' or trust<35:value*=1.3
    if relation in HOSTILE:value*=.8               # stosunki już złe — mniejsza potrzeba dalszego pogarszania
    return round(value*(.6+t.get('revenge',50)/100),3)


def relation_steps(ctx,other):
    """O ile stopni pogorszyć stosunki: 2 przy powtarzających się próbach (≥ 3) i braku przyjaznej przeszłości."""
    item=record(ctx).get(other)
    if not item or item['count']<3:return 1
    relation=((ctx.situation.get('relations') or {}).get(other) or {}).get('relation','neutralne')
    return 1 if relation in FRIENDLY and ctx.perception(other).get('trust',50)>=65 else 2


def retaliations_since(ctx,other,since):
    """Liczba własnych misji hybrydowych przeciw `other` rozpoczętych od `since` (czas gry)."""
    from sqlalchemy import select,func
    from sqlalchemy.orm import Session
    from extensions import db
    from game.intelligence_models import IntelligenceMission
    from game.intelligence_service import HYBRID
    query=select(func.count(IntelligenceMission.id)).where(IntelligenceMission.panstwo_id==ctx.country_id,IntelligenceMission.target_country_id==other,IntelligenceMission.kind.in_(HYBRID))
    if since is not None:query=query.where(IntelligenceMission.starts_at>=since)
    with Session(db.engine) as session:return session.scalar(query) or 0


def retaliation_targets(ctx):
    """[(sprawca, wpis rejestru)] — sprawcy, na których próby nie odpowiedziano jeszcze odwetem (wysoki rewanżyzm)."""
    if ctx.traits.get('revenge',50)<REVENGE_LEVEL:return []
    return [(other,item) for other,item in record(ctx).items() if retaliations_since(ctx,other,_parse(item['first_at']))<item['count']]


def retaliation_terms(ctx,other,agent_level):
    """(ocena sytuacyjna, uwagi) albo None, gdy odwet jest nierozsądny (zbyt silny sprawca)."""
    from game.intelligence_service import AGENT_CHANCES
    from game.paga2.diplomacy import powers
    t=ctx.traits;item=record(ctx)[other];notes=[]
    try:own,_,foe=powers(ctx,other)
    except Exception:own,foe=1.0,1.0
    ratio=foe/max(1.0,own)
    if ratio>MAX_STRENGTH_RATIO and t.get('revenge',50)<FEARLESS_REVENGE:return None
    base=6.0+2.0*min(3,item['count'])+(t.get('revenge',50)-REVENGE_LEVEL)/8
    if ratio>1:base-=2.0*min(3.0,ratio-1);notes.append(f'Sprawca silniejszy militarnie (×{ratio:.2f}) — ostrożniejszy odwet.')
    chance=AGENT_CHANCES[agent_level-1]
    base+=(chance-35)/10
    if (ctx.relationships.get(other) or {}).get('status')=='historical_ally':base-=4.0
    notes.insert(0,f'Odwet za {item["count"]} wykrytą(e) próbę(y) sabotażu ze strony państwa {other} (ostatnia: {item["last_kind"] or "nieznany rodzaj"}); szansa agenta {chance}%.')
    return base,notes
