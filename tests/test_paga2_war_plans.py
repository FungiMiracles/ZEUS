"""Reforma wojny, wywiadu i dyplomacji PAGA2 (21 Nov 2026) — scenariusze akceptacyjne 1–15 ze specyfikacji administratora."""
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace as NS
from unittest.mock import patch
from extensions import db
from game.paga2 import war_plans as wp
from game_features_support import FeatureTestCase

NOW = datetime(3002, 1, 1, 12, 0)


def areas(combat=1.0, reach=1.0, finance=1.0, supply=1.0, intel=1.0):
    return {k: {'have': v, 'need': 1, 'ratio': v} for k, v in dict(combat=combat, reach=reach, finance=finance, supply=supply, intel=intel).items()}


TARGET = [{'kind': 'base', 'id': 5, 'region': '9', 'label': 'baza #5'}]


def ctx(plans, *, relation='wrogie', at_war=(), allies=(), mode='CYCLIC'):
    return NS(country_id=1, now=NOW, mode=mode, errors=[], traits={'predictability': 50},
              situation={'relations': {p.enemy_id: {'relation': relation, 'state': 'wojnakinetyczna' if p.enemy_id in at_war else 'pokoj'} for p in plans},
                         'at_war': list(at_war), 'allies': list(allies)}, _war_plans=list(plans))


def plan(stage='INTELLIGENCE', goal_type='conquer_region', **extra):
    values = dict(id=1, country_id=1, enemy_id=2, kind='OFFENSIVE', ally_id=None, stage=stage, reason='test', goal={'type': goal_type, 'region_id': 9, 'label': 'cel'},
                  readiness=0.0, stale_cycles=0, idle_cycles=0, intel_attempts=0, operations=0, assessment={}, history=[], power_at_start=None,
                  declared_at=None, first_operation_pending=False)
    values.update(extra)
    return NS(**values)


def run_review(p, result, **kw):
    """Przegląd planu z podstawioną oceną gotowości; zwraca zapisane zmiany planu."""
    saved = {}
    c = ctx([p], **kw)
    with patch.object(wp, 'active_plans', return_value=[p]), patch.object(wp, 'assess', return_value=result), \
         patch.object(wp, 'save', side_effect=lambda plan_id, **changes: saved.update(changes)), \
         patch.object(wp, 'goal_done', return_value=False), patch('game.sovereignty.lost', return_value=None):
        wp.review(c, None, {}, {})
    return saved


