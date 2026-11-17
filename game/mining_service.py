"""Kopalnie poziomu 1: budowa, skończone złoża i wydobycie do magazynu."""
from game.governance import controlled_ids, controller_id
from datetime import timedelta
from math import isfinite
from uuid import UUID
from sqlalchemy import select,func
from sqlalchemy.orm import Session,lazyload
from extensions import db
from models import Panstwo,Region,RegionZasob,DictZasob
from services.natural_resources import RESOURCES,normalized
from game.finance_service import FinanceError,_country_for_user,game_now,period_key
from game.finance_models import StateBudget
from game.commerce_models import Mine,MiningExpense,ResourceStock,TradeOffer

from game.industry_catalog import MINE_RULES
RULES={code:(values[2][0]*1000000000,values[4]) for code,values in MINE_RULES.items()}
NAMES={code:values[0] for code,values in MINE_RULES.items()}
EXTRACTION_INTERVAL=timedelta(days=1)


def request_key(value):
    try:return str(UUID(value))
    except (ValueError,TypeError,AttributeError):raise FinanceError('Nieprawidłowy identyfikator operacji.') from None


def resource_ids(session):
    rows=list(session.execute(select(DictZasob.zasob_id,DictZasob.zasob_kod,DictZasob.zasob_nazwa)))
    result={}
    for code,label in RESOURCES:
        matches=[row[0] for row in rows if normalized(row[1])==normalized(code) or normalized(row[2])==normalized(label)]
        if len(matches)!=1:raise FinanceError('Słownik surowców wymaga sprawdzenia przez administratora.')
        result[code]=matches[0]
    return result


def stock(session,country_id,resource):
    item=session.scalar(select(ResourceStock).where(ResourceStock.panstwo_id==country_id,ResourceStock.resource==resource).with_for_update().execution_options(populate_existing=True))
    if item is None:item=ResourceStock(panstwo_id=country_id,resource=resource,quantity=0);session.add(item)
    return item


def mining_budget(session,country_id):
    from game.budget_transfers import infrastructure_balance
    year,period=period_key(game_now())
    budget=session.scalar(select(StateBudget).where(StateBudget.panstwo_id==country_id,StateBudget.game_year==year,StateBudget.period==period))
    if budget is None:return None,0,0
    total,available=infrastructure_balance(session,budget)
    return budget,total,available


def build_mine(user_id,data):
    from game.military_service import natural
    from game.military_geography import region_contains
    key=request_key(data.get('request_id'));resource=data.get('resource');x,y=data.get('x'),data.get('y')
    if not isinstance(resource,str) or resource not in RULES:raise FinanceError('Wybierz rodzaj kopalni.')
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not isfinite(v) for v in (x,y)):raise FinanceError('Nieprawidłowa lokalizacja kopalni.')
    with Session(db.engine) as session,session.begin():
        country=_country_for_user(session,user_id,lock=True);country_id=country.PANSTWO_ID
        existing=session.scalar(select(Mine).where(Mine.panstwo_id==country_id,Mine.request_id==key).with_for_update())
        if existing:
            if (existing.resource,existing.region_id,existing.map_x,existing.map_y)!=(resource,data.get('region_id'),x,y):raise FinanceError('Identyfikator operacji jest już wykorzystany.')
            return existing.id
        region=session.scalar(select(Region).options(lazyload('*')).where(Region.region_id==natural(data.get('region_id'),'Region',1)).with_for_update())
        from game.foreign_mining import allowed
        abroad=region is not None and controller_id(session,region.panstwo_id)!=country_id
        if region is None or (abroad and not allowed(session,country_id,region)) or not region_contains(region.region_id,x,y):raise FinanceError('Kopalnia musi znajdować się wewnątrz własnego regionu.')
        from game.nuclear import require_clear
        require_clear(session,x,y)   # 13 Nov 2026: strefa skażenia po uderzeniu atomowym
        from game.land_war import require_buildable
        require_buildable(session,region.region_id,country_id)
        from game.industry_service import require_technologies,ready_at,settle_industry
        require_technologies(session,country_id,[MINE_RULES[resource][1]])
        dictionary=resource_ids(session)
        deposit=session.scalar(select(RegionZasob).where(RegionZasob.region_id==region.region_id,RegionZasob.zasob_id==dictionary[resource]).with_for_update())
        if deposit is None or not deposit.zloze_ilosc:raise FinanceError('W tym regionie nie ma złoża wybranego surowca.')
        if type(data.get('level',1)) is not int or data.get('level',1)!=1:raise FinanceError('Kopalnię można zbudować tylko na poziomie 1.')
        settle_industry(session,country_id)
        budget,total,available=mining_budget(session,country_id);cost,days=RULES[resource]
        base_cost=cost
        if abroad:cost*=2
        if budget is None or available<cost:raise FinanceError('Za mało środków we wspólnym budżecie infrastruktury na bieżący okres budżetowy. Możesz przesunąć środki w formularzu zatwierdzonego budżetu.')
        now=game_now();ready=ready_at(now,days)
        mine=Mine(panstwo_id=country_id,region_id=region.region_id,resource=resource,map_x=x,map_y=y,health=100,level=1,investment=cost,starts_at=now,ready_at=ready,extracted_at=ready,request_id=key)
        session.add(mine);session.flush();session.add(MiningExpense(panstwo_id=country_id,budget_id=budget.id,mine_id=mine.id,amount=cost))
        from game.foreign_mining import POLLUTION
        from game.industry_service import change_pollution
        change_pollution(session,region.region_id,POLLUTION)
        mine.pollution_points=POLLUTION
        if abroad:
            from game.industry_models import IndustryMovement
            host=controller_id(session,region.panstwo_id)
            host_budget,_,_=mining_budget(session,host)
            if host_budget is None:raise FinanceError('Gospodarz musi mieć bieżący budżet infrastruktury.')
            session.add(IndustryMovement(panstwo_id=host,budget_id=host_budget.id,amount=-base_cost,request_id=key,payload={'foreign_mine_id':mine.id,'guest':country_id},sector='infrastructure'))
        return mine.id


