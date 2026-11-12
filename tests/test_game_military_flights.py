"""Pozycje, przeloty i atomowe skutki trafień w miasta."""
from datetime import datetime,timedelta
from math import hypot
from unittest.mock import patch
from types import SimpleNamespace
from sqlalchemy import MetaData,Table,Column,Integer,update,select
from test_game_military import MilitaryFixture,NOW
from extensions import db
from models import Miasto,MiastoStateHistory,Panstwo,Stosunki,Wojsko,Region
from game.military_models import MilitaryBase,MilitaryFlight,MilitaryOrder,MapCalibration,MilitaryVessel
from game.military_service import create_order,active_counts
from game.military_flights import complete_flights,distance_km,busy_fighters
from game.finance_service import FinanceError


class FlightFixture(MilitaryFixture):
    def setUp(self):
        super().setUp()
        metadata=MetaData()
        Table(MiastoStateHistory.__tablename__,metadata,*[
            Column(c.name,Integer if c.name=='id' else c.type,primary_key=c.primary_key,nullable=c.nullable)
            for c in MiastoStateHistory.__table__.columns]).create(db.engine)
        db.session.add(Stosunki(PANSTWO_ID=1,PANSTWO_ID2=2,stan_id=8))
        db.session.add(Miasto(miasto_id=9001,panstwo_id=2,region_id=2,miasto_nazwa='Cel',miasto_populacja=1000))
        db.session.execute(update(Panstwo).where(Panstwo.PANSTWO_ID==2).values(panstwo_populacja=2000))
        db.session.commit()
        self.point=patch('game.military_flights.city_point',return_value=[100,0]);self.point.start();self.addCleanup(self.point.stop)
        self.owner=patch('game.military_service._country_for_user',return_value=SimpleNamespace(PANSTWO_ID=1));self.owner.start();self.addCleanup(self.owner.stop)

    def source(self,kind='land'):
        base=self.base(kind=kind)
        base.map_x=0;base.map_y=0;base.garrison={'launchers':1} if kind=='land' else {'fighters':1} if kind=='air' else {'warships':1}
        db.session.commit()
        return base

    def launch(self,base,**extra):
        payload={'kind':'air' if base.kind=='air' else 'naval' if base.kind=='naval' else 'missile',
            'region_id':2,'city_id':9001,'source_base_id':base.id,'missile_type':'short','missiles':1}
        return create_order(1,{**payload,**extra})


