from game.paga_ai_actor import country_user_id
"""Limity baz i atomowe zarządzanie wojskami gracza."""
from game.governance import army_for_country, controller_id, controlled_ids
from game.governance import controlled_ids, controller_id
from decimal import Decimal
from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session, lazyload
from extensions import db
from models import Panstwo, Miasto, Region, Wojsko, Stosunki, DictStosunkiStan
from game.finance_models import StateBudget, StateBudgetAllocation
from game.finance_service import FinanceError, _country_for_user, game_now, period_key, period_months
from game.military_models import MilitaryBase, MilitaryExpense, MilitaryMaintenance, MissileDefenseExpense

BASES = {'land':('Baza lądowa','liczba_baz_ladowych','wojska_ladowe_ilosc'),
         'air':('Baza powietrzna','liczba_baz_powietrznych','wojska_powietrzne_ilosc'),
         'naval':('Baza morska','liczba_baz_morskich','wojska_morskie_ilosc'),
         'nuclear':('Silos atomowy',None,None)}
RESOURCES = {
    'warheads':('Głowice atomowe','bron_atomowa_ilosc','SILOS ATOMOWY.svg'),
    'soldiers':('Żołnierze',None,'CZŁOWIEK.svg'), 'tanks':('Czołgi','czolgi_ilosc','CZOŁG.svg'),
    'launchers':('Wyrzutnie rakiet','wyrzutnie_rakiet_ilosc','WYRZUTNIA RAKIET.svg'),
    'armored':('Wozy opancerzone','wozy_opancerzone_ilosc','WÓZ OPANCERZONY.svg'),
    'fighters':('Myśliwce','mysliwce_ilosc','MYŚLIWIEC.svg'),
    'warships':('Okręty wojenne','okrety_wojenne_ilosc','OKRĘT WOJENNY.svg'),
    'submarines':('Okręty podwodne','okrety_podwodne_ilosc','SUBMARINE.svg'),
}
CAPACITIES = {
    'nuclear':[{'warheads':n} for n in (100,200,500,1000,2000,3000,5000)],
    'land': [dict(zip(('soldiers','tanks','launchers','armored'), row)) for row in
             [(10000,100,25,25),(20000,150,40,40),(30000,190,50,50),(40000,240,60,60),(50000,280,70,70),(60000,300,80,80),(75000,400,100,100)]],
    'air': [dict(zip(('soldiers','fighters'), row)) for row in
            [(10000,25),(20000,40),(30000,50),(40000,60),(50000,70),(60000,80),(75000,100)]],
    'naval': [dict(zip(('soldiers','warships','submarines'), row)) for row in
              [(10000,1,0),(20000,1,1),(30000,3,2),(40000,5,4),(50000,10,8),(60000,20,12),(75000,40,20)]],
}
UPGRADE_COSTS = {level: Decimal(cost) * 1000000000 for level,cost in [(2,1),(3,8),(4,14),(5,23),(6,79),(7,139)]}
UPKEEP_RATES = dict(soldiers=4000,tanks=8000,launchers=8000,armored=8000,fighters=25000,warships=600000,submarines=650000,warheads=100000000)


def enemies(session, country_id):
    rows = session.execute(select(Stosunki.PANSTWO_ID, Stosunki.PANSTWO_ID2).join(
        DictStosunkiStan, Stosunki.stan_id == DictStosunkiStan.stan_id).where(
        or_(Stosunki.PANSTWO_ID == country_id, Stosunki.PANSTWO_ID2 == country_id),
        func.lower(DictStosunkiStan.stan_nazwa).in_(['wojna kinetyczna', 'wojna']),
    )).all()
    return sorted({owner for a,b in rows if (owner := controller_id(session, b if a == country_id else a)) is not None and owner != country_id})


def capacities(base):
    return CAPACITIES[base.kind][base.level - 1]


