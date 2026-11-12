"""PAGA MULTI-AI (UAT, 10 Nov 2026): three models, one PAGA.

    Gemini Flash  — strategic model (budget, economy, infrastructure, armed forces, research, production, trade, goals)
    Groq          — operational-diplomatic model (messages, forum, international events, simpler decisions);
                    takes over Gemini's tasks when Gemini is unavailable (and vice versa, administrator decision)
    local Qwen    — incoming inter-state loan requests ONLY (accept / reject)

Every model goes through the same runner, context builder, shared country memory, guard and player routes;
no model touches the database. Keys come from the environment (.env.uat, loaded by systemd) at call time,
are sent only in request headers and are never stored, logged or returned (scrub()).
Only free-tier models are used (FREE_MODELS); a model outside the list is treated as unavailable, never paid for.
"""
import json,os,re,socket,time,urllib.error,urllib.request
from datetime import timedelta
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from extensions import db
from game.paga_ai_models import PagaAiMetric,PagaAiProvider,PagaAiJob
from game.paga_ai_tasks import now

TRUE={'1','true','yes','on','tak'}
LANES=('gemini','groq','qwen')
PROVIDERS={
    'gemini':{'label':'Gemini','switch':'PAGA_GEMINI_ENABLED','key':'GEMINI_API_KEY','model_env':'PAGA_GEMINI_MODEL','model':'gemini-3.8-flash',
              # The newest free Flash model is often overloaded (HTTP 503 "high demand", UAT 10 Nov 2026): one retry on this free model.
              'spare_env':'PAGA_GEMINI_SPARE_MODELS','spare':'gemini-3.6-flash,gemini-3.5-flash-lite',
              # Free-tier limits are shown only in AI Studio; conservative defaults, overridable per environment.
              'rpm':8,'rpd':200,'tpm':200000,'role':'model strategiczny'},
    'groq':{'label':'Groq','switch':'PAGA_GROQ_ENABLED','key':'GROQ_API_KEY','model_env':'PAGA_GROQ_MODEL','model':'openai/gpt-oss-120b',
            # GroqCloud table (Nov 2026): 30 RPM, 1K RPD, 8K TPM for this model; kept below the ceiling.
            'rpm':25,'rpd':900,'tpm':7000,'role':'model operacyjno-dyplomatyczny'},
    'qwen':{'label':'Qwen 3.5 4B','switch':'PAGA_QWEN_ENABLED','key':None,'model_env':None,'model':'Qwen3.5-4B-Q4_K_M','role':'model finansowy (pożyczki)'},
}
# Free-of-charge models only (provider pricing pages, Nov 2026). Nothing outside this list is ever called.
FREE_MODELS={'gemini':{'gemini-3.8-flash','gemini-3.6-flash','gemini-3.5-flash-lite','gemini-3.1-flash-lite','gemini-3-flash-preview','gemini-2.5-flash','gemini-2.5-flash-lite'},
             'groq':{'openai/gpt-oss-120b','openai/gpt-oss-20b','qwen/qwen3.8-27b'}}

# Task routing by kind. Everything not listed belongs to the strategic model.
GROQ_KINDS={'private_message','forum_reply','forum_mention','diplomatic_proposal','relation_change','alliance_change','world_event'}
QWEN_KINDS={'loan_event'}
NO_MODEL_KINDS={'conditional_plan'}      # pre-authorised plan: ZEUS executes it without a model call
FALLBACK={'gemini':'groq','groq':'gemini','qwen':None}
LOAN_DECISIONS={'accept','reject'}       # incoming loan requests: reserved for Qwen

