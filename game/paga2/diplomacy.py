"""PAGA2 — dyplomacja: zmiana relacji (propozycje poprawy, sojusze i partnerstwa, jednostronne pogorszenie),
propozycje pokoju i zawieszenia broni oraz odpowiedzi na propozycje innych państw.

Wypowiedzenie wojny należy do etapu „Wojna” (nigdy w trybie cyklicznym).
Ocena uwzględnia ogólny charakter (np. państwo hegemonistyczne buduje sojusze), cechy (ugodowość, prowokacyjność,
lojalność sojusznicza, rewanżyzm, izolacjonizm), powiązania historyczne, zaufanie i pamięć działań wobec państwa.
"""
from datetime import timedelta
from sqlalchemy import select
from sqlalchemy.orm import Session
from extensions import db
from game.paga2.engine import Adapter,register
from game.paga2.scoring import Option,clip
from game.paga2.finance import result
from game.paga2.war_losses import deterrence   # 13 Nov 2026: pokój po ciężkiej wojnie odstrasza od ponownej wrogości

ACTION='/game/dyplomacja/akcje'
DECIDE='/game/dyplomacja/propozycje/{id}/decyzja'
ORDER=('egzystencjalniewrogie','wrogie','napiete','zle','chlodne','neutralne','dobre','przyjazne','partnerskie','partnerskiestrategiczne','sojusznicze')
PACTS=('partnerskie','partnerskiestrategiczne','sojusznicze')
COOLDOWN_DAYS=30
MAX_TARGETS=15


def dictionaries():
    from models import DictStosunkiRelacja
    from services.natural_resources import normalized
    with Session(db.engine) as session:
        return {normalized(name):id for id,name in session.execute(select(DictStosunkiRelacja.relacja_id,DictStosunkiRelacja.relacja_nazwa))}


def candidates(ctx):
    """Państwa istotne dla dyplomacji: sąsiedzi, państwa z relacją lub powiązaniem, zagrożenia i sojusznicy (ograniczona liczba)."""
    world=ctx.world_summary();s=ctx.situation
    pool=set(world.get('neighbor_countries',[]))|set(s.get('relations',{}))|set(ctx.relationships)|set(s.get('threats',[]))|set(s.get('allies',[]))
    pool.discard(ctx.country_id)
    def weight(other):
        p=ctx.perception(other)
        return (other in s.get('at_war',[]))*100+(other in world.get('neighbor_countries',[]))*30+(other in ctx.relationships)*25+abs(p.get('trust',50)-50)+p.get('threat',20)
    return sorted(pool,key=weight,reverse=True)[:MAX_TARGETS]


def recently(ctx,action,target):
    """Ta sama decyzja wobec tego państwa w ostatnich 30 dniach Entendy (unikanie powtarzania propozycji)."""
    if getattr(ctx,'_executed',None) is None:
        from game.paga2.memory import executed_actions
        with Session(db.engine) as session:ctx._executed=executed_actions(session,ctx.country_id,since=ctx.now-timedelta(days=COOLDOWN_DAYS) if ctx.now else None)
    return any(a==action and t==target for a,t,_ in ctx._executed)


def addressable(ctx):
    """Państwa, które mogą rozpatrzyć propozycję: aktywny gracz ludzki albo włączona autonomia (inaczej gra ją odrzuca)."""
    if getattr(ctx,'_addressable',None) is None:
        from game.models import GameUser,GamePlayerCountry
        from game.diplomacy_service import npc_eligible
        from game.paga2.models import Paga2Profile
        with Session(db.engine) as session:
            humans=set(session.scalars(select(GamePlayerCountry.panstwo_id).join(GameUser,GameUser.id==GamePlayerCountry.user_id).where(GameUser.is_active.is_(True))))
            autonomous={id for id in session.scalars(select(Paga2Profile.panstwo_id).where(Paga2Profile.autonomy_enabled.is_(True))) if npc_eligible(session,id)}
        ctx._addressable=humans|autonomous
    return ctx._addressable


def occupations_now(ctx):
    """Jawne okupacje na świecie: [(okupant, właściciel)] — do reakcji na zajmowanie ziem sojuszników."""
    if getattr(ctx,'_occupations',None) is None:
        from game.land_war_models import Occupation
        with Session(db.engine) as session:
            ctx._occupations=list(session.execute(select(Occupation.occupier_id,Occupation.owner_id).where(Occupation.status=='ACTIVE',Occupation.kind.in_(['base','city']))).all())
    return ctx._occupations


