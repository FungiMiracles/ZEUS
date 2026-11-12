"""Regresje odczytu listy, uszkodzeń obrony i wykrywania kopalń."""
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
from sqlalchemy import select
from extensions import db
from game.finance_service import FinanceError
from game.forum import notification_severity
from game.forum_models import GameNotification
from game.military_models import MissileDefense, MilitaryFlight
from game.military_service import military_budget
from game.military_flights import complete_flights, apply_structural_damage
from game.missile_defense import intercept
from game.commerce_models import Mine
from game.intelligence_service import known_ids
from game.military import visible_mines
import test_game_military_combat_defense as defense_tests
from test_game_military_flights import FlightFixture
from test_game_intelligence import IntelligenceFixture
from game_features_support import FeatureTestCase
from test_game_military import NOW


class DefenseRepairTests(defense_tests.DefenseTests.__bases__[0]):
    defense = defense_tests.DefenseTests.defense

    def test_repair_cost_limits_and_ownership(self):
        defense=self.defense();defense.health=70;db.session.commit()
        before=military_budget(db.session,1)[2]
        self.change('defense_repair',defense_id=defense.id,count=20)
        self.assertEqual(db.session.get(MissileDefense,defense.id).health,90)
        self.assertEqual(before-military_budget(db.session,1)[2],200000)
        for count in (0,11,True,-1):
            with self.assertRaises(FinanceError):self.change('defense_repair',defense_id=defense.id,count=count)
        defense=db.session.get(MissileDefense,defense.id);defense.panstwo_id=2;db.session.commit()
        with self.assertRaises(FinanceError):self.change('defense_repair',defense_id=defense.id,count=1)

    def test_disabled_defense_cannot_intercept_until_repaired(self):
        defense=self.defense();defense.health=0;db.session.commit()
        flight=SimpleNamespace(target_country_id=1,missiles=2)
        with patch('game.missile_defense.randbelow',return_value=0):
            self.assertEqual(intercept(db.session,flight,1,'region',1),2)
        self.assertEqual(defense.ammunition,100)
        db.session.commit()
        with self.assertRaises(FinanceError):self.change('defense_upgrade',defense_id=defense.id)
        self.change('defense_repair',defense_id=defense.id,count=1)
        with patch('game.missile_defense.randbelow',return_value=0):
            self.assertEqual(intercept(db.session,flight,1,'region',1),0)

    def test_repair_insufficient_budget_does_not_change_health(self):
        defense=self.defense();defense.health=50;db.session.commit();self.set_budget(0)
        with self.assertRaises(FinanceError):self.change('defense_repair',defense_id=defense.id,count=1)
        self.assertEqual(db.session.get(MissileDefense,defense.id).health,50)


class DefenseStrikeTests(FlightFixture):
    def enemy_defense(self):
        defense=MissileDefense(panstwo_id=2,region_id=2,target_kind='region',target_id=2,level=1,ammunition=100)
        db.session.add(defense);db.session.commit();return defense

    def test_strike_requires_intelligence_and_war_and_one_target(self):
        source=self.source();defense=self.enemy_defense()
        with self.assertRaises(FinanceError):self.launch(source,city_id=None,target_defense_id=defense.id)
        with patch('game.intelligence_service.known_ids',return_value={defense.id}):
            with self.assertRaises(FinanceError):self.launch(source,target_defense_id=defense.id)
        with patch('game.intelligence_service.known_ids',return_value={defense.id}),patch('game.military_service.enemies',return_value=[]):
            with self.assertRaises(FinanceError):self.launch(source,city_id=None,target_defense_id=defense.id)
        self.assertEqual(db.session.query(MilitaryFlight).count(),0)

    def test_missiles_damage_defense_once_and_preserve_interception(self):
        source=self.source();defense=self.enemy_defense()
        with patch('game.intelligence_service.known_ids',return_value={defense.id}),patch('game.military_geography.region_point',return_value=[100,0]):
            flight_id=self.launch(source,city_id=None,target_defense_id=defense.id,missiles=2)
        db.session.expire_all();flight=db.session.get(MilitaryFlight,flight_id)
        self.assertEqual(flight.target_kind,'defense');self.assertEqual(flight.target_defense_id,defense.id)
        with patch('game.missile_defense.randbelow',side_effect=[0,99]),patch('game.military_flights.randbelow',return_value=6):
            complete_flights(db.session,NOW+timedelta(hours=1));db.session.commit()
        self.assertEqual(db.session.get(MissileDefense,defense.id).health,91)
        self.assertEqual(db.session.get(MissileDefense,defense.id).ammunition,99)
        self.assertEqual(flight.damage['defenseHealthLost'],9)
        complete_flights(db.session,NOW+timedelta(hours=2));db.session.commit()
        self.assertEqual(db.session.get(MissileDefense,defense.id).health,91)

    def test_damage_range_and_cap_at_zero(self):
        defense=self.enemy_defense()
        flight=SimpleNamespace(target_kind='defense',target_defense_id=defense.id,target_country_id=2)
        for roll,loss in [(0,3),(6,9)]:
            defense.health=100
            with patch('game.military_flights.randbelow',return_value=roll):
                damage=apply_structural_damage(db.session,flight,None,1)
            self.assertEqual(damage['defenseHealthLost'],loss)
        defense.health=2
        with patch('game.military_flights.randbelow',return_value=6):
            damage=apply_structural_damage(db.session,flight,None,10)
        self.assertEqual(defense.health,0);self.assertTrue(damage['defenseDestroyed'])


