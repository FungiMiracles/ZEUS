"""Panel państwa (13 Nov 2026): dane mapy (regiony, obiekty) i kontenery informacyjne (alerty, energetyka,
sytuacja międzynarodowa, produkcja przemysłowa). Wyłącznie odczyt."""
from sqlalchemy import select,func,or_
from extensions import db
from game.governance import controlled_ids
from game.finance_service import game_now

# Filtry mapy pogrupowane jak w panelu obronnym: (grupa, [(kod, etykieta, ikona)])
MAP_FILTERS=[
    ('Wojsko',[('land','Bazy lądowe','BAZA.svg'),('air','Bazy powietrzne','MYŚLIWIEC.svg'),('naval','Bazy morskie','OKRĘT WOJENNY.svg'),
               ('nuclear','Silosy atomowe','SILOS ATOMOWY.svg'),('defenses','Obrona przeciwrakietowa','OBRONA PRZECIWRAKIETOWA.svg'),
               ('radars','Radary','RADAR.svg'),('vessels','Okręty na morzu','OKRĘT WOJENNY.svg')]),
    ('Gospodarka',[('mines','Kopalnie','KOPALNIA.svg'),('factories','Fabryki','FABRYKA.svg'),('power','Elektrownie','ELEKTROWNIA WĘGLOWA.svg')]),
    ('Infrastruktura',[('cities','Miasta','MIASTO.svg')]),
]
VESSEL_ICONS={'warships':'OKRĘT WOJENNY.svg','submarines':'SUBMARINE.svg','carriers':'LOTNISKOWIEC.svg'}
VESSEL_LABELS={'warships':'Okręt wojenny','submarines':'Okręt podwodny','carriers':'Lotniskowiec'}
ATTACK_LABELS={'air':'Bombardowanie z powietrza','missile':'Atak rakietowy','naval':'Atak z okrętu'}


def region_info(country_id):
    """{region_id: {'population', 'infrastructure'}} dla regionów państwa (średnia jak w podsumowaniu państwa)."""
    from models import Region,Miasto
    ids=controlled_ids(db.session,country_id) or [country_id]
    cities={region:int(total or 0) for region,total in db.session.execute(select(Miasto.region_id,func.sum(Miasto.miasto_populacja)).where(Miasto.panstwo_id.in_(ids)).group_by(Miasto.region_id))}
    result={}
    for r in db.session.execute(select(Region.region_id,Region.region_ludnosc_pozamiejska,Region.region_polozenie_id,Region.region_stan_infra_kolejowej,Region.region_stan_infra_drogowej,
                                      Region.region_stan_infra_energetycznej,Region.region_stan_infra_mieszkalnej,Region.region_stan_infra_portowej).where(Region.panstwo_id.in_(ids))):
        values=[r.region_stan_infra_kolejowej,r.region_stan_infra_drogowej,r.region_stan_infra_energetycznej,r.region_stan_infra_mieszkalnej]
        if r.region_polozenie_id and r.region_polozenie_id!=1:values.append(r.region_stan_infra_portowej)
        values=[v for v in values if v is not None]
        result[str(r.region_id)]={'population':int(r.region_ludnosc_pozamiejska or 0)+cities.get(r.region_id,0),
                                  'infrastructure':round(sum(values)/len(values),1) if values else None}
    return result


