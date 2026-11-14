"""13 Nov 2026: wycofanie oferty po 14 dniach Entendy (gracz i PAGA2), obniżka ceny oferty, PAGA2 bez duplikatów ofert."""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import patch
from sqlalchemy import select
from extensions import db
from test_game_commerce import CommerceFixture
from test_game_military import NOW
from game.commerce_models import TradeOffer,ResourceStock
from game.trade_service import create_offer,expire_offers,reprice_offer,buy_offer,OFFER_LIFETIME_DAYS
from game.finance_service import FinanceError
from game.forum_models import GameNotification


class OfferExpiryTests(CommerceFixture):
    def offer(self,**extra):
        return create_offer(1,dict(request_id=str(uuid4()),cargo={'wegiel_kamienny':5},price='1000',port_id=101,departure_rate='0',**extra))

    def coal(self):
        db.session.expire_all();return int(db.session.get(ResourceStock,(1,'wegiel_kamienny')).quantity)

    def test_offer_records_game_time_and_expires_after_14_days(self):
        self.assertEqual(OFFER_LIFETIME_DAYS,14)
        id=self.offer();self.assertEqual(self.coal(),15)
        offer=db.session.get(TradeOffer,id);self.assertEqual(offer.created_game_at,NOW)
        self.assertEqual(expire_offers(db.session,NOW+timedelta(days=13,hours=23)),0);db.session.commit()
        self.assertEqual(expire_offers(db.session,NOW+timedelta(days=14)),1);db.session.commit()
        db.session.expire_all();self.assertEqual(db.session.get(TradeOffer,id).status,'cancelled');self.assertEqual(self.coal(),20)
        notes=[n.system_text for n in db.session.scalars(select(GameNotification).where(GameNotification.user_id==1))]
        self.assertTrue(any(f'#{id}' in t and '14 dni Entendy' in t and 'wycofana' in t for t in notes))
        self.assertEqual(expire_offers(db.session,NOW+timedelta(days=30)),0)   # tylko raz

    def test_expired_offer_cannot_be_bought(self):
        id=self.offer()
        with patch('game.trade_service.game_now',return_value=NOW+timedelta(days=15)):
            with self.assertRaisesRegex(FinanceError,'wygasła'):buy_offer(2,dict(request_id=str(uuid4()),offer_id=id,port_id=102,arrival_rate='0'))

    def test_trade_state_sweeps_expired_offers(self):
        id=self.offer();self.login(2)
        with patch('game.commerce.game_now',return_value=NOW+timedelta(days=15)),patch('game.trade_service.game_now',return_value=NOW+timedelta(days=15)),patch('game.finance_service.game_now',return_value=NOW+timedelta(days=15)):
            from game.commerce import trade_state
            with self.app.test_request_context():state=trade_state(2)
        db.session.commit()
        self.assertNotIn(id,[o['id'] for o in state['offers']]);db.session.expire_all();self.assertEqual(db.session.get(TradeOffer,id).status,'cancelled')

    def test_reprice_only_lower_own_open_offer(self):
        id=self.offer()
        with self.assertRaisesRegex(FinanceError,'niższa'):reprice_offer(1,{'offer_id':id,'price':'1000'})
        with self.assertRaisesRegex(FinanceError,'nie należy'):reprice_offer(2,{'offer_id':id,'price':'900'})
        with patch('game.trade_service.game_now',return_value=NOW+timedelta(days=3)):reprice_offer(1,{'offer_id':id,'price':'900'})
        db.session.expire_all();offer=db.session.get(TradeOffer,id)
        self.assertEqual((offer.price,offer.price_changed_game_at,offer.created_game_at),(Decimal('900.00'),NOW+timedelta(days=3),NOW))   # termin wycofania bez zmian


class Paga2OfferTests(CommerceFixture):
    def paga(self,now):
        return SimpleNamespace(country_id=1,now=now,traits={'trade_propensity':80,'isolationism':30,'ambition':50,'militarism':10},situation={'level':'peace'},priorities=['trade'],categories=[])

    def test_no_second_offer_for_listed_good_and_reprice_after_3_days(self):
        from game.paga2 import trade
        screen={'warehouse':{'wegiel_kamienny':{'available':500}},'offers':[{'id':7,'own':True,'cargo':{'wegiel_kamienny':5},'price':'1000000000','createdAt':NOW.isoformat()+'Z','priceChangedAt':None}],
                'ports':{'101':{'countryId':1,'allowed':True,'rate':'0'}}}
        with patch('game.paga2.trade.own_port',return_value=101),patch('game.paga2.trade.port_limit',return_value=(None,None)),patch('game.paga2.planner._holdings',return_value=None),\
             patch('game.paga2.pricing.consumption',return_value={}),patch('game.paga2.trade.unfriendly',return_value=set()):
            self.assertEqual(trade.sell_options(self.paga(NOW),screen,{}),[])                       # towar już wystawiony — bez nowej oferty
        self.assertEqual(trade.reprice_options(self.paga(NOW+timedelta(days=2)),screen),[])          # za wcześnie na obniżkę
        [option]=trade.reprice_options(self.paga(NOW+timedelta(days=3)),screen)
        self.assertEqual(option.action,'TRADE_REPRICE');self.assertEqual(option.payload['offer_id'],7)
        self.assertEqual(Decimal(option.payload['price']),Decimal('900000000.00'))
        screen['offers'][0]['priceChangedAt']=(NOW+timedelta(days=3)).isoformat()+'Z'
        self.assertEqual(trade.reprice_options(self.paga(NOW+timedelta(days=5)),screen),[])          # 3 dni od ostatniej obniżki
