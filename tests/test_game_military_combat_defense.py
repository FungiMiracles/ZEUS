"""Przybrzeżne bazy, obrona przeciwrakietowa i skutki trafień."""
from datetime import timedelta
from unittest.mock import patch
from sqlalchemy import select
from test_game_military import MilitaryFixture,NOW
from test_game_military_flights import FlightFixture
from extensions import db
from models import Region,Miasto,Wojsko
from game.military_models import (MilitaryBase,MilitaryVessel,MilitaryFlight,MissileDefense,MissileDefenseExpense,MilitaryMaintenance)
from game.military_service import military_budget,reconcile_maintenance
from game.military_flights import complete_flights
from game.military_geography import exposed_coastlines,naval_location_allowed
from game.finance_service import FinanceError
from game.forum_models import GameNotification


class CoastTests(MilitaryFixture):
    @staticmethod
    def feature(id,points):return {'properties':{'region_id':id},'geometry':{'type':'Polygon','coordinates':[points]}}

    def test_land_border_and_same_region_parts_are_not_coast(self):
        a=self.feature(1,[[0,0],[10,0],[10,10],[0,10],[0,0]])
        for id in [2,1,None]:
            b=self.feature(id,[[10,0],[20,0],[20,10],[10,10],[10,5],[10,0]])
            coast=exposed_coastlines([a,b])[1]
            self.assertFalse(any(p[0][0]==p[1][0]==10 for p in coast))
        # Repeated geometry must not remove real coast.
        self.assertEqual(len(exposed_coastlines([a,a])[1]),4)

    def test_band_is_three_km_inside_region_not_across_land_border(self):
        with patch('game.military_geography.region_contains',side_effect=lambda id,x,y:0<=x<=10 and 0<=y<=10),patch('game.military_geography.coastline_segments',return_value=[[[0,0],[10,0]]]):
            self.assertTrue(naval_location_allowed(1,5,1.5,2))
            self.assertFalse(naval_location_allowed(1,5,1.5001,2))
            self.assertFalse(naval_location_allowed(1,5,-1,2))
            self.assertFalse(naval_location_allowed(1,9.5,5,2))

    def test_naval_location_enforced_and_coast_endpoint_scoped(self):
        db.session.get(Region,1).region_polozenie_id=2;db.session.commit();base=self.base('naval')
        with patch('game.military_geography.region_contains',return_value=True),patch('game.military_geography.naval_location_allowed',return_value=False):
            with self.assertRaises(FinanceError):self.change('location',base_id=base.id,x=0,y=0)
        with patch('game.military_geography.region_contains',return_value=True),patch('game.military_geography.naval_location_allowed',return_value=True):self.change('location',base_id=base.id,x=0,y=0)
        self.assertEqual(db.session.get(MilitaryBase,base.id).map_x,0)
        self.assertEqual(self.client.get('/game/obrona-panstwa/wybrzeze/2').status_code,403)
        with patch('game.military_geography.coastline_segments',return_value=[[[0,0],[10,0]]]):
            response=self.client.get('/game/obrona-panstwa/wybrzeze/1');self.assertEqual(response.json['widthKm'],3)
            self.assertEqual(response.json['segments'],[[[0,0],[10,0]]])


