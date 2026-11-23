"""Wojska lądowe: obrona miast, inwazja (przemarsz i bitwa), okupacja obiektów i regionów, aneksja (UAT, 11 Nov 2026).

Zasady zatwierdzone przez administratora:
* inwazja: wojna z celem + wspólna granica państw; z własnej bazy lądowej; cel: wroga baza lądowa/morska/powietrzna albo miasto;
* koszt (budżet sił zbrojnych): żołnierz 10 000, wóz opancerzony 30 000, czołg 50 000 ROI + PKB per capita × 0,01 za każdą jednostkę;
* prędkość: 50 km/h Entendy, 80 km/h gdy w armii są wozy opancerzone;
* siła = (żołnierze + 3 × wozy + 5 × czołgi) × wyszkolenie wojsk lądowych / 100 × (1 + los 0,0–0,5); remis wygrywa obrońca;
* przegrany traci całą armię; zwycięzca traci część jednostek w proporcji siła przegranego / siła zwycięzcy;
* zwycięski atakujący okupuje obiekt; okupacja regionu po zajęciu wszystkich baz i miast regionu i decyzji okupanta;
  aneksja po 30 dniach Entendy okupacji regionu.
Wszystkie zmiany stanu przechodzą przez zwykłe walidacje gracza (FinanceError) i blokady wierszy państw.
"""
import math,secrets
from datetime import datetime,timedelta
from decimal import Decimal
from uuid import UUID
from sqlalchemy import select,func,or_,and_,update
from sqlalchemy.orm import Session,lazyload
from extensions import db
from game.finance_service import FinanceError,game_now
from game.land_war_models import LandArmy,Occupation
from game.military_models import MilitaryBase
from models import Panstwo,Miasto,Region,Wojsko

UNITS=('soldiers','armored','tanks')
UNIT_LABELS={'soldiers':'żołnierzy','armored':'wozów opancerzonych','tanks':'czołgów'}
UNIT_COST={'soldiers':Decimal(10000),'armored':Decimal(30000),'tanks':Decimal(50000)}
WEIGHTS={'soldiers':1,'armored':3,'tanks':5}
FIELDS={'soldiers':'wojska_ladowe_ilosc','armored':'wozy_opancerzone_ilosc','tanks':'czolgi_ilosc'}
SPEED_FOOT=50
SPEED_ARMORED=80
ANNEX_DAYS=30
GDP_SOURCE='ANEKSJA'
TARGET_BASE_KINDS=('land','naval','air')
LIVE=('MARCHING','DEFENDING','OCCUPYING','RETURNING')   # RETURNING: anulowany przemarsz — powrót do bazy (22 Nov 2026)
_random=secrets.SystemRandom()


# ---------------- helpers ----------------

def natural(value,label,minimum=0):
    if isinstance(value,bool) or not isinstance(value,int) or not minimum<=value<=10**12:raise FinanceError('Nieprawidłowa liczba: '+label)
    return value


def request_key(value):
    try:return str(UUID(str(value)))
    except (TypeError,ValueError):raise FinanceError('Nieprawidłowy identyfikator operacji.') from None


def units_from(data):
    units={unit:natural(data.get(unit,0),UNIT_LABELS[unit]) for unit in UNITS}
    if not any(units.values()):raise FinanceError('Wybierz żołnierzy lub sprzęt.')
    return units


def speed(units):
    return SPEED_ARMORED if units.get('armored') else SPEED_FOOT


def gdp_per_capita(session,country_id):
    gdp,population=session.execute(select(Panstwo.panstwo_PKB,Panstwo.panstwo_populacja).where(Panstwo.PANSTWO_ID==country_id)).one()
    return (Decimal(gdp)/Decimal(population)) if gdp and population else Decimal(0)


def invasion_cost(session,country_id,units):
    extra=gdp_per_capita(session,country_id)*Decimal('0.01')
    return sum(((UNIT_COST[unit]+extra)*units[unit] for unit in UNITS),Decimal(0)).quantize(Decimal('0.01'))


def training(session,country_id):
    value=session.scalar(select(Wojsko.wyszkolenie_ladowe).where(Wojsko.panstwo_id==country_id))
    return 100 if value is None else int(value)


def strength(units,level):
    return sum(units.get(unit,0)*WEIGHTS[unit] for unit in UNITS)*level/100


def deployed_counts(session,country_id):
    """Units outside bases (marching, defending cities, occupying) — still allocated from the country's totals."""
    row=session.execute(select(func.coalesce(func.sum(LandArmy.soldiers),0),func.coalesce(func.sum(LandArmy.armored),0),func.coalesce(func.sum(LandArmy.tanks),0))
                        .where(LandArmy.panstwo_id==country_id,LandArmy.status.in_(LIVE))).one()
    return {FIELDS[unit]:int(value) for unit,value in zip(UNITS,row)}


def spent(session,budget_id):
    return session.scalar(select(func.coalesce(func.sum(LandArmy.cost),0)).where(LandArmy.budget_id==budget_id)) or Decimal(0)


def active_occupation(session,kind,object_id):
    column={'base':Occupation.base_id,'city':Occupation.city_id,'region':Occupation.region_id}[kind]
    return session.scalar(select(Occupation).where(Occupation.kind==kind,column==object_id,Occupation.status=='ACTIVE').order_by(Occupation.id.desc()).limit(1))


def occupied_base_ids(session,owner_id=None):
    query=select(Occupation.base_id).where(Occupation.kind=='base',Occupation.status=='ACTIVE')
    if owner_id is not None:query=query.where(Occupation.owner_id==owner_id)
    return {id for id in session.scalars(query) if id is not None}


def require_usable_base(session,base_id):
    """An occupied base cannot be used by its previous owner (any military action)."""
    if base_id is not None and active_occupation(session,'base',base_id) is not None:
        raise FinanceError('Ta baza jest okupowana przez przeciwnika i nie może być wykorzystywana.')


def require_buildable(session,region_id,country_id):
    """A region occupied by another country is closed to any construction by its owner (11 Nov 2026)."""
    if region_id is None:return
    row=active_occupation(session,'region',int(region_id))
    if row is not None and row.occupier_id!=country_id:
        region=session.scalar(select(Region.region_nazwa).where(Region.region_id==int(region_id)))
        raise FinanceError(f'Region {region} jest okupowany przez {names(session,row.occupier_id).get(row.occupier_id,"przeciwnika")} — nie można w nim nic budować.')


def notify(session,country_id,text):
    from game.paga_ai_actor import country_user_id
    from game.forum_models import GameNotification
    from game.models import utc_now
    owner=country_user_id(session,country_id)
    if owner is not None:session.add(GameNotification(user_id=owner,notification_type='SYSTEM',system_text=text[:1000],created_at=utc_now()))


def names(session,*ids):
    return dict(session.execute(select(Panstwo.PANSTWO_ID,Panstwo.panstwo_nazwa).where(Panstwo.PANSTWO_ID.in_([i for i in ids if i is not None]))).all())


def lock_countries(session,*ids):
    list(session.scalars(select(Panstwo.PANSTWO_ID).where(Panstwo.PANSTWO_ID.in_(sorted({i for i in ids if i is not None}))).order_by(Panstwo.PANSTWO_ID).with_for_update()))


def units_text(units):
    return ', '.join(f"{units.get(unit,0)} {UNIT_LABELS[unit]}" for unit in UNITS)


def change_totals(session,country_id,losses,field_for=None):
    """Fallen soldiers and destroyed equipment leave the country's totals."""
    army=session.scalar(select(Wojsko).where(Wojsko.panstwo_id==country_id).with_for_update())
    if army is None:return
    for unit,count in losses.items():
        if not count:continue
        field=(field_for or {}).get(unit) or FIELDS[unit]
        setattr(army,field,max(0,(getattr(army,field) or 0)-count))


def base_soldier_field(base):
    from game.military_service import BASES
    return BASES[base.kind][2]


# ---------------- geography ----------------

_INDEX={}


def _region_index():
    """Bounding boxes of region polygons, cached per map file version."""
    from game.military_geography import MAP_PATH
    version=MAP_PATH.stat().st_mtime_ns
    if _INDEX.get('version')!=version:_INDEX.update(version=version,index=_build_region_index())
    return _INDEX['index']


def _build_region_index():
    from game.military_geography import map_features,MAP_PATH,polygons
    index=[]
    for feature in map_features(MAP_PATH):
        region_id=(feature.get('properties') or {}).get('region_id');geometry=feature.get('geometry') or {}
        points=[point for rings in polygons(geometry) for point in rings[0]] if polygons(geometry) else []
        if region_id is None or not points:continue
        xs=[p[0] for p in points];ys=[p[1] for p in points]
        index.append((int(region_id),min(xs),min(ys),max(xs),max(ys),geometry))
    return index


