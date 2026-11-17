"""PAGA Context Builder: a compact JSON per decision.

Information access: everything the model sees about the game comes from the AI identity's own *player routes*
(executor GETs with the ordinary permissions) or from the country's own notifications/tasks. No direct ORM data
about other countries is put in front of the model.
Money in decision contexts is shown in MLD (10^9), rounded; the adapter converts back exactly for game routes.
"""
import json,re,time
from decimal import Decimal,ROUND_HALF_UP
from game.paga_ai_tasks import KINDS,PRIORITY_NAME

BILLION=Decimal(1000000000)
# Prompt budget (4096-token window, ≤512 output). Real UAT data is dense (≈2.6 chars/token, measured 2026-11-09:
# a 4123-token request was rejected), so: system ≈3.3k chars + user ≤4.6k chars ≈ ≤3.1k tokens.
DATA_BUDGET=2400          # characters of game data per call
READ_BUDGET=1200          # characters per single read
RESEARCH_BUDGET=1500      # available technologies with exact codes (the model invented 'research_lab_1a')
MILITARY_BUDGET=1800      # the military facts (own bases, defenses, regions, enemy targets) are the core of a war decision
WAR_KINDS=('war_declared','under_attack','military_loss','plan_result','military_report')
USER_BUDGET=4600          # whole user context (checked by tests)
TIGHT_BUDGET=3000         # retry size when the model server still reports an oversized prompt
LONG_DECIMAL=re.compile(r'^-?\d+\.\d{3,}$')

