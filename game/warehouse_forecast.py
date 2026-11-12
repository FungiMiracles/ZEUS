"""Warehouse depletion estimates at the current daily rates in Entenda time."""
from collections import defaultdict
from datetime import timedelta
from fractions import Fraction
from math import ceil
from sqlalchemy import select
from models import Region,RegionZasob
from game.commerce_models import Mine
from game.research_models import AmmunitionFactory
from game.industry_models import PowerPlant
from game.industry_catalog import FACTORIES,POWER_PLANTS,MINE_RULES
from game.industry_service import factory_can_work,power_can_work,month_after
from game.mining_service import resource_ids
from game.governance import controlled_ids
from game.finance_service import game_now


def daily_flows(session,country_id,now):
    incoming=defaultdict(Fraction);consumption=defaultdict(Fraction)
    for factory in session.scalars(select(AmmunitionFactory).where(AmmunitionFactory.panstwo_id==country_id,AmmunitionFactory.removed_at.is_(None))):
        if not factory_can_work(session,factory):continue
        rule=FACTORIES[factory.kind]['levels'][factory.level-1]
        days=rule['days']
        if days=='month':
            days=factory.cycle_days if factory.production_progress>0 else (month_after(now)-now).days
        # Daily factories consume the recipe for every produced unit. Longer
        # cycles reserve one recipe at their start, so use its daily average.
        units=Fraction(rule['quantity'],days)
        recipes=units if days==1 else Fraction(1,days)
        for code,amount in rule['inputs'].items():consumption[code]+=amount*recipes
        incoming[rule['product']]+=units
    for plant in session.scalars(select(PowerPlant).where(PowerPlant.panstwo_id==country_id,PowerPlant.removed_at.is_(None))):
        rule=POWER_PLANTS[plant.kind]
        if rule['fuel'] and power_can_work(session,plant):
            consumption[rule['fuel']]+=rule['amounts'][plant.level-1]
    controlled=controlled_ids(session,country_id)
    mining=defaultdict(int)
    for mine in session.scalars(select(Mine).join(Region,Region.region_id==Mine.region_id).where(Mine.panstwo_id==country_id,Mine.removed_at.is_(None),Mine.health>0,Mine.ready_at<=now,Region.panstwo_id.in_(controlled))):
        mining[(mine.region_id,mine.resource)]+=MINE_RULES[mine.resource][3][mine.level-1]
    if mining:
        dictionary=resource_ids(session)
        for (region,code),rate in mining.items():
            deposit=session.scalar(select(RegionZasob.zloze_ilosc).where(RegionZasob.region_id==region,RegionZasob.zasob_id==dictionary[code])) or 0
            incoming[code]+=min(rate,max(0,int(deposit)))
    return incoming,consumption


def depletion_dates(session,country_id,warehouse,now=None):
    now=now or game_now()
    incoming,consumption=daily_flows(session,country_id,now)
    dates={}
    for code,item in warehouse.items():
        deficit=consumption[code]-incoming[code]
        if deficit<=0:continue
        days=ceil(Fraction(max(0,int(item['available'])))/deficit)
        # Stocks can be very large. Dates outside the calendar are not shown.
        if days>(now.max.date()-now.date()).days:continue
        date=now.date()+timedelta(days=days)
        dates[code]=f'{date.day:02d}.{date.month:02d}.{date.year:04d}'
    return dates
