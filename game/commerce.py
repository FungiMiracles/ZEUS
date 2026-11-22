"""Handel międzypaństwowy i interfejs magazynu oraz kopalń."""
import secrets
from game.governance import controller_id
from flask import Blueprint,render_template,request,session,jsonify,redirect,url_for
from sqlalchemy import select,or_
from extensions import db
from models import Panstwo,Miasto
from services.natural_resources import RESOURCES
from game.forum import player
from game.country_summary import country_summary
from game.finance_models import StateFinancialAccount
from game.finance_service import FinanceError,game_now
from game.military import csrf_valid
from game.military_geography import city_point
from game.military_flights import calibration
from game.mining_service import warehouse,mine_data,mining_budget,build_mine,extract_country,RULES,NAMES
from game.trade_service import create_offer,cancel_offer,buy_offer,reprice_offer,set_tariff,set_port_access,port_allows,ports,tariff,deliver_shipments,SHIP_SPEED
from game.commerce_models import Mine,TradeOffer,TradeShipment,PortTariff
from game.trade_goods import AMMUNITION,AMMUNITION_LABEL,trade_warehouse
from game.trade_diplomacy import ammunition_allowed,allied_country_ids
from engine.clock import get_time_multiplier

trade_bp=Blueprint('game_trade',__name__,url_prefix='/game/handel')


def resource_catalog():
    from game.industry_catalog import MINE_RULES,GOODS,TECHNOLOGIES
    files=['WEGIEL.svg','ROPA.svg','ZŁOTO.svg','SREBRO.svg','KAMIEŃ.svg','NATSYT.svg','KERBIT.svg','CEMIUM.svg','URAN.svg','ŻELAZO.svg']
    return {code:{'label':label,'icon':url_for('static',filename='icons/'+file,v='20261108-ui2'),'mineName':NAMES[code],
        'cost':RULES[code][0],'days':RULES[code][1],'technology':MINE_RULES[code][1],
        'technologyLabel':TECHNOLOGIES[MINE_RULES[code][1]]['label'],
        'levels':[{'level':i+1,'cost':cost*1000000000,'dailyExtraction':MINE_RULES[code][3][i]} for i,cost in enumerate(MINE_RULES[code][2])]} for (code,label),file in zip(RESOURCES,files)}

def goods_catalog():
    from game.industry_catalog import GOODS
    return {**resource_catalog(),**{code:{'label':label,'icon':url_for('static',filename='icons/'+file,v='20261108-ui2')} for code,(label,file) in GOODS.items()},AMMUNITION:{'label':AMMUNITION_LABEL,'icon':url_for('static',filename='icons/AMMO.svg')}}


def goods_order():
    """19 Nov 2026: kolejność towarów na ekranach — surowce wydobywalne, produkty fabryk (chipy), sprzęt wojskowy
    (uzbrojenie i amunicja przeciwrakietowa). Słownik w JSON-ie traci kolejność (tojson sortuje klucze), stąd jawna lista."""
    from game.industry_catalog import GOODS,ARMY_GOODS
    return ([code for code,_ in RESOURCES]+[code for code in GOODS if code not in ARMY_GOODS]
            +[code for code in GOODS if code in ARMY_GOODS]+[AMMUNITION])


def settle_own(country_id):
    deliver_shipments(db.session,game_now(),country_id)
    from game.research_service import settle_production
    settle_production(db.session,country_id,game_now())


def mining_state(country_id):
    budget,total,available=mining_budget(db.session,country_id)
    from game.industry_service import researched
    from game.industry_catalog import TECHNOLOGIES
    return {'technologies':{key:researched(db.session,country_id,key) for key in TECHNOLOGIES},'warehouse':trade_warehouse(db.session,country_id),'mines':[mine_data(mine,game_now()) for mine in db.session.scalars(select(Mine).where(Mine.panstwo_id==country_id,Mine.removed_at.is_(None)).order_by(Mine.id))],
            'budgetTotal':str(total),'budgetAvailable':str(available),'gameNow':game_now().isoformat()+'Z','timeMultiplier':get_time_multiplier()}