def occupation_stance(ctx,other):
    """Premia do pogorszenia (+) / poprawy (−) relacji z państwem, które okupuje ziemie naszych sojuszników,
    oraz premia do poprawy relacji z sojusznikiem, którego ziemie są okupowane (lojalność, interwencjonizm, solidarność)."""
    allies=set(ctx.situation.get('allies',[]));t=ctx.traits;value=0.0
    for occupier,owner in occupations_now(ctx):
        if occupier==other and owner in allies:value+=4*(t.get('alliance_loyalty',50)+t.get('interventionism',50))/100
        if owner==other and other in allies and occupier!=ctx.country_id:value-=3*t.get('solidarity',50)/50
    return value


def relation_options(ctx,ids):
    s=ctx.situation;t=ctx.traits;options=[]
    proposals_possible=addressable(ctx)
    hegemonic='hegemonic' in ctx.categories
    for other in candidates(ctx):
        row=s.get('relations',{}).get(other) or {'relation':'neutralne','state':'pokoj'}
        current=row['relation'] if row['relation'] in ORDER else 'neutralne'
        rank=ORDER.index(current);war=row.get('state')=='wojnakinetyczna'
        history=ctx.history(other);p=ctx.perception(other)
        attacked=history['hostile_from']
        pending={kind for target,kind in pending_pairs(ctx) if target==other}
        if war and other in proposals_possible:
            terms=peace_terms(ctx,other)
            for kind,label,bonus in (('PEACE','Propozycja pokoju',2.0),('CEASEFIRE','Propozycja zawieszenia broni',0.0)):
                if recently(ctx,kind,other) or kind in pending:continue
                days=ceasefire_length(ctx,other) if kind=='CEASEFIRE' else None
                options.append(Option(key=f'diplomacy:{kind.lower()}:{other}',domain='diplomacy',action=kind,label=f'{label}: państwo {other}'+(f' na {days} dni' if days else ''),target=other,stance='friendly',
                                      effects=terms['effects'],traits=terms['traits'],base=terms['base']+bonus,notes=list(terms['notes'])+([f'Proponowany czas zawieszenia broni: {days} dni Entendy.'] if days else []),
                                      payload={'kind':kind,'target_id':other,'group':f'diplomacy:{other}',**({'days':days} if days else {})}))
        if war:continue
        if rank<len(ORDER)-1 and other in proposals_possible and 'RELATION' not in pending and not recently(ctx,'RELATION_IMPROVE',other):
            better=ORDER[rank+1]
            if better in ids:
                pact=better in PACTS
                options.append(Option(key=f'diplomacy:improve:{other}',domain='diplomacy',action='RELATION_IMPROVE',label=f'Propozycja poprawy relacji z państwem {other}: {current} → {better}',
                                      target=other,stance='friendly',effects={'alliances':1.0 if pact else .6,'trade':.4,'welfare':.2},
                                      traits={'agreeableness':.8,'solidarity':.4,'isolationism':-.7,'alliance_loyalty':.4 if pact else 0,'provocation':-.4},
                                      categories={'hegemonic':.8 if pact else .4,'economic':.3,'isolationist':-.6},base=-2.0-3*min(3,attacked)-occupation_stance(ctx,other),
                                      payload={'kind':'RELATION','target_id':other,'relation_id':ids[better],'group':f'diplomacy:{other}'}))
        # Bezpośrednia propozycja sojuszu przy wysokim zaufaniu (budowa sojuszy — państwo hegemonistyczne i priorytet „sojusze”).
        if other in proposals_possible and 'RELATION' not in pending and 'sojusznicze' in ids and current in ('dobre','przyjazne','partnerskie','partnerskiestrategiczne') and p.get('trust',50)>=65 and not recently(ctx,'ALLIANCE',other):
            options.append(Option(key=f'diplomacy:alliance:{other}',domain='diplomacy',action='ALLIANCE',label=f'Propozycja sojuszu z państwem {other}',target=other,stance='friendly',
                                  effects={'alliances':1.0,'defensive_army':.4},traits={'alliance_loyalty':.8,'agreeableness':.4,'isolationism':-.9},
                                  categories={'hegemonic':1.0,'isolationist':-.8},base=-1.0+(3.0 if hegemonic else 0),
                                  payload={'kind':'RELATION','target_id':other,'relation_id':ids['sojusznicze'],'group':f'diplomacy:{other}'}))
        if rank>0 and not recently(ctx,'RELATION_WORSEN',other):
            worse=ORDER[rank-1]
            if worse in ids:
                options.append(Option(key=f'diplomacy:worsen:{other}',domain='diplomacy',action='RELATION_WORSEN',label=f'Jednostronne pogorszenie relacji z państwem {other}: {current} → {worse}',
                                      target=other,stance='hostile',effects={'conquest':.4,'alliances':-.6 if current in PACTS else -.2,'trade':-.3},
                                      traits={'provocation':.9,'revenge':.5,'agreeableness':-.8,'isolationism':.3,'predictability':-.2},
                                      categories={'imperialist':.5,'terrorist':.4},base=-8.0+4*min(3,attacked)+(p.get('threat',20)-50)/10+occupation_stance(ctx,other)-min(6.0,deterrence(ctx,other)/2),
                                      payload={'kind':'RELATION','target_id':other,'relation_id':ids[worse],'group':f'diplomacy:{other}'}))
    return options