def region_at(x,y,index=None):
    from game.military_geography import contains_point
    for region_id,x0,y0,x1,y1,geometry in index or _region_index():
        if x0<=x<=x1 and y0<=y<=y1 and contains_point(geometry,(x,y)):return region_id
    return None


def border_fraction(session,holder_id,source,target,samples=120):
    """Share of the route at which the army first enters the defender's territory (for the border notification)."""
    from game.governance import controller_id
    index=_region_index();owners={}
    for step in range(samples+1):
        f=step/samples;x=source[0]+(target[0]-source[0])*f;y=source[1]+(target[1]-source[1])*f
        region=region_at(x,y,index)
        if region is None:continue
        if region not in owners:owners[region]=controller_id(session,session.scalar(select(Region.panstwo_id).where(Region.region_id==region)))
        occupied=active_occupation(session,'region',region)
        holder=occupied.occupier_id if occupied is not None else owners[region]
        if holder==holder_id:return f
    return 1.0


def overland(session,source,target):
    """22 Nov 2026: armia lądowa porusza się tylko po lądzie — trasa nie może przecinać morza ani oceanu."""
    from game.sea_routes import overland as covered
    from game.military_flights import calibration
    return covered(source,target,endpoint_km=4,km_per_unit=calibration(session).km_per_unit)


def require_overland(session,source,target):
    if not overland(session,source,target):
        raise FinanceError('Armia lądowa nie dotrze do celu: trasa przemarszu przecina morze lub ocean. Wybierz cel osiągalny drogą lądową.')


# ---------------- targets ----------------

def target_state(session,kind,target_id):
    """(object, holder country, original owner, region_id, name, point) of an invasion target."""
    from game.governance import controller_id
    from game.military_geography import city_point
    if kind=='base':
        base=session.get(MilitaryBase,target_id)
        if base is None or base.kind not in TARGET_BASE_KINDS:raise FinanceError('Celem może być baza lądowa, morska albo powietrzna.')
        if base.health<=0:raise FinanceError('Ta baza jest zniszczona.')
        if base.map_x is None or base.map_y is None:raise FinanceError('Baza nie ma lokalizacji na mapie.')
        owner=controller_id(session,base.panstwo_id);occupation=active_occupation(session,'base',base.id)
        from game.military_service import BASES
        return base,(occupation.occupier_id if occupation else owner),owner,base.region_id,base.name or f'{BASES[base.kind][0]} #{base.id}',(base.map_x,base.map_y)
    if kind=='city':
        city=session.scalar(select(Miasto).options(lazyload('*')).where(Miasto.miasto_id==target_id))
        if city is None or city.czy_na_mapie!='TAK':raise FinanceError('Nie znaleziono miasta na mapie.')
        point=city_point(city.miasto_id)
        if not point:raise FinanceError('Miasto nie ma lokalizacji na mapie.')
        owner=controller_id(session,city.panstwo_id);occupation=active_occupation(session,'city',city.miasto_id)
        return city,(occupation.occupier_id if occupation else owner),owner,city.region_id,city.miasto_nazwa,tuple(point[:2])
    raise FinanceError('Wybierz bazę albo miasto przeciwnika.')


def own_land_base(session,country_id,base_id,*,lock=True):
    query=select(MilitaryBase).where(MilitaryBase.id==natural(base_id,'Baza',1),MilitaryBase.panstwo_id==country_id)
    base=session.scalar(query.with_for_update() if lock else query)
    if base is None or base.kind!='land':raise FinanceError('Wybierz własną bazę lądową.')
    require_usable_base(session,base.id)
    if not base.operational or base.health<=0:raise FinanceError('Baza nie jest sprawna.')
    return base


def take_from_garrison(base,units):
    garrison=dict(base.garrison or {})
    for unit,count in units.items():
        if count>(garrison.get(unit) or 0):raise FinanceError(f'W bazie brakuje {UNIT_LABELS[unit]}: dostępne {garrison.get(unit) or 0}.')
    for unit,count in units.items():garrison[unit]=(garrison.get(unit) or 0)-count
    base.garrison=garrison


def return_to_garrison(base,units):
    from game.military_service import CAPACITIES
    capacity=CAPACITIES[base.kind][base.level-1];garrison=dict(base.garrison or {})
    for unit,count in units.items():
        if unit in capacity and (garrison.get(unit) or 0)+count>capacity[unit]:raise FinanceError(f'Baza nie pomieści powracających: {UNIT_LABELS[unit]}.')
        garrison[unit]=(garrison.get(unit) or 0)+count
    base.garrison=garrison


# ---------------- city defence ----------------

def _player_country(session,user_id):
    from game.finance_service import _country_for_user
    return _country_for_user(session,user_id,lock=True)


def add_city_defense(user_id,data):
    from game.governance import controller_id
    key=request_key(data.get('request_id'));units=units_from(data)
    with Session(db.engine) as session,session.begin():
        country=_player_country(session,user_id);own=country.PANSTWO_ID
        existing=session.scalar(select(LandArmy).where(LandArmy.panstwo_id==own,LandArmy.request_id==key))
        if existing is not None:return existing.id
        city=session.scalar(select(Miasto).options(lazyload('*')).where(Miasto.miasto_id==natural(data.get('city_id'),'Miasto',1)))
        if city is None or controller_id(session,city.panstwo_id)!=own:raise FinanceError('Obronę można przydzielić tylko własnemu miastu.')
        if active_occupation(session,'city',city.miasto_id) is not None:raise FinanceError('Miasto jest okupowane — najpierw je odbij.')
        base=own_land_base(session,own,data.get('base_id'))
        if base.region_id!=city.region_id:raise FinanceError('Obronę miasta można wysłać tylko z bazy lądowej w tym samym regionie.')
        take_from_garrison(base,units)
        now=game_now()
        army=LandArmy(panstwo_id=own,user_id=user_id,request_id=key,role='city_defense',status='DEFENDING',source_base_id=base.id,**units,target_kind='city',
                      target_city_id=city.miasto_id,target_country_id=own,target_region_id=city.region_id,target_name=city.miasto_nazwa,starts_at=now,arrives_at=now,resolved_at=now)
        session.add(army);session.flush()
        from game.military_service import reconcile_maintenance
        reconcile_maintenance(session,own)
        return army.id


def withdraw_city_defense(user_id,data):
    """Wycofanie (części) oddziału broniącego miasta — 23 Nov 2026: do wybranej własnej, sprawnej bazy z wolnym miejscem
    (domyślnie baza macierzysta) albo do rezerwy państwa (`to_reserve`, jednostki bez przydziału). Oddziały bez bazy
    macierzystej (np. dawne wojska okupacyjne po aneksji) i takie, których baza jest pełna, można więc zawsze wycofać.
    Bez podanych liczb wycofuje się cały oddział; reszta nadal broni miasta."""
    with Session(db.engine) as session,session.begin():
        country=_player_country(session,user_id);own=country.PANSTWO_ID
        army=session.scalar(select(LandArmy).where(LandArmy.id==natural(data.get('army_id'),'Oddział',1),LandArmy.panstwo_id==own,LandArmy.status=='DEFENDING').with_for_update())
        if army is None:raise FinanceError('Nie znaleziono oddziału broniącego miasta.')
        present=army_units(army)
        if all(data.get(unit) is None for unit in UNITS):units=dict(present)
        else:units={unit:natural(data.get(unit,0) or 0,UNIT_LABELS[unit]) for unit in UNITS}
        if not any(units.values()):raise FinanceError('Wybierz żołnierzy lub sprzęt do wycofania.')
        for unit,count in units.items():
            if count>present[unit]:raise FinanceError(f'Oddział ma tylko {present[unit]}: {UNIT_LABELS[unit]}.')
        if data.get('to_reserve'):
            target='rezerwy państwa'
        else:
            base_id=data.get('base_id') or army.source_base_id
            if base_id is None:raise FinanceError('Oddział nie ma bazy macierzystej — wybierz bazę albo rezerwę państwa.')
            base=session.scalar(select(MilitaryBase).where(MilitaryBase.id==natural(base_id,'Baza',1),MilitaryBase.panstwo_id==own).with_for_update())
            if base is None or base.health<=0 or not base.operational:raise FinanceError('Wybierz własną, sprawną bazę.')
            require_usable_base(session,base.id)
            free=free_capacity(base)
            if any(count>free[unit] for unit,count in units.items()):
                raise FinanceError('Baza nie pomieści wszystkich jednostek. Wolne miejsca: '+', '.join(f'{UNIT_LABELS[u]} {free[u]}' for u in UNITS)+'. Wybierz inną bazę, mniej jednostek albo rezerwę państwa.')
            _into_garrison(session,base,units,own)
            target=f'bazy {base.name or "#"+str(base.id)}'
        for unit,count in units.items():setattr(army,unit,present[unit]-count)
        if not any(getattr(army,unit) for unit in UNITS):army.status='WITHDRAWN';army.resolved_at=game_now()
        session.flush()
        from game.military_service import reconcile_maintenance
        reconcile_maintenance(session,own)
        return {'id':army.id,'message':f'Oddział wrócił do {target}.' if army.status=='WITHDRAWN' else f'Część oddziału wróciła do {target}; reszta nadal broni miasta.'}


