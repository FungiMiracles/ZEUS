"""Decision contracts for the hybrid runner, distinct from native player form envelopes.

Money fields explicitly end in _mld; ids, counts and percentage rates are never rescaled.
Native player validators remain authoritative for ownership, available funds and game rules.
"""
from decimal import Decimal,localcontext
from game.budget_categories import CODES

ID={'type':'integer','minimum':1}
COUNT={'type':'integer','minimum':1}
MLD={'type':'number','exclusiveMinimum':0}
RATE={'type':'number','minimum':0,'maximum':100}
SECTOR={'type':'string','enum':list(CODES)}


def obj(properties,required):
    return {'type':'object','properties':properties,'required':required,'additionalProperties':False}


def schema(operation,provider=None):
    if operation=='game_finance.transfer:POST':
        return obj({'source':SECTOR,'destination':SECTOR,'amount_mld':MLD},['source','destination','amount_mld'])
    if operation in ('game_forum.page:POST','game_messages.send:POST'):
        # AI texts stay well inside one answer (640 tokens); the game itself allows 1000/3000 characters.
        properties={'content':{'type':'string','minLength':1,'maxLength':500 if 'forum' in operation else 600},'reply_to_id':ID,'recipient_id':ID}
        if 'forum' in operation:
            properties['recipient_id']={'type':['integer','array'],'minimum':1,'items':ID}
            return obj(properties,['content'])
        # Replies may omit the recipient: the existing adapter resolves the sender of our own received message.
        return {'anyOf':[obj(properties,['content','recipient_id']),obj({k:v for k,v in properties.items() if k!='recipient_id'},['content','reply_to_id'])]}
    if operation=='game_research.change:POST':
        from game.industry_catalog import TECHNOLOGIES
        return {'anyOf':[
            obj({'action':{'type':'string','enum':['buy']},'count':COUNT},['action','count']),
            obj({'action':{'type':'string','enum':['invest']},'node':{'type':'string','enum':list(TECHNOLOGIES)},'count':COUNT},['action','node','count']),
            obj({'action':{'type':'string','enum':['factory']},'region_id':ID,'x':{'type':'number'},'y':{'type':'number'}},['action','region_id','x','y'])]}
    if operation=='game_loans.change:POST':
        request=obj({'action':{'type':'string','enum':['request']},'lender_id':ID,'amount_mld':MLD},['action','lender_id','amount_mld'])
        # PAGA MULTI-AI: incoming requests are decided only by the financial model (Qwen), which can do nothing else.
        if provider=='qwen':return obj({'action':{'type':'string','enum':['accept','reject']},'loan_id':ID,'funding_category':SECTOR},['action','loan_id'])
        actions=['cancel','repay'] if provider in ('gemini','groq') else ['accept','reject','cancel','repay']
        settle=obj({'action':{'type':'string','enum':actions},'loan_id':ID,'funding_category':SECTOR},['action','loan_id'])
        return {'anyOf':[request,settle]}
    if operation=='game_trade.change:POST':
        from services.natural_resources import RESOURCES
        cargo=obj({code:{'type':'integer','minimum':0} for code,_ in RESOURCES},[])
        return {'anyOf':[
            obj({'action':{'type':'string','enum':['offer']},'cargo':cargo,'price_mld':MLD,'port_id':ID,'departure_rate':RATE,'excluded':{'type':'array','items':ID}},['action','cargo','price_mld','port_id','departure_rate']),
            obj({'action':{'type':'string','enum':['buy']},'offer_id':ID,'port_id':ID,'arrival_rate':RATE},['action','offer_id','port_id','arrival_rate']),
            obj({'action':{'type':'string','enum':['cancel']},'offer_id':ID},['action','offer_id']),
            obj({'action':{'type':'string','enum':['tariff']},'rate':RATE},['action','rate']),
            obj({'action':{'type':'string','enum':['port_access']},'block_foreign':{'type':'boolean'},'blocked_countries':{'type':'array','items':ID}},['action','block_foreign','blocked_countries'])]}
    return None


def validate(value,contract):
    """Validate the runner contract too, even when a caller bypasses the model's grammar."""
    from game.paga_ai_executor import check_schema
    if 'anyOf' in contract:
        errors=[]
        for variant in contract['anyOf']:
            try:validate(value,variant);return
            except (ValueError,TypeError) as error:errors.append(str(error))
        raise ValueError('Niekompletna lub nieprawidłowa dyspozycja: '+' / '.join(dict.fromkeys(errors))[:450])
    check_schema(value,contract)
    if isinstance(value,dict):
        for key,item in value.items():validate(item,contract.get('properties',{}).get(key,{}))
    elif isinstance(value,list):
        for item in value:validate(item,contract.get('items',{}))
    elif isinstance(value,str):
        if len(value.strip())<contract.get('minLength',0):raise ValueError('content: wymagana jest niepusta treść wiadomości.')
        if len(value)>contract.get('maxLength',10000):raise ValueError('Tekst przekracza dozwoloną długość.')
    elif type(value) in (int,float):
        if 'minimum' in contract and value<contract['minimum']:raise ValueError('Wartość mniejsza od dozwolonej.')
        if 'exclusiveMinimum' in contract and value<=contract['exclusiveMinimum']:raise ValueError('Kwota MLD musi być dodatnia.')
        if 'maximum' in contract and value>contract['maximum']:raise ValueError('Wartość przekracza limit.')


def native_data(operation,data):
    """Convert only declared monetary decisions; refuse sub-cent amounts, never round a decision silently."""
    contract=schema(operation)
    if contract is not None:validate(data,contract)
    payload=dict(data)
    with localcontext() as context:
        context.prec=64
        for decision_field,native_field in (('amount_mld','amount'),('price_mld','price')):
            if decision_field not in payload:continue
            amount=Decimal(str(payload.pop(decision_field)))*1000000000
            if amount!=amount.quantize(Decimal('.01')):raise ValueError('Kwota po przeliczeniu MLD musi mieć dokładność do grosza.')
            payload[native_field]=format(amount,'.2f')
    if operation=='game_trade.change:POST':
        for key in ('departure_rate','arrival_rate','rate'):
            if key in payload:payload[key]=str(payload[key])
    return payload


def fields(contract):
    """Short accurate field list for the model; grammar provides action-specific requirements."""
    if 'anyOf' in contract:
        return ' | '.join(fields(variant) for variant in contract['anyOf'])
    properties=contract.get('properties',{});required=set(contract.get('required',[]))
    return ','.join(key+('*' if key in required else '') for key in properties)
