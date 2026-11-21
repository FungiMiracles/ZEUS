"""Obrona regionów, miast i baz oraz finansowanie jej amunicji."""
from game.governance import controlled_ids, controller_id
from decimal import Decimal
from secrets import randbelow
from sqlalchemy import select
from sqlalchemy.orm import lazyload
from game.finance_service import FinanceError
from game.military_models import MissileDefense,MissileDefenseExpense,MilitaryBase
from models import Region,Miasto
from game.commerce_models import Mine
from game.research_models import AmmunitionFactory

CAPACITIES=(100,500,1000,2000,4500,6000,10000)
EFFICIENCIES=(30,45,55,65,75,85,95)
COSTS={1:100000000,2:500000000,3:750000000,4:1000000000,5:1250000000,6:1500000000,7:2000000000}
AMMUNITION_PRICE=15000


def owned_target(session,country_id,kind,target_id):
    from game.military_service import natural
    target_id=natural(target_id,'Cel obrony',1)
    if kind=='region':
        target=session.scalar(select(Region).options(lazyload('*')).where(Region.region_id==target_id,Region.panstwo_id.in_(controlled_ids(session, country_id))))
    elif kind=='city':
        target=session.scalar(select(Miasto).options(lazyload('*')).where(Miasto.miasto_id==target_id,Miasto.panstwo_id.in_(controlled_ids(session, country_id))))
    elif kind=='base':
        target=session.scalar(select(MilitaryBase).where(MilitaryBase.id==target_id,MilitaryBase.panstwo_id==country_id))
        if target and target.health<=0:raise FinanceError('Nie można dodać obrony do zniszczonej bazy.')
    elif kind=='mine':
        target=session.scalar(select(Mine).where(Mine.id==target_id,Mine.panstwo_id.in_(controlled_ids(session,country_id))))
        if target and target.health<=0:raise FinanceError('Nie można dodać obrony do zniszczonej kopalni.')
    elif kind=='factory':
        target=session.scalar(select(AmmunitionFactory).where(AmmunitionFactory.id==target_id,AmmunitionFactory.panstwo_id==country_id))
        if target and target.health<=0:raise FinanceError('Nie można dodać obrony do zniszczonej fabryki.')
    elif kind=='power':
        from game.industry_models import PowerPlant
        target=session.scalar(select(PowerPlant).where(PowerPlant.id==target_id,PowerPlant.panstwo_id==country_id,PowerPlant.removed_at.is_(None)))
        if target and target.health<=0:raise FinanceError('Nie można chronić zniszczonej elektrowni.')
    elif kind=='radar':
        from game.radar_models import Radar
        target=session.scalar(select(Radar).where(Radar.id==target_id,Radar.panstwo_id==country_id))
        if target and target.health<=0:raise FinanceError('Nie można dodać obrony do zniszczonego radaru.')
    elif kind=='airport':
        # 20 Nov 2026: port lotniczy (game.airports) — obrona na wszystkich poziomach, także w trakcie budowy
        from game.airport_models import Airport
        target=session.scalar(select(Airport).where(Airport.id==target_id,Airport.panstwo_id.in_(controlled_ids(session,country_id)),Airport.removed_at.is_(None)))
        if target and target.health<=0:raise FinanceError('Nie można dodać obrony do zniszczonego lotniska.')
    else:raise FinanceError('Nieprawidłowy rodzaj chronionego obiektu.')
    if target is not None and getattr(target,'removed_at',None) is not None:target=None
    if target is None:raise FinanceError('Chroniony obiekt nie należy do gracza.')
    return target


