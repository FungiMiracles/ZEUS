"""PAGA2 — ustalanie budżetu półrocza (tryb BUDGET): podatek, podział na sektory, świadczenia dla dzieci i seniorów.

Algorytm:
1. podgląd bazowy gry (ten sam co gracza) — stawka poprzednia, dochody, oczekiwane świadczenia, wskaźniki społeczne,
2. podział sektorów z profilu (priorytety, cechy, charakter) i sytuacji (wojna/zagrożenie), wygładzony poprzednim planem,
3. kilka wariantów stawki podatku (poprzednia, najwyższa bez kary społecznej, niższe i wyższe) — każdy przeliczony podglądem gry,
4. ocena wariantów: dochody vs kara społeczna, pokrycie świadczeń, zmiana względem poprzedniej stawki,
5. zatwierdzenie najlepszego wariantu tą samą operacją co gracz (/game/finanse/zatwierdz).
"""
import math
from decimal import Decimal,ROUND_DOWN,ROUND_HALF_UP,InvalidOperation
from game.paga2.engine import Adapter,register
from game.paga2.scoring import Option,clip
from game.paga2.catalog import priority_weights

PREVIEW='/game/finanse/podglad'
APPROVE='/game/finanse/zatwierdz'
SECTORS=('administration','infrastructure','armed_forces','social_policy','environment','healthcare','education','research','security_services','propaganda')
BASE={'administration':8,'infrastructure':12,'armed_forces':12,'social_policy':14,'environment':4,'healthcare':12,'education':10,'research':6,'security_services':5,'propaganda':2,'reserve':5}
PRIORITY_SECTORS={'infrastructure':{'infrastructure':1},'research':{'research':1,'education':.5},'offensive_army':{'armed_forces':1},
                  'defensive_army':{'armed_forces':1,'security_services':.3},'welfare':{'social_policy':1,'healthcare':.6,'education':.4},
                  'trade':{'infrastructure':.6},'production':{'infrastructure':.6,'research':.6},'environment':{'environment':1.2},
                  'conquest':{'armed_forces':1.2},'intelligence':{'security_services':1.2},'financial_stability':{'reserve':1.2},
                  'alliances':{'propaganda':.5,'administration':.3}}
TRAIT_SECTORS={'prosociality':{'social_policy':1},'health':{'healthcare':1},'ecology':{'environment':1},'militarism':{'armed_forces':1},
               'espionage':{'security_services':.8},'subversion':{'security_services':.6,'propaganda':.4},'industrialism':{'infrastructure':.8},
               'secrecy':{'security_services':.4},'provocation':{'propaganda':.6},'fiscal_conservatism':{'reserve':1}}
CATEGORY_SECTORS={'imperialist':{'armed_forces':.6},'economic':{'infrastructure':.4,'research':.3},'welfare':{'social_policy':.5,'healthcare':.4,'education':.3},
                  'isolationist':{'armed_forces':.3,'reserve':.3},'terrorist':{'security_services':.6,'propaganda':.4},'hegemonic':{'armed_forces':.4,'propaganda':.3,'administration':.2}}
SITUATION_SECTORS={'war':{'armed_forces':2.0,'security_services':1.4,'environment':.4,'research':.8,'social_policy':.85,'reserve':.6},
                   'threat':{'armed_forces':1.4,'security_services':1.2}}
CENT=Decimal('0.01')


def dec(value,default='0'):
    try:return Decimal(str(value if value is not None else default))
    except (InvalidOperation,ValueError):return Decimal(default)


def sector_weights(ctx):
    """Względne wagi sektorów (łącznie z rezerwą) wynikające z profilu i sytuacji państwa."""
    weights=priority_weights(ctx.priorities);t=ctx.traits;level=ctx.situation.get('level','peace')
    result={}
    for sector,base in BASE.items():
        value=base*(1+2.5*sum(w*PRIORITY_SECTORS.get(p,{}).get(sector,0) for p,w in weights.items()))
        for trait,mapping in TRAIT_SECTORS.items():
            if sector in mapping:value*=1+mapping[sector]*(t.get(trait,50)-50)/100
        value*=1+sum(CATEGORY_SECTORS.get(c,{}).get(sector,0) for c in ctx.categories)
        value*=SITUATION_SECTORS.get(level,{}).get(sector,1)
        result[sector]=max(.1,value)
    return result


