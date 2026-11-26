"""Ataki na wrogie armie maszerujące po naszym terytorium (22 Nov 2026): lotnictwo/rakiety/okręt i przechwycenie lądowe."""
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
from sqlalchemy.orm import Session
from extensions import db
from models import Wojsko
from test_land_war import LandWarFixture, key
from test_game_military import NOW
from game.military_models import MilitaryBase, MilitaryFlight
from game.land_war_models import LandArmy
from game.finance_service import FinanceError
from game.forum_models import GameNotification
from game import land_war
import game.infrastructure_service  # noqa: F401 — import przed łatkami fixtury (moduł wiąże _country_for_user przy imporcie)


class MarchAttackTests(LandWarFixture):
    def setUp(self):
        super().setUp()
        # Armia państwa 2 maszeruje po terytorium państwa 1: (200,0) -> (0,0), 200 km w 4 godz., granica przekroczona.
        self.hostile=LandArmy(panstwo_id=2,user_id=2,request_id=key(),role='invasion',status='MARCHING',soldiers=1000,armored=0,tanks=10,
                              target_kind='city',target_city_id=11,target_country_id=1,target_region_id=1,target_name='Miasto A',
                              source_x=200,source_y=0,target_x=0,target_y=0,distance_km=200,speed_kmh=50,starts_at=NOW,border_at=NOW,
                              border_notified=True,arrives_at=NOW+timedelta(hours=4),cost=0)
        db.session.add(self.hostile);db.session.commit()

    def intercept(self,**units):
        return land_war.launch_interception(1,{'army_id':self.hostile.id,'source_base_id':self.home.id,'request_id':key(),**units})

    def resolve(self,moment,rolls):
        self.now=moment
        with patch.object(land_war._random,'uniform',side_effect=list(rolls)):
            with Session(db.engine) as session,session.begin():land_war.complete_marches(session,moment)

    def test_interception_meets_the_army_on_its_route_and_wins(self):
        interceptor=self.army(self.intercept(soldiers=3000))
        self.assertEqual((interceptor.role,interceptor.target_kind,interceptor.target_army_id,interceptor.status),('intercept','army',self.hostile.id,'MARCHING'))
        self.assertAlmostEqual((interceptor.arrives_at-NOW).total_seconds(),2*3600,delta=2)   # 50 km/h z obu stron: spotkanie w połowie
        self.assertAlmostEqual(interceptor.target_x,100,delta=0.1)
        db.session.expire_all();self.assertEqual(db.session.get(MilitaryBase,self.home.id).garrison['soldiers'],2000)
        self.resolve(interceptor.arrives_at,[0.0,0.0])
        # 3000 × 3,0 = 9000 vs (1000 + 5 × 10) × 7,0 = 7350 -> przechwycenie udane, straty 3000 × 7350/9000
        interceptor,hostile=self.army(interceptor.id),self.army(self.hostile.id)
        self.assertEqual(interceptor.battle['result'],'INTERCEPT_WON');self.assertEqual(interceptor.status,'WITHDRAWN')
        self.assertEqual((hostile.status,hostile.soldiers,hostile.tanks,hostile.battle['result']),('DESTROYED',0,0,'INTERCEPTED'))
        self.assertEqual(db.session.get(MilitaryBase,self.home.id).garrison['soldiers'],2000+3000-2450)
        self.assertEqual(db.session.query(Wojsko).filter_by(panstwo_id=2).one().wojska_ladowe_ilosc,50000-1000)
        self.assertEqual(db.session.query(Wojsko).filter_by(panstwo_id=2).one().czolgi_ilosc,90)
        self.assertTrue(any('Bitwa w marszu' in (n.system_text or '') for n in db.session.query(GameNotification).filter_by(user_id=2)))

    def test_lost_interception_weakens_the_army_which_keeps_marching(self):
        interceptor=self.army(self.intercept(soldiers=100))
        self.resolve(interceptor.arrives_at,[0.0,0.0])
        interceptor,hostile=self.army(interceptor.id),self.army(self.hostile.id)
        self.assertEqual((interceptor.status,interceptor.battle['result']),('DESTROYED','INTERCEPT_LOST'))
        self.assertEqual((hostile.status,hostile.soldiers,hostile.tanks),('MARCHING',1000-round(1000*300/7350),10))
        self.assertEqual(db.session.query(Wojsko).filter_by(panstwo_id=1).one().wojska_ladowe_ilosc,100000-100)

    def test_interception_rules(self):
        self.hostile.border_at=NOW+timedelta(minutes=30);db.session.commit()
        with self.assertRaises(FinanceError) as error:self.intercept(soldiers=10)
        self.assertIn('granicy',str(error.exception))
        self.hostile.border_at=NOW;self.hostile.arrives_at=NOW+timedelta(minutes=20);self.hostile.source_x=20;db.session.commit()
        self.home.map_x=-100;db.session.commit()
        with self.assertRaises(FinanceError) as error:self.intercept(soldiers=10)
        self.assertIn('nie zdąży',str(error.exception))
        self.player=2   # własnej armii nie można przechwycić
        with self.assertRaises(FinanceError):land_war.launch_interception(2,{'army_id':self.hostile.id,'source_base_id':self.enemy.id,'request_id':key(),'soldiers':10})

    def test_missile_strike_destroys_a_share_of_the_army(self):
        from game.military_service import create_order
        from game.military_flights import complete_flights
        self.home.garrison={**self.home.garrison,'launchers':1};db.session.commit()
        data={'kind':'missile','target_army_id':self.hostile.id,'region_id':1,'source_base_id':self.home.id,'missile_type':'short','missiles':5}
        with patch('game.military_service._country_for_user',return_value=SimpleNamespace(PANSTWO_ID=1)):
            with self.assertRaises(FinanceError):create_order(1,{**data,'is_nuclear':True})
            with self.assertRaises(FinanceError):create_order(1,{**data,'kind':'land'})
            flight_id=create_order(1,data)
        db.session.expire_all();flight=db.session.get(MilitaryFlight,flight_id)
        self.assertEqual((flight.target_kind,flight.target_country_id),('army',2))
        self.assertLess(flight.impact_at,self.hostile.arrives_at)
        with patch.object(land_war._random,'uniform',return_value=2.0),Session(db.engine) as session,session.begin():complete_flights(session,flight.impact_at)
        keep=0.98**5
        hostile=self.army(self.hostile.id)
        self.assertEqual((hostile.soldiers,hostile.tanks,hostile.status),(1000-round(1000*(1-keep)),10-round(10*(1-keep)),'MARCHING'))
        db.session.expire_all();flight=db.session.get(MilitaryFlight,flight_id)
        self.assertEqual(flight.damage['armyLosses']['soldiers'],round(1000*(1-keep)))
        self.assertTrue(any('Straty armii w marszu' in (n.system_text or '') for n in db.session.query(GameNotification).filter_by(user_id=1)))

    def test_strike_can_destroy_the_army(self):
        with Session(db.engine) as session,session.begin():
            army=session.get(LandArmy,self.hostile.id);army.soldiers=10;army.tanks=0
            with patch.object(land_war._random,'uniform',return_value=3.0):damage=land_war.strike_army(session,army,200,NOW)
        self.assertTrue(damage['armyDestroyed']);self.assertEqual(self.army(self.hostile.id).status,'DESTROYED')

    def test_visible_to_defender_with_region(self):
        rows=land_war.visible_armies(db.session,1)
        row=next(r for r in rows if r['id']==self.hostile.id)
        self.assertEqual((row['role'],row['targetRegionId'],row['targetArmyId']),('invasion',1,None))


