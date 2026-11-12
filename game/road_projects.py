from game.paga_ai_actor import country_user_id
"""Proporcjonalne współfinansowanie dróg, zgoda sąsiada i modernizacja."""
from decimal import Decimal,ROUND_HALF_UP
from math import hypot
from uuid import uuid5,NAMESPACE_URL
from sqlalchemy import select,or_
from sqlalchemy.orm import Session
from extensions import db
from models import Panstwo,Region
from game.civic_models import Road,RoadProposal,RoadInvestment
from game.finance_models import StateBudget
from game.finance_service import FinanceError,FinanceConflict,_country_for_user,game_now,period_key
from game.models import GameUser,GamePlayerCountry,utc_now
from game.forum_models import GameNotification
from game.governance import controller_id
from game.budget_transfers import precise,infrastructure_balance
from game.mining_service import request_key
from game.roads import quote_road,road_data,build_road,PRICES
from game.road_geometry import prepare_features,partition_path
from game.military_geography import MAP_PATH,region_adjacency
from game import roads as road_source


def neighboring_countries(session,country):
    rows=list(session.execute(select(Region.region_id,Region.panstwo_id,Region.terytorium_zamorskie)))
    by_id={id:owner for id,owner,_ in rows};own={id for id,owner,overseas in rows if owner==country and not overseas}
    graph=region_adjacency()
    return {root for id in own for neighbor in graph.get(id,()) if (root:=controller_id(session,by_id.get(neighbor))) not in (None,country)}


def features_for(session,country,lock=False):
    query=select(Region.region_id,Region.panstwo_id,Region.terytorium_zamorskie).order_by(Region.region_id)
    if lock:query=query.with_for_update()
    owners={id:controller_id(session,owner) for id,owner,overseas in session.execute(query) if owner!=country or not overseas}
    return prepare_features(road_source.map_features(MAP_PATH),{id:owner for id,owner in owners.items() if owner is not None})


def path_length(path):return sum(hypot(b[0]-a[0],b[1]-a[1]) for a,b in zip(path,path[1:]))


@precise
def network_quote(session,country,data,lock=False):
    quote=quote_road(session,country,data,admin=True,lock_regions=False)
    parts=partition_path(quote['path'],features_for(session,country,lock))
    if not parts or parts[0]['countryId']!=country:raise FinanceError('Początek drogi musi leżeć we własnym terytorium metropolitalnym.')
    owners={part['countryId'] for part in parts};foreign=owners-{country}
    if len(foreign)>1:raise FinanceError('Jedno zapytanie może obejmować własny kraj i jednego sąsiada. Podziel trasę na odcinki.')
    partner=next(iter(foreign),None)
    if partner is not None and (partner not in neighboring_countries(session,country) or parts[-1]['countryId']!=partner):raise FinanceError('Droga międzynarodowa musi kończyć się u bezpośredniego sąsiada.')
    total=(Decimal(quote['distanceKm'])*PRICES[quote['kind']]).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
    raw={owner:sum((Decimal(str(path_length(part['path']))) for part in parts if part['countryId']==owner),Decimal(0)) for owner in owners};length=sum(raw.values())
    shares={str(owner):{'countryId':owner,'cost':str((total*raw[owner]/length).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)),'distanceKm':str((Decimal(quote['distanceKm'])*raw[owner]/length).quantize(Decimal('.001'),rounding=ROUND_HALF_UP))} for owner in owners}
    shares[str(country)]['cost']=str(total-sum((Decimal(value['cost']) for key,value in shares.items() if int(key)!=country),Decimal(0)))
    return {**quote,'cost':str(total),'countryId':country,'partnerId':partner,'shares':shares,'parts':parts}


def notice(session,country,text):
    owner=country_user_id(session,country)
    if owner is not None:session.add(GameNotification(user_id=owner,notification_type='SYSTEM',system_text='Droga: '+text,created_at=utc_now()))


def current_budget(session,country,amount):
    year,period=period_key(game_now());budget=session.scalar(select(StateBudget).where(StateBudget.panstwo_id==country,StateBudget.game_year==year,StateBudget.period==period).with_for_update())
    if budget is None or infrastructure_balance(session,budget)[1]<amount:raise FinanceError('Państwo nie ma wystarczających niewydanych środków w bieżącym budżecie infrastruktury.')
    return budget


