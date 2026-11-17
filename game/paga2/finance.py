"""PAGA2 — finanse w trakcie półrocza: przesunięcia między sektorami, wnioski o pożyczki, spłaty
oraz ocena zdolności do udzielenia pożyczki (decyzję o udzieleniu podejmuje model AI — zob. loan_capacity).
"""
from decimal import Decimal,ROUND_DOWN
from uuid import uuid5,NAMESPACE_URL
from sqlalchemy import select
from sqlalchemy.orm import Session
from extensions import db
from game.paga2.engine import Adapter,register
from game.paga2.scoring import Option,clip
from game.paga2.catalog import priority_weights

SECTORS=('administration','infrastructure','armed_forces','social_policy','environment','healthcare','education','research','security_services','propaganda')
SECTOR_PRIORITY={'infrastructure':'infrastructure','armed_forces':'defensive_army','social_policy':'welfare','environment':'environment','healthcare':'welfare',
                 'education':'research','research':'research','security_services':'intelligence','propaganda':'alliances','administration':'financial_stability','reserve':'financial_stability'}
MIN_TRANSFER=1e8     # przesunięcia poniżej 0,1 MLD nie mają sensu
CENT=Decimal('0.01')


def request_id(ctx,option):return str(uuid5(NAMESPACE_URL,f'paga2:{ctx.request_key}:{option.key}'))


def result(status,data,**extra):
    data=data if isinstance(data,dict) else {}
    return {'status':status,'error':data.get('error'),**extra}


def finance_state(ctx):
    """Stan budżetu z ekranu finansów gracza; gdy ekran jest niedostępny — te same pola z własnych danych w bazie."""
    screen=ctx.screen('finance')
    state=((screen or {}).get('data') or {}).get('finance_state') or {}
    if state.get('budget_id'):return state
    from game.finance_models import StateBudget
    from game.finance_service import period_key
    from game.budget_transfers import public_trust,TRANSFER_TRUST_THRESHOLD,defensive_war
    year,period=period_key(ctx.now)
    with Session(db.engine) as session:
        budget=session.scalar(select(StateBudget.id).where(StateBudget.panstwo_id==ctx.country_id,StateBudget.game_year==year,StateBudget.period==period))
        trust=public_trust(session,ctx.country_id) if budget else None
        defense=defensive_war(session,ctx.country_id) if budget else False
    return {'budget_id':budget,'can_transfer':budget is not None,'public_trust':trust,'sector_transfers_allowed':trust is None or trust>TRANSFER_TRUST_THRESHOLD,
            'defense_transfers_allowed':defense}


def targets(ctx):
    """Docelowe proporcje środków sektorów (te same wagi co przy budżecie: profil i sytuacja)."""
    from game.paga2.budget import sector_weights
    weights=sector_weights(ctx);total=sum(weights[s] for s in SECTORS)
    return {s:weights[s]/total for s in SECTORS}


def plan_needs(ctx):
    """Brakujące środki na najbliższe etapy aktywnych planów (sektor -> kwota ROI)."""
    from game.paga2.models import Paga2Plan,table_ready
    needs={}
    with Session(db.engine) as session:
        if not table_ready(session,Paga2Plan):return needs
        for row in session.scalars(select(Paga2Plan).where(Paga2Plan.country_id==ctx.country_id,Paga2Plan.status=='ACTIVE')):
            item=next((s for s in row.steps or [] if s.get('status')=='ready' and s.get('cost') and s.get('sector')),None)
            if item and ctx.available(item['sector'])<item['cost']:
                needs[item['sector']]=needs.get(item['sector'],0)+item['cost']-ctx.available(item['sector'])
    return needs