def trade_state(country_id):
    all_ports=ports(db.session);own=any(controller_id(db.session,port.panstwo_id)==country_id for port in all_ports)
    from game.trade_service import departure_countries
    senders=departure_countries(db.session,country_id,all_ports)   # 18 Nov 2026: None = własne porty
    tariffs={row.panstwo_id:row.rate for row in db.session.scalars(select(PortTariff))}
    names=dict(db.session.execute(select(Panstwo.PANSTWO_ID,Panstwo.panstwo_nazwa)).all())
    cities={city.miasto_id:city for city in all_ports}
    from game.trade_service import expire_offers,offer_expires_at
    expire_offers(db.session)   # 13 Nov 2026: oferty niesprzedane przez 14 dni Entendy wracają do sprzedających
    stamp=lambda value:value.isoformat()+'Z' if value else None
    # 22 Nov 2026: oferty bez transportu — towar w magazynie sprzedającego; drogę dostawy wybiera kupujący (game.trade_routes)
    from game.airports import active_airports
    from game.trade_routes import AIR_SPEED,RAIL_SPEED,customs_rates,legs_json
    from game.governance import controlled_ids
    working=active_airports(db.session)
    own_ids=set(controlled_ids(db.session,country_id)) or {country_id}
    own_airports=[a for a in working if a.panstwo_id in own_ids]
    city_names=dict(db.session.execute(select(Miasto.miasto_id,Miasto.miasto_nazwa)).all())
    offers=[]
    for offer in db.session.scalars(select(TradeOffer).where(TradeOffer.status=='open').order_by(TradeOffer.id.desc())):
        if country_id!=offer.panstwo_id and (country_id in offer.excluded or (AMMUNITION in offer.cargo and not ammunition_allowed(db.session,offer.panstwo_id,country_id))):continue
        from game.warehouse import warehouse_city
        origin=warehouse_city(db.session,controller_id(db.session,offer.panstwo_id))
        offers.append({'id':offer.id,'sellerId':offer.panstwo_id,'seller':names.get(offer.panstwo_id,''),'flag':url_for('static',filename='flags/'+names.get(offer.panstwo_id,'').replace(' ','_')+'.jpg'),'cargo':offer.cargo,'price':str(offer.price),
            'warehouse':city_names.get(origin,''),'own':offer.panstwo_id==country_id,
            'createdAt':stamp(offer.created_game_at),'priceChangedAt':stamp(offer.price_changed_game_at),'expiresAt':stamp(offer_expires_at(offer)),
            'excluded':offer.excluded if offer.panstwo_id==country_id else [],'usable':True})
    active=list(db.session.scalars(select(TradeShipment).where(TradeShipment.delivered_at.is_(None),TradeShipment.sunk_at.is_(None),TradeShipment.health>0).order_by(TradeShipment.id)))
    recent=list(db.session.scalars(select(TradeShipment).where(or_(TradeShipment.seller_id==country_id,TradeShipment.buyer_id==country_id),or_(TradeShipment.delivered_at.is_not(None),TradeShipment.sunk_at.is_not(None))).order_by(TradeShipment.id.desc()).limit(20)))
    shipments=[]
    for shipment in active+recent:
        own_shipment=country_id in (shipment.seller_id,shipment.buyer_id)
        item={'id':shipment.id,'sellerId':shipment.seller_id,'buyerId':shipment.buyer_id,'seller':names.get(shipment.seller_id,''),'buyer':names.get(shipment.buyer_id,''),
            'source':[shipment.source_x,shipment.source_y],'target':[shipment.target_x,shipment.target_y],'distanceKm':shipment.distance_km,
            'route':shipment.route,'legs':legs_json(shipment.legs),'transport':shipment.transport or 'sea','health':shipment.health,'sellerFlag':url_for('static',filename='flags/'+names.get(shipment.seller_id,'').replace(' ','_')+'.jpg'),'sunk':shipment.sunk_at is not None,'originCountryId':shipment.origin_country_id or shipment.seller_id,
            'flag':url_for('static',filename='flags/'+names.get(shipment.origin_country_id or shipment.seller_id,'').replace(' ','_')+'.jpg'),
            'startsAt':shipment.starts_at.isoformat()+'Z','arrivesAt':shipment.arrives_at.isoformat()+'Z','delivered':shipment.delivered_at is not None,'deliveredAt':shipment.delivered_at.isoformat()+'Z' if shipment.delivered_at else None,'own':own_shipment}
        if own_shipment:item.update({'cargo':shipment.cargo,'departureFee':str(shipment.departure_fee),'arrivalFee':str(shipment.arrival_fee)})
        if not item['legs']:item['legs']=None
        shipments.append(item)
    policy=db.session.get(PortTariff,country_id)
    account=db.session.get(StateFinancialAccount,country_id)
    return {'warehouse':trade_warehouse(db.session,country_id),'alliedCountryIds':allied_country_ids(db.session,country_id),'reserve':str(account.reserve_balance if account else 0),'offers':offers,'shipments':shipments,
        'ports':{str(city.miasto_id):{'name':city.miasto_nazwa,'countryId':controller_id(db.session,city.panstwo_id),'country':names.get(city.panstwo_id,''),'position':city_point(city.miasto_id),
            'rate':str(tariffs.get(controller_id(db.session,city.panstwo_id),0)),'allowed':(controller_id(db.session,city.panstwo_id)==country_id) if senders is None else (controller_id(db.session,city.panstwo_id) in senders and port_allows(db.session,city.panstwo_id,country_id)),   # 18 Nov 2026: odbiór też tylko przez port najbliższego sąsiada
            'blocked':not port_allows(db.session,city.panstwo_id,country_id),
            'departureAllowed':(controller_id(db.session,city.panstwo_id)==country_id) if senders is None else (controller_id(db.session,city.panstwo_id) in senders and port_allows(db.session,city.panstwo_id,country_id))} for city in all_ports},
        'portAccess':{'block_foreign':bool(policy.block_foreign) if policy else False,'blocked_countries':policy.blocked_countries or [] if policy else []},
        'airports':{str(a.miasto_id):{'name':a.name,'position':[a.map_x,a.map_y],'own':a.panstwo_id in own_ids,'country':names.get(a.panstwo_id,'')} for a in working},
        'ownAirports':[str(a.miasto_id) for a in own_airports],'airSpeed':AIR_SPEED,'railSpeed':RAIL_SPEED,
        'customs':str(customs_rates(db.session).get(country_id,0)),
        'ownPorts':own,'ownTariff':str(tariffs.get(country_id,0)),'countries':{str(id):name for id,name in names.items() if controller_id(db.session,id)==id},
        'gameNow':game_now().isoformat()+'Z','timeMultiplier':get_time_multiplier()}