def extract_country(session,country_id,now):
    session.scalar(select(Panstwo.PANSTWO_ID).where(Panstwo.PANSTWO_ID==country_id).with_for_update())
    region_ids=list(session.scalars(select(Mine.region_id).where(Mine.panstwo_id==country_id,Mine.health>0,Mine.removed_at.is_(None),Mine.extracted_at<=now-EXTRACTION_INTERVAL).distinct()))
    if not region_ids:return
    list(session.scalars(select(Region.region_id).where(Region.region_id.in_(region_ids)).order_by(Region.region_id).with_for_update()))
    dictionary=resource_ids(session)
    for mine in session.scalars(select(Mine).where(Mine.panstwo_id==country_id,Mine.health>0,Mine.removed_at.is_(None),Mine.extracted_at<=now-EXTRACTION_INTERVAL).order_by(Mine.id).with_for_update().execution_options(populate_existing=True)):
        region=session.scalar(select(Region).options(lazyload('*')).where(Region.region_id==mine.region_id))
        # Rail infrastructure of the region lengthens the time per extracted unit; below 10 nothing is extracted
        # (time still passes, so an improved railway does not release a backlog).
        from game.infrastructure_effects import extraction_time_factor
        factor=extraction_time_factor(region.region_stan_infra_kolejowej if region is not None else 0)
        if factor is None:
            mine.extracted_at=now;continue
        interval=EXTRACTION_INTERVAL*float(factor)
        periods=int((now-mine.extracted_at)//interval)
        if periods<1:continue
        if region is not None:
            deposit=session.scalar(select(RegionZasob).options(lazyload('*')).where(RegionZasob.region_id==mine.region_id,RegionZasob.zasob_id==dictionary[mine.resource]).with_for_update())
            quantity=min(periods*MINE_RULES[mine.resource][3][mine.level-1],max(0,deposit.zloze_ilosc or 0)) if deposit else 0
            if quantity:
                item=stock(session,country_id,mine.resource);item.quantity+=quantity;deposit.zloze_ilosc-=quantity
                if deposit.zloze_ilosc==0:
                    from game.industry_service import notify
                    affected=session.scalars(select(Mine).where(Mine.region_id==mine.region_id,Mine.resource==mine.resource,Mine.health>0,Mine.removed_at.is_(None),Mine.ready_at<=now))
                    for stopped in affected:notify(session,stopped.panstwo_id,NAMES[mine.resource]+f' #{stopped.id}: wydobycie zatrzymane — wyczerpano złoże w regionie.')
        mine.extracted_at+=interval*periods
    session.flush()


def warehouse(session,country_id):
    available={row.resource:int(row.quantity) for row in session.scalars(select(ResourceStock).where(ResourceStock.panstwo_id==country_id))}
    reserved={code:0 for code,_ in RESOURCES}
    for cargo in session.scalars(select(TradeOffer.cargo).where(TradeOffer.panstwo_id==country_id,TradeOffer.status=='open')):
        for code,quantity in cargo.items():
            if code in reserved:reserved[code]+=quantity
    return {code:{'available':available.get(code,0),'reserved':reserved[code],'total':available.get(code,0)+reserved[code]} for code,_ in RESOURCES}


def mine_data(mine,now):
    duration=(mine.ready_at-mine.starts_at).total_seconds()
    return {'id':mine.id,'countryId':mine.panstwo_id,'regionId':str(mine.region_id),'resource':mine.resource,'name':NAMES[mine.resource]+' #'+str(mine.id),
            'position':[mine.map_x,mine.map_y],'health':mine.health,'level':mine.level,'removed':mine.removed_at is not None,'refund':str(MINE_RULES[mine.resource][2][mine.level-1]*1000000000//4),'dailyExtraction':MINE_RULES[mine.resource][3][mine.level-1],'upgradeCost':str(MINE_RULES[mine.resource][2][mine.level]*1000000000) if mine.level<3 else None,'ready':mine.ready_at<=now,
            'readyAt':mine.ready_at.isoformat()+'Z','progress':min(100,max(0,int((now-mine.starts_at).total_seconds()/duration*100)))}
