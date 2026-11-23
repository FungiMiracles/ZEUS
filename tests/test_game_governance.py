"""Sovereign selection and shared administration without changing WIKI ownership."""
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4
from unittest.mock import patch
from sqlalchemy import select, text, MetaData, Integer
from sqlalchemy.orm import lazyload
from flask import template_rendered

from game_features_support import FeatureTestCase
from test_game_commerce import CommerceFixture
from test_game_intelligence import IntelligenceFixture
from test_game_military import NOW
from extensions import db
from models import Panstwo, Region, Miasto, Wojsko
from game.models import GameUser, GamePlayerCountry, GameLoginEvent
from game.governance import controlled_ids, controller_id, economy, army_for_country
from game.country_summary import country_summary, metropolitan_region_ids
from game.finance_service import FinanceError, _country_for_user
from game.infrastructure_service import start_project
from game.infrastructure_models import InfrastructureProject
from game.mining_service import extract_country
from game.commerce_models import Mine, ResourceStock, PortTariff, TradeReserveMovement
from game.trade_service import choose_port, tariff, set_tariff
from game.missile_defense import owned_target


def country(id):
    return db.session.scalar(select(Panstwo).options(lazyload('*')).where(Panstwo.PANSTWO_ID==id))


class SovereignRegistrationTests(FeatureTestCase):
    def setUp(self):
        super().setUp()
        db.session().expire_on_commit = False
        from game.routes_auth import init_game_auth_routes
        # The lightweight fixture installs placeholder endpoints.
        self.app.view_functions.pop('game_main_page')
        self.app.view_functions.pop('game_logout')
        init_game_auth_routes(self.app)
        # SQLite autoincrement requires INTEGER, whereas production uses BIGINT.
        login_metadata = MetaData()
        GameUser.__table__.to_metadata(login_metadata)
        login_events = GameLoginEvent.__table__.to_metadata(login_metadata)
        login_events.c.id.type = Integer()
        login_events.create(db.engine, checkfirst=True)
        self.dependent = country(4)
        self.dependent.czy_suwerenny = 'NIE'
        self.dependent.zwierzch_panstwo_id = 1
        db.session.commit()
        with self.client.session_transaction() as browser:
            browser['game_registration_csrf'] = 'registration-test'

    def submit(self, country, password='bezpieczne-haslo-test'):
        return self.client.post('/game/api/rejestracja', headers={'X-CSRF-Token': 'registration-test'}, json={
            'username':'NowyGracz', 'email':'new@example.test', 'password':password,
            'password_confirm':password, 'panstwo_id':country})

    def test_password_must_be_longer_than_six_characters(self):
        # 16 Nov 2026: hasło dłuższe niż 6 znaków (7–128).
        self.dependent.czy_suwerenny = 'TAK'; self.dependent.zwierzch_panstwo_id = None; db.session.commit()
        for password in ('123456', 'x' * 129):
            response = self.submit(4, password)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json['error'], 'Hasło musi mieć od 7 do 128 znaków.')
        self.assertEqual(self.submit(4, '1234567').status_code, 201)

    def test_forged_dependent_registration_cannot_create_account(self):
        response = self.submit(4)
        self.assertEqual(response.status_code, 400)
        self.assertIn('niesuwerenne', response.json['error'])
        self.assertEqual(self.count(GameUser), 4)
        self.assertIsNone(db.session.scalar(select(GamePlayerCountry).where(GamePlayerCountry.panstwo_id==4)))
        self.assertEqual(self.count(GameLoginEvent), 0)

    def test_free_sovereign_registration_and_occupied_dependency(self):
        self.dependent.czy_suwerenny = 'TAK'
        self.dependent.zwierzch_panstwo_id = None
        db.session.commit()
        response = self.submit(4)
        self.assertEqual(response.status_code, 201, response.json)
        self.assertIsNotNone(db.session.scalar(select(GamePlayerCountry).where(GamePlayerCountry.panstwo_id==4)))

    def test_sovereign_with_legacy_assigned_dependency_is_unavailable(self):
        # Root 4 is free, but a legacy assignment to its dependency must not be stolen.
        self.dependent.czy_suwerenny = 'TAK'
        child = country(3)
        child.czy_suwerenny = 'NIE'; child.zwierzch_panstwo_id = 4
        db.session.commit()
        response = self.submit(4)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.count(GameUser), 4)