def transfer_options(ctx):
    state=finance_state(ctx)
    budget_id=state.get('budget_id')
    if not budget_id or not state.get('can_transfer',True):return []
    sectors_allowed=bool(state.get('sector_transfers_allowed',True))
    defense_allowed=bool(state.get('defense_transfers_allowed',False))   # 17 Nov 2026: wojna obronna — do sił zbrojnych bez progu zaufania
    total=sum(ctx.available(s) for s in SECTORS)
    if total<=0 and ctx.available('reserve')<=0:return []
    share=targets(ctx);needs=plan_needs(ctx)
    # Sytuacja (wojna/zagrożenie) i profil: sektory wyraźnie poniżej proporcji docelowej.
    for sector in SECTORS:
        deficit=share[sector]*total-ctx.available(sector)
        if deficit>.15*share[sector]*total and ctx.situation.get('level')!='peace' and sector in ('armed_forces','security_services'):
            needs[sector]=max(needs.get(sector,0),deficit)
    weights=priority_weights(ctx.priorities);options=[]
    for recipient,need in sorted(needs.items(),key=lambda item:-item[1]):
        if need<MIN_TRANSFER or recipient=='reserve':continue
        donors=[]
        for donor in SECTORS:
            if donor==recipient:continue
            surplus=ctx.available(donor)-share[donor]*total*.8
            if surplus>MIN_TRANSFER and (sectors_allowed or (defense_allowed and recipient=='armed_forces')):donors.append((donor,surplus))
        reserve=ctx.available('reserve')*(.6-.4*ctx.traits.get('fiscal_conservatism',50)/100)
        if reserve>MIN_TRANSFER:donors.append(('reserve',reserve))
        if not donors:continue
        # Dawca: najmniej ważny dla priorytetów sektor z nadwyżką (rezerwa — gdy brak innych lub mało konserwatywne państwo).
        donor,surplus=min(donors,key=lambda d:(weights.get(SECTOR_PRIORITY.get(d[0]),0),-d[1]))
        amount=Decimal(str(min(need,surplus))).quantize(CENT,rounding=ROUND_DOWN)
        if amount<MIN_TRANSFER:continue
        recipient_priority=SECTOR_PRIORITY.get(recipient);donor_priority=SECTOR_PRIORITY.get(donor)
        effects={}
        if recipient_priority:effects[recipient_priority]=1.0
        if donor_priority and donor_priority!=recipient_priority:effects[donor_priority]=effects.get(donor_priority,0)-.4
        options.append(Option(key=f'transfer:{donor}:{recipient}',domain='finance',action='TRANSFER',label=f'Przesunięcie {float(amount)/1e9:.2f} MLD: {donor} → {recipient}',
                              effects=effects,traits={'strategic_flexibility':.5,'fiscal_conservatism':-.3 if donor=='reserve' else 0},base=3.0,
                              notes=[f'Potrzeba w sektorze {recipient}: {need/1e9:.2f} MLD; nadwyżka dawcy {donor}: {surplus/1e9:.2f} MLD.'],
                              payload={'source':donor,'destination':recipient,'amount':str(amount),'budget_id':budget_id,'group':'transfer'}))
    return options


LOAN_REPAY_AFTER_DAYS=180     # spłata najwcześniej po pół roku gry (wcześniej pożyczka wpływała do rezerwy i była od razu spłacana)
LOAN_REQUEST_EVERY_DAYS=60    # kolejny wniosek do tego samego państwa najwcześniej po tylu dniach gry
LOAN_REFUSAL_DAYS=90          # po odmowie państwo nie jest proszone przez tyle dni gry


def loan_age_days(loan):
    """Wiek wniosku w dniach gry (createdAt to czas rzeczywisty UTC; zegar gry płynie szybciej)."""
    from datetime import datetime
    from engine.clock import get_time_multiplier
    try:created=datetime.fromisoformat(str(loan.get('createdAt','')).rstrip('Z'))
    except ValueError:return 0.0
    from game.paga2.models import utc_now
    return max(0.0,(utc_now()-created).total_seconds()*get_time_multiplier()/86400)


def loan_options(ctx):
    """Wniosek o pożyczkę, gdy brakuje środków na najważniejsze cele, a państwo toleruje zadłużenie; spłata, gdy rezerwa jest duża.
    12 Nov 2026: jeden dług naraz, przerwy między wnioskami, pamięć odmów i spłata dopiero po pół roku gry."""
    screen=(ctx.screen('loans') or {}).get('data') or {}
    loans=screen.get('loans') or [];reserve=float(screen.get('reserve') or 0);options=[]
    t=ctx.traits
    planned=sum(plan_needs(ctx).values())
    own=[loan for loan in loans if loan.get('ownRequest')]
    for loan in own:
        if loan.get('status')!='accepted' or loan_age_days(loan)<LOAN_REPAY_AFTER_DAYS:continue
        amount=float(loan.get('amount') or 0)
        if reserve-planned>=amount*(1.5+t.get('debt_tolerance',50)/50):
            options.append(Option(key=f'loan:repay:{loan["id"]}',domain='finance',action='LOAN_REPAY',label=f'Spłata pożyczki #{loan["id"]} ({amount/1e9:.2f} MLD) dla {loan.get("lender")}',
                                  target=loan.get('lenderId'),stance='friendly',effects={'financial_stability':.8},traits={'fiscal_conservatism':.8,'debt_tolerance':-.6,'predictability':.3},
                                  base=2.0,payload={'loan_id':loan['id'],'group':'loan'}))
    if any(loan.get('status')=='pending' for loan in own):return options
    outstanding=sum(1 for loan in own if loan.get('status')=='accepted')
    if outstanding>=(2 if t.get('debt_tolerance',50)>=80 else 1):return options
    recent={loan.get('lenderId') for loan in own if loan_age_days(loan)<LOAN_REQUEST_EVERY_DAYS}
    refused={loan.get('lenderId') for loan in own if loan.get('status')=='rejected' and loan_age_days(loan)<LOAN_REFUSAL_DAYS}
    needs=plan_needs(ctx);shortage=sum(needs.values())-sum(ctx.available(s) for s in SECTORS)*.3-reserve*.5
    if ctx.situation.get('level')=='war':shortage=max(shortage,ctx.sector_start('armed_forces')*.5-ctx.available('armed_forces'))
    if shortage<5e8 or t.get('debt_tolerance',50)<35:return options
    lenders=[int(id) for id in (screen.get('countries') or {}) if int(id) not in recent|refused]
    if not lenders:return options
    def appeal(other):
        p=ctx.perception(other);link=ctx.relationships.get(other,{})
        return p.get('trust',50)+(25 if other in ctx.situation.get('allies',[]) else 0)+(15 if link.get('status')=='historical_ally' else 0)-(40 if other in ctx.situation.get('hostile',[]) else 0)-(100 if other in ctx.situation.get('at_war',[]) else 0)
    best=max(lenders,key=appeal)
    if appeal(best)<40:return options
    amount=Decimal(str(min(shortage,5e10))).quantize(CENT,rounding=ROUND_DOWN)
    options.append(Option(key=f'loan:request:{best}',domain='finance',action='LOAN_REQUEST',label=f'Wniosek o pożyczkę {float(amount)/1e9:.2f} MLD od {screen["countries"].get(str(best))}',
                          target=best,stance='friendly',effects={'financial_stability':-.2},
                          traits={'debt_tolerance':1.0,'fiscal_conservatism':-.6,'agreeableness':.2},base=2.0+min(8.0,shortage/1e10),
                          notes=[f'Niedobór środków na cele państwa: {shortage/1e9:.2f} MLD.'],payload={'lender_id':best,'amount':str(amount),'group':'loan'}))
    for option in options:
        if option.action=='LOAN_REQUEST':
            for sector in needs:
                key=SECTOR_PRIORITY.get(sector)
                if key:option.effects[key]=max(option.effects.get(key,0),.6)
    return options


