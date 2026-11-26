from game.paga_ai_actor import country_user_id
"""Budżet służb, misje agentów i jawne uprawnienia do danych wywiadu."""
from game.governance import controller_id, army_for_country
from datetime import timedelta
from decimal import Decimal
from secrets import randbelow
from uuid import UUID
from sqlalchemy import select,func,or_,and_
from sqlalchemy.orm import Session,lazyload
from extensions import db
from models import Panstwo,Region,Wojsko,RegionZasob,DictZasob
from game.finance_service import FinanceError,FinanceConflict,_country_for_user,game_now,period_key
from game.finance_models import StateBudget
from game.models import GamePlayerCountry,utc_now
from game.forum_models import GameNotification
from game.intelligence_models import IntelligenceAgent,IntelligenceMission,CounterIntelligence,IntelligenceExpense
from game.military_models import MilitaryBase,MissileDefense

AGENT_COSTS=(17050000,27800000,34200000,45000000,65500000,72300000,105900000)
AGENT_CHANCES=(15,25,35,45,60,75,90)
COUNTER_COSTS=(0,50000000,500000000,2000000000,5000000000,7000000000,10000000000)
COUNTER_PROTECTION=(5,10,20,35,50,65,75)
MISSION_COSTS=(50000000,200000000,400000000,600000000,800000000,1000000000,1200000000)
MISSIONS={'power':'Położenie elektrowni','bases':'Położenie baz wojskowych','defenses':'Obrona przeciwrakietowa',
          'nuclear':'Liczba głowic jądrowych','resources':'Zasoby naturalne regionu',
          'infrastructure':'Infrastruktura regionu','silos':'Rozmieszczenie silosów atomowych','mines':'Położenie kopalń','warehouses':'Stany magazynowe'}


HYBRID={
    'cyber_energy':('Cyberatak na infrastrukturę energetyczną','region_stan_infra_energetycznej','energia',3),
    'cyber_rail':('Cyberatak na infrastrukturę kolejową','region_stan_infra_kolejowej','kolej',3),
    'cyber_port':('Cyberatak na infrastrukturę portową','region_stan_infra_portowej','porty',3),
    'arson':('Podpalenie','region_stan_infra_mieszkalnej','mieszkania',1),
    'rail_explosive':('Ładunek wybuchowy na kolei','region_stan_infra_kolejowej','kolej',2),
}
MISSIONS.update({key:label for key,(label,_,_,_) in HYBRID.items()})


def mission_days(kind):
    return 2 if kind in HYBRID else 4


def hybrid_report(session,mission,success,now):
    from models import RegionStateHistory
    region=session.scalar(select(Region).options(lazyload('*')).where(Region.region_id==mission.region_id).with_for_update())
    if region is None or controller_id(session,region.panstwo_id)!=mission.target_country_id:
        mission.success=False
        return {'invalid_target':True,'entries':[{'label':'Wynik','value':'Region zmienił właściciela. Działania anulowane, agent wraca.'}]}
    label,field,history_field,loss=HYBRID[mission.kind]
    if not success:return {'entries':[{'label':'Wynik','value':'Działania hybrydowe nie powiodły się. Infrastruktura bez zmian.'}]}
    old=getattr(region,field)
    if old is None:
        mission.success=False
        return {'entries':[{'label':'Wynik','value':'Brak danych infrastruktury. Nie wykonano sabotażu.'}]}
    new=max(0,old-loss);setattr(region,field,new)
    session.add(RegionStateHistory(region_id=region.region_id,data_entenda=mission.ends_at,data_rzeczywista=utc_now(),source='HYBRID',**{'old_'+history_field:old,'new_'+history_field:new}))
    return {'damage':{'field':field,'before':old,'after':new,'loss':old-new},'entries':[{'label':label,'value':f'{old} → {new} (spadek o {old-new}).'}]}


def counter_level(session,country_id):
    return session.scalar(select(CounterIntelligence.level).where(CounterIntelligence.panstwo_id==country_id)) or 1


