"""Oferty z depozytem towarów, opłaty portowe i dostawa po rejsie."""
from game.sea_routes import shortest_sea_route,path_length
from game.governance import controller_id
from datetime import timedelta
from decimal import Decimal,ROUND_HALF_UP
from sqlalchemy import select,func
from sqlalchemy.orm import Session,lazyload
from extensions import db
from models import Panstwo,Miasto
from services.natural_resources import RESOURCES
from game.finance_service import FinanceError,FinanceConflict,_country_for_user,game_now,money,percentage,utc_now
from game.finance_models import StateFinancialAccount
from game.budget_transfers import precise
from game.mining_service import request_key
from game.military_geography import city_point
from game.military_flights import distance_km
from game.commerce_models import TradeOffer,TradeShipment,PortTariff,TradeReserveMovement
from game.trade_goods import AMMUNITION,AMMUNITION_LABEL,change_goods
from game.trade_diplomacy import allied,ammunition_allowed

SHIP_SPEED=100
from game.industry_catalog import GOODS
CODES={code for code,_ in RESOURCES}|{AMMUNITION}|set(GOODS)


def ports(session):
    return [city for city in session.scalars(select(Miasto).options(lazyload('*')).where(Miasto.czy_portowe=='TAK',Miasto.czy_na_mapie=='TAK',Miasto.panstwo_id.is_not(None)).order_by(Miasto.miasto_id)) if city_point(city.miasto_id) is not None]


def port_allows(session, owner, country_id, *, lock=False):
    owner=controller_id(session,owner)
    if owner is None:return False
    if owner==country_id or allied(session,owner,country_id,lock=lock):return True
    query=select(PortTariff).where(PortTariff.panstwo_id==owner).execution_options(populate_existing=True)
    if lock:query=query.with_for_update()
    policy=session.scalar(query)
    return policy is None or (not policy.block_foreign and country_id not in (policy.blocked_countries or []))


def set_port_access(user_id,data):
    from game.military_service import natural
    blocked=data.get('blocked_countries',[])
    if type(data.get('block_foreign')) is not bool or not isinstance(blocked,list) or len(blocked)>1000:raise FinanceError('Nieprawidłowe ustawienia dostępu portów.')
    blocked=sorted({natural(id,'Państwo',1) for id in blocked})
    with Session(db.engine) as session,session.begin():
        country=_country_for_user(session,user_id,lock=True)
        if not any(controller_id(session,port.panstwo_id)==country.PANSTWO_ID for port in ports(session)):raise FinanceError('Państwo nie posiada portu na mapie.')
        if any(id==country.PANSTWO_ID or controller_id(session,id)!=id for id in blocked):raise FinanceError('Wybierz inne suwerenne państwa.')
        if any(allied(session,country.PANSTWO_ID,id,lock=True) for id in blocked):raise FinanceError('Nie można blokować tranzytu dla państw w relacji sojuszniczej, partnerskiej lub partnerskiej strategicznej.')
        policy=session.scalar(select(PortTariff).where(PortTariff.panstwo_id==country.PANSTWO_ID).with_for_update())
        if policy is None:policy=PortTariff(panstwo_id=country.PANSTWO_ID,rate=0);session.add(policy)
        policy.block_foreign=data['block_foreign'];policy.blocked_countries=blocked


def choose_port(session,country_id,port_id):
    from game.military_service import natural
    port_id=natural(port_id,'Miasto portowe',1);all_ports=ports(session)
    own=any(controller_id(session,port.panstwo_id)==country_id for port in all_ports)
    port=next((port for port in all_ports if port.miasto_id==port_id),None)
    if port is None or controller_id(session,port.panstwo_id) is None:raise FinanceError('Wybierz działające miasto portowe na mapie.')
    if own and controller_id(session,port.panstwo_id)!=country_id:raise FinanceError('Państwo posiada własny port. Wybierz port własnego kraju.')
    if not port_allows(session,port.panstwo_id,country_id):raise FinanceError('Właściciel portu zablokował tranzyt dla tego państwa.')
    return port


def tariff(session,owner,country_id):
    owner=controller_id(session,owner)
    return Decimal(0) if owner==country_id else session.scalar(select(PortTariff.rate).where(PortTariff.panstwo_id==owner).with_for_update()) or Decimal(0)


