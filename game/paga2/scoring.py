"""System punktowania decyzji PAGA2.

Każda opcja otrzymuje punkty (bazowo 50) z jawnie zapisanych składników:
- priorytety strategiczne (waga pozycji × wpływ opcji × mnożnik sytuacji geopolitycznej),
- charakterystyka państwa (25 cech 0–100; 50 = neutralnie),
- ogólny charakter państwa (do 3 typów),
- powiązania historyczne z państwem docelowym (sojusznik / nieprzyjazne / satelita),
- pamięć: zaufanie, zagrożenie i historia działań państwa docelowego wobec nas,
- rozwaga finansowa (udział kosztu w dostępnych środkach), ryzyko i tolerancja strat,
- nieprzewidywalność (mały rozrzut zależny od cechy „przewidywalność”).
"""
from dataclasses import dataclass,field
from hashlib import sha256
from random import Random
from game.paga2.catalog import priority_weights

BASE=50.0


@dataclass
class Option:
    key:str
    domain:str
    action:str
    label:str
    target:int|None=None
    effects:dict=field(default_factory=dict)      # priorytet -> wpływ [-1, 1]
    traits:dict=field(default_factory=dict)       # cecha -> powinowactwo [-1, 1] (+: wysoka cecha sprzyja opcji)
    categories:dict=field(default_factory=dict)   # ogólny charakter -> powinowactwo [-1, 1]
    cost:float=0.0                                # ROI z budżetu sektora
    sector:str|None=None
    resources:dict=field(default_factory=dict)    # surowiec -> ilość z magazynu
    risk:float=0.0                                # 0..1
    stance:str='neutral'                          # wobec celu: friendly / hostile / neutral
    base:float=0.0                                # ocena sytuacyjna adaptera (opisana w notes)
    notes:list=field(default_factory=list)
    payload:dict=field(default_factory=dict)
    passive:bool=False
    # wyniki
    score:float=0.0
    factors:dict=field(default_factory=dict)
    feasible:bool|None=None
    blocked:str|None=None
    chosen:bool=False
    result:dict|None=None

    def public(self):
        return {'key':self.key,'domain':self.domain,'action':self.action,'label':self.label,'target':self.target,'score':round(self.score,3),
                'factors':self.factors,'feasible':self.feasible,'blocked':self.blocked,'chosen':self.chosen,'cost':self.cost,'sector':self.sector,
                'resources':self.resources,'notes':self.notes,'payload':self.payload,'result':self.result}


def clip(value,low,high):return max(low,min(high,value))


def limits(traits):
    """Ile środków sektora może pochłonąć jedna akcja i cały przebieg (nieodpowiedzialne wydatki są zablokowane)."""
    fc=traits.get('fiscal_conservatism',50)/100
    per_action=round(.6-.4*fc,3)              # 20%–60% środków sektora na jedną akcję
    per_run=round(min(.9,per_action*1.6),3)
    return {'per_action':per_action,'per_run':per_run}


def relationship_term(option,ctx):
    """Powiązania historyczne, zaufanie/zagrożenie i historia działań wobec nas (dla opcji z państwem docelowym)."""
    if option.target is None or option.stance=='neutral':return 0.0,{}
    t=ctx.traits;friendly=option.stance=='friendly';hostile=option.stance=='hostile'
    parts={}
    link=ctx.relationships.get(option.target)
    if link:
        status,role=link['status'],link.get('role')
        if status=='historical_ally':parts['historyczny_sojusznik']=12 if friendly else -(14+16*t.get('alliance_loyalty',50)/100)
        elif status=='historical_hostile':parts['historycznie_nieprzyjazne']=6 if hostile else -12
        elif status=='satellite' and role=='satellite':parts['satelita_patrona']=10 if friendly else -25
        elif status=='satellite' and role=='patron':parts['patron_satelity']=6 if friendly else -6
    perception=ctx.perception(option.target)
    trust=perception.get('trust',50);threat=perception.get('threat',20)
    parts['zaufanie']=round((trust-50)/5*(1 if friendly else -1),3)
    # 14 Nov 2026: przy pokoju/zawieszeniu broni zagrożenie ze strony przeciwnika skłania do zawarcia pokoju, a nie do jego odrzucenia
    # (wcześniej odrzucenie pokoju jako działanie „wrogie” dostawało premię za zagrożenie — im groźniejszy wróg, tym dłuższa wojna).
    peace=option.action in ('PEACE','CEASEFIRE') or bool((option.payload or {}).get('peace'))
    if peace:
        if friendly:parts['zagrożenie_skłania_do_pokoju']=round(threat/10*(1.3-t.get('revenge',50)/100),3)
    elif hostile:parts['zagrożenie']=round(threat/10*(.3+t.get('revenge',50)/100),3)
    history=ctx.history(option.target)
    if history['hostile_from']:
        n=min(3,history['hostile_from'])
        if hostile:parts['rewanż']=round(5*n*t.get('revenge',50)/100,3)
        if friendly:parts['pamięć_ataków']=round(-3*n*(100-t.get('agreeableness',50))/100,3)
    if option.target in ctx.situation.get('allies',[]):
        parts['obecny_sojusz']=8 if friendly else -(10+10*t.get('alliance_loyalty',50)/100)
    return sum(parts.values()),parts