def intelligence_budget(session,country_id,now=None):
    from game.budget_transfers import effective_allocation
    year,period=period_key(now or game_now())
    budget=session.scalar(select(StateBudget).where(StateBudget.panstwo_id==country_id,StateBudget.game_year==year,StateBudget.period==period))
    if budget is None:return None,Decimal(0),Decimal(0)
    total=effective_allocation(session,budget.id,'security_services')
    spent=session.scalar(select(func.coalesce(func.sum(IntelligenceExpense.amount),0)).where(IntelligenceExpense.budget_id==budget.id)) or Decimal(0)
    from game.crime_funding import CrimeFunding   # 16 Nov 2026: środki na walkę z przestępczością są już rozdysponowane
    spent+=session.scalar(select(func.coalesce(func.sum(CrimeFunding.paid),0)).where(CrimeFunding.budget_id==budget.id)) or Decimal(0)
    return budget,total,max(Decimal(0),total-spent)


def operate(user_id,data):
    with Session(db.engine) as session,session.begin():
        country=_country_for_user(session,user_id,lock=True)
        return operate_in_transaction(session,country.PANSTWO_ID,data)


def operate_in_transaction(session,country_id,data,now=None,*,dry_run=False):
    from game.military_service import natural
    try:request_id=str(UUID(data.get('request_id')))
    except (ValueError,TypeError,AttributeError):raise FinanceError('Nieprawidłowy identyfikator operacji.') from None
    action=data.get('action');payload={key:value for key,value in data.items() if key!='request_id'}
    if session.scalar(select(Panstwo.PANSTWO_ID).where(Panstwo.PANSTWO_ID==country_id,Panstwo.status=="aktywne").with_for_update()) is None:raise FinanceError("Nie znaleziono państwa.")
    if action=='rename':
        from unicodedata import category
        name=data.get('name')
        if not isinstance(name,str) or any(category(char).startswith('C') for char in name):raise FinanceError('Podaj poprawne imię i nazwisko agenta.')
        name=' '.join(name.split())
        if not 3<=len(name)<=100 or len(name.split())<2:raise FinanceError('Podaj imię i nazwisko agenta (3–100 znaków).')
        agent=session.scalar(select(IntelligenceAgent).where(IntelligenceAgent.id==natural(data.get('agent_id'),'Agent',1),IntelligenceAgent.panstwo_id==country_id).with_for_update())
        if agent is None:raise FinanceError('Agent nie należy do gracza.')
        agent.name=name
        return
    existing=session.scalar(select(IntelligenceExpense).where(IntelligenceExpense.panstwo_id==country_id,IntelligenceExpense.request_id==request_id))
    if existing:
        if existing.payload!=payload:raise FinanceConflict('Identyfikator operacji został już wykorzystany.')
        return
    now=now or game_now();budget,total,available=intelligence_budget(session,country_id,now)
    if action=='recruit':
        level=natural(data.get('level'),'Poziom agenta',1);count=natural(data.get('count'),'Liczba agentów',1)
        if level>7 or count>1000:raise FinanceError('Poziom musi wynosić 1–7, a liczba agentów 1–1000.')
        cost=AGENT_COSTS[level-1]*count
    elif action=='counter_upgrade':
        level=counter_level(session,country_id)
        if natural(data.get('expected_level'),'Poziom ochrony',1)!=level:raise FinanceConflict('Poziom ochrony zmienił się. Odśwież ekran.')
        if level>=7:raise FinanceError('Ochrona osiągnęła maksymalny poziom 7.')
        cost=COUNTER_COSTS[level]
    elif action=='mission':
        kind=data.get('kind')
        if not isinstance(kind,str) or kind not in MISSIONS:raise FinanceError('Wybierz dostępną misję.')
        agent=session.scalar(select(IntelligenceAgent).where(IntelligenceAgent.id==natural(data.get('agent_id'),'Agent',1),IntelligenceAgent.panstwo_id==country_id).with_for_update())
        if agent is None:raise FinanceError('Agent nie należy do gracza.')
        if agent.captured_at is not None:raise FinanceError('Agent został schwytany i nie jest dostępny.')
        if session.scalar(select(IntelligenceMission.id).where(IntelligenceMission.agent_id==agent.id,IntelligenceMission.completed_at.is_(None))):raise FinanceError('Agent już wykonuje misję.')
        region=None
        if kind=='warehouses':
            target_id=natural(data.get('country_id'),'Państwo',1)
            target=session.execute(select(Panstwo.PANSTWO_ID,Panstwo.panstwo_nazwa).where(Panstwo.PANSTWO_ID==target_id,Panstwo.status=='aktywne')).first()
            if target is None or target_id==country_id or controller_id(session,target_id)!=target_id:raise FinanceError('Wybierz inne suwerenne państwo.')
            if data.get('region_id') is not None:raise FinanceError('Stany magazynowe rozpoznaje się dla całego państwa, bez wskazywania regionu.')
            target_name=target.panstwo_nazwa
        else:
            region=session.scalar(select(Region).options(lazyload('*')).where(Region.region_id==natural(data.get('region_id'),'Region',1)))
            if region is None or controller_id(session,region.panstwo_id) in (None,country_id):raise FinanceError('Wybierz region innego państwa.')
            if kind=='cyber_port' and region.region_polozenie_id in (None,1):raise FinanceError('Cyberatak portowy wymaga regionu nadmorskiego.')
            target_id=controller_id(session,region.panstwo_id);target_name=region.region_nazwa
        cost=MISSION_COSTS[agent.level-1]
    else:raise FinanceError('Nieprawidłowa operacja wywiadowcza.')
    if budget is None or available<cost:raise FinanceError('Za mało środków w budżecie służb specjalnych i porządkowych na bieżący okres budżetowy.')
    if dry_run:return {'cost':str(cost),'budget_id':budget.id}
    mission=None
    if action=='recruit':
        session.add_all(IntelligenceAgent(panstwo_id=country_id,level=level) for _ in range(count))
    elif action=='counter_upgrade':
        record=session.get(CounterIntelligence,country_id)
        if record is None:record=CounterIntelligence(panstwo_id=country_id,level=1);session.add(record)
        record.level=level+1
    else:
        mission=IntelligenceMission(panstwo_id=country_id,agent_id=agent.id,region_id=region.region_id if region else None,target_country_id=target_id,region_name=target_name,kind=kind,starts_at=now,ends_at=now+timedelta(days=mission_days(kind)))
        session.add(mission)
    session.add(IntelligenceExpense(panstwo_id=country_id,budget_id=budget.id,amount=cost,request_id=request_id,payload=payload))
    session.flush()
    return mission.id if mission else None