def change_defense_system(session,country_id,action,data):
    from game.military_service import natural,military_budget
    if action=='defense_place':
        kind=data.get('target_kind');target_id=natural(data.get('target_id'),'Chroniony obiekt',1)
        target=owned_target(session,country_id,kind,target_id)
        if session.scalar(select(MissileDefense.id).where(MissileDefense.target_kind==kind,MissileDefense.target_id==target_id)):
            raise FinanceError('Ten obiekt posiada już obronę przeciwrakietową.')
        from game.land_war import require_buildable
        require_buildable(session,target.region_id,country_id)
        defense=MissileDefense(panstwo_id=country_id,region_id=target.region_id,target_kind=kind,target_id=target_id,level=1,ammunition=CAPACITIES[0])
        cost=COSTS[1]
    else:
        defense=session.scalar(select(MissileDefense).where(MissileDefense.id==natural(data.get('defense_id'),'Obrona',1),MissileDefense.panstwo_id==country_id).with_for_update())
        if defense is None:raise FinanceError('Obrona nie należy do państwa gracza.')
        target=owned_target(session,country_id,defense.target_kind,defense.target_id)
        if action=='defense_repair':
            count=natural(data.get('count'),'Procent życia do naprawy',1)
            if count>100-defense.health:raise FinanceError('Naprawa przekracza maksymalne życie obrony.')
            cost=count*10000
        elif defense.health<=0:raise FinanceError('Najpierw napraw zniszczoną obronę przeciwrakietową.')
        elif action=='defense_upgrade':
            if defense.level>=7:raise FinanceError('Obrona osiągnęła maksymalny poziom 7.')
            cost=COSTS[defense.level+1]
        else:
            count=natural(data.get('count'),'Liczba pocisków',1)
            if count>CAPACITIES[defense.level-1]-defense.ammunition:raise FinanceError('Przekroczona pojemność wyrzutni.')
            if data.get('source','purchase') not in ('purchase','stock'):raise FinanceError('Wybierz źródło amunicji.')
            if data.get('source')=='stock':
                from game.research_service import settle_production,account_for
                settle_production(session,country_id);stock=account_for(session,country_id)
                if stock.ammunition<count:raise FinanceError('Za mało własnej amunicji przeciwrakietowej.')
                stock.ammunition-=count;cost=0
            else:cost=count*AMMUNITION_PRICE
    budget,total,available=military_budget(session,country_id)
    if cost and (budget is None or available<cost):raise FinanceError('Za mało środków w budżecie sił zbrojnych na bieżący okres budżetowy.')
    if action=='defense_place':session.add(defense)
    elif action=='defense_repair':defense.health+=count
    elif action=='defense_upgrade':
        defense.ammunition+=CAPACITIES[defense.level]-CAPACITIES[defense.level-1];defense.level+=1
    else:defense.ammunition+=count
    session.flush()
    if cost:session.add(MissileDefenseExpense(panstwo_id=country_id,budget_id=budget.id,defense_id=defense.id,amount=Decimal(cost)))
    session.flush()


def intercept(session,flight,region_id,kind,target_id):
    """A hit requires one interceptor; empty launchers cannot intercept."""
    remaining=flight.missiles
    conditions=[(MissileDefense.target_kind=='region')&(MissileDefense.target_id==region_id)]
    if kind in ('base','city','mine','factory','power','radar','airport'):conditions.append((MissileDefense.target_kind==kind)&(MissileDefense.target_id==target_id))
    if kind=='defense':
        conditions.append(MissileDefense.id==target_id)
        target=session.get(MissileDefense,target_id)
        if target and target.target_kind in ('city','base','mine','factory','power','radar','airport'):
            conditions.append((MissileDefense.target_kind==target.target_kind)&(MissileDefense.target_id==target.target_id))
    from sqlalchemy import or_
    defenses=list(session.scalars(select(MissileDefense).where(MissileDefense.panstwo_id==flight.target_country_id,MissileDefense.health>0,or_(*conditions)).order_by(MissileDefense.id).with_for_update()))
    defenses.sort(key=lambda defense:0 if defense.target_kind=='region' else 1)
    for defense in defenses:
        if remaining<=0:break
        neutralized=0
        for _ in range(remaining):
            if neutralized>=defense.ammunition:break
            if randbelow(100)<EFFICIENCIES[defense.level-1]:neutralized+=1
        defense.ammunition-=neutralized;remaining-=neutralized
    return remaining


def defense_data(defense):
    from game.military_geography import city_point,region_point
    from sqlalchemy.orm import object_session
    owner=object_session(defense)
    base=owner.get(MilitaryBase,defense.target_id) if owner is not None and defense.target_kind=='base' else None
    if owner is not None and defense.target_kind=='mine':base=owner.get(Mine,defense.target_id)
    if owner is not None and defense.target_kind=='factory':base=owner.get(AmmunitionFactory,defense.target_id)
    if owner is not None and defense.target_kind=='power':
        from game.industry_models import PowerPlant
        base=owner.get(PowerPlant,defense.target_id)
    if owner is not None and defense.target_kind=='radar':
        from game.radar_models import Radar
        base=owner.get(Radar,defense.target_id)
    if owner is not None and defense.target_kind=='airport':
        from game.airport_models import Airport
        base=owner.get(Airport,defense.target_id)
    position=[base.map_x,base.map_y] if base is not None and base.map_x is not None else None
    return {'id':defense.id,'countryId':defense.panstwo_id,'regionId':str(defense.region_id),
        'targetKind':defense.target_kind,'targetId':defense.target_id,'level':defense.level,
        'health':defense.health,'repairPrice':10000,'ammunition':defense.ammunition,'capacity':CAPACITIES[defense.level-1],
        'efficiency':EFFICIENCIES[defense.level-1],'upgradeCost':COSTS.get(defense.level+1,0),
        'position':city_point(defense.target_id) if defense.target_kind=='city' else region_point(defense.region_id) if defense.target_kind=='region' else position}