def _into_garrison(session,base,units,country_id):
    """Dodaje jednostki do garnizonu bazy; żołnierze lądowi w bazie morskiej/powietrznej przechodzą do tego rodzaju sił."""
    garrison=dict(base.garrison or {})
    for unit,count in units.items():
        if count:garrison[unit]=int(garrison.get(unit) or 0)+count
    base.garrison=garrison
    field=base_soldier_field(base)
    if units.get('soldiers') and field and field!=FIELDS['soldiers']:
        totals=session.scalar(select(Wojsko).where(Wojsko.panstwo_id==country_id).with_for_update())
        if totals is not None:
            moved=min(units['soldiers'],int(totals.wojska_ladowe_ilosc or 0))
            totals.wojska_ladowe_ilosc=int(totals.wojska_ladowe_ilosc or 0)-moved;setattr(totals,field,int(getattr(totals,field) or 0)+moved)


# ---------------- invasion ----------------

def quote(session,country_id,base,units,target_point):
    from game.military_flights import distance_km
    distance=distance_km(session,(base.map_x,base.map_y),target_point);kmh=speed(units)
    return {'cost':invasion_cost(session,country_id,units),'distance_km':distance,'speed_kmh':kmh,'hours':distance/kmh if kmh else 0,
            'gdp_per_capita':gdp_per_capita(session,country_id)}


def launch_invasion(user_id,data):
    from game.military_service import enemies,military_budget,reconcile_maintenance
    from game.road_projects import neighboring_countries
    from game.trade_diplomacy import allied_country_ids
    key=request_key(data.get('request_id'));units=units_from(data)
    kind=data.get('target_kind')
    if kind not in ('base','city'):raise FinanceError('Wybierz bazę albo miasto przeciwnika.')
    with Session(db.engine) as session,session.begin():
        country=_player_country(session,user_id);own=country.PANSTWO_ID
        existing=session.scalar(select(LandArmy).where(LandArmy.panstwo_id==own,LandArmy.request_id==key))
        if existing is not None:return existing.id
        target,holder,owner,region_id,name,point=target_state(session,kind,natural(data.get('target_id'),'Cel',1))
        reinforce=bool(data.get('reinforce'))
        if reinforce:
            # 22 Nov 2026: posiłki do obiektu okupowanego przez nasze wojska — przemarsz po terytorium właściciela obiektu;
            # po dotarciu armia dołącza do wojsk okupacyjnych (gdy obiekt został w międzyczasie odbity — walczy o niego).
            occupation=active_occupation(session,kind,target.id if kind=='base' else target.miasto_id)
            if occupation is None or occupation.occupier_id!=own:raise FinanceError('Posiłki można wysłać tylko do miasta lub bazy okupowanej przez nasze wojska.')
            holder=occupation.owner_id
        else:
            if holder==own:raise FinanceError('Ten obiekt jest już pod kontrolą naszego państwa.')
            recapture=owner==own
            # 23 Nov 2026: wyzwolenie miasta/bazy sojusznika okupowanej przez przeciwnika — wymaga wojny z okupantem; bez wymogu
            # wspólnej granicy (armia może wyruszyć np. z naszej bazy za granicą), byle dotarła do celu drogą lądową
            # (require_overland). Po zwycięstwie obiekt wraca do sojusznika, a armia — do swojej bazy (liberate).
            liberation=not recapture and holder!=owner and owner in set(allied_country_ids(session,own))
            if holder not in enemies(session,own):
                raise FinanceError('Wyzwolenie obiektu sojusznika wymaga trwającej wojny z okupantem.' if liberation else 'Wojska lądowe można wprowadzić tylko do państwa, z którym trwa wojna.')
            if not recapture and not liberation and holder not in neighboring_countries(session,own):raise FinanceError('Atakowane państwo musi graniczyć z naszym państwem.')
            if kind=='base' and not recapture and not liberation:
                from game.intelligence_service import known_ids
                if target.id not in known_ids(session,own,'bases'):raise FinanceError('Lokalizacja tej bazy nie jest znana — najpierw zdobądź ją wywiadem.')
        lock_countries(session,own,holder,owner)
        base=own_land_base(session,own,data.get('source_base_id'))
        if base.map_x is None or base.map_y is None:raise FinanceError('Baza nie ma lokalizacji na mapie.')
        require_overland(session,(base.map_x,base.map_y),point)
        offer=quote(session,own,base,units,point)
        budget,_,available=military_budget(session,own)
        if budget is None:raise FinanceError('Brak zatwierdzonego budżetu na bieżący okres budżetowy.')
        if available<offer['cost']:raise FinanceError('Za mało środków w budżecie sił zbrojnych na koszt inwazji.')
        take_from_garrison(base,units)
        now=game_now();arrives=now+timedelta(hours=offer['hours'])
        fraction=border_fraction(session,holder,(base.map_x,base.map_y),point)
        army=LandArmy(panstwo_id=own,user_id=user_id,request_id=key,role='invasion',status='MARCHING',source_base_id=base.id,**units,target_kind=kind,
                      target_base_id=target.id if kind=='base' else None,target_city_id=target.miasto_id if kind=='city' else None,target_country_id=holder,
                      target_region_id=region_id,target_name=name[:255],source_x=base.map_x,source_y=base.map_y,target_x=point[0],target_y=point[1],
                      distance_km=offer['distance_km'],speed_kmh=offer['speed_kmh'],starts_at=now,border_at=now+(arrives-now)*fraction,arrives_at=arrives,
                      cost=offer['cost'],budget_id=budget.id)
        session.add(army);session.flush()
        reconcile_maintenance(session,own)
        return army.id


# ---------------- ataki na wrogie armie w marszu (22 Nov 2026) ----------------
# Armię przeciwnika maszerującą po naszym terytorium (po przekroczeniu granicy) można:
# (i) bombardować z powietrza, (ii) ostrzelać rakietami z własnego terytorium, (iii) ostrzelać z okrętu —
#     loty game.military_flights z celem 'army'; każde nieprzechwycone trafienie niszczy 1–3% każdego rodzaju jednostek armii;
# (iv) zatrzymać własną armią lądową — oddział 'intercept' wyrusza z bazy lądowej do punktu spotkania; bitwa jak przy
#     inwazji (remis wygrywa obrońca); zwycięski oddział wraca do bazy, a pokonana armia przeciwnika zostaje zniszczona.
STRIKE_LOSS=(1.0,3.0)   # % jednostek każdego rodzaju na jedno trafienie


def army_position(army,moment):
    """Position of a marching army at the given moment (linear march from source to target)."""
    total=(army.arrives_at-army.starts_at).total_seconds()
    f=1.0 if total<=0 else min(1.0,max(0.0,(moment-army.starts_at).total_seconds()/total))
    return (army.source_x+(army.target_x-army.source_x)*f,army.source_y+(army.target_y-army.source_y)*f)


def catch_up(session,source,army,speed_kmh,now):
    """Earliest moment when a unit starting at `source` (speed km/h) reaches the marching army, or None if the army
    arrives at its target first. Returns (moment, point)."""
    from game.military_flights import distance_km
    remaining=(army.arrives_at-now).total_seconds()
    if remaining<=0 or speed_kmh<=0:return None
    reach=lambda seconds:distance_km(session,source,army_position(army,now+timedelta(seconds=seconds)))<=seconds*speed_kmh/3600
    if not reach(remaining):return None
    lo,hi=0.0,remaining
    for _ in range(45):
        middle=(lo+hi)/2
        if reach(middle):hi=middle
        else:lo=middle
    moment=now+timedelta(seconds=max(1.0,hi))
    return moment,army_position(army,moment)


def hostile_army(session,own,army_id,now=None,lock=False):
    """An enemy army marching across our territory (after crossing the border) that we may attack."""
    from game.military_service import enemies
    now=now or game_now()
    query=select(LandArmy).where(LandArmy.id==natural(army_id,'Armia przeciwnika',1))
    army=session.scalar(query.with_for_update() if lock else query)
    if army is None or army.status!='MARCHING' or army.role!='invasion':raise FinanceError('Ta armia nie jest już w marszu.')
    if army.target_country_id!=own or army.panstwo_id==own:raise FinanceError('Można atakować tylko wrogie armie maszerujące po naszym terytorium.')
    if army.border_at is None or army.border_at>now:raise FinanceError('Armia nie przekroczyła jeszcze naszej granicy.')
    if army.arrives_at<=now:raise FinanceError('Armia dotarła już do celu.')
    if army.panstwo_id not in enemies(session,own):raise FinanceError('Atak wymaga trwającej wojny z państwem tej armii.')
    return army