# Which player screens give the facts for each domain, and which decisions belong to it.
DOMAINS={
    'finance':{'reads':['game_finance.page:GET'],'more':['game_loans.state:GET','game_finance.budget_history:GET'],
               'writes':['budget.plan','game_finance.transfer:POST','game_loans.change:POST']},
    'economy':{'reads':['game_infrastructure.industry_state:GET','game_research.state:GET'],
               'more':['game_trade.state:GET','game_trade.mine_state:GET','game_infrastructure.page:GET'],
               'writes':['game_infrastructure.industry_change:POST','game_infrastructure.expand:POST','game_research.change:POST','game_trade.change:POST','game_trade.mining_build:POST']},
    # PAGA2 (11 Nov 2026): odpowiedzi na forum i w wiadomościach nie zmieniają stosunków — tym zajmuje się algorytm PAGA2.
    'communication':{'reads':['game_messages.addressees:GET'],'more':['game_messages.index:GET','game_forum.page:GET','game_diplomacy.page:GET'],
                     'writes':['game_messages.send:POST','game_forum.page:POST']},
    'communication_legacy':{'reads':['game_messages.addressees:GET'],'more':['game_messages.index:GET','game_forum.page:GET','game_diplomacy.page:GET'],
                     'writes':['game_messages.send:POST','game_forum.page:POST','game_diplomacy.create_action:POST']},
    'diplomacy':{'reads':['game_diplomacy.page:GET','game_messages.addressees:GET'],'more':['game_diplomacy.world_news:GET','game_player.events:GET','game_messages.index:GET'],
                 'writes':['game_diplomacy.create_action:POST','game_diplomacy.decide:POST','game_forum.page:POST','game_messages.send:POST']},
    'military':{'reads':['game_military.defense_page:GET','game_messages.addressees:GET'],'more':['game_military.war_page:GET','game_army.page:GET','game_player.events:GET'],
                'writes':['game_military.war_order:POST','game_military.defense_change:POST','game_diplomacy.create_action:POST','game_forum.page:POST','game_messages.send:POST','plan.conditional','plan.cancel']},
    'intelligence':{'reads':['game_intelligence.state:GET'],'more':['game_intelligence.report:GET','game_player.events:GET'],
                    'writes':['game_intelligence.change:POST','game_forum.page:POST','game_messages.send:POST']},
    # PAGA MULTI-AI financial model (Qwen): incoming loan requests only.
    'loans':{'reads':['game_loans.state:GET'],'more':[],'writes':['game_loans.change:POST']},
    'strategy':{'reads':['game_finance.page:GET','game_diplomacy.page:GET'],
                'more':['game_military.defense_page:GET','game_military.war_page:GET','game_messages.addressees:GET','game_infrastructure.industry_state:GET','game_research.state:GET','game_intelligence.state:GET','game_trade.state:GET','game_messages.index:GET','game_player.events:GET'],
                'writes':['budget.plan','game_finance.transfer:POST','game_loans.change:POST','game_infrastructure.industry_change:POST','game_infrastructure.expand:POST',
                          'game_research.change:POST','game_trade.change:POST','game_trade.mining_build:POST',
                          'game_diplomacy.create_action:POST','game_diplomacy.decide:POST','game_forum.page:POST','game_messages.send:POST',
                          'game_military.war_order:POST','game_military.defense_change:POST','game_intelligence.change:POST','plan.conditional','plan.cancel']},
}
# Required fields per action, taken from the game services (military_service, missile_defense, military_navy,
# industry_service, intelligence_service, research_service, trade_service, loans, diplomacy_service).
# Object ids (base_id, defense_id, vessel_id, object_id, agent_id …) must come from dane_gry: only own objects are valid.
ACTION_HELP={
    'game_military.defense_change:POST':{
        'deploy':'kind(land|air|naval|nuclear), region_id(z nasze_regiony), x, y, garrison{soldiers,tanks,armored,launchers,fighters,warships,submarines,warheads}; budowa zużywa surowce z magazynu: lądowa 21 kamienia + 16 żelaza, morska 28 + 18, powietrzna 20 + 12 (silos bez surowców); liczba baz nie jest limitowana',
        'place':'kind, region_id(własny), count','garrison':'base_id, garrison{…}','location':'base_id, x, y','rename':'base_id, name',
        'upgrade':'base_id','withdraw':'base_id','sail':'base_id, vessel_kind(warships|submarines), x, y','return_vessel':'vessel_id, base_id','rename_vessel':'vessel_id, name',
        'defense_place':'target_kind(region|city|base|mine|factory|power), target_id (własny obiekt bez obrony)','defense_upgrade':'defense_id (istniejąca obrona)','defense_refill':'defense_id, ammunition','defense_repair':'defense_id, count(% życia)'},
    'game_military.war_order:POST':{
        'land':'kind=land, region_id(cel), soldiers/tanks/armored, source_base_id','air':'kind=air, region_id, fighters/drones, source_base_id, cel: city_id|target_*_id|infrastructure',
        'missile':'kind=missile, region_id, missile_type, missiles, source_base_id, cel: city_id|target_*_id|infrastructure','naval':'kind=naval, region_id, vessel_id lub okręty, cel'},
    'game_infrastructure.industry_change:POST':{'build':'category, kind, region_id(własny), x, y','upgrade':'category, object_id','repair':'category, object_id','pause':'category, object_id','resume':'category, object_id','remove':'category, object_id','filter':'category(power), object_id (elektrownia węglowa bez filtra; wymaga technologii air_filters; płatne z budżetu environment)','waste_filter':'category(factory), object_id (fabryka bez filtra; wymaga technologii waste_filters; płatne z budżetu environment)'},
    'game_intelligence.change:POST':{'recruit':'level, count','mission':'kind, agent_id, region_id','counter_upgrade':'(ZEUS uzupełnia poziom)','rename':'agent_id, name'},
    'game_research.change:POST':{'buy':'count (cenę uzupełnia ZEUS)','invest':'node(z kodów technologii), count','factory':'region_id(własny), x, y'},
    'game_finance.transfer:POST':{'transfer':'source, destination(kody kategorii), amount_mld; ZEUS ustala bieżący budget_id; między sektorami (bez reserve) tylko przy zaufaniu do władzy > 65'},
    'game_forum.page:POST':{'post':'content(obowiązkowe 1–1000 znaków), reply_to_id lub recipient_id opcjonalne'},
    'game_messages.send:POST':{'send':'content(obowiązkowe), recipient_id albo reply_to_id własnej otrzymanej wiadomości'},
    'game_loans.change:POST':{'request':'lender_id, amount_mld','accept':'loan_id','reject':'loan_id','cancel':'loan_id','repay':'loan_id'},
    'game_diplomacy.create_action:POST':{'RELATION':'kind=RELATION, target_id, relation_id','WAR':'kind=WAR, target_id (wymaga wcześniej wrogiej relacji)','PEACE':'kind=PEACE, target_id (podczas wojny)','CEASEFIRE':'kind=CEASEFIRE, target_id, days (1–180 dni Entendy; podczas wojny)'},
}

def action_help(names):
    return {name:ACTION_HELP[name] for name in names if name in ACTION_HELP}