def map_objects(country_id,icon_url):
    """Własne obiekty z map obrony, wojny i infrastruktury: {kind, name, position|path, icon, health}."""
    from game.military_models import MilitaryBase,MissileDefense,MilitaryVessel
    from game.commerce_models import Mine
    from game.research_models import AmmunitionFactory
    from game.industry_models import PowerPlant
    from game.industry_catalog import FACTORIES,POWER_PLANTS
    from game.mining_service import NAMES
    from game.military_service import BASES
    now=game_now();items=[]
    def add(kind,name,position,icon,health=None,**extra):
        if position and position[0] is not None and position[1] is not None:
            items.append({'kind':kind,'name':name,'position':[float(position[0]),float(position[1])],'icon':icon_url(icon),'health':health,**extra})
    for b in db.session.scalars(select(MilitaryBase).where(MilitaryBase.panstwo_id==country_id)):
        icon={'land':'BAZA.svg','air':'MYŚLIWIEC.svg','naval':'OKRĘT WOJENNY.svg','nuclear':'SILOS ATOMOWY.svg'}.get(b.kind,'BAZA.svg')
        add(b.kind,(b.name or f'{BASES[b.kind][0]} #{b.id}')+f' · poziom {b.level}',[b.map_x,b.map_y],icon,b.health)
    try:
        from game.missile_defense import defense_data
        # 19 Nov 2026: filtr „Obrona przeciwrakietowa” pokazuje tylko obronę regionów (plakietka na środku regionu);
        # obrona konkretnego obiektu należy do warstwy tego obiektu — widać ją tylko razem z nim (filtr obiektu).
        bases=dict(db.session.execute(select(MilitaryBase.id,MilitaryBase.kind).where(MilitaryBase.panstwo_id==country_id)).all())
        layer_of={'region':'defenses','city':'cities','mine':'mines','factory':'factories','power':'power','radar':'radars'}
        for d in db.session.scalars(select(MissileDefense).where(MissileDefense.panstwo_id==country_id)):
            layer=bases.get(d.target_id) if d.target_kind=='base' else layer_of.get(d.target_kind)
            if not layer:continue
            data=defense_data(d);add(layer,f'Obrona przeciwrakietowa #{d.id} · poziom {d.level}',data.get('position'),'OBRONA PRZECIWRAKIETOWA.svg',d.health,
                                     defense='region' if d.target_kind=='region' else 'object',regionId=str(d.region_id))
    except Exception:pass
    try:
        from game.radar_models import Radar
        for r in db.session.scalars(select(Radar).where(Radar.panstwo_id==country_id)):
            add('radars',f'Radar #{r.id} · poziom {r.level}',[r.map_x,r.map_y],'RADAR.svg',r.health)
    except Exception:pass
    try:
        from game.military_navy import vessel_position
        for v in db.session.scalars(select(MilitaryVessel).where(MilitaryVessel.panstwo_id==country_id,MilitaryVessel.status.in_(['sailing','stationed','returning']))):
            add('vessels',v.name or f'{VESSEL_LABELS.get(v.kind,"Okręt")} #{v.id}',vessel_position(v,now),VESSEL_ICONS.get(v.kind,'OKRĘT WOJENNY.svg'),v.health)
    except Exception:pass
    for m in db.session.scalars(select(Mine).where(Mine.panstwo_id==country_id,Mine.removed_at.is_(None))):
        add('mines',f'{NAMES.get(m.resource,m.resource)} #{m.id} · poziom {m.level}',[m.map_x,m.map_y],'KOPALNIA.svg',m.health)
    for f in db.session.scalars(select(AmmunitionFactory).where(AmmunitionFactory.panstwo_id==country_id,AmmunitionFactory.removed_at.is_(None))):
        add('factories',f'{FACTORIES[f.kind]["label"]} #{f.id} · poziom {f.level}',[f.map_x,f.map_y],'FABRYKA.svg',f.health)
    for p in db.session.scalars(select(PowerPlant).where(PowerPlant.panstwo_id==country_id,PowerPlant.removed_at.is_(None))):
        add('power',f'{POWER_PLANTS[p.kind]["label"]} #{p.id} · poziom {p.level}',[p.map_x,p.map_y],POWER_PLANTS[p.kind].get('icon') or 'ELEKTROWNIA WĘGLOWA.svg',round(p.health*100/3))
    return items


def _names():
    from models import Panstwo
    return dict(db.session.execute(select(Panstwo.PANSTWO_ID,Panstwo.panstwo_nazwa)).all())