def active_counts(bases,session=None,country_id=None):
    active = {}
    for base in bases:
        for resource, count in base.garrison.items():
            field = BASES[base.kind][2] if resource == 'soldiers' else RESOURCES[resource][1]
            active[field] = active.get(field,0) + count
        field = BASES[base.kind][1]
        if field:active[field] = active.get(field,0) + 1
    if session is not None:
        from game.military_models import MilitaryVessel
        owner=country_id or (bases[0].panstwo_id if bases else None)
        if owner:
            for kind,count in session.execute(select(MilitaryVessel.kind,func.count()).where(MilitaryVessel.panstwo_id==owner,MilitaryVessel.base_id.is_(None),MilitaryVessel.kind!='carriers',MilitaryVessel.status.in_(['sailing','stationed','returning'])).group_by(MilitaryVessel.kind)):
                field=RESOURCES[kind][1];active[field]=active.get(field,0)+count
            # Myśliwce na lotniskowcach, których baza powietrzna przestała istnieć, pozostają zajęte.
            orphan_fighters=session.scalar(select(func.coalesce(func.sum(MilitaryVessel.fighters),0)).where(MilitaryVessel.panstwo_id==owner,MilitaryVessel.kind=='carriers',MilitaryVessel.air_base_id.is_(None),MilitaryVessel.status.in_(['sailing','stationed','returning']))) or 0
            if orphan_fighters:active['mysliwce_ilosc']=active.get('mysliwce_ilosc',0)+int(orphan_fighters)
        # Land armies outside bases (marching, defending cities, occupying) stay allocated from the totals.
        if owner:
            from game.land_war import deployed_counts
            for field,count in deployed_counts(session,owner).items():active[field]=active.get(field,0)+count
        from game.military_flights import busy_fighters
        for base in bases:
            if base.kind=='air':
                extra=max(0,busy_fighters(session,base.id)-base.garrison.get('fighters',0))
                active['mysliwce_ilosc']=active.get('mysliwce_ilosc',0)+extra
    return active


def upkeep_cost(bases):
    return sum(count * UPKEEP_RATES.get(resource,0) for base in bases for resource,count in base.garrison.items()) + sum(500000000 for base in bases if base.kind=='nuclear' and base.operational)


def military_budget(session, country_id, now=None):
    year, period = period_key(now or game_now())
    budget = session.scalar(select(StateBudget).where(StateBudget.panstwo_id == country_id, StateBudget.game_year == year, StateBudget.period == period))
    if not budget:
        return None, Decimal(0), Decimal(0)
    from game.budget_transfers import effective_allocation
    total = effective_allocation(session,budget.id,'armed_forces')
    spent = session.scalar(select(func.coalesce(func.sum(MilitaryExpense.amount),0)).where(MilitaryExpense.budget_id == budget.id))
    spent += session.scalar(select(func.coalesce(func.sum(MissileDefenseExpense.amount),0)).where(MissileDefenseExpense.budget_id==budget.id))
    from game.land_war import spent as land_war_spent
    from game.military_training import spent as training_spent
    from game.radar import spent as radar_spent
    spent += land_war_spent(session,budget.id)+training_spent(session,budget.id)+radar_spent(session,budget.id)
    maintenance = session.scalar(select(MilitaryMaintenance.amount).where(MilitaryMaintenance.panstwo_id == country_id, MilitaryMaintenance.game_year == year, MilitaryMaintenance.period == period)) or Decimal(0)
    return budget, total, max(Decimal(0), total - spent - maintenance)


def natural(value, label, minimum=0):
    if isinstance(value,bool) or not isinstance(value,int) or not minimum <= value <= 10**12:
        raise FinanceError('Nieprawidłowa liczba: ' + label)
    return value