ROLE_PROMPTS={
    'gemini':'Twoja rola w PAGA MULTI-AI: model strategiczny — budżet, decyzje gospodarcze, inwestycje infrastrukturalne, siły zbrojne, sytuacja międzynarodowa, '
             'cele krótko- i długoterminowe, badania, produkcja i handel. Wnioski innych państw o pożyczki rozpatruje osobny model — ty ich nie akceptujesz ani nie odrzucasz.',
    'groq':'Twoja rola w PAGA MULTI-AI: model operacyjno-dyplomatyczny — wiadomości dyplomatyczne, wpisy i odpowiedzi na forum, reakcje na wydarzenia międzynarodowe '
           'i prostsze decyzje operacyjne. Gdy przejmujesz zadanie modelu strategicznego, decyduj tak samo odpowiedzialnie. Wniosków o pożyczki nie rozpatrujesz.',
    'qwen':'Twoja rola w PAGA MULTI-AI: wyłącznie rozpatrujesz przychodzące wnioski innych państw o pożyczkę od naszego państwa — accept albo reject (albo no_action). '
           'Nie wykonujesz żadnych innych zadań zarządzania państwem.',
}


class ProviderUnavailable(RuntimeError):
    """The provider cannot take the call now (switched off, no key, network, 5xx, limit). The task is re-queued, not failed."""
    outcome='UNAVAILABLE'
    def __init__(self,message,retry_after=None,local=False):
        super().__init__(message);self.retry_after=retry_after;self.local=local


class RateLimited(ProviderUnavailable):
    outcome='RATE_LIMIT'


def flag(name,default=False):
    value=os.environ.get(name)
    if value is None:return default
    return value.strip().strip('"\'').lower() in TRUE


def writes_enabled():
    """PAGA_AUTONOMOUS_WRITES_ENABLED: state-changing game operations by any model. Missing = off (never self-activated)."""
    return flag('PAGA_AUTONOMOUS_WRITES_ENABLED',False)


def _number(name,default):
    try:return max(1,int(os.environ.get(name,default)))
    except (TypeError,ValueError):return default


def model_name(provider):
    spec=PROVIDERS[provider]
    return (os.environ.get(spec['model_env']) or spec['model']).strip() if spec['model_env'] else spec['model']


def spare_models(provider):
    """Free spare models tried in order when the main model is overloaded; anything outside FREE_MODELS is ignored."""
    spec=PROVIDERS[provider]
    if not spec.get('spare'):return []
    names=[name.strip() for name in (os.environ.get(spec['spare_env']) or spec['spare']).split(',')]
    return [name for name in dict.fromkeys(names) if name in FREE_MODELS.get(provider,()) and name!=model_name(provider)]


def model_key(provider,model):
    return f'{provider}:{model}'[:64]


def model_paused(session,provider,model,moment=None):
    """Per-model pause (Gemini free quotas are counted per model): the pause end or None."""
    row=session.get(PagaAiProvider,model_key(provider,model))
    return row.cooldown_until if row is not None and row.cooldown_until and row.cooldown_until>(moment or now()) else None


def active_models(provider):
    """Main and free spare models of a provider that are not paused now, in order of preference."""
    with Session(db.engine) as session:
        return [model for model in [model_name(provider),*spare_models(provider)] if not model_paused(session,provider,model)]


def compact_schema(schema):
    """Gemini rejects the full per-operation grammar as too complex (HTTP 400, UAT 10 Nov 2026). It gets the decision
    shape with operation_id limited to this task's operations; ZEUS validates every action's fields as before."""
    try:choices=schema['properties']['actions']['items']['anyOf']
    except (KeyError,TypeError):return schema
    operations=[choice['properties']['operation_id']['enum'][0] for choice in choices]
    free={'type':'object','additionalProperties':True}
    return {'type':'object','properties':{'ocena':{'type':'string'},'actions':{'type':'array','maxItems':schema['properties']['actions'].get('maxItems',3),
            'items':{'type':'object','properties':{'operation_id':{'type':'string','enum':operations},'path':free,'data':free},'required':['operation_id','data']}},
            'task_done':{'type':'boolean'},'memory':{'type':'string'}},'required':['ocena','actions','task_done']}


def limits(provider):
    spec=PROVIDERS[provider];prefix='PAGA_'+provider.upper()+'_'
    return {key:_number(prefix+key.upper(),spec[key]) for key in ('rpm','rpd','tpm')} if spec.get('rpm') else {}


def _key(provider):
    name=PROVIDERS[provider]['key']
    return (os.environ.get(name) or '').strip().strip('"\'') if name else None


