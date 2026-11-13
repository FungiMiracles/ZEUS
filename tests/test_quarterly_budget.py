"""Budżet kwartalny od 1 października 3001 (13 Nov 2026)."""
import unittest
from datetime import datetime
from decimal import Decimal
from game.finance_service import (period_key,period_bounds,period_months,period_share,next_period_key,period_label,calculate_budget,FinanceError)


class QuarterlyPeriodTests(unittest.TestCase):
    def test_halves_until_october_3001_then_quarters(self):
        self.assertEqual(period_key(datetime(3001,9,30,23)),(3001,2))
        self.assertEqual(period_key(datetime(3001,10,1)),(3001,4))
        self.assertEqual(period_key(datetime(3002,1,1)),(3002,1))
        self.assertEqual(period_key(datetime(3002,5,15)),(3002,2))
        self.assertEqual(period_key(datetime(3002,8,1)),(3002,3))
        self.assertEqual(period_key(datetime(3000,8,1)),(3000,2))

    def test_bounds_and_lengths(self):
        self.assertEqual(period_bounds(3001,2),(datetime(3001,7,1),datetime(3001,10,1)))   # II półrocze 3001 skrócone
        self.assertEqual(period_bounds(3001,4),(datetime(3001,10,1),datetime(3002,1,1)))
        self.assertEqual(period_bounds(3002,2),(datetime(3002,4,1),datetime(3002,7,1)))
        self.assertEqual(period_bounds(3000,2),(datetime(3000,7,1),datetime(3001,1,1)))
        with self.assertRaises(FinanceError):period_bounds(3001,3)      # w 3001 nie ma III kwartału
        with self.assertRaises(FinanceError):period_bounds(3000,4)
        self.assertEqual((period_months(3001,2),period_months(3001,4),period_months(3005,3)),(6,3,3))
        self.assertEqual(period_share(3002,1),Decimal('0.25'))

    def test_next_period_and_order(self):
        sequence=[(3001,1)]
        for _ in range(6):sequence.append(next_period_key(sequence[-1]))
        self.assertEqual(sequence,[(3001,1),(3001,2),(3001,4),(3002,1),(3002,2),(3002,3),(3002,4)])
        self.assertEqual(sequence,sorted(sequence))   # kolejność krotek = kolejność w czasie
        self.assertEqual(next_period_key((3000,2)),(3001,1))

    def test_labels(self):
        self.assertEqual(period_label(3001,2),'II półrocze 3001')
        self.assertEqual(period_label(3001,4),'IV kwartał 3001')

    def test_quarter_collects_quarter_of_annual_tax(self):
        half=calculate_budget(Decimal(1000000),Decimal(1000),Decimal(0),Decimal(20),Decimal(0),{'reserve':100})
        quarter=calculate_budget(Decimal(1000000),Decimal(1000),Decimal(0),Decimal(20),Decimal(0),{'reserve':100},share=period_share(3002,1))
        self.assertEqual(quarter['tax_total']*2,half['tax_total'])


class QuarterlyAmountTests(unittest.TestCase):
    def test_upkeep_estimate_is_halved_in_a_quarter(self):
        from unittest.mock import patch
        from game.paga2.defense import upkeep
        garrison={'soldiers':1000,'tanks':10}
        with patch('game.finance_service.current_period_months',return_value=6):half=upkeep(garrison)
        with patch('game.finance_service.current_period_months',return_value=3):quarter=upkeep(garrison)
        self.assertEqual(quarter*2,half)