def strike_army(session,army,hits,moment):
    """Hits of bombs/missiles on a marching army: every hit destroys 1–3% of each unit type (rounded)."""
    if army is None or army.status!='MARCHING':return {'targetUnavailable':True}
    keep=1.0
    for _ in range(hits):keep*=1-_random.uniform(*STRIKE_LOSS)/100
    units=army_units(army)
    lost={unit:min(count,round(count*(1-keep))) for unit,count in units.items()}
    for unit in UNITS:setattr(army,unit,units[unit]-lost[unit])
    change_totals(session,army.panstwo_id,lost)
    destroyed=not any(getattr(army,unit) for unit in UNITS)
    if destroyed:
        army.status='DESTROYED';army.resolved_at=moment;army.battle={'result':'DESTROYED_IN_MARCH','at':moment.isoformat()}
        from game.military_service import reconcile_maintenance
        reconcile_maintenance(session,army.panstwo_id)
    return {'armyLosses':lost,'armyDestroyed':destroyed,'remaining':army_units(army)}


def launch_interception(user_id,data):
    """(iv) Own land army marches from a land base to meet the enemy army on our territory."""
    from game.military_service import reconcile_maintenance
    key=request_key(data.get('request_id'));units=units_from(data)
    with Session(db.engine) as session,session.begin():
        country=_player_country(session,user_id);own=country.PANSTWO_ID
        existing=session.scalar(select(LandArmy).where(LandArmy.panstwo_id==own,LandArmy.request_id==key))
        if existing is not None:return existing.id
        now=game_now()
        enemy=hostile_army(session,own,data.get('army_id'),now)
        lock_countries(session,own,enemy.panstwo_id)
        enemy=hostile_army(session,own,enemy.id,now,lock=True)
        base=own_land_base(session,own,data.get('source_base_id'))
        if base.map_x is None or base.map_y is None:raise FinanceError('Baza nie ma lokalizacji na mapie.')
        kmh=speed(units);meeting=catch_up(session,(base.map_x,base.map_y),enemy,kmh,now)
        if meeting is None:raise FinanceError(f'Oddział z tej bazy ({kmh} km/h) nie zdąży dogonić armii przed jej dotarciem do celu ({enemy.target_name}).')
        moment,point=meeting
        require_overland(session,(base.map_x,base.map_y),point)
        take_from_garrison(base,units)
        from game.military_flights import distance_km
        who=names(session,enemy.panstwo_id).get(enemy.panstwo_id,'przeciwnika')
        army=LandArmy(panstwo_id=own,user_id=user_id,request_id=key,role='intercept',status='MARCHING',source_base_id=base.id,**units,target_kind='army',
                      target_army_id=enemy.id,target_country_id=enemy.panstwo_id,target_region_id=enemy.target_region_id,
                      target_name=f'Armia państwa {who} (cel: {enemy.target_name})'[:255],source_x=base.map_x,source_y=base.map_y,target_x=point[0],target_y=point[1],
                      distance_km=distance_km(session,(base.map_x,base.map_y),point),speed_kmh=kmh,starts_at=now,arrives_at=moment,cost=0)
        session.add(army);session.flush()
        reconcile_maintenance(session,own)
        return army.id


def intercept_battle(session,army,moment,rolls=None):
    """Interceptor meets the enemy army. The interceptor defends its own territory (a draw goes to the interceptor)."""
    enemy=session.scalar(select(LandArmy).where(LandArmy.id==army.target_army_id).with_for_update()) if army.target_army_id else None
    if enemy is None or enemy.status!='MARCHING':
        army.battle={'result':'TARGET_GONE','reason':'Armia przeciwnika nie jest już w marszu.'};_return_home(session,army);return
    ours,theirs=army_units(army),army_units(enemy)
    own_level,enemy_level=training(session,army.panstwo_id),training(session,enemy.panstwo_id)
    r_own,r_enemy=rolls if rolls is not None else (_random.uniform(0,0.5),_random.uniform(0,0.5))
    base_own,base_enemy=strength(ours,own_level),strength(theirs,enemy_level)
    final_own=base_own*(1+r_own);final_enemy=base_enemy*(1+r_enemy)
    won=final_own>=final_enemy
    record={'attacker':{'country':enemy.panstwo_id,'units':theirs,'training':enemy_level,'strength':round(base_enemy,2),'chance':round(r_enemy,3),'final':round(final_enemy,2)},
            'defender':{'country':army.panstwo_id,'units':ours,'training':own_level,'strength':round(base_own,2),'chance':round(r_own,3),'final':round(final_own,2)},
            'result':'INTERCEPT_WON' if won else 'INTERCEPT_LOST','at':moment.isoformat()}
    if won:
        fraction=(final_enemy/final_own) if final_own else 0
        lost={unit:min(count,round(count*fraction)) for unit,count in ours.items()}
        for unit in UNITS:setattr(army,unit,ours[unit]-lost[unit])
        change_totals(session,army.panstwo_id,lost);change_totals(session,enemy.panstwo_id,theirs)
        for unit in UNITS:setattr(enemy,unit,0)
        enemy.status='DESTROYED';enemy.resolved_at=moment;enemy.battle={**record,'result':'INTERCEPTED'}
        record['defender']['lost']=lost;record['attacker']['lost']=theirs
        army.battle=record
        _return_home(session,army)
        army.resolved_at=moment
    else:
        fraction=(final_own/final_enemy) if final_enemy else 0
        lost={unit:min(count,round(count*fraction)) for unit,count in theirs.items()}
        for unit in UNITS:setattr(enemy,unit,theirs[unit]-lost[unit])
        change_totals(session,enemy.panstwo_id,lost);change_totals(session,army.panstwo_id,ours)
        for unit in UNITS:setattr(army,unit,0)
        army.status='DESTROYED';army.resolved_at=moment
        record['defender']['lost']=ours;record['attacker']['lost']=lost
        army.battle=record
        if not any(getattr(enemy,unit) for unit in UNITS):enemy.status='DESTROYED';enemy.resolved_at=moment;enemy.battle={**record,'result':'INTERCEPTED'}
    n=names(session,army.panstwo_id,enemy.panstwo_id)
    summary=(f"Bitwa w marszu ({enemy.target_name}): przechwycenie przez {n.get(army.panstwo_id,'?')} (siła {record['defender']['final']}) vs armia {n.get(enemy.panstwo_id,'?')} (siła {record['attacker']['final']}). "
             f"{'Armia przeciwnika została rozbita' if won else 'Oddział przechwytujący został rozbity, armia przeciwnika maszeruje dalej'}. "
             f"Straty przechwytujących: {units_text(record['defender']['lost'])}; armii w marszu: {units_text(record['attacker']['lost'])}.")
    notify(session,army.panstwo_id,summary);notify(session,enemy.panstwo_id,summary)
    from game.military_service import reconcile_maintenance
    for country in sorted({army.panstwo_id,enemy.panstwo_id}):
        try:
            with session.begin_nested():reconcile_maintenance(session,country)
        except FinanceError:pass


# ---------------- anulowanie przemarszu (22 Nov 2026) ----------------

def cancel_march(user_id,data):
    """Own marching army turns back from its current position to its home base; the return takes as long as the march so far.
    The invasion cost is not refunded."""
    with Session(db.engine) as session,session.begin():
        country=_player_country(session,user_id);own=country.PANSTWO_ID
        army=session.scalar(select(LandArmy).where(LandArmy.id==natural(data.get('army_id'),'Armia',1),LandArmy.panstwo_id==own).with_for_update())
        if army is None or army.status!='MARCHING':raise FinanceError('Ta armia nie jest w marszu.')
        now=game_now()
        if army.arrives_at<=now:raise FinanceError('Armia dotarła już do celu.')
        position=army_position(army,now)
        base=session.get(MilitaryBase,army.source_base_id) if army.source_base_id else None
        home=(base.map_x,base.map_y) if base is not None and base.map_x is not None else (army.source_x,army.source_y)
        elapsed=max(timedelta(seconds=1),now-army.starts_at)
        army.status='RETURNING';army.source_x,army.source_y=position;army.target_x,army.target_y=home
        army.starts_at=now;army.arrives_at=now+elapsed;army.border_at=None
        from game.military_flights import distance_km
        army.distance_km=distance_km(session,position,home)
        session.flush()
        return army.id


def complete_returns(session,now):
    for army in session.scalars(select(LandArmy).where(LandArmy.status=='RETURNING',LandArmy.arrives_at<=now).with_for_update()):
        _return_home(session,army);army.resolved_at=army.arrives_at
        notify(session,army.panstwo_id,f'Armia zawrócona z przemarszu ({army.target_name}) wróciła do bazy.')
    session.flush()


# ---------------- resolution ----------------

