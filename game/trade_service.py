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
LAND_SPEED=150   # 18 Nov 2026: transport lądowy między stolicami państw sąsiadujących (km/h Entendy)
AIR_SPEED=1000   # 20 Nov 2026: samolot towarowy między lotniskami sprzedającego i kupującego (km/h Entendy)
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


def country_graph(session):
    """Sąsiedztwo państw (suwerennych właścicieli) po granicach regionów; jak road_projects.neighboring_countries
    — granice liczone od terytorium metropolitalnego państwa."""
    from models import Region
    from game.military_geography import region_adjacency
    rows=list(session.execute(select(Region.region_id,Region.panstwo_id,Region.terytorium_zamorskie)))
    roots={};root=lambda owner:roots.setdefault(owner,controller_id(session,owner) if owner is not None else None)
    owners={id:root(owner) for id,owner,_ in rows}
    graph={}
    adjacency=region_adjacency()
    for id,owner,overseas in rows:
        if overseas or owners[id] is None:continue
        for neighbor in adjacency.get(id,()):
            other=owners.get(neighbor)
            if other is not None and other!=owners[id]:graph.setdefault(owners[id],set()).add(other)
    return graph


def departure_countries(session,country_id,all_ports=None):
    """18 Nov 2026: państwa, z których portów `country_id` może wysłać ładunek. Państwo z własnym portem — tylko własne
    porty (None oznacza ten przypadek). Bez portu — porty najbliższych sąsiadów: najpierw bezpośrednich, a gdy żaden
    sąsiad nie ma dostępnego portu, sąsiadów sąsiadów (i dalej, kolejnymi pierścieniami). Gdy żadne państwo osiągalne lądem nie ma dostępnego portu
    (np. wyspa bez portu), obowiązuje dotychczasowa reguła — dowolny dostępny port."""
    all_ports=ports(session) if all_ports is None else all_ports
    owners={}
    for port in all_ports:
        owner=controller_id(session,port.panstwo_id)
        if owner is not None:owners.setdefault(owner,port.panstwo_id)
    if country_id in owners:return None
    usable={owner for owner,raw in owners.items() if port_allows(session,raw,country_id)}
    graph=country_graph(session);seen={country_id};frontier={country_id}
    while frontier:
        frontier={other for country in frontier for other in graph.get(country,())}-seen
        seen|=frontier
        found=frontier&usable
        if found:return found
    return usable   # żadne osiągalne lądem państwo nie ma dostępnego portu (np. wyspa) — dowolny dostępny port


def choose_port(session,country_id,port_id,departure=True):
    from game.military_service import natural
    port_id=natural(port_id,'Miasto portowe',1);all_ports=ports(session)
    own=any(controller_id(session,port.panstwo_id)==country_id for port in all_ports)
    port=next((port for port in all_ports if port.miasto_id==port_id),None)
    if port is None or controller_id(session,port.panstwo_id) is None:raise FinanceError('Wybierz działające miasto portowe na mapie.')
    if own and controller_id(session,port.panstwo_id)!=country_id:raise FinanceError('Państwo posiada własny port. Wybierz port własnego kraju.')
    if not port_allows(session,port.panstwo_id,country_id):raise FinanceError('Właściciel portu zablokował tranzyt dla tego państwa.')
    # 18 Nov 2026: reguła najbliższego sąsiada obowiązuje przy wysyłce i (od zgłoszenia Elgia → Izziko) przy odbiorze.
    if departure and not own and controller_id(session,port.panstwo_id) not in departure_countries(session,country_id,all_ports):
        raise FinanceError('Państwo bez własnego portu może wysyłać i odbierać ładunki tylko przez port najbliższego sąsiada (lub sąsiada sąsiada, gdy żaden sąsiad nie ma portu).')
    return port


def capital_city(session,country_id):
    """Stolica państwa na mapie (miasto typu 1); bez niej — największe miasto państwa na mapie."""
    rows=session.execute(select(Miasto.miasto_id,Miasto.miasto_typ_id,Miasto.miasto_populacja).where(Miasto.panstwo_id==country_id,Miasto.czy_na_mapie=='TAK')
                         .order_by((Miasto.miasto_typ_id==1).desc(),Miasto.miasto_populacja.desc(),Miasto.miasto_id)).all()
    return next((row.miasto_id for row in rows if city_point(row.miasto_id) is not None),None)


def land_neighbors(session,a,b):
    from game.road_projects import neighboring_countries
    return b in neighboring_countries(session,a) or a in neighboring_countries(session,b)


def land_route(session,seller_id,buyer_id,neighbors=None):
    """18 Nov 2026: zakup od państwa z granicą lądową — transport lądowy między stolicami (None: transport morski)."""
    seller,buyer=controller_id(session,seller_id),controller_id(session,buyer_id)
    if seller is None or buyer is None or seller==buyer:return None
    if not (buyer in neighbors if neighbors is not None else land_neighbors(session,seller,buyer)):return None
    source,target=capital_city(session,seller),capital_city(session,buyer)
    if source is None or target is None:return None
    from game.military_flights import calibration
    route=[list(city_point(source)),list(city_point(target))]
    return {'source':source,'target':target,'route':route,'distance':path_length(route)*calibration(session).km_per_unit}


