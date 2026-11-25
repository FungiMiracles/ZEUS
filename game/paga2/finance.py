"""PAGA2 — finanse w trakcie półrocza: przesunięcia między sektorami, wnioski o pożyczki, spłaty
oraz decyzje o udzieleniu pożyczki innym państwom (19 Nov 2026: decyduje wyłącznie PAGA2 — zob. loan_decision).
"""
from decimal import Decimal,ROUND_DOWN
from uuid import uuid5,NAMESPACE_URL
from sqlalchemy import select
from sqlalchemy.orm import Session
from extensions import db
from game.paga2.engine import Adapter,register
from game.paga2.scoring import Option,clip
from game.paga2.catalog import priority_weights

SECTORS=('administration','infrastructure','armed_forces','social_policy','environment','healthcare','education','research','security_services')
SECTOR_PRIORITY={'infrastructure':'infrastructure','armed_forces':'defensive_army','social_policy':'welfare','environment':'environment','healthcare':'welfare',
                 'education':'research','research':'research','security_services':'intelligence','administration':'financial_stability','reserve':'financial_stability'}
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
    return {'budget_id':budget,'can_transfer':budget is not None,'public_trust':trust,'sector_transfers_allowed':True,
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
    protected=imf_installment(imf_loans(ctx))
    for recipient,need in sorted(needs.items(),key=lambda item:-item[1]):
        if need<MIN_TRANSFER or recipient=='reserve':continue
        donors=[]
        for donor in SECTORS:
            if donor==recipient:continue
            surplus=ctx.available(donor)-share[donor]*total*.8
            if surplus>MIN_TRANSFER and (sectors_allowed or (defense_allowed and recipient=='armed_forces')):donors.append((donor,surplus))
        # 18 Nov 2026: rata MFW należna w tym cyklu nie jest dostępna do przesunięć z rezerwy.
        reserve=max(0.0,ctx.available('reserve')-protected)*(.6-.4*ctx.traits.get('fiscal_conservatism',50)/100)
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


IMF_REQUEST_EVERY_DAYS=90    # kolejny wniosek do MFW najwcześniej po tylu dniach gry
IMF_REFUSAL_DAYS=120         # po odmowie MFW państwo czeka dłużej
IMF_CONSERVATIVE=70          # od tego konserwatyzmu fiskalnego: brak wniosków w pokoju, mała kwota w wojnie
IMF_MIN_COVERAGE=.3          # pożyczka musi pokryć co najmniej 30% niedoboru
IMF_MIN_REPAYMENT=1e8        # spłaty poniżej 0,1 MLD pomijane


def imf_installment(loans):
    """18 Nov 2026: rata MFW należna w bieżącym cyklu według harmonogramu (bez odsetek): w cyklu wypłaty brak raty,
    w trzech kolejnych po 1/3 pożyczki, przed terminem (1 cykl lub mniej) — cała reszta. Liczona od celu „ile może
    jeszcze zostać do spłaty”, więc ponowne wywołanie w tym samym cyklu nie każe płacić drugi raz."""
    from game.imf import REPAYMENT_CYCLES
    due=0.0
    for loan in loans or []:
        if loan.get('status')!='active':continue
        left,amount,outstanding=loan.get('periodsLeft'),float(loan.get('amount') or 0),float(loan.get('outstanding') or 0)
        target=0.0 if loan.get('overdue') or left is None or left<=1 else amount*min(1.0,(left-1)/(REPAYMENT_CYCLES-1))
        due+=max(0.0,outstanding-target)
    return due


def imf_loans(ctx):
    screen=getattr(ctx,'screen',None)
    if screen is None:return []
    return ((screen('imf') or {}).get('data') or {}).get('loans') or []


def imf_options(ctx):
    """18 Nov 2026: pożyczki Międzynarodowego Funduszu Walutowego (ekran /game/mfw/stan — to samo, co widzi gracz).

    Wniosek: gdy brakuje środków na plany / bieżące potrzeby (albo na wojnie — na siły zbrojne), a państwo toleruje
    zadłużenie (próg 35 pkt, wyższy przy izolacjonizmie > 50, niższy o 15 pkt w wojnie). Konserwatyzm fiskalny ≥ 70
    blokuje wniosek w pokoju i ogranicza kwotę w wojnie. Kwota: najwyżej 50–70% zdolności kredytowej i pula MFW, co
    najmniej 30% niedoboru. Najwyżej jedna aktywna pożyczka; koszt odsetek (5% za cykl) obniża ocenę wniosku.
    Spłata: z nadwyżki rezerwy ponad potrzeby planów; pilnie, gdy zbliża się termin (inaczej MFW pobierze do 65% budżetu).
    """
    screen=(ctx.screen('imf') or {}).get('data') or {}
    if not screen:return []
    t=ctx.traits;options=[]
    tolerance,conservatism,isolationism=t.get('debt_tolerance',50),t.get('fiscal_conservatism',50),t.get('isolationism',50)
    war=ctx.situation.get('level')=='war'
    loans=screen.get('loans') or [];reserve=float(screen.get('reserve') or 0)
    needs=plan_needs(ctx);planned=sum(needs.values())
    active=[loan for loan in loans if loan.get('status')=='active']
    debt=sum(float(loan.get('outstanding') or 0) for loan in active)
    if debt>0:
        # (B) 18 Nov 2026: spłata ratalna — co cykl rata z harmonogramu (imf_installment), także bez „nadwyżki”;
        # potrzeby planów chronią rezerwę tym słabiej, im bliżej terminu (3+ cykle: 50%, 2 cykle: 25%, ostatni: 0%).
        left=min((loan.get('periodsLeft') if loan.get('periodsLeft') is not None else 0) for loan in active)
        urgent=any(loan.get('overdue') for loan in active) or left<=1
        installment=imf_installment(active)
        keep=planned*(.5 if left>=3 else .25 if left==2 else 0.0)+(0.0 if urgent else reserve*(.15 if war else .05))
        payable=max(0.0,reserve-keep)
        spare=reserve-planned-reserve*(.2 if war else .05)
        willing=conservatism>=55 or tolerance<=45 or spare>=debt*1.5
        amount=min(debt,max(min(installment,payable),spare if willing else 0.0,min(installment,reserve*.65) if urgent else 0.0))
        if amount>=IMF_MIN_REPAYMENT:
            whole=amount>=debt
            value=Decimal(str(amount)).quantize(CENT,rounding=ROUND_DOWN)
            notes=[f'Rata według harmonogramu: {installment/1e9:.2f} MLD (do terminu: {left} cykl.).']
            if urgent:notes.append('Termin spłaty blisko — bez spłaty MFW pobierze zaległość z budżetu (do 65%).')
            if amount<installment:notes.append(f'Rezerwa pozwala spłacić tylko {float(value)/1e9:.2f} MLD z raty.')
            options.append(Option(key='imf:repay',domain='finance',action='IMF_REPAY',
                                  label=f'Spłata MFW: {"całość" if whole else f"{float(value)/1e9:.2f} MLD"} (dług {debt/1e9:.2f} MLD)',
                                  effects={'financial_stability':.8},traits={'fiscal_conservatism':.8,'debt_tolerance':-.6,'predictability':.3},
                                  base=(4.0 if installment>0 else 2.0)+(3.0 if urgent else 0.0)-(1.0 if war and not urgent else 0.0),
                                  notes=notes,payload={'amount':'all' if whole else str(value),'group':'imf_repay'}))
    if any(o.action=='IMF_REPAY' for o in options):return options   # spłata w tym cyklu — bez nowego wniosku
    if any(loan_age_days(loan)<IMF_REQUEST_EVERY_DAYS for loan in loans if loan.get('status')!='rejected'):return options
    if any(loan_age_days(loan)<IMF_REFUSAL_DAYS for loan in loans if loan.get('status')=='rejected'):return options
    # 18 Nov 2026 (korekty po analizie pierwszych pożyczek):
    # (1) wysoki konserwatyzm fiskalny blokuje wniosek w pokoju, a w wojnie ogranicza kwotę;
    if conservatism>=IMF_CONSERVATIVE and not war:return options
    # (2) izolacjonizm tylko podnosi próg (nie obniża go poniżej 35); wojna nadal obniża próg o 15 pkt;
    threshold=35+max(0.0,(isolationism-50)*.4)-(15 if war else 0)
    if tolerance<threshold:return options
    # 18 Nov 2026: najwyżej jedna aktywna pożyczka w MFW — nowa dopiero po spłacie poprzedniej.
    if debt>0 or (screen.get('credit') or {}).get('activeLoan'):return options
    credit=screen.get('credit') or {}
    capacity,base=float(credit.get('capacity') or 0),float(credit.get('base') or 0)
    max_loan=float(credit.get('maxLoan') or 0)
    plan_shortage=planned-sum(ctx.available(s) for s in SECTORS)*.3-reserve*.5
    army_gap=ctx.sector_start('armed_forces')*.5-ctx.available('armed_forces') if war else 0.0
    shortage=max(plan_shortage,army_gap)
    if shortage<1e9 or max_loan<1e9:return options
    appetite=clip(.5+tolerance/100-conservatism/200+(.3 if war else 0),.3,1.3)
    if conservatism>=IMF_CONSERVATIVE:appetite=min(appetite,.4)   # (1) wojna: ostrożna kwota
    # (3) zapas zdolności kredytowej: najwyżej 50–70% zdolności (więcej przy wyższej tolerancji zadłużenia);
    headroom=capacity*(.5+.2*tolerance/100)
    amount=int(min(shortage*appetite,max_loan,headroom)//1e9)*Decimal(1000000000)
    # (4) wniosek tylko, gdy pożyczka pokryje sensowną część niedoboru (≥ 30%).
    if amount<1000000000 or float(amount)<shortage*IMF_MIN_COVERAGE:return options
    # (6) osobna notatka dla luki w budżecie sił zbrojnych (wojna) i dla potrzeb planów.
    notes=[]
    if plan_shortage>=1e9:notes.append(f'Niedobór środków na plany i bieżące potrzeby: {plan_shortage/1e9:.2f} MLD.')
    if war and army_gap>=1e9:notes.append(f'Luka w budżecie sił zbrojnych (wojna): {army_gap/1e9:.2f} MLD.')
    notes.append(f'Kwota {float(amount)/1e9:.0f} MLD pokrywa {float(amount)/shortage*100:.0f}% niedoboru; zdolność kredytowa {capacity/1e9:.2f} MLD.')
    # 18 Nov 2026: odsetki 5% za cykl — koszt pełnego terminu (4 cykle, procent składany) obniża atrakcyjność pożyczki.
    rate=float((screen.get('rules') or {}).get('interestRate') or 0)/100
    cost=float(amount)*((1+rate)**4-1)
    if cost>0:notes.append(f'Koszt odsetek przy spłacie w terminie: do {cost/1e9:.2f} MLD ({rate*100:.0f}% za cykl).')
    if war:notes.append('Państwo prowadzi wojnę.')
    option=Option(key='imf:request',domain='finance',action='IMF_REQUEST',label=f'Wniosek do MFW o pożyczkę {float(amount)/1e9:.0f} MLD',
                  effects={'financial_stability':-.2-min(.4,rate*4)},traits={'debt_tolerance':1.0,'fiscal_conservatism':-.6-min(.3,rate*4),'isolationism':-.5},
                  base=2.0+min(8.0,shortage/1e10)+(3.0 if war else 0.0)-min(3.0,rate*30),notes=notes,
                  payload={'amount':str(amount),'group':'loan'})
    for sector in needs:
        key=SECTOR_PRIORITY.get(sector)
        if key:option.effects[key]=max(option.effects.get(key,0),.6)
    if war:option.effects['defensive_army']=max(option.effects.get('defensive_army',0),.7)
    options.append(option)
    return options


# 19 Nov 2026 (decyzja administratora): o udzieleniu pożyczki decyduje wyłącznie PAGA2 — na podstawie relacji z państwem
# wnioskującym, ilości własnych środków (rezerwy), konserwatyzmu fiskalnego i solidarności międzynarodowej.
# Wcześniej decyzję podejmował model AI; przy wyczerpanych limitach dostawców wnioski czekały bez końca.
RELATION_ORDER=('egzystencjalniewrogie','wrogie','napiete','zle','chlodne','neutralne','dobre','przyjazne','partnerskie','partnerskiestrategiczne','sojusznicze')
LOAN_MIN_RELATION='chlodne'     # przy relacji gorszej niż chłodna pożyczki nie udziela się nikomu


def relation_factor(relation):
    """Relacja z wnioskującym w skali −1 (egzystencjalnie wrogie) … 0 (neutralne) … +1 (sojusznicze)."""
    from services.natural_resources import normalized
    name=normalized(relation or 'neutralne')
    index=RELATION_ORDER.index(name) if name in RELATION_ORDER else RELATION_ORDER.index('neutralne')
    return (index-5)/5


def loan_decision(amount,reserve,relation,fiscal_conservatism,solidarity,at_war=False):
    """Decyzja o wniosku: (przyjąć?, część rezerwy, którą państwo gotowe jest pożyczyć, uzasadnienie).

    Część rezerwy = 25% + 35% × relacja + 25% × solidarność − 25% × konserwatyzm (cechy 0–100 względem 50), w granicach 0–75%.
    Wniosek jest przyjmowany, gdy kwota mieści się w tej części rezerwy, a relacja jest co najmniej chłodna i nie trwa wojna."""
    rel=relation_factor(relation);sol=(float(solidarity)-50)/50;cons=(float(fiscal_conservatism)-50)/50
    share=clip(.25+.35*rel+.25*sol-.25*cons,0.0,.75)
    limit=max(0.0,float(reserve))*share
    from services.natural_resources import normalized
    name=normalized(relation or 'neutralne')
    hostile=name in RELATION_ORDER and RELATION_ORDER.index(name)<RELATION_ORDER.index(LOAN_MIN_RELATION)
    accept=not at_war and not hostile and 0<float(amount)<=limit
    reason=('wojna z wnioskującym' if at_war else f'relacja „{relation}” gorsza niż chłodna' if hostile
            else f'kwota {float(amount)/1e9:.2f} MLD mieści się w limicie {limit/1e9:.2f} MLD' if accept
            else f'kwota {float(amount)/1e9:.2f} MLD przekracza limit {limit/1e9:.2f} MLD')
    note=(f'Relacja: {relation} ({rel:+.1f}), rezerwa: {float(reserve)/1e9:.2f} MLD, konserwatyzm fiskalny: {float(fiscal_conservatism):.0f}, '
          f'solidarność: {float(solidarity):.0f} → gotowość pożyczenia {share*100:.0f}% rezerwy; {reason}.')
    return accept,round(share,3),note


def loan_decision_options(ctx):
    """Odpowiedź na każdy oczekujący wniosek skierowany do tego państwa — decyzja wymagana (zapada zawsze, poza limitem działań)."""
    screen=(ctx.screen('loans') or {}).get('data') or {}
    reserve=float(screen.get('reserve') or 0);options=[]
    t=ctx.traits;relations=ctx.situation.get('relations',{});wars=set(ctx.situation.get('at_war',[]))
    for loan in screen.get('loans') or []:
        if loan.get('ownRequest') or loan.get('status')!='pending':continue
        other=loan.get('borrowerId');amount=float(loan.get('amount') or 0)
        relation=(relations.get(other) or {}).get('relation_label') or 'neutralne'
        accept,share,note=loan_decision(amount,reserve,relation,t.get('fiscal_conservatism',50),t.get('solidarity',50),at_war=other in wars)
        if accept:reserve-=amount   # kolejne wnioski w tym przebiegu liczone od pomniejszonej rezerwy
        options.append(Option(key=f'loan:{"accept" if accept else "reject"}:{loan["id"]}',domain='finance',action='LOAN_ACCEPT' if accept else 'LOAN_REJECT',
                              label=f'{"Udzielenie" if accept else "Odmowa udzielenia"} pożyczki #{loan["id"]} ({amount/1e9:.2f} MLD) dla {loan.get("borrower")}',
                              target=other,stance='friendly' if accept else 'neutral',base=5.0,notes=[note],
                              payload={'loan_id':loan['id'],'group':f'loan:decide:{loan["id"]}','required':True,'share':share}))
    return options


def propose(ctx):
    return transfer_options(ctx)+loan_options(ctx)+loan_decision_options(ctx)+imf_options(ctx)


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
    if option.action in ('LOAN_ACCEPT','LOAN_REJECT'):
        status,data=ctx.call('/game/pozyczki/zmien',json={'action':'accept' if option.action=='LOAN_ACCEPT' else 'reject','loan_id':p['loan_id']})
        return result(status,data)
    if option.action=='LOAN_REPAY':
        status,data=ctx.call('/game/pozyczki/zmien',json={'action':'repay','loan_id':p['loan_id'],'request_id':request_id(ctx,option)})
        return result(status,data)
    if option.action in ('IMF_REQUEST','IMF_REPAY'):
        status,data=ctx.call('/game/mfw/zmien',json={'action':'request' if option.action=='IMF_REQUEST' else 'repay','amount':p['amount'],'request_id':request_id(ctx,option)})
        if status<400 and option.action=='IMF_REQUEST' and isinstance(data,dict) and data.get('status')=='rejected':
            return result(status,data,note='MFW odrzucił wniosek: '+(data.get('reason') or ''))
        return result(status,data)
    return {'status':400,'error':'Nieznana operacja finansowa.'}


ADAPTER=register(Adapter(name='finance',modes=('CYCLIC','IMMEDIATE'),propose=propose,execute=execute))