def collect_report(session,mission):
    from game.infrastructure_service import FIELDS
    from game.military_geography import city_point,region_point
    from game.missile_defense import defense_data
    from models import Miasto
    if mission.kind=='warehouses':
        if controller_id(session,mission.target_country_id)!=mission.target_country_id:
            return {'invalid_target':True,'entries':[{'label':'Wynik','value':'Państwo utraciło suwerenność. Nie uzyskano danych.'}]}
        from game.trade_goods import trade_warehouse
        from services.natural_resources import RESOURCES
        from game.industry_catalog import GOODS
        labels={**dict(RESOURCES),**{code:rule[0] for code,rule in GOODS.items()},'interceptor_ammunition':'Amunicja przeciwrakietowa','nuclear_missiles':'Rakiety z głowicą nuklearną','spy_satellites':'Satelity szpiegowskie'}
        snapshot=trade_warehouse(session,mission.target_country_id)
        from game.commerce_models import ResourceStock
        for stock in session.scalars(select(ResourceStock).where(ResourceStock.panstwo_id==mission.target_country_id)):
            if stock.resource not in snapshot:snapshot[stock.resource]={'available':int(stock.quantity),'reserved':0,'total':int(stock.quantity)}
        return {'scope':'country','country_id':mission.target_country_id,'warehouse':snapshot,'entries':[
            {'label':labels.get(code,code),'value':f'Dostępne: {values["available"]}; zarezerwowane: {values["reserved"]}; razem: {values["total"]}'} for code,values in snapshot.items()]}
    region=session.scalar(select(Region).options(lazyload('*')).where(Region.region_id==mission.region_id))
    report={'entries':[]};entries=report['entries']
    if region is None or controller_id(session,region.panstwo_id)!=mission.target_country_id:
        return {'invalid_target':True,'entries':[{'label':'Wynik','value':'Region zmienił właściciela. Nie uzyskano aktualnych danych.'}]}
    if mission.kind in ('bases','silos'):
        # 12 Nov 2026: rozpoznanie obejmuje bazy wszystkich obcych państw w regionie (np. bazy sojuszników gospodarza), nie tylko właściciela.
        query=select(MilitaryBase).where(MilitaryBase.region_id==region.region_id,MilitaryBase.panstwo_id!=mission.panstwo_id)
        query=query.where(MilitaryBase.kind=='nuclear' if mission.kind=='silos' else MilitaryBase.kind!='nuclear')
        report['base_ids']=[]
        names=dict(session.execute(select(Panstwo.PANSTWO_ID,Panstwo.panstwo_nazwa)).all())
        for base in session.scalars(query.order_by(MilitaryBase.id)):
            if base.map_x is None:continue
            report['base_ids'].append(base.id)
            owner='' if base.panstwo_id==mission.target_country_id else f' — państwo {names.get(base.panstwo_id,base.panstwo_id)}'
            entries.append({'label':(base.name or f'Baza #{base.id}')+owner,'value':f'Poziom {base.level}. Lokalizacja mapy: {base.map_x:.3f}, {base.map_y:.3f}.'})
    elif mission.kind=='mines':
        from game.commerce_models import Mine
        from game.mining_service import mine_data
        report['mine_ids']=[]
        for mine in session.scalars(select(Mine).where(Mine.region_id==region.region_id,Mine.panstwo_id==mission.target_country_id).order_by(Mine.id)):
            report['mine_ids'].append(mine.id);data=mine_data(mine,game_now())
            entries.append({'label':data['name'],'value':f'Poziom 1. Lokalizacja mapy: {mine.map_x:.3f}, {mine.map_y:.3f}. Życie: {mine.health}/100.'})
    elif mission.kind=='power':
        from game.industry_models import PowerPlant
        from game.industry_catalog import POWER_PLANTS
        report['power_ids']=[]
        for plant in session.scalars(select(PowerPlant).where(PowerPlant.region_id==region.region_id,PowerPlant.panstwo_id==mission.target_country_id,PowerPlant.removed_at.is_(None))):
            report['power_ids'].append(plant.id)
            entries.append({'label':POWER_PLANTS[plant.kind]['label']+f' #{plant.id}','value':f'Poziom {plant.level}. Lokalizacja: {plant.map_x}, {plant.map_y}. Życie: {plant.health}/3.'})
    elif mission.kind=='defenses':
        report['defense_ids']=[]
        for defense in session.scalars(select(MissileDefense).where(MissileDefense.region_id==region.region_id,MissileDefense.panstwo_id==mission.target_country_id).order_by(MissileDefense.id)):
            report['defense_ids'].append(defense.id)
            data=defense_data(defense)
            entries.append({'label':{'base':'Baza','city':'Miasto','region':'Region'}[defense.target_kind]+f' #{defense.target_id}',
                            'value':f'Poziom {defense.level}. Życie {defense.health}%. Skuteczność {data["efficiency"]}%. Pociski: {defense.ammunition}/{data["capacity"]}. Lokalizacja mapy: '+(', '.join(f'{value:.3f}' for value in data['position']) if data['position'] else 'brak danych')})
    elif mission.kind=='nuclear':
        from game.nuclear import total
        count=total(session,mission.target_country_id)   # 13 Nov 2026: rzeczywista liczba rakiet z głowicą nuklearną
        loaded=sum(base.garrison.get('warheads',0) for base in session.scalars(select(MilitaryBase).where(MilitaryBase.region_id==region.region_id,MilitaryBase.kind=='nuclear',MilitaryBase.panstwo_id==mission.target_country_id)))
        entries.extend([{'label':'Zapas głowic jądrowych państwa','value':str(count)},{'label':'Głowice w silosach wybranego regionu','value':str(loaded)}])
    elif mission.kind=='resources':
        for name,unit,amount in session.execute(select(DictZasob.zasob_nazwa,DictZasob.zasob_jednostka,RegionZasob.zloze_ilosc).join(RegionZasob,RegionZasob.zasob_id==DictZasob.zasob_id).where(RegionZasob.region_id==region.region_id).order_by(DictZasob.zasob_id)):
            entries.append({'label':name,'value':f'{amount or 0} {unit}'})
    elif mission.kind=='infrastructure':
        labels={'road':'Drogowa','rail':'Kolejowa','energy':'Energetyczna','housing':'Mieszkaniowa','port':'Portowa','connection':'Skomunikowanie'}
        entries.extend({'label':labels[metric],'value':str(getattr(region,field)) if getattr(region,field) is not None else 'Brak danych'} for metric,field in FIELDS.items())
    if not entries:entries.append({'label':'Wynik','value':'Nie znaleziono obiektów tego rodzaju w regionie.'})
    return report


