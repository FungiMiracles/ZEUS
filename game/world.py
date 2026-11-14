"""Ekran „Świat” (13 Nov 2026): mapa polityczna i regionalna świata Entendy z tooltipami państw, regionów i miast."""
from flask import Blueprint,redirect,url_for,render_template,current_app
from sqlalchemy import select,func
from extensions import db
from game.forum import player
from game.finance_service import game_now
from engine.clock import get_time_multiplier
from game.country_summary import country_summary
from game.governance import controller_id
from game.commerce_models import TradeShipment

world_bp=Blueprint('game_world',__name__,url_prefix='/game/swiat')


def world_data():
    from models import Panstwo,Region,Miasto,DictPanstwoUstroj,DictMiastoTyp
    money=current_app.jinja_env.filters.get('game_money',lambda value:str(value))
    regimes=dict(db.session.execute(select(DictPanstwoUstroj.ustroj_id,DictPanstwoUstroj.ustroj_nazwa)).all())
    city_types=dict(db.session.execute(select(DictMiastoTyp.miasto_typ_id,DictMiastoTyp.miasto_typ_nazwa)).all())
    cache={}
    def owner_of(country_id):
        if country_id not in cache:cache[country_id]=controller_id(db.session,country_id)
        return cache[country_id]
    countries={}
    for c in db.session.scalars(select(Panstwo)):
        countries[str(c.PANSTWO_ID)]={'name':c.panstwo_nazwa,'fullName':getattr(c,'panstwo_pelna_nazwa',None) or c.panstwo_nazwa,
            'flag':url_for('static',filename='flags/'+(c.panstwo_nazwa or '').replace(' ','_')+'.jpg'),'regime':regimes.get(c.ustroj_id),
            'population':c.panstwo_populacja,'gdp':money(c.panstwo_PKB) if c.panstwo_PKB is not None else None,'controller':None}
    for id in list(countries):
        owner=owner_of(int(id))
        countries[id]['controller']=owner if owner!=int(id) else None
    city_population={region:int(total or 0) for region,total in db.session.execute(select(Miasto.region_id,func.sum(Miasto.miasto_populacja)).group_by(Miasto.region_id))}
    regions={}
    for r in db.session.execute(select(Region.region_id,Region.region_nazwa,Region.panstwo_id,Region.region_ludnosc_pozamiejska)):
        regions[str(r.region_id)]={'name':r.region_nazwa,'countryId':owner_of(r.panstwo_id),
                                   'population':int(r.region_ludnosc_pozamiejska or 0)+city_population.get(r.region_id,0)}
    occupied={}
    try:
        from game.land_war_models import Occupation
        for o in db.session.scalars(select(Occupation).where(Occupation.kind=='region',Occupation.status=='ACTIVE')):
            occupied[str(o.region_id)]={'occupierId':o.occupier_id,'occupier':(countries.get(str(o.occupier_id)) or {}).get('name')}
    except Exception:
        current_app.logger.exception('Ekran Świat: okupacje')
    cities={str(m.miasto_id):{'name':m.miasto_nazwa,'population':m.miasto_populacja,'type':city_types.get(m.miasto_typ_id),'port':m.czy_portowe=='TAK',
                              'capital':m.miasto_typ_id==1}
            for m in db.session.scalars(select(Miasto).where(Miasto.czy_na_mapie=='TAK'))}
    # Kontynenty: państwa wg kontynentu i łączne wskaźniki (13 Nov 2026)
    from models import DictKontynent
    names=dict(db.session.execute(select(DictKontynent.kontynent_id,DictKontynent.kontynent_nazwa)).all())
    continents={}
    for c in db.session.scalars(select(Panstwo)):
        if c.kontynent_id is None or getattr(c,'status','aktywne')!='aktywne':continue   # tylko istniejące państwa
        item=continents.setdefault(str(c.kontynent_id),{'name':names.get(c.kontynent_id),'countries':0,'population':0,'gdp':0})
        item['countries']+=1;item['population']+=int(c.panstwo_populacja or 0);item['gdp']+=c.panstwo_PKB or 0
        countries[str(c.PANSTWO_ID)]['continentId']=str(c.kontynent_id)
    for item in continents.values():item['gdp']=money(item['gdp'])
    # Płynące statki towarowe (wszystkie aktywne rejsy)
    ships=[]
    try:
        from game.trade_navigation import active_shipments
        for ship in db.session.scalars(active_shipments(db.session).order_by(TradeShipment.id)):
            ships.append({'id':ship.id,'seller':(countries.get(str(ship.seller_id)) or {}).get('name'),'buyer':(countries.get(str(ship.buyer_id)) or {}).get('name'),
                          'route':ship.route or [[ship.source_x,ship.source_y],[ship.target_x,ship.target_y]],'source':[ship.source_x,ship.source_y],'target':[ship.target_x,ship.target_y],
                          'startsAt':ship.starts_at.isoformat()+'Z','arrivesAt':ship.arrives_at.isoformat()+'Z','health':ship.health,
                          'flag':(countries.get(str(ship.origin_country_id or ship.seller_id)) or {}).get('flag')})
    except Exception:
        current_app.logger.exception('Ekran Świat: statki')
    return {'countries':countries,'regions':regions,'occupied':occupied,'cities':cities,'continents':continents,'ships':ships}