# Administrator decision (10 Nov 2026): PAGA AI does not build or decide about roads and does not consider
# Event Generator news. Enforced here and again in the runner (never offered, never executed).
EXCLUDED_OPERATIONS={'game_infrastructure.roads_change:POST','game_infrastructure.roads_state:GET','game_public.events:GET'}
assert not any(name in EXCLUDED_OPERATIONS for spec in DOMAINS.values() for name in (*spec['reads'],*spec['more'],*spec['writes']))

# Strategic self-management is available in every task: the model can always record goals and intentions.
COMMON=['goal.create','goal.update','intent.create']

# Object-specific screen for reactive tasks (the very message/event that caused the task).
def object_read(task):
    ref=task.object_ref
    if task.kind=='private_message' and ref:return ('game_messages.detail:GET',{'message_id':int(ref)},{})
    if task.kind in ('forum_reply','forum_mention') and ref:return ('game_forum.page:GET',{},{'reply_to_id':int(ref)})
    if task.kind=='loan_event':return ('game_loans.state:GET',{},{})
    return None


def research_view(result):
    """game_research.state (player route) -> what can be decided now: points, price, technologies open to investment
    with their exact codes, and those already developed. UAT 10 Nov 2026: invented codes such as research_lab_1a."""
    if not isinstance(result,dict) or 'nodes' not in result:return result
    technologies=result.get('technologies') or {};nodes=result.get('nodes') or {}
    def developed(code):return (nodes.get(code) or {}).get('level',0)>=1
    available=[];done=[]
    for code,node in nodes.items():
        info=technologies.get(code) or {}
        if info.get('available') is False:continue          # planned, not playable yet
        if developed(code):done.append(code)
        if node.get('maximum'):continue
        parent=info.get('parent')
        if parent and not developed(parent):continue
        available.append({'node':code,'nazwa':info.get('label'),'brakuje_punktów':max(0,(node.get('required') or 0)-(node.get('progress') or 0))})
    available.sort(key=lambda item:item['brakuje_punktów'])
    points=result.get('points') or 0
    return {'nasze_punkty_rozwoju':points,'cena_punktu_mld':to_mld(result.get('pointPrice') or 0),'budżet_badań_mld':to_mld(result.get('budget') or 0),
            'technologie_do_inwestycji':available[:12],'opracowane':done[:20],
            'jak_działa':'buy: count = liczba kupowanych punktów (koszt count × cena_punktu_mld z budżetu badań). '
                         'invest: node = kod z technologie_do_inwestycji, count = punkty z nasze_punkty_rozwoju, najwyżej brakuje_punktów.'
                         +(' Mamy 0 punktów: najpierw buy.' if not points else '')}


LOAN_STATUS={'pending':'oczekuje na decyzję','accepted':'zaakceptowana (środki przekazane)','rejected':'odrzucona','cancelled':'wycofana','repaid':'spłacona'}

def loans_view(result):
    """game_loans.state (player route) -> unambiguous loan cases: number, direction, amount in MLD, our possible decisions."""
    if not isinstance(result,dict) or 'loans' not in result:return result
    own=result.get('countryId');cases=[]
    for loan in result.get('loans') or []:
        lender=loan.get('lenderId')==own;status=loan.get('status')
        if lender:
            direction=f"{loan.get('borrower')} prosi NASZE państwo o pożyczkę (to my pożyczylibyśmy pieniądze)"
            decisions=['accept','reject'] if status=='pending' else []
        else:
            direction=f"NASZE państwo prosi {loan.get('lender')} o pożyczkę (to my bylibyśmy dłużnikiem)"
            decisions=['cancel'] if status=='pending' else ['repay'] if status=='accepted' else []
        case={'loan_id':loan.get('id'),'kierunek':direction,'kwota_mld':to_mld(loan.get('amount') or 0),'status':LOAN_STATUS.get(status,status),
              'nasze_możliwe_decyzje':decisions}
        if lender and status=='pending':case['brak_naszej_rezerwy_mld']=to_mld(loan.get('gap') or 0)
        cases.append(case)
    cases.sort(key=lambda case:(not case['nasze_możliwe_decyzje'],-(case['loan_id'] or 0)))
    return {'nasza_rezerwa_mld':to_mld(result.get('reserve') or 0),'pożyczki':cases[:8],
            'jak_zdecydować':'game_loans.change:POST z data.action (accept/reject/cancel/repay) i data.loan_id z tej listy.'}