def change_defense(user_id, action, data):
    with Session(db.engine) as session, session.begin():
        country = _country_for_user(session,user_id,lock=False)
        if isinstance(action,str) and action.startswith('defense_'):
            from game.research_service import settle_production
            settle_production(session,country.PANSTWO_ID)
        country=_country_for_user(session,user_id,lock=True)
        army = army_for_country(session, country.PANSTWO_ID, lock=True)
        if army is None:
            raise FinanceError('Brak zasobów wojskowych państwa.')
        deployment_key=None
        if action=='deploy':
            from game.mining_service import request_key
            deployment_key=request_key(data.get('request_id'))
            existing=session.scalar(select(MilitaryBase).where(MilitaryBase.panstwo_id==country.PANSTWO_ID,MilitaryBase.deployment_request_id==deployment_key))
            if existing:
                if existing.deployment_payload!={'region_id':data.get('region_id'),'kind':data.get('kind'),'garrison':data.get('garrison')}:raise FinanceError('Identyfikator rozmieszczenia został już użyty.')
                return existing.id
        bases = list(session.scalars(select(MilitaryBase).where(MilitaryBase.panstwo_id == country.PANSTWO_ID).order_by(MilitaryBase.id).with_for_update()))
        active = active_counts(bases,session,country.PANSTWO_ID)
        from game.military_navy import settle_vessels
        settle_vessels(session,game_now(),country.PANSTWO_ID)
        if action in ('place','deploy'):
            kind = data.get('kind')
            if not isinstance(kind,str) or kind not in BASES:
                raise FinanceError('Nieprawidłowy rodzaj bazy.')
            region_id = natural(data.get('region_id'),'Region',1)
            from game.base_permits import permitted_region_ids,ABROAD_UPKEEP
            abroad = region_id in permitted_region_ids(session,country.PANSTWO_ID)   # baza u sojusznika (pozwolenie aktywne)
            region = session.scalar(select(Region).options(lazyload('*')).where(Region.region_id == region_id, *(() if abroad else (Region.panstwo_id.in_(controlled_ids(session, country.PANSTWO_ID)),))))
            if region is None:
                raise FinanceError('Region nie należy do państwa gracza.')
            if abroad and kind=='nuclear':raise FinanceError('Silosów atomowych nie można budować na terytorium sojusznika.')
            from game.land_war import require_buildable
            require_buildable(session,region.region_id,country.PANSTWO_ID)
            if kind == 'naval' and region.region_polozenie_id in (None,1):
                raise FinanceError('Baza morska wymaga regionu nadmorskiego.')
            count = 1 if action=='deploy' else natural(data.get('count'), 'Liczba baz',1)
            field = BASES[kind][1]
            if kind=='nuclear':
                if count>100:raise FinanceError('Możesz zbudować najwyżej 100 silosów jednocześnie.')
                budget,total,available=military_budget(session,country.PANSTWO_ID)
                silo_upkeep=Decimal(500000000)*period_months(*period_key(game_now()))/6
                if budget is None or available<count*(25000000000+silo_upkeep):raise FinanceError('Za mało środków na budowę silosu i jego utrzymanie w bieżącym okresie budżetowym.')
            if field and count > (getattr(army,field) or 0) - active.get(field,0):
                raise FinanceError('Brak dostępnych baz tego rodzaju.')
            garrison={}
            if action=='deploy':
                requested=data.get('garrison')
                if not isinstance(requested,dict) or set(requested)-set(CAPACITIES[kind][0]):raise FinanceError('Uzupełnij garnizon wybranego rodzaju bazy.')
                for resource,capacity in CAPACITIES[kind][0].items():
                    value=natural(requested.get(resource,0),RESOURCES[resource][0]);field_name=BASES[kind][2] if resource=='soldiers' else RESOURCES[resource][1]
                    if value>capacity or value>(getattr(army,field_name) or 0)-active.get(field_name,0):raise FinanceError('Przekroczona pojemność lub dostępny zapas: '+RESOURCES[resource][0])
                    garrison[resource]=value
                if kind=='nuclear':
                    if not garrison.get('warheads'):raise FinanceError('Dodaj co najmniej jedną głowicę.')
                elif not garrison.get('soldiers') or not any(n for resource,n in garrison.items() if resource!='soldiers'):
                    raise FinanceError('Dodaj żołnierzy oraz co najmniej jedną jednostkę sprzętu.')
                scale=Decimal(period_months(*period_key(game_now())))/6
                additional=sum(n*UPKEEP_RATES[resource] for resource,n in garrison.items() if resource!='warheads')*(ABROAD_UPKEEP if abroad else 1)*scale+(25000000000+500000000*scale if kind=='nuclear' else 0)
                budget,total,available=military_budget(session,country.PANSTWO_ID)
                if budget is None or available<additional:raise FinanceError('Za mało środków na utworzenie i utrzymanie garnizonu.')
            for _ in range(count):
                new_base=MilitaryBase(panstwo_id=country.PANSTWO_ID,region_id=region.region_id,kind=kind,level=1,garrison=garrison,deployment_request_id=deployment_key,deployment_payload={'region_id':data.get('region_id'),'kind':kind,'garrison':data.get('garrison')} if deployment_key else None)
                session.add(new_base);session.flush()
                if kind=='nuclear':session.add(MilitaryExpense(panstwo_id=country.PANSTWO_ID,budget_id=budget.id,base_id=new_base.id,level=1,amount=25000000000))
            session.flush();reconcile_maintenance(session,country.PANSTWO_ID)
            return new_base.id if action=='deploy' else None
        if action in ('defense_place','defense_upgrade','defense_refill','defense_repair'):
            from game.missile_defense import change_defense_system
            change_defense_system(session,country.PANSTWO_ID,action,data)
            return
        if action in ('sail','sail_carrier','return_vessel','redirect_vessel','rename_vessel'):
            from game.military_navy import change_vessel
            change_vessel(session,country.PANSTWO_ID,action,data,game_now())
            return
        base_id = natural(data.get('base_id'),'Baza',1)
        base = next((base for base in bases if base.id == base_id),None)
        if base is None:
            raise FinanceError('Baza nie należy do państwa gracza.')
        from game.land_war import require_usable_base
        require_usable_base(session,base.id)
        from game.military_flights import busy_fighters
        busy=busy_fighters(session,base.id)
        from game.military_navy import busy_vessels,returning_reservations
        deployed={kind:busy_vessels(session,base.id,kind) for kind in ('warships','submarines')} if base.kind=='naval' else {}
        incoming={kind:returning_reservations(session,base.id,kind) for kind in ('warships','submarines')} if base.kind=='naval' else {}
        if action=='rename':
            name=data.get('name')
            if not isinstance(name,str) or not 1<=len(name.strip())<=120 or any(ord(c)<32 for c in name):raise FinanceError('Nazwa bazy musi mieć od 1 do 120 znaków.')
            base.name=name.strip()
        elif action == 'location':
            from math import isfinite
            from game.military_geography import region_contains
            x,y=data.get('x'),data.get('y')
            if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not isfinite(v) for v in (x,y)):
                raise FinanceError('Nieprawidłowe współrzędne bazy.')
            if any(incoming.values()) or any(deployed.values()):raise FinanceError('Zaczekaj na powrót okrętów przed przeniesieniem bazy.')
            if busy:
                raise FinanceError('Zaczekaj na powrót myśliwca przed przeniesieniem bazy.')
            if not region_contains(base.region_id,x,y):
                raise FinanceError('Lokalizacja bazy musi znajdować się wewnątrz jej regionu.')
            if base.kind=='naval':
                from game.military_geography import naval_location_allowed
                from game.military_flights import calibration
                region=session.scalar(select(Region).options(lazyload('*')).where(Region.region_id==base.region_id))
                if region.region_polozenie_id in (None,1) or not naval_location_allowed(base.region_id,x,y,calibration(session).km_per_unit):
                    raise FinanceError('Baza morska musi leżeć wewnątrz nadmorskiego regionu, najwyżej 3 km od jego wybrzeża.')
            base.map_x,base.map_y=x,y
        elif action == 'garrison':
            requested = data.get('garrison')
            if not isinstance(requested,dict) or set(requested) - set(capacities(base)):
                raise FinanceError('Nieprawidłowe zasoby dla wybranego rodzaju bazy.')
            result = {}
            for resource,capacity in capacities(base).items():
                count = natural(requested.get(resource,0),RESOURCES[resource][0])
                field = BASES[base.kind][2] if resource == 'soldiers' else RESOURCES[resource][1]
                available = (getattr(army,field) or 0) - active.get(field,0) + base.garrison.get(resource,0)
                if count < deployed.get(resource,0) or count+incoming.get(resource,0)>capacity:raise FinanceError('Uwzględnij okręty w rejsie i miejsca zarezerwowane na ich powrót.')
                if count > capacity or count > available:
                    raise FinanceError('Przekroczona pojemność bazy lub dostępne zasoby: ' + RESOURCES[resource][0])
                result[resource] = count
            if result.get("fighters",0)<busy:
                raise FinanceError("Nie można wycofać myśliwców wykonujących misję.")
            base.garrison = result
        elif action == 'withdraw':
            if any(deployed.values()):raise FinanceError('Zaczekaj na powrót okrętów przed wycofaniem garnizonu.')
            if busy:
                raise FinanceError('Zaczekaj na powrót myśliwców przed wycofaniem garnizonu.')
            base.garrison = {}
        elif action == 'upgrade':
            if base.level >= 7:
                raise FinanceError('Baza osiągnęła maksymalny poziom 7.')
            target = base.level + 1
            if any(count > CAPACITIES[base.kind][target-1].get(resource,0) for resource,count in base.garrison.items()):
                raise FinanceError('Przed zmianą poziomu wycofaj zasoby przekraczające pojemność docelowej bazy.')
            budget,total,available = military_budget(session,country.PANSTWO_ID)
            cost = UPGRADE_COSTS[target]*(2 if base.kind=='nuclear' else 1)
            if budget is None or available < cost:
                raise FinanceError('Za mało środków w budżecie sił zbrojnych na bieżące półrocze.')
            base.level = target
            session.add(MilitaryExpense(panstwo_id=country.PANSTWO_ID,budget_id=budget.id,base_id=base.id,level=target,amount=cost))
        elif action == 'cancel_deploy':
            # Rezygnacja ze stawiania nowej bazy (12 Nov 2026): tylko baza bez lokalizacji; garnizon wraca do puli,
            # miejsce na bazę nie przepada (inaczej niż przy likwidacji), a koszt budowy silosu wraca do budżetu.
            if base.map_x is not None or base.map_y is not None:raise FinanceError('Bazę z lokalizacją można jedynie zlikwidować.')
            for expense in session.scalars(select(MilitaryExpense).where(MilitaryExpense.base_id==base.id)):session.delete(expense)
            from game.military_destruction import detach_base
            detach_base(session,base)
            session.delete(base)
        elif action == 'liquidate':
            # Likwidacja bazy (11 Nov 2026): garnizon wraca do zasobów państwa, liczba baz tego rodzaju maleje o 1,
            # koszty budowy i rozbudowy nie są zwracane; obrona przeciwrakietowa bazy zostaje usunięta.
            if any(deployed.values()) or any(incoming.values()):raise FinanceError('Zaczekaj na powrót okrętów przed likwidacją bazy.')
            if busy:raise FinanceError('Zaczekaj na powrót myśliwców przed likwidacją bazy.')
            from game.land_war_models import LandArmy
            if session.scalar(select(LandArmy.id).where(LandArmy.source_base_id==base.id,LandArmy.status=='DEFENDING').limit(1)) is not None:
                raise FinanceError('Najpierw wycofaj do bazy oddziały broniące miast, wysłane z tej bazy.')
            field=BASES[base.kind][1]
            if field:setattr(army,field,max(0,(getattr(army,field) or 0)-1))
            from game.military_destruction import detach_base
            detach_base(session,base)
            session.delete(base)
        else:
            raise FinanceError('Nieprawidłowa operacja.')
        session.flush()
        reconcile_maintenance(session,country.PANSTWO_ID)



