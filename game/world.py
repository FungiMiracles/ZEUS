"""Ekran „Świat” (13 Nov 2026): mapa polityczna i regionalna świata Entendy z tooltipami państw, regionów i miast."""
from flask import Blueprint,redirect,url_for,render_template,current_app
from sqlalchemy import select,func
from extensions import db
from game.forum import player
from game.country_summary import country_summary
from game.governance import controller_id

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
    return {'countries':countries,'regions':regions,'occupied':occupied,'cities':cities}


@world_bp.get('')
def page():
    user,country=player()
    if user is None:return redirect(url_for('wejscie'))
    config={**world_data(),'countryId':country.PANSTWO_ID if country else None,
            'regionsUrl':url_for('static',filename='maps/entenda_regiony.geojson'),
            'countriesUrl':url_for('region_sovereignty.country_boundaries'),
            'citiesUrl':url_for('static',filename='maps/entenda_miasta.geojson'),
            'cityIcon':url_for('static',filename='icons/MIASTO.svg'),'regionIcon':url_for('static',filename='icons/WORLD.svg')}
    response=render_template('game/world.html',game_user=user,game_country=country_summary(country),game_home_url=url_for('game_main_page'),
                             game_logout_url=url_for('game_logout'),game_active_page='world',world_config=config)
    db.session.rollback()
    return response
