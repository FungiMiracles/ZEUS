"""PAGA2 — handel międzynarodowy: opłaty portowe, dostęp do portów, sprzedaż nadwyżek (z ukrywaniem ofert przed
państwami wrogimi) i zakup brakujących surowców zgodnie z budżetem, interesem narodowym, stosunkami i charakterem.
Dane: ekran handlu gracza (/game/handel/stan) — wyłącznie oferty i porty widoczne dla tego państwa.
"""
from decimal import Decimal,ROUND_HALF_UP
from sqlalchemy import select
from sqlalchemy.orm import Session
from extensions import db
from game.paga2.engine import Adapter,register
from game.paga2.scoring import Option,clip
from game.paga2.finance import request_id,result
from game.paga2 import pricing

PATH='/game/handel/zmien'
MIN_OFFER_VALUE=2e8
LABELS={'wegiel_kamienny':'węgiel','ropa_naftowa':'ropa','zloto':'złoto','srebro':'srebro','kamien':'kamień','natsyt':'natsyt','kerbit':'kerbit','cemium':'cemium','zelazo':'żelazo','uran':'uran'}


def trade_screen(ctx):return (ctx.screen('trade') or {}).get('data') or {}


def unfriendly(ctx):
    """Państwa, przed którymi ukrywamy oferty i którym blokujemy porty (wojna, wrogie relacje, historyczna wrogość przy rewanżyzmie)."""
    s=ctx.situation;t=ctx.traits
    result=set(s.get('at_war',[]))
    if t.get('isolationism',50)>=40 or t.get('provocation',50)>=60 or t.get('revenge',50)>=60:result|=set(s.get('hostile',[]))
    if t.get('revenge',50)>=50:result|={other for other,link in ctx.relationships.items() if link.get('status')=='historical_hostile'}
    return result-set(s.get('allies',[]))


def own_port(screen,country_id):
    ports=screen.get('ports') or {}
    own=[int(id) for id,p in ports.items() if p.get('countryId')==country_id]
    return own[0] if own else None


def arrival_port(screen,country_id):
    """Port odbioru: własny (gra wymaga go, gdy państwo ma port) albo najtańszy dozwolony obcy."""
    ports=screen.get('ports') or {}
    own=own_port(screen,country_id)
    if own:return own,ports[str(own)].get('rate','0')
    allowed=[(float(p.get('rate') or 0),int(id)) for id,p in ports.items() if p.get('allowed') and not p.get('blocked')]
    if not allowed:return None,None
    rate,port=min(allowed);return port,ports[str(port)].get('rate','0')


def port_limit(port_id):
    """Limit wielkości oferty z infrastruktury portowej regionu portu (jak w grze)."""
    from models import Miasto,Region
    from game.infrastructure_effects import port_export_limit
    with Session(db.engine) as session:
        region=session.scalar(select(Miasto.region_id).where(Miasto.miasto_id==port_id))
        level=session.scalar(select(Region.region_stan_infra_portowej).where(Region.region_id==region)) if region else 0
    return port_export_limit(level or 0)


POLICY_COOLDOWN_DAYS=180   # 12 Nov 2026: ustawienia portów zmieniane najwyżej raz na pół roku gry


def recent_policy(ctx,action,days=POLICY_COOLDOWN_DAYS):
    """Czy państwo wykonało to ustawienie w ostatnich `days` dniach gry (także w przebiegu z kilkoma działaniami)."""
    if getattr(ctx,'_policy_history',None) is None:
        from datetime import timedelta
        from game.paga2.memory import executed_actions
        with Session(db.engine) as session:
            ctx._policy_history=executed_actions(session,ctx.country_id,since=ctx.now-timedelta(days=days) if ctx.now else None)
    return any(a==action for a,_,_ in ctx._policy_history)