def complete_marches(session,now=None):
    """Border notifications and battles of every army that is due (called on page loads and by the scheduler)."""
    now=now or game_now()
    # 22 Nov 2026: najpierw trafienia lotów wymierzonych w armie w marszu — straty liczą się przed bitwą u celu.
    from game.military_flights import complete_flights
    complete_flights(session,now,army_strikes=True)
    due=list(session.execute(select(LandArmy.id,LandArmy.panstwo_id,LandArmy.target_country_id).where(LandArmy.status=='MARCHING',
         or_(LandArmy.arrives_at<=now,and_(LandArmy.border_notified.is_(False),LandArmy.border_at<=now)))))
    complete_returns(session,now)
    if not due:return
    lock_countries(session,*{row.panstwo_id for row in due},*{row.target_country_id for row in due})
    for army in session.scalars(select(LandArmy).where(LandArmy.id.in_([row.id for row in due])).order_by(LandArmy.arrives_at,LandArmy.id).with_for_update().execution_options(populate_existing=True)):
        if army.status!='MARCHING':continue
        if not army.border_notified and army.border_at is not None and army.border_at<=now:
            army.border_notified=True
            who=names(session,army.panstwo_id).get(army.panstwo_id,'Obce państwo')
            notify(session,army.target_country_id,f'Wtargnięcie: armia państwa {who} wkroczyła na nasze terytorium ({units_text(army_units(army))}). Cel: {army.target_name}.')
        if army.arrives_at<=now:
            if army.role=='intercept':intercept_battle(session,army,army.arrives_at)
            else:battle(session,army,army.arrives_at)
    session.flush()


def army_units(army):
    return {unit:int(getattr(army,unit) or 0) for unit in UNITS}


def defenders(session,army):
    """(defending country, units, training, apply_losses(fraction or None=all)) for the army's target as it is now."""
    if army.target_kind=='base':
        base=session.scalar(select(MilitaryBase).where(MilitaryBase.id==army.target_base_id).with_for_update())
        if base is None or base.health<=0:return None
        occupation=active_occupation(session,'base',base.id)
        if occupation is not None:return _army_defenders(session,occupation.occupier_id,_occupiers(session,'base',base.id))
        owner=base.panstwo_id;units={unit:int((base.garrison or {}).get(unit) or 0) for unit in UNITS}
        field_for={'soldiers':base_soldier_field(base)}
        def apply(fraction):
            lost={unit:(count if fraction is None else min(count,round(count*fraction))) for unit,count in units.items()}
            garrison=dict(base.garrison or {})
            for unit,count in lost.items():garrison[unit]=max(0,(garrison.get(unit) or 0)-count)
            base.garrison=garrison;change_totals(session,owner,lost,field_for);return lost
        return owner,units,training(session,owner),apply
    city=session.get(Miasto,army.target_city_id)
    if city is None:return None
    occupation=active_occupation(session,'city',city.miasto_id)
    if occupation is not None:return _army_defenders(session,occupation.occupier_id,_occupiers(session,'city',city.miasto_id))
    from game.governance import controller_id
    owner=controller_id(session,city.panstwo_id)
    rows=list(session.scalars(select(LandArmy).where(LandArmy.target_city_id==city.miasto_id,LandArmy.status=='DEFENDING',LandArmy.panstwo_id==owner).with_for_update()))
    return _army_defenders(session,owner,rows)


def _occupiers(session,kind,object_id):
    column=LandArmy.target_base_id if kind=='base' else LandArmy.target_city_id
    return list(session.scalars(select(LandArmy).where(LandArmy.target_kind==kind,column==object_id,LandArmy.status=='OCCUPYING').with_for_update()))


def _army_defenders(session,country_id,rows):
    units={unit:sum(int(getattr(row,unit) or 0) for row in rows) for unit in UNITS}
    def apply(fraction):
        lost={unit:0 for unit in UNITS}
        for row in rows:
            for unit in UNITS:
                count=int(getattr(row,unit) or 0);loss=count if fraction is None else min(count,round(count*fraction))
                setattr(row,unit,count-loss);lost[unit]+=loss
            if fraction is None or not any(getattr(row,unit) for unit in UNITS):row.status='DESTROYED';row.resolved_at=game_now()
        change_totals(session,country_id,lost);return lost
    return country_id,units,training(session,country_id),apply


def battle(session,army,moment,rolls=None):
    """Battle at the target. rolls=(attacker, defender) only for tests."""
    attacking=army_units(army);attacker=army.panstwo_id
    found=defenders(session,army)
    if found is None:
        army.battle={'result':'TARGET_GONE'};_return_home(session,army);return
    defender,defending,defender_level,apply=found
    from game.trade_diplomacy import allied_country_ids
    if defender!=attacker and defender in set(allied_country_ids(session,attacker)):
        # 23 Nov 2026: cel wyzwolenia przeszedł w międzyczasie pod kontrolę sojusznika — bez bitwy, armia wraca do bazy.
        army.battle={'result':'TARGET_GONE','reason':'Obiekt jest już pod kontrolą sojusznika.'};_return_home(session,army);return
    if defender==attacker:
        object_id=army.target_base_id if army.target_kind=='base' else army.target_city_id
        occupation=active_occupation(session,army.target_kind,object_id)
        if occupation is not None and occupation.occupier_id==attacker:
            # 22 Nov 2026: posiłki (lub kolejna fala) docierają do obiektu okupowanego przez nasze wojska — dołączają do okupacji.
            army.status='OCCUPYING';army.resolved_at=moment;army.battle={'result':'REINFORCED','at':moment.isoformat()}
            notify(session,attacker,f'Posiłki dotarły do: {army.target_name} ({units_text(attacking)}) i dołączyły do wojsk okupacyjnych.')
            return
        # Cel przeszedł pod naszą kontrolę przed przybyciem armii (np. odbiła go wcześniejsza fala): bez bitwy z własnymi wojskami.
        army.battle={'result':'TARGET_GONE','reason':'Cel jest już pod kontrolą naszego państwa.'};_return_home(session,army);return
    attacker_level=training(session,attacker)
    r_att,r_def=rolls if rolls is not None else (_random.uniform(0,0.5),_random.uniform(0,0.5))
    base_att=strength(attacking,attacker_level);base_def=strength(defending,defender_level)
    final_att=base_att*(1+r_att);final_def=base_def*(1+r_def)
    won=final_att>final_def
    record={'attacker':{'country':attacker,'units':attacking,'training':attacker_level,'strength':round(base_att,2),'chance':round(r_att,3),'final':round(final_att,2)},
            'defender':{'country':defender,'units':defending,'training':defender_level,'strength':round(base_def,2),'chance':round(r_def,3),'final':round(final_def,2)},
            'result':'ATTACKER_WON' if won else 'DEFENDER_WON','at':moment.isoformat()}
    if won:
        fraction=(final_def/final_att) if final_att else 0
        lost={unit:min(count,round(count*fraction)) for unit,count in attacking.items()}
        for unit in UNITS:setattr(army,unit,attacking[unit]-lost[unit])
        change_totals(session,attacker,lost)
        record['attacker']['lost']=lost;record['defender']['lost']=apply(None)
        _conquer(session,army,defender,moment)
    else:
        fraction=(final_att/final_def) if final_def else 0
        record['attacker']['lost']=attacking;record['defender']['lost']=apply(fraction)
        change_totals(session,attacker,attacking)
        for unit in UNITS:setattr(army,unit,0)
        army.status='DESTROYED'
    army.resolved_at=moment;army.battle=record
    n=names(session,attacker,defender)
    summary=(f"Bitwa o {army.target_name}: atak {n.get(attacker,'?')} (siła {record['attacker']['final']}) vs obrona {n.get(defender,'?')} (siła {record['defender']['final']}). "
             f"{'Zwycięstwo atakujących' if won else 'Zwycięstwo obrońców'}. Straty atakujących: {units_text(record['attacker']['lost'])}; obrońców: {units_text(record['defender']['lost'])}.")
    notify(session,attacker,summary);notify(session,defender,summary)


def _return_home(session,army):
    """Target vanished before arrival: the army returns to its base if possible, otherwise it disbands into the totals."""
    base=session.scalar(select(MilitaryBase).where(MilitaryBase.id==army.source_base_id,MilitaryBase.panstwo_id==army.panstwo_id).with_for_update()) if army.source_base_id else None
    try:
        if base is None or active_occupation(session,'base',base.id) is not None:raise FinanceError('brak bazy')
        return_to_garrison(base,army_units(army))
    except FinanceError:pass
    army.status='WITHDRAWN';army.resolved_at=game_now()
    for unit in UNITS:setattr(army,unit,0)


