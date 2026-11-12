"""Translate economic decisions into ordinary player requests; never bypass validators."""
from decimal import Decimal,ROUND_CEILING,ROUND_DOWN,localcontext
from sqlalchemy import select
from sqlalchemy.orm import Session
from extensions import db
from game.paga_ai_models import PagaAiLog

PREVIEW='game_finance.preview:POST'
APPROVE='game_finance.approve:POST'
RATIONALE={'type':'string','minLength':20,'maxLength':900}

def prepare_intent(data):
    """Explicit units/relative priorities; raw percentage plans are never silently normalized."""
    if data.get('repeat_previous') is True and set(data)-{'repeat_previous','rationale'}:
        raise ValueError('Powtórzenie zachowuje podatki, podział i wypłaty. Aby je zmienić, wybierz nowy plan z repeat_previous=false.')
    payload={k:v for k,v in data.items() if k not in ('rationale','allocation_weights','benefits_millions','benefit_policy')}
    if 'allocation_weights' in data:
        if 'shares' in data:raise ValueError('Wybierz jeden sposób podziału: względne allocation_weights albo dokładne shares, nie oba.')
        from game.finance_service import CATEGORY_CODES,decimal_value
        weights=data['allocation_weights']
        if not isinstance(weights,dict) or set(weights)-set(CATEGORY_CODES):raise ValueError('Wagi muszą wskazywać rzeczywiste kategorie budżetu.')
        weights={key:decimal_value(value,'Waga '+key) for key,value in weights.items()}
        if any(v<0 for v in weights.values()) or sum(weights.values())<=0:raise ValueError('Wagi priorytetów muszą być nieujemne i co najmniej jedna dodatnia.')
        with localcontext() as context:
            context.prec=64
            total=sum(weights.values())
            payload['shares']={key:str((value*100/total).quantize(Decimal('.01'),rounding=ROUND_DOWN)) for key,value in weights.items()}
        # The ordinary player calculator puts only the rounding remainder into reserve.
    if 'benefit_policy' in data and ('benefits_millions' in data or 'benefits' in data):raise ValueError('Wybierz politykę świadczeń albo konkretne kwoty, nie obie naraz.')
    if 'benefits_millions' in data:
        if 'benefits' in data:raise ValueError('Wybierz jedną jednostkę świadczeń: benefits_millions albo benefits, nie obie.')
        from game.finance_service import decimal_value
        benefits=data['benefits_millions']
        if not isinstance(benefits,dict) or set(benefits)-{'children','seniors'}:raise ValueError('Świadczenia dotyczą children i seniors.')
        payload['benefits']={key:str(decimal_value(value,'Świadczenie w milionach')*1000000) for key,value in benefits.items()}
    return payload

def policy_payments(state,policy):
    """An explicit economic policy, not a repair of an unaffordable amount order."""
    if policy not in ('available_proportional','expected','none'):raise ValueError('Nieznana polityka świadczeń.')
    with localcontext() as context:
        context.prec=64
        expected=(state.get('benefits') or {}).get('expected') or {}
        values={key:Decimal(str(expected.get(key,0))) for key in ('children','seniors')}
        if policy=='none':return {key:'0.00' for key in values}
        if policy=='expected':return {key:str(value) for key,value in values.items()}
        total=sum(values.values())
        available=Decimal(str(state.get('allocations',{}).get('social_policy',0)))+Decimal(str(state.get('benefits',{}).get('carry_in',0)))
        paid=min(total,available)
        children=(paid*values['children']/total).quantize(Decimal('.01'),rounding=ROUND_DOWN) if total else Decimal(0)
        return {'children':str(children),'seniors':str(paid-children)}

def completed_budget(state):
    """Player-visible 'approved' state as an explicit finished goal. Information only, not a game rule."""
    if not isinstance(state,dict) or not state.get('approved'):return None
    year,period,budget_id=state.get('year'),state.get('period'),state.get('budget_id')
    return {'goal':'budżet_półrocza','status':'ZAKOŃCZONY','year':year,'period':period,'budget_id':budget_id,
            'message':f'Budżet państwa na półrocze {year}/{period} jest już zatwierdzony (budget_id {budget_id}). Ta operacja została zakończona sukcesem. '
                      'Nie wywołuj ponownie game_finance.preview ani game_finance.approve w tym półroczu; kolejny budżet przygotujesz w następnym półroczu.',
            'next':'Przejdź do innych obszarów zgodnie z interesami PAGA: gospodarka (handel, przemysł, wydobycie, badania, infrastruktura, pożyczki, przesunięcia środków budżetu), '
                   'dyplomacja, wojsko, wywiad, forum i wiadomości. Jeśli nic nie wymaga działania, zakończ analizę operacją finish.'}