@precise
def submit_road(user_id,data):
    key=request_key(data.get('request_id'))
    with Session(db.engine) as session,session.begin():
        country=_country_for_user(session,user_id).PANSTWO_ID
        # Validate and quote before any mutation; all parties are then locked in ID order.
        quote=network_quote(session,country,data)
        if quote['partnerId'] is None:
            session.rollback()
            return {'road':build_road(user_id,data)}
        partner=quote['partnerId']
        list(session.scalars(select(Panstwo.PANSTWO_ID).where(Panstwo.PANSTWO_ID.in_(sorted([country,partner]))).order_by(Panstwo.PANSTWO_ID).with_for_update()))
        existing=session.scalar(select(RoadProposal).where(RoadProposal.initiator_id==country,RoadProposal.request_id==key).with_for_update())
        if existing:
            if existing.kind!=data.get('kind') or existing.path!=quote['path']:raise FinanceConflict('Identyfikator zapytania został już użyty.')
            return {'proposalId':existing.id}
        quote=network_quote(session,country,data,lock=True)
        if data.get('expected_cost')!=quote['cost'] or data.get('path')!=quote['path']:raise FinanceConflict('Wycena lub przebieg drogi zmieniły się. Ponów wycenę.')
        if country_user_id(session,partner) is None:raise FinanceError('Sąsiad nie ma aktywnego gracza, który mógłby zaakceptować współfinansowanie.')
        current_budget(session,country,Decimal(quote['shares'][str(country)]['cost']))
        proposal=RoadProposal(initiator_id=country,partner_id=partner,kind=quote['kind'],path=quote['path'],control_points=quote['control_points'],shares=quote['shares'],total_cost=Decimal(quote['cost']),status='pending',request_id=key)
        session.add(proposal);session.flush()
        name=session.scalar(select(Panstwo.panstwo_nazwa).where(Panstwo.PANSTWO_ID==country))
        notice(session,partner,f'{name} proponuje wspólną budowę. Twój odcinek: {quote["shares"][str(partner)]["distanceKm"]} km, koszt {quote["shares"][str(partner)]["cost"]} ROI. Zaakceptuj lub odrzuć w infrastrukturze.')
        return {'proposalId':proposal.id}


@precise
def resolve_proposal(user_id,data,preview=False):
    from game.military_service import natural
    id=natural(data.get('proposal_id'),'Zapytanie',1);action=data.get('decision')
    if action not in ('accept','reject','border','cancel'):raise FinanceError('Nieprawidłowa decyzja.')
    with Session(db.engine) as session,session.begin():
        own=_country_for_user(session,user_id).PANSTWO_ID;initial=session.get(RoadProposal,id)
        if initial is None or own not in (initial.initiator_id,initial.partner_id):raise FinanceError('Nie znaleziono własnego zapytania.')
        ids=sorted([initial.initiator_id,initial.partner_id]);list(session.scalars(select(Panstwo.PANSTWO_ID).where(Panstwo.PANSTWO_ID.in_(ids)).order_by(Panstwo.PANSTWO_ID).with_for_update()))
        proposal=session.scalar(select(RoadProposal).where(RoadProposal.id==id).with_for_update().execution_options(populate_existing=True))
        target={'accept':'accepted','reject':'rejected','border':'border_built','cancel':'cancelled'}[action]
        if own!=(proposal.partner_id if action in ('accept','reject') else proposal.initiator_id):raise FinanceError('Ta decyzja należy do drugiej strony.')
        if proposal.status==target:return id
        if proposal.status!=('rejected' if action=='border' else 'pending'):raise FinanceConflict('Stan zapytania zmienił się. Odśwież listę.')
        if action in ('reject','cancel'):
            proposal.status=target;proposal.resolved_at=utc_now()
            notice(session,proposal.initiator_id if action=='reject' else proposal.partner_id,f'Zapytanie #{id} zostało '+('odrzucone. Możesz zbudować własny odcinek tylko do granicy.' if action=='reject' else 'wycofane.'))
            return id
        quote=network_quote(session,proposal.initiator_id,{'kind':proposal.kind,'start':proposal.path[0],'end':proposal.path[-1],'control_points':proposal.control_points},lock=True)
        if quote['path']!=proposal.path or quote['shares']!=proposal.shares or Decimal(quote['cost'])!=proposal.total_cost:raise FinanceConflict('Granice, skala lub koszt zmieniły się. Złóż nowe zapytanie.')
        parts=quote['parts']
        if action=='border':
            parts=[parts[0]];country=proposal.initiator_id
            from game.military_flights import calibration
            distance=Decimal(str(path_length(parts[0]['path'])*calibration(session).km_per_unit)).quantize(Decimal('.001'),rounding=ROUND_HALF_UP)
            border_cost=(distance*PRICES[proposal.kind]).quantize(Decimal('.01'))
            if preview:return {'cost':str(border_cost),'distanceKm':str(distance)}
            if data.get('expected_cost')!=str(border_cost):raise FinanceConflict('Koszt odcinka do granicy zmienił się. Ponów wycenę.')
            quote['shares']={str(country):{'cost':str(border_cost)}}
        budgets={country:current_budget(session,country,Decimal(quote['shares'][str(country)]['cost'])) for country in sorted({part['countryId'] for part in parts})}
        allocated={country:Decimal(0) for country in budgets}
        for i,part in enumerate(parts):
            country=part['countryId'];later=any(p['countryId']==country for p in parts[i+1:]);total=Decimal(quote['shares'][str(country)]['cost'])
            own_length=sum(path_length(p['path']) for p in parts if p['countryId']==country)
            cost=(total*Decimal(str(path_length(part['path'])/own_length))).quantize(Decimal('.01')) if later else total-allocated[country];allocated[country]+=cost
            from game.military_flights import calibration
            distance=Decimal(str(path_length(part['path'])*calibration(session).km_per_unit)).quantize(Decimal('.001'),rounding=ROUND_HALF_UP)
            if distance<=0:raise FinanceError('Odcinek przy granicy jest zbyt krótki.')
            key=str(uuid5(NAMESPACE_URL,f'road-proposal:{id}:{action}:{i}'))
            start,end=part['path'][0],part['path'][-1]
            from sqlalchemy import and_
            same=or_(and_(Road.start_x==start[0],Road.start_y==start[1],Road.end_x==end[0],Road.end_y==end[1]),and_(Road.start_x==end[0],Road.start_y==end[1],Road.end_x==start[0],Road.end_y==start[1]))
            if session.scalar(select(Road.id).where(Road.panstwo_id==country,Road.kind==proposal.kind,same)):raise FinanceError('Jeden z odcinków już istnieje. Zmień przebieg drogi.')
            session.add(Road(panstwo_id=country,kind=proposal.kind,start_x=start[0],start_y=start[1],end_x=end[0],end_y=end[1],path=part['path'],distance_km=distance,cost=cost,budget_id=budgets[country].id,user_id=user_id,request_id=key))
        proposal.status=target;proposal.resolved_at=utc_now()
        for country in ids:notice(session,country,f'Zapytanie #{id}: '+('wybudowano drogę po obu stronach granicy.' if action=='accept' else 'wybudowano wyłącznie odcinek inicjatora do granicy.'))
        return id