def fee(price,rate):return (price*rate/100).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)


def reserve_delta(session,country_id,budget_id):
    condition=TradeReserveMovement.budget_id.is_(None) if budget_id is None else TradeReserveMovement.budget_id==budget_id
    return session.scalar(select(func.coalesce(func.sum(TradeReserveMovement.amount),0)).where(TradeReserveMovement.panstwo_id==country_id,condition)) or Decimal(0)


def account_for(session,country_id):
    account=session.scalar(select(StateFinancialAccount).where(StateFinancialAccount.panstwo_id==country_id).with_for_update())
    if account is None:
        now=utc_now();account=StateFinancialAccount(panstwo_id=country_id,reserve_balance=0,last_transaction_sequence=0,created_at=now,updated_at=now)
        session.add(account);session.flush()
    return account


@precise
def create_offer(user_id,data):
    from game.military_service import natural
    key=request_key(data.get('request_id'));price=money(data.get('price'))
    if price<=0:raise FinanceError('Łączna cena oferty musi być dodatnia.')
    cargo=data.get('cargo');excluded=data.get('excluded',[])
    if not isinstance(cargo,dict) or not cargo or set(cargo)-CODES:raise FinanceError('Wybierz towary z magazynu.')
    cargo={code:natural(value,'Ilość towaru') for code,value in cargo.items()}
    cargo={code:quantity for code,quantity in cargo.items() if quantity>0}
    if not cargo:raise FinanceError('Oferta musi obejmować co najmniej jedną jednostkę towaru.')
    # 12 Nov 2026: jeden rodzaj towaru na ofertę i cena jednostki w granicach (game/trade_prices).
    from game import trade_prices
    problem=trade_prices.check_offer(cargo,price)
    if problem:raise FinanceError(problem)
    if not isinstance(excluded,list) or len(excluded)>1000:raise FinanceError('Nieprawidłowa lista wykluczonych państw.')
    excluded=sorted({natural(id,'Państwo',1) for id in excluded})
    with Session(db.engine) as session,session.begin():
        country=_country_for_user(session,user_id,lock=False);country_id=country.PANSTWO_ID
        if AMMUNITION in cargo:
            from game.research_service import settle_production
            settle_production(session,country_id,game_now())
        country=_country_for_user(session,user_id,lock=True)
        if any(controller_id(session,id) is None for id in excluded):raise FinanceError('Nieprawidłowe wykluczone państwo.')
        excluded=sorted({controller_id(session,id) for id in excluded})
        existing=session.scalar(select(TradeOffer).where(TradeOffer.panstwo_id==country_id,TradeOffer.request_id==key).with_for_update())
        if existing:
            if (existing.cargo,existing.price,existing.excluded,existing.port_id)!=(cargo,price,excluded,data.get('port_id')):raise FinanceConflict('Identyfikator żądania został już wykorzystany.')
            return existing.id
        if len(list(session.scalars(select(Panstwo.PANSTWO_ID).where(Panstwo.PANSTWO_ID.in_(excluded)))))!=len(excluded):raise FinanceError('Nieprawidłowe wykluczone państwo.')
        port=choose_port(session,country_id,data.get('port_id'))
        # Port infrastructure of the departure port's region limits the size of an export offer (10 Nov 2026).
        from game.infrastructure_effects import port_export_limit
        from models import Region as PortRegion
        port_region=session.get(PortRegion,port.region_id)
        limit,only=port_export_limit(port_region.region_stan_infra_portowej if port_region is not None else 0)
        if only is not None and set(cargo)-{only}:
            raise FinanceError('Infrastruktura portowa tego regionu jest poniżej 10: z tego portu można eksportować wyłącznie węgiel kamienny (najwyżej 100 sztuk).')
        if limit is not None and sum(cargo.values())>limit:
            raise FinanceError(f'Infrastruktura portowa regionu pozwala wystawić w tym porcie ofertę najwyżej na {limit} sztuk towarów.')
        departure_rate=tariff(session,port.panstwo_id,country_id)
        if departure_rate!=percentage(data.get('departure_rate'),'Opłata portu wysyłki'):raise FinanceConflict('Opłata portu wysyłki zmieniła się. Odśwież formularz.')
        from game.research_service import settle_production
        settle_production(session,country_id,game_now())
        for code,quantity in sorted(cargo.items()):
            change_goods(session,country_id,code,-quantity)
        offer=TradeOffer(panstwo_id=country_id,user_id=user_id,cargo=cargo,price=price,excluded=excluded,port_id=port.miasto_id,port_country_id=controller_id(session,port.panstwo_id),departure_rate=departure_rate,request_id=key,status='open',
                         created_game_at=game_now())
        session.add(offer);session.flush();return offer.id


