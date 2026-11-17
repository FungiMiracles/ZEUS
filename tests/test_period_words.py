"""16 Nov 2026: nazwa okresu budżetowego w tekstach gry — półrocze do 1 października 3001, potem kwartał."""
import unittest
from datetime import datetime
from unittest.mock import patch
from game.finance_service import period_words


class PeriodWordsTests(unittest.TestCase):
    def test_half_year_and_quarter_forms(self):
        half = period_words(3001, 2)
        self.assertEqual((half['current'], half['loc'], half['share'], half['months']), ('bieżące półrocze', 'półroczu', 50, 6))
        quarter = period_words(3001, 4)
        self.assertEqual((quarter['current'], quarter['gen'], quarter['share'], quarter['months']), ('bieżący kwartał', 'kwartału', 25, 3))
        self.assertIn('kwietniu', quarter['per_year']); self.assertIn('lipcu', half['per_year'])

    def test_defaults_to_current_game_period(self):
        with patch('game.finance_service.game_now', return_value=datetime(3001, 10, 7)):
            self.assertEqual(period_words()['nom'], 'kwartał')


if __name__ == '__main__':
    unittest.main()