def scrub(text):
    """Remove every configured API key from a text before it is stored or shown."""
    text=str(text or '')
    for provider in PROVIDERS:
        key=_key(provider)
        if key and len(key)>=8:text=text.replace(key,'***')
    return re.sub(r'(key=|Bearer\s+)[A-Za-z0-9_\-.]{12,}',r'\1***',text)


def availability(session,provider,moment=None):
    """(available, reason). Reason is shown to the administrator; never contains a key."""
    spec=PROVIDERS[provider];moment=moment or now()
    if not flag(spec['switch'],False):return False,f"{spec['label']} wyłączony ({spec['switch']})."
    if spec['key'] and not _key(provider):return False,f"{spec['label']}: brak klucza API ({spec['key']})."
    if provider in FREE_MODELS and model_name(provider) not in FREE_MODELS[provider]:
        return False,f"{spec['label']}: model {model_name(provider)} nie należy do bezpłatnego planu — nie jest używany."
    row=session.get(PagaAiProvider,provider)
    if row is not None and row.cooldown_until and row.cooldown_until>moment:
        return False,f"{spec['label']} niedostępny do {row.cooldown_until:%H:%M:%S} UTC: {row.last_error or 'limit'}"
    return True,None


def primary(kind):
    if kind in NO_MODEL_KINDS:return 'zeus'
    if kind in QWEN_KINDS:return 'qwen'
    if kind in GROQ_KINDS:return 'groq'
    return 'gemini'


def route(session,kind,moment=None,cache=None):
    """Which model takes this task now: (provider|None, handover dict|None, reason).
    Loans go to Qwen only; Gemini<->Groq hand over to each other; None = nobody can, the task waits in the queue."""
    cache={} if cache is None else cache
    def ok(provider):
        if provider not in cache:cache[provider]=availability(session,provider,moment)
        return cache[provider]
    first=primary(kind)
    if first=='zeus':return 'zeus',None,None
    available,reason=ok(first)
    if available:return first,None,None
    second=FALLBACK.get(first)
    if second:
        available2,reason2=ok(second)
        if available2:return second,{'from':first,'to':second,'reason':reason},None
        return None,None,f'{reason} {reason2}'
    return None,None,reason


def lane(provider):
    """ZEUS-only tasks (conditional plans) run in the strategic lane without a model call."""
    return 'gemini' if provider=='zeus' else provider


def set_cooldown(provider,seconds,reason):
    """Provider-wide pause after a limit or an outage; routing hands work to another model or keeps it queued."""
    until=now()+timedelta(seconds=max(5,min(int(seconds),24*3600)))
    with Session(db.engine) as session,session.begin():
        row=session.get(PagaAiProvider,provider,with_for_update=True)
        if row is None:row=PagaAiProvider(provider=provider);session.add(row)
        if row.cooldown_until is None or row.cooldown_until<until:row.cooldown_until=until
        row.last_error=scrub(reason)[:300];row.updated_at=now()
    return until


def admit(provider,estimate_tokens):
    """Client-side free-tier limits (requests/min, requests/day, tokens/min), counted from logged calls."""
    rule=limits(provider)
    if not rule:return
    moment=now()
    with Session(db.engine) as session:
        base=select(func.count()).select_from(PagaAiMetric).where(PagaAiMetric.provider==provider,PagaAiMetric.is_call.is_(True))
        minute=session.scalar(base.where(PagaAiMetric.created_at>=moment-timedelta(seconds=60))) or 0
        day=session.scalar(base.where(PagaAiMetric.created_at>=moment-timedelta(hours=24))) or 0
        tokens=session.scalar(select(func.coalesce(func.sum(func.coalesce(PagaAiMetric.prompt_tokens,0)+func.coalesce(PagaAiMetric.generated_tokens,0)),0))
                              .where(PagaAiMetric.provider==provider,PagaAiMetric.is_call.is_(True),PagaAiMetric.created_at>=moment-timedelta(seconds=60))) or 0
    label=PROVIDERS[provider]['label']
    if day>=rule['rpd']:raise RateLimited(f'{label}: wyczerpany dzienny limit zapytań ({rule["rpd"]}).',retry_after=3600,local=True)
    if minute>=rule['rpm']:raise RateLimited(f'{label}: limit zapytań na minutę ({rule["rpm"]}).',retry_after=60,local=True)
    if tokens+estimate_tokens>rule['tpm']:raise RateLimited(f'{label}: limit tokenów na minutę ({rule["tpm"]}).',retry_after=60,local=True)