def cancel_offer(user_id,data):
    from game.military_service import natural
    with Session(db.engine) as session,session.begin():
        country=_country_for_user(session,user_id,lock=True)
        offer=session.scalar(select(TradeOffer).where(TradeOffer.id==natural(data.get('offer_id'),'Oferta',1),TradeOffer.panstwo_id==country.PANSTWO_ID).with_for_update())
        if offer is None:raise FinanceError('Oferta nie należy do gracza.')
        if offer.status=='cancelled':return
        if offer.status!='open':raise FinanceConflict('Oferta została już zakupiona.')
        from game.research_service import settle_production
        settle_production(session,country.PANSTWO_ID,game_now())
        for code,quantity in sorted(offer.cargo.items()):change_goods(session,country.PANSTWO_ID,code,quantity)
        offer.status='cancelled'


# 13 Nov 2026: oferta niesprzedana przez 14 dni Entendy jest wycofywana (towar wraca do magazynu, sprzedający dostaje powiadomienie).
OFFER_LIFETIME_DAYS=14


def offer_expires_at(offer):
    from datetime import timedelta
    return offer.created_game_at+timedelta(days=OFFER_LIFETIME_DAYS) if offer.created_game_at else None


def expire_offers(session,now=None):
    """Wycofuje wszystkie otwarte oferty starsze niż 14 dni Entendy. Zwraca liczbę wycofanych ofert."""
    from datetime import timedelta
    from game.paga_ai_actor import country_user_id
    from game.forum_models import GameNotification
    from game.models import utc_now
    moment=now or game_now();limit=moment-timedelta(days=OFFER_LIFETIME_DAYS)
    expired=list(session.scalars(select(TradeOffer).where(TradeOffer.status=='open',TradeOffer.created_game_at.is_not(None),TradeOffer.created_game_at<=limit).order_by(TradeOffer.id).with_for_update()))
    if not expired:return 0
    from game.mining_service import RESOURCES as RAW
    from game.industry_catalog import GOODS
    names={**{code:label for code,label in RAW},**{code:value[0] for code,value in GOODS.items()},
           'tanks':'Czołgi','armored':'Wozy opancerzone','fighters':'Myśliwce','drones':'Drony','warships':'Okręty wojenne','submarines':'Okręty podwodne','carriers':'Lotniskowce'}
    settled=set()
    for offer in expired:
        if offer.panstwo_id not in settled and AMMUNITION in offer.cargo:
            from game.research_service import settle_production
            settle_production(session,offer.panstwo_id,moment);settled.add(offer.panstwo_id)
        for code,quantity in sorted(offer.cargo.items()):change_goods(session,offer.panstwo_id,code,quantity)
        offer.status='cancelled'
        owner=country_user_id(session,offer.panstwo_id)
        if owner is not None:
            goods=', '.join(f'{quantity} × {names.get(code,code)}' for code,quantity in offer.cargo.items())
            session.add(GameNotification(user_id=owner,notification_type='SYSTEM',created_at=utc_now(),
                system_text=f'Oferta handlowa #{offer.id} ({goods}) nie znalazła kupca przez {OFFER_LIFETIME_DAYS} dni Entendy i została wycofana. Towar wrócił do magazynu.'))
    session.flush()
    return len(expired)