class DefenseTests(MilitaryFixture):
    def defense(self,kind='region',id=1):
        self.change('defense_place',target_kind=kind,target_id=id)
        return db.session.scalar(select(MissileDefense).where(MissileDefense.target_kind==kind,MissileDefense.target_id==id))

    def test_build_upgrade_refill_and_shared_budget(self):
        defense=self.defense();self.assertEqual(defense.ammunition,100)
        self.assertEqual(military_budget(db.session,1)[2],999900000000)
        for level,cost in [(2,500000000),(3,750000000),(4,1000000000),(5,1250000000),(6,1500000000),(7,2000000000)]:
            before=military_budget(db.session,1)[2];self.change('defense_upgrade',defense_id=defense.id)
            defense=db.session.get(MissileDefense,defense.id);self.assertEqual(defense.level,level)
            self.assertEqual(before-military_budget(db.session,1)[2],cost)
        self.assertEqual(defense.ammunition,10000)
        with self.assertRaises(FinanceError):self.change('defense_upgrade',defense_id=defense.id)
        defense.ammunition=9990;db.session.commit();before=military_budget(db.session,1)[2]
        self.change('defense_refill',defense_id=defense.id,count=10)
        self.assertEqual(before-military_budget(db.session,1)[2],150000)
        with self.assertRaises(FinanceError):self.change('defense_refill',defense_id=defense.id,count=1)

    def test_upgrade_preserves_spent_ammunition(self):
        defense=self.defense();defense.ammunition=25;db.session.commit()
        self.change('defense_upgrade',defense_id=defense.id)
        self.assertEqual(db.session.get(MissileDefense,defense.id).ammunition,425)

    def test_owned_city_base_region_and_duplicate_checks(self):
        base=self.base();db.session.add(Miasto(miasto_id=123,panstwo_id=1,region_id=1,miasto_nazwa='Własne'));db.session.commit()
        self.defense('base',base.id);self.defense('city',123);self.defense()
        self.assertEqual(db.session.query(MissileDefense).count(),3)
        with self.assertRaises(FinanceError):self.defense()
        with self.assertRaises(FinanceError):self.defense('region',2)
        with self.assertRaises(FinanceError):self.defense('city',999)
        self.login(2)
        self.assertEqual(self.client.post('/game/obrona-panstwa/zmien',json={'action':'defense_upgrade','defense_id':1},headers={'X-CSRF-Token':'token'}).status_code,400)

    def test_no_funds_rollback_and_maintenance_honors_expenses(self):
        self.set_budget(99999999)
        with self.assertRaises(FinanceError):self.defense()
        self.assertEqual(db.session.query(MissileDefenseExpense).count(),0)
        self.set_budget(100400000);base=self.base();self.change('garrison',base_id=base.id,garrison={'soldiers':10000,'tanks':100})
        with self.assertRaises(FinanceError):self.defense()
        self.change('garrison',base_id=base.id,garrison={'tanks':50});self.defense()
        reconcile_maintenance(db.session,1,NOW);db.session.commit()
        self.assertEqual(db.session.get(MilitaryBase,base.id).garrison['tanks'],50)
        self.assertEqual(db.session.query(MilitaryMaintenance).one().amount,400000)
        self.assertEqual(military_budget(db.session,1)[2],0)