@trade_bp.get('')
def page():
    user,country=player()
    if user is None:return redirect(url_for('wejscie'))
    country_id=country.PANSTWO_ID;session.setdefault('game_csrf_token',secrets.token_urlsafe(32))
    settle_own(country_id);config=trade_state(country_id)
    config.update({'countryId':country_id,'csrf':session['game_csrf_token'],'changeUrl':url_for('game_trade.change'),'stateUrl':url_for('game_trade.state'),
        'resources':goods_catalog(),'resourceOrder':goods_order(),'priceLimits':__import__('game.trade_prices',fromlist=['all_limits']).all_limits(goods_catalog().keys()),'regionsUrl':url_for('static',filename='maps/entenda_regiony.geojson'),
        'shipIcon':url_for('static',filename='icons/CARGO SHIP.svg'),'shipSpeed':SHIP_SPEED,'airIcon':url_for('static',filename='icons/SAMOLOT.svg'),'landIcon':url_for('static',filename='icons/TRANSPORT LĄDOWY.svg'),'landSpeed':__import__('game.trade_service',fromlist=['LAND_SPEED']).LAND_SPEED,'kmPerUnit':calibration(db.session).km_per_unit})
    # 22 Nov 2026: miasta i tory kolejowe na mapie handlu; wybór drogi dostawy przy zakupie
    from game.rail import world_lines
    config.update({'citiesUrl':url_for('static',filename='maps/entenda_miasta.geojson'),'deliveryUrl':url_for('game_trade.delivery'),
                   'packageIcon':url_for('static',filename='icons/PACZKA.svg'),
                   'rails':[{'path':line['path'],'name':f"{line['cityAName']} – {line['cityBName']}"} for line in world_lines(db.session) if line['completed']]})
    from game import warehouse   # 22 Nov 2026: magazyn — ikona na mapie handlu i zmiana lokalizacji
    config['warehouseMarker']=warehouse.marker(db.session,country_id)   # 'warehouse' w trade_state = stan towarów magazynu
    warehouse_modal=warehouse.modal_config(db.session,country_id,warehouse.required(db.session,country_id))
    response=render_template('game/trade.html',game_user=user,game_country=country_summary(country),game_active_page='trade',game_home_url=url_for('game_main_page'),game_logout_url=url_for('game_logout'),trade_config=config,warehouse_modal=warehouse_modal)
    db.session.commit();return response