def reprice_offer(user_id,data):
    """Obniżenie ceny własnej, otwartej oferty (w granicach cen gry); termin wycofania liczony od wystawienia."""
    from game.military_service import natural
    from game import trade_prices
    price=money(data.get('price'))
    with Session(db.engine) as session,session.begin():
        country=_country_for_user(session,user_id,lock=True)
        offer=session.scalar(select(TradeOffer).where(TradeOffer.id==natural(data.get('offer_id'),'Oferta',1),TradeOffer.panstwo_id==country.PANSTWO_ID).with_for_update())
        if offer is None:raise FinanceError('Oferta nie należy do gracza.')
        if offer.status!='open':raise FinanceConflict('Oferta nie jest już otwarta.')
        if price>=offer.price:raise FinanceError('Nowa cena musi być niższa od obecnej.')
        problem=trade_prices.check_offer(offer.cargo,price)
        if problem:raise FinanceError(problem)
        offer.price=price;offer.price_changed_game_at=game_now()
        return offer.id


def set_tariff(user_id,data):
    rate=percentage(data.get('rate'),'Opłata portowa')
    with Session(db.engine) as session,session.begin():
        country=_country_for_user(session,user_id,lock=True)
        if not any(controller_id(session,port.panstwo_id)==country.PANSTWO_ID for port in ports(session)):raise FinanceError('Państwo nie posiada miasta portowego na mapie.')
        setting=session.get(PortTariff,country.PANSTWO_ID)
        if setting is None:setting=PortTariff(panstwo_id=country.PANSTWO_ID);session.add(setting)
        setting.rate=rate


@precise
def buy_offer(user_id,data):
    from game.military_service import natural
    key=request_key(data.get('request_id'));offer_id=natural(data.get('offer_id'),'Oferta',1)
    with Session(db.engine) as session,session.begin():
        country=_country_for_user(session,user_id);buyer_id=country.PANSTWO_ID
        existing=session.scalar(select(TradeShipment).where(TradeShipment.buyer_id==buyer_id,TradeShipment.request_id==key).with_for_update())
        if existing:
            if (existing.offer_id,existing.arrival_port_id)!=(offer_id,data.get('port_id')):raise FinanceConflict('Identyfikator żądania został już wykorzystany.')
            return existing.id
        preview=session.get(TradeOffer,offer_id)
        if preview is None:raise FinanceError('Oferta nie jest dostępna.')
        expires=offer_expires_at(preview)
        if preview.status=='open' and expires is not None and expires<=game_now():raise FinanceError('Oferta wygasła po 14 dniach Entendy i nie jest już dostępna.')
        arrival=choose_port(session,buyer_id,data.get('port_id'))
        involved=sorted({buyer_id,preview.panstwo_id,preview.port_country_id,controller_id(session,arrival.panstwo_id)})
        list(session.scalars(select(Panstwo.PANSTWO_ID).where(Panstwo.PANSTWO_ID.in_(involved)).order_by(Panstwo.PANSTWO_ID).with_for_update()))
        existing=session.scalar(select(TradeShipment).where(TradeShipment.buyer_id==buyer_id,TradeShipment.request_id==key).with_for_update())
        if existing:
            if (existing.offer_id,existing.arrival_port_id)!=(offer_id,arrival.miasto_id):raise FinanceConflict('Identyfikator żądania został już wykorzystany.')
            return existing.id
        offer=session.scalar(select(TradeOffer).where(TradeOffer.id==offer_id).with_for_update().execution_options(populate_existing=True))
        if offer.status!='open' or buyer_id in offer.excluded or offer.panstwo_id==buyer_id:raise FinanceError('Oferta nie jest dostępna dla tego państwa.')
        if AMMUNITION in offer.cargo and not ammunition_allowed(session,offer.panstwo_id,buyer_id,lock=True):raise FinanceError('Relacje lub stan dyplomatyczny państw nie pozwalają na handel amunicją przeciwrakietową.')
        departure=choose_port(session,offer.panstwo_id,offer.port_id)
        if controller_id(session,departure.panstwo_id)!=offer.port_country_id:raise FinanceConflict('Zmienił się właściciel portu wysyłki. Sprzedający musi odnowić ofertę.')
        for port,operator in ((departure,offer.panstwo_id),(arrival,buyer_id)):
            if not port_allows(session,port.panstwo_id,operator,lock=True):raise FinanceError('Port zablokował tranzyt dla państwa korzystającego z portu. Wybierz inną trasę lub ofertę.')
        current_rate=tariff(session,arrival.panstwo_id,buyer_id)
        expected=percentage(data.get('arrival_rate'),'Opłata portu odbioru')
        if current_rate!=expected:raise FinanceConflict('Opłata portu odbioru zmieniła się. Odśwież ofertę przed zakupem.')
        from game.research_service import settle_production
        for country in sorted((buyer_id,offer.panstwo_id)):settle_production(session,country,game_now())
        departure_fee=fee(offer.price,offer.departure_rate);arrival_fee=fee(offer.price,current_rate)
        accounts={id:account_for(session,id) for id in involved}
        if accounts[buyer_id].reserve_balance<offer.price+arrival_fee:raise FinanceError('Za mało środków w rezerwie na zakup i opłatę portu odbioru.')
        route=shortest_sea_route(city_point(departure.miasto_id),city_point(arrival.miasto_id));source,target=route[0],route[-1]
        from game.military_flights import calibration
        distance=path_length(route)*calibration(session).km_per_unit;now=game_now()
        shipment=TradeShipment(offer_id=offer.id,seller_id=offer.panstwo_id,buyer_id=buyer_id,cargo=offer.cargo,departure_port_id=departure.miasto_id,arrival_port_id=arrival.miasto_id,
            route=route,origin_country_id=departure.panstwo_id,health=100,departure_fee=departure_fee,arrival_fee=arrival_fee,source_x=source[0],source_y=source[1],target_x=target[0],target_y=target[1],distance_km=distance,
            starts_at=now,arrives_at=now+timedelta(seconds=max(1,distance/SHIP_SPEED*3600)),request_id=key)
        session.add(shipment);offer.status='sold';session.flush()
        changes={id:Decimal(0) for id in involved}
        changes[buyer_id]-=offer.price+arrival_fee;changes[offer.panstwo_id]+=offer.price-departure_fee
        changes[controller_id(session,departure.panstwo_id)]+=departure_fee;changes[controller_id(session,arrival.panstwo_id)]+=arrival_fee
        for id,amount in changes.items():
            if not amount:continue
            account=accounts[id];account.reserve_balance=money(account.reserve_balance+amount,'Saldo rezerwy');account.updated_at=utc_now()
            session.add(TradeReserveMovement(panstwo_id=id,budget_id=account.last_budget_id,shipment_id=shipment.id,amount=amount))
        from game.forum_models import GameNotification
        names={**dict(RESOURCES),**{code:label for code,(label,_) in GOODS.items()}};names[AMMUNITION]=AMMUNITION_LABEL
        goods=', '.join(f"{quantity} {names[code]}" for code,quantity in sorted(offer.cargo.items()))
        def roi(value):return format(value,',.2f').replace(',',' ').replace('.',',')+' ROI'
        buyer_name=session.scalar(select(Panstwo.panstwo_nazwa).where(Panstwo.PANSTWO_ID==buyer_id))
        message=f"{buyer_name} zakupił/a {goods} za {roi(offer.price)}. Cło portowe: {roi(departure_fee)}"
        session.add(GameNotification(user_id=offer.user_id,notification_type='SYSTEM',system_text=message,created_at=utc_now()))
        return shipment.id


