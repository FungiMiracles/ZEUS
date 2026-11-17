"""PAGA2 requests concessions after reconnaissance and builds permitted foreign mines."""
from sqlalchemy import select
from sqlalchemy.orm import Session
from extensions import db
from game.paga2.engine import Adapter,register
from game.paga2.scoring import Option
from game.paga2.finance import request_id,result
from game.industry_catalog import MINE_RULES


def propose(ctx):
    from game.foreign_mining import map_regions
    from game.mining_service import resource_ids
    from game.industry_service import researched
    from game.commerce_models import Mine
    from models import RegionZasob
    options=[]
    with Session(db.engine) as session:
        regions=map_regions(session,ctx.country_id)
        ids=resource_ids(session)
        for rid,row in regions.items():
            if row['canRequest']:
                options.append(Option(key=f'mining:permit:{rid}',domain='diplomacy',action='MINING_PERMIT',label=f'Wniosek o wydobycie: {row["name"]}',target=row['countryId'],stance='friendly',effects={'infrastructure':.6,'production':.8},traits={'industrialism':.8,'agreeableness':.3},base=1,payload={'region_id':int(rid),'target_id':row['countryId']}))
            if not row['permit']:continue
            for code,rule in MINE_RULES.items():
                if not researched(session,ctx.country_id,rule[1]):continue
                if session.scalar(select(Mine.id).where(Mine.region_id==int(rid),Mine.panstwo_id==ctx.country_id,Mine.resource==code,Mine.removed_at.is_(None))):continue
                deposit=session.scalar(select(RegionZasob.zloze_ilosc).where(RegionZasob.region_id==int(rid),RegionZasob.zasob_id==ids[code])) or 0
                if deposit<=0:continue
                options.append(Option(key=f'mining:build:{rid}:{code}',domain='economy',action='FOREIGN_MINE_BUILD',label=f'{rule[0]} za granicą: {row["name"]}',target=row['countryId'],cost=2*rule[2][0]*1e9,sector='infrastructure',effects={'infrastructure':.6,'production':1.0},traits={'industrialism':.8},base=2,payload={'region_id':int(rid),'kind':code}))
    return options


def check(ctx,option):
    if option.action=='MINING_PERMIT':return None
    from game.paga2.location import pick_point
    from game.paga2.planner import _holdings,_km
    point=pick_point(option.payload['region_id'],_holdings(ctx).objects,_km(ctx),seed=f'{ctx.request_key}:{option.key}')
    if not point:return 'Brak wolnej lokalizacji kopalni.'
    option.payload.update(x=point[0],y=point[1])


def execute(ctx,option):
    p=option.payload
    if option.action=='MINING_PERMIT':
        status,data=ctx.call('/game/dyplomacja/akcje',form={'kind':'MINING_PERMIT','target_id':str(p['target_id']),'region_id':str(p['region_id'])})
    else:
        status,data=ctx.call('/game/infrastruktura/obiekty/zmien',json={**p,'category':'mine','action':'build','request_id':request_id(ctx,option)})
        ctx._holdings=None
    return result(status,data)


ADAPTER=register(Adapter(name='mines_abroad',modes=('CYCLIC','IMMEDIATE'),propose=propose,execute=execute,check=check))
