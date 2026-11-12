"""Usuwanie zniszczonych baz, straty garnizonu i jednostki bez portu."""
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
from sqlalchemy import select,text
from test_game_military_flights import FlightFixture
from test_game_military import NOW
from extensions import db
from models import Wojsko,Region
from game.military_models import MilitaryBase,MilitaryExpense,MilitaryVessel,MilitaryFlight,MissileDefense,MissileDefenseExpense
from game.intelligence_models import IntelligenceAgent,IntelligenceMission
from game.military_flights import complete_flights
from game.military_service import active_counts,create_order
from game.military_navy import change_vessel,settle_vessels
from game.forum_models import GameNotification
from game.finance_service import FinanceError


class DestructionTests(FlightFixture):
    def setUp(self):
        super().setUp()
        self.target=MilitaryBase(panstwo_id=2,region_id=2,kind='land',level=1,garrison={'soldiers':100,'tanks':4},map_x=100,map_y=0,health=5,name='Fort Testowy')
        db.session.add(self.target)
        self.enemy_army=Wojsko(panstwo_id=2,liczba_baz_ladowych=1,liczba_baz_morskich=2,wojska_ladowe_ilosc=500,wojska_morskie_ilosc=500,czolgi_ilosc=20,okrety_wojenne_ilosc=3,okrety_podwodne_ilosc=1,rakiety_krotkiego_zasiegu=20)
        db.session.add(self.enemy_army);agent=IntelligenceAgent(panstwo_id=1,level=1);db.session.add(agent);db.session.flush()
        db.session.add(IntelligenceMission(panstwo_id=1,agent_id=agent.id,region_id=2,target_country_id=2,region_name='Cel',kind='bases',starts_at=NOW-timedelta(days=7),ends_at=NOW,completed_at=NOW,success=True,report={'base_ids':[self.target.id]}))
        db.session.execute(text("INSERT INTO game_state_budgets (id,panstwo_id,game_year,period) VALUES (2,2,2990,1)"))
        db.session.execute(text("INSERT INTO game_state_budget_allocations (id,budget_id,category_code,amount) VALUES (2,2,'armed_forces',100000000000)"))
        db.session.commit()

    def impact(self):
        source=self.source();flight=self.launch(source,city_id=None,target_base_id=self.target.id,missiles=2)
        with patch('game.military_flights.randbelow',return_value=0):complete_flights(db.session,NOW+timedelta(hours=1))
        db.session.commit();db.session.expire_all();return flight

    def test_base_removed_garrison_lost_history_preserved_and_notification_once(self):
        target_id=self.target.id
        expense=MilitaryExpense(panstwo_id=2,budget_id=2,base_id=target_id,level=2,amount=1000000000);db.session.add(expense)
        defense=MissileDefense(panstwo_id=2,region_id=2,target_kind='base',target_id=target_id,level=1,ammunition=0);db.session.add(defense);db.session.flush()
        defense_id=defense.id;defexpense=MissileDefenseExpense(panstwo_id=2,budget_id=2,defense_id=defense_id,amount=100000000);db.session.add(defexpense);db.session.commit()
        flight_id=self.impact()
        self.assertIsNone(db.session.get(MilitaryBase,target_id))
        self.assertEqual(db.session.scalar(select(Wojsko.wojska_ladowe_ilosc).where(Wojsko.panstwo_id==2)),400)
        self.assertEqual(db.session.scalar(select(Wojsko.czolgi_ilosc).where(Wojsko.panstwo_id==2)),16)
        self.assertEqual(db.session.scalar(select(Wojsko.liczba_baz_ladowych).where(Wojsko.panstwo_id==2)),0)
        self.assertIsNone(db.session.get(MilitaryExpense,expense.id).base_id)
        self.assertIsNone(db.session.get(MissileDefense,defense_id))
        self.assertIsNone(db.session.get(MissileDefenseExpense,defexpense.id).defense_id)
        flight=db.session.get(MilitaryFlight,flight_id);self.assertTrue(flight.damage['baseDestroyed']);self.assertEqual(flight.target_kind,'base');self.assertIsNone(flight.target_base_id)
        complete_flights(db.session,NOW+timedelta(hours=2));db.session.commit()
        notices=[n for n in db.session.query(GameNotification) if n.user_id==2 and 'Twoja baza' in n.system_text]
        self.assertEqual(len(notices),1)

    def test_surviving_vessel_without_base_can_fire_and_return_elsewhere(self):
        self.target.kind='naval';self.target.garrison={'warships':2,'submarines':1,'soldiers':100}
        destination=MilitaryBase(panstwo_id=2,region_id=2,kind='naval',level=2,garrison={},map_x=200,map_y=0)
        vessel=MilitaryVessel(panstwo_id=2,base_id=self.target.id,region_id=2,kind='warships',name='Ocalały',status='stationed',source_x=100,source_y=0,target_x=100,target_y=0,starts_at=NOW,arrives_at=NOW)
        db.session.add_all([destination,vessel]);db.session.commit();vessel_id=vessel.id;target_id=self.target.id
        self.impact();self.assertIsNone(db.session.get(MilitaryBase,target_id))
        vessel=db.session.get(MilitaryVessel,vessel_id);self.assertIsNone(vessel.base_id);self.assertEqual(vessel.status,'stationed')
        self.assertEqual(db.session.scalar(select(Wojsko.okrety_wojenne_ilosc).where(Wojsko.panstwo_id==2)),2)
        self.assertEqual(db.session.scalar(select(Wojsko.okrety_podwodne_ilosc).where(Wojsko.panstwo_id==2)),0)
        self.assertEqual(active_counts([],db.session,2)['okrety_wojenne_ilosc'],1)
        with patch('game.military_service._country_for_user',return_value=SimpleNamespace(PANSTWO_ID=2)),patch('game.military_flights.region_point',return_value=[50,0]):
            flight_id=create_order(2,{'kind':'naval','vessel_id':vessel_id,'region_id':1,'missile_type':'short','missiles':1,'infrastructure':'road'})
        self.assertIsNone(db.session.get(MilitaryFlight,flight_id).source_base_id)
        change_vessel(db.session,2,'return_vessel',{'vessel_id':vessel_id,'base_id':destination.id},NOW)
        settle_vessels(db.session,NOW+timedelta(hours=2),2);db.session.commit()
        self.assertEqual(db.session.get(MilitaryVessel,vessel_id).base_id,destination.id)
        self.assertEqual(db.session.get(MilitaryBase,destination.id).garrison['warships'],1)

    def test_rollback_restores_base_and_inventory(self):
        source=self.source();target_id=self.target.id;flight_id=self.launch(source,city_id=None,target_base_id=target_id,missiles=2)
        with patch('game.military_flights.randbelow',return_value=0):complete_flights(db.session,NOW+timedelta(hours=1))
        db.session.rollback()
        self.assertEqual(db.session.get(MilitaryBase,target_id).health,5)
        self.assertEqual(db.session.scalar(select(Wojsko.wojska_ladowe_ilosc).where(Wojsko.panstwo_id==2)),500)
        self.assertEqual(db.session.query(GameNotification).count(),0)

    def test_unknown_base_cannot_be_attacked_by_guessing_id(self):
        db.session.query(IntelligenceMission).delete();db.session.commit()
        with self.assertRaises(FinanceError):self.launch(self.source(),city_id=None,target_base_id=self.target.id)

    def test_pending_second_hit_does_not_damage_region_after_target_deleted(self):
        db.session.get(Region,2).region_stan_infra_drogowej=50;db.session.commit();source=self.source();target_id=self.target.id
        first=self.launch(source,city_id=None,target_base_id=target_id,missiles=2,infrastructure='road')
        second=self.launch(source,city_id=None,target_base_id=target_id,missiles=2,infrastructure='road')
        # Orders accepted by pre-migration workers retain their actual target.
        db.session.get(MilitaryFlight,first).target_kind='region';db.session.get(MilitaryFlight,second).target_kind='region';db.session.commit()
        with patch('game.military_flights.randbelow',return_value=0):complete_flights(db.session,NOW+timedelta(hours=1))
        db.session.commit()
        self.assertIsNone(db.session.get(MilitaryBase,target_id))
        self.assertEqual(db.session.get(Region,2).region_stan_infra_drogowej,50)
        notices=[n for n in db.session.query(GameNotification) if n.user_id==2 and 'Twoja baza' in n.system_text]
        self.assertEqual(len(notices),1)