# ---------------- HTTP clients ----------------

TIMEOUT=120


def _retry_after(headers,body):
    value=headers.get('retry-after') if headers is not None else None
    try:
        if value:return max(1,int(float(value)))
    except ValueError:pass
    match=re.search(r'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"',body or '')
    if match:return max(1,int(float(match.group(1)))+1)
    match=re.search(r'try again in (?:(\d+)m)?(\d+(?:\.\d+)?)s',body or '')
    if match:return int(match.group(1) or 0)*60+int(float(match.group(2)))+1
    return 60


def _post(provider,url,body,headers,pause_on_outage=True):
    """pause_on_outage=False: the caller decides what to pause (Gemini limits are per model, not per provider)."""
    data=json.dumps(body,ensure_ascii=False).encode()
    request=urllib.request.Request(url,data=data,headers={'Content-Type':'application/json','User-Agent':'ZEUS-UAT-PAGA/1.0',**headers})
    try:
        with urllib.request.urlopen(request,timeout=TIMEOUT) as response:return json.load(response)
    except urllib.error.HTTPError as error:
        text=scrub(error.read(4000).decode('utf-8','replace') if hasattr(error,'read') else '')
        label=PROVIDERS[provider]['label']
        if error.code==429:
            seconds=_retry_after(error.headers,text)
            if pause_on_outage:set_cooldown(provider,seconds,'HTTP 429 — limit dostawcy')
            raise RateLimited(f'{label}: przekroczony limit API (HTTP 429), ponowienie za {seconds} s.',retry_after=seconds)
        if error.code>=500:
            if pause_on_outage:set_cooldown(provider,120,f'HTTP {error.code}')
            raise ProviderUnavailable(f'{label}: błąd serwera dostawcy (HTTP {error.code}).',retry_after=120)
        if error.code==413 or 'Request too large' in text or 'context_length_exceeded' in text:
            from game.qwen_runtime import ContextTooLarge
            raise ContextTooLarge(f'{label}: zapytanie za duże dla limitu modelu: {text[:200]}')
        if error.code in (401,403):
            set_cooldown(provider,1800,f'HTTP {error.code} — klucz odrzucony');raise ProviderUnavailable(f'{label}: dostawca odrzucił klucz API (HTTP {error.code}).',retry_after=1800)
        raise ValueError(f'{label}: zapytanie odrzucone (HTTP {error.code}): {text[:300]}') from None
    except (urllib.error.URLError,socket.timeout,TimeoutError,ConnectionError) as error:
        if pause_on_outage:set_cooldown(provider,120,'brak połączenia')
        raise ProviderUnavailable(f"{PROVIDERS[provider]['label']}: brak połączenia z API ({type(error).__name__}).",retry_after=120) from None


def _decision(text,label):
    try:decision=json.loads(text)
    except (TypeError,ValueError):
        match=re.search(r'\{.*\}',text or '',re.S)
        if not match:raise ValueError(f'{label}: odpowiedź nie jest obiektem JSON.') from None
        decision=json.loads(match.group(0))
    if not isinstance(decision,dict):raise ValueError(f'{label}: odpowiedź nie jest obiektem JSON.')
    return decision