class FlightTests(FlightFixture):
    def test_reference_scale_and_distance(self):
        a=[954.7510623012616,-1801.62366708549];b=[952.4987942837062,-1776.1536230000308]
        db.session.get(MapCalibration,1).km_per_unit=100/hypot(a[0]-b[0],a[1]-b[1]);db.session.commit()
        self.assertAlmostEqual(distance_km(db.session,a,b),100,places=8)

    def test_location_saved_only_inside_region_and_owned(self):
        base=self.base()
        with patch('game.military_geography.region_contains',return_value=True):self.change('location',base_id=base.id,x=0,y=0)
        self.assertEqual((db.session.get(MilitaryBase,base.id).map_x,db.session.get(MilitaryBase,base.id).map_y),(0,0))
        self.assertEqual(db.session.get(MilitaryBase,base.id).health,100)
        with patch('game.military_geography.region_contains',return_value=False):
            with self.assertRaises(FinanceError):self.change('location',base_id=base.id,x=999,y=999)
        for value in [True,float('nan'),float('inf'),'1']:
            with self.assertRaises(FinanceError):self.change('location',base_id=base.id,x=value,y=0)
        with self.assertRaises(FinanceError):self.change('location',base_id=999,x=0,y=0)

    def test_geometry_holes_and_islands(self):
        from game.military_geography import contains_point
        geometry={'type':'Polygon','coordinates':[[[0,0],[10,0],[10,10],[0,10],[0,0]],[[3,3],[7,3],[7,7],[3,7],[3,3]]]}
        self.assertTrue(contains_point(geometry,(1,1)))
        self.assertFalse(contains_point(geometry,(5,5)))
        self.assertFalse(contains_point(geometry,(12,5)))
        self.assertTrue(contains_point({'type':'MultiPolygon','coordinates':[geometry['coordinates'],[[[20,20],[22,20],[22,22],[20,22],[20,20]]]]},(21,21)))

    def test_impact_timing_ammo_and_exactly_once(self):
        base=self.source();id=self.launch(base,missiles=2)
        db.session.expire_all();flight=db.session.get(MilitaryFlight,id)
        self.assertEqual(flight.distance_km,100)
        self.assertEqual(flight.impact_at,NOW+timedelta(seconds=200))  # 100 km przy 1800 km/h (12 Nov 2026)
        self.assertEqual(db.session.query(Wojsko).one().rakiety_krotkiego_zasiegu,18)
        with patch('game.military_flights.randbelow',return_value=100):
            complete_flights(db.session,NOW+timedelta(seconds=199));db.session.commit()  # tuż przed uderzeniem (200 s)
            self.assertEqual(db.session.get(Miasto,9001).miasto_populacja,1000)
            complete_flights(db.session,NOW+timedelta(hours=1));db.session.commit()
            complete_flights(db.session,NOW+timedelta(hours=2));db.session.commit()
        self.assertEqual(db.session.get(Miasto,9001).miasto_populacja,800)
        self.assertEqual(db.session.scalar(select(Panstwo.panstwo_populacja).where(Panstwo.PANSTWO_ID==2)),1800)
        self.assertEqual(db.session.get(MilitaryFlight,id).casualties,200)
        self.assertEqual(db.session.query(MiastoStateHistory).count(),1)

    def test_losses_capped_and_zero_casualties_supported(self):
        base=self.source();db.session.get(Miasto,9001).miasto_populacja=30;db.session.commit()
        id=self.launch(base)
        with patch('game.military_flights.randbelow',return_value=100):complete_flights(db.session,NOW+timedelta(hours=1));db.session.commit()
        self.assertEqual(db.session.get(MilitaryFlight,id).casualties,30)
        self.assertEqual(db.session.get(Miasto,9001).miasto_populacja,0)
        id=self.launch(base)
        with patch('game.military_flights.randbelow',return_value=0):complete_flights(db.session,NOW+timedelta(hours=1));db.session.commit()
        self.assertEqual(db.session.get(MilitaryFlight,id).casualties,0)

    def test_impact_rollback_restores_population_and_flight(self):
        base=self.source();id=self.launch(base)
        with patch('game.military_flights.randbelow',return_value=50):complete_flights(db.session,NOW+timedelta(hours=1))
        db.session.rollback()
        self.assertEqual(db.session.get(Miasto,9001).miasto_populacja,1000)
        self.assertIsNone(db.session.get(MilitaryFlight,id).impacted_at)
        self.assertEqual(db.session.query(MiastoStateHistory).count(),0)

    def test_fighter_outbound_wait_return_and_reservation(self):
        base=self.source('air');id=self.launch(base)
        flight=db.session.get(MilitaryFlight,id)
        self.assertEqual(flight.fighter_arrives_at,NOW+timedelta(seconds=400))
        self.assertEqual(flight.returns_at,NOW+timedelta(seconds=800))
        self.assertEqual(busy_fighters(db.session,base.id,NOW),1)
        with self.assertRaises(FinanceError):self.launch(base)
        with self.assertRaises(FinanceError):self.change('withdraw',base_id=base.id)
        with patch('game.military_geography.region_contains',return_value=True):
            with self.assertRaises(FinanceError):self.change('location',base_id=base.id,x=1,y=1)
        with patch('game.military_flights.randbelow',return_value=0):complete_flights(db.session,NOW+timedelta(seconds=400));db.session.commit()
        self.assertIsNone(db.session.get(MilitaryFlight,id).returned_at)
        complete_flights(db.session,NOW+timedelta(seconds=800));db.session.commit()
        self.assertIsNotNone(db.session.get(MilitaryFlight,id).returned_at)

    def test_range_source_and_city_validation_rollback_ammo(self):
        base=self.source()
        with patch('game.military_flights.city_point',return_value=[501,0]):
            with self.assertRaises(FinanceError):self.launch(base)
        with self.assertRaises(FinanceError):self.launch(base,city_id=123456)
        with self.assertRaises(FinanceError):self.launch(base,source_base_id=999)
        with self.assertRaises(FinanceError):self.launch(base,missiles=10001)
        db.session.expire_all()
        self.assertEqual(db.session.query(MilitaryOrder).count(),0)
        self.assertEqual(db.session.query(Wojsko).one().rakiety_krotkiego_zasiegu,20)
        army=db.session.query(Wojsko).one();army.rakiety_sredniego_zasiegu=2;army.rakiety_dalekiego_zasiegu=2;db.session.commit()
        with patch('game.military_flights.city_point',return_value=[600,0]):id=self.launch(base,missile_type='medium')
        self.assertEqual(db.session.get(MilitaryFlight,id).impact_at,NOW+timedelta(seconds=900))  # 600 km przy 2400 km/h
        with patch('game.military_flights.city_point',return_value=[2500,0]):id=self.launch(base,missile_type='long')
        self.assertEqual(db.session.get(MilitaryFlight,id).impact_at,NOW+timedelta(hours=2500/5200))  # rakieta dalekiego zasięgu 5200 km/h

    def test_live_state_shows_participant_flights_and_base_positions(self):
        base=self.source();id=self.launch(base)
        response=self.client.get('/game/panel-wojenny/stan')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['flights'][0]['id'],id)
        self.assertEqual(response.json['bases'][0]['position'],[0,0])
        self.assertEqual(response.json['bases'][0]['health'],100)
        self.login(2);self.assertEqual(self.client.get('/game/panel-wojenny/stan').json['flights'][0]['id'],id)
        self.login(3);self.assertEqual(self.client.get('/game/panel-wojenny/stan').json['flights'],[])

    def test_naval_city_attack_and_destroyed_base_cannot_launch(self):
        db.session.get(Region,1).region_polozenie_id=2
        db.session.get(Region,2).region_polozenie_id=2
        db.session.commit()
        base=self.source('naval');id=self.launch(base)
        self.assertEqual(db.session.get(MilitaryFlight,id).kind,'naval')
        base.health=0;db.session.commit()
        with self.assertRaises(FinanceError):self.launch(base)
        self.assertEqual(db.session.query(Wojsko).one().rakiety_krotkiego_zasiegu,19)

    def test_background_job_resolves_impacts_without_open_panel(self):
        from engine.infrastructure_scheduler import run_flights_tick
        base=self.source();id=self.launch(base)
        with patch('engine.infrastructure_scheduler.game_now',return_value=NOW+timedelta(hours=1)),patch('game.military_flights.randbelow',return_value=25):
            run_flights_tick(self.app);run_flights_tick(self.app)
        db.session.expire_all()
        self.assertEqual(db.session.get(Miasto,9001).miasto_populacja,975)
        self.assertEqual(db.session.get(MilitaryFlight,id).casualties,25)
        self.assertEqual(db.session.query(MiastoStateHistory).count(),1)