class WarPlanRules(unittest.TestCase):
    def test_01_imperialist_with_40_percent_cannot_declare(self):
        blockers = wp.declare_blockers(areas(combat=.4), targets=TARGET, intel_fresh=True, relation='wrogie', grace_until=None, now=NOW)
        self.assertTrue(blockers and 'potencjał bojowy: 40%' in blockers[0])
        saved = run_review(plan('INTELLIGENCE'), (TARGET, areas(combat=.4), [], True, {'own': 10, 'enemy': 30}))
        self.assertEqual(saved['stage'], 'PREPARATION')                     # przygotowania zamiast wojny
        saved = run_review(plan('PREPARATION', stale_cycles=wp.MAX_STALE_CYCLES - 1, readiness=.4), (TARGET, areas(combat=.4), [], True, {}))
        self.assertEqual(saved['stage'], 'ABANDONED')                       # bez postępu — porzucenie

    def test_02_85_percent_with_intel_can_be_considered(self):
        self.assertEqual(wp.declare_blockers(areas(combat=.85, finance=.9), targets=TARGET, intel_fresh=True, relation='wrogie', grace_until=None, now=NOW), [])
        saved = run_review(plan('PREPARATION'), (TARGET, areas(combat=.85), [], True, {}))
        self.assertEqual(saved['stage'], 'READY')
        # 80% w każdym obszarze — duże finanse nie rekompensują braku sił
        self.assertTrue(wp.declare_blockers(areas(combat=.1, finance=1.0), targets=TARGET, intel_fresh=True, relation='wrogie', grace_until=None, now=NOW))

    def test_03_missing_intel_starts_reconnaissance(self):
        saved = run_review(plan('PLANNING'), (TARGET, areas(intel=0), [], False, {}))
        self.assertEqual(saved['stage'], 'INTELLIGENCE')
        self.assertIn('rozpoznania', ' '.join(wp.declare_blockers(areas(intel=0), targets=TARGET, intel_fresh=False, relation='wrogie', grace_until=None, now=NOW)))
        saved = run_review(plan('INTELLIGENCE', intel_attempts=wp.MAX_INTEL_ATTEMPTS), (TARGET, areas(intel=0), [], False, {}))
        self.assertEqual(saved['stage'], 'ABANDONED')                       # bez nieskończonych prób

    def test_04_rejected_first_attack_leads_to_alternatives(self):
        from game.paga2 import war
        p = plan('ACTIVE', first_operation_pending=True)
        c = ctx([p])
        c._plan_state = {1: {'plan': p, 'stage': 'ACTIVE', 'targets': TARGET}}
        strike = NS(action='STRIKE_BASE', target=2, payload={'target_base_id': 5, 'group': 'war:strike:2'}, base=0.0, notes=[])
        other = NS(action='STRIKE_POWER', target=2, payload={'target_power_id': 7, 'group': 'war:strike:2'}, base=0.0, notes=[])
        war.plan_operation_bonus(c, [strike, other])
        self.assertTrue(strike.payload['required'] and other.payload['required'])          # najlepsza wykonalna z grupy pierwszej operacji
        self.assertEqual(strike.payload['group'], 'war:first:1')
        self.assertGreater(strike.base, other.base)                                         # cel planu ma pierwszeństwo
        stage, idle, text = wp.review_war(idle=2, operations_since=0, goal_done=False, power_now=10, power_start=10, at_war=True)
        self.assertEqual((stage, idle), ('ACTIVE', 3)); self.assertIn('ponowna analiza', text)
        stage, idle, _ = wp.review_war(idle=5, operations_since=0, goal_done=False, power_now=10, power_start=10, at_war=True)
        self.assertEqual(stage, 'NEGOTIATION')
        self.assertEqual(wp.review_war(idle=5, operations_since=1, goal_done=False, power_now=10, power_start=10, at_war=True)[1], 0)

    def test_05_ally_request_with_50_percent_is_refused(self):
        reasons = wp.join_blockers(areas(combat=.5), requester_relation='sojusznicze', enemy_relation='wrogie', threat=70, hostile_from=1, targets=TARGET, intel_fresh=True)
        self.assertTrue(any(r.startswith('A.') for r in reasons))

    def test_06_ally_request_against_friendly_country_is_refused(self):
        reasons = wp.join_blockers(areas(), requester_relation='sojusznicze', enemy_relation='przyjazne', threat=20, hostile_from=0, targets=TARGET, intel_fresh=True)
        self.assertTrue(any(r.startswith('C.') for r in reasons))
        self.assertEqual(wp.join_blockers(areas(), requester_relation='przyjazne', enemy_relation='zle', threat=20, hostile_from=0, targets=TARGET, intel_fresh=True), [])
        self.assertTrue(wp.join_blockers(areas(), requester_relation='dobre', enemy_relation='wrogie', threat=80, hostile_from=2, targets=TARGET, intel_fresh=True))   # B

    def test_07_goal_achieved_leads_to_peace_evaluation(self):
        stage, _, text = wp.review_war(idle=0, operations_since=1, goal_done=True, power_now=10, power_start=10, at_war=True)
        self.assertEqual(stage, 'NEGOTIATION'); self.assertIn('Cel główny osiągnięty', text)
        value, notes = wp.peace_adjustment(goal_done=True, near_goal=False, superiority=True, occupied_recoverable=False, idle=0, losses=False)
        self.assertGreater(value, 0)
        value, _ = wp.peace_adjustment(goal_done=False, near_goal=True, superiority=True, occupied_recoverable=True, idle=0, losses=False)
        self.assertLess(value, 0)                                                          # blisko celu i przewaga — bez pochopnego pokoju

    def test_08_heavy_losses_change_strategy(self):
        stage, _, text = wp.review_war(idle=0, operations_since=1, goal_done=False, power_now=30, power_start=100, at_war=True)
        self.assertEqual(stage, 'NEGOTIATION'); self.assertIn('Straty', text)
        self.assertGreater(wp.peace_adjustment(goal_done=False, near_goal=False, superiority=False, occupied_recoverable=False, idle=0, losses=True)[0], 0)

    def test_09_relation_change_lock(self):
        until = wp.lock_until([(2, NOW - timedelta(days=30))], [], 2, NOW)
        self.assertEqual(until, NOW + timedelta(days=60))
        self.assertIsNone(wp.lock_until([(2, NOW - timedelta(days=30))], [], 3, NOW))      # inne państwo — bez blokady
        self.assertIsNone(wp.lock_until([(2, NOW - timedelta(days=95))], [], 2, NOW))

    def test_10_attack_lifts_relation_lock(self):
        events = [('BOMBARDMENT', 2, NOW - timedelta(days=5), [2, 1])]
        self.assertIsNone(wp.lock_until([(2, NOW - timedelta(days=30))], events, 2, NOW))
        old = [('BOMBARDMENT', 2, NOW - timedelta(days=40), [2, 1])]                       # atak sprzed zmiany nie znosi karencji
        self.assertIsNotNone(wp.lock_until([(2, NOW - timedelta(days=30))], old, 2, NOW))

    def test_11_no_new_offensive_war_60_days_after_peace(self):
        peace = {2: NOW - timedelta(days=60)}
        until = wp.grace_until(peace, [], 2, NOW)
        self.assertEqual(until, NOW + timedelta(days=120))
        self.assertTrue(wp.declare_blockers(areas(), targets=TARGET, intel_fresh=True, relation='wrogie', grace_until=until, now=NOW))
        self.assertIsNone(wp.grace_until(peace, [('LAND_ATTACK', 2, NOW - timedelta(days=10), [2, 1])], 2, NOW))   # wyjątek: nowy atak
        self.assertIsNone(wp.grace_until({2: NOW - timedelta(days=181)}, [], 2, NOW))

    def test_13_defence_is_not_blocked_by_offensive_readiness(self):
        from game.paga2 import war
        self.assertIsNone(war.check(NS(), NS(action='RECAPTURE', payload={'target_kind': 'city'})))
        self.assertIsNone(war.check(NS(), NS(action='STRIKE_BASE', payload={})))
        self.assertIsNotNone(war.check(NS(), NS(action='WAR', payload={'blockers': ['Gotowość poniżej 80%']})))
        # plan bez wypowiedzenia wojny przechodzi do realizacji, gdy przeciwnik sam zaatakował
        saved = run_review(plan('PREPARATION'), (TARGET, areas(combat=.3), [], True, {'own': 5}), at_war=(2,))
        self.assertEqual(saved['stage'], 'ACTIVE')

    def test_14_destroyed_target_before_declaration(self):
        saved = run_review(plan('READY', goal_type='destroy_bases'), ([], areas(), [], True, {}))
        self.assertEqual(saved['stage'], 'ABANDONED')
        self.assertIn('Brak konkretnego', ' '.join(wp.declare_blockers(areas(), targets=[], intel_fresh=True, relation='wrogie', grace_until=None, now=NOW)))

    def test_15_clock_speed_does_not_move_entenda_deadlines(self):
        from engine.paga2_scheduler import cycle_minutes
        control = NS(interval_minutes=60)
        self.assertEqual((cycle_minutes(control, 12), cycle_minutes(control, 24), cycle_minutes(control, 36)), (60.0, 30.0, 20.0))
        change = NOW - timedelta(days=30)
        for _speed in (6, 12, 24, 36):        # terminy liczone wyłącznie w czasie Entendy — niezależne od tempa zegara
            self.assertEqual(wp.lock_until([(2, change)], [], 2, NOW), change + timedelta(days=wp.RELATION_LOCK_DAYS))
            self.assertEqual(wp.grace_until({2: change}, [], 2, NOW), change + timedelta(days=wp.OFFENSIVE_GRACE_DAYS))


