"""Czas rozwoju technologii (13 Nov 2026)."""
import unittest
from datetime import datetime,timedelta
from game.research_timing import DURATION_DAYS,developed,researching,start
from game.industry_catalog import TECHNOLOGIES

NOW=datetime(3001,1,1,12)


class ResearchTimingTests(unittest.TestCase):
    def test_every_technology_has_a_duration_and_examples_match_requirements(self):
        self.assertFalse(set(TECHNOLOGIES)-set(DURATION_DAYS))
        expected={'method':1,'it_industry':2,'mine_coal':1,'mine_oil':3,'mine_uranium':16,'chip_cemium_ii':60,'power_nuclear':60,
                  'tanks':21,'fighters':60,'warship':124,'carrier':182,'submarine':166,'waste_filters':7,'air_filters':12,'interceptor_ammo':10}
        for code,days in expected.items():self.assertEqual(DURATION_DAYS[code],days,code)

    def test_funded_technology_is_developed_only_after_its_time(self):
        nodes={'tanks':TECHNOLOGIES['tanks']['cost']}
        timers=start({},'tanks',NOW)
        self.assertTrue(researching(nodes,timers,'tanks',NOW+timedelta(days=20)))
        self.assertFalse(developed(nodes,timers,'tanks',NOW+timedelta(days=20)))
        self.assertTrue(developed(nodes,timers,'tanks',NOW+timedelta(days=21)))
        self.assertTrue(developed(nodes,{},'tanks',NOW))                           # opracowana przed wprowadzeniem czasu rozwoju
        self.assertFalse(developed({'tanks':1},{},'tanks',NOW))                    # niepełne punkty