def deliver_shipments(session,now,country_id=None):
    query=select(TradeShipment).where(TradeShipment.delivered_at.is_(None),TradeShipment.sunk_at.is_(None),TradeShipment.health>0,TradeShipment.arrives_at<=now)
    if country_id is not None:query=query.where(TradeShipment.buyer_id==country_id)
    rows=list(session.execute(query.with_only_columns(TradeShipment.id,TradeShipment.buyer_id)))
    if not rows:return
    from game.military_flights import complete_flights
    complete_flights(session,now,shipment_ids=[row.id for row in rows],lock_country_ids={row.buyer_id for row in rows})
    list(session.scalars(select(Panstwo.PANSTWO_ID).where(Panstwo.PANSTWO_ID.in_({row.buyer_id for row in rows})).order_by(Panstwo.PANSTWO_ID).with_for_update()))
    for shipment in session.scalars(query.where(TradeShipment.id.in_([row.id for row in rows])).order_by(TradeShipment.id).with_for_update().execution_options(populate_existing=True)):
        from game.industry_service import settle_industry
        settle_industry(session,shipment.buyer_id,shipment.arrives_at)
        for code,quantity in sorted(shipment.cargo.items()):change_goods(session,shipment.buyer_id,code,quantity)
        shipment.delivered_at=shipment.arrives_at
    session.flush()