def alerts(country_id,limit=6):
    """Najpilniejsze ostatnie zdarzenia: ataki na państwo (wszystkie rodzaje) i wypowiedzenia wojny."""
    from game.military_models import MilitaryFlight
    from game.land_war_models import LandArmy
    from game.diplomacy_models import DiplomaticAction
    from models import AudytStosunki
    names=_names();items=[]
    for f in db.session.scalars(select(MilitaryFlight).where(MilitaryFlight.target_country_id==country_id).order_by(MilitaryFlight.starts_at.desc()).limit(limit)):
        label='Uderzenie atomowe' if f.is_nuclear else ATTACK_LABELS.get(f.kind,'Atak')
        items.append({'kind':'attack','at':f.starts_at,'text':f'{label} — {names.get(f.panstwo_id,"przeciwnik")}: {f.target_name}'})
    for a in db.session.scalars(select(LandArmy).where(LandArmy.target_country_id==country_id,LandArmy.role=='invasion').order_by(LandArmy.starts_at.desc()).limit(limit)):
        items.append({'kind':'attack','at':a.starts_at,'text':f'Inwazja lądowa — {names.get(a.panstwo_id,"przeciwnik")}: {a.target_name}'})
    for d in db.session.scalars(select(DiplomaticAction).where(DiplomaticAction.target_country_id==country_id,DiplomaticAction.kind=='WAR',DiplomaticAction.status=='APPLIED').order_by(DiplomaticAction.id.desc()).limit(limit)):
        a,b=sorted((d.source_country_id,d.target_country_id))
        from datetime import timedelta
        at=db.session.scalar(select(AudytStosunki.data_zmiany_entenda).where(AudytStosunki.panstwo_id==a,AudytStosunki.panstwo_id2==b,
            AudytStosunki.data_zmiany_rzeczywista.between(d.created_at-timedelta(seconds=5),d.created_at+timedelta(minutes=2))).order_by(AudytStosunki.id).limit(1))
        items.append({'kind':'war','at':at,'text':f'Wypowiedzenie wojny przez {d.source_country_name}'})
    items.sort(key=lambda item:item['at'] or game_now().replace(year=1),reverse=True)
    return [{**item,'date':item['at'].strftime('%d.%m.%Y %H:%M') if item['at'] else ''} for item in items[:limit]]


def energy(country_id):
    try:
        from game.industry_service import energy_balance
        data=energy_balance(db.session,country_id)
        return {'production':float(data['production']),'consumption':float(data['consumption']),'sufficient':bool(data['sufficient'])}
    except Exception:
        return None


def international(country_id):
    from models import Stosunki,DictStosunkiRelacja,DictStosunkiStan
    from services.natural_resources import normalized
    from game.land_war_models import Occupation
    relations={id:normalized(name or '') for id,name in db.session.execute(select(DictStosunkiRelacja.relacja_id,DictStosunkiRelacja.relacja_nazwa))}
    states={id:normalized(name or '') for id,name in db.session.execute(select(DictStosunkiStan.stan_id,DictStosunkiStan.stan_nazwa))}
    alliances=wars=0
    for relation,state in db.session.execute(select(Stosunki.relacja_id,Stosunki.stan_id).where(or_(Stosunki.PANSTWO_ID==country_id,Stosunki.PANSTWO_ID2==country_id))):
        alliances+=relations.get(relation)=='sojusznicze';wars+=states.get(state)=='wojnakinetyczna'
    occupied=db.session.scalar(select(func.count()).select_from(Occupation).where(Occupation.kind=='region',Occupation.occupier_id==country_id,Occupation.status=='ACTIVE')) or 0
    return {'alliances':alliances,'wars':wars,'occupied':occupied}


def industry(country_id):
    from game.research_models import AmmunitionFactory
    from game.commerce_models import Mine
    factories=db.session.scalar(select(func.count()).select_from(AmmunitionFactory).where(AmmunitionFactory.panstwo_id==country_id,AmmunitionFactory.removed_at.is_(None),
                                AmmunitionFactory.health>0,AmmunitionFactory.paused.is_(False))) or 0
    mines=db.session.scalar(select(func.count()).select_from(Mine).where(Mine.panstwo_id==country_id,Mine.removed_at.is_(None),Mine.health>0,Mine.ready_at<=game_now())) or 0
    return {'factories':factories,'mines':mines}


def dashboard(country_id):
    """Dane czterech kontenerów; każdy liczony osobno, błąd jednego nie psuje panelu."""
    result={}
    for key,function in (('alerts',alerts),('energy',energy),('international',international),('industry',industry)):
        try:result[key]=function(country_id)
        except Exception:
            from flask import current_app
            current_app.logger.exception('Panel państwa: %s',key);result[key]=None
    return result