def peace_terms(ctx,other):
    """Wspólna ocena pokoju z państwem (propozycja własna i przyjęcie cudzej): okupacja i straty skłaniają do pokoju."""
    t=ctx.traits;attacked=ctx.history(other)['hostile_from']
    # 13 Nov 2026: zniszczone w tej wojnie bazy, fabryki, elektrownie i infrastruktura oraz zmęczenie wojną skłaniają do pokoju
    from game.paga2.war_losses import peace_bonus
    bonus,loss,days=peace_bonus(ctx,other)
    notes=[f'Straty w tej wojnie: bazy {loss.get("bases",0)}, fabryki {loss.get("factories",0)}, elektrownie {loss.get("power",0)}, infrastruktura −{loss.get("infrastructure",0)} pkt; wojna trwa {days} dni Entendy.'] if loss else []
    if loss.get('nuclear'):notes.append(f'Przeciwnik użył przeciw nam broni atomowej ({loss["nuclear"]} rakiet z głowicą nuklearną) — pokój jest pilną koniecznością.')
    return dict(effects={'welfare':.8,'financial_stability':.6,'defensive_army':.3,'conquest':-.8,'offensive_army':-.5},
                traits={'agreeableness':1.0,'revenge':-.6,'loss_tolerance':-.6,'militarism':-.5,'strategic_patience':.3},
                base=4.0*len(ctx.situation.get('occupied_regions',{}))+2*min(3,attacked)*(100-t.get('loss_tolerance',50))/100+weakness(ctx)+bonus,notes=notes)


def ceasefire_length(ctx,other):
    """17 Nov 2026: proponowany czas zawieszenia broni (1–180 dni Entendy): ugodowość, cierpliwość strategiczna i własne straty
    wydłużają rozejm; mściwość i militaryzm go skracają."""
    t=ctx.traits
    days=20+1.0*t.get('agreeableness',50)+.6*t.get('strategic_patience',50)-.5*t.get('revenge',50)-.4*t.get('militarism',50)
    days+=10*len(ctx.situation.get('occupied_regions',{}))+weakness(ctx)*3
    return int(max(7,min(180,round(days))))


def weakness(ctx):
    """Brak zdolności do odpowiedzi militarnej skłania ku rozwiązaniom dyplomatycznym (brak obsadzonych baz, brak budżetu wojska)."""
    try:
        from game.paga2.defense import _forces
        forces=_forces(ctx)
    except Exception:return 0.0
    staffed=[b for b in forces.bases if b.health>0 and b.garrison]
    return (6.0 if not staffed else 0.0)+(6.0 if not forces.has_budget or forces.budget_available<=0 else 0.0)


