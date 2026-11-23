"""Wyzwalanie obiektów sojuszników, regionów spod aneksji i wskrzeszanie państw (23 Nov 2026)."""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from sqlalchemy import select, update
from extensions import db
from models import Wojsko, Miasto, Region, Stosunki, Panstwo, DictStosunkiRelacja
from test_land_war import LandWarFixture, key
from game.military_models import MilitaryBase
from game.land_war_models import LandArmy, Occupation, SovereigntyLoss
from game.finance_service import FinanceError
from game.forum_models import GameNotification
from game.region_history import RegionTransfer, record, former_owner
from game import land_war, liberation

ALLIED = 11


class LiberationFixture(LandWarFixture):
    def setUp(self):
        super().setUp()
        RegionTransfer.__table__.create(db.engine, checkfirst=True)
        from game.paga2.models import Paga2Profile, Paga2ProfileRevision
        for model in (Paga2Profile, Paga2ProfileRevision):
            model.__table__.create(db.engine, checkfirst=True)
        db.session.add(DictStosunkiRelacja(relacja_id=ALLIED, relacja_nazwa='Sojusznicze'))
        db.session.commit()
        land_war_clock = patch('game.liberation.game_now', side_effect=lambda: self.now)
        land_war_clock.start(); self.addCleanup(land_war_clock.stop)

    def texts(self, user_id):
        return [n.system_text or '' for n in db.session.query(GameNotification).filter_by(user_id=user_id)]


class AllyLiberationTests(LiberationFixture):
    def setUp(self):
        super().setUp()
        db.session.add(Stosunki(PANSTWO_ID=1, PANSTWO_ID2=3, relacja_id=ALLIED, stan_id=1))   # sojusz 1–3
        db.session.add(Region(region_id=5, panstwo_id=3, region_nazwa='Region sojusznika'))
        db.session.add(Miasto(miasto_id=20, panstwo_id=3, miasto_nazwa='Miasto sojusznika', region_id=5, czy_na_mapie='TAK', miasto_populacja=500))
        self.ally_base = MilitaryBase(panstwo_id=3, region_id=5, kind='land', level=1, garrison={}, map_x=80, map_y=0)
        db.session.add(self.ally_base); db.session.flush()
        # Państwo 2 (wróg gracza) okupuje miasto i bazę sojusznika oraz cały jego region.
        for kind, object_id in (('city', 20), ('base', self.ally_base.id)):
            db.session.add(Occupation(kind=kind, city_id=object_id if kind == 'city' else None, base_id=object_id if kind == 'base' else None,
                                      region_id=5, owner_id=3, occupier_id=2, status='ACTIVE', started_at=self.now))
            db.session.add(LandArmy(panstwo_id=2, request_id=key(), role='invasion', status='OCCUPYING', soldiers=100, armored=0, tanks=0,
                                    target_kind=kind, target_city_id=object_id if kind == 'city' else None,
                                    target_base_id=object_id if kind == 'base' else None, target_country_id=3, target_region_id=5,
                                    target_name='cel', starts_at=self.now, arrives_at=self.now))
        db.session.add(Occupation(kind='region', region_id=5, owner_id=3, occupier_id=2, status='ACTIVE', started_at=self.now))
        db.session.commit()

    def test_liberated_objects_return_to_ally_and_region_is_freed(self):
        city_army = self.arrive(self.invade('city', 20, soldiers=3000), [0.0, 0.0])
        self.assertEqual(city_army.status, 'WITHDRAWN', 'zwycięska armia wraca do bazy')
        db.session.expire_all()
        city = db.session.scalar(select(Occupation).where(Occupation.kind == 'city', Occupation.city_id == 20).order_by(Occupation.id.desc()))
        self.assertEqual(city.status, 'ENDED')
        self.assertIsNone(db.session.scalar(select(Occupation).where(Occupation.occupier_id == 1)), 'gracz niczego nie okupuje')
        self.assertEqual(db.session.get(Miasto, 20).panstwo_id, 3)
        region = db.session.scalar(select(Occupation).where(Occupation.kind == 'region', Occupation.region_id == 5))
        self.assertEqual(region.status, 'ACTIVE', 'okupant trzyma jeszcze bazę regionu')
        self.assertTrue(any('wyzwoliły' in text for text in self.texts(3)))
        # Odbita baza: ostatni obiekt — okupacja regionu kończy się, region w całości wraca do sojusznika.
        self.arrive(self.invade('base', self.ally_base.id, soldiers=1000), [0.0, 0.0])
        db.session.expire_all()
        self.assertEqual(db.session.get(Occupation, region.id).status, 'ENDED')
        base = db.session.get(MilitaryBase, self.ally_base.id)
        self.assertEqual(base.panstwo_id, 3)
        self.assertEqual(db.session.get(MilitaryBase, self.home.id).garrison['soldiers'], 5000 - round(3000 * (100 * 700 / 100) / (3000 * 300 / 100)) - round(1000 * (100 * 700 / 100) / (1000 * 300 / 100)))

    def test_requires_war_with_occupier_but_no_border(self):
        db.session.execute(update(Occupation).where(Occupation.kind == 'city').values(occupier_id=4))
        db.session.commit()
        with self.assertRaises(FinanceError) as error:
            self.invade('city', 20, soldiers=10)
        self.assertIn('wojny z okupantem', str(error.exception))
        db.session.execute(update(Occupation).where(Occupation.kind == 'city').values(occupier_id=2))
        db.session.commit()
        # Bez wspólnej granicy — np. z naszej bazy za granicą; wystarczy trasa lądowa do celu.
        with patch('game.road_projects.neighboring_countries', return_value=set()):
            self.assertTrue(self.invade('city', 20, soldiers=10))
        with patch('game.land_war.overland', return_value=False), self.assertRaises(FinanceError) as error:
            self.invade('city', 20, soldiers=10)
        self.assertIn('drogą lądową', str(error.exception))

    def test_ally_base_needs_no_intelligence(self):
        with patch('game.intelligence_service.known_ids', return_value=set()):
            self.assertTrue(self.invade('base', self.ally_base.id, soldiers=10))

    def test_no_battle_when_ally_already_holds_the_object(self):
        army_id = self.invade('city', 20, soldiers=3000)
        db.session.execute(update(Occupation).where(Occupation.kind == 'city').values(status='ENDED'))
        db.session.execute(update(LandArmy).where(LandArmy.panstwo_id == 2).values(status='WITHDRAWN'))
        db.session.commit()
        army = self.arrive(army_id, [0.0, 0.0])
        self.assertEqual((army.status, army.battle['result']), ('WITHDRAWN', 'TARGET_GONE'))


