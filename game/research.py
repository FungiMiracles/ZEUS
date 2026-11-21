"""Research screen and authenticated, CSRF-protected investments."""
from decimal import Decimal
from flask import Blueprint,render_template,redirect,url_for,jsonify,request
from sqlalchemy import select
from extensions import db
from game.forum import player
from game.military import csrf_valid
from game.finance_service import FinanceError,game_now,period_key
from game.finance_models import StateBudget
from game.budget_transfers import sector_balances
from game.research_models import ResearchAccount,AmmunitionFactory
from game.industry_catalog import TECHNOLOGIES,PLANNED_TECHNOLOGIES,RESEARCH_TECHNOLOGIES
from game.research_service import node_state,settle_production,change_research,POINT_PRICE,FACTORY_PRICE
from game.country_summary import country_summary,own_metropolitan_region_ids

research_bp=Blueprint('game_research',__name__,url_prefix='/game/badania')


def state_data(session,country):
    row=settle_production(session,country)
    year,period=period_key(game_now())
    budget=session.scalar(select(StateBudget).where(StateBudget.panstwo_id==country,StateBudget.game_year==year,StateBudget.period==period))
    balances=sector_balances(session,budget) if budget else {}
    return {'points':row.points if row else 0,'ammunition':row.ammunition if row else 0,
        'nodes':{**{key:node_state((row.nodes if row else {}).get(key,0),key,getattr(row,'timers',None) if row else None,game_now()) for key in TECHNOLOGIES},**{key:dict(invested=0,level=0,progress=0,required=0,maximum=False) for key in PLANNED_TECHNOLOGIES}},
        'budget':str(balances.get('research',{}).get('remaining',0)),'infrastructureBudget':str(balances.get('infrastructure',{}).get('remaining',0)),
        'year':year,'period':period,'gameNow':game_now().isoformat(),'timeMultiplier':__import__('engine.clock',fromlist=['get_time_multiplier']).get_time_multiplier(),'durations':_durations(session,country),'educationBonus':_education_bonus(session,country),'pointPrice':POINT_PRICE,'factoryPrice':FACTORY_PRICE, 'technologies':RESEARCH_TECHNOLOGIES,
        'factories':[{'id':f.id,'regionId':str(f.region_id),'position':[f.map_x,f.map_y],'level':f.level,'dailyProduction':__import__('game.industry_catalog',fromlist=['FACTORIES']).FACTORIES[f.kind]['levels'][f.level-1]['quantity'] if f.health>0 and not f.paused else 0,'health':f.health} for f in session.scalars(select(AmmunitionFactory).where(AmmunitionFactory.panstwo_id==country,AmmunitionFactory.removed_at.is_(None)))]}


def _education_bonus(session,country):
    from game.research_timing import education_bonus
    from game.cities import education_level
    return education_bonus(education_level(session,country))


def _durations(session,country):
    """21 Nov 2026: czas rozwoju technologii po bonusie za poziom edukacji powyżej 50."""
    from game.research_timing import DURATION_DAYS,effective_days
    bonus=_education_bonus(session,country)
    return {node:effective_days(node,bonus) for node in DURATION_DAYS}


@research_bp.get('')
def page():
    user,country=player()
    if user is None:return redirect(url_for('wejscie'))
    state=state_data(db.session,country.PANSTWO_ID)
    layout=technology_layout()
    rendered=render_template('game/research.html',research_state=state,technologies=RESEARCH_TECHNOLOGIES,technology_layout=layout,research_budget_display=format(Decimal(state['budget']),',.2f').replace(',',' ').replace('.',','),game_user=user,game_country=country_summary(country),game_active_page='research',game_home_url=url_for('game_main_page'),game_logout_url=url_for('game_logout'))
    db.session.commit();return rendered


