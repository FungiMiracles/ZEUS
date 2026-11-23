"""16 Nov 2026: rekrutacja żołnierzy do służby czynnej, limit 30% ludności 18–64, opłata PKB per capita × 0,01
za żołnierza na okres (raz na okres, od następnego okresu po rekrutacji), zwolnienia z braku środków i na życzenie."""
import unittest
from datetime import datetime
from types import SimpleNamespace as NS
from unittest.mock import patch
from flask import template_rendered
from sqlalchemy import text
from extensions import db
from models import Panstwo, Wojsko
from game.military_models import MilitaryBase, MilitaryMaintenance
from game.military_service import reconcile_maintenance
from game.military_recruitment import change, summary, soldier_rate
from game.forum_models import GameNotification
from game.finance_service import FinanceError
from test_game_military import MilitaryFixture, NOW


class RecruitmentTests(MilitaryFixture):
    def setUp(self):
        super().setUp()
        from game.population_structure import PopulationStructure
        PopulationStructure.__table__.create(db.engine, checkfirst=True)
        db.session.execute(db.update(Panstwo).where(Panstwo.PANSTWO_ID == 1).values(panstwo_PKB=1_000_000_000_000, panstwo_populacja=1_000_000))   # PKB per capita 1 mln → 10 000 ROI za żołnierza
        db.session.add(PopulationStructure(panstwo_id=1, children=20, working=60, seniors=20, actor='test'))   # 18–64: 600 000 → limit 180 000
        db.session.commit()
        clock = patch('game.military_recruitment.game_now', return_value=NOW); clock.start(); self.addCleanup(clock.stop)

    def army(self):
        db.session.expire_all()
        return db.session.scalar(db.select(Wojsko).where(Wojsko.panstwo_id == 1))

    def soldiers(self):
        army = self.army()
        return army.wojska_ladowe_ilosc, army.wojska_morskie_ilosc, army.wojska_powietrzne_ilosc

    def act(self, action, branch, count):
        result = change(db.session, 1, action, branch, count); db.session.commit(); return result

    def test_rate_limit_and_recruitment_into_active_service(self):
        self.assertEqual(soldier_rate(db.session, 1), 10000)
        data = summary(db.session, 1)
        self.assertEqual((data['total'], data['limit']), (150000, 180000))
        self.act('recruit', 'naval', 30000)
        self.assertEqual(self.soldiers(), (100000, 50000, 30000))
        with self.assertRaises(FinanceError) as error:
            self.act('recruit', 'air', 1)
        self.assertIn('30% ludności w wieku 18–64', str(error.exception))
        self.assertIn('Można jeszcze zrekrutować 0', str(error.exception))
        db.session.rollback()
        with self.assertRaises(FinanceError):change(db.session, 1, 'recruit', 'space', 5)
        with self.assertRaises(FinanceError):change(db.session, 1, 'recruit', 'land', 0)
        with self.assertRaises(FinanceError):change(db.session, 1, 'recruit', 'land', '5')

    def test_no_age_structure_blocks_recruitment(self):
        from game.population_structure import PopulationStructure
        db.session.delete(db.session.get(PopulationStructure, 1)); db.session.commit()
        with self.assertRaises(FinanceError) as error:
            change(db.session, 1, 'recruit', 'land', 1)
        self.assertIn('strukturę wieku', str(error.exception))

    def test_dismissal_only_from_reserve(self):
        base = self.base(); self.change('garrison', base_id=base.id, garrison={'soldiers': 10000})
        data = summary(db.session, 1)
        self.assertEqual(data['branches']['land'], {'label': 'Wojska lądowe', 'total': 100000, 'assigned': 10000, 'reserve': 90000})
        with self.assertRaises(FinanceError) as error:
            change(db.session, 1, 'dismiss', 'land', 90001)
        self.assertIn('w rezerwie jest 90 000', str(error.exception))
        db.session.rollback()
        self.act('dismiss', 'land', 90000)
        self.assertEqual(self.soldiers()[0], 10000)
        self.assertEqual(db.session.get(MilitaryBase, base.id).garrison['soldiers'], 10000)

    def test_fee_assessed_once_per_period_recruit_free_until_next_period(self):
        reconcile_maintenance(db.session, 1, NOW); db.session.commit()
        record = db.session.query(MilitaryMaintenance).one()
        self.assertEqual((record.soldier_count, record.soldier_fee, record.amount), (150000, 1_500_000_000, 1_500_000_000))
        self.act('recruit', 'land', 30000)              # rekrutacja w trakcie okresu — bez opłaty w tym okresie
        self.act('dismiss', 'air', 10000)               # zwolnienie — koszt maleje dopiero od następnego okresu
        reconcile_maintenance(db.session, 1, NOW); db.session.commit()
        db.session.expire_all()
        record = db.session.query(MilitaryMaintenance).one()
        self.assertEqual((record.soldier_count, record.soldier_fee), (150000, 1_500_000_000))
        self.assertEqual(summary(db.session, 1, now=NOW)['nextFee'], '1700000000.00')
        self.set_budget(1_000_000_000_000, period=2)
        reconcile_maintenance(db.session, 1, datetime(2990, 7, 1)); db.session.commit()
        db.session.expire_all()
        second = db.session.query(MilitaryMaintenance).filter_by(period=2).one()
        self.assertEqual((second.soldier_count, second.soldier_fee), (170000, 1_700_000_000))

    def test_recruits_before_first_assessment_are_free_until_next_period(self):
        # 16 Nov 2026: opłata naliczana dopiero po rekrutacji nie obejmuje rekrutów z bieżącego okresu.
        self.act('recruit', 'land', 30000)
        self.act('dismiss', 'land', 10000)              # zwolnienie przed naliczeniem — najpierw rekruci z tego okresu
        reconcile_maintenance(db.session, 1, NOW); db.session.commit(); db.session.expire_all()
        record = db.session.query(MilitaryMaintenance).one()
        self.assertEqual((record.soldiers_recruited, record.soldier_count, record.soldier_fee), (20000, 150000, 1_500_000_000))
        self.set_budget(1_000_000_000_000, period=2)
        reconcile_maintenance(db.session, 1, datetime(2990, 7, 1)); db.session.commit(); db.session.expire_all()
        second = db.session.query(MilitaryMaintenance).filter_by(period=2).one()
        self.assertEqual((second.soldiers_recruited, second.soldier_count), (0, 170000))

    def test_unaffordable_soldiers_dismissed_reserve_first_then_garrisons_and_notified(self):
        base = self.base(); self.change('garrison', base_id=base.id, garrison={'soldiers': 10000})
        db.session.query(MilitaryMaintenance).delete(); db.session.commit()      # opłata jeszcze nienaliczona w tym okresie
        self.set_budget(500_000_000)                    # stać na 50 000 żołnierzy
        reconcile_maintenance(db.session, 1, NOW); db.session.commit()
        land, naval, air = self.soldiers()
        self.assertEqual(land + naval + air, 50000)
        self.assertEqual(db.session.get(MilitaryBase, base.id).garrison['soldiers'], 10000)   # rezerwa wystarczyła
        record = db.session.query(MilitaryMaintenance).one()
        self.assertEqual((record.soldier_count, record.soldier_fee), (50000, 500_000_000))
        notice = db.session.query(GameNotification).one()
        self.assertIn('Zwolniono 100 000 żołnierzy', notice.system_text)
        db.session.query(MilitaryMaintenance).delete(); db.session.commit()
        self.set_budget(30_000_000)                     # stać na 3 000 — brak rezerwy, cięcie garnizonu
        reconcile_maintenance(db.session, 1, NOW); db.session.commit()
        self.assertEqual(sum(self.soldiers()), 3000)
        self.assertLessEqual(db.session.get(MilitaryBase, base.id).garrison['soldiers'], 3000)

    def test_no_assessment_and_no_dismissal_without_approved_budget(self):
        db.session.execute(text('DELETE FROM game_state_budget_allocations')); db.session.execute(text('DELETE FROM game_state_budgets')); db.session.commit()
        reconcile_maintenance(db.session, 1, NOW); db.session.commit()
        self.assertEqual(sum(self.soldiers()), 150000)
        # 23 Nov 2026: bez zatwierdzonego budżetu przeliczenie niczego nie nalicza ani nie zapisuje (wcześniej pusty rekord)
        record = db.session.query(MilitaryMaintenance).one_or_none()
        self.assertTrue(record is None or (record.soldiers_assessed_at is None and record.soldier_fee == 0))

    def test_endpoint_page_and_screens_show_fee(self):
        self.login(1)
        bad = self.client.post('/game/sily-zbrojne/rekrutacja', json={'action': 'recruit', 'branch': 'land', 'count': 5})
        self.assertEqual(bad.status_code, 403)
        headers = {'X-CSRF-Token': 'token'}
        response = self.client.post('/game/sily-zbrojne/rekrutacja', json={'action': 'recruit', 'branch': 'land', 'count': 5}, headers=headers)
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['recruitment']['branches']['land']['total'], 100005)
        self.assertEqual(self.client.post('/game/sily-zbrojne/rekrutacja', json={'action': 'dismiss', 'branch': 'land', 'count': 10**9}, headers=headers).status_code, 400)
        page = self.client.get('/game/sily-zbrojne').get_data(as_text=True)
        self.assertIn('Służba czynna', page); self.assertIn('data-recruit="land"', page); self.assertIn('10000,00 ROI', page)
        contexts = []
        with template_rendered.connected_to(lambda sender, template, context, **kw: contexts.append(context), self.app):
            defense = self.client.get('/game/obrona-panstwa')
        self.assertEqual(defense.status_code, 200)
        self.assertIn('Opłata za żołnierzy · bieżący okres', defense.get_data(as_text=True))
        self.assertEqual(contexts[-1]['soldier_fee']['total'], 150005)