def plan_shares(ctx,previous):
    """Udziały procentowe sektorów (rezerwa = reszta do 100%), wygładzone poprzednim planem zależnie od przewidywalności."""
    weights=sector_weights(ctx);total=sum(weights.values())
    target={s:Decimal(str(100*weights[s]/total)) for s in SECTORS}
    previous={s:dec(previous.get(s)) for s in SECTORS} if previous and sum(dec(previous.get(s)) for s in SECTORS)>0 else None
    if previous:
        alpha=Decimal(str(round(.15+.45*ctx.traits.get('predictability',50)/100,4)))
        target={s:(1-alpha)*target[s]+alpha*previous[s] for s in SECTORS}
    return {s:target[s].quantize(CENT,rounding=ROUND_DOWN) for s in SECTORS}


def social_coverage_target(ctx):
    """Docelowe pokrycie oczekiwanych świadczeń (0.4–1.0) — prospołeczność, priorytet opiekuńczy, charakter państwa dobrobytu."""
    weights=priority_weights(ctx.priorities)
    value=.35+.55*ctx.traits.get('prosociality',50)/100+.4*weights.get('welfare',0)+(.15 if 'welfare' in ctx.categories else 0)
    if ctx.situation.get('level')=='war':value-=.15
    return clip(value,.4,1.0)


def with_social_floor(shares,state,coverage):
    """Podnosi udział polityki społecznej, aby sfinansować docelową część świadczeń; pozostałe sektory oddają proporcjonalnie."""
    expected=sum(dec(v) for v in ((state.get('benefits') or {}).get('expected') or {}).values())
    budget=dec(state.get('budget_total'))
    if expected<=0 or budget<=0:return shares,False
    carry=dec((state.get('benefits') or {}).get('carry_in'))
    needed=max(Decimal(0),expected*Decimal(str(coverage))-carry)
    share=(needed*100/budget).quantize(CENT,rounding=ROUND_HALF_UP)+CENT
    if share<=shares['social_policy']:return shares,False
    share=min(share,Decimal('60'))
    others=[s for s in SECTORS if s!='social_policy'];rest=sum(shares[s] for s in others)
    room=sum(shares.values())-share
    if rest<=0 or room<0:return shares,False
    scaled={s:(shares[s]*room/rest).quantize(CENT,rounding=ROUND_DOWN) for s in others}
    return {**scaled,'social_policy':share},True


def payments(state):
    """Wypłaty: pełne oczekiwania, gdy budżet społeczny wystarcza, w przeciwnym razie proporcjonalnie do dostępnych środków."""
    benefits=state.get('benefits') or {};expected=benefits.get('expected') or {}
    values={k:dec(expected.get(k)) for k in ('children','seniors')}
    total=sum(values.values())
    available=dec((state.get('allocations') or {}).get('social_policy'))+dec(benefits.get('carry_in'))
    if total<=0:return {'children':'0.00','seniors':'0.00'},Decimal(1)
    paid=min(total,available)
    children=(paid*values['children']/total).quantize(CENT,rounding=ROUND_DOWN)
    seniors=(paid-children).quantize(CENT,rounding=ROUND_DOWN)
    return {'children':str(children),'seniors':str(seniors)},(children+seniors)/total


def half(value):
    """Zaokrąglenie stawki do wielokrotności 0,5 pkt proc."""
    return ((Decimal(value)*2).quantize(Decimal('1'),rounding=ROUND_HALF_UP)/2).quantize(Decimal('0.1'))


def max_step(ctx):
    """Największa zmiana stawki PIT w jednym półroczu: 3–12 pkt proc. (elastyczność strategiczna, w czasie wojny +3)."""
    value=3+9*ctx.traits.get('strategic_flexibility',50)/100+(3 if ctx.situation.get('level')=='war' else 0)
    return Decimal(str(round(value*2)/2))


def penalty_free_rate(state):
    """Najwyższa stawka bez kary społecznej, liczona tą samą funkcją co gra (game.general_tax.tax_penalty)."""
    basis=state.get('revenue_basis')
    if not isinstance(basis,dict) or basis.get('trust') is None:return None
    from game.general_tax import tax_penalty
    best=None;rate=Decimal('0.5')
    while rate<=Decimal('80'):
        if tax_penalty(basis,rate)==0:best=rate
        else:break
        rate+=Decimal('0.5')
    return best


def preview(ctx,body):
    status,data=ctx.call(PREVIEW,json=body)
    if status>=400 or not isinstance(data,dict) or not isinstance(data.get('state'),dict):
        raise RuntimeError('Podgląd budżetu odrzucony: '+str((data or {}).get('error') if isinstance(data,dict) else status))
    return data['state']