@precise
def upgrade_road(user_id,data,*,admin_country_id=None,admin_actor=None,preview=False):
    from game.military_service import natural
    id=natural(data.get('road_id'),'Droga',1)
    with Session(db.engine) as session,session.begin():
        country=admin_country_id if admin_country_id is not None else _country_for_user(session,user_id).PANSTWO_ID
        session.scalar(select(Panstwo.PANSTWO_ID).where(Panstwo.PANSTWO_ID==country).with_for_update())
        road=session.scalar(select(Road).where(Road.id==id,Road.panstwo_id==country).with_for_update())
        if road is None:raise FinanceError('Droga nie należy do wybranego państwa.')
        key=request_key(data.get('request_id')) if not preview else None
        if key and session.scalar(select(RoadInvestment.id).where(RoadInvestment.panstwo_id==country,RoadInvestment.request_id==key)):
            investment=session.scalar(select(RoadInvestment).where(RoadInvestment.panstwo_id==country,RoadInvestment.request_id==key))
            if investment.road_id!=id:raise FinanceConflict('Identyfikator modernizacji został już użyty.')
            return road_data(road)
        if road.kind!='national':raise FinanceError('Do autostrady można rozbudować tylko drogę krajową.')
        cost=Decimal(0) if admin_country_id is not None else (road.distance_km*800000).quantize(Decimal('.01'))
        if preview:return {'roadId':id,'distanceKm':str(road.distance_km),'cost':str(cost)}
        if data.get('expected_cost')!=str(cost):raise FinanceConflict('Koszt modernizacji zmienił się. Ponów wycenę.')
        budget=None if admin_country_id is not None else current_budget(session,country,cost)
        road.kind='motorway';session.add(RoadInvestment(panstwo_id=country,budget_id=budget.id if budget else None,road_id=id,amount=cost,request_id=key));session.flush()
        return road_data(road)


def proposals_state(session,country):
    names=dict(session.execute(select(Panstwo.PANSTWO_ID,Panstwo.panstwo_nazwa)).all())
    return [{'id':p.id,'kind':p.kind,'status':p.status,'initiatorId':p.initiator_id,'partnerId':p.partner_id,'initiator':names.get(p.initiator_id,''),'partner':names.get(p.partner_id,''),'shares':p.shares,'path':p.path,'own':p.initiator_id==country} for p in session.scalars(select(RoadProposal).where(or_(RoadProposal.initiator_id==country,RoadProposal.partner_id==country)).order_by(RoadProposal.id.desc()).limit(100))]