class Paga2RecruitmentTests(unittest.TestCase):
    def options(self, recruitment, level='peace', budget=1e10, militarism=50):
        from game.paga2 import defense
        ctx = NS(traits={'militarism': militarism}, situation={'level': level})
        forces = NS(recruitment=recruitment, has_budget=True, budget_total=budget, budget_available=budget)
        return defense.recruitment_options(ctx, forces)

    def data(self, reserve=0, total=0, rate='10000', limit=1_000_000):
        return {'rate': rate, 'total': total, 'limit': limit,
                'branches': {b: {'label': b, 'reserve': reserve, 'total': total, 'assigned': 0} for b in ('land', 'naval', 'air')}}

    def test_recruits_reserve_for_garrisons_within_budget_share_and_limit(self):
        [option] = self.options(self.data())
        self.assertEqual(option.action, 'RECRUIT'); self.assertEqual(option.payload['count'], 10000)
        self.assertEqual(self.options(self.data(), budget=1e6), [])                    # opłata przekroczyłaby budżet
        self.assertEqual(self.options(self.data(limit=0)), [])                          # limit 30% ludności
        [war] = self.options(self.data(), level='war')
        self.assertGreater(war.payload['count'], option.payload['count'])

    def test_dismisses_reserve_when_fee_exceeds_budget_share(self):
        [option] = self.options(self.data(reserve=50000, total=150000), budget=1e9)
        self.assertEqual(option.action, 'DISMISS'); self.assertEqual(option.payload['action'], 'dismiss')
        self.assertLessEqual(option.payload['count'], 50000)


if __name__ == '__main__':
    unittest.main()