def pair_now(session,a,b):
    """Bieżący stan pary państw (relacja, stan, ostatni wpis audytu) — jak przy rozpatrywaniu propozycji w grze."""
    from models import Stosunki,AudytStosunki
    from game.diplomacy_service import dictionaries
    from sqlalchemy import func
    a,b=sorted((a,b));relations,states,neutral=dictionaries(session)
    row=session.execute(select(Stosunki.relacja_id,Stosunki.stan_id).where(Stosunki.PANSTWO_ID==a,Stosunki.PANSTWO_ID2==b)).first()
    revision=session.scalar(select(func.max(AudytStosunki.id)).where(AudytStosunki.panstwo_id==a,AudytStosunki.panstwo_id2==b)) or 0
    return ((row.relacja_id if row and row.relacja_id is not None else neutral),(row.stan_id if row and row.stan_id is not None else states['pokoj']),revision)


def pending_pairs(ctx):
    """Pary i rodzaje propozycji oczekujących (gra nie przyjmie drugiej takiej samej)."""
    if getattr(ctx,'_pending',None) is None:
        from game.diplomacy_models import DiplomaticAction
        with Session(db.engine) as session:
            rows=session.execute(select(DiplomaticAction.source_country_id,DiplomaticAction.target_country_id,DiplomaticAction.kind).where(DiplomaticAction.status=='PENDING',
                                 (DiplomaticAction.source_country_id==ctx.country_id)|(DiplomaticAction.target_country_id==ctx.country_id))).all()
        ctx._pending={(b if a==ctx.country_id else a,kind) for a,b,kind in rows}
    return ctx._pending


JOIN_ALLIES=('sojusznicze','partnerskiestrategiczne')


def military_power(session,country_id):
    """Siła zbrojna (ważona liczba sprzętu) i przemysł wojskowy (suma poziomów fabryk amunicji)."""
    from game.governance import army_for_country
    from game.research_models import AmmunitionFactory
    from sqlalchemy import func
    army=army_for_country(session,country_id)
    weights={'czolgi_ilosc':1,'wozy_opancerzone_ilosc':.5,'wyrzutnie_rakiet_ilosc':2,'mysliwce_ilosc':3,'okrety_wojenne_ilosc':20,'okrety_podwodne_ilosc':25}
    power=sum((getattr(army,field,0) or 0)*w for field,w in weights.items()) if army else 0
    industry=session.scalar(select(func.coalesce(func.sum(AmmunitionFactory.level),0)).where(AmmunitionFactory.panstwo_id==country_id,AmmunitionFactory.removed_at.is_(None),AmmunitionFactory.health>0)) or 0
    return float(power),int(industry)


def powers(ctx,enemy):
    with Session(db.engine) as session:
        own,industry=military_power(session,ctx.country_id);foe,_=military_power(session,enemy)
    return own,industry,foe


def join_terms(ctx,enemy):
    """Ocena prośby o dołączenie do wojny: lojalność sojusznicza, interwencjonizm, siły zbrojne i przemysł wojskowy."""
    t=ctx.traits
    own,industry,foe=powers(ctx,enemy)
    ratio=own/max(1.0,foe);wars=len(ctx.situation.get('at_war',[]))
    base=(6*(t.get('alliance_loyalty',50)-50)/50+5*(t.get('interventionism',50)-50)/50+3*(min(2.0,ratio)-1)+min(4,industry)*.75-3*wars-(6 if own<=0 else 0))
    notes=[f'Siły własne {own:.0f} wobec {foe:.0f} wroga (×{ratio:.2f}); przemysł wojskowy: {industry} poz.; trwające wojny: {wars}.']
    return {'base':base,'notes':notes}


def join_capability(ctx,enemy):
    """16 Nov 2026: zdolność do dołączenia do wojny z `enemy` — te same kryteria co przy wypowiedzeniu wojny
    (game.paga2.war.war_capability). Bez danych o siłach decyzja nie jest blokowana."""
    try:
        from game.paga2.defense import _forces
        from game.paga2.war import war_capability,war_screen
        return war_capability(ctx,_forces(ctx),war_screen(ctx),enemy)
    except Exception:return {'able':True,'notes':[],'bonus':0.0,'distant':False}


def check(ctx,option):
    if option.action=='PROPOSAL_ACCEPT' and option.payload.get('capable') is False:
        return 'Brak zdolności do dołączenia do wojny. '+(option.payload.get('reason') or '')
    return None