class WarPlanPersistence(FeatureTestCase):
    def setUp(self):
        super().setUp()
        from game.paga2.models import Paga2WarPlan
        Paga2WarPlan.__table__.create(db.engine, checkfirst=True)

    def test_12_plan_survives_restart_and_is_not_duplicated(self):
        c = NS(country_id=1, now=NOW, _war_plans=None)
        first = wp.create(c, 2, kind='OFFENSIVE', reason='test', goal={'type': 'conquer_region', 'region_id': 1, 'label': 'cel'}, stage='INTELLIGENCE')
        self.assertIsNotNone(first)
        self.assertIsNone(wp.create(c, 2, kind='OFFENSIVE', reason='drugi', goal={'type': 'conquer_region'}, stage='INTELLIGENCE'))   # jeden plan na parę
        db.session.remove()                                                                  # „restart”: nowa sesja czyta stan z bazy
        fresh = NS(country_id=1, now=NOW, _war_plans=None)
        rows = wp.active_plans(fresh)
        self.assertEqual([(r.id, r.stage, r.enemy_id) for r in rows], [(first, 'INTELLIGENCE', 2)])
        wp.save(first, stage='ABANDONED', note='koniec', now=NOW)
        self.assertIsNotNone(wp.create(c, 2, kind='OFFENSIVE', reason='nowy', goal={'type': 'conquer_region'}, stage='INTELLIGENCE'))   # po zakończeniu można zacząć nowy
        view = wp.admin_view(db.session, 1, {2: 'Państwo 2'})
        self.assertEqual(view[-1]['endReason'], None); self.assertEqual(view[-1]['stage'], 'ABANDONED')


if __name__ == '__main__':
    unittest.main()