def propose(ctx):
    baseline=preview(ctx,{})
    if baseline.get('approved'):return []
    previous_rate=dec(baseline.get('pit_rate'),'10')
    shares=plan_shares(ctx,baseline.get('shares') if baseline.get('has_previous') else None)
    limit=penalty_free_rate(baseline)
    step=max_step(ctx)
    # Pierwszy budżet państwa (12 Nov 2026): stawka startuje z domyślnych 5% — od razu wolno dojść do stawki bez kary społecznej.
    if not baseline.get('has_previous') and limit is not None and limit>previous_rate:step=max(step,limit-previous_rate)
    # Odpowiedzialna zmiana: w jednym półroczu stawka zmienia się najwyżej o `step` pkt proc.; dalszy kierunek w kolejnych okresach.
    rates={previous_rate,previous_rate-step,previous_rate-step/2,previous_rate+step/2,previous_rate+step}
    if limit is not None and abs(limit-previous_rate)<=step:rates.add(limit)
    rates=sorted({half(r) for r in rates if Decimal('1')<=half(r)<=Decimal('60')})
    coverage=social_coverage_target(ctx)
    base_revenue=None;options=[]
    t=ctx.traits;war=ctx.situation.get('level')=='war'
    for rate in rates:
        body={'pit_rate':str(rate),'shares':{k:str(v) for k,v in shares.items()}}
        state=preview(ctx,body)
        adjusted,changed=with_social_floor(shares,state,coverage)
        if changed:
            body['shares']={k:str(v) for k,v in adjusted.items()}
            state=preview(ctx,body)
        paid,covered=payments(state)
        revenue=dec(state.get('tax_total'));penalty=int(dec(state.get('tax_penalty')))
        if rate==previous_rate:base_revenue=revenue
        options.append((rate,body,state,paid,covered,revenue,penalty))
    base_revenue=base_revenue or max((o[5] for o in options),default=Decimal(1))
    result=[]
    for rate,body,state,paid,covered,revenue,penalty in options:
        gain=float((revenue-base_revenue)/base_revenue) if base_revenue>0 else 0.0
        # Malejąca użyteczność dodatkowych dochodów (logarytm), aby wzrost wpływów nie przesłonił kosztów społecznych.
        base=(12*math.log1p(max(gain,-.9))*(.6+t.get('fiscal_conservatism',50)/100+(.6 if war else 0))
              -penalty*(3+5*t.get('prosociality',50)/100+4*(100-t.get('loss_tolerance',50))/100)
              -abs(float(rate-previous_rate))*.4*t.get('predictability',50)/100
              +(10*(float(covered)-1)*(t.get('prosociality',50)/100+.3) if covered<1 else 0))
        notes=[f'Stawka PIT {rate}% (poprzednia {previous_rate}%' + (f', bez kary do {limit}%' if limit is not None else '')+f'; maks. zmiana w półroczu {step} pkt).',
               f'Dochody podatkowe: {revenue:,.0f} ROI ({gain*100:+.1f}% wobec poprzedniej stawki).'.replace(',',' '),
               f'Kara społeczna za wysoki podatek: {penalty} pkt.',f'Pokrycie oczekiwanych świadczeń: {float(covered)*100:.0f}%.']
        result.append(Option(key=f'budget:{rate}',domain='finance',action='BUDGET_APPROVE',label=f'Budżet półrocza z podatkiem PIT {rate}%',
                             effects={'financial_stability':clip(gain*2,-1,1),'welfare':clip(-penalty/4+(float(covered)-1),-1,1)},
                             base=round(base,3),notes=notes,
                             payload={'group':'budget','year':state.get('year'),'period':state.get('period'),'basis_token':state.get('basis_token'),
                                      'pit_rate':str(rate),'shares':body['shares'],'benefits':paid,
                                      'summary':{'tax_total':str(revenue),'budget_total':str(state.get('budget_total')),'penalty':penalty,'coverage':round(float(covered),3),
                                                 'allocations':{k:str(v) for k,v in (state.get('allocations') or {}).items()}}}))
    return result


def check(ctx,option):
    if not option.payload.get('basis_token'):return 'Brak tokenu podglądu budżetu.'
    return None


def execute(ctx,option):
    p=option.payload
    status,data=ctx.call(APPROVE,json={'year':p['year'],'period':p['period'],'basis_token':p['basis_token'],'pit_rate':p['pit_rate'],
                                       'shares':p['shares'],'benefits':p['benefits'],'repeat_previous':False})
    data=data if isinstance(data,dict) else {}
    return {'status':status,'budget_id':data.get('budget_id'),'already_approved':data.get('already_approved'),'error':data.get('error')}


ADAPTER=register(Adapter(name='budget',modes=('BUDGET',),propose=propose,execute=execute,check=check))
