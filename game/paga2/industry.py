"""PAGA2 — infrastruktura i energetyka poza planami: rozbudowa kopalń i elektrowni, filtry, naprawy,
wznawianie fabryk oraz likwidacja obiektów zniszczonych lub bez złoża (budowę nowych obiektów prowadzi planer).
"""
from sqlalchemy import select
from sqlalchemy.orm import Session
from extensions import db
from game.industry_catalog import MINE_RULES,POWER_PLANTS,FACTORIES,FILTER_COSTS,WASTE_FILTER_COSTS,FILTER_TECHNOLOGY,WASTE_FILTER_TECHNOLOGY
from game.paga2.engine import Adapter,register
from game.paga2.scoring import Option
from game.paga2.finance import request_id,result

PATH='/game/infrastruktura/obiekty/zmien'


def objects(ctx):
    """Własne obiekty przemysłowe (pełne dane potrzebne do decyzji)."""
    from game.research_models import AmmunitionFactory
    from game.commerce_models import Mine
    from game.industry_models import PowerPlant
    from models import RegionZasob
    with Session(db.engine) as session:
        factories=[dict(id=f.id,kind=f.kind,level=f.level,health=f.health,paused=f.paused,filter=f.waste_filter,region=f.region_id)
                   for f in session.scalars(select(AmmunitionFactory).where(AmmunitionFactory.panstwo_id==ctx.country_id,AmmunitionFactory.removed_at.is_(None)))]
        plants=[dict(id=p.id,kind=p.kind,level=p.level,health=p.health,filter=p.air_filter,region=p.region_id,investment=float(p.investment))
                for p in session.scalars(select(PowerPlant).where(PowerPlant.panstwo_id==ctx.country_id,PowerPlant.removed_at.is_(None)))]
        mines=[dict(id=m.id,resource=m.resource,level=m.level,health=m.health,ready=m.ready_at<=ctx.now,region=m.region_id)
               for m in session.scalars(select(Mine).where(Mine.panstwo_id==ctx.country_id,Mine.removed_at.is_(None)))]
        deposits={}
        try:
            from game.mining_service import resource_ids
            ids=resource_ids(session)
            for mine in mines:
                deposits[mine['id']]=session.scalar(select(RegionZasob.zloze_ilosc).where(RegionZasob.region_id==mine['region'],RegionZasob.zasob_id==ids.get(mine['resource']))) or 0
        except Exception:pass
    return factories,plants,mines,deposits


def h_running(h,plant_id):
    """Rozbudowa ma sens tylko dla elektrowni, która produkuje (nie stoi z braku paliwa)."""
    return next((p.get('running',True) for p in h.plants if p.get('id')==plant_id),True)


def developed(ctx,node):
    from game.paga2.planner import _holdings
    return _holdings(ctx).developed(node)