def join_request_options(ctx):
    """Prośby do sojuszników i partnerów strategicznych o dołączenie do trwającej wojny (gdy wróg jest silny)."""
    enemies=list(ctx.situation.get('at_war',[]))
    if not enemies:return []
    from game.diplomacy_service import joinable_wars
    options=[];possible=addressable(ctx);pending={(target,kind) for target,kind in pending_pairs(ctx)}
    with Session(db.engine) as session:
        own,_=military_power(session,ctx.country_id)
        for ally,row in ctx.situation.get('relations',{}).items():
            if row.get('relation') not in JOIN_ALLIES or ally not in possible or (ally,'JOIN_WAR') in pending or recently(ctx,'JOIN_WAR',ally):continue
            for enemy in joinable_wars(session,ctx.country_id,ally,ctx.now):
                foe,_=military_power(session,enemy);need=foe/max(1.0,own)
                options.append(Option(key=f'diplomacy:join:{ally}:{enemy}',domain='diplomacy',action='JOIN_WAR',label=f'Prośba do państwa {ally} o dołączenie do wojny z państwem {enemy}',
                                      target=ally,stance='friendly',effects={'alliances':.6,'defensive_army':.8,'conquest':.4},
                                      traits={'alliance_loyalty':.5,'interventionism':.3,'strategic_patience':-.2},categories={'hegemonic':.4},
                                      base=-3.0+4*min(2.0,need),notes=[f'Siła wroga względem własnej: ×{need:.2f}.'],
                                      payload={'kind':'JOIN_WAR','target_id':ally,'enemy_id':enemy,'group':f'diplomacy:{ally}'}))
                break
    return options