def loan_capacity(session,country_id,now=None):
    """Ile państwo PAGA2 może pożyczyć innemu państwu bez szkody dla własnych celów (dla modelu AI decydującego o pożyczce).

    Uwzględnia rezerwę, konserwatyzm fiskalny, potrzeby aktywnych planów i sytuację bezpieczeństwa.
    """
    from game.finance_models import StateFinancialAccount
    from game.paga2.models import Paga2Profile,Paga2Plan,table_ready
    from game.paga2.catalog import default_profile
    from game.paga2.situation import assess
    account=session.get(StateFinancialAccount,country_id);reserve=float(account.reserve_balance) if account else 0.0
    profile=session.get(Paga2Profile,country_id)
    traits=default_profile(profile.traits if profile else None)
    planned=0.0
    if table_ready(session,Paga2Plan):
        for row in session.scalars(select(Paga2Plan).where(Paga2Plan.country_id==country_id,Paga2Plan.status=='ACTIVE')):
            planned+=sum(float(s.get('cost') or 0) for s in row.steps or [] if s.get('status') in ('ready','blocked'))
    level=assess(session,country_id,now)['level'] if now else 'peace'
    keep=.3+.5*traits['fiscal_conservatism']/100+(.2 if level=='war' else .1 if level=='threat' else 0)
    capacity=max(0.0,reserve*(1-min(.95,keep))-planned*.25)
    return {'reserve':reserve,'planned_needs':planned,'kept_share':round(min(.95,keep),3),'security_level':level,'max_loan':round(capacity,2),
            'solidarity':traits['solidarity'],'trade_propensity':traits['trade_propensity']}


def propose(ctx):
    return transfer_options(ctx)+loan_options(ctx)


def execute(ctx,option):
    p=option.payload
    if option.action=='TRANSFER':
        status,data=ctx.call('/game/finanse/przesun',json={'source':p['source'],'destination':p['destination'],'amount':p['amount'],'budget_id':p['budget_id'],'request_id':request_id(ctx,option)})
        if status<400:
            ctx._sectors[p['source']]=ctx._sectors.get(p['source'],0)-float(p['amount']);ctx._sectors[p['destination']]=ctx._sectors.get(p['destination'],0)+float(p['amount'])
        return result(status,data)
    if option.action=='LOAN_REQUEST':
        status,data=ctx.call('/game/pozyczki/zmien',json={'action':'request','lender_id':p['lender_id'],'amount':p['amount'],'request_id':request_id(ctx,option)})
        return result(status,data)
    if option.action=='LOAN_REPAY':
        status,data=ctx.call('/game/pozyczki/zmien',json={'action':'repay','loan_id':p['loan_id'],'request_id':request_id(ctx,option)})
        return result(status,data)
    return {'status':400,'error':'Nieznana operacja finansowa.'}


ADAPTER=register(Adapter(name='finance',modes=('CYCLIC','IMMEDIATE'),propose=propose,execute=execute))