class NotificationListTests(FeatureTestCase):
    def test_only_displayed_own_ids_read_and_csrf_required(self):
        notices=[GameNotification(user_id=1 if i<21 else 2,notification_type='SYSTEM',system_text='Atak rakietowy') for i in range(22)]
        db.session.add_all(notices);db.session.commit()
        path='/game/forum/powiadomienia/odczytaj'
        self.assertEqual(self.client.post(path,data={'ids':[str(notices[0].id)]}).status_code,400)
        feed=self.client.get('/game/forum/powiadomienia').json
        self.assertEqual(feed['unread_count'],21)
        ids=[str(item['id']) for item in feed['items']]
        result=self.client.post(path,data={'csrf_token':'token','ids':ids})
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(result.json['unread_count'],1)
        self.assertEqual(self.client.post(path,data={'csrf_token':'token','ids':[str(notices[-1].id)]}).json['unread_count'],1)
        db.session.refresh(notices[-1]);self.assertIsNone(notices[-1].read_at)
        result=self.client.post(path,data={'csrf_token':'token','ids':ids})
        self.assertEqual(result.json['unread_count'],1)

    def test_mark_all_read(self):
        db.session.add_all([GameNotification(user_id=1,notification_type='SYSTEM',system_text='x') for _ in range(30)]+[GameNotification(user_id=2,notification_type='SYSTEM',system_text='y')]);db.session.commit()
        result=self.client.post('/game/forum/powiadomienia/odczytaj',data={'csrf_token':'token','all':'1'})
        self.assertEqual(result.status_code,200);self.assertEqual(result.json['unread_count'],0)
        self.assertEqual(db.session.query(GameNotification).filter(GameNotification.read_at.is_(None)).count(),1)   # cudze bez zmian

    def test_notification_categories(self):
        for kind,text,expected in [('SYSTEM','Państwo przeprowadziło atak.','war'),('SYSTEM','Twoja baza została zniszczona.','war'),('INFRASTRUCTURE_COMPLETED','Gotowe','construction'),('SYSTEM','Zakończono budowę kopalni.','construction')]:
            self.assertEqual(notification_severity(SimpleNamespace(notification_type=kind,system_text=text)),expected)


class MineIntelligenceTests(IntelligenceFixture):
    def test_successful_mission_reveals_only_selected_region_mines(self):
        mines=[Mine(panstwo_id=2,region_id=region,resource='wegiel_kamienny',map_x=100,map_y=0,health=100,starts_at=NOW-timedelta(days=5),ready_at=NOW,extracted_at=NOW,request_id=str(region)) for region in (2,3)]
        db.session.add_all(mines);db.session.commit()
        self.assertEqual(known_ids(db.session,1,'mines'),set())
        mission=self.start('mines');self.finish()
        self.assertEqual(known_ids(db.session,1,'mines'),{mines[0].id})
        visible=visible_mines(1,True)
        self.assertEqual([mine['id'] for mine in visible],[mines[0].id])