class FighterRangeCarrierTests(FlightFixture):
    """12 Nov 2026: myśliwiec ma zasięg 1000 km i dowolną rakietę; lotniskowiec zabiera do 5 myśliwców."""
    def test_fighter_range_ignores_missile_type(self):
        base=self.source('air');base.garrison={'fighters':3};db.session.query(Wojsko).update({'rakiety_dalekiego_zasiegu':10,'rakiety_sredniego_zasiegu':10});db.session.commit()
        self.assertTrue(self.launch(base,missile_type='long'))                      # 100 km rakietą dalekiego zasięgu
        with patch('game.military_flights.city_point',return_value=[1500,0]):
            with self.assertRaisesRegex(FinanceError,'Zasięg myśliwca'):self.launch(base,missile_type='medium')

    def carrier_setup(self):
        from models import Wojsko
        db.session.get(Region,1).region_polozenie_id=2
        db.session.query(Wojsko).update({'lotniskowce_ilosc':1});db.session.commit()
        port=self.source('naval');air=self.source('air');air.garrison={'fighters':6};db.session.commit()
        return port,air

    def test_carrier_sails_with_fighters_and_attacks_from_sea(self):
        from game.military_flights import busy_fighters
        port,air=self.carrier_setup()
        with self.assertRaisesRegex(FinanceError,'najwyżej 5'):self.change('sail_carrier',base_id=port.id,air_base_id=air.id,fighters=6,x=50,y=0)
        self.change('sail_carrier',base_id=port.id,air_base_id=air.id,fighters=5,x=50,y=0)
        carrier=db.session.scalar(select(MilitaryVessel).where(MilitaryVessel.kind=='carriers'))
        self.assertEqual((carrier.fighters,carrier.air_base_id,carrier.status),(5,air.id,'sailing'))
        self.assertEqual(busy_fighters(db.session,air.id),5)
        with self.assertRaisesRegex(FinanceError,'wolnego lotniskowca'):self.change('sail_carrier',base_id=port.id,air_base_id=air.id,fighters=1,x=50,y=0)
        with self.assertRaises(FinanceError):self.change('garrison',base_id=air.id,garrison={'soldiers':0,'fighters':0})   # zaokrętowanych nie można wycofać
        flight=create_order(1,{'kind':'air','region_id':2,'city_id':9001,'carrier_id':carrier.id,'source_base_id':None,'missile_type':'short','missiles':1})
        row=db.session.get(MilitaryFlight,flight);self.assertEqual((row.source_vessel_id,row.source_base_id),(carrier.id,None))

    def test_sunk_carrier_loses_its_fighters(self):
        from models import Wojsko
        from game.military_flights import sink_carrier
        port,air=self.carrier_setup()
        self.change('sail_carrier',base_id=port.id,air_base_id=air.id,fighters=4,x=50,y=0)
        carrier=db.session.scalar(select(MilitaryVessel).where(MilitaryVessel.kind=='carriers'))
        army=db.session.query(Wojsko).one();before=army.mysliwce_ilosc
        sink_carrier(db.session,carrier,army);db.session.commit()
        self.assertEqual(army.lotniskowce_ilosc,0);self.assertEqual(army.mysliwce_ilosc,before-4)
        self.assertEqual(db.session.get(MilitaryBase,air.id).garrison['fighters'],2)