def complete_missions(session,now,country_id=None):
    query=select(IntelligenceMission).where(IntelligenceMission.completed_at.is_(None),IntelligenceMission.ends_at<=now)
    if country_id is not None:query=query.where(or_(IntelligenceMission.panstwo_id==country_id,and_(IntelligenceMission.target_country_id==country_id,IntelligenceMission.kind.in_(HYBRID))))
    due=list(session.execute(query.with_only_columns(IntelligenceMission.id,IntelligenceMission.panstwo_id,IntelligenceMission.target_country_id)))
    if not due:return
    ids={id for row in due for id in (row.panstwo_id,row.target_country_id)}
    list(session.scalars(select(Panstwo.PANSTWO_ID).where(Panstwo.PANSTWO_ID.in_(ids)).order_by(Panstwo.PANSTWO_ID).with_for_update()))
    for mission in session.scalars(query.where(IntelligenceMission.id.in_([row.id for row in due])).order_by(IntelligenceMission.id).with_for_update().execution_options(populate_existing=True)):
        agent=session.get(IntelligenceAgent,mission.agent_id)
        chance=AGENT_CHANCES[agent.level-1]*(100-COUNTER_PROTECTION[counter_level(session,mission.target_country_id)-1])
        mission.effective_chance=chance;mission.success=randbelow(10000)<chance
        if mission.kind in HYBRID:
            report=hybrid_report(session,mission,mission.success,now)
            captured=not mission.success and not report.get('invalid_target') and randbelow(100)<COUNTER_PROTECTION[counter_level(session,mission.target_country_id)-1]
            if captured:agent.captured_at=now
            mission.report={**report,'captured':bool(captured),'entries':[*report['entries'],{'label':'Agent','value':'Schwytany przez obce służby — nie wraca do kraju.' if captured else 'Agent wrócił do kraju.'}]}
        else:
            mission.report=collect_report(session,mission) if mission.success else {'entries':[{'label':'Wynik','value':'Nie zdobyto informacji. Agent wrócił i może podjąć kolejną misję.'}]}
        if mission.report.get('invalid_target'):mission.success=False
        mission.completed_at=now
        owner=country_user_id(session,mission.panstwo_id)
        if owner is not None:
            notice=GameNotification(user_id=owner,notification_type='SYSTEM',system_text=f'Wywiad wojskowy: {MISSIONS[mission.kind]} — {'państwo' if mission.kind=='warehouses' else 'region'} {mission.region_name}. '+('Misja zakończona powodzeniem.' if mission.success else 'Misja nie powiodła się.'),created_at=utc_now())
            session.add(notice);session.flush();mission.notification_id=notice.id
        if mission.kind in HYBRID:
            victim=country_user_id(session,mission.target_country_id)
            outcome='Sabotaż zakończony powodzeniem.' if mission.success else 'Próba sabotażu nie powiodła się.'
            capture=' Agent został schwytany przez służby kraju sabotowanego i nie wraca.' if mission.report.get('captured') else ' Agent wrócił do kraju.'
            damage=mission.report.get('damage')
            effect=f' Infrastruktura: {damage["before"]} → {damage["after"]}.' if damage else ''
            if owner is not None:notice.system_text+=capture+effect
            if victim is not None:session.add(GameNotification(user_id=victim,notification_type='SYSTEM',system_text=f'Działania hybrydowe: {MISSIONS[mission.kind]} — {'państwo' if mission.kind=='warehouses' else 'region'} {mission.region_name}. '+outcome+effect+(' Schwytano obcego agenta.' if mission.report.get('captured') else ''),created_at=utc_now()))
    session.flush()


def known_ids(session,country_id,kind):
    kinds={'bases':['bases','silos'],'defenses':['defenses'],'mines':['mines'],'power':['power']}[kind]
    key={'bases':'base_ids','defenses':'defense_ids','mines':'mine_ids','power':'power_ids'}[kind]
    known={int(id) for report in session.scalars(select(IntelligenceMission.report).where(IntelligenceMission.panstwo_id==country_id,IntelligenceMission.kind.in_(kinds),IntelligenceMission.success.is_(True),IntelligenceMission.completed_at.is_not(None))) for id in (report or {}).get(key,[])}
    # 26 Nov 2026: obiekty rozpoznane przez satelity szpiegowskie (całe państwo celu, zawsze skutecznie)
    from game.satellites import known_report_ids
    return known|known_report_ids(session,country_id,kinds,key)


def mission_details(mission):
    return {'title':MISSIONS[mission.kind]+' — '+mission.region_name,'success':mission.success,
            'date':mission.ends_at.strftime('%d.%m.%Y %H:%M'),'chance':f'{(mission.effective_chance or 0)/100:.2f}%',
            'entries':(mission.report or {}).get('entries',[]),'completed':mission.completed_at is not None}