def proposal_options(ctx):
    """Odpowiedzi na oczekujące propozycje innych państw: przyjęcie albo odrzucenie (odpowiedź jest zawsze udzielana)."""
    from game.diplomacy_models import DiplomaticAction
    from models import DictStosunkiRelacja
    from services.natural_resources import normalized
    options=[]
    with Session(db.engine) as session:
        names=dict(session.execute(select(DictStosunkiRelacja.relacja_id,DictStosunkiRelacja.relacja_nazwa)).all())
        rows=list(session.scalars(select(DiplomaticAction).where(DiplomaticAction.target_country_id==ctx.country_id,DiplomaticAction.status=='PENDING').order_by(DiplomaticAction.id).limit(10)))
        # Propozycje nieaktualne (stosunki zmieniły się od ich złożenia) gra i tak odrzuci — pomijamy je.
        rows=[row for row in rows if pair_now(session,row.source_country_id,row.target_country_id)==(row.expected_relation_id,row.expected_state_id,row.expected_audit_id)]
        for row in rows:session.expunge(row)
    for row in rows:
        other=row.source_country_id
        label=row.kind if row.kind!='RELATION' else f'relacja „{names.get(row.proposed_relation_id)}”'
        payload={'proposal_id':row.id,'group':f'proposal:{row.id}','required':True}
        params=getattr(row,'params',None) or {}
        if row.kind=='JOIN_WAR':
            label=f'dołączenie do wojny z państwem {params.get("enemy_name")}'
            terms=join_terms(ctx,params.get('enemy_id'))
            cap=join_capability(ctx,params.get('enemy_id'))
            accept=dict(effects={'alliances':1.0,'conquest':.5,'offensive_army':.5,'welfare':-.4,'financial_stability':-.3},
                        traits={'alliance_loyalty':1.0,'interventionism':1.0,'militarism':.4,'isolationism':-.8},categories={'hegemonic':.6,'isolationist':-.8},
                        base=terms['base']-(0 if cap['able'] else 8.0),notes=terms['notes']+cap['notes'])
            reject=dict(effects={'alliances':-.6,'financial_stability':.3,'welfare':.2},traits={'isolationism':.6,'alliance_loyalty':-.6,'interventionism':-.6},
                        categories={'isolationist':.6},base=-terms['base'],notes=terms['notes'])
        elif row.kind=='MINING_PERMIT':
            label=f'wydobycie w regionie {params.get("region_name")}'
            relation=ctx.situation.get('relations',{}).get(other,{}).get('relation','neutralne')
            rank={'sojusznicze':5,'partnerskiestrategiczne':4,'partnerskie':3,'przyjazne':2,'dobre':1}.get(normalized(relation),0)
            base=rank+2*(ctx.traits.get('agreeableness',50)-50)/50+2*(ctx.traits.get('industrialism',50)-50)/50
            accept=dict(effects={'infrastructure':1.0,'financial_stability':.8},traits={'agreeableness':.8,'industrialism':.8},base=base+1,notes=['Połowa podwójnego kosztu budowy zasili budżet infrastruktury. Zanieczyszczenie pozostaje w regionie.'])
            reject=dict(effects={'infrastructure':-.3},traits={'agreeableness':-.6,'industrialism':-.6},base=-base)
        elif row.kind=='BASE_PERMIT':
            from game.paga2.bases_abroad import permit_terms
            label=f'baza wojskowa w regionie {params.get("region_name")}'
            terms=permit_terms(ctx,row)
            accept=dict(effects={'alliances':.8,'defensive_army':.4},traits={'alliance_loyalty':.8,'agreeableness':.4,'isolationism':-.6},base=terms['base'],notes=terms['notes'])
            reject=dict(effects={'alliances':-.3},traits={'isolationism':.6,'alliance_loyalty':-.4},base=-terms['base'],notes=terms['notes'])
        elif row.kind in ('PEACE','CEASEFIRE'):
            terms=peace_terms(ctx,other)
            payload['peace']=True   # ocena zagrożenia jak przy pokoju (scoring.relationship_term)
            accept=dict(effects=terms['effects'],traits=terms['traits'],base=terms['base']+(2.0 if row.kind=='PEACE' else 0),notes=list(terms['notes']))
            reject=dict(effects={k:-v for k,v in terms['effects'].items()},traits={k:-v for k,v in terms['traits'].items()},base=-terms['base'])
        else:
            proposal=normalized(names.get(row.proposed_relation_id,'') or '')
            pact=proposal in PACTS
            accept=dict(effects={'alliances':1.0 if pact else .5,'trade':.3},traits={'agreeableness':.8,'solidarity':.3,'isolationism':-.6,'alliance_loyalty':.4 if pact else 0},
                        categories={'hegemonic':.8 if pact else .3,'isolationist':-.6},base=2.0)
            reject=dict(effects={'alliances':-.3},traits={'agreeableness':-.6,'isolationism':.6,'provocation':.3},categories={'isolationist':.6},base=0.0)
        accept_payload=dict(payload)
        if row.kind=='JOIN_WAR' and not cap['able']:accept_payload.update(capable=False,reason=' '.join(cap['notes']))
        options.append(Option(key=f'proposal:accept:{row.id}',domain='diplomacy',action='PROPOSAL_ACCEPT',label=f'Przyjęcie propozycji państwa {row.source_country_name}: {label}',
                              target=other,stance='friendly',payload=accept_payload,**accept))
        options.append(Option(key=f'proposal:reject:{row.id}',domain='diplomacy',action='PROPOSAL_REJECT',label=f'Odrzucenie propozycji państwa {row.source_country_name}: {label}',
                              target=other,stance='hostile',payload=dict(payload),**reject))
    return options


def propose(ctx):
    options=relation_options(ctx,dictionaries())+proposal_options(ctx)
    try:options+=join_request_options(ctx)
    except Exception:pass
    return options


def execute(ctx,option):
    p=option.payload
    if option.action in ('PROPOSAL_ACCEPT','PROPOSAL_REJECT'):
        status,data=ctx.call(DECIDE.format(id=p['proposal_id']),form={'decision':'accept' if option.action=='PROPOSAL_ACCEPT' else 'reject'})
    else:
        form={'kind':p['kind'],'target_id':str(p['target_id'])}
        if p.get('relation_id'):form['relation_id']=str(p['relation_id'])
        if p.get('enemy_id'):form['enemy_id']=str(p['enemy_id'])
        if p.get('region_id'):form['region_id']=str(p['region_id'])
        if p.get('days'):form['days']=str(p['days'])   # 17 Nov 2026: czas zawieszenia broni
        status,data=ctx.call(ACTION,form=form)
    return result(status,data)


ADAPTER=register(Adapter(name='diplomacy',modes=('CYCLIC','IMMEDIATE'),propose=propose,execute=execute,check=check))