def latest_plan(actor):
    with Session(db.engine) as session:
        row=session.scalar(select(PagaAiLog).where(
            PagaAiLog.country_id==actor.country_id,PagaAiLog.job_id==actor.job_id,
            PagaAiLog.operation==PREVIEW).order_by(PagaAiLog.id.desc()).limit(1))
        if row is None or row.validation!='EXECUTED':
            raise ValueError('Najpierw przelicz poprawny plan budżetu, oceń wynik, następnie zatwierdź go bez parametrów technicznych.')
        plan=(row.result or {}).get('_budget_plan')
        if not plan:
            if ((row.result or {}).get('result') or {}).get('completed_goal'):
                raise ValueError('Ostatni podgląd wykazał, że budżet tego półrocza jest już zatwierdzony. Nie zatwierdzaj go ponownie.')
            raise ValueError('Ostatni podgląd nie zawiera planu do zatwierdzenia. Odczytaj game_finance.page:GET i przelicz plan przez preview.')
        return plan

def approval_payload(actor,data):
    if set(data)-{'rationale','accept_social_shortfall','accept_revenue_decline'}:
        raise ValueError('Zatwierdzenie dotyczy ostatniego podglądu. Zmianę podatku lub udziałów prześlij do podglądu; token i okres przygotowuje ZEUS.')
    if len(data.get('rationale','').strip())<20:
        raise ValueError('Uzasadnij zatwierdzenie: dochody, potrzeby społeczne i inwestycje oraz interesy PAGA. Stawki są w procentach: 5 oznacza 5%, a 0.05 oznacza 0.05%.')
    plan=latest_plan(actor)
    state=plan['state']
    expected=sum((Decimal(str(v)) for v in (state.get('benefits',{}).get('expected') or {}).values()),Decimal(0))
    allocated=Decimal(str(state.get('allocations',{}).get('social_policy',0)))+Decimal(str(state.get('benefits',{}).get('carry_in',0)))
    payments=plan.get('payments',{})
    paid=sum((Decimal(str(v)) for v in payments.values()),Decimal(0))
    if plan.get('repeat_previous'):paid=min(paid,allocated)
    if paid<expected and data.get('accept_social_shortfall') is not True:
        raise ValueError(f'Plan wypłat świadczeń wynosi {paid}, przy oczekiwaniach {expected}; niedobór {expected-paid}. Popraw plan albo świadomie zaakceptuj niedobór: accept_social_shortfall=true i uzasadnij strategię w rationale.')
    baseline=plan.get('baseline') or {}
    if baseline.get('tax_total') is not None and Decimal(str(state['tax_total']))<Decimal(str(baseline['tax_total'])) and data.get('accept_revenue_decline') is not True:
        raise ValueError('Plan zmniejsza dochody względem wariantu bazowego. Popraw plan albo podaj accept_revenue_decline=true i uzasadnij finansowanie potrzeb w rationale.')
    return {'year':state['year'],'period':state['period'],'basis_token':state['basis_token'],
            'pit_rate':state['pit_rate'],'shares':state['shares'],'repeat_previous':plan.get('repeat_previous',False),'benefits':payments}

def summary(state):
    keys=('balances','can_transfer','sector_transfers_allowed','public_trust','transfer_trust_threshold','approved','budget_id','year','period','has_previous','pit_rate','cit_rate','shares','tax_total',
          'budget_total','opening_reserve','closing_reserve','allocations','benefits','tax_penalty','revenue_basis')
    result={key:state[key] for key in keys if key in state}
    if state:
        expected=(state.get('benefits') or {}).get('expected') or {}
        result['amounts_in_millions']={
            'tax_revenue':str(Decimal(str(state.get('tax_total') or 0))/1000000),
            'budget_total':str(Decimal(str(state.get('budget_total') or 0))/1000000),
            'social_allocation':str(Decimal(str((state.get('allocations') or {}).get('social_policy') or 0))/1000000),
            'children_expected':str(Decimal(str(expected.get('children') or 0))/1000000),
            'seniors_expected':str(Decimal(str(expected.get('seniors') or 0))/1000000)}
    return result