def _conquer(session,army,defender,moment):
    kind=army.target_kind;object_id=army.target_base_id if kind=='base' else army.target_city_id
    occupation=active_occupation(session,kind,object_id)
    if occupation is not None and occupation.owner_id!=army.panstwo_id:
        from game.trade_diplomacy import allied_country_ids
        if occupation.owner_id in set(allied_country_ids(session,army.panstwo_id)):
            _liberate(session,army,occupation,moment);return
    if occupation is not None and occupation.owner_id==army.panstwo_id:
        # Recaptured by the original owner: the occupation ends and the object is usable again at once;
        # the army enters the base garrison (what does not fit returns to the national pool) or defends the city.
        occupation.status='ENDED';occupation.ended_at=moment
        if kind=='base':merge_into_base(session,session.get(MilitaryBase,object_id),[army],army.panstwo_id)
        else:army.status='DEFENDING';army.role='city_defense';army.target_country_id=army.panstwo_id
        session.flush()
        _release_region(session,army.target_region_id,occupation.occupier_id,moment,recaptured=army.target_name)
        return
    previous=None
    if occupation is not None:occupation.status='ENDED';occupation.ended_at=moment;previous=occupation.occupier_id
    if kind=='base':
        from game.governance import controller_id
        owner=controller_id(session,session.get(MilitaryBase,object_id).panstwo_id)
    else:
        from game.governance import controller_id
        owner=controller_id(session,session.get(Miasto,object_id).panstwo_id)
    session.add(Occupation(kind=kind,base_id=object_id if kind=='base' else None,city_id=object_id if kind=='city' else None,region_id=army.target_region_id,
                           owner_id=owner,occupier_id=army.panstwo_id,status='ACTIVE',started_at=moment))
    army.status='OCCUPYING';session.flush()
    if previous is not None and previous!=army.panstwo_id:_release_region(session,army.target_region_id,previous,moment)
    _check_region(session,army.target_region_id,army.panstwo_id,owner,moment)


def _liberate(session,army,occupation,moment):
    """23 Nov 2026: zwycięska armia wyzwoliła miasto/bazę sojusznika — okupacja się kończy, obiekt wraca do sojusznika,
    a armia wraca do swojej bazy (nadmiar, który się nie zmieści, trafia do ogólnej puli wojsk). Gdy okupant nie trzyma
    już żadnego obiektu w regionie, kończy się także okupacja regionu."""
    occupation.status='ENDED';occupation.ended_at=moment
    session.flush()
    _return_home(session,army)
    ally,occupier=occupation.owner_id,occupation.occupier_id
    _release_region(session,army.target_region_id,occupier,moment)
    n=names(session,army.panstwo_id,ally,occupier)
    region=session.scalar(select(Region.region_nazwa).where(Region.region_id==army.target_region_id))
    notify(session,ally,f'Wojska sojusznika {n.get(army.panstwo_id,"?")} wyzwoliły {army.target_name} (region {region}) spod okupacji państwa {n.get(occupier,"?")}. Obiekt wrócił pod nasze panowanie.')
    notify(session,army.panstwo_id,f'Wyzwoliliśmy {army.target_name} — obiekt wrócił do sojusznika {n.get(ally,"?")}. Armia wraca do bazy.')


def region_objects(session,region_id,owner_id):
    bases=list(session.scalars(select(MilitaryBase.id).where(MilitaryBase.region_id==region_id,MilitaryBase.panstwo_id==owner_id,MilitaryBase.kind.in_(TARGET_BASE_KINDS),MilitaryBase.health>0)))
    cities=list(session.scalars(select(Miasto.miasto_id).where(Miasto.region_id==region_id,Miasto.czy_na_mapie=='TAK')))
    return bases,cities


def held_all(session,region_id,occupier,owner):
    """The occupier holds every base and city of the owner's region."""
    bases,cities=region_objects(session,region_id,owner)
    held=lambda kind,ids:all((o:=active_occupation(session,kind,i)) is not None and o.occupier_id==occupier for i in ids)
    return bool(bases or cities) and held('base',bases) and held('city',cities)


def held_any(session,region_id,occupier):
    return session.scalar(select(Occupation.id).where(Occupation.kind.in_(['base','city']),Occupation.region_id==region_id,
                          Occupation.occupier_id==occupier,Occupation.status=='ACTIVE').limit(1)) is not None


def _check_region(session,region_id,occupier,owner,moment):
    """All bases and cities of the region held by the same occupier: ask the occupier whether to occupy the region."""
    if session.scalar(select(Occupation.id).where(Occupation.kind=='region',Occupation.region_id==region_id,Occupation.status.in_(['PENDING','ACTIVE']))) is not None:return
    if not held_all(session,region_id,occupier,owner):return
    session.add(Occupation(kind='region',region_id=region_id,owner_id=owner,occupier_id=occupier,status='PENDING',started_at=moment))
    region=session.scalar(select(Region.region_nazwa).where(Region.region_id==region_id))
    notify(session,occupier,f'Nasze wojska zajęły wszystkie bazy i miasta regionu {region}. Zdecyduj w panelu wojennym, czy prowadzić okupację regionu.')


def _release_region(session,region_id,occupier,moment,recaptured=None):
    """The occupier lost an object in the region. A pending/declined decision lapses at once (it needs every object);
    an ACTIVE region occupation ends only when the occupier holds no base or city of the region any more (11 Nov 2026)."""
    region=session.scalar(select(Region.region_nazwa).where(Region.region_id==region_id))
    holds=held_any(session,region_id,occupier)
    for row in session.scalars(select(Occupation).where(Occupation.kind=='region',Occupation.region_id==region_id,Occupation.occupier_id==occupier,
                                                      Occupation.status.in_(['PENDING','DECLINED','ACTIVE'])).with_for_update()):
        if row.status=='ACTIVE' and holds:
            if recaptured:notify(session,row.owner_id,f'Odbiliśmy {recaptured}. Region {region} pozostaje okupowany, dopóki nie odbijemy wszystkich baz i miast regionu.')
            continue
        was_active=row.status=='ACTIVE';row.status='ENDED';row.ended_at=moment
        if was_active:
            notify(session,row.occupier_id,f'Okupacja regionu {region} zakończona: przeciwnik odzyskał wszystkie bazy i miasta regionu.')
            notify(session,row.owner_id,f'Odzyskaliśmy wszystkie bazy i miasta regionu {region} — region nie jest już okupowany.')


def free_capacity(base):
    """Wolne miejsca w bazie dla żołnierzy, wozów i czołgów (sprzęt pomieści tylko baza lądowa)."""
    from game.military_service import CAPACITIES
    capacity=CAPACITIES[base.kind][base.level-1];garrison=base.garrison or {}
    return {unit:max(0,int(capacity.get(unit,0))-int(garrison.get(unit) or 0)) if unit in capacity else 0 for unit in UNITS}


def withdraw_occupation(user_id,data):
    """Okupant wycofuje (część) wojsk okupacyjnych z miasta lub bazy do własnej bazy — tylko tyle, ile baza pomieści.
    Wycofanie wszystkich jednostek kończy okupację obiektu (wraca do właściciela); gdy okupant nie trzyma już żadnego
    obiektu regionu, kończy się także okupacja regionu."""
    units={unit:natural(data.get(unit,0),UNIT_LABELS[unit]) for unit in UNITS}
    if not any(units.values()):raise FinanceError('Wybierz żołnierzy lub sprzęt do wycofania.')
    with Session(db.engine) as session,session.begin():
        country=_player_country(session,user_id);own=country.PANSTWO_ID
        occupation=session.scalar(select(Occupation).where(Occupation.id==natural(data.get('occupation_id'),'Okupacja',1),Occupation.kind.in_(['base','city']),
                                  Occupation.occupier_id==own,Occupation.status=='ACTIVE').with_for_update())
        if occupation is None:raise FinanceError('Nasze wojska nie okupują tego miasta ani bazy.')
        object_id=occupation.base_id if occupation.kind=='base' else occupation.city_id
        armies=[army for army in _occupiers(session,occupation.kind,object_id) if army.panstwo_id==own]
        present={unit:sum(int(getattr(army,unit) or 0) for army in armies) for unit in UNITS}
        for unit,count in units.items():
            if count>present[unit]:raise FinanceError(f'W okupowanym obiekcie jest tylko {present[unit]}: {UNIT_LABELS[unit]}.')
        base=session.scalar(select(MilitaryBase).where(MilitaryBase.id==natural(data.get('base_id'),'Baza',1),MilitaryBase.panstwo_id==own).with_for_update())
        if base is None or base.health<=0 or not base.operational:raise FinanceError('Wybierz własną, sprawną bazę.')
        require_usable_base(session,base.id)
        free=free_capacity(base)
        over={unit:count-free[unit] for unit,count in units.items() if count>free[unit]}
        if over:raise FinanceError('Baza nie pomieści wszystkich jednostek. Wolne miejsca: '+', '.join(f'{UNIT_LABELS[u]} {free[u]}' for u in UNITS)+'.')
        # Zabieramy jednostki z armii okupacyjnych (największe najpierw); puste armie kończą okupację.
        for unit,count in units.items():
            for army in sorted(armies,key=lambda a:-int(getattr(a,unit) or 0)):
                take=min(count,int(getattr(army,unit) or 0));setattr(army,unit,int(getattr(army,unit) or 0)-take);count-=take
                if not count:break
        moment=game_now()
        for army in armies:
            if not any(getattr(army,unit) for unit in UNITS):army.status='WITHDRAWN';army.resolved_at=moment
        _into_garrison(session,base,units,own)
        ended=all(army.status=='WITHDRAWN' for army in armies)
        name=next((army.target_name for army in armies),'obiekt')
        if ended:
            occupation.status='ENDED';occupation.ended_at=moment;session.flush()
            notify(session,occupation.owner_id,f'Okupant wycofał wszystkie wojska z: {name}. Obiekt wrócił pod naszą kontrolę.')
            _release_region(session,occupation.region_id,own,moment)
        session.flush()
        from game.military_service import reconcile_maintenance
        reconcile_maintenance(session,own)
        return {'id':occupation.id,'ended':ended,'message':f'Wycofano wojska do bazy {base.name or "#"+str(base.id)}.'+(' Okupacja obiektu zakończona.' if ended else '')}


