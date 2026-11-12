"""Świadomość mapy świata PAGA2.

Dane jawne, widoczne na mapie każdego gracza: właściciel regionu, sąsiedztwo granic, wybrzeże i okupacje.
a) bezpośredni sąsiedzi państwa, b) sąsiedztwo wszystkich państw, c) regiony sąsiadujące z państwem,
d) sąsiedztwo regionów na świecie, e) odległości między punktami (km), f) położenie nadmorskie i linia brzegowa.
"""
from functools import lru_cache
from math import hypot
from sqlalchemy import select
from models import Region
from game.governance import controllers
from game.military_geography import MAP_PATH,region_adjacency,region_point,coastline_segments,segment_distance,region_contains


@lru_cache(maxsize=4)
def _centers(modified):
    from game.military_geography import map_features
    ids={int(f['properties']['region_id']) for f in map_features(MAP_PATH) if f.get('properties',{}).get('region_id') is not None}
    return {region:region_point(region) for region in ids}


def region_centers():
    return _centers(MAP_PATH.stat().st_mtime_ns)


class World:
    """Migawka geografii politycznej w ramach jednej sesji."""

    def __init__(self,session,*,km_per_unit=None):
        mapping=controllers(session)
        rows=session.execute(select(Region.region_id,Region.panstwo_id,Region.region_nazwa,Region.terytorium_zamorskie)).all()
        self.owner={id:mapping.get(owner) for id,owner,_,_ in rows}
        self.name={id:name for id,_,name,_ in rows}
        self.overseas={id:bool(overseas) for id,_,_,overseas in rows}
        self.graph={region:set(neighbors) for region,neighbors in region_adjacency().items()}
        if km_per_unit is None:
            from game.military_models import MapCalibration
            scale=session.get(MapCalibration,1)
            km_per_unit=scale.km_per_unit if scale is not None and scale.km_per_unit>0 else None
        self.km_per_unit=km_per_unit
        from game.land_war_models import Occupation
        self.occupied={region:occupier for region,occupier in session.execute(select(Occupation.region_id,Occupation.occupier_id).where(Occupation.status=='ACTIVE'))}

    # ---- regiony ----
    def regions_of(self,country):
        return sorted(id for id,owner in self.owner.items() if owner==country)

    def region_neighbors(self,region):
        """d) sąsiedztwo regionów na świecie."""
        return sorted(self.graph.get(region,()))

    def neighbor_regions(self,country):
        """c) obce regiony graniczące z państwem."""
        own=set(self.regions_of(country))
        return sorted({other for region in own for other in self.graph.get(region,()) if other not in own and self.owner.get(other) is not None})

    def border_regions(self,country):
        """Własne regiony graniczące z obcym państwem (front lądowy)."""
        return sorted({region for region in self.regions_of(country) for other in self.graph.get(region,()) if self.owner.get(other) not in (None,country)})

    # ---- państwa ----
    def neighbors(self,country):
        """a) bezpośredni sąsiedzi lądowi państwa."""
        cache=self.__dict__.setdefault('_neighbors',{})
        if country not in cache:cache[country]=sorted({self.owner[other] for other in self.neighbor_regions(country)})
        return cache[country]

    def country_graph(self):
        """b) które państwa ze sobą sąsiadują."""
        graph={}
        for region,others in self.graph.items():
            owner=self.owner.get(region)
            if owner is None:continue
            for other in others:
                neighbor=self.owner.get(other)
                if neighbor is not None and neighbor!=owner:graph.setdefault(owner,set()).add(neighbor);graph.setdefault(neighbor,set()).add(owner)
        return {country:sorted(items) for country,items in graph.items()}

    # ---- odległości ----
    def center(self,region):return region_centers().get(region)

    def distance_km(self,a,b):
        """e) odległość między dwoma punktami mapy w km (None bez kalibracji)."""
        if a is None or b is None or not self.km_per_unit:return None
        return hypot(b[0]-a[0],b[1]-a[1])*self.km_per_unit

    def region_distance_km(self,first,second):
        return self.distance_km(self.center(first),self.center(second))

    def country_distance_km(self,first,second):
        """Najmniejsza odległość między środkami regionów dwóch państw (0 dla sąsiadów lądowych)."""
        if second in self.neighbors(first):return 0.0
        values=[d for a in self.regions_of(first) for b in self.regions_of(second) if (d:=self.region_distance_km(a,b)) is not None]
        return min(values) if values else None

    def nearest_region(self,country,point):
        values=[(d,region) for region in self.regions_of(country) if (d:=self.distance_km(self.center(region),point)) is not None]
        return min(values)[1] if values else None

    # ---- wybrzeże ----
    def coastal(self,region):
        """f) czy region leży nad morzem."""
        return bool(coastline_segments(region))

    def coastline(self,region):
        return coastline_segments(region)

    def coast_distance_km(self,region,point):
        segments=coastline_segments(region)
        if not segments or not self.km_per_unit:return None
        return min(segment_distance(point,a,b) for a,b in segments)*self.km_per_unit

    def contains(self,region,point):return region_contains(region,point[0],point[1])

    # ---- podsumowanie dla decyzji ----
    def summary(self,country):
        own=self.regions_of(country)
        neighbors=self.neighbors(country)
        others=sorted({owner for owner in self.owner.values() if owner not in (None,country)})
        distances={other:(0.0 if other in neighbors else self.country_distance_km(country,other)) for other in others}
        return {
            'regions':[{'id':r,'name':self.name.get(r),'coastal':self.coastal(r),'overseas':self.overseas.get(r,False),
                        'occupied_by':self.occupied.get(r),'neighbors':self.region_neighbors(r)} for r in own],
            'neighbor_countries':neighbors,
            'neighbor_regions':[{'id':r,'owner':self.owner.get(r),'name':self.name.get(r)} for r in self.neighbor_regions(country)],
            'border_regions':self.border_regions(country),
            'coastal_regions':[r for r in own if self.coastal(r)],
            'country_distances_km':{other:(round(d,1) if d is not None else None) for other,d in distances.items()},
            'occupied_by_others':{r:o for r,o in self.occupied.items() if self.owner.get(r)==country},
            'occupied_by_us':{r:self.owner.get(r) for r,o in self.occupied.items() if o==country},
        }