def comparison(state,baseline,payments=None,repeat_previous=False):
    result={'plan':summary(state),'units':'Stawki i udziały w procentach: 5 = 5%, 0.05 = 0.05%.',
            'next':'Oceń dochody, oczekiwania świadczeń, inwestycje i PAGA. Popraw plan przez preview albo zatwierdź przez approve z rationale.'}
    expected=sum((Decimal(str(v)) for v in (state.get('benefits',{}).get('expected') or {}).values()),Decimal(0))
    allocated=Decimal(str(state.get('allocations',{}).get('social_policy',0)))+Decimal(str(state.get('benefits',{}).get('carry_in',0)))
    paid=sum((Decimal(str(v)) for v in (payments or {}).values()),Decimal(0))
    if repeat_previous:paid=min(paid,allocated)
    result['planned_benefit_payments']=payments or {'children':0,'seniors':0}
    if repeat_previous:result['repeat_note']='Poprzednie wypłaty; przy mniejszym budżecie gra zmniejsza je proporcjonalnie. planned_paid uwzględnia dostępne środki.'
    total_budget=Decimal(str(state.get('budget_total',0)))
    carry=Decimal(str(state.get('benefits',{}).get('carry_in',0)))
    needed=max(Decimal(0),paid-carry)
    minimum_share=((needed*100/total_budget).quantize(Decimal('.01'),rounding=ROUND_CEILING)) if total_budget>0 else None
    result['benefit_affordability']={'available':str(allocated),'planned_payments':str(paid),'minimum_social_share_percent_for_these_payments':str(minimum_share) if minimum_share is not None else None,
        'options':'Przy niedoborze sam wybierz: zwiększ social_policy do wskazanego udziału kosztem innych sektorów, przelicz inny podatek albo zmniejsz wypłaty. ZEUS nie wybiera priorytetów za gracza.'}
    result['amounts_in_millions']={'tax_revenue':str(Decimal(str(state.get('tax_total',0)))/1000000),'budget_total':str(total_budget/1000000),
        'social_available':str(allocated/1000000),'benefits_expected':str(expected/1000000),'benefits_planned':str(paid/1000000),
        'unfunded_payments':str(max(Decimal(0),paid-allocated)/1000000)}
    result['social_expectations_check']={'expected':str(expected),'allocated':str(allocated),'planned_paid':str(paid),'unfunded_planned_payments':str(max(Decimal(0),paid-allocated)),'gap':str(max(Decimal(0),expected-paid)),
        'meaning':'Przydział środków nie jest wypłatą świadczeń. Porównanie oczekiwań z zaplanowanymi wypłatami; niedobór wymaga świadomego uzasadnienia, nie jest nową regułą gry.'}
    if baseline and not baseline.get('approved'):

        before=Decimal(str(baseline['tax_total']));after=Decimal(str(state['tax_total']))
        result['baseline']={key:baseline.get(key) for key in ('pit_rate','tax_total','budget_total','benefits')}
        result['change_in_tax_revenue']=str(after-before)
        result['change_in_tax_revenue_percent']=str((after-before)*100/before) if before else None
    return result

BUDGET_GUIDANCE=(
    ' Finanse: najpierw game_finance.page:GET. PIT jest w procentach: 5 oznacza 5%, 0.05 oznacza 0.05%. '
    'game_finance.preview:POST przyjmuje pit_rate, allocation_weights, benefit_policy ALBO benefits_millions, repeat_previous i rationale. '
    'allocation_weights to WZGLĘDNE WAGI priorytetów w kodach kategorii z finansów, nie procenty: nie muszą sumować się do 100. '
    'ZEUS proporcjonalnie przelicza wagi na udziały, które zobaczysz w podglądzie. Wybierz własne priorytety zgodnie z PAGA. '
    'benefit_policy=available_proportional oznacza: wypłać dzieciom i seniorom proporcjonalnie do oczekiwań, najwyżej do wysokości dostępnego budżetu social_policy. To świadoma strategia częściowego pokrycia potrzeb; actualne kwoty i niedobór pokaże ZEUS. benefit_policy=expected żąda pełnych oczekiwanych kwot i wymaga odpowiedniego finansowania, none oznacza brak wypłat. Nie łącz polityki z konkretnymi kwotami. '
    'benefits_millions określa KWOTY W MILIONACH dla children i seniors: 100 oznacza 100 mln, nie 100 jednostek. '
    'Przydział social_policy nie jest wypłatą: brak benefits_millions oznacza wypłaty 0 w nowym planie. '
    'Oczekiwania społeczne i available/carry_in są w danych; amounts_in_millions pomaga porównać kwoty. '
    'Oceń dochody, świadczenia, inwestycje, kary podatkowe i PAGA. minimum_social_share_percent_for_these_payments pokazuje potrzebny udział dla wybranych wypłat. '
    'Jeśli wypłaty przekraczają social_available, zmień wagi, podatek lub kwoty świadczeń i PRZELICZ NOWY PLAN; nie da się wypłacić pieniędzy z innych sektorów bez zmiany podziału. '
    'Nie używaj repeat_previous=true, gdy has_previous=false. '
    'Dopiero po ocenie poprawnego podglądu użyj game_finance.approve:POST z rationale (minimum 20 znaków) opisującym faktyczne skutki. '
    'Przy świadomie wybranych wypłatach niższych od oczekiwań podaj accept_social_shortfall=true; przy spadku dochodów accept_revenue_decline=true. '
    'To nie pozwala przekroczyć dostępnych środków. Radykalne obniżki podatków są dozwolone, ale uzasadnij strategię i jej finansowanie. '
    'approved=true albo completed_goal oznacza, że budżet bieżącego półrocza JEST JUŻ ZATWIERDZONY: nie wywołuj ponownie preview ani approve w tym półroczu, przejdź do innych spraw państwa. '
    'Token, okres i sesję przygotowuje ZEUS; nie generuj ich. Błąd nie oznacza sukcesu: popraw decyzję; identyczne odrzucone próby są blokowane. '
    'Nie twierdź, że coś wykonano, bez potwierdzenia wyniku. Zwracaj wyłącznie JSON operation_id,path,data,memory.'
)