class RegionRestoreTests(LiberationFixture):
    def setUp(self):
        super().setUp()
        db.session.execute(update(Panstwo).where(Panstwo.PANSTWO_ID == 2).values(panstwo_PKB=10000000, panstwo_populacja=10000))
        db.session.execute(update(Region).where(Region.region_id == 2).values(region_ludnosc_pozamiejska=1000, region_powierzchnia=30))
        db.session.execute(update(Region).where(Region.region_id == 3).values(region_ludnosc_pozamiejska=500, region_powierzchnia=70))
        db.session.commit()

    def occupy(self, previous_owner, kind='ANNEX', extra_cities=()):
        record(db.session, 2, previous_owner, 2, kind, self.now - timedelta(days=100)); db.session.commit()
        self.arrive(self.invade(soldiers=3000), [0.0, 0.0])
        for city_id in (10, *extra_cities):
            self.arrive(self.invade('city', city_id, soldiers=100), [0.0, 0.0])
        row = db.session.scalar(select(Occupation).where(Occupation.kind == 'region'))
        land_war.decide_region(1, {'occupation_id': row.id, 'occupy': True})
        db.session.expire_all()
        return db.session.get(Occupation, row.id)

    def test_region_returns_to_existing_former_owner(self):
        row = self.occupy(3)
        option = next(o['restore'] for o in land_war.visible_occupations(db.session, 1) if o['id'] == row.id)
        self.assertEqual(option, {'countryId': 3, 'name': 'Państwo 3', 'resurrect': False})
        with self.assertRaises(FinanceError) as error:
            liberation.restore_region(1, {'occupation_id': row.id})
        self.assertIn('30 dniach', str(error.exception))
        self.now = row.started_at + timedelta(days=30)
        result = liberation.restore_region(1, {'occupation_id': row.id, 'country_id': 3})
        self.assertEqual(result, {'region_id': 2, 'country_id': 3, 'resurrected': False})
        db.session.expire_all()
        self.assertEqual((db.session.get(Region, 2).panstwo_id, db.session.get(Miasto, 10).panstwo_id), (3, 3))
        base = db.session.get(MilitaryBase, self.enemy.id)
        self.assertEqual((base.panstwo_id, base.garrison), (3, {}), 'baza przechodzi pusta')
        self.assertEqual(db.session.get(Occupation, row.id).status, 'ENDED')
        self.assertFalse(db.session.scalars(select(LandArmy).where(LandArmy.panstwo_id == 1, LandArmy.status == 'OCCUPYING')).all(), 'armie wracają do baz')
        self.assertEqual(db.session.scalar(select(Wojsko.liczba_baz_ladowych).where(Wojsko.panstwo_id == 2)), 1)
        # PKB per capita posiadacza (1 000) × ludność regionu (1 000 + 1 000 w Mieście B)
        gdp = dict(db.session.execute(select(Panstwo.PANSTWO_ID, Panstwo.panstwo_PKB).where(Panstwo.PANSTWO_ID.in_([2, 3]))).all())
        self.assertEqual(gdp[2], 8000000)
        self.assertEqual(gdp[3], 2000000)
        last = db.session.scalar(select(RegionTransfer).order_by(RegionTransfer.id.desc()))
        self.assertEqual((last.kind, last.from_country_id, last.to_country_id, last.actor_country_id), ('RESTORE', 2, 3, 1))
        self.assertTrue(any('przywróciło go nam' in text for text in self.texts(3)))

    def test_resurrection_of_a_country_without_player_hands_it_to_paga2(self):
        from game.paga2.models import Paga2Profile
        from game.finance_models import StateFinancialAccount
        from game.civic_models import TreasuryAdjustment
        db.session.add(SovereigntyLoss(panstwo_id=4, annexed_by=2, capital_region_id=2, lost_at=self.now - timedelta(days=100)))
        db.session.add(Miasto(miasto_id=13, panstwo_id=2, miasto_nazwa='Największe', region_id=2, czy_na_mapie='TAK', miasto_populacja=5000, miasto_typ_id=2))
        db.session.add(StateFinancialAccount(panstwo_id=4, reserve_balance=Decimal('500.00'), last_transaction_sequence=0))
        db.session.add(Wojsko(panstwo_id=4))
        db.session.execute(update(Panstwo).where(Panstwo.PANSTWO_ID == 4).values(panstwo_PKB=0, panstwo_populacja=0))
        db.session.commit()
        row = self.occupy(4, 'SOVEREIGNTY', extra_cities=(13,))
        self.assertTrue(next(o['restore'] for o in land_war.visible_occupations(db.session, 1) if o['id'] == row.id)['resurrect'])
        self.now = row.started_at + timedelta(days=30)
        result = liberation.restore_region(1, {'occupation_id': row.id})
        self.assertTrue(result['resurrected'])
        db.session.expire_all()
        self.assertIsNone(db.session.get(SovereigntyLoss, 4))
        self.assertEqual(db.session.get(Region, 2).panstwo_id, 4)
        self.assertEqual(db.session.get(Miasto, 13).miasto_typ_id, 1, 'stolica w największym mieście regionu')
        country = db.session.execute(select(Panstwo.panstwo_nazwa, Panstwo.panstwo_populacja, Panstwo.panstwo_PKB).where(Panstwo.PANSTWO_ID == 4)).one()
        self.assertEqual(country.panstwo_nazwa, 'Państwo 4')
        self.assertEqual(country.panstwo_populacja, 1000 + 1000 + 5000)
        self.assertEqual(country.panstwo_PKB, 7000000, 'PKB per capita anektującego (1 000) × ludność regionu')
        self.assertEqual(db.session.get(StateFinancialAccount, 4).reserve_balance, 0)
        self.assertEqual(db.session.scalar(select(TreasuryAdjustment.amount).where(TreasuryAdjustment.panstwo_id == 4)), Decimal('-500.00'))
        relation = lambda a, b: db.session.execute(select(Stosunki.relacja_id, Stosunki.stan_id).where(Stosunki.PANSTWO_ID == a, Stosunki.PANSTWO_ID2 == b)).one()
        self.assertEqual(relation(1, 4), (ALLIED, 1), 'sojusz z wyzwolicielem')
        self.assertEqual(relation(2, 4), (10, 8), 'wojna z anektującym')
        self.assertTrue(db.session.get(Paga2Profile, 4).autonomy_enabled)
        self.assertEqual(db.session.get(Wojsko, db.session.scalar(select(Wojsko.ID).where(Wojsko.panstwo_id == 4))).liczba_baz_ladowych, 1)

    def test_former_player_regains_the_country(self):
        from game.paga2.models import Paga2Profile
        db.session.add(SovereigntyLoss(panstwo_id=3, annexed_by=2, capital_region_id=2, lost_at=self.now))
        db.session.commit()
        self.assertEqual(liberation._government(db.session, 3), 'player')
        self.assertIsNone(db.session.get(Paga2Profile, 3))

    def test_region_with_the_holders_capital_can_only_be_annexed(self):
        db.session.execute(update(Miasto).where(Miasto.miasto_id == 10).values(miasto_typ_id=1)); db.session.commit()
        row = self.occupy(3)
        self.assertIsNone(next(o['restore'] for o in land_war.visible_occupations(db.session, 1) if o['id'] == row.id))
        self.now = row.started_at + timedelta(days=30)
        with self.assertRaises(FinanceError) as error:
            liberation.restore_region(1, {'occupation_id': row.id})
        self.assertIn('tylko anektować', str(error.exception))

    def test_no_restore_option_without_history_or_for_own_region(self):
        row = self.occupy(1)   # region należał kiedyś do gracza — zwykła aneksja (odzyskanie)
        self.assertIsNone(next(o['restore'] for o in land_war.visible_occupations(db.session, 1) if o['id'] == row.id))

    def test_annexation_records_history_and_later_restore_uses_it(self):
        row = self.occupy(3)
        self.now = row.started_at + timedelta(days=30)
        land_war.annex_region(1, {'occupation_id': row.id})
        db.session.expire_all()
        last = db.session.scalar(select(RegionTransfer).order_by(RegionTransfer.id.desc()))
        self.assertEqual((last.kind, last.from_country_id, last.to_country_id), ('ANNEX', 2, 1))
        self.assertEqual(former_owner(db.session, 2, 1), 2)


