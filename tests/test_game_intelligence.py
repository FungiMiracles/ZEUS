"""Wywiad, budżet służb, raporty i ograniczenia ujawniania danych."""
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4
from unittest.mock import patch
from sqlalchemy import select,text
from test_game_military import MilitaryFixture,NOW
from extensions import db
from models import Region,Wojsko,DictZasob,RegionZasob
from game.intelligence import intelligence_bp
from game.intelligence_models import IntelligenceAgent,IntelligenceMission,CounterIntelligence,IntelligenceExpense
from game.intelligence_service import operate,complete_missions,intelligence_budget,known_ids
from game.military_models import MilitaryBase,MissileDefense
from game.military import visible_base_data,visible_defenses
from game.forum_models import GameNotification
from game.finance_service import FinanceError


class IntelligenceFixture(MilitaryFixture):
    def setUp(self):
        super().setUp();self.app.register_blueprint(intelligence_bp)
        db.session.execute(text("INSERT INTO game_state_budget_allocations (id,budget_id,category_code,amount) VALUES (2,1,'security_services',100000000000)"));db.session.commit()
        clock=patch('game.intelligence_service.game_now',return_value=NOW);clock.start();self.addCleanup(clock.stop)
        self.enemy=MilitaryBase(panstwo_id=2,region_id=2,kind='land',level=1,garrison={'soldiers':1234},map_x=100,map_y=0)
        db.session.add(self.enemy);db.session.commit()

    def operation(self,action,**values):
        data={'action':action,'request_id':str(uuid4()),**values};operate(1,data);db.session.expire_all();return data

    def recruit(self,level=7):
        self.operation('recruit',level=level,count=1);return db.session.scalar(select(IntelligenceAgent).order_by(IntelligenceAgent.id.desc()))

    def start(self,kind='bases',agent=None):
        agent=agent or self.recruit();self.operation('mission',kind=kind,agent_id=agent.id,region_id=2)
        return db.session.scalar(select(IntelligenceMission).order_by(IntelligenceMission.id.desc()))

    def finish(self,roll=0):
        with patch('game.intelligence_service.randbelow',return_value=roll):complete_missions(db.session,NOW+timedelta(days=7))
        db.session.commit();db.session.expire_all()