class CombatTests(FlightFixture):
    def setUp(self):
        super().setUp()
        region=patch('game.military_flights.region_point',return_value=[100,0]);region.start();self.addCleanup(region.stop)

    def target_base(self):
        base=MilitaryBase(panstwo_id=2,region_id=2,kind='land',level=1,garrison={},map_x=100,map_y=0)
        db.session.add(base);db.session.flush()
        from game.intelligence_models import IntelligenceAgent,IntelligenceMission
        agent=IntelligenceAgent(panstwo_id=1,level=1);db.session.add(agent);db.session.flush()
        db.session.add(IntelligenceMission(panstwo_id=1,agent_id=agent.id,region_id=2,target_country_id=2,region_name='Cel',kind='bases',starts_at=NOW-timedelta(days=7),ends_at=NOW,completed_at=NOW,success=True,report={'base_ids':[base.id]}))
        db.session.commit();return base

    def protection(self,kind='region',target=2,ammo=100,level=1):
        defense=MissileDefense(panstwo_id=2,region_id=2,target_kind=kind,target_id=target,level=level,ammunition=ammo)
        db.session.add(defense);db.session.commit();return defense

    def complete(self,**patches):
        with patch('game.military_flights.randbelow',return_value=patches.get('roll',0)),patch('game.missile_defense.randbelow',return_value=patches.get('intercept',99)):
            complete_flights(db.session,NOW+timedelta(hours=2));db.session.commit()
        db.session.expire_all()

    def test_infrastructure_loses_one_per_hit_clamps_and_notifications(self):
        db.session.get(Region,2).region_stan_infra_drogowej=2;db.session.commit()
        id=self.launch(self.source(),city_id=None,infrastructure='road',missiles=3)
        self.complete();self.complete()
        self.assertEqual(db.session.get(Region,2).region_stan_infra_drogowej,0)
        self.assertEqual(db.session.get(MilitaryFlight,id).damage['infrastructurePoints'],2)
        self.assertEqual(db.session.get(Miasto,9001).miasto_populacja,1000)
        self.assertEqual(db.session.query(GameNotification).count(),2)
        self.assertTrue(all('Zniszczenia infrastruktury: 2 pkt' in n.system_text for n in db.session.query(GameNotification)))

    def test_base_damage_bounds_and_exactly_once(self):
        source=self.source();base=self.target_base()
        id=self.launch(source,city_id=None,target_base_id=base.id,missiles=2)
        self.complete(roll=11);self.complete(roll=11)
        self.assertEqual(db.session.get(MilitaryBase,base.id).health,70)
        self.assertEqual(db.session.get(MilitaryFlight,id).damage['baseHealthLost'],30)
        id=self.launch(source,city_id=None,target_base_id=base.id)
        self.complete(roll=0)
        self.assertEqual(db.session.get(MilitaryBase,base.id).health,66)
        self.assertEqual(db.session.get(Miasto,9001).miasto_populacja,1000)

    def test_region_then_base_interception_ammo_is_limited(self):
        base=self.target_base();regional=self.protection(ammo=2);local=self.protection('base',base.id,ammo=3,level=7)
        id=self.launch(self.source(),city_id=None,target_base_id=base.id,missiles=10)
        self.complete(intercept=0)
        self.assertEqual(db.session.get(MissileDefense,regional.id).ammunition,0)
        self.assertEqual(db.session.get(MissileDefense,local.id).ammunition,0)
        self.assertEqual(db.session.get(MilitaryFlight,id).intercepted,5)
        self.assertEqual(db.session.get(MilitaryBase,base.id).health,80)
        self.complete(intercept=0)
        self.assertEqual(db.session.get(MilitaryBase,base.id).health,80)

    def test_city_protected_without_losses_and_region_runs_first(self):
        regional=self.protection(ammo=10);local=self.protection('city',9001,ammo=10)
        id=self.launch(self.source(),missiles=2);self.complete(intercept=0,roll=100)
        self.assertEqual(db.session.get(Miasto,9001).miasto_populacja,1000)
        self.assertEqual(db.session.get(MissileDefense,regional.id).ammunition,8)
        self.assertEqual(db.session.get(MissileDefense,local.id).ammunition,10)
        self.assertEqual(db.session.get(MilitaryFlight,id).intercepted,2)

    def test_no_ammo_means_no_interception(self):
        defense=self.protection(ammo=0)
        id=self.launch(self.source(),missiles=2);self.complete(intercept=0,roll=100)
        self.assertEqual(db.session.get(Miasto,9001).miasto_populacja,800)
        self.assertEqual(db.session.get(MilitaryFlight,id).intercepted,0)

    def test_invalid_target_does_not_consume_ammunition(self):
        source=self.source();own=self.base();own.map_x=100;own.map_y=0;db.session.commit()
        for kwargs in [{'city_id':None,'target_base_id':own.id},{'city_id':None,'target_base_id':999},{'target_base_id':self.target_base().id},{'city_id':None,'target_vessel_id':999}]:
            with self.assertRaises(FinanceError):self.launch(source,**kwargs)
        db.session.expire_all();self.assertEqual(db.session.query(Wojsko).one().rakiety_krotkiego_zasiegu,20)

    def enemy_vessel(self,kind='warships',health=100):
        base=self.target_base();base.kind='naval';base.garrison={kind:1}
        army=Wojsko(panstwo_id=2,okrety_wojenne_ilosc=1,okrety_podwodne_ilosc=1);db.session.add(army)
        vessel=MilitaryVessel(panstwo_id=2,base_id=base.id,kind=kind,health=health,status='stationed',source_x=100,source_y=0,target_x=100,target_y=0,starts_at=NOW,arrives_at=NOW)
        db.session.add(vessel);db.session.commit();return vessel,base,army

    def test_ship_sinks_stock_and_base_counts_removed_once(self):
        vessel,base,army=self.enemy_vessel(health=8)
        id=self.launch(self.source(),city_id=None,target_vessel_id=vessel.id,missiles=2)
        self.complete();self.complete()
        self.assertEqual(db.session.get(MilitaryVessel,vessel.id).status,'sunk')
        self.assertEqual(db.session.get(MilitaryVessel,vessel.id).health,0)
        self.assertEqual(db.session.get(MilitaryBase,base.id).garrison['warships'],0)
        self.assertEqual(db.session.scalar(select(Wojsko.okrety_wojenne_ilosc).where(Wojsko.panstwo_id==2)),0)
        self.assertTrue(db.session.get(MilitaryFlight,id).damage['sunk'])
        self.assertEqual(len(self.client.get('/game/panel-wojenny/stan').json['vessels']),0)

    def test_enemy_vessel_visible_in_war_and_no_rename_permission(self):
        vessel,base,army=self.enemy_vessel('submarines')
        state=self.client.get('/game/panel-wojenny/stan').json
        self.assertEqual(state['vessels'][0]['countryId'],2)
        with self.assertRaises(FinanceError):self.change('rename_vessel',vessel_id=vessel.id,name='Cudzy')

    def test_moving_vessel_destination_accounts_for_travel(self):
        vessel,base,army=self.enemy_vessel();vessel.status='sailing';vessel.target_x=200;vessel.arrives_at=NOW+timedelta(hours=1);db.session.commit()
        id=self.launch(self.source(),city_id=None,target_vessel_id=vessel.id)
        flight=db.session.get(MilitaryFlight,id)
        # Interception at 1500*t = 100+100*t, not at the launch-time point.
        self.assertAlmostEqual(flight.target_x,100*1800/1700,places=5)  # rakieta 1800 km/h, okręt 100 km/h

    def test_base_and_ship_targets_from_fighter_and_deployed_navy(self):
        base=self.target_base();vessel,home,army=self.enemy_vessel()
        db.session.get(Region,1).region_polozenie_id=2;db.session.commit()
        for kind in ['land','air','naval']:
            source=self.source(kind);options={}
            if kind=='naval':
                self.change('sail',base_id=source.id,vessel_kind='warships',x=50,y=0)
                own=db.session.scalar(select(MilitaryVessel).where(MilitaryVessel.panstwo_id==1));options['vessel_id']=own.id
            self.launch(source,city_id=None,target_base_id=base.id,**options);self.complete()
            # A second air mission is allowed after its prior return.
            self.launch(source,city_id=None,target_vessel_id=vessel.id,**options);self.complete()
        self.assertEqual(db.session.get(MilitaryBase,base.id).health,88)
        self.assertEqual(db.session.get(MilitaryVessel,vessel.id).health,88)

    def test_rollback_restores_defense_health_and_notifications(self):
        base=self.target_base();defense=self.protection(ammo=1)
        id=self.launch(self.source(),city_id=None,target_base_id=base.id,missiles=2)
        with patch('game.military_flights.randbelow',return_value=0),patch('game.missile_defense.randbelow',return_value=0):
            complete_flights(db.session,NOW+timedelta(hours=2))
        db.session.rollback()
        self.assertEqual(db.session.get(MilitaryBase,base.id).health,100)
        self.assertEqual(db.session.get(MissileDefense,defense.id).ammunition,1)
        self.assertIsNone(db.session.get(MilitaryFlight,id).impacted_at)
        self.assertEqual(db.session.query(GameNotification).count(),0)

    def test_nuclear_is_intercepted_but_causes_no_damage(self):
        defense=self.protection(ammo=100);silo=self.base('nuclear');silo.map_x=0;silo.map_y=0;silo.garrison={'warheads':1}
        from game.commerce_models import ResourceStock   # 13 Nov 2026: rzeczywisty licznik rakiet z głowicą nuklearną
        db.session.add(ResourceStock(panstwo_id=1,resource='nuclear_missiles',quantity=1));db.session.commit()
        base=self.target_base();id=self.launch(silo,city_id=None,target_base_id=base.id,is_nuclear=True)
        self.complete(intercept=0)
        self.assertEqual(db.session.get(MissileDefense,defense.id).ammunition,99)
        self.assertEqual(db.session.get(MilitaryFlight,id).intercepted,1)
        self.assertEqual(db.session.get(MilitaryBase,base.id).health,100)