def gemini_generate(messages,*,schema=None,stats=None,max_tokens=640,cancelled=lambda:False):
    stats=stats if stats is not None else {};began=time.monotonic()
    system='\n\n'.join(m['content'] for m in messages if m['role']=='system')
    contents=[{'role':'model' if m['role']=='assistant' else 'user','parts':[{'text':m['content']}]} for m in messages if m['role']!='system']
    config={'temperature':0.3,'maxOutputTokens':max(4096,int(max_tokens)*4),'responseMimeType':'application/json'}
    if schema:config['responseJsonSchema']=compact_schema(schema)
    body={'systemInstruction':{'parts':[{'text':system}]},'contents':contents,'generationConfig':config}
    headers={'x-goog-api-key':_key('gemini')}
    def call(model):
        stats['model']=model
        url=f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'
        try:return _post('gemini',url,body,headers,pause_on_outage=False)
        except ValueError as error:
            if 'responseJsonSchema' not in config or 'schema' not in str(error).lower():raise
            # A grammar the API cannot express: JSON mode only; ZEUS validates every action anyway.
            config.pop('responseJsonSchema',None);stats['schema_fallback']=True
            return _post('gemini',url,body,headers,pause_on_outage=False)
    try:
        result=None;limited=[];failures=[]
        models=active_models('gemini')
        for model in models:
            try:result=call(model);break
            except RateLimited as error:
                # Quota of THIS model is used up (Gemini counts per model): pause the model, try the next free one.
                set_cooldown(model_key('gemini',model),error.retry_after or 60,'HTTP 429 — limit modelu');limited.append(error);stats.setdefault('spare_reason',str(error)[:120])
            except ProviderUnavailable as error:
                # Overloaded model (503 "high demand"): short pause for this model only.
                set_cooldown(model_key('gemini',model),60,str(error));failures.append(error);stats.setdefault('spare_reason',str(error)[:120])
        if result is None:
            # No free Gemini model can answer now: pause the provider until the first model is free again.
            with Session(db.engine) as session:
                ends=[model_paused(session,'gemini',model) for model in [model_name('gemini'),*spare_models('gemini')]]
            ends=[end for end in ends if end]
            seconds=max(5,int((min(ends)-now()).total_seconds())) if ends else 120
            reason='wszystkie bezpłatne modele Gemini wyczerpały limit lub są przeciążone'
            set_cooldown('gemini',seconds,reason)
            if limited and not failures:raise RateLimited(f'Gemini: {reason} (HTTP 429).',retry_after=seconds)
            raise ProviderUnavailable(f'Gemini: {reason}.',retry_after=seconds)
        usage=result.get('usageMetadata') or {}
        stats.update(prompt_tokens=usage.get('promptTokenCount'),generated_tokens=(usage.get('candidatesTokenCount') or 0)+(usage.get('thoughtsTokenCount') or 0) or None)
        candidates=result.get('candidates') or []
        if not candidates:raise ValueError('Gemini: brak odpowiedzi (zablokowana treść albo pusta odpowiedź).')
        candidate=candidates[0]
        if candidate.get('finishReason')=='MAX_TOKENS':raise ValueError('Gemini: ucięta odpowiedź modelu; nie wykonano dyspozycji.')
        text=''.join(part.get('text','') for part in (candidate.get('content') or {}).get('parts') or [] if not part.get('thought'))
        if cancelled():raise RuntimeError('Zadanie anulowano.')
        return _decision(text,'Gemini')
    finally:stats['seconds']=round(time.monotonic()-began,2)