def to_mld(value,digits=2):
    try:return float((Decimal(str(value))/BILLION).quantize(Decimal(1).scaleb(-digits),rounding=ROUND_HALF_UP))
    except Exception:return None


def finance_view(result):
    """game_finance.page:GET (player route) -> decision facts in MLD. Exact numbers stay in the game."""
    if not isinstance(result,dict):return result
    state=result.get('state') or {}
    if not state:return {'error':result.get('error')}
    benefits=state.get('benefits') or {};expected=benefits.get('expected') or {};paid=benefits.get('paid') or {}
    allocations=state.get('allocations') or {}
    total_expected=sum((Decimal(str(value)) for value in expected.values()),Decimal(0))
    total_paid=sum((Decimal(str(value)) for value in paid.values()),Decimal(0))
    view={'okres':f"{state.get('year')}/{state.get('period')}",'budżet_zatwierdzony':bool(state.get('approved')),
          'budget_id':state.get('budget_id'),'ma_poprzedni_budżet':state.get('has_previous'),
          'pit_rate_percent':state.get('pit_rate'),
          'half_year_tax_revenue_mld':to_mld(state.get('tax_total') or 0),'budget_total_mld':to_mld(state.get('budget_total') or 0),
          'opening_reserve_mld':to_mld(state.get('opening_reserve') or 0),'closing_reserve_mld':to_mld(state.get('closing_reserve') or 0),
          'shares_percent':{key:value for key,value in (state.get('shares') or {}).items() if Decimal(str(value or 0))},
          'allocations_mld':{key:to_mld(value) for key,value in allocations.items() if Decimal(str(value or 0))},
          'social_policy_allocation_mld':to_mld(allocations.get('social_policy') or 0),
          'expected_children_benefits_mld':to_mld(expected.get('children') or 0),'expected_seniors_benefits_mld':to_mld(expected.get('seniors') or 0),
          'carry_in_mld':to_mld(benefits.get('carry_in') or 0),'tax_penalty':state.get('tax_penalty'),
          'kategorie_budżetu':[row.get('code') if isinstance(row,dict) else row for row in result.get('categories') or []]}
    if state.get('balances'):
        view['available_by_sector_mld']={key:to_mld(row.get('remaining') or 0) for key,row in state['balances'].items()}
        view['przesunięcia_możliwe']=bool(state.get('can_transfer'))
        if state.get('can_transfer') and not state.get('sector_transfers_allowed',True):
            view['przesunięcia_między_sektorami']=f"zablokowane: zaufanie do władzy {state.get('public_trust')} ≤ {state.get('transfer_trust_threshold')}; możliwe tylko operacje z rezerwą (reserve)"
    if paid:
        view['paid_children_benefits_mld']=to_mld(paid.get('children') or 0);view['paid_seniors_benefits_mld']=to_mld(paid.get('seniors') or 0)
        view['benefits_coverage_percent']=float((total_paid*100/total_expected).quantize(Decimal('0.1'))) if total_expected else None
    if state.get('approved'):view['uwaga']='Budżet tego okresu jest zatwierdzony. Nie zatwierdzaj go ponownie.'
    return {key:value for key,value in view.items() if value not in (None,{},[])}


def preview_view(result):
    """Adapter result of a budget preview -> MLD + coverage, for the model to judge its own plan."""
    plan=(result or {}).get('plan') or {}
    check=(result or {}).get('social_expectations_check') or {}
    expected=Decimal(str(check.get('expected') or 0));planned=Decimal(str(check.get('planned_paid') or 0))
    return {'pit_rate_percent':plan.get('pit_rate'),'shares_percent':{k:v for k,v in (plan.get('shares') or {}).items() if Decimal(str(v or 0))},
            'half_year_tax_revenue_mld':to_mld(plan.get('tax_total') or 0),'budget_total_mld':to_mld(plan.get('budget_total') or 0),
            'social_policy_available_mld':to_mld(check.get('allocated') or 0),'benefits_expected_mld':to_mld(expected),'benefits_planned_mld':to_mld(planned),
            'benefits_coverage_percent':float((planned*100/expected).quantize(Decimal('0.1'))) if expected else None,
            'unfunded_payments_mld':to_mld(check.get('unfunded_planned_payments') or 0),
            'change_in_tax_revenue_mld':to_mld((result or {}).get('change_in_tax_revenue') or 0) if (result or {}).get('change_in_tax_revenue') is not None else None,
            'social_policy_share_needed_percent':float(Decimal(str((((result or {}).get('benefit_affordability') or {}).get('minimum_social_share_percent_for_these_payments')) or 0))) if ((result or {}).get('benefit_affordability') or {}).get('minimum_social_share_percent_for_these_payments') else None}


