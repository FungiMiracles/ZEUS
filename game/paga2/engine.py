"""Silnik decyzji PAGA2: opcje → wykonalność → punktacja → wybór (randomizer przy remisie) → wykonanie → dziennik.

Tryby:
- CYCLIC    — cykliczny przegląd infrastruktury, wydobycia, energii, badań, handlu, obrony i stosunków; wojnę ofensywną można
              wypowiedzieć wyłącznie z gotowego planu wojennego (game.paga2.war_plans, 21 Nov 2026),
- IMMEDIATE — natychmiastowa reakcja na zagrożenia (wojna, atak, najazd) oraz na wiadomości, wpisy forum i powiadomienia,
- BUDGET    — ustalenie budżetu bieżącego okresu budżetowego, gdy wymaga tego przebieg gry.

Wszystkie działania przechodzą przez oryginalne ekrany i operacje gracza (game/paga2/gateway.py), więc państwo PAGA2
podlega tym samym regułom i ograniczeniom co gracz ludzki. Domeny działań dokładają adaptery (register()).
"""
from dataclasses import dataclass
from datetime import timedelta
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from extensions import db
from game.paga2 import catalog
from game.paga2.models import Paga2Control,Paga2Profile,Paga2Decision,utc_now
from game.paga2.scoring import Option,score,check_resources,limits

MODES=('CYCLIC','IMMEDIATE','BUDGET')
MIN_SCORE=50.0


@dataclass(frozen=True)
class Adapter:
    """Domena działań: propose(ctx) -> [Option]; check(ctx, option) -> powód blokady | None; execute(ctx, option) -> dict."""
    name:str
    modes:tuple
    propose:object
    execute:object
    check:object=None


ADAPTERS=[]


def register(adapter):
    if all(item.name!=adapter.name for item in ADAPTERS):ADAPTERS.append(adapter)
    return adapter