def groq_generate(messages,*,schema=None,stats=None,max_tokens=640,cancelled=lambda:False):
    stats=stats if stats is not None else {};began=time.monotonic()
    # Free tier: 8K tokens/min INCLUDING the reserved answer. The full decision grammar alone exceeds it (UAT 10 Nov 2026: 8058),
    # so Groq gets the compact grammar: operation_id limited to this task's operations (without it the model dropped the
    # ':POST' suffix, UAT task 480); ZEUS validates every action's fields.
    stats['model']=model_name('groq')
    body={'model':model_name('groq'),'messages':messages,'temperature':0.3,'max_completion_tokens':max(1024,int(max_tokens)*2),
          'response_format':{'type':'json_schema','json_schema':{'name':'decyzja_paga','schema':compact_schema(schema),'strict':False}} if schema else {'type':'json_object'}}
    if model_name('groq').startswith('openai/gpt-oss'):body['reasoning_effort']='low'
    url='https://api.groq.com/openai/v1/chat/completions'
    try:
        try:result=_post('groq',url,body,{'Authorization':'Bearer '+_key('groq')})
        except ValueError as error:
            # An answer outside the grammar (json_validate_failed) is a model error; a grammar the API refuses falls back to JSON mode.
            if not schema or 'json_validate_failed' in str(error) or 'schema' not in str(error).lower():raise
            body['response_format']={'type':'json_object'};stats['schema_fallback']=True
            result=_post('groq',url,body,{'Authorization':'Bearer '+_key('groq')})
        usage=result.get('usage') or {}
        stats.update(prompt_tokens=usage.get('prompt_tokens'),generated_tokens=usage.get('completion_tokens'))
        choice=(result.get('choices') or [{}])[0]
        if choice.get('finish_reason')=='length':raise ValueError('Groq: ucięta odpowiedź modelu; nie wykonano dyspozycji.')
        if cancelled():raise RuntimeError('Zadanie anulowano.')
        return _decision((choice.get('message') or {}).get('content'),'Groq')
    finally:stats['seconds']=round(time.monotonic()-began,2)


def remote_generate(provider,messages,**kwargs):
    return {'gemini':gemini_generate,'groq':groq_generate}[provider](messages,**kwargs)


def generator(provider,qwen=None):
    """The generate() callable for one lane. API calls pass the free-tier limiter first."""
    if provider=='qwen':
        if qwen is not None:return qwen
        from game import qwen_runtime
        return qwen_runtime.generate
    def generate(messages,**kwargs):
        size=len(json.dumps(messages,ensure_ascii=False))
        admit(provider,size//3+int(kwargs.get('max_tokens') or 640))
        return remote_generate(provider,messages,**kwargs)
    return generate


def permitted(provider,operation,data):
    """Central split of responsibilities that no model can bypass. Returns an error text or None."""
    action=(data or {}).get('action') if isinstance(data,dict) else None
    loan=str(operation).split(':')[0]=='game_loans.change'     # with or without the method suffix
    if provider=='qwen':
        if operation=='no_action' or (loan and action in LOAN_DECISIONS):return None
        return 'Model finansowy (Qwen) rozpatruje wyłącznie przychodzące wnioski o pożyczki (accept/reject).'
    if loan and action in LOAN_DECISIONS:
        return 'Wnioski innych państw o pożyczkę rozpatruje wyłącznie model finansowy (Qwen).'
    return None


def status(session):
    """Administrator view: switches, keys present (yes/no only), model, limits, pause, calls in the last 24 h."""
    moment=now();result=[]
    since=moment-timedelta(hours=24)
    counts=dict(session.execute(select(PagaAiMetric.provider,func.count()).where(PagaAiMetric.is_call.is_(True),PagaAiMetric.created_at>=since).group_by(PagaAiMetric.provider)).all())
    limited=dict(session.execute(select(PagaAiMetric.provider,func.count()).where(PagaAiMetric.outcome=='RATE_LIMIT',PagaAiMetric.created_at>=since).group_by(PagaAiMetric.provider)).all())
    queued=dict(session.execute(select(PagaAiJob.provider,func.count()).where(PagaAiJob.status=='RUNNING').group_by(PagaAiJob.provider)).all())
    for provider,spec in PROVIDERS.items():
        available,reason=availability(session,provider,moment)
        result.append({'provider':provider,'label':spec['label'],'role':spec['role'],'model':model_name(provider),'enabled':flag(spec['switch'],False),
                       'keyPresent':None if not spec['key'] else bool(_key(provider)),'available':available,'reason':reason,'limits':limits(provider),
                       'calls24h':counts.get(provider,0),'rateLimited24h':limited.get(provider,0),'running':queued.get(provider,0),
                       'pausedModels':{model:f'{until:%H:%M} UTC' for model in [model_name(provider),*spare_models(provider)] if (until:=model_paused(session,provider,model,moment))}})
    return {'providers':result,'writesEnabled':writes_enabled()}