def merge_into_base(session,base,armies,country_id):
    """Armies enter the base garrison up to its capacity (only a land base holds vehicles and tanks); the rest returns to the
    country's free pool. Land soldiers garrisoning a naval/air base are moved to that service's totals."""
    from game.military_service import CAPACITIES
    capacity=CAPACITIES[base.kind][base.level-1];garrison=dict(base.garrison or {});moved=0
    for army in armies:
        for unit in UNITS:
            count=int(getattr(army,unit) or 0)
            if unit in capacity:
                fit=max(0,min(count,capacity[unit]-int(garrison.get(unit) or 0)));garrison[unit]=int(garrison.get(unit) or 0)+fit
                if unit=='soldiers':moved+=fit
            setattr(army,unit,0)
        army.status='MERGED';army.resolved_at=army.resolved_at or game_now()
    base.garrison=garrison
    field=base_soldier_field(base)
    if moved and field and field!=FIELDS['soldiers']:
        totals=session.scalar(select(Wojsko).where(Wojsko.panstwo_id==country_id).with_for_update())
        if totals is not None:
            moved=min(moved,int(totals.wojska_ladowe_ilosc or 0))
            totals.wojska_ladowe_ilosc=int(totals.wojska_ladowe_ilosc or 0)-moved;setattr(totals,field,int(getattr(totals,field) or 0)+moved)


def decide_region(user_id,data):
    """Occupier's answer: occupy the region (yes) or keep the troops without occupation (no)."""
    with Session(db.engine) as session,session.begin():
        country=_player_country(session,user_id)
        row=session.scalar(select(Occupation).where(Occupation.id==natural(data.get('occupation_id'),'Okupacja',1),Occupation.kind=='region',
                           Occupation.occupier_id==country.PANSTWO_ID,Occupation.status.in_(['PENDING','DECLINED'])).with_for_update())
        if row is None:raise FinanceError('Brak decyzji o okupacji tego regionu.')
        if data.get('occupy') is True:
            if not held_all(session,row.region_id,row.occupier_id,row.owner_id):raise FinanceError('Nasze wojska nie kontrolują już wszystkich baz i miast tego regionu.')
            row.status='ACTIVE';row.started_at=game_now()
            from game.foreign_mining import seize
            seize(session,row.region_id,row.occupier_id,row.started_at)
            region=session.scalar(select(Region.region_nazwa).where(Region.region_id==row.region_id))
            who=names(session,country.PANSTWO_ID).get(country.PANSTWO_ID)
            notify(session,row.owner_id,f'Region {region} jest okupowany przez {who}. Bez odbicia w ciągu {ANNEX_DAYS} dni Entendy okupant może go anektować.')
        elif data.get('occupy') is False:row.status='DECLINED'
        else:raise FinanceError('Wybierz: tak albo nie.')
        return row.id


def annex_region(user_id,data):
    """After 30 Entenda days of region occupation the occupier may annex it (the region changes państwo_id), provided it still
    holds every base and city of the region. Annexing the region with the owner's capital ends the owner's sovereignty."""
    from game.military_service import reconcile_maintenance
    with Session(db.engine) as session,session.begin():
        country=_player_country(session,user_id);own=country.PANSTWO_ID
        row=session.scalar(select(Occupation).where(Occupation.id==natural(data.get('occupation_id'),'Okupacja',1),Occupation.kind=='region',
                           Occupation.occupier_id==own,Occupation.status=='ACTIVE').with_for_update())
        if row is None:raise FinanceError('Ten region nie jest okupowany przez nasze państwo.')
        now=game_now()
        if now<row.started_at+timedelta(days=ANNEX_DAYS):raise FinanceError(f'Aneksja będzie możliwa po {ANNEX_DAYS} dniach Entendy okupacji ({(row.started_at+timedelta(days=ANNEX_DAYS)):%Y-%m-%d %H:%M}).')
        lock_countries(session,own,row.owner_id)
        if not held_all(session,row.region_id,own,row.owner_id):raise FinanceError('Aneksja wymaga kontroli nad wszystkimi bazami i miastami regionu — przeciwnik odbił część z nich.')
        owner=row.owner_id
        capital=session.scalar(select(Miasto.miasto_id).where(Miasto.region_id==row.region_id,Miasto.miasto_typ_id==1,Miasto.panstwo_id==owner).limit(1))
        name=annex(session,row,own,now)
        who=names(session,own,owner)
        notify(session,owner,f'Region {name} został anektowany przez {who.get(own)}.')
        notify(session,own,f'Anektowaliśmy region {name}.')
        if capital is not None:
            from game.sovereignty import lose_sovereignty
            lose_sovereignty(session,owner,own,row.region_id,row.id,now)
        reconcile_maintenance(session,own);reconcile_maintenance(session,owner)
        return row.region_id


def region_population(session,region_id):
    rural=session.scalar(select(Region.region_ludnosc_pozamiejska).where(Region.region_id==region_id)) or 0
    urban=session.scalar(select(func.sum(Miasto.miasto_populacja)).where(Miasto.region_id==region_id)) or 0
    return int(rural)+int(urban)


def recount_country(session,country_id):
    """Population and area of a country from its regions and cities (as after a secession), 14 Nov 2026."""
    rural=session.scalar(select(func.sum(Region.region_ludnosc_pozamiejska)).where(Region.panstwo_id==country_id)) or 0
    urban=session.scalar(select(func.sum(Miasto.miasto_populacja)).where(Miasto.panstwo_id==country_id)) or 0
    areas=list(session.scalars(select(Region.region_powierzchnia).where(Region.panstwo_id==country_id)))
    area=sum(areas) if all(value is not None for value in areas) else None
    session.execute(update(Panstwo).where(Panstwo.PANSTWO_ID==country_id)
                    .values(panstwo_populacja=int(rural)+int(urban),panstwo_powierzchnia=area,panstwo_populacja_audit=datetime.now())
                    .execution_options(synchronize_session=False))


def transfer_gdp(session,source,target,amount,moment):
    """Moves `amount` of GDP between countries and records both changes in the GDP history (source ANEKSJA)."""
    from models import PKBStateHistory
    amount=int(amount or 0)
    if amount<=0 or source==target:return 0
    values=dict(session.execute(select(Panstwo.PANSTWO_ID,Panstwo.panstwo_PKB).where(Panstwo.PANSTWO_ID.in_([source,target]))).all())
    amount=min(amount,int(values.get(source) or 0))
    if amount<=0:return 0
    day=moment.date()
    for country_id,delta in ((source,-amount),(target,amount)):
        old=int(values.get(country_id) or 0);new=old+delta
        session.execute(update(Panstwo).where(Panstwo.PANSTWO_ID==country_id).values(panstwo_PKB=new).execution_options(synchronize_session=False))
        # One history row per country, Entenda day and source (uq_pkb_state_once): later annexations of the day are added to it.
        entry=session.scalar(select(PKBStateHistory).where(PKBStateHistory.panstwo_id==country_id,PKBStateHistory.data_entenda==day,
                                                           PKBStateHistory.source==GDP_SOURCE).with_for_update())
        if entry is None:
            session.add(PKBStateHistory(panstwo_id=country_id,data_entenda=day,data_rzeczywista=datetime.now(),source=GDP_SOURCE,
                                        old_pkb=old,new_pkb=new,change_delta=delta))
            session.flush()
        else:
            entry.new_pkb=new;entry.change_delta=int(entry.change_delta or 0)+delta;entry.data_rzeczywista=datetime.now()
    return amount


