"""23 Nov 2026: wycofanie obrony miasta do wybranej bazy albo do rezerwy państwa, także częściowe (oddziały bez bazy
macierzystej po aneksji i oddziały, których baza jest pełna)."""
from extensions import db
from game.military_models import MilitaryBase
from game.land_war_models import LandArmy
from game.finance_service import FinanceError
from game import land_war
from test_land_war import LandWarFixture, key


class CityDefenseWithdrawTests(LandWarFixture):
    def detachment(self, source_base_id=None, soldiers=5000, armored=10, tanks=0):
        army = LandArmy(panstwo_id=1, request_id=key(), role='city_defense', status='DEFENDING', source_base_id=source_base_id,
                        soldiers=soldiers, armored=armored, tanks=tanks, target_kind='city', target_city_id=11, target_country_id=1,
                        target_region_id=1, target_name='Miasto A', starts_at=self.now, arrives_at=self.now)
        db.session.add(army); db.session.commit()
        return army.id

    def test_detachment_without_home_base_goes_to_reserve(self):
        army_id = self.detachment()
        with self.assertRaises(FinanceError) as error:
            land_war.withdraw_city_defense(1, {'army_id': army_id})
        self.assertIn('rezerwę', str(error.exception))
        result = land_war.withdraw_city_defense(1, {'army_id': army_id, 'to_reserve': True})
        self.assertIn('rezerwy państwa', result['message'])
        army = self.army(army_id)
        self.assertEqual((army.status, army.soldiers, army.armored), ('WITHDRAWN', 0, 0))

    def test_full_home_base_partial_withdrawal_to_another_base(self):
        small = MilitaryBase(panstwo_id=1, region_id=1, kind='land', level=1, garrison={'soldiers': 8374, 'armored': 0, 'tanks': 0}, map_x=5, map_y=0)
        db.session.add(small); db.session.commit()
        army_id = self.detachment(source_base_id=small.id, soldiers=5049, armored=18)
        with self.assertRaises(FinanceError) as error:
            land_war.withdraw_city_defense(1, {'army_id': army_id})
        self.assertIn('Wolne miejsca', str(error.exception))
        # część do bazy macierzystej (zmieści się 1 626 żołnierzy), reszta do dużej bazy
        result = land_war.withdraw_city_defense(1, {'army_id': army_id, 'soldiers': 1626, 'armored': 0, 'tanks': 0})
        self.assertIn('reszta nadal broni miasta', result['message'])
        self.assertEqual(self.army(army_id).soldiers, 5049 - 1626)
        land_war.withdraw_city_defense(1, {'army_id': army_id, 'base_id': self.home.id})
        db.session.expire_all()
        self.assertEqual(db.session.get(MilitaryBase, small.id).garrison['soldiers'], 10000)
        home = db.session.get(MilitaryBase, self.home.id).garrison
        self.assertEqual((home['soldiers'], home['armored']), (5000 + 5049 - 1626, 20 + 18))
        self.assertEqual(self.army(army_id).status, 'WITHDRAWN')

    def test_cannot_withdraw_more_than_the_detachment_has(self):
        army_id = self.detachment()
        with self.assertRaises(FinanceError):
            land_war.withdraw_city_defense(1, {'army_id': army_id, 'to_reserve': True, 'soldiers': 6000})