def budget_options(view):
    """Ways out of an unaffordable benefit plan, computed by ZEUS; the model chooses one (or another plan)."""
    available=view.get('social_policy_available_mld');planned=view.get('benefits_planned_mld');needed=view.get('social_policy_share_needed_percent')
    if available is None or planned is None or planned<=available:return None
    options=[f"1) Zwiększ udział social_policy do ≥{needed}%, by wypłacić {planned} MLD." if needed else None,
             f"2) Albo wypłać łącznie ≤{available} MLD (z accept_social_shortfall=true).",
             "3) Albo benefit_policy=available_proportional (wypłata w granicach social_policy).",
             "Akceptacja niedoboru nie pozwala wypłacić więcej niż środki social_policy."]
    return ' '.join(item for item in options if item)   # one text: list compaction must never drop a way out


def compact(value,*,depth=0,list_limit=12):
    """Shrink a player-route projection: drop navigation/forms, round long decimals, cap lists and texts."""
    if depth>8:return '…'
    if isinstance(value,dict):
        result={}
        for key,item in value.items():
            if key in ('forms','actions','guidance','correction','next','options','meaning','repeat_note','units','flag','href'):continue
            result[key]=compact(item,depth=depth+1,list_limit=list_limit)
        return result
    if isinstance(value,list):
        items=[compact(item,depth=depth+1,list_limit=list_limit) for item in value[:list_limit]]
        if len(value)>list_limit:items.append(f'… oraz {len(value)-list_limit} kolejnych')
        return items
    if isinstance(value,float):return round(value,2)
    if isinstance(value,str):
        if LONG_DECIMAL.match(value):return str(round(float(value),2))
        return value if len(value)<=400 else value[:400]+'…'
    return value


def fit(value,budget):
    """Reduce list sizes until the JSON fits; as a last resort cut text (marked)."""
    for limit in (12,6,3,1):
        shrunk=compact(value,list_limit=limit);text=json.dumps(shrunk,ensure_ascii=False,default=str)
        if len(text)<=budget:return shrunk
    return {'skrót':text[:budget-40]+'…','uwaga':'dane skrócone; użyj read po szczegóły'}


def money_view(operation,result):
    """Label only verified currency fields in MLD; never touch ids, quantities or research-point costs."""
    known={
        'game_research.state:GET':{'budget','infrastructureBudget','pointPrice','factoryPrice'},
        'game_trade.state:GET':{'reserve','price','departureFee','arrivalFee'},
        'game_trade.mine_state:GET':{'budgetTotal','budgetAvailable','cost'},
        'game_infrastructure.industry_state:GET':{'budget','cost','costs','repairCost','upgradeCost','filterCost','upgradeFilterCost','wasteFilterCost'},
        'game_intelligence.state:GET':{'budgetTotal','budgetAvailable','counterCost'},
    }.get(operation,set())
    def project(value,depth=0):
        if isinstance(value,list):return [project(item,depth+1) for item in value]
        if not isinstance(value,dict):return value
        output={}
        for key,item in value.items():
            if key in known and (operation!='game_research.state:GET' or depth==0):
                output[key+'_mld']=[to_mld(v,digits=11) for v in item] if isinstance(item,list) else to_mld(item,digits=11)
            else:output[key]=project(item,depth+1)
        return output
    return project(result)