@research_bp.get('/stan')
def state():
    user,country=player()
    if user is None:return jsonify(error='Zaloguj się ponownie.'),401
    data=state_data(db.session,country.PANSTWO_ID);db.session.commit();response=jsonify(data);response.headers['Cache-Control']='no-store';return response


@research_bp.post('/zmien')
def change():
    user,country=player()
    if user is None:return jsonify(error='Zaloguj się ponownie.'),401
    if not csrf_valid():return jsonify(error='Sesja formularza wygasła. Odśwież stronę.'),403
    data=request.get_json(silent=True)
    if not isinstance(data,dict):return jsonify(error='Nieprawidłowe dane.'),400
    # Release read-session locks before entering the transaction service.
    user_id=user.id;db.session.rollback()
    try:change_research(user_id,data);return jsonify(ok=True)
    except FinanceError as error:return jsonify(error=str(error)),400


def technology_layout():
    from math import sin,cos,radians,hypot
    positions={'method':{'x':450,'y':390}}
    def place(key,angle,radius,origin='method'):
        center=positions[origin]
        positions[key]={'x':round(center['x']+cos(radians(angle))*radius,2),'y':round(center['y']+sin(radians(angle))*radius,2)}
    place('arms_industry',-135,95)
    military=[('short_missiles',-146),('interceptor_ammo',-126),('drones',-106),('warship',-86)]
    for key,angle in military:place(key,angle,170)
    for key,angle,radius in [('nuclear_missiles',-146,380),('medium_missiles',-146,240),('long_missiles',-146,310),('fighters',-106,240),('submarine',-94,245),('carrier',-78,245)]:place(key,angle,radius)
    # Armoured vehicles and tanks on one straight line leading out of the arms industry (10 Nov 2026).
    place('armored',160,85,'arms_industry');place('tanks',160,160,'arms_industry')
    # Move the complete arms branch together, preserving its internal spacing.
    pending=['arms_industry']
    while pending:
        key=pending.pop();positions[key]['x']-=45;positions[key]['y']-=45
        pending.extend(child for child,rule in RESEARCH_TECHNOLOGIES.items() if rule['parent']==key)
    place('mining_industry',-35,95)
    mining=[key for key,rule in TECHNOLOGIES.items() if rule['parent']=='mining_industry']
    for i,key in enumerate(mining):place(key,-68+i*12,195)
    place('it_industry',47,95)
    for i,key in enumerate(['chip_simple','chip_kerbit','chip_natsyt','chip_cemium_i','chip_cemium_ii']):place(key,47,160+i*55)
    # Radar reconnaissance (11 Nov 2026): a side bubble branching off the natsyt chip.
    place('radar',-43,70,'chip_natsyt')
    place('energy_industry',135,95)
    for key,angle in [('power_coal',111),('power_nuclear',127),('power_wind',143),('power_solar',159)]:place(key,angle,190,'energy_industry')
    # Environmental protection branch (10 Nov 2026), straight below the research method.
    place('environment_tech',90,95)
    place('air_filters',70,110,'environment_tech');place('waste_filters',110,110,'environment_tech')
    # Transport (19 Nov 2026): transport i komunikacja w lewo od metody badawczej, kolej dalej w tej samej linii.
    place('national_hubs',180,95);place('rail_transport',180,80,'national_hubs')
    # Transport lotniczy (20 Nov 2026, nieaktywny): kolejny bąbel w tej samej linii, za koleją.
    place('air_transport',180,80,'rail_transport')
    edges=[]
    for key,rule in RESEARCH_TECHNOLOGIES.items():
        if not rule['parent']:continue
        a=positions[rule['parent']];b=positions[key];dx=b['x']-a['x'];dy=b['y']-a['y'];distance=hypot(dx,dy)
        edges.append({'child':key,'startX':a['x']+dx/distance*23,'startY':a['y']+dy/distance*23,'endX':b['x']-dx/distance*27,'endY':b['y']-dy/distance*27})
    return {'positions':positions,'edges':edges,'width':900,'height':780}