def score(option,ctx):
    t=ctx.traits;situation=ctx.situation;weights=priority_weights(ctx.priorities)
    if option.passive:
        option.score=BASE+ctx.passive_bonus();option.factors={'oczekiwanie':round(option.score-BASE,3),'cierpliwość_strategiczna':t.get('strategic_patience',50)}
        return option
    mult=situation.get('multipliers',{})
    priorities={key:round(40*weights[key]*value*mult.get(key,1.0),3) for key,value in option.effects.items() if key in weights}
    trait_parts={key:aff*(t.get(key,50)-50)/50 for key,aff in option.traits.items()}
    norm=max(1.0,sum(abs(a) for a in option.traits.values()))**.5
    traits_total=clip(18*sum(trait_parts.values())/norm,-20,20)
    categories=clip(8*sum(value for key,value in option.categories.items() if key in ctx.categories),-16,16)
    relation,relation_parts=relationship_term(option,ctx)
    prudence=0.0
    if option.cost>0 and option.sector:
        available=ctx.available(option.sector)
        share=option.cost/available if available>0 else 9.9
        # Kara rośnie kwadratowo z udziałem w limicie jednej akcji: przy limicie −10 pkt, przy połowie −2,5 pkt.
        prudence=-round(min(40.0,10*(share/max(.05,ctx.limits['per_action']))**2),3)
    risk=-round(option.risk*20*(100-t.get('loss_tolerance',50))/100,3)
    rng=Random(int(sha256(f'{ctx.request_key}:{option.key}'.encode()).hexdigest()[:16],16))
    unpredictability=round(rng.uniform(-4,4)*(100-t.get('predictability',50))/100,3)
    total=BASE+sum(priorities.values())+traits_total+categories+relation+prudence+risk+option.base+unpredictability
    option.score=round(total,3)
    option.factors={'priorytety':priorities,'cechy':round(traits_total,3),'charakter':round(categories,3),'powiązania':relation_parts,
                    'rozwaga_finansowa':prudence,'ryzyko':risk,'sytuacja_adaptera':round(option.base,3),'nieprzewidywalność':unpredictability,
                    'poziom_zagrożenia':situation.get('level')}
    return option


def check_resources(option,ctx):
    """Wykonalność finansowa i surowcowa; zwraca powód blokady albo None."""
    if option.cost>0:
        if not option.sector:return 'Brak sektora budżetu dla wydatku.'
        available=ctx.available(option.sector)
        if option.cost>available:return f'Za mało środków w sektorze {option.sector}: potrzeba {option.cost:,.0f} ROI, dostępne {available:,.0f} ROI.'.replace(',',' ')
        start=ctx.sector_start(option.sector)
        minimal=bool(option.payload.get('minimal_purchase'))   # 13 Nov 2026: najmniejszy możliwy zakup (1 punkt) nie podlega limitom rozwagi
        if minimal:return None
        if option.cost>ctx.limits['per_action']*start+1e-6:
            return f'Nierozważny wydatek: {100*option.cost/max(1,start):.0f}% środków sektora (limit jednej akcji {100*ctx.limits["per_action"]:.0f}%).'
        if ctx.spent.get(option.sector,0)+option.cost>ctx.limits['per_run']*start+1e-6:
            return f'Limit wydatków tego przebiegu w sektorze {option.sector} ({100*ctx.limits["per_run"]:.0f}%) zostałby przekroczony.'
    for resource,amount in option.resources.items():
        stock=ctx.stock(resource)
        if amount>stock:return f'Za mało surowca {resource}: potrzeba {amount}, w magazynie {stock}.'
        if amount>ctx.limits['per_action']*stock+1e-6 and stock>0:
            return f'Nierozważne zużycie surowca {resource}: {100*amount/stock:.0f}% zapasu (limit {100*ctx.limits["per_action"]:.0f}%).'
    return None