def read(app,actor,operation,path=None,data=None,*,step,model_id):
    """One player-route read as the AI identity; returns the decoded, compact result."""
    from game.paga_ai_executor import execute
    response=execute(app,actor,{'operation_id':operation,'path':path or {},'data':data or {}},step=step,model_id=model_id)
    try:
        if (response.get('observation') or {}).get('next_offset') is not None:raise ValueError('truncated window')
        body=json.loads(response['observation']['text'])
    except (ValueError,KeyError,TypeError):
        # A long answer does not fit the observation window: use the complete (scrubbed) audited result instead.
        from game.paga_ai_runner import audit_result
        full=audit_result(response.get('audit_id'))
        body={'result':full} if full else {'error':'Nie udało się odczytać danych.'}
    result=body.get('result') if isinstance(body,dict) else body
    if response['status']>=400:return {'error':str((result or {}).get('error') if isinstance(result,dict) else result)[:300]}
    if operation=='game_finance.page:GET':return finance_view(result)
    if operation=='game_loans.state:GET':return fit(loans_view(result),READ_BUDGET)
    if operation=='game_research.state:GET':return fit(research_view(result),RESEARCH_BUDGET)
    if operation in ('game_military.defense_page:GET','game_military.war_page:GET'):
        from game.paga_ai_military import military_view
        return fit(military_view(result),MILITARY_BUDGET)
    if operation=='game_messages.addressees:GET':
        from game.paga_ai_military import addressees_view
        return fit(addressees_view(result),READ_BUDGET)
    return fit(money_view(operation,result),READ_BUDGET)


def operations_view(app,names):
    """Compact list of possible decisions: id -> parameter names (the grammar enforces exact shapes)."""
    from game.player_operations import catalogue
    from game.paga_ai_strategy import VIRTUAL
    catalog=catalogue(app);result={}
    for name in names:
        if name in VIRTUAL:result[name]=VIRTUAL[name]['hint']
        elif name in catalog:
            op=catalog[name];properties=op.input_schema.get('properties',{})
            # Names only: the decision grammar enforces exact shapes and allowed values.
            path=list((op.path_schema.get('properties') or {}))
            from game.paga_ai_contracts import schema as contract_schema,fields
            contract=contract_schema(name)
            if contract is not None:
                result[name]=fields(contract);continue
            result[name]=('path:'+','.join(path)+'; ' if path else '')+','.join(properties)
    return result


def reply_reference(session,task,identity):
    """Exact parameters for answering the message that caused the task (UAT 9 Nov 2026: replies went to a wrong id).
    The message is the one in this country's own inbox; its text is given separately as untrusted data."""
    ref=task.object_ref
    if task.kind=='private_initiative':ref=ref or '0'
    if not ref or not str(ref).isdigit():return None,None
    if task.kind in ('forum_reply','forum_mention'):
        from game.forum_models import ForumMessage
        message=session.get(ForumMessage,int(ref))
        if message is None:return None,None
        return ({'operacja':'game_forum.page:POST','data':{'reply_to_id':message.id},'autor':message.country_name,
                 'uwaga':'Użyj dokładnie tego reply_to_id; autor wpisu zostanie dodany jako adresat automatycznie.'},
                {'wpis_id':message.id,'autor':message.country_name,'treść':message.content[:600]})
    if task.kind=='private_initiative' and (task.context or {}).get('recipient_user_id'):
        context=task.context
        return ({'operacja':'game_messages.send:POST','data':{'recipient_id':context['recipient_user_id']},'adresat':context.get('target_country_name'),
                 'uwaga':'Napisz nową wiadomość (bez reply_to_id) dokładnie do tego recipient_id.'},None)
    if task.kind=='private_message':
        from game.communication_models import PrivateMessage
        message=session.get(PrivateMessage,int(ref))
        if message is None or identity is None or message.recipient_user_id!=identity.user_id:return None,None
        return ({'operacja':'game_messages.send:POST','data':{'reply_to_id':message.id,'recipient_id':message.sender_user_id},'autor':message.sender_country_name,
                 'uwaga':'Użyj dokładnie tych reply_to_id i recipient_id.'},
                {'wiadomość_id':message.id,'autor':message.sender_country_name,'treść':message.content[:600]})
    return None,None


def interlocutor(session,task):
    """Państwo, do którego model mówi: autor wpisu, nadawca wiadomości albo adresat inicjatywy PAGA2."""
    if (task.context or {}).get('target_country_id'):return (task.context or {})['target_country_id']
    ref=task.object_ref
    if not ref or not str(ref).isdigit():return None
    if task.kind in ('forum_reply','forum_mention'):
        from game.forum_models import ForumMessage
        message=session.get(ForumMessage,int(ref));return message.panstwo_id if message else None
    if task.kind=='private_initiative' and (task.context or {}).get('recipient_user_id'):
        context=task.context
        return ({'operacja':'game_messages.send:POST','data':{'recipient_id':context['recipient_user_id']},'adresat':context.get('target_country_name'),
                 'uwaga':'Napisz nową wiadomość (bez reply_to_id) dokładnie do tego recipient_id.'},None)
    if task.kind=='private_message':
        from game.communication_models import PrivateMessage
        message=session.get(PrivateMessage,int(ref));return message.sender_country_id if message else None
    return None