def reconcile_maintenance(session,country_id,now=None):
    """Bieżące zobowiązanie półroczne, z proporcjonalną redukcją zasobów."""
    from models import Panstwo
    from game.models import GamePlayerCountry,utc_now
    from game.forum_models import GameNotification
    from game.military_models import MilitaryVessel
    from game.military_navy import settle_vessels
    moment=now or game_now();year,period=period_key(moment)
    # 13 Nov 2026: stawki utrzymania są półroczne — w kwartale połowa (roczny koszt bez zmian)
    scale=Decimal(period_months(year,period))/6
    session.scalar(select(Panstwo.PANSTWO_ID).where(Panstwo.PANSTWO_ID==country_id).with_for_update())
    bases=list(session.scalars(select(MilitaryBase).where(MilitaryBase.panstwo_id==country_id).order_by(MilitaryBase.id).with_for_update()))
    settle_vessels(session,moment,country_id)
    army=army_for_country(session, country_id, lock=True)
    heads=(army.bron_atomowa_ilosc or 0) if army else 0
    orphans=list(session.scalars(select(MilitaryVessel).where(MilitaryVessel.panstwo_id==country_id,MilitaryVessel.base_id.is_(None),MilitaryVessel.kind!='carriers',MilitaryVessel.status.in_(['sailing','stationed','returning'])).with_for_update()))
    if not bases and not heads and not orphans:return
    def notify(text):
        owner=country_user_id(session,country_id)
        if owner is not None:session.add(GameNotification(user_id=owner,notification_type='SYSTEM',system_text=text,created_at=utc_now()))
    record=session.scalar(select(MilitaryMaintenance).where(MilitaryMaintenance.panstwo_id==country_id,MilitaryMaintenance.game_year==year,MilitaryMaintenance.period==period).with_for_update())
    budget,total,available=military_budget(session,country_id,moment)
    spent=session.scalar(select(func.coalesce(func.sum(MilitaryExpense.amount),0)).where(MilitaryExpense.budget_id==budget.id)) if budget else Decimal(0)
    if budget:spent+=session.scalar(select(func.coalesce(func.sum(MissileDefenseExpense.amount),0)).where(MissileDefenseExpense.budget_id==budget.id))
    if budget:
        from game.land_war import spent as land_war_spent
        from game.military_training import spent as training_spent
        from game.radar import spent as radar_spent
        spent+=land_war_spent(session,budget.id)+training_spent(session,budget.id)+radar_spent(session,budget.id)
    affordable=max(Decimal(0),total-spent)
    # Annual silo maintenance is split equally between two half-years.
    fixed=0
    for base in bases:
        if base.kind!='nuclear':continue
        enabled=affordable-fixed>=500000000*scale
        if base.operational and not enabled:notify(f'Silos {base.name or "#"+str(base.id)} został czasowo wyłączony: brak środków na utrzymanie.')
        base.operational=enabled
        if enabled:fixed+=500000000*scale
    affordable-=fixed
    from game.base_permits import own_region_ids,ABROAD_UPKEEP
    own=own_region_ids(session,country_id)
    factor={base.id:(ABROAD_UPKEEP if base.region_id is not None and base.region_id not in own else 1) for base in bases}   # baza za granicą: 2× utrzymanie
    items=[(base.id,resource,count,UPKEEP_RATES[resource]*factor[base.id]*scale) for base in bases for resource,count in base.garrison.items() if resource!='warheads']
    items.extend((-v.id,v.kind,1,UPKEEP_RATES[v.kind]*scale) for v in orphans)
    if heads:items.append((0,'warheads',heads,UPKEEP_RATES['warheads']*scale))
    cost=sum(count*rate for _,_,count,rate in items)
    if cost>affordable:
        ratio=affordable/Decimal(cost);reduced={};remainders=[];used=0
        for base_id,resource,count,rate in items:
            raw=Decimal(count)*ratio;value=int(raw);reduced[(base_id,resource)]=value;used+=value*rate
            if value<count:remainders.append((raw-value,base_id,resource,rate))
        for fraction,base_id,resource,rate in sorted(remainders,key=lambda item:(-item[0],item[1],item[2])):
            if used+rate<=affordable:reduced[(base_id,resource)]+=1;used+=rate
        for base in bases:
            base.garrison={resource:reduced.get((base.id,resource),count) for resource,count in base.garrison.items()}
        if army is not None:army.bron_atomowa_ilosc=reduced.get((0,'warheads'),heads)
        remaining=army.bron_atomowa_ilosc if army else 0
        # Loaded warheads form a subset of the national stock, never a second charge.
        for base in bases:
            if base.kind=='nuclear':
                count=min(base.garrison.get('warheads',0),remaining);remaining-=count
                base.garrison={**base.garrison,'warheads':count}
        # Automatic budget withdrawals also release the corresponding vessels.
        for base in bases:
            if base.kind!='naval':continue
            for kind in ('warships','submarines'):
                vessels=list(session.scalars(select(MilitaryVessel).where(MilitaryVessel.base_id==base.id,MilitaryVessel.kind==kind,MilitaryVessel.status.in_(['sailing','stationed','returning'])).order_by(MilitaryVessel.id).with_for_update()))
                for vessel in vessels[base.garrison.get(kind,0):]:vessel.status='docked'
        for vessel in orphans:
            if reduced.get((-vessel.id,vessel.kind),0)==0:vessel.status='docked'
        cost=used
        notify('Brakuje pieniędzy na utrzymanie wojska. System proporcjonalnie wycofał z baz żołnierzy i sprzęt oraz zmniejszył zapas głowic atomowych, aby koszt mieścił się w budżecie sił zbrojnych.')
    if record is None:
        record=MilitaryMaintenance(panstwo_id=country_id,game_year=year,period=period,amount=0);session.add(record)
    record.budget_id=budget.id if budget else None;record.amount=cost+fixed;record.assessed_at=utc_now()
    session.flush()


