"""Drogi dostawy towarów w handlu (administrator, 22 Nov 2026).

* Sprzedający wystawia ofertę bez wyboru transportu — towar czeka w jego magazynie (game.warehouse).
* Kupujący (gracz albo PAGA2) wybiera przy zakupie jedną z dostępnych dróg dostawy z magazynu sprzedającego do
  własnego magazynu:
  - **kolej** — tylko gdy ukończone linie kolejowe łączą oba magazyny; gdy trasa może prowadzić przez różne państwa
    tranzytowe, kupujący wybiera trasę (każda opcja ma własny zestaw państw tranzytowych i ceł);
  - **morze** — port wysyłki sprzedającego i port odbioru kupującego według dotychczasowych zasad portów (własny port
    albo port najbliższego sąsiada, blokady tranzytu, limit eksportu infrastruktury portowej); magazyn i port w różnych
    miastach — towar jedzie koleją do portu wysyłki i z portu odbioru do magazynu; bez takiego połączenia droga morska
    jest niedostępna. Opłaty portowe bez zmian: port wysyłki opłaca sprzedający, port odbioru — kupujący;
  - **powietrze** — czynne lotniska obu państw, połączenie między nimi niezawieszone; dowóz koleją jak przy porcie.
* Opłata za wysyłkę dla MFW (płaci kupujący): lotnicza 8%, morska 5%, kolejowa 0% wartości towaru. Kwoty są zapisywane
  na koncie MFW (ImfShippingFee) i wyświetlane na ekranie MFW — nie zasilają puli pożyczek.
* „Cło lądowe” — procent wartości towaru ustalany przez państwo (ekran handlu); kupujący płaci je każdemu państwu
  tranzytowemu, przez które jedzie pociąg (poza sprzedającym i kupującym); wpływa do rezerwy budżetowej tego państwa.
* Trasa kolejowa nie prowadzi przez państwa w stanie wojny ze sprzedającym albo kupującym.
* Pociąg towarowy jedzie 120 km/h czasu gry (jak inne pociągi), statek 100 km/h, samolot 1000 km/h.
"""
import heapq
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy import select
from sqlalchemy.orm import lazyload
from extensions import db
from models import Miasto, Panstwo
from game.models import utc_now
from game.finance_service import FinanceError
from game.governance import controller_id

RAIL_SPEED = 120     # km/h czasu gry — jak pociągi na mapie świata (game.rail.TRAIN_SPEED)
SEA_SPEED = 100
AIR_SPEED = 1000
IMF_RATES = {'land': Decimal('0'), 'sea': Decimal('5'), 'air': Decimal('8')}   # % wartości towaru, płaci kupujący
MODE_LABELS = {'land': 'Kolej', 'sea': 'Droga morska', 'air': 'Droga lotnicza'}
MAX_RAIL_ALTERNATIVES = 6


class LandCustoms(db.Model):
    """Cło lądowe państwa — % wartości towaru płacony przez kupującego za przejazd pociągu przez terytorium państwa."""
    __tablename__ = 'game_land_customs'
    panstwo_id = db.Column(db.Integer, db.ForeignKey('panstwa.PANSTWO_ID'), primary_key=True)
    rate = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    updated_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    __table_args__ = (db.CheckConstraint('rate BETWEEN 0 AND 100', name='ck_land_customs_rate'), {'mysql_engine': 'InnoDB'})


class ImfShippingFee(db.Model):
    """Opłata za wysyłkę na rzecz MFW (zapis i podgląd; poza pulą pożyczek)."""
    __tablename__ = 'game_imf_shipping_fees'
    id = db.Column(db.Integer, primary_key=True)
    shipment_id = db.Column(db.Integer, db.ForeignKey('game_trade_shipments.id'), nullable=False, unique=True)
    buyer_id = db.Column(db.Integer, nullable=False, index=True)
    seller_id = db.Column(db.Integer, nullable=False)
    transport = db.Column(db.String(8), nullable=False)
    rate = db.Column(db.Numeric(5, 2), nullable=False)
    amount = db.Column(db.Numeric(30, 2), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    __table_args__ = (db.CheckConstraint('amount >= 0', name='ck_imf_shipping_fee_amount'), {'mysql_engine': 'InnoDB'})


def fee(price, rate):
    return (Decimal(price) * Decimal(rate) / 100).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)