class SharedAdministrationTests(CommerceFixture):
    def setUp(self):
        super().setUp()
        db.session().expire_on_commit = False
        child = country(4)
        child.czy_suwerenny='NIE'; child.zwierzch_panstwo_id=1
        child.panstwo_populacja=2000000; child.panstwo_PKB=200000000; child.panstwo_powierzchnia=20
        parent=country(1)
        parent.panstwo_populacja=1000000; parent.panstwo_PKB=100000000; parent.panstwo_powierzchnia=10
        db.session.get(Region,1).panstwo_id=4
        port=db.session.get(Miasto,101);port.panstwo_id=4
        db.session.add(Region(region_id=4,panstwo_id=4,region_nazwa='Zamorski',terytorium_zamorskie=True))
        db.session.commit()

    def test_scope_chains_cycles_orphans_and_sovereign_boundaries(self):
        self.assertEqual(controlled_ids(db.session,1),[1,4])
        self.assertEqual(controller_id(db.session,4),1)
        self.assertEqual(controlled_ids(db.session,4),[])
        self.assertEqual(controlled_ids(db.session,2),[2])
        child=country(4);child.zwierzch_panstwo_id=4;db.session.commit()
        self.assertIsNone(controller_id(db.session,4))
        child.zwierzch_panstwo_id=None;db.session.commit()
        self.assertIsNone(controller_id(db.session,4))
        child.czy_suwerenny='TAK';child.zwierzch_panstwo_id=1;db.session.commit()
        self.assertEqual(controller_id(db.session,4),4)
        self.assertEqual(controlled_ids(db.session,1),[1])
        child.czy_suwerenny='NIE';child.zwierzch_panstwo_id=2
        middle=country(2);middle.czy_suwerenny='NIE';middle.zwierzch_panstwo_id=1
        db.session.commit()
        self.assertEqual(controlled_ids(db.session,1),[1,2,4])
        self.assertEqual(controller_id(db.session,4),1)

    def test_combined_economy_summary_and_metropolitan_map_do_not_annex_wiki(self):
        self.assertEqual(economy(db.session,1),dict(population=3000000,gdp=300000000,area=30))
        self.assertEqual(metropolitan_region_ids(1),['1'])
        with self.app.test_request_context():
            summary=country_summary(country(1))
        self.assertEqual(summary['populacja'],3000000)
        self.assertEqual(summary['territories'],['Państwo 4'])
        self.assertEqual(db.session.get(Region,1).panstwo_id,4)
        self.assertEqual(country(1).panstwo_populacja,1000000)

    def test_dependent_infrastructure_uses_sovereign_budget_only(self):
        region=db.session.get(Region,1)
        region.region_ludnosc_pozamiejska=1000000;region.region_stan_infra_drogowej=50
        db.session.commit()
        with patch('game.infrastructure_service.game_now',return_value=NOW):
            start_project(1,1,'road',1,False)
        db.session.expire_all()
        project=db.session.scalar(select(InfrastructureProject))
        self.assertEqual((project.panstwo_id,project.region_id,project.budget_id),(1,1,1))
        with patch('game.infrastructure_service.game_now',return_value=NOW):
            with self.assertRaises(FinanceError):start_project(2,1,'road',1,False)

    def test_base_and_missile_defense_can_be_placed_in_dependency(self):
        self.base(region=1)
        region=owned_target(db.session,1,'region',1)
        city=owned_target(db.session,1,'city',101)
        self.assertEqual(region.panstwo_id,4)
        self.assertEqual(city.panstwo_id,4)
        with self.assertRaises(FinanceError):owned_target(db.session,2,'region',1)

    def test_dependent_mine_extracts_into_shared_warehouse(self):
        id=self.mine()
        db.session.expire_all();mine=db.session.get(Mine,id)
        self.assertEqual((mine.panstwo_id,mine.region_id),(1,1))
        extract_country(db.session,1,mine.ready_at+timedelta(days=3));db.session.commit()
        stock=db.session.scalar(select(ResourceStock).where(ResourceStock.panstwo_id==1))
        self.assertEqual(stock.quantity,23)
        self.assertIsNone(db.session.scalar(select(ResourceStock).where(ResourceStock.panstwo_id==4)))

    def test_dependency_port_is_own_and_port_fees_go_to_controller(self):
        self.assertEqual(choose_port(db.session,1,101).panstwo_id,4)
        with self.assertRaises(FinanceError):choose_port(db.session,1,102)
        db.session.add(PortTariff(panstwo_id=1,rate=10));db.session.commit()
        self.assertEqual(tariff(db.session,4,1),0)
        self.assertEqual(tariff(db.session,4,2),10)
        set_tariff(1,{'rate':'12'})
        db.session.expire_all();self.assertEqual(db.session.get(PortTariff,1).rate,12)
        # Seller without ports uses the dependency's port; its fee belongs to root 1.
        from game.trade_service import create_offer, buy_offer
        db.session.get(Miasto,102).czy_portowe='NIE'
        db.session.add(ResourceStock(panstwo_id=2,resource='wegiel_kamienny',quantity=5))
        from game.finance_models import StateFinancialAccount
        db.session.add(StateFinancialAccount(panstwo_id=3,reserve_balance=10000,last_transaction_sequence=0,created_at=NOW,updated_at=NOW))
        db.session.commit()
        # 22 Nov 2026: towar jedzie koleją z magazynu sprzedającego (102) do portu zależności (101), dalej statkiem do 103.
        from game.rail_models import RailLine
        from datetime import timedelta
        RailLine.__table__.create(db.engine,checkfirst=True)
        db.session.add(RailLine(initiator_id=2,partner_id=4,city_a_id=102,city_b_id=101,path=[[100,0],[0,0]],distance_km=100,cost=0,shares={},build_days=1,status='ACTIVE',
                                starts_at=NOW-timedelta(days=5),ready_at=NOW-timedelta(days=1),request_id=str(uuid4())));db.session.commit()
        offer=create_offer(2,{'request_id':str(uuid4()),'cargo':{'wegiel_kamienny':1},'price':'1000'})
        buy_offer(3,{'request_id':str(uuid4()),'offer_id':offer,'delivery':'sea:103'})
        db.session.expire_all()
        self.assertEqual(db.session.get(StateFinancialAccount,1).reserve_balance,120)
        self.assertIsNone(db.session.get(StateFinancialAccount,4))

    def test_shared_army_stock_consumption_is_conserved(self):
        db.session.add(Wojsko(panstwo_id=4,czolgi_ilosc=30,rakiety_krotkiego_zasiegu=10))
        db.session.commit()
        army=army_for_country(db.session,1,lock=True)
        self.assertEqual(army.czolgi_ilosc,530)
        army.rakiety_krotkiego_zasiegu=5
        db.session.commit()
        self.assertEqual(army_for_country(db.session,1).rakiety_krotkiego_zasiegu,5)
        values=dict(db.session.execute(select(Wojsko.panstwo_id,Wojsko.rakiety_krotkiego_zasiegu)).all())
        self.assertEqual(values,{1:0,4:5})
        self.assertEqual(army_for_country(db.session,2),None)