class IntelligenceTests(IntelligenceFixture):
    def test_recruitment_prices_budget_and_idempotence(self):
        prices=(17050000,27800000,34200000,45000000,65500000,72300000,105900000)
        for level,price in enumerate(prices,1):
            before=intelligence_budget(db.session,1)[2];data=self.operation('recruit',level=level,count=2)
            operate(1,data);self.assertEqual(before-intelligence_budget(db.session,1)[2],price*2)
        self.assertEqual(db.session.query(IntelligenceAgent).count(),14)
        self.assertEqual(db.session.query(IntelligenceExpense).count(),7)

    def test_week_long_mission_is_paid_and_agent_reserved(self):
        mission=self.start();agent=db.session.get(IntelligenceAgent,mission.agent_id)
        self.assertEqual(mission.ends_at-mission.starts_at,timedelta(days=7))
        self.assertEqual(sum(row.amount for row in db.session.query(IntelligenceExpense)),3105900000)
        with self.assertRaises(FinanceError):self.operation('mission',kind='bases',agent_id=agent.id,region_id=2)
        complete_missions(db.session,NOW+timedelta(days=7)-timedelta(seconds=1));db.session.commit()
        self.assertIsNone(db.session.get(IntelligenceMission,mission.id).completed_at)
        self.finish(9999);self.assertFalse(db.session.get(IntelligenceMission,mission.id).success)
        self.start(agent=agent)

    def test_counterintelligence_prices_and_proportional_chance(self):
        for level in range(1,7):self.operation('counter_upgrade',expected_level=level)
        self.assertEqual(db.session.get(CounterIntelligence,1).level,7)
        self.assertEqual(sum(row.amount for row in db.session.query(IntelligenceExpense)),24550000000)
        with self.assertRaises(FinanceError):self.operation('counter_upgrade',expected_level=7)
        db.session.add(CounterIntelligence(panstwo_id=2,level=7));db.session.commit()
        mission=self.start();self.finish(2249)
        self.assertEqual(db.session.get(IntelligenceMission,mission.id).effective_chance,2250)
        self.assertTrue(db.session.get(IntelligenceMission,mission.id).success)
        second=self.start();self.finish(2250);self.assertFalse(db.session.get(IntelligenceMission,second.id).success)

    def test_visibility_unlocked_by_success_not_failure(self):
        self.assertEqual(visible_base_data(1,True),[])
        mission=self.start();self.finish(9999);self.assertEqual(known_ids(db.session,1,'bases'),set())
        mission=self.start();self.finish();data=visible_base_data(1,True)
        self.assertEqual(data[0]['id'],self.enemy.id);self.assertEqual(data[0]['garrison'],{})
        self.assertEqual(visible_base_data(3,True),[])

    def test_base_and_silo_intelligence_are_separate(self):
        silo=MilitaryBase(panstwo_id=2,region_id=2,kind='nuclear',level=1,garrison={'warheads':10},map_x=101,map_y=1);db.session.add(silo);db.session.commit()
        self.start();self.finish();self.assertEqual(known_ids(db.session,1,'bases'),{self.enemy.id})
        self.start('silos');self.finish();self.assertEqual(known_ids(db.session,1,'bases'),{self.enemy.id,silo.id})

    def test_base_reconnaissance_includes_foreign_bases_in_region(self):
        guest=MilitaryBase(panstwo_id=3,region_id=2,kind='air',level=1,garrison={'fighters':5},map_x=102,map_y=2)
        own=MilitaryBase(panstwo_id=1,region_id=2,kind='land',level=1,garrison={'soldiers':1},map_x=103,map_y=3)
        db.session.add_all([guest,own]);db.session.commit()
        mission=self.start();self.finish()
        self.assertEqual(known_ids(db.session,1,'bases'),{self.enemy.id,guest.id})   # baza państwa 3 w regionie państwa 2, bez własnej
        report=db.session.get(IntelligenceMission,mission.id).report
        self.assertTrue(any('państwo' in entry['label'] for entry in report['entries']))

    def test_defense_visibility_unlocked_independently(self):
        defense=MissileDefense(panstwo_id=2,region_id=2,target_kind='region',target_id=2,level=3,ammunition=900);db.session.add(defense);db.session.commit()
        self.assertEqual(visible_defenses(1,True),[])
        self.start('defenses');self.finish();self.assertEqual(visible_defenses(1,True)[0]['id'],defense.id)
        self.assertEqual(visible_base_data(1,True),[])

    def test_report_notification_opens_modal_private_and_exactly_once(self):
        mission=self.start();self.finish();self.finish()
        self.assertEqual(db.session.query(GameNotification).count(),1)
        notice=db.session.query(GameNotification).one()
        response=self.client.get('/game/forum/powiadomienia');self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['items'][0]['kind'],'INTELLIGENCE_REPORT')
        response=self.client.post(f'/game/forum/powiadomienia/{notice.id}/otworz',data={'csrf_token':'token'},headers={'Accept':'application/json'})
        self.assertEqual(response.status_code,200);self.assertTrue(response.json['report']['success'])
        self.login(2);self.assertEqual(self.client.get(f'/game/wywiad-wojskowy/raport/{mission.id}').status_code,404)
        self.assertEqual(self.client.post(f'/game/forum/powiadomienia/{notice.id}/otworz',data={'csrf_token':'token'},headers={'Accept':'application/json'}).status_code,404)

    def test_nuclear_resources_and_infrastructure_reports(self):
        # 13 Nov 2026: raport podaje rzeczywistą liczbę rakiet z głowicą nuklearną (magazyn), nie pole tabeli „wojsko”
        from game.commerce_models import ResourceStock
        db.session.add(Wojsko(panstwo_id=2,bron_atomowa_ilosc=999));db.session.add(ResourceStock(panstwo_id=2,resource='nuclear_missiles',quantity=42))
        db.session.get(Region,2).region_stan_infra_drogowej=66;db.session.commit()
        self.start('nuclear');self.finish();report=db.session.scalar(select(IntelligenceMission).order_by(IntelligenceMission.id.desc())).report
        self.assertEqual(report['entries'][0]['value'],'42')
        self.start('infrastructure');self.finish();report=db.session.scalar(select(IntelligenceMission).order_by(IntelligenceMission.id.desc())).report
        self.assertEqual(report['entries'][0]['value'],'66')
        DictZasob.__table__.create(db.engine);RegionZasob.__table__.create(db.engine)
        db.session.add(DictZasob(zasob_id=1,zasob_kod='gold',zasob_kategoria='Metal',zasob_nazwa='Złoto',zasob_jednostka='t'));db.session.add(RegionZasob(region_id=2,zasob_id=1,zloze_ilosc=250));db.session.commit()
        self.start('resources');self.finish();report=db.session.scalar(select(IntelligenceMission).order_by(IntelligenceMission.id.desc())).report
        self.assertEqual(report['entries'][0],{'label':'Złoto','value':'250 t'})

    def test_unsupported_or_unowned_missions_and_low_budget(self):
        agent=self.recruit()
        for kind,region in [('warehouses',2),('bases',1),('bases',999)]:
            with self.assertRaises(FinanceError):self.operation('mission',agent_id=agent.id,kind=kind,region_id=region)
        with self.assertRaises(FinanceError):self.operation('mission',agent_id=999,kind='bases',region_id=2)
        db.session.execute(text("UPDATE game_state_budget_allocations SET amount=0 WHERE category_code='security_services'"));db.session.commit()
        with self.assertRaises(FinanceError):self.recruit()
        with self.assertRaises(FinanceError):self.start(agent=agent)

    def test_security_budget_balance_and_transfers_reserve_expenses(self):
        self.recruit();from game.budget_transfers import sector_balances,transfer_funds
        from game.finance_models import StateBudget
        balances=sector_balances(db.session,db.session.get(StateBudget,1));self.assertEqual(balances['security_services']['spent'],105900000)
        with patch('game.budget_transfers.game_now',return_value=NOW):
            with self.assertRaises(FinanceError):transfer_funds(1,{'budget_id':1,'source':'security_services','destination':'armed_forces','amount':'100000000000','request_id':str(uuid4())})

    def test_rollback_does_not_release_intelligence_or_send_notification(self):
        mission=self.start()
        with patch('game.intelligence_service.randbelow',return_value=0):complete_missions(db.session,NOW+timedelta(days=7))
        db.session.rollback();self.assertEqual(known_ids(db.session,1,'bases'),set());self.assertEqual(db.session.query(GameNotification).count(),0)

    def test_screen_and_csrf(self):
        self.assertEqual(self.client.get('/game/wywiad-wojskowy').status_code,200)
        self.assertEqual(self.client.post('/game/wywiad-wojskowy/zmien',json={}).status_code,403)
        response=self.client.post('/game/wywiad-wojskowy/zmien',json={'action':'recruit','level':1,'count':1,'request_id':str(uuid4())},headers={'X-CSRF-Token':'token'})
        self.assertEqual(response.status_code,200)

    def test_incoming_flight_does_not_reveal_undiscovered_base(self):
        from models import Stosunki
        from types import SimpleNamespace
        from game.military_service import create_order
        db.session.add(Stosunki(PANSTWO_ID=1,PANSTWO_ID2=2,stan_id=8))
        self.enemy.garrison={'launchers':1};db.session.add(Wojsko(panstwo_id=2,rakiety_krotkiego_zasiegu=10));db.session.commit()
        with patch('game.military_service._country_for_user',return_value=SimpleNamespace(PANSTWO_ID=2)),patch('game.military_flights.region_point',return_value=[0,0]):
            id=create_order(2,{'kind':'missile','source_base_id':self.enemy.id,'region_id':1,'infrastructure':'road','missile_type':'short','missiles':1})
        with patch('game.military.game_now',return_value=NOW):state=self.client.get('/game/panel-wojenny/stan').json
        self.assertEqual(state['flights'],[]);self.assertEqual(state['bases'],[])

    def test_foreign_vessel_return_route_does_not_disclose_home_port(self):
        from game.military_models import MilitaryVessel
        from game.military import visible_vessels
        vessel=MilitaryVessel(panstwo_id=2,base_id=self.enemy.id,region_id=2,kind='warships',status='returning',source_x=50,source_y=0,target_x=100,target_y=0,starts_at=NOW,arrives_at=NOW+timedelta(hours=1))
        db.session.add(vessel);db.session.commit()
        with patch('game.military.game_now',return_value=NOW):data=visible_vessels(1,True)[0]
        self.assertIsNone(data['baseId']);self.assertIsNone(data['regionId']);self.assertEqual(data['source'],data['target'])

    def test_foreign_warships_visible_to_everyone_sailing_on_remaining_route(self):
        # 14 Nov 2026: obce okręty wojenne i lotniskowce widać bez wywiadu; okręty podwodne tylko w czasie wojny.
        from game.military_models import MilitaryVessel
        from game.military import visible_vessels
        sailing=MilitaryVessel(panstwo_id=2,base_id=self.enemy.id,region_id=2,kind='carriers',status='sailing',source_x=0,source_y=0,target_x=100,target_y=0,starts_at=NOW-timedelta(minutes=30),arrives_at=NOW+timedelta(minutes=30))
        sub=MilitaryVessel(panstwo_id=2,base_id=self.enemy.id,region_id=2,kind='submarines',status='stationed',source_x=0,source_y=0,target_x=10,target_y=0,starts_at=NOW,arrives_at=NOW)
        db.session.add_all([sailing,sub]);db.session.commit()
        with patch('game.military.game_now',return_value=NOW),patch('game.military_navy.vessel_route',return_value=[[0,0],[100,0]]):
            peaceful=visible_vessels(1,False);at_war=visible_vessels(1,True)
        self.assertEqual([v['kind'] for v in peaceful],['carriers'])
        self.assertEqual(sorted(v['kind'] for v in at_war),['carriers','submarines'])
        carrier=peaceful[0]
        self.assertIsNone(carrier['baseId']);self.assertEqual(carrier['route'],[[50.0,0.0],[100,0]])   # od bieżącej pozycji do celu
        self.assertEqual(carrier['source'],[50.0,0.0]);self.assertEqual(carrier['startsAt'],NOW.isoformat()+'Z')