def paga2_blocks(session,country_id,task,domain):
    try:
        from game.paga2.llm_context import policy,loan_limits
        now=_game_now()
        result={'policy':policy(session,country_id,now,other_id=interlocutor(session,task))}
        if domain=='loans' and result['policy'] is not None:result['loan']=loan_limits(session,country_id,now)
        return result
    except Exception:
        session.rollback();return {}


def build(app,actor,task,identity,config,country_name,*,feedback=None,step_base=100,model_id,tight=False,domain=None):
    """Assemble the decision context for one task. Returns (context_dict, allowed_operations, timing_ms)."""
    started=time.monotonic()
    from game.paga import TRAITS,INTERESTS
    from game.paga_relationships import country_preferences
    from game.paga_ai_strategy import goals_view,plans_view,strategy_notes
    from extensions import db
    from sqlalchemy.orm import Session
    domain=domain or KINDS.get(task.kind,KINDS['legacy'])['domain']
    spec=DOMAINS[domain]
    data={};step=step_base
    obj=object_read(task)
    if obj:
        step+=1;data['dotyczy']=read(app,actor,obj[0],obj[1],obj[2],step=step,model_id=model_id)
    for operation in spec['reads']:
        if operation=='game_military.defense_page:GET' and task.kind in WAR_KINDS:
            # In war the war panel adds land targets and known enemy objects; without war it is unavailable (falls back).
            step+=1;war=read(app,actor,'game_military.war_page:GET',step=step,model_id=model_id)
            if not (isinstance(war,dict) and set(war)=={'error'}):data['game_military.war_page']=war;continue
        step+=1;data[operation.split(':')[0]]=read(app,actor,operation,step=step,model_id=model_id)
    for operation,result in (feedback or {}).get('reads',{}).items():data[operation]=result
    data=fit(data,DATA_BUDGET)
    with Session(db.engine) as session:
        relations=country_preferences(session,actor.country_id)
        goals=goals_view(session,actor.country_id)
        plans=plans_view(session,actor.country_id)
        notes=strategy_notes(identity)
        answer,quoted=reply_reference(session,task,identity)
        from game.paga_ai_military import relation_choices
        relation_names=relation_choices(session) if 'game_diplomacy.create_action:POST' in spec['writes'] else {}
        # PAGA2 (11 Nov 2026): profil, sytuacja, decyzje i plany algorytmu — modele mówią zgodnie z jego polityką.
        paga2=paga2_blocks(session,actor.country_id,task,domain)
    # The loan model has no strategic operations (goals, intents): it only accepts or rejects requests.
    # Modele AI (komunikacja, pożyczki) nie tworzą celów ani zamiarów strategicznych: strategię prowadzi PAGA2.
    from game.paga_ai_tasks import legacy_engines
    if domain=='communication' and legacy_engines():spec=DOMAINS['communication_legacy']
    allowed=[*spec['writes'],*([] if domain=='loans' or (domain=='communication' and not legacy_engines()) else COMMON),'no_action']
    context={
        'zadanie':{'rodzaj':task.kind,'priorytet':PRIORITY_NAME.get(task.priority,'NORMAL'),'źródło':task.source,
                   'cel_zadania':goal_text(task),'szczegóły':untrusted_context({**(task.context or {}),**({'otrzymana_treść':quoted} if quoted else {})}),
                   **({'jak_odpowiedzieć':answer} if answer else {})},
        'własne_państwo':{'id':actor.country_id,'nazwa':country_name,'data_Entendy':str(_game_now())[:16],
                   **({'polityka_PAGA2':paga2['policy']} if paga2.get('policy') else
                      {'charakter_PAGA':{TRAITS[key]:value for key,value in (getattr(config,'approved_character',None) or {}).items() if key in TRAITS},
                       'interesy_od_najważniejszego':[INTERESTS[row['key']] for row in getattr(config,'approved_interests',None) or [] if row.get('active') and row.get('key') in INTERESTS]}),
                   'powiązania_historyczne_PAGA':relations},
        **({'granice_pożyczki':paga2['loan']} if paga2.get('loan') else {}),
        'cele_strategiczne':goals,'plany':plans,
        'pamięć_strategiczna_niezaufana':notes,
        'przebieg_zadania':list(task.journal or [])[-8:],
        'dane_gry':data,
        'możliwe_działania':operations_view(app,allowed),
        **({'relacje_dyplomatyczne':{str(id):name for id,name in relation_names.items()}} if relation_names else {}),
        'wymagane_pola':action_help(allowed),
        'dodatkowe_odczyty':spec['more'],
    }
    # The correction is the core of a retry: larger budget than other data (the whole context stays bounded below).
    if feedback and feedback.get('problems'):context['wymaga_korekty']=fit(feedback['problems'],1600)
    # Final guard: shrink game data further if the whole context would not fit the model window.
    def size():return len(json.dumps(context,ensure_ascii=False,default=str))
    limit=TIGHT_BUDGET if tight else USER_BUDGET
    if tight:
        context['przebieg_zadania']=context['przebieg_zadania'][-3:];context['pamięć_strategiczna_niezaufana']={'notatki':notes.get('notatki',[])[-2:]}
        context['cele_strategiczne']=[{key:goal[key] for key in ('id','tytuł','priorytet','status')} for goal in goals]
    if size()>limit:
        # The field cheat-sheet shrinks first to action names (full fields are always repeated with any error).
        context['wymagane_pola']={name:sorted(actions) for name,actions in context['wymagane_pola'].items()}
    for budget in (DATA_BUDGET,1600,1000):
        if size()<=limit:break
        context['dane_gry']=fit(context['dane_gry'],budget)
    if size()>limit:context.pop('wymagane_pola',None)  # repeated with any error, so the model still gets it when needed
    if size()>limit:context['możliwe_działania']=sorted(context['możliwe_działania'])  # grammar enforces exact parameters
    for budget in (600,300):
        if size()<=limit:break
        context['dane_gry']=fit(context['dane_gry'],budget)
    return context,allowed,int((time.monotonic()-started)*1000)