def customs_rates(session):
    from sqlalchemy import inspect
    if not inspect(session.connection()).has_table(LandCustoms.__tablename__):
        return {}
    return {row.panstwo_id: Decimal(row.rate) for row in session.scalars(select(LandCustoms))}


def set_customs(user_id, data):
    from sqlalchemy.orm import Session
    from game.finance_service import _country_for_user, percentage
    rate = percentage(data.get('rate'), 'Cło lądowe')
    with Session(db.engine) as session, session.begin():
        country = _country_for_user(session, user_id, lock=True)
        row = session.get(LandCustoms, country.PANSTWO_ID, with_for_update=True)
        if row is None:
            row = LandCustoms(panstwo_id=country.PANSTWO_ID)
            session.add(row)
        row.rate = rate
        row.updated_at = utc_now()
        return country.PANSTWO_ID


def imf_shipping_total(session):
    from sqlalchemy import func, inspect
    if not inspect(session.connection()).has_table(ImfShippingFee.__tablename__):
        return {'total': Decimal(0), 'byTransport': {}}
    rows = session.execute(select(ImfShippingFee.transport, func.coalesce(func.sum(ImfShippingFee.amount), 0)).group_by(ImfShippingFee.transport)).all()
    by = {mode: Decimal(amount) for mode, amount in rows}
    return {'total': sum(by.values(), Decimal(0)), 'byTransport': by}


# ---------------- kolej ----------------

class RailNetwork:
    """Graf ukończonych linii kolejowych (miasta = węzły) z właścicielami miast."""

    def __init__(self, session, now=None):
        from sqlalchemy import inspect
        from game.finance_service import game_now
        from game.rail_models import RailLine
        self.edges = {}
        self.owner = {}
        if not inspect(session.connection()).has_table(RailLine.__tablename__):
            return
        now = now or game_now()
        lines = list(session.scalars(select(RailLine).where(RailLine.status == 'ACTIVE', RailLine.ready_at <= now)))
        for line in lines:
            km = float(line.distance_km)
            path = [list(p) for p in (line.path or [])]
            self.edges.setdefault(line.city_a_id, []).append((line.city_b_id, km, path))
            self.edges.setdefault(line.city_b_id, []).append((line.city_a_id, km, list(reversed(path))))
        ids = list(self.edges)
        if ids:
            for city_id, country in session.execute(select(Miasto.miasto_id, Miasto.panstwo_id).where(Miasto.miasto_id.in_(ids))):
                self.owner[city_id] = controller_id(session, country) if country is not None else None

    def shortest(self, source, target, banned=frozenset()):
        """Najkrótsza trasa (km, [miasta], [punkty]) albo None; miasta państw `banned` są wyłączone (poza końcami)."""
        if source == target:
            return 0.0, [source], []
        if source not in self.edges or target not in self.edges:
            return None
        best = {source: 0.0}
        previous = {}
        queue = [(0.0, source)]
        while queue:
            distance, city = heapq.heappop(queue)
            if city == target:
                break
            if distance > best.get(city, float('inf')):
                continue
            for other, km, path in self.edges.get(city, ()):
                if other != target and self.owner.get(other) in banned:
                    continue
                total = distance + km
                if total < best.get(other, float('inf')):
                    best[other] = total
                    previous[other] = (city, path)
                    heapq.heappush(queue, (total, other))
        if target not in best:
            return None
        cities, points, city = [target], [], target
        segments = []
        while city != source:
            city, path = previous[city]
            cities.append(city)
            segments.append(path)
        cities.reverse()
        for path in reversed(segments):
            points.extend(path if not points else path[1:])
        return best[target], cities, points

    def transit(self, cities, seller, buyer):
        """Państwa tranzytowe trasy (właściciele miast pośrednich i końcowych poza sprzedającym i kupującym)."""
        return sorted({self.owner.get(city) for city in cities} - {seller, buyer, None})

    def alternatives(self, source, target, banned, seller, buyer, limit=MAX_RAIL_ALTERNATIVES):
        """Trasy o różnych zestawach państw tranzytowych (najkrótsza, potem z wykluczeniem kolejnych państw)."""
        found, seen_sets, queue, tried = [], set(), [frozenset(banned)], set()
        while queue and len(found) < limit:
            excluded = queue.pop(0)
            if excluded in tried:
                continue
            tried.add(excluded)
            route = self.shortest(source, target, excluded)
            if route is None:
                continue
            km, cities, points = route
            countries = frozenset(self.transit(cities, seller, buyer))
            if countries not in seen_sets:
                seen_sets.add(countries)
                found.append({'km': km, 'cities': cities, 'path': points, 'transit': sorted(countries)})
            for country in countries:
                queue.append(excluded | {country})
        return sorted(found, key=lambda r: r['km'])