@trade_bp.get('/stan')
def state():
    user,country=player()
    if user is None:return jsonify(error='Zaloguj się ponownie.'),401
    country_id=country.PANSTWO_ID;settle_own(country_id);response=jsonify(trade_state(country_id));db.session.commit();response.headers['Cache-Control']='no-store';return response


@trade_bp.get('/dostawa')
def delivery():
    """22 Nov 2026: dostępne drogi dostawy oferty do magazynu kupującego (kolej / morze / powietrze) z kosztami."""
    user,country=player()
    if user is None:return jsonify(error='Zaloguj się ponownie.'),401
    from game.trade_routes import delivery_options
    try:offer_id=int(request.args.get('offer_id',''))
    except ValueError:return jsonify(error='Nieprawidłowa oferta.'),400
    offer=db.session.get(TradeOffer,offer_id)
    if offer is None or offer.status!='open' or country.PANSTWO_ID in (offer.excluded or []) or offer.panstwo_id==country.PANSTWO_ID:return jsonify(error='Oferta nie jest dostępna.'),404
    options=delivery_options(db.session,offer,country.PANSTWO_ID)
    db.session.rollback()
    response=jsonify(offerId=offer_id,options=options);response.headers['Cache-Control']='no-store';return response


@trade_bp.post('/zmien')
def change():
    user,country=player()
    if user is None:return jsonify(error='Zaloguj się ponownie.'),401
    if not csrf_valid():return jsonify(error='Sesja formularza wygasła. Odśwież stronę.'),403
    data=request.get_json(silent=True)
    if not isinstance(data,dict):return jsonify(error='Nieprawidłowe dane formularza.'),400
    from game.trade_routes import set_customs   # 22 Nov 2026: cło lądowe
    functions={'offer':create_offer,'buy':buy_offer,'cancel':cancel_offer,'reprice':reprice_offer,'tariff':set_tariff,'port_access':set_port_access,'customs':set_customs}
    action=data.get('action')
    if not isinstance(action,str) or action not in functions:return jsonify(error='Nieprawidłowa operacja.'),400
    try:result=functions[action](user.id,data)
    except FinanceError as exc:return jsonify(error=str(exc)),400
    return jsonify(ok=True,id=result)


@trade_bp.get('/wydobycie/stan')
def mine_state():
    user,country=player()
    if user is None:return jsonify(error='Zaloguj się ponownie.'),401
    country_id=country.PANSTWO_ID;settle_own(country_id);response=jsonify(mining_state(country_id));db.session.commit();response.headers['Cache-Control']='no-store';return response


@trade_bp.post('/wydobycie/buduj')
def mining_build():
    user,country=player()
    if user is None:return jsonify(error='Zaloguj się ponownie.'),401
    if not csrf_valid():return jsonify(error='Sesja formularza wygasła. Odśwież stronę.'),403
    data=request.get_json(silent=True)
    if not isinstance(data,dict):return jsonify(error='Nieprawidłowe dane formularza.'),400
    try:id=build_mine(user.id,data)
    except FinanceError as exc:return jsonify(error=str(exc)),400
    return jsonify(ok=True,id=id)