class Context:
    """Wszystko, co algorytm wie o państwie w chwili decyzji (dane gracza, mapa, pamięć, sytuacja, profil)."""

    def __init__(self,app,actor,profile,mode,trigger,request_key,*,triggers=None,now=None):
        from game.finance_service import game_now
        self.app=app;self.actor=actor;self.country_id=actor.country_id;self.mode=mode;self.trigger=trigger;self.request_key=request_key
        self.triggers=list(triggers or [])
        self.traits=catalog.default_profile(profile.traits);self.priorities=list(profile.priorities or []);self.categories=list(profile.categories or [])
        self.limits=limits(self.traits);self.spent={};self.used_resources={};self.errors=[]
        self.now=now or game_now()
        self._screens={};self._world=None;self._history={};self._perception={}
        with Session(db.engine) as session:
            from game.paga2.memory import recall
            from game.paga_relationships import country_preferences
            from game.paga2.situation import assess
            self.memory=recall(session,self.country_id,self.now)
            self.relationships={item['country_id']:item for item in country_preferences(session,self.country_id)}
            self.situation=assess(session,self.country_id,self.now,world=self.world_summary(session),memory=self.memory)
            self._sectors=self._read_sectors(session)
            self._stocks=self._read_stocks(session)

    # ---- dane własnego państwa ----
    def _read_sectors(self,session):
        from game.budget_overview import budget_overview
        try:return {item['code']:float(item['remaining']) for item in budget_overview(session,self.country_id)['items']}
        except Exception:return {}

    def _read_stocks(self,session):
        from game.commerce_models import ResourceStock
        return {row.resource:int(row.quantity) for row in session.scalars(select(ResourceStock).where(ResourceStock.panstwo_id==self.country_id))}

    def sector_start(self,sector):return self._sectors.get(sector,0.0)
    def available(self,sector):return max(0.0,self._sectors.get(sector,0.0)-self.spent.get(sector,0.0))
    def stock(self,resource):return self._stocks.get(resource,0)-self.used_resources.get(resource,0)

    def world_summary(self,session=None):
        if self._world is None:
            from game.paga2.geography import World
            if session is None:
                with Session(db.engine) as own:self._world=World(own).summary(self.country_id)
            else:self._world=World(session).summary(self.country_id)
        return self._world

    def screen(self,name):
        """Ekran gracza (czytany raz na przebieg)."""
        if name not in self._screens:
            from game.paga2.view import read
            self._screens[name]=read(self.app,self.actor,name)
        return self._screens[name]

    def call(self,path,*,method='POST',json=None,form=None):
        from game.paga2.gateway import call
        self._screens.clear()  # po operacji ekrany mogą się zmienić
        return call(self.app,self.actor,path,method=method,json=json,form=form)

    def perception(self,other):
        if other not in self._perception:
            known=(self.memory.get('perception') or {}).get(other)
            self._perception[other]=known or {'trust':50,'threat':20,'confidence':20}
        return self._perception[other]

    def _sabotage_summary(self):
        from game.paga2.sabotage import summary
        try:return summary(self)
        except Exception:return []

    def history(self,other):
        if other not in self._history:
            from game.paga2.memory import history_with
            with Session(db.engine) as session:self._history[other]=history_with(session,self.country_id,other,self.now)
        return self._history[other]

    def threshold(self,passive):
        """Minimalna ocena działania. Budżet półrocza trzeba ustalić zawsze — wybór dotyczy tylko jego wariantu."""
        return float('-inf') if self.mode=='BUDGET' else max(passive.score,MIN_SCORE)

    def passive_bonus(self):
        """Wartość wstrzymania się od działania: cierpliwe państwa częściej czekają, wojna wymusza aktywność."""
        bonus=5+(self.traits.get('strategic_patience',50)-50)/10
        if self.situation.get('level')=='war':bonus-=6
        elif self.situation.get('level')=='threat':bonus-=3
        return round(bonus,3)

    def max_actions(self):
        if self.mode=='BUDGET':return 1
        if self.mode=='IMMEDIATE':return 2 if self.situation.get('level')=='war' else 1
        return 1+int(self.traits.get('ambition',50)//40)

    def inputs(self):
        world=self._world or {}
        return {'tryb':self.mode,'wyzwalacz':self.trigger,'wyzwalacze':self.triggers[:20],
                'profil':{'charakter':self.categories,'priorytety':self.priorities,'cechy':self.traits},
                'sytuacja':{key:value for key,value in self.situation.items() if key!='relations'},
                'limity_wydatków':self.limits,'środki_sektorów_ROI':self._sectors,'magazyn':self._stocks,
                'geografia':{'sąsiedzi':world.get('neighbor_countries',[]),'regiony_nadmorskie':world.get('coastal_regions',[]),
                             'regiony_przygraniczne':world.get('border_regions',[]),'okupowane_przez_innych':world.get('occupied_by_others',{})},
                'pamięć':{'ostatnie_decyzje':self.memory.get('own_decisions',[])[:10],'działania_wobec_nas':self.memory.get('actions_against_us',[])[:10],
                          'zmiany_relacji':self.memory.get('relation_changes',[])[:10],'wykryty_sabotaż':self._sabotage_summary()},
                'powiązania_historyczne':list(self.relationships.values()),'błędy_adapterów':self.errors}


def passive_option():
    return Option(key='passive',domain='planning',action='PASSIVE',label='Wstrzymanie się od działania',passive=True)


def eligible(session,country_id):
    """PAGA2 włączone globalnie, profil z autonomią, państwo bez gracza i suwerenne."""
    from game.diplomacy_service import npc_eligible
    control=session.get(Paga2Control,1,populate_existing=True)
    if control is None or not control.enabled:return None
    profile=session.get(Paga2Profile,country_id,populate_existing=True)
    if profile is None or not profile.autonomy_enabled or not npc_eligible(session,country_id):return None
    from game.sovereignty import lost
    if lost(session,country_id) is not None:return None
    return profile


def run(app,country_id,mode,trigger,*,request_key=None,triggers=None,adapters=None,now=None):
    """Jeden przebieg decyzyjny państwa. Zwraca id zapisu w historii decyzji (albo None, gdy PAGA2 nie działa)."""
    if mode not in MODES:raise ValueError('Nieznany tryb PAGA2.')
    request_key=(request_key or f'{mode}:{country_id}:{trigger}')[:160]
    from game.paga2.gateway import actor_for
    with Session(db.engine) as session,session.begin():
        existing=session.scalar(select(Paga2Decision.id).where(Paga2Decision.request_key==request_key))
        if existing:return existing
        profile=eligible(session,country_id)
        if profile is None:return None
        session.expunge(profile)
        actor=actor_for(session,country_id)
    try:
        ctx=Context(app,actor,profile,mode,trigger,request_key,triggers=triggers,now=now)
        options=[passive_option()];owners={}
        for adapter in (ADAPTERS if adapters is None else adapters):
            if mode not in adapter.modes:continue
            try:
                for option in adapter.propose(ctx) or []:options.append(option);owners[option.key]=adapter
            except Exception as error:
                app.logger.exception('PAGA2: adapter %s państwa %s',adapter.name,country_id)
                ctx.errors.append(f'{adapter.name}: {type(error).__name__}: {error}'[:300])
        for option in options:score(option,ctx)
        for option in options:
            if option.passive:option.feasible=True;continue
            reason=check_resources(option,ctx)
            adapter=owners[option.key]
            if reason is None and adapter.check is not None:
                try:reason=adapter.check(ctx,option)
                except Exception as error:reason=f'Błąd sprawdzania: {type(error).__name__}: {error}'[:300]
            option.feasible=reason is None;option.blocked=reason
        passive=options[0];executed=[];attempted=[];randomized=False
        # Grupy z decyzją wymaganą (np. odpowiedź na propozycję): w grupie startuje tylko najlepsza opcja.
        for group in {o.payload.get('group') for o in options if o.payload.get('required')}:
            members=sorted((o for o in options if o.payload.get('group')==group and o.feasible),key=lambda o:-o.score)
            for weaker in members[1:]:weaker.payload=dict(weaker.payload,required=False)
        blocked_groups=set()
        def attempt(option):
            attempted.append(option)
            try:result=owners[option.key].execute(ctx,option) or {}
            except Exception as error:
                app.logger.exception('PAGA2: wykonanie %s państwa %s',option.key,country_id)
                result={'status':500,'error':f'{type(error).__name__}: {error}'[:300]}
            option.result=result
            if int(result.get('status',200))<400:
                option.chosen=True;executed.append(option)
                if option.cost and option.sector:ctx.spent[option.sector]=ctx.spent.get(option.sector,0)+option.cost
                for resource,amount in option.resources.items():ctx.used_resources[resource]=ctx.used_resources.get(resource,0)+amount
                if option.payload.get('group'):blocked_groups.add(option.payload['group'])
            else:
                option.feasible=False;option.blocked='Gra odrzuciła operację: '+str(result.get('error') or result.get('status'))[:300]
        # 12 Nov 2026: decyzje wymagane (odpowiedzi na propozycje, decyzje o okupacji) zapadają zawsze i poza limitem działań —
        # wcześniej wyżej ocenione działania zajmowały limit i propozycje latami czekały na odpowiedź.
        for option in sorted((o for o in options if o.payload.get('required') and o.feasible and not o.passive),key=lambda o:-o.score):
            if option.payload.get('group') in blocked_groups:continue
            attempt(option)
        for _ in range(ctx.max_actions()):
            pool=[o for o in options if not o.passive and o.feasible and not o.chosen and o.result is None and not o.payload.get('required')
                  and o.score>ctx.threshold(passive) and o.payload.get('group') not in blocked_groups]
            if not pool:break
            key,drawn=_choose(country_id,pool,request_key)
            randomized=randomized or drawn
            attempt(next(o for o in pool if o.key==key))
        if not executed and not attempted:passive.chosen=True
        status='EXECUTED' if executed else 'REJECTED' if attempted else 'PASSIVE'
        lead=(executed or attempted or [passive])[0]
        row=Paga2Decision(request_key=request_key,country_id=country_id,mode=mode,trigger=str(trigger)[:80],domain=lead.domain,
                          action='+'.join(o.action for o in (executed or attempted)) [:60] if (executed or attempted) else 'PASSIVE',
                          target_id=lead.target,status=status,score=lead.score,randomized=randomized,
                          options=[o.public() for o in sorted(options,key=lambda o:-o.score)],inputs=_json(ctx.inputs()),
                          result={'wykonane':[o.public() for o in executed],'próby':[o.public() for o in attempted]},game_at=ctx.now)
    except Exception as error:
        app.logger.exception('PAGA2: przebieg %s państwa %s',mode,country_id)
        row=Paga2Decision(request_key=request_key,country_id=country_id,mode=mode,trigger=str(trigger)[:80],domain='planning',action='ERROR',
                          status='ERROR',options=[],inputs={'wyzwalacz':str(trigger)[:200]},error=f'{type(error).__name__}: {error}'[:3000])
    with Session(db.engine) as session:
        try:
            with session.begin():session.add(row)
        except IntegrityError:
            return session.scalar(select(Paga2Decision.id).where(Paga2Decision.request_key==request_key))
        return row.id


def _choose(country_id,pool,request_key):
    """Najwyżej oceniona opcja; przy remisie (równe oceny — od 17 Nov 2026 bez marginesu 2 pkt) decyduje randomizer (zapis i licznik wywołań)."""
    from game.paga2 import randomizer
    scored=[(o.key,o.score) for o in pool]
    top=randomizer.tied(scored)
    if len(top)==1:return top[0][0],False
    with Session(db.engine) as session,session.begin():
        key=randomizer.draw(session,country_id,top,reason='Remis ocen opcji — konflikt priorytetów',decision_key=request_key)
    return key,True


def _json(value):
    from game.paga2.gateway import plain
    return plain(value)