def policy_options(ctx,screen):
    """Opłata portowa i dostęp do portów to decyzje administracyjne: wykonywane poza limitem działań (payload.required),
    gdy obecne ustawienie odbiega od docelowego — wcześniej zawsze przegrywały z działaniami strategicznymi (12 Nov 2026)."""
    options=[];t=ctx.traits
    if not screen.get('ownPorts'):return options
    current=float(screen.get('ownTariff') or 0)
    target=round(clip(3+15*t.get('isolationism',50)/100+10*(100-t.get('trade_propensity',50))/100-5*t.get('solidarity',50)/100+(5 if ctx.situation.get('level')=='war' else 0),0,30))
    if abs(current-target)>=2 and not recent_policy(ctx,'PORT_TARIFF'):
        options.append(Option(key='trade:tariff',domain='trade',action='PORT_TARIFF',label=f'Opłata portowa {current:g}% → {target}%',
                              effects={'trade':.4 if target<current else -.2,'financial_stability':.3 if target>current else 0},
                              traits={'isolationism':.6 if target>current else -.6,'trade_propensity':-.5 if target>current else .5},base=3.0,
                              notes=['Docelowa opłata wynika z izolacjonizmu, skłonności do handlu, solidarności i sytuacji bezpieczeństwa.'],payload={'action':'tariff','rate':str(target),'group':'trade:tariff','required':True}))
    access=screen.get('portAccess') or {};countries={int(k) for k in (screen.get('countries') or {})}
    desired=sorted((unfriendly(ctx)&countries)-{ctx.country_id})
    block_foreign='isolationist' in ctx.categories and t.get('isolationism',50)>=85
    changed=set(desired)!=set(access.get('blocked_countries') or []) or block_foreign!=bool(access.get('block_foreign'))
    # Blokada państw w stanie wojny działa od razu; pozostałe zmiany dostępu — najwyżej raz na pół roku.
    urgent=bool(set(ctx.situation.get('at_war',[]))&(set(desired)-set(access.get('blocked_countries') or [])))
    if changed and (urgent or not recent_policy(ctx,'PORT_ACCESS')):
        options.append(Option(key='trade:port_access',domain='trade',action='PORT_ACCESS',label=f'Dostęp do portów: blokada {len(desired)} państw'+(' i wszystkich obcych' if block_foreign else ''),
                              effects={'defensive_army':.3,'trade':-.2*len(desired)/max(1,len(countries))},traits={'isolationism':.5,'revenge':.3},base=4.0,
                              notes=['Blokowane: państwa w stanie wojny, wrogie (przy izolacjonizmie/prowokacyjności/rewanżyzmie) i historycznie nieprzyjazne (przy rewanżyzmie).'],
                              payload={'action':'port_access','block_foreign':block_foreign,'blocked_countries':desired,'group':'trade:port_access','required':True}))
    return options