class OverlandAndCancelTests(LandWarFixture):
    def test_invasion_across_the_sea_is_rejected(self):
        with patch('game.land_war.march_route',return_value=None):
            with self.assertRaises(FinanceError) as error:self.invade(soldiers=10)
        self.assertIn('morze',str(error.exception))
        self.assertEqual(db.session.query(LandArmy).count(),0)

    def test_overland_geometry(self):
        from shapely.geometry import box
        from game import sea_routes
        router=SimpleNamespace(land=box(0,0,10,10).union(box(20,0,30,10)),lock=__import__('threading').RLock())
        with patch('game.sea_routes._world_router',return_value=router):
            self.assertTrue(sea_routes.overland((1,1),(9,9)))
            self.assertFalse(sea_routes.overland((1,1),(25,5)))                       # przez „morze” 10–20
            self.assertTrue(sea_routes.overland((1,1),(11,5),endpoint_km=2,km_per_unit=1))   # cel w pasie przybrzeżnym

    def test_cancel_turns_the_army_back_to_its_base(self):
        id=self.invade(soldiers=100)
        self.now=NOW+timedelta(minutes=30)
        land_war.cancel_march(1,{'army_id':id})
        army=self.army(id)
        self.assertEqual((army.status,army.arrives_at),('RETURNING',NOW+timedelta(minutes=60)))
        self.assertAlmostEqual(army.source_x,25,delta=0.01);self.assertEqual((army.target_x,army.target_y),(0,0))
        with self.assertRaises(FinanceError):land_war.cancel_march(1,{'army_id':id})
        self.assertEqual(land_war.deployed_counts(db.session,1)['wojska_ladowe_ilosc'],100)   # jednostki nadal w drodze
        self.now=NOW+timedelta(minutes=61)
        with Session(db.engine) as session,session.begin():land_war.complete_marches(session,self.now)
        army=self.army(id)
        self.assertEqual(army.status,'WITHDRAWN')
        self.assertEqual(db.session.get(MilitaryBase,self.home.id).garrison['soldiers'],5000)
        self.assertTrue(any('wróciła do bazy' in (n.system_text or '') for n in db.session.query(GameNotification).filter_by(user_id=1)))

    def test_only_own_marching_army_can_be_cancelled(self):
        id=self.invade(soldiers=10)
        self.player=2
        with self.assertRaises(FinanceError):land_war.cancel_march(2,{'army_id':id})
