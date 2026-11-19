"""Shared route/time sampling and combat visibility for merchant vessels."""
from sqlalchemy import select,or_
from models import Miasto,Panstwo
from game.commerce_models import TradeShipment
from game.finance_service import FinanceError,game_now
from game.sea_routes import path_position
from game.governance import controller_id


def shipment_position(shipment,now):
    duration=max(1,(shipment.arrives_at-shipment.starts_at).total_seconds())
    return path_position(shipment.route or [[shipment.source_x,shipment.source_y],[shipment.target_x,shipment.target_y]],(now-shipment.starts_at).total_seconds()/duration)


def target_country(session,shipment,attacker):
    from game.military_service import enemies
    actors={controller_id(session,id) for id in (shipment.seller_id,shipment.buyer_id)}
    if attacker in actors:raise FinanceError('Nie można zaatakować własnego statku ani własnego ładunku.')
    enemy=set(enemies(session,attacker));candidates=actors&enemy
    if not candidates:raise FinanceError('Statek nie przewozi ładunku państwa, z którym trwa wojna.')
    return controller_id(session,shipment.buyer_id) if controller_id(session,shipment.buyer_id) in candidates else min(candidates)


def active_shipments(session,now=None):
    now=now or game_now()
    return select(TradeShipment).where(TradeShipment.delivered_at.is_(None),TradeShipment.sunk_at.is_(None),TradeShipment.health>0,TradeShipment.starts_at<= now,TradeShipment.arrives_at>now)


def visible_shipments(session,country_id):
    from game.military_service import enemies
    names=dict(session.execute(select(Panstwo.PANSTWO_ID,Panstwo.panstwo_nazwa)).all());enemy=set(enemies(session,country_id))
    cities={id:(region,owner) for id,region,owner in session.execute(select(Miasto.miasto_id,Miasto.region_id,Miasto.panstwo_id))}
    result=[]
    for ship in session.scalars(active_shipments(session).order_by(TradeShipment.id)):
        origin=cities.get(ship.departure_port_id);arrival=cities.get(ship.arrival_port_id)
        if not origin or not arrival:continue
        own=country_id in (ship.seller_id,ship.buyer_id)
        owner=ship.buyer_id if ship.buyer_id in enemy else ship.seller_id if ship.seller_id in enemy else ship.buyer_id
        result.append({'id':ship.id,'countryId':owner,'regionId':str(origin[0]),'originCountryId':ship.origin_country_id or origin[1],
            'sellerId':ship.seller_id,'buyerId':ship.buyer_id,'seller':names.get(ship.seller_id,''),'buyer':names.get(ship.buyer_id,''),'health':ship.health,
            'route':ship.route or [[ship.source_x,ship.source_y],[ship.target_x,ship.target_y]],'startsAt':ship.starts_at.isoformat()+'Z','arrivesAt':ship.arrives_at.isoformat()+'Z',
            'canAttack':not own and bool({ship.seller_id,ship.buyer_id}&enemy),'transport':ship.transport or 'sea'})
    return result