def own_airport(session,country_id,city_id,label='Lotnisko'):
    """20 Nov 2026: czynne lotnisko państwa w mieście city_id — port handlu lotniczego (bez opłat portowych)."""
    from game.military_service import natural
    from game.airports import own_operational
    city_id=natural(city_id,label,1)
    airport=next((a for a in own_operational(session,country_id) if a.miasto_id==city_id),None)
    if airport is None:raise FinanceError(f'{label}: wybierz czynny port lotniczy własnego państwa.')
    return airport


def transport_mode(data):
    mode=data.get('transport','sea') or 'sea'
    if mode not in ('sea','air'):raise FinanceError('Nieprawidłowy rodzaj transportu.')
    return mode


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
    """22 Nov 2026: oferta bez wyboru transportu i portu — towar czeka w magazynie sprzedającego (game.warehouse);
    drogę dostawy wybiera kupujący przy zakupie (game.trade_routes)."""
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
            if (existing.cargo,existing.price,existing.excluded)!=(cargo,price,excluded):raise FinanceConflict('Identyfikator żądania został już wykorzystany.')
            return existing.id
        if len(list(session.scalars(select(Panstwo.PANSTWO_ID).where(Panstwo.PANSTWO_ID.in_(excluded)))))!=len(excluded):raise FinanceError('Nieprawidłowe wykluczone państwo.')
        from game.warehouse import warehouse_city
        origin=warehouse_city(session,country_id)
        if origin is None:raise FinanceError('Państwo nie ma na mapie miasta, w którym mógłby znajdować się magazyn.')
        from game.research_service import settle_production
        settle_production(session,country_id,game_now())
        for code,quantity in sorted(cargo.items()):
            change_goods(session,country_id,code,-quantity)
        offer=TradeOffer(panstwo_id=country_id,user_id=user_id,cargo=cargo,price=price,excluded=excluded,port_id=origin,port_country_id=country_id,departure_rate=Decimal(0),request_id=key,status='open',
                         created_game_at=game_now(),transport='sea')   # port_id = miasto magazynu; transport wybiera kupujący
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
    """22 Nov 2026: kupujący wybiera drogę dostawy (`delivery` = klucz opcji z game.trade_routes.delivery_options; PAGA2
    może podać 'auto' — najtańsza opcja). Płaci cenę, opłatę portu odbioru, cła tranzytowe i opłatę MFW; sprzedający
    płaci opłatę portu wysyłki."""
    from game.military_service import natural
    from game import trade_routes
    key=request_key(data.get('request_id'));offer_id=natural(data.get('offer_id'),'Oferta',1)
    choice=data.get('delivery')
    with Session(db.engine) as session,session.begin():
        country=_country_for_user(session,user_id);buyer_id=country.PANSTWO_ID
        existing=session.scalar(select(TradeShipment).where(TradeShipment.buyer_id==buyer_id,TradeShipment.request_id==key).with_for_update())
        if existing:
            if existing.offer_id!=offer_id:raise FinanceConflict('Identyfikator żądania został już wykorzystany.')
            return existing.id
        preview=session.get(TradeOffer,offer_id)
        if preview is None:raise FinanceError('Oferta nie jest dostępna.')
        expires=offer_expires_at(preview)
        if preview.status=='open' and expires is not None and expires<=game_now():raise FinanceError('Oferta wygasła po 14 dniach Entendy i nie jest już dostępna.')
        if preview.status!='open' or buyer_id in preview.excluded or preview.panstwo_id==buyer_id:raise FinanceError('Oferta nie jest dostępna dla tego państwa.')
        if not isinstance(choice,str) or not choice or len(choice)>200:raise FinanceError('Wybierz sposób dostawy.')
        options=trade_routes.delivery_options(session,preview,buyer_id)
        if not options:raise FinanceError('Brak dostępnej drogi dostawy z magazynu sprzedającego do Twojego magazynu (kolej, port lub lotnisko).')
        option=options[0] if choice=='auto' else next((o for o in options if o['key']==choice),None)
        if option is None:raise FinanceConflict('Wybrana droga dostawy nie jest już dostępna. Odśwież ofertę przed zakupem.')
        if choice!='auto' and data.get('expected_total') is not None and money(data.get('expected_total'))!=Decimal(option['total']):
            raise FinanceConflict('Koszt dostawy zmienił się. Odśwież ofertę przed zakupem.')
        port_owner=lambda city_id:controller_id(session,session.scalar(select(Miasto.panstwo_id).where(Miasto.miasto_id==city_id))) if city_id else None
        departure_owner,arrival_owner=port_owner(option.get('departurePortId')),port_owner(option.get('arrivalPortId'))
        customs={int(t['countryId']):Decimal(t['amount']) for t in option['transit']}
        involved=sorted({buyer_id,controller_id(session,preview.panstwo_id),*customs,*(x for x in (departure_owner,arrival_owner) if x is not None)})
        list(session.scalars(select(Panstwo.PANSTWO_ID).where(Panstwo.PANSTWO_ID.in_(involved)).order_by(Panstwo.PANSTWO_ID).with_for_update()))
        existing=session.scalar(select(TradeShipment).where(TradeShipment.buyer_id==buyer_id,TradeShipment.request_id==key).with_for_update())
        if existing:
            if existing.offer_id!=offer_id:raise FinanceConflict('Identyfikator żądania został już wykorzystany.')
            return existing.id
        offer=session.scalar(select(TradeOffer).where(TradeOffer.id==offer_id).with_for_update().execution_options(populate_existing=True))
        if offer.status!='open' or buyer_id in offer.excluded or offer.panstwo_id==buyer_id:raise FinanceError('Oferta nie jest dostępna dla tego państwa.')
        if AMMUNITION in offer.cargo and not ammunition_allowed(session,offer.panstwo_id,buyer_id,lock=True):raise FinanceError('Relacje lub stan dyplomatyczny państw nie pozwalają na handel amunicją przeciwrakietową.')
        from game.research_service import settle_production
        for id in sorted((buyer_id,offer.panstwo_id)):settle_production(session,id,game_now())
        price=offer.price;departure_fee=Decimal(option['departureFee']);arrival_fee=Decimal(option['arrivalFee']);imf_fee=Decimal(option['imfFee'])
        total=price+arrival_fee+imf_fee+sum(customs.values(),Decimal(0))
        accounts={id:account_for(session,id) for id in involved}
        if accounts[buyer_id].reserve_balance<total:raise FinanceError('Za mało środków w rezerwie na zakup, opłaty i cła.')
        now=game_now();legs,arrives=trade_routes.schedule(option['legs'],now)
        route=[]
        for leg in legs:
            for point in leg['path']:
                if not route or list(point)!=list(route[-1]):route.append(list(point))
        if len(route)<2:raise FinanceError('Nie udało się wyznaczyć trasy dostawy.')
        mode=option['mode'];seller_id=offer.panstwo_id
        departure_city=option.get('departurePortId') or option.get('departureAirportCityId') or option['departureCityId']
        arrival_city=option.get('arrivalPortId') or option.get('arrivalAirportCityId') or option['arrivalCityId']
        shipment=TradeShipment(offer_id=offer.id,seller_id=seller_id,buyer_id=buyer_id,cargo=offer.cargo,departure_port_id=departure_city,arrival_port_id=arrival_city,
            route=route,legs=legs,origin_country_id=departure_owner if mode=='sea' and departure_owner else seller_id,transport=mode,health=100,departure_fee=departure_fee,arrival_fee=arrival_fee,
            source_x=route[0][0],source_y=route[0][1],target_x=route[-1][0],target_y=route[-1][1],distance_km=sum(leg['km'] for leg in legs),
            starts_at=now,arrives_at=arrives,request_id=key)
        session.add(shipment);offer.status='sold';session.flush()
        changes={id:Decimal(0) for id in involved}
        changes[buyer_id]-=total;changes[controller_id(session,seller_id)]+=price-departure_fee
        if departure_owner is not None:changes[departure_owner]+=departure_fee
        if arrival_owner is not None:changes[arrival_owner]+=arrival_fee
        for id,amount in customs.items():changes[id]+=amount
        for id,amount in changes.items():
            if not amount:continue
            account=accounts[id];account.reserve_balance=money(account.reserve_balance+amount,'Saldo rezerwy');account.updated_at=utc_now()
            session.add(TradeReserveMovement(panstwo_id=id,budget_id=account.last_budget_id,shipment_id=shipment.id,amount=amount))
        session.add(trade_routes.ImfShippingFee(shipment_id=shipment.id,buyer_id=buyer_id,seller_id=seller_id,transport=mode,rate=Decimal(option['imfRate']),amount=imf_fee))
        from game.forum_models import GameNotification
        names={**dict(RESOURCES),**{code:label for code,(label,_) in GOODS.items()}};names[AMMUNITION]=AMMUNITION_LABEL
        goods=', '.join(f"{quantity} {names[code]}" for code,quantity in sorted(offer.cargo.items()))
        def roi(value):return format(value,',.2f').replace(',',' ').replace('.',',')+' ROI'
        buyer_name=session.scalar(select(Panstwo.panstwo_nazwa).where(Panstwo.PANSTWO_ID==buyer_id))
        message=f"{buyer_name} zakupił/a {goods} za {roi(offer.price)}. Dostawa: {trade_routes.MODE_LABELS[mode].lower()}. Opłata portu wysyłki: {roi(departure_fee)}."
        session.add(GameNotification(user_id=offer.user_id,notification_type='SYSTEM',system_text=message,created_at=utc_now()))
        for id,amount in customs.items():
            from game.paga_ai_actor import country_user_id
            user=country_user_id(session,id)
            if user is not None and amount:session.add(GameNotification(user_id=user,notification_type='SYSTEM',created_at=utc_now(),
                system_text=f'Cło lądowe: {roi(amount)} za przejazd pociągu z towarem ({goods}) przez nasze terytorium — wpłynęło do rezerwy budżetowej.'))
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