def world_vessels(country):
    """14 Nov 2026: okręty wojenne i lotniskowce wszystkich państw na mapie świata (z flagą), jak na panelu wojennym."""
    if country is None:return []
    try:
        from game.military import visible_vessels
        from game.military_service import enemies
        from models import Panstwo
        names=dict(db.session.execute(select(Panstwo.PANSTWO_ID,Panstwo.panstwo_nazwa)).all())
        items=[]
        for v in visible_vessels(country.PANSTWO_ID,bool(enemies(db.session,country.PANSTWO_ID))):
            name=names.get(v['countryId']) or ''
            items.append({'id':v['id'],'kind':v['kind'],'name':v['name'],'status':v['status'],'health':v['health'],'own':v['countryId']==country.PANSTWO_ID,
                          'country':name,'flag':url_for('static',filename='flags/'+name.replace(' ','_')+'.jpg'),
                          'route':v['route'],'source':v['source'],'target':v['target'],'startsAt':v['startsAt'],'arrivesAt':v['arrivesAt']})
        return items
    except Exception:
        current_app.logger.exception('Ekran Świat: okręty')
        return []


@world_bp.get('')
def page():
    user,country=player()
    if user is None:return redirect(url_for('wejscie'))
    config={**world_data(),'countryId':country.PANSTWO_ID if country else None,'vessels':world_vessels(country),
            'vesselIcons':{kind:url_for('static',filename='icons/'+name) for kind,name in [('warships','OKRĘT WOJENNY.svg'),('submarines','SUBMARINE.svg'),('carriers','LOTNISKOWIEC.svg')]},
            'regionsUrl':url_for('static',filename='maps/entenda_regiony.geojson'),
            'countriesUrl':url_for('region_sovereignty.country_boundaries'),
            'watersUrl':url_for('game_world.territorial_waters'),
            'citiesUrl':url_for('static',filename='maps/entenda_miasta.geojson'),
            'cityIcon':url_for('static',filename='icons/MIASTO.svg'),'regionIcon':url_for('static',filename='icons/WORLD.svg'),
            'shipIcon':url_for('static',filename='icons/CARGO SHIP.svg'),'gameNow':game_now().isoformat()+'Z','timeMultiplier':get_time_multiplier()}
    response=render_template('game/world.html',game_user=user,game_country=country_summary(country),game_home_url=url_for('game_main_page'),
                             game_logout_url=url_for('game_logout'),game_active_page='world',world_config=config)
    db.session.rollback()
    return response


@world_bp.get('/wody-terytorialne.geojson')
def territorial_waters():
    """15 Nov 2026: wody terytorialne państw (100 km od wybrzeża) do filtra mapy świata."""
    from flask import jsonify
    from game.finance_service import FinanceError
    from game.territorial_waters import waters_geojson
    user,_country=player()
    if user is None:return jsonify(error='Zaloguj się do gry.'),401
    try:data=waters_geojson(db.session)
    except FinanceError as error:return jsonify(error=str(error)),409
    finally:db.session.rollback()
    response=jsonify(data);response.headers['Cache-Control']='private, max-age=60'
    return response