# ---------------- opcje dostawy ----------------

def _war_banned(session, seller, buyer):
    from game.military_service import enemies
    return (set(enemies(session, seller)) | set(enemies(session, buyer))) - {seller, buyer}


def _port_rate(session, owner, country_id):
    from game.commerce_models import PortTariff
    owner = controller_id(session, owner)
    if owner == country_id:
        return Decimal(0)
    return Decimal(session.scalar(select(PortTariff.rate).where(PortTariff.panstwo_id == owner)) or 0)


def allowed_ports(session, country_id, all_ports=None):
    """Porty, przez które państwo może wysyłać i odbierać ładunki (własne albo najbliższego sąsiada; blokady)."""
    from game.trade_service import ports, departure_countries, port_allows
    all_ports = ports(session) if all_ports is None else all_ports
    senders = departure_countries(session, country_id, all_ports)
    result = []
    for port in all_ports:
        owner = controller_id(session, port.panstwo_id)
        if senders is None:
            if owner == country_id:
                result.append(port)
        elif owner in senders and port_allows(session, port.panstwo_id, country_id):
            result.append(port)
    return result


def _point(city_id):
    from game.military_geography import city_point
    point = city_point(city_id)
    return [point[0], point[1]] if point is not None else None


def _rail_leg(net, source, target, banned, seller, buyer):
    """Dowóz koleją między miastami (None — brak połączenia); to samo miasto — pusty odcinek."""
    route = net.shortest(source, target, banned)
    if route is None:
        return None
    km, cities, points = route
    return {'mode': 'land', 'km': km, 'path': points, 'cities': cities, 'transit': net.transit(cities, seller, buyer)} if km else \
        {'mode': 'land', 'km': 0.0, 'path': [], 'cities': cities, 'transit': []}


def _names(session, ids):
    ids = {i for i in ids if i is not None}
    return dict(session.execute(select(Panstwo.PANSTWO_ID, Panstwo.panstwo_nazwa).where(Panstwo.PANSTWO_ID.in_(ids or {0}))).all()) if ids else {}


def _finish(session, option, price, seller, buyer, rates):
    """Koszty opcji: cła tranzytowe, opłata MFW, opłaty portowe; czas przejazdu."""
    transit = sorted({country for leg in option['legs'] for country in leg.get('transit', [])})
    names = _names(session, transit)
    option['transit'] = [{'countryId': c, 'name': names.get(c, ''), 'rate': str(rates.get(c, Decimal(0))), 'amount': str(fee(price, rates.get(c, Decimal(0))))} for c in transit]
    customs = sum((fee(price, rates.get(c, Decimal(0))) for c in transit), Decimal(0))
    imf_rate = IMF_RATES[option['mode']]
    imf = fee(price, imf_rate)
    arrival_fee = option.pop('_arrival_fee', Decimal(0))
    departure_fee = option.pop('_departure_fee', Decimal(0))
    speeds = {'land': RAIL_SPEED, 'sea': SEA_SPEED, 'air': AIR_SPEED}
    hours = sum(leg['km'] / speeds[leg['mode']] for leg in option['legs'])
    option.update(customs=str(customs), imfRate=str(imf_rate), imfFee=str(imf), arrivalFee=str(arrival_fee), departureFee=str(departure_fee),
                  km=round(sum(leg['km'] for leg in option['legs']), 1), hours=round(hours, 2),
                  total=str(Decimal(price) + arrival_fee + customs + imf), sellerNet=str(Decimal(price) - departure_fee))
    for leg in option['legs']:
        leg['km'] = round(leg['km'], 3)
    return option


