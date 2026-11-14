"""Granice cen jednostki, jeden rodzaj towaru na ofertę i minimum 1 MLN (12 Nov 2026)."""
import unittest
from decimal import Decimal
from uuid import uuid4
from test_game_commerce import CommerceFixture
from game.finance_service import FinanceError
from game.trade_service import create_offer
from game import trade_prices


class PriceLimitTests(unittest.TestCase):
    def test_limits_follow_production_costs_with_margins(self):
        low,high=trade_prices.unit_limits('wegiel_kamienny')
        # minimum: kopalnia poz. 1 (2 MLD / 73 jedn. rocznie) −5%; maksimum: + technologie (75 pkt × cena punktu) +10%
        # 13 Nov 2026: punkt rozwoju 150 mln ROI (było 400 mln) — górny limit węgla 483 → 200 MLN
        self.assertEqual(low,26_000_000);self.assertEqual(high,200_000_000)
        self.assertEqual(trade_prices.unit_limits('kamien')[0],1_000_000)            # nie mniej niż 1 MLN
        for code in ('tanks','chip_natsyt','interceptor_ammunition','cemium'):
            low,high=trade_prices.unit_limits(code);self.assertLess(low,high);self.assertGreaterEqual(low,1_000_000)

    def test_offer_rules(self):
        self.assertIn('jeden rodzaj',trade_prices.check_offer({'zloto':1,'srebro':1},'100000000'))
        self.assertIsNone(trade_prices.check_offer({'wegiel_kamienny':10},'1000000000'))   # 100 MLN za jedn.
        self.assertIn('poza dozwolonym',trade_prices.check_offer({'wegiel_kamienny':10},'100000000'))
        self.assertIn('poza dozwolonym',trade_prices.check_offer({'wegiel_kamienny':1},'600000000'))
        self.assertIn('1 MLN',trade_prices.check_offer({'kamien':1},'999999'))
        self.assertEqual(trade_prices.clamp('wegiel_kamienny',2,Decimal(1)),Decimal(52_000_000))


class OfferPriceTests(CommerceFixture):
    ENFORCE_TRADE_RULES=True
    def offer(self,cargo,price):
        return create_offer(1,dict(request_id=str(uuid4()),cargo=cargo,price=price,port_id=101,departure_rate='0'))

    def test_create_offer_enforces_rules(self):
        with self.assertRaisesRegex(FinanceError,'1 MLN'):self.offer({'wegiel_kamienny':5},'1000')
        with self.assertRaisesRegex(FinanceError,'poza dozwolonym'):self.offer({'wegiel_kamienny':5},'50000000')
        self.assertIsNotNone(self.offer({'wegiel_kamienny':5},'500000000'))