class SovereigntyHistoryTests(LiberationFixture):
    def test_every_region_of_a_defeated_country_is_recorded(self):
        from game.sovereignty import lose_sovereignty
        from sqlalchemy.orm import Session
        with Session(db.engine) as session, session.begin():
            lose_sovereignty(session, 2, 1, 2, None, self.now)
        rows = db.session.scalars(select(RegionTransfer).where(RegionTransfer.kind == 'SOVEREIGNTY')).all()
        self.assertEqual(sorted((r.region_id, r.from_country_id, r.to_country_id) for r in rows), [(2, 2, 1), (3, 2, 1)])


class EmptyTreasuryTests(LiberationFixture):
    def test_unspent_sector_funds_and_reserve_are_zeroed_by_adjustments(self):
        from sqlalchemy import text
        from game.finance_models import StateFinancialAccount
        from game.civic_models import TreasuryAdjustment
        db.session.execute(text("INSERT INTO game_state_budgets (id,panstwo_id,game_year,period) VALUES (7,4,2990,1)"))
        db.session.execute(text("INSERT INTO game_state_budget_allocations (id,budget_id,category_code,amount) VALUES (70,7,'research',100)"))
        db.session.execute(text("INSERT INTO game_state_budget_allocations (id,budget_id,category_code,amount) VALUES (71,7,'reserve',40)"))
        db.session.add(StateFinancialAccount(panstwo_id=4, reserve_balance=Decimal('40.00'), last_budget_id=7, last_transaction_sequence=0))
        db.session.commit()
        liberation._empty_treasury(db.session, 4); db.session.commit()
        rows = {(r.category, r.amount, r.budget_id) for r in db.session.scalars(select(TreasuryAdjustment).where(TreasuryAdjustment.panstwo_id == 4))}
        self.assertEqual(rows, {('research', Decimal('-100.00'), 7), ('reserve', Decimal('-40.00'), 7)})
        self.assertEqual(db.session.get(StateFinancialAccount, 4).reserve_balance, 0)
        from game.budget_transfers import sector_balances
        from game.finance_models import StateBudget
        balances = sector_balances(db.session, db.session.get(StateBudget, 7))
        self.assertEqual(sum(item['remaining'] for item in balances.values()), 0)