def delivery_options(session, offer, buyer, now=None):
    """Dostępne drogi dostawy oferty do magazynu kupującego — lista opcji (kolej, morze, powietrze) z kosztami."""
    from game.warehouse import warehouse_city
    from game.trade_service import ports
    from game.military_flights import calibration
    seller = controller_id(session, offer.panstwo_id)
    buyer = controller_id(session, buyer)
    origin, destination = warehouse_city(session, seller), warehouse_city(session, buyer)
    if origin is None or destination is None or seller == buyer:
        return []
    price = Decimal(offer.price)
    rates = customs_rates(session)
    banned = frozenset(_war_banned(session, seller, buyer))
    net = RailNetwork(session, now)
    options = []
    # --- kolej: magazyn → magazyn, po jednej opcji na zestaw państw tranzytowych
    if origin != destination:
        for route in net.alternatives(origin, destination, banned, seller, buyer):
            key = 'land:' + ('-'.join(str(c) for c in route['transit']) or 'direct')
            options.append(_finish(session, {'key': key, 'mode': 'land', 'label': MODE_LABELS['land'],
                                             'legs': [{'mode': 'land', 'km': route['km'], 'path': route['path'], 'transit': route['transit']}],
                                             'departureCityId': origin, 'arrivalCityId': destination}, price, seller, buyer, rates))
    km_per_unit = calibration(session).km_per_unit
    # --- morze: magazyn → (kolej) → port wysyłki → statek → port odbioru → (kolej) → magazyn
    from game.infrastructure_effects import port_export_limit
    from models import Region
    all_ports = ports(session)
    departures = []
    for port in allowed_ports(session, seller, all_ports):
        region = session.get(Region, port.region_id)
        limit, only = port_export_limit(region.region_stan_infra_portowej if region is not None else 0)
        if only is not None and set(offer.cargo) - {only}:
            continue
        if limit is not None and sum(offer.cargo.values()) > limit:
            continue
        leg = _rail_leg(net, origin, port.miasto_id, banned, seller, buyer)
        if leg is not None and _point(port.miasto_id) is not None:
            departures.append((leg['km'], port, leg))
    if departures:
        from game.sea_routes import shortest_sea_route, path_length
        _, departure, first = min(departures, key=lambda item: (item[0], item[1].miasto_id))
        for port in allowed_ports(session, buyer, all_ports):
            if port.miasto_id == departure.miasto_id or _point(port.miasto_id) is None:
                continue
            last = _rail_leg(net, port.miasto_id, destination, banned, seller, buyer)
            if last is None:
                continue
            sea = shortest_sea_route(_point(departure.miasto_id), _point(port.miasto_id))
            legs = [leg for leg in (first,) if leg['km']] + [{'mode': 'sea', 'km': path_length(sea) * km_per_unit, 'path': [list(p) for p in sea], 'transit': []}] + \
                   [leg for leg in (last,) if leg['km']]
            options.append(_finish(session, {'key': f'sea:{port.miasto_id}', 'mode': 'sea', 'label': MODE_LABELS['sea'], 'legs': legs,
                                             'departurePortId': departure.miasto_id, 'departurePort': departure.miasto_nazwa,
                                             'arrivalPortId': port.miasto_id, 'arrivalPort': port.miasto_nazwa,
                                             'departureCityId': origin, 'arrivalCityId': destination,
                                             '_departure_fee': fee(price, _port_rate(session, departure.panstwo_id, seller)),
                                             '_arrival_fee': fee(price, _port_rate(session, port.panstwo_id, buyer))}, price, seller, buyer, rates))
    # --- powietrze: magazyn → (kolej) → lotnisko sprzedającego → samolot → lotnisko kupującego → (kolej) → magazyn
    from game.airports import own_operational, suspended_pairs
    seller_airports, buyer_airports = own_operational(session, seller, now), own_operational(session, buyer, now)
    if seller_airports and buyer_airports:
        blocked = suspended_pairs(session)
        starts = []
        for airport in seller_airports:
            leg = _rail_leg(net, origin, airport.miasto_id, banned, seller, buyer)
            if leg is not None:
                starts.append((leg['km'], airport, leg))
        for target in buyer_airports:
            last = _rail_leg(net, target.miasto_id, destination, banned, seller, buyer)
            if last is None:
                continue
            usable = [item for item in starts if frozenset((item[1].id, target.id)) not in blocked and item[1].id != target.id]
            if not usable:
                continue
            _, source, first = min(usable, key=lambda item: (item[0], item[1].id))
            flight = [[source.map_x, source.map_y], [target.map_x, target.map_y]]
            from math import hypot
            legs = [leg for leg in (first,) if leg['km']] + [{'mode': 'air', 'km': hypot(flight[1][0] - flight[0][0], flight[1][1] - flight[0][1]) * km_per_unit, 'path': flight, 'transit': []}] + \
                   [leg for leg in (last,) if leg['km']]
            options.append(_finish(session, {'key': f'air:{target.miasto_id}', 'mode': 'air', 'label': MODE_LABELS['air'], 'legs': legs,
                                             'departureAirport': source.name, 'departureAirportCityId': source.miasto_id,
                                             'arrivalAirport': target.name, 'arrivalAirportCityId': target.miasto_id,
                                             'departureCityId': origin, 'arrivalCityId': destination}, price, seller, buyer, rates))
    options.sort(key=lambda o: (Decimal(o['total']), o['hours']))
    # Najwyżej 3 opcje morskie i 3 lotnicze (najtańsze, potem najszybsze) — kolejne porty/lotniska odbioru różnią się zwykle tylko czasem.
    kept, count = [], {}
    for option in options:
        count[option['mode']] = count.get(option['mode'], 0) + 1
        if option['mode'] == 'land' or count[option['mode']] <= 3:
            kept.append(option)
    return kept