class DependencyIntelligenceTests(IntelligenceFixture):
    def setUp(self):
        super().setUp()
        db.session().expire_on_commit = False
        child=country(4);child.czy_suwerenny='NIE';child.zwierzch_panstwo_id=2
        db.session.get(Region,2).panstwo_id=4
        db.session.commit()

    def test_mission_reports_assets_owned_by_controller_in_dependency(self):
        mission=self.start()
        self.assertEqual(mission.target_country_id,2)
        self.finish()
        report=db.session.get(type(mission),mission.id).report
        self.assertIn(self.enemy.id,report['base_ids'])

    def test_own_dependency_cannot_be_spied_on_or_attacked_diplomatically(self):
        country(4).zwierzch_panstwo_id=1;db.session.commit()
        agent=self.recruit()
        with self.assertRaises(FinanceError):self.operation('mission',kind='bases',agent_id=agent.id,region_id=2)
        response=self.client.post('/game/dyplomacja/akcje',data={'target_id':4,'kind':'WAR','csrf_token':'token'})
        self.assertEqual(response.status_code,400)

from test_game_military_flights import FlightFixture
from game.military_models import MilitaryFlight, MissileDefense
from game.military_flights import complete_flights
from game.forum_models import GameNotification


class DependencyFlightTests(FlightFixture):
    def setUp(self):
        super().setUp()
        child=country(4);child.czy_suwerenny='NIE';child.zwierzch_panstwo_id=2;child.panstwo_populacja=1000
        db.session.get(Region,2).panstwo_id=4
        db.session.get(Miasto,9001).panstwo_id=4
        db.session.commit()

    def test_attack_on_dependency_notifies_controller_and_reduces_actual_population(self):
        source=self.source();id=self.launch(source)
        db.session.expire_all();flight=db.session.get(MilitaryFlight,id)
        self.assertEqual(flight.target_country_id,2)
        with patch('game.military_flights.randbelow',return_value=50):
            complete_flights(db.session,NOW+timedelta(hours=1));db.session.commit()
        self.assertEqual(db.session.get(Miasto,9001).miasto_populacja,950)
        self.assertEqual(country(4).panstwo_populacja,950)
        self.assertEqual(country(2).panstwo_populacja,2000)
        self.assertEqual(set(db.session.scalars(select(GameNotification.user_id))),{1,2})

    def test_controller_defense_intercepts_attacks_on_dependency(self):
        db.session.add(MissileDefense(panstwo_id=2,region_id=2,target_kind='region',target_id=2,level=7,ammunition=100))
        db.session.commit()
        source=self.source();source.garrison={'launchers':2};db.session.commit()   # 23 Nov 2026: 10 rakiet na wyrzutnię
        id=self.launch(source,missiles=20)
        with patch('game.missile_defense.randbelow',side_effect=[0]*19+[99]):
            complete_flights(db.session,NOW+timedelta(hours=1));db.session.commit()
        self.assertEqual(db.session.get(MilitaryFlight,id).intercepted,19)
