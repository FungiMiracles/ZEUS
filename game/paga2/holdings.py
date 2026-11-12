"""Stan własnego państwa potrzebny do planowania (tylko dane własnego państwa — te same, które gracz widzi na swoich ekranach)."""
from decimal import Decimal
from sqlalchemy import select
from game.industry_catalog import TECHNOLOGIES,FACTORIES,POWER_PLANTS,MINE_RULES


class Holdings:
    def __init__(self,session,country_id,now):
        from game.research_models import ResearchAccount,AmmunitionFactory
        from game.commerce_models import Mine,ResourceStock
        from game.industry_models import PowerPlant
        from game.governance import controlled_ids
        from models import Region,RegionZasob
        from game.land_war_models import Occupation
        self.country_id=country_id;self.now=now
        account=session.get(ResearchAccount,country_id)
        self.points=int(account.points) if account else 0
        self.nodes=dict(account.nodes or {}) if account else {}
        self.factories=[{'id':f.id,'kind':f.kind,'level':f.level,'region':f.region_id,'x':f.map_x,'y':f.map_y,'health':f.health}
                        for f in session.scalars(select(AmmunitionFactory).where(AmmunitionFactory.panstwo_id==country_id,AmmunitionFactory.removed_at.is_(None)))]
        self.mines=[{'id':m.id,'resource':m.resource,'level':m.level,'region':m.region_id,'x':m.map_x,'y':m.map_y,'ready':m.ready_at<=now,'ready_at':m.ready_at}
                    for m in session.scalars(select(Mine).where(Mine.panstwo_id==country_id,Mine.removed_at.is_(None)))]
        self.plants=[{'id':p.id,'kind':p.kind,'level':p.level,'region':p.region_id,'x':p.map_x,'y':p.map_y,'health':p.health,'running':bool(p.running)}
                     for p in session.scalars(select(PowerPlant).where(PowerPlant.panstwo_id==country_id,PowerPlant.removed_at.is_(None)))]
        self.stock={row.resource:int(row.quantity) for row in session.scalars(select(ResourceStock).where(ResourceStock.panstwo_id==country_id))}
        scope=controlled_ids(session,country_id) or [country_id]
        occupied=set(session.scalars(select(Occupation.region_id).where(Occupation.status=='ACTIVE')))
        self.regions=[{'id':id,'coastal':position not in (None,1)} for id,position in session.execute(select(Region.region_id,Region.region_polozenie_id).where(Region.panstwo_id.in_(scope)).order_by(Region.region_id)) if id not in occupied]
        own={r['id'] for r in self.regions}
        self.deposits={}
        try:
            from game.mining_service import resource_ids
            codes={value:key for key,value in resource_ids(session).items()}
            for region,resource,amount in session.execute(select(RegionZasob.region_id,RegionZasob.zasob_id,RegionZasob.zloze_ilosc).where(RegionZasob.region_id.in_(own or [-1]))):
                if amount and resource in codes:self.deposits.setdefault(codes[resource],[]).append(region)
        except Exception:self.deposits={}
        try:
            from game.industry_service import energy_balance
            balance=energy_balance(session,country_id)
            self.energy={'production':float(balance['production']),'demand':float(balance['demand'])}
        except Exception:self.energy={'production':0.0,'demand':0.0}
        self.objects=self._objects(session)

    def _objects(self,session):
        """Punkty wszystkich własnych obiektów na mapie (do unikania kolizji przestrzennych)."""
        from game.military_models import MilitaryBase
        points=[(o['x'],o['y']) for group in (self.factories,self.mines,self.plants) for o in group if o['x'] is not None]
        points+=[(b.map_x,b.map_y) for b in session.scalars(select(MilitaryBase).where(MilitaryBase.panstwo_id==self.country_id)) if b.map_x is not None]
        try:
            from game.radar_models import Radar
            points+=[(r.map_x,r.map_y) for r in session.scalars(select(Radar).where(Radar.panstwo_id==self.country_id))]
        except Exception:pass
        return points

    # ---- pytania planera ----
    def developed(self,node):
        rule=TECHNOLOGIES.get(node)
        return bool(rule) and int(self.nodes.get(node,0))>=rule['cost']

    def missing_points(self,node):
        return max(0,TECHNOLOGIES[node]['cost']-int(self.nodes.get(node,0)))

    def has_factory(self,kind):return any(f['kind']==kind and f['health']>0 for f in self.factories)
    def has_mine(self,resource):return any(m['resource']==resource for m in self.mines)
    def mine_ready(self,resource):return any(m['resource']==resource and m['ready'] for m in self.mines)
    def has_plant(self,kind):return any(p['kind']==kind and p['health']>0 for p in self.plants)
    def energy_surplus(self):return self.energy['production']-self.energy['demand']

    def idle_capacity(self):
        """Moc sprawnych elektrowni, które nie produkują (brak paliwa) — nowe elektrownie tego nie naprawią."""
        return sum(POWER_PLANTS[p['kind']]['production'][p['level']-1] for p in self.plants if p['health']>=3 and not p.get('running',True) and p['kind'] in POWER_PLANTS)
    def coastal_regions(self):return [r['id'] for r in self.regions if r['coastal']]
    def deposit_regions(self,resource):return self.deposits.get(resource,[])
    def objects_in(self,region):
        return sum(1 for group in (self.factories,self.mines,self.plants) for o in group if o['region']==region)