def schedule(legs, start):
    """Czasy odcinków: kolej 120 km/h, statek 100 km/h, samolot 1000 km/h (czas gry)."""
    from datetime import timedelta
    speeds = {'land': RAIL_SPEED, 'sea': SEA_SPEED, 'air': AIR_SPEED}
    moment, result = start, []
    for leg in legs:
        end = moment + timedelta(seconds=max(1, leg['km'] / speeds[leg['mode']] * 3600))
        result.append({'mode': leg['mode'], 'path': leg['path'], 'km': leg['km'], 'startsAt': moment.isoformat(), 'arrivesAt': end.isoformat()})
        moment = end
    return result, moment


def leg_at(shipment, moment):
    """Odcinek podróży przesyłki w danej chwili (None — przesyłka bez odcinków, czyli sprzed 22 Nov 2026)."""
    from datetime import datetime
    legs = getattr(shipment, 'legs', None) or []
    if not legs:
        return None
    for leg in legs:
        if moment < datetime.fromisoformat(leg['arrivesAt']):
            return leg
    return legs[-1]


def mode_at(shipment, moment):
    leg = leg_at(shipment, moment)
    return leg['mode'] if leg else (shipment.transport or 'sea')


def legs_json(legs):
    """Odcinki przesyłki dla map (czas z sufiksem Z jak pozostałe znaczniki czasu gry)."""
    return [{'mode': leg['mode'], 'path': leg['path'], 'startsAt': leg['startsAt'] + 'Z', 'arrivesAt': leg['arrivesAt'] + 'Z'} for leg in legs or []]