def propose(ctx):
    from game.paga2.planner import _holdings
    from game.paga2.pricing import consumption
    factories,plants,mines,deposits=objects(ctx)
    h=_holdings(ctx);t=ctx.traits;options=[]
    deficit=h.energy_surplus()<0
    needs=consumption(h)
    for p in plants:
        rule=POWER_PLANTS[p['kind']]
        if p['health']<3:
            cost=p['investment']*(3-p['health'])/3
            options.append(Option(key=f'repair:power:{p["id"]}',domain='economy',action='POWER_REPAIR',label=f'Naprawa: {rule["label"]} #{p["id"]}',cost=cost,sector='infrastructure',
                                  effects={'infrastructure':1.0,'production':.5},base=6.0+(6.0 if deficit else 0),payload={'action':'repair','category':'power','object_id':p['id']}))
        elif p['level']<3 and deficit and h_running(h,p['id']):
            options.append(Option(key=f'upgrade:power:{p["id"]}',domain='economy',action='POWER_UPGRADE',label=f'Rozbudowa: {rule["label"]} #{p["id"]} do poziomu {p["level"]+1}',
                                  cost=rule['costs'][p['level']],sector='infrastructure',effects={'infrastructure':.8,'production':.6},traits={'industrialism':.5},
                                  base=3.0,notes=[f'Brak energii: {-h.energy_surplus():.0f} jedn.'],payload={'action':'upgrade','category':'power','object_id':p['id']}))
        if p['kind']=='coal' and not p['filter'] and p['health']>0 and developed(ctx,FILTER_TECHNOLOGY):
            options.append(Option(key=f'filter:power:{p["id"]}',domain='economy',action='AIR_FILTER',label=f'Filtr zanieczyszczeń: elektrownia węglowa #{p["id"]}',
                                  cost=FILTER_COSTS[p['level']-1],sector='environment',effects={'environment':1.0,'welfare':.3},traits={'ecology':1.0,'health':.4,'industrialism':-.2},
                                  payload={'action':'filter','category':'power','object_id':p['id']}))
    for f in factories:
        if f['paused'] and f['health']>0:
            options.append(Option(key=f'resume:factory:{f["id"]}',domain='economy',action='FACTORY_RESUME',label=f'Wznowienie: {FACTORIES[f["kind"]]["label"]} #{f["id"]}',
                                  effects={'production':1.0},base=5.0,payload={'action':'resume','category':'factory','object_id':f['id']}))
        if not f['filter'] and f['health']>0 and developed(ctx,WASTE_FILTER_TECHNOLOGY):
            options.append(Option(key=f'filter:factory:{f["id"]}',domain='economy',action='WASTE_FILTER',label=f'Filtr odpadów: {FACTORIES[f["kind"]]["label"]} #{f["id"]}',
                                  cost=WASTE_FILTER_COSTS[f['level']-1],sector='environment',effects={'environment':1.0},traits={'ecology':1.0,'industrialism':-.2},
                                  payload={'action':'waste_filter','category':'factory','object_id':f['id']}))
        if f['health']<=0:
            options.append(Option(key=f'remove:factory:{f["id"]}',domain='economy',action='FACTORY_REMOVE',label=f'Likwidacja zniszczonej fabryki #{f["id"]} (zwrot 25% wartości)',
                                  effects={'financial_stability':.5},base=4.0,payload={'action':'remove','category':'factory','object_id':f['id']}))
    for m in mines:
        rule=MINE_RULES[m['resource']];deposit=deposits.get(m['id'],1)
        if not deposit:
            options.append(Option(key=f'remove:mine:{m["id"]}',domain='economy',action='MINE_REMOVE',label=f'Likwidacja: {rule[0]} #{m["id"]} — złoże wyczerpane',
                                  effects={'financial_stability':.6},base=8.0,payload={'action':'remove','category':'mine','object_id':m['id']}))
            continue
        if m['ready'] and m['health']>0 and m['level']<3:
            useful=needs.get(m['resource'],0)>h.stock.get(m['resource'],0) or m['resource'] in ('zloto','srebro','kerbit','natsyt','cemium','uran')
            if useful:
                options.append(Option(key=f'upgrade:mine:{m["id"]}',domain='economy',action='MINE_UPGRADE',label=f'Rozbudowa: {rule[0]} #{m["id"]} do poziomu {m["level"]+1}',
                                      cost=rule[2][m['level']]*1e9,sector='infrastructure',effects={'production':.8,'trade':.5},traits={'industrialism':.6,'ecology':-.3},
                                      notes=[f'Wydobycie na poziomie {m["level"]+1}: {rule[3][m["level"]]} jedn. na cykl.'],
                                      payload={'action':'upgrade','category':'mine','object_id':m['id']}))
    return options


def execute(ctx,option):
    status,data=ctx.call(PATH,json={**option.payload,'request_id':request_id(ctx,option)})
    if status<400:ctx._holdings=None
    return result(status,data)


ADAPTER=register(Adapter(name='industry',modes=('CYCLIC',),propose=propose,execute=execute))