def _game_now():
    import game.finance_service as finance
    return finance.game_now()


GOALS={
    'strategic_review':'Okresowy przegląd strategiczny: oceń sytuację, swoje cele i postępy; kontynuuj, zmień priorytety albo zainicjuj nowe działania w dowolnym obszarze. Bezczynność jest dozwolona, jeśli świadomie ją wybierasz.',
    'budget':'Przygotuj i zatwierdź budżet bieżącego okresu (kwartału) jedną decyzją budget.plan.',
    'private_message':'Otrzymano wiadomość prywatną: zdecyduj, czy i jak odpowiedzieć lub działać.',
    'forum_reply':'Wpis na forum skierowany do nas lub odpowiedź na nasz wpis: zdecyduj o reakcji.',
    'forum_mention':'Nasze państwo zostało wspomniane na forum: zdecyduj, czy zająć stanowisko.',
    'diplomatic_proposal':'Otrzymano propozycję dyplomatyczną: przyjmij, odrzuć albo działaj inaczej.',
    'war_declared':'Wypowiedziano wojnę z udziałem naszego państwa: zdecyduj o reakcji.',
    'under_attack':'Nasze państwo zostało zaatakowane: zdecyduj o obronie, odwecie lub dyplomacji.',
    'military_loss':'Utraciliśmy siły lub obiekty wojskowe: oceń sytuację i zdecyduj.',
    'loan_event':'Sprawa pożyczki: w dane_gry.dotyczy jest numer pożyczki (loan_id), kierunek, kwota i nasze możliwe decyzje. Zdecyduj, czy i jak działać.',
    'forum_announcement':'Opublikuj na forum międzynarodowym wpis o wydarzeniu opisanym w szczegółach, zgodny z polityką PAGA2 państwa.',
    'private_initiative':'Napisz wiadomość prywatną do wskazanego państwa w sprawie opisanej w szczegółach, zgodną z polityką PAGA2 państwa.',
}

def goal_text(task):
    return (task.context or {}).get('cel') or GOALS.get(task.kind) or 'Oceń zdarzenie i zdecyduj, czy wymaga działania.'


def untrusted_context(context):
    """Task details may quote other players (notifications, messages): marked as data, trimmed, never instructions."""
    if not context:return {}
    clean={key:value for key,value in context.items() if key not in ('cel',)}
    return fit(clean,900)