def sell_options(ctx,screen,factors):
    from game.paga2.planner import _holdings
    warehouse=screen.get('warehouse') or {};t=ctx.traits
    port=own_port(screen,ctx.country_id) or arrival_port(screen,ctx.country_id)[0]
    if port is None:return []
    reserve=pricing.consumption(_holdings(ctx),days=60+int(60*t.get('isolationism',50)/100))
    share=.3+.5*t.get('trade_propensity',50)/100
    cargo={}
    peaceful=ctx.situation.get('level')=='peace' and t.get('militarism',50)<20 and 'defensive_army' not in ctx.priorities[:3]
    for code,row in warehouse.items():
        surplus=int(row.get('available') or 0)-reserve.get(code,0)
        military=code.endswith('_missiles') or code in ('tanks','fighters','armored','drones','warships','submarines','carriers',pricing.AMMUNITION)
        if military:
            # Uzbrojenie to siły zbrojne państwa, nie nadwyżka: najwyżej 5% i tylko państwo bardzo mało zmilitaryzowane w czasie pokoju.
            if not peaceful:continue
            quantity=int(int(row.get('available') or 0)*.05)
        else:quantity=int(surplus*share)
        if quantity>0:cargo[code]=quantity
    if not cargo:return []
    limit,only=port_limit(port)
    if only is not None:cargo={k:v for k,v in cargo.items() if k==only}
    if limit is not None:
        total=sum(cargo.values())
        if total>limit:cargo={k:max(1,v*limit//total) for k,v in cargo.items()}
        while sum(cargo.values())>limit:largest=max(cargo,key=cargo.get);cargo[largest]-=1
        cargo={k:v for k,v in cargo.items() if v>0}
    if not cargo:return []
    # 12 Nov 2026: jedna oferta = jeden rodzaj towaru (najcenniejszy pakiet); cena w granicach gry (game/trade_prices).
    best=max(cargo,key=lambda code:pricing.cargo_value({code:cargo[code]},factors))
    cargo={best:cargo[best]}
    value=pricing.cargo_value(cargo,factors)
    if value<MIN_OFFER_VALUE:return []
    markup=1.05+.35*(100-t.get('trade_propensity',50))/100+.2*t.get('ambition',50)/100
    from game.trade_prices import clamp
    price=clamp(best,cargo[best],Decimal(str(value*markup))).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP)
    excluded=sorted(unfriendly(ctx)-{ctx.country_id})
    rate=(screen.get('ports') or {}).get(str(port),{}).get('rate','0')
    return [Option(key='trade:offer',domain='trade',action='TRADE_OFFER',label='Oferta sprzedaży: '+', '.join(f'{q} {LABELS.get(c,c)}' for c,q in cargo.items()),
                   effects={'trade':1.0,'financial_stability':.4},traits={'trade_propensity':1.0,'isolationism':-.6},base=2.0,
                   notes=[f'Nadwyżka ponad rezerwę operacyjną; cena {float(price)/1e9:.2f} MLD (wartość {value/1e9:.2f} MLD × {markup:.2f}, w granicach cen gry).',
                          f'Oferta ukryta przed {len(excluded)} państwami (wojna / wrogość).'],
                   payload={'action':'offer','cargo':cargo,'price':str(price),'port_id':port,'departure_rate':str(rate),'excluded':excluded,'group':'trade:offer'})]


def planned_acquisitions(ctx):
    """Surowce, które aktywne plany wieloetapowe muszą kupić w handlu (brak własnych złóż)."""
    from game.paga2.models import Paga2Plan,table_ready
    result=set()
    with Session(db.engine) as session:
        if table_ready(session,Paga2Plan):
            for row in session.scalars(select(Paga2Plan).where(Paga2Plan.country_id==ctx.country_id,Paga2Plan.status=='ACTIVE')):
                result|={s['params']['resource'] for s in row.steps or [] if s.get('kind')=='acquire'}
    return result


def buy_options(ctx,screen,factors):
    from game.paga2.planner import _holdings
    h=_holdings(ctx);t=ctx.traits
    need={code:max(0,amount-h.stock.get(code,0)) for code,amount in pricing.consumption(h).items()}
    for resource in planned_acquisitions(ctx):need[resource]=max(need.get(resource,0),10)
    need={k:v for k,v in need.items() if v>0}
    if not need:return []
    port,rate=arrival_port(screen,ctx.country_id)
    if port is None:return []
    reserve=float(screen.get('reserve') or 0);ctx._sectors['reserve']=reserve
    avoid=unfriendly(ctx)
    tolerance=1.0+.5*t.get('trade_propensity',50)/100+(.3 if ctx.situation.get('level')=='war' else 0)
    options=[]
    for offer in screen.get('offers') or []:
        if offer.get('own') or not offer.get('usable',True) or offer.get('sellerId') in avoid:continue
        cargo=offer.get('cargo') or {}
        useful=set(cargo)&set(need)
        if not useful:continue
        weights={code:(1.0 if code in need else .5) for code in cargo}
        value=pricing.cargo_value(cargo,factors,weights)
        price=float(offer.get('price') or 0);total=price*(1+float(rate or 0)/100)
        if total>value*tolerance:continue
        options.append(Option(key=f'trade:buy:{offer["id"]}',domain='trade',action='TRADE_BUY',label=f'Zakup oferty #{offer["id"]} od {offer.get("seller")}: '+', '.join(f'{q} {LABELS.get(c,c)}' for c,q in cargo.items()),
                              target=offer.get('sellerId'),stance='friendly',cost=total,sector='reserve',
                              effects={'production':1.0,'trade':.5},traits={'trade_propensity':.8,'isolationism':-.5},base=4.0+min(6.0,10*(value*tolerance-total)/max(1,total)),
                              notes=[f'Potrzebne: {", ".join(LABELS.get(c,c) for c in sorted(useful))}; cena z opłatą {total/1e9:.2f} MLD, wartość {value/1e9:.2f} MLD.'],
                              payload={'action':'buy','offer_id':offer['id'],'port_id':port,'arrival_rate':str(rate),'group':'trade:buy'}))
    return sorted(options,key=lambda o:-o.base)[:5]


def propose(ctx):
    screen=trade_screen(ctx)
    if not screen:return []
    factors=pricing.market_factors(screen.get('offers'))
    return policy_options(ctx,screen)+sell_options(ctx,screen,factors)+buy_options(ctx,screen,factors)


def execute(ctx,option):
    body={k:v for k,v in option.payload.items() if k not in ('group','required')}
    status,data=ctx.call(PATH,json={**body,'request_id':request_id(ctx,option)})
    if status<400:ctx._holdings=None
    return result(status,data)


ADAPTER=register(Adapter(name='trade',modes=('CYCLIC',),propose=propose,execute=execute))
