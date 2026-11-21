"""Transport lotniczy — dane startowe UAT (administrator, 20 Nov 2026). Tylko ZEUS_UAT (entenda_uat_db).

    ENV_NAME=UAT venv/bin/python migrations/sql/airports_uat_seed_20261120.py            # podgląd
    ENV_NAME=UAT venv/bin/python migrations/sql/airports_uat_seed_20261120.py --apply    # zapis (idempotentny)

- Ozilandia i Findehalia: technologie „Transport i komunikacja” → „Transport kolejowy” → „Transport lotniczy” opracowane
  (komplet punktów, bez trwającego czasu rozwoju);
- czynne porty lotnicze: Saint Adams (Ozilandia) i Delin (Findehalia), nazwy domyślne, budowa zakończona — przydział
  administratora bez pobierania surowców i środków budżetu;
- Findehalia wystawia przez endpoint gracza (bramka PAGA2) ofertę sprzedaży żelaza drogą lotniczą z lotniska Delin;
  magazyn Findehalii dostaje dokładnie tyle żelaza, ile obejmuje oferta (towar zostaje zarezerwowany w ofercie).
Wymaga migracji airports_20261120.
"""
import argparse, os, sys
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
COUNTRIES = {'Ozilandia': 'Saint Adams', 'Findehalia': 'Delin'}
CHAIN = ('method', 'national_hubs', 'rail_transport', 'air_transport')
OFFER_RESOURCE, OFFER_QUANTITY = 'zelazo', 50


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    assert ROOT.name == 'ZEUS_UAT' and os.environ.get('ENV_NAME') == 'UAT', 'Skrypt wyłącznie dla ZEUS_UAT z ENV_NAME=UAT.'
    sys.path.insert(0, str(ROOT))
    from zeus_app import app
    from sqlalchemy import select, text
    from sqlalchemy.orm import Session
    from extensions import db
    from models import Panstwo, Miasto
    from game.finance_service import game_now
    from game.industry_catalog import TECHNOLOGIES
    from game.research_models import ResearchAccount
    from game.airport_models import Airport
    from game.airports import default_name, BUILD_DAYS, PRICE_PER_RESIDENT
    from game.commerce_models import TradeOffer, ResourceStock
    with app.app_context():
        assert db.session.execute(text('SELECT DATABASE()')).scalar() == 'entenda_uat_db'
        now = game_now()
        with Session(db.engine) as session, session.begin():
            ids = {}
            for country, city_name in COUNTRIES.items():
                country_id = session.scalar(select(Panstwo.PANSTWO_ID).where(Panstwo.panstwo_nazwa == country))
                city = session.scalar(select(Miasto).where(Miasto.miasto_nazwa == city_name, Miasto.panstwo_id == country_id))
                assert country_id and city, f'Brak państwa {country} lub miasta {city_name}.'
                ids[country] = (country_id, city.miasto_id)
                account = session.get(ResearchAccount, country_id)
                if account is None:
                    account = ResearchAccount(panstwo_id=country_id, points=0, ammunition=0, nodes={})
                    session.add(account)
                nodes, timers = dict(account.nodes or {}), dict(getattr(account, 'timers', None) or {})
                changed = [code for code in CHAIN if int(nodes.get(code, 0)) < TECHNOLOGIES[code]['cost']]
                for code in changed:
                    nodes[code] = TECHNOLOGIES[code]['cost']
                    timers.pop(code, None)
                print(f'{country}: technologie do uzupełnienia: {changed or "brak"}')
                if args.apply and changed:
                    account.nodes = nodes
                    if hasattr(account, 'timers'):
                        account.timers = timers
                existing = session.scalar(select(Airport).where(Airport.miasto_id == city.miasto_id, Airport.removed_at.is_(None)))
                print(f'{country}: lotnisko w mieście {city.miasto_nazwa}: {"istnieje (#%d)" % existing.id if existing else "do utworzenia"}')
                if args.apply and existing is None:
                    from game.military_geography import city_point
                    point = city_point(city.miasto_id)
                    session.add(Airport(panstwo_id=country_id, miasto_id=city.miasto_id, region_id=city.region_id,
                                        name=default_name(city.miasto_nazwa, city.miasto_kod), map_x=float(point[0]), map_y=float(point[1]),
                                        cost=(Decimal(int(city.miasto_populacja or 0)) * PRICE_PER_RESIDENT), materials={}, health=100,
                                        starts_at=now - timedelta(days=BUILD_DAYS), ready_at=now - timedelta(minutes=1),
                                        request_id='uat-seed-20261120'))
            seller, delin = ids['Findehalia']
            offer = session.scalar(select(TradeOffer).where(TradeOffer.panstwo_id == seller, TradeOffer.transport == 'air', TradeOffer.status == 'open'))
            print(f'Findehalia: otwarta oferta lotnicza: {"#%d" % offer.id if offer else "do wystawienia"}')
            stocked = session.scalar(select(ResourceStock.quantity).where(ResourceStock.panstwo_id == seller, ResourceStock.resource == OFFER_RESOURCE)) or 0
            if args.apply and offer is None and stocked < OFFER_QUANTITY:
                stock = session.get(ResourceStock, (seller, OFFER_RESOURCE))
                if stock is None:
                    stock = ResourceStock(panstwo_id=seller, resource=OFFER_RESOURCE, quantity=0)
                    session.add(stock)
                stock.quantity += OFFER_QUANTITY - stocked
        if not args.apply:
            return
        seller, delin = ids['Findehalia']
        with Session(db.engine) as session:
            if session.scalar(select(TradeOffer.id).where(TradeOffer.panstwo_id == seller, TradeOffer.transport == 'air', TradeOffer.status == 'open')):
                print('Gotowe (oferta już istniała).')
                return
        from game import trade_prices
        price = trade_prices.all_limits([OFFER_RESOURCE])[OFFER_RESOURCE]
        unit = (Decimal(str(price['min'])) + Decimal(str(price['max']))) / 2
        total = (unit * OFFER_QUANTITY).quantize(Decimal('1'))
        from game.paga2 import gateway
        from game.paga_ai_actor import ensure_identity, AiActor
        from game.paga2.models import Paga2Control
        with Session(db.engine) as session:
            identity = ensure_identity(session, seller)
            control = session.get(Paga2Control, 1)
            actor = AiActor(country_id=seller, user_id=identity.user_id, revision=control.revision, engine='paga2')
            session.commit()
        status, data = gateway.call(app, actor, '/game/handel/zmien', method='POST',
                                    json={'action': 'offer', 'transport': 'air', 'cargo': {OFFER_RESOURCE: OFFER_QUANTITY}, 'price': str(total),
                                          'port_id': delin, 'departure_rate': '0', 'excluded': [], 'request_id': str(uuid4())})
        print('Oferta Findehalii:', status, data)
        assert status < 400, 'Nie udało się wystawić oferty.'


if __name__ == '__main__':
    main()