def annexed_gdp(session,owner_id,region_id):
    """GDP that follows an annexed region: the owner's GDP per capita × the region's population."""
    gdp,population=session.execute(select(Panstwo.panstwo_PKB,Panstwo.panstwo_populacja).where(Panstwo.PANSTWO_ID==owner_id)).one()
    if not gdp or not population:return 0
    people=min(region_population(session,region_id),int(population))
    return int((Decimal(int(gdp))*people/Decimal(int(population))).to_integral_value())


def annex(session,row,own,now):
    """Moves the region and its cities to the occupier; occupied bases change hands with the occupying armies as their garrison.
    14 Nov 2026: the region's share of GDP (owner's GDP per capita × region population) moves to the annexer and the population
    and area of both countries are recounted."""
    from game.military_service import BASES
    gdp=annexed_gdp(session,row.owner_id,row.region_id)
    region=session.scalar(select(Region).options(lazyload('*')).where(Region.region_id==row.region_id).with_for_update())
    from game.foreign_mining import seize
    seize(session,row.region_id,own,now)
    region.panstwo_id=own
    for city in session.scalars(select(Miasto).options(lazyload('*')).where(Miasto.region_id==row.region_id).with_for_update()):city.panstwo_id=own
    session.flush()
    from game.region_history import record   # 23 Nov 2026: historia przynależności (wyzwalanie spod aneksji)
    record(session,row.region_id,row.owner_id,own,'ANNEX',now,occupation_id=row.id)
    transfer_gdp(session,row.owner_id,own,gdp,now)
    recount_country(session,own);recount_country(session,row.owner_id)
    old_army=session.scalar(select(Wojsko).where(Wojsko.panstwo_id==row.owner_id).with_for_update());new_army=session.scalar(select(Wojsko).where(Wojsko.panstwo_id==own).with_for_update())
    for occupation in session.scalars(select(Occupation).where(Occupation.region_id==row.region_id,Occupation.status=='ACTIVE',Occupation.occupier_id==own,Occupation.kind.in_(['base','city']))):
        occupation.status='ANNEXED';occupation.ended_at=now
        if occupation.kind=='base' and occupation.base_id:
            base=session.get(MilitaryBase,occupation.base_id,with_for_update=True)
            if base is None:continue
            label,base_field,soldier_field=BASES[base.kind]
            # The previous owner loses the base and the equipment left inside; the occupying army becomes its garrison.
            lost={resource:count for resource,count in (base.garrison or {}).items() if count}
            if old_army is not None:
                from game.military_service import RESOURCES
                for resource,count in lost.items():
                    field=soldier_field if resource=='soldiers' else RESOURCES[resource][1]
                    if field:setattr(old_army,field,max(0,(getattr(old_army,field) or 0)-count))
                if base_field:setattr(old_army,base_field,max(0,(getattr(old_army,base_field) or 0)-1))
            if new_army is not None and base_field:setattr(new_army,base_field,(getattr(new_army,base_field) or 0)+1)
            base.panstwo_id=own;base.garrison={}
            merge_into_base(session,base,_occupiers(session,'base',base.id),own)
        elif occupation.kind=='city' and occupation.city_id:
            for army in _occupiers(session,'city',occupation.city_id):army.status='DEFENDING';army.role='city_defense';army.target_country_id=own
    row.status='ANNEXED';row.ended_at=now
    return region.region_nazwa


# ---------------- views ----------------

def army_data(army,flags=None):
    stamp=lambda value:value.isoformat()+'Z' if value else None
    return {'id':army.id,'countryId':army.panstwo_id,'role':army.role,'status':army.status,'sourceBaseId':army.source_base_id,'units':army_units(army),
            'targetKind':army.target_kind,'targetBaseId':army.target_base_id,'targetArmyId':army.target_army_id,'targetRegionId':army.target_region_id,'targetCityId':army.target_city_id,'targetCountryId':army.target_country_id,
            'targetName':army.target_name,'source':[army.source_x,army.source_y] if army.source_x is not None else None,'target':[army.target_x,army.target_y] if army.target_x is not None else None,
            'distanceKm':army.distance_km,'speedKmh':army.speed_kmh,'startsAt':stamp(army.starts_at),'borderAt':stamp(army.border_at),'arrivesAt':stamp(army.arrives_at),
            'resolvedAt':stamp(army.resolved_at),'cost':str(army.cost),'battle':army.battle}


def visible_armies(session,country_id):
    """Own armies, armies marching against us (after they crossed our border) and every army defending or occupying a city/base we can see."""
    now=game_now()
    query=select(LandArmy).where(or_(
        and_(LandArmy.panstwo_id==country_id,or_(LandArmy.status.in_(LIVE),LandArmy.resolved_at>=now-timedelta(days=2))),
        and_(LandArmy.target_country_id==country_id,LandArmy.status=='MARCHING',LandArmy.border_at<=now),
        LandArmy.status=='OCCUPYING')).order_by(LandArmy.id)
    return [army_data(army) for army in session.scalars(query)]


def visible_occupations(session,country_id=None):
    """23 Nov 2026: `restore` — przy okupacji regionu przez `country_id`: państwo, któremu można przywrócić region
    zamiast aneksji (game.liberation), z informacją, czy zostanie wskrzeszone."""
    stamp=lambda value:value.isoformat()+'Z' if value else None
    from game.liberation import restore_candidate
    def restore(row):
        if country_id is None or row.kind!='region' or row.occupier_id!=country_id or row.status!='ACTIVE':return None
        try:return restore_candidate(session,row,country_id)
        except Exception:return None
    return [{'id':row.id,'kind':row.kind,'baseId':row.base_id,'cityId':row.city_id,'regionId':row.region_id,'ownerId':row.owner_id,'occupierId':row.occupier_id,
             'status':row.status,'startedAt':stamp(row.started_at),'annexAt':stamp(row.started_at+timedelta(days=ANNEX_DAYS)) if row.kind=='region' else None,
             'restore':restore(row)}
            for row in session.scalars(select(Occupation).where(Occupation.status.in_(['ACTIVE','PENDING','DECLINED'])).order_by(Occupation.id))]


def end_occupations_on_peace(session,a,b,moment=None):
    """17 Nov 2026 (decyzja administratora): zawarcie pokoju kończy okupację.
    Wszystkie okupacje baz, miast i regionów między stronami pokoju (w obu kierunkach) zostają zakończone — obiekty wracają
    do właściciela, a regiony nie podlegają już aneksji. Armie okupacyjne i maszerujące wracają do swoich baz macierzystych
    (gdy baza nie istnieje albo jest okupowana, żołnierze wracają do ogólnej puli wojsk państwa). Zwraca liczbę zakończonych okupacji."""
    moment=moment or game_now()
    pairs=[(a,b),(b,a)]
    ended=0
    for occupier,owner in pairs:
        objects=list(session.scalars(select(Occupation).where(Occupation.kind.in_(['base','city']),Occupation.occupier_id==occupier,
                                                             Occupation.owner_id==owner,Occupation.status=='ACTIVE').with_for_update()))
        released=[]
        for occupation in objects:
            object_id=occupation.base_id if occupation.kind=='base' else occupation.city_id
            for army in _occupiers(session,occupation.kind,object_id):
                if army.panstwo_id==occupier:_return_home(session,army)
            occupation.status='ENDED';occupation.ended_at=moment;ended+=1
            released.append(occupation)
        regions=list(session.scalars(select(Occupation).where(Occupation.kind=='region',Occupation.occupier_id==occupier,Occupation.owner_id==owner,
                                                             Occupation.status.in_(['PENDING','DECLINED','ACTIVE'])).with_for_update()))
        for row in regions:
            if row.status=='ACTIVE':ended+=1
            row.status='ENDED';row.ended_at=moment
        # Armie w marszu na terytorium drugiej strony zawracają.
        for army in session.scalars(select(LandArmy).where(LandArmy.panstwo_id==occupier,LandArmy.target_country_id==owner,LandArmy.status=='MARCHING').with_for_update()):
            _return_home(session,army)
        if released or regions:
            n=names(session,occupier,owner)
            places=', '.join(sorted({o.city_id and session.scalar(select(Miasto.miasto_nazwa).where(Miasto.miasto_id==o.city_id)) or f'baza #{o.base_id}' for o in released}))[:500]
            notify(session,owner,f'Zawarcie pokoju z państwem {n.get(occupier,"?")} zakończyło okupację naszego terytorium. Odzyskane obiekty: {places or "—"}; regiony nie są już okupowane.')
            notify(session,occupier,f'Zawarcie pokoju z państwem {n.get(owner,"?")} zakończyło naszą okupację jego terytorium. Wojska okupacyjne wróciły do baz.')
    session.flush()
    if ended:
        from game.military_service import reconcile_maintenance
        for country in (a,b):
            try:
                with session.begin_nested():reconcile_maintenance(session,country)
            except FinanceError:pass   # rozliczenie utrzymania nie może zablokować zawarcia pokoju
    return ended