class AgentNameTests(IntelligenceFixture):
    def test_rename_busy_agent_without_cost_and_keep_assignment(self):
        agent=self.recruit();mission=self.start(agent=agent)
        count=db.session.query(IntelligenceExpense).count()
        self.operation('rename',agent_id=agent.id,name='  Jan   Kowalski ')
        self.assertEqual(db.session.get(IntelligenceAgent,agent.id).name,'Jan Kowalski')
        self.assertEqual(db.session.query(IntelligenceExpense).count(),count)
        self.assertIsNone(db.session.get(IntelligenceMission,mission.id).completed_at)
        from game.intelligence import state_data
        state=state_data(1)
        self.assertEqual(state['agents'][0]['name'],'Jan Kowalski')
        self.assertTrue(state['agents'][0]['busy'])
        self.assertEqual(state['missions'][0]['country'],'Państwo 2')
        self.assertEqual(state['missions'][0]['agentName'],'Jan Kowalski')
    def test_rename_rejects_foreign_agent_and_invalid_names(self):
        agent=self.recruit()
        for name in ['', 'Jan', 'A'*101, 'Jan\nKowalski', None]:
            with self.assertRaises(FinanceError):self.operation('rename',agent_id=agent.id,name=name)
        with self.assertRaises(FinanceError):operate(2,{'action':'rename','agent_id':agent.id,'name':'Jan Kowalski','request_id':str(uuid4())})