MISSILES = {'short':('rakiety_krotkiego_zasiegu','Rakiety krótkiego zasięgu'),
            'medium':('rakiety_sredniego_zasiegu','Rakiety średniego zasięgu'),
            'long':('rakiety_dalekiego_zasiegu','Rakiety dalekiego zasięgu')}


def land_targets(session,country_id):
    from game.military_geography import region_adjacency
    own_regions = set(session.scalars(select(Region.region_id).where(Region.panstwo_id.in_(controlled_ids(session, country_id)))))
    # W fazie 1 atak nie przenosi wojsk ani nie zajmuje wrogich regionów.
    occupied = {base.region_id for base in session.scalars(select(MilitaryBase).where(MilitaryBase.panstwo_id == country_id)) if base.garrison.get('soldiers',0)>0}
    neighbors = region_adjacency()
    return sorted(set().union(*(neighbors.get(region,set()) for region in own_regions|occupied)) - own_regions)


def create_order(user_id,data):
    from game.military_models import MilitaryOrder
    from game.infrastructure_service import FIELDS
    if sum(data.get(key) is not None for key in ('city_id','target_base_id','target_vessel_id','target_mine_id','target_defense_id','target_shipment_id','target_factory_id','target_power_id','target_radar_id'))>1:raise FinanceError('Wybierz dokładnie jeden obiekt celu.')
    with Session(db.engine) as session, session.begin():
        country = _country_for_user(session,user_id,lock=data.get('target_shipment_id') is None and data.get('target_factory_id') is None and data.get('target_power_id') is None)
        if data.get('target_shipment_id') is not None:
            from game.commerce_models import TradeShipment
            target_id=natural(data.get('target_shipment_id'),'Statek handlowy',1)
            actors=session.execute(select(TradeShipment.seller_id,TradeShipment.buyer_id).where(TradeShipment.id==target_id)).one_or_none()
            if actors is None:raise FinanceError('Nie znaleziono statku handlowego.')
            involved=sorted({country.PANSTWO_ID,*actors})
            list(session.scalars(select(Panstwo.PANSTWO_ID).where(Panstwo.PANSTWO_ID.in_(involved)).order_by(Panstwo.PANSTWO_ID).with_for_update()))
            country=_country_for_user(session,user_id,lock=True)
        if data.get('target_power_id') is not None:
            from game.industry_models import PowerPlant
            owner=session.scalar(select(PowerPlant.panstwo_id).where(PowerPlant.id==natural(data.get('target_power_id'),'Elektrownia',1)))
            if owner is None:raise FinanceError('Nie znaleziono elektrowni.')
            list(session.scalars(select(Panstwo.PANSTWO_ID).where(Panstwo.PANSTWO_ID.in_(sorted({country.PANSTWO_ID,owner}))).order_by(Panstwo.PANSTWO_ID).with_for_update()))
        if data.get('target_factory_id') is not None:
            from game.research_models import AmmunitionFactory
            factory_id=natural(data.get('target_factory_id'),'Fabryka celu',1)
            owner=session.scalar(select(AmmunitionFactory.panstwo_id).where(AmmunitionFactory.id==factory_id))
            if owner is None:raise FinanceError('Nie znaleziono fabryki.')
            involved=sorted({country.PANSTWO_ID,owner})
            list(session.scalars(select(Panstwo.PANSTWO_ID).where(Panstwo.PANSTWO_ID.in_(involved)).order_by(Panstwo.PANSTWO_ID).with_for_update()))
            country=_country_for_user(session,user_id,lock=True)
        if data.get('target_radar_id') is not None:
            from game.radar_models import Radar
            radar_owner=session.scalar(select(Radar.panstwo_id).where(Radar.id==natural(data.get('target_radar_id'),'Radar celu',1)))
            if radar_owner is None:raise FinanceError('Nie znaleziono radaru.')
            list(session.scalars(select(Panstwo.PANSTWO_ID).where(Panstwo.PANSTWO_ID.in_(sorted({country.PANSTWO_ID,radar_owner}))).order_by(Panstwo.PANSTWO_ID).with_for_update()))
        enemy_ids = enemies(session,country.PANSTWO_ID)
        if not enemy_ids:
            raise FinanceError('Państwo nie znajduje się w stanie wojny.')
        from game.military_models import MilitaryVessel,MissileDefense
        from game.commerce_models import Mine,TradeShipment
        special_target=None;shipment_target=None
        if data.get('target_shipment_id') is not None:
            from game.trade_navigation import target_country
            shipment_target=session.scalar(select(TradeShipment).where(TradeShipment.id==target_id).with_for_update())
            if shipment_target is None or shipment_target.health<=0 or shipment_target.sunk_at is not None or shipment_target.delivered_at is not None or not shipment_target.starts_at<=game_now()<shipment_target.arrives_at:raise FinanceError('Statek handlowy nie znajduje się już w rejsie.')
            target_country(session,shipment_target,country.PANSTWO_ID)
            port=session.scalar(select(Miasto).options(lazyload('*')).where(Miasto.miasto_id==shipment_target.departure_port_id))
            if port is None:raise FinanceError('Brak portu macierzystego statku.')
            region_id=port.region_id
        elif data.get('target_radar_id') is not None:
            from game.radar_models import Radar
            special_target=session.scalar(select(Radar).where(Radar.id==natural(data.get('target_radar_id'),'Radar celu',1)).with_for_update())
            if special_target is None or special_target.health<=0:raise FinanceError('Wybierz istniejący, sprawny radar.')
            region_id=special_target.region_id
        elif data.get('target_power_id') is not None:
            from game.industry_models import PowerPlant
            from game.intelligence_service import known_ids
            special_target=session.scalar(select(PowerPlant).where(PowerPlant.id==natural(data.get('target_power_id'),'Elektrownia celu',1)).with_for_update())
            if special_target is None or special_target.health<=0 or special_target.removed_at is not None:raise FinanceError('Wybierz istniejącą elektrownię.')
            if special_target.id not in known_ids(session,country.PANSTWO_ID,'power'):raise FinanceError('Brak informacji wywiadowczych o położeniu elektrowni.')
            region_id=special_target.region_id
        elif data.get('target_factory_id') is not None:
            special_target=session.scalar(select(AmmunitionFactory).where(AmmunitionFactory.id==factory_id).with_for_update())
            if special_target is None or special_target.health<=0 or special_target.destroyed_at is not None or special_target.removed_at is not None:raise FinanceError('Wybierz istniejącą, sprawną fabrykę.')
            region_id=special_target.region_id
        elif data.get('target_base_id') is not None:
            special_target=session.get(MilitaryBase,natural(data.get('target_base_id'),'Baza celu',1))
            if special_target is None or special_target.health<=0 or special_target.map_x is None:raise FinanceError('Wybierz istniejącą, sprawną bazę na mapie.')
            region_id=special_target.region_id
        elif data.get('target_vessel_id') is not None:
            special_target=session.get(MilitaryVessel,natural(data.get('target_vessel_id'),'Okręt celu',1))
            if special_target is None or special_target.health<=0 or special_target.status not in ('sailing','stationed','returning'):raise FinanceError('Okręt celu nie znajduje się na morzu.')
            home=session.get(MilitaryBase,special_target.base_id) if special_target.base_id else None
            region_id=home.region_id if home else special_target.region_id
        elif data.get('target_defense_id') is not None:
            special_target=session.get(MissileDefense,natural(data.get('target_defense_id'),'Obrona celu',1))
            if special_target is None or special_target.health<=0:raise FinanceError('Wybierz istniejącą, sprawną obronę przeciwrakietową.')
            region_id=special_target.region_id
        elif data.get('target_mine_id') is not None:
            special_target=session.get(Mine,natural(data.get('target_mine_id'),'Kopalnia celu',1))
            if special_target is None or special_target.health<=0:raise FinanceError('Wybierz istniejącą kopalnię.')
            region_id=special_target.region_id
        else:region_id = natural(data.get('region_id'),'Region',1)
        if isinstance(special_target,MilitaryBase):
            from game.intelligence_service import known_ids
            if special_target.id not in known_ids(session,country.PANSTWO_ID,'bases'):raise FinanceError('Brak informacji wywiadowczych o położeniu tej bazy.')
        if isinstance(special_target,MissileDefense):
            from game.intelligence_service import known_ids
            if special_target.id not in known_ids(session,country.PANSTWO_ID,'defenses'):raise FinanceError('Brak informacji wywiadowczych o położeniu tej obrony.')
        if isinstance(special_target,Mine):
            from game.intelligence_service import known_ids
            if special_target.id not in known_ids(session,country.PANSTWO_ID,'mines'):raise FinanceError('Brak informacji wywiadowczych o położeniu tej kopalni.')
        if special_target is not None and controller_id(session,special_target.panstwo_id) not in enemy_ids:raise FinanceError('Cel nie należy do państwa, z którym trwa wojna.')
        if sum(data.get(key) is not None for key in ('city_id','target_base_id','target_vessel_id','target_mine_id','target_defense_id','target_shipment_id','target_factory_id','target_power_id','target_radar_id'))>1:raise FinanceError('Wybierz dokładnie jeden obiekt celu.')
        target = session.scalar(select(Region).options(lazyload('*')).where(Region.region_id == region_id))
        if target is None or (shipment_target is None and controller_id(session,target.panstwo_id) not in enemy_ids):
            raise FinanceError('Wybrany region nie należy do państwa, z którym trwa wojna.')
        kind = data.get('kind')
        if kind not in ('air','missile','naval','land'):
            raise FinanceError('Nieprawidłowy rodzaj ataku.')
        if (special_target is not None or shipment_target is not None) and kind=='land':raise FinanceError('Wybierz bombardowanie z powietrza, lądu lub okrętu.')
        army = army_for_country(session, country.PANSTWO_ID, lock=True)
        if army is None:
            raise FinanceError('Brak zasobów wojskowych.')
        if kind == 'naval' and not data.get('vessel_id') and (target.region_polozenie_id in (None,1) or (army.okrety_wojenne_ilosc or 0)<1):
            raise FinanceError('Atak z okrętu wymaga okrętu wojennego i nadmorskiego regionu celu.')
        from game.military_navy import settle_vessels
        settle_vessels(session,game_now(),country.PANSTWO_ID)
        payload = {}
        if kind == 'land':
            if region_id not in land_targets(session,country.PANSTWO_ID):
                raise FinanceError('Region nie graniczy z własnym terytorium ani regionem obsadzonym przez nasze wojska.')
            for resource,field in [('soldiers','wojska_ladowe_ilosc'),('tanks','czolgi_ilosc'),('armored','wozy_opancerzone_ilosc')]:
                count = natural(data.get(resource,0),RESOURCES[resource][0])
                if count > (getattr(army,field) or 0):
                    raise FinanceError('Brak wystarczających zasobów: '+RESOURCES[resource][0])
                payload[resource] = count
            if not any(payload.values()):
                raise FinanceError('Wybierz żołnierzy lub sprzęt do wysłania.')
        else:
            missile_type = data.get('missile_type')
            if not isinstance(missile_type,str) or missile_type not in MISSILES:
                raise FinanceError('Wybierz rodzaj rakiet.')
            count = natural(data.get('missiles'),'Liczba rakiet',1)
            if count > (getattr(army,MISSILES[missile_type][0]) or 0):
                raise FinanceError('Brak wystarczającego zapasu wybranych rakiet.')
            infrastructure = data.get('infrastructure')
            if data.get('city_id') is None and data.get('target_base_id') is None and data.get('target_vessel_id') is None and data.get('target_mine_id') is None and data.get('target_defense_id') is None and data.get('target_shipment_id') is None and data.get('target_factory_id') is None and data.get('target_power_id') is None and data.get('target_radar_id') is None and (not isinstance(infrastructure,str) or infrastructure not in FIELDS):
                raise FinanceError('Wybierz rodzaj infrastruktury.')
            payload = dict(missile_type=missile_type,missiles=count,infrastructure=infrastructure)
        order=MilitaryOrder(panstwo_id=country.PANSTWO_ID,user_id=user_id,region_id=region_id,kind=kind,payload=payload)
        session.add(order);session.flush()
        if kind!='land':
            from game.military_flights import launch_flight
            flight_id=launch_flight(session,country.PANSTWO_ID,army,target,order,data)
            if data.get('is_nuclear'):reconcile_maintenance(session,country.PANSTWO_ID)
            return flight_id
        return None
