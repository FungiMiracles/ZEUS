"""Rozkazy floty, silosy i powiadomienia — bez rzeczywistych ataków na UAT."""
from datetime import timedelta
from unittest.mock import patch
from sqlalchemy import select
from test_game_military_flights import FlightFixture
from test_game_military import MilitaryFixture,NOW
from extensions import db
from models import Region,Wojsko,Miasto
from game.military_models import MilitaryBase,MilitaryVessel,MilitaryFlight,MilitaryExpense,MilitaryMaintenance
from game.military_navy import vessel_position,settle_vessels,busy_vessels
from game.military_flights import complete_flights
from game.military_service import reconcile_maintenance,create_order,CAPACITIES,UPGRADE_COSTS
from game.forum_models import GameNotification
from game.finance_service import FinanceError


class NavyNuclearTests(MilitaryFixture):
    def naval(self):
        db.session.get(Region,1).region_polozenie_id=2;db.session.commit()
        base=self.base('naval');base.map_x=0;base.map_y=0;base.garrison={'warships':1};db.session.commit()
        return base

    def test_rename_ownership_and_validation(self):
        base=self.base();self.change('rename',base_id=base.id,name='  Fort Północny  ')
        self.assertEqual(db.session.get(MilitaryBase,base.id).name,'Fort Północny')
        for name in ['', ' '*5,'a'*121,'x\ny',False]:
            with self.assertRaises(FinanceError):self.change('rename',base_id=base.id,name=name)
        with self.assertRaises(FinanceError):self.change('rename',base_id=999,name='Cudza')

    def test_redirect_vessel_from_current_position(self):
        base=self.naval();self.change('sail',base_id=base.id,vessel_kind='warships',x=100,y=0)
        vessel=db.session.query(MilitaryVessel).one()
        with patch('game.military_service.game_now',return_value=NOW+timedelta(minutes=30)):
            self.change('redirect_vessel',vessel_id=vessel.id,x=50,y=100)
        vessel=db.session.get(MilitaryVessel,vessel.id)
        self.assertEqual([vessel.source_x,vessel.source_y,vessel.target_x,vessel.target_y],[50,0,50,100])   # z bieżącej pozycji
        self.assertEqual(vessel.arrives_at,NOW+timedelta(minutes=90));self.assertEqual(vessel.status,'sailing')
        with self.assertRaises(FinanceError):self.change('redirect_vessel',vessel_id=vessel.id,x='a',y=1)

    def test_sailing_interpolation_reservation_return_and_capacity(self):
        base=self.naval();self.change('sail',base_id=base.id,vessel_kind='warships',x=100,y=0)
        vessel=db.session.query(MilitaryVessel).one()
        self.assertEqual(vessel.arrives_at,NOW+timedelta(hours=1))
        self.assertEqual(vessel_position(vessel,NOW+timedelta(minutes=30)),[50,0])
        self.assertEqual(busy_vessels(db.session,base.id,'warships'),1)
        with self.assertRaises(FinanceError):self.change('sail',base_id=base.id,vessel_kind='warships',x=100,y=0)
        with self.assertRaises(FinanceError):self.change('withdraw',base_id=base.id)
        with self.assertRaises(FinanceError):self.change('garrison',base_id=base.id,garrison={'warships':0})
        with patch('game.military_geography.region_contains',return_value=True):
            with self.assertRaises(FinanceError):self.change('location',base_id=base.id,x=1,y=1)
        settle_vessels(db.session,NOW+timedelta(hours=1),1);db.session.commit()
        self.assertEqual(vessel.status,'stationed')
        with patch('game.military_service.game_now',return_value=NOW+timedelta(hours=1)):
            self.change('return_vessel',vessel_id=vessel.id,base_id=base.id)
        vessel=db.session.get(MilitaryVessel,vessel.id)
        self.assertEqual(vessel.arrives_at,NOW+timedelta(hours=2))
        settle_vessels(db.session,NOW+timedelta(hours=2),1);db.session.commit()
        settle_vessels(db.session,NOW+timedelta(hours=3),1);db.session.commit()
        self.assertEqual(vessel.status,'docked');self.assertEqual(base.garrison['warships'],1)
        self.assertEqual(busy_vessels(db.session,base.id,'warships'),0)

    def test_return_to_other_base_reserves_slot_and_transfers_once(self):
        base=self.naval();db.session.query(Wojsko).one().liczba_baz_morskich=2;db.session.commit()
        other=self.base('naval');other.map_x=100;other.map_y=0;db.session.commit()
        self.change('sail',base_id=base.id,vessel_kind='warships',x=100,y=0)
        vessel=db.session.query(MilitaryVessel).one()
        self.change('return_vessel',vessel_id=vessel.id,base_id=other.id)
        with self.assertRaises(FinanceError):self.change('garrison',base_id=other.id,garrison={'warships':1})
        settle_vessels(db.session,NOW+timedelta(hours=2),1);db.session.commit();db.session.expire_all()
        self.assertEqual(db.session.get(MilitaryBase,base.id).garrison['warships'],0)
        self.assertEqual(db.session.get(MilitaryBase,other.id).garrison['warships'],1)
        self.assertEqual(db.session.get(MilitaryVessel,vessel.id).base_id,other.id)

    def test_vessel_name_and_health_survive_return_and_next_voyage(self):
        base=self.naval();self.change('sail',base_id=base.id,vessel_kind='warships',x=100,y=0)
        vessel=db.session.query(MilitaryVessel).one();vessel.health=75;db.session.commit()
        self.change('rename_vessel',vessel_id=vessel.id,name='  Północ  ')
        self.change('return_vessel',vessel_id=vessel.id,base_id=base.id)
        settle_vessels(db.session,NOW+timedelta(seconds=1),1);db.session.commit()
        self.change('sail',base_id=base.id,vessel_kind='warships',x=100,y=0)
        vessel=db.session.query(MilitaryVessel).one()
        self.assertEqual(vessel.name,'Północ');self.assertEqual(vessel.health,75)
        for name in ['',False,'a'*121,'x\ny']:
            with self.assertRaises(FinanceError):self.change('rename_vessel',vessel_id=vessel.id,name=name)

    def test_submarine_speed_and_foreign_vessel_rejected(self):
        base=self.naval();base.level=2;base.garrison={'submarines':1};db.session.commit()
        self.change('sail',base_id=base.id,vessel_kind='submarines',x=100,y=0)
        vessel=db.session.query(MilitaryVessel).one();self.assertEqual(vessel.arrives_at,NOW+timedelta(hours=1))
        vessel.panstwo_id=2;db.session.commit()
        with self.assertRaises(FinanceError):self.change('return_vessel',vessel_id=vessel.id,base_id=base.id)
        for x in [True,float('nan'),float('inf')]:
            with self.assertRaises(FinanceError):self.change('sail',base_id=base.id,vessel_kind='submarines',x=x,y=0)

    def test_silo_cost_capacity_upgrades_and_national_head_upkeep(self):
        # 13 Nov 2026: utrzymanie liczone tylko od rakiet z głowicą nuklearną w silosie (650 mln ROI), dostępność z rzeczywistego licznika
        from game.commerce_models import ResourceStock
        silo=self.base('nuclear')
        self.assertEqual(db.session.query(MilitaryExpense).one().amount,25000000000)
        self.assertEqual(db.session.query(MilitaryMaintenance).one().amount,500000000)
        army=db.session.query(Wojsko).one();army.bron_atomowa_ilosc=5000   # pole tabeli nie daje głowic
        db.session.add(ResourceStock(panstwo_id=1,resource='nuclear_missiles',quantity=110));db.session.commit()
        self.change('garrison',base_id=silo.id,garrison={'warheads':100})
        self.assertEqual(db.session.query(MilitaryMaintenance).one().amount,500000000+100*650000000)   # 10 w magazynie — bez kosztu
        with self.assertRaises(FinanceError):self.change('garrison',base_id=silo.id,garrison={'warheads':101})
        for level in range(2,8):
            self.change('upgrade',base_id=silo.id)
            self.assertEqual(db.session.get(MilitaryBase,silo.id).level,level)
            expense=db.session.scalar(select(MilitaryExpense).where(MilitaryExpense.base_id==silo.id,MilitaryExpense.level==level))
            self.assertEqual(expense.amount,UPGRADE_COSTS[level]*2)
        self.assertEqual(CAPACITIES['nuclear'][6]['warheads'],5000)
        with self.assertRaises(FinanceError):self.change('upgrade',base_id=silo.id)

    def test_silo_shortage_disables_once_then_reactivates(self):
        silo=self.base('nuclear');self.set_budget(25000000000)
        reconcile_maintenance(db.session,1,NOW);db.session.commit()
        self.assertFalse(db.session.get(MilitaryBase,silo.id).operational)
        self.assertEqual(db.session.query(MilitaryMaintenance).one().amount,0)
        reconcile_maintenance(db.session,1,NOW);db.session.commit()
        self.assertEqual(db.session.query(GameNotification).count(),1)
        self.set_budget(26000000000);reconcile_maintenance(db.session,1,NOW);db.session.commit()
        self.assertTrue(db.session.get(MilitaryBase,silo.id).operational)


# Reuse only the common fixture setup, avoiding inherited test duplication.
class NewFlightTests(FlightFixture):
    def test_notifications_to_both_players_exactly_once(self):
        base=self.source();id=self.launch(base)
        with patch('game.military_flights.randbelow',return_value=50):
            complete_flights(db.session,NOW+timedelta(hours=1));db.session.commit()
            complete_flights(db.session,NOW+timedelta(hours=2));db.session.commit()
        notices=db.session.query(GameNotification).all()
        self.assertEqual({n.user_id for n in notices},{1,2});self.assertEqual(len(notices),2)
        self.assertTrue(all('Ofiary: 50' in n.system_text and 'Zniszczenia infrastruktury: 0' in n.system_text for n in notices))

    def test_nuclear_uses_head_and_rocket_without_casualties(self):
        # 13 Nov 2026: odpalenie zużywa tylko rakietę z głowicą nuklearną (bez rakiety konwencjonalnej); trafienie — wybuch jądrowy
        from game.commerce_models import ResourceStock
        silo=self.base('nuclear');silo.map_x=0;silo.map_y=0;silo.garrison={'warheads':2}
        db.session.add(ResourceStock(panstwo_id=1,resource='nuclear_missiles',quantity=2));db.session.commit()
        id=self.launch(silo,is_nuclear=True,missile_type='long')
        db.session.expire_all()
        self.assertEqual(db.session.get(ResourceStock,(1,'nuclear_missiles')).quantity,1)
        self.assertEqual(db.session.query(Wojsko).one().rakiety_krotkiego_zasiegu,20)
        self.assertEqual(db.session.get(MilitaryBase,silo.id).garrison['warheads'],1)
        with patch('game.military_geography.city_point',return_value=[100,0]):
            complete_flights(db.session,NOW+timedelta(hours=1));db.session.commit()
        self.assertEqual(db.session.get(Miasto,9001).miasto_populacja,0)
        self.assertEqual(db.session.get(MilitaryFlight,id).casualties,1000)

    def test_nuclear_air_and_ship_require_loaded_silo(self):
        # 13 Nov 2026: uderzenie atomowe tylko rakietą z silosu — bombowce i okręty nie przenoszą broni jądrowej
        from game.commerce_models import ResourceStock
        silo=self.base('nuclear');silo.map_x=0;silo.map_y=0;silo.garrison={'warheads':2}
        db.session.add(ResourceStock(panstwo_id=1,resource='nuclear_missiles',quantity=2));db.session.commit()
        jet=self.source('air')
        with self.assertRaisesRegex(FinanceError,'wyłącznie rakietą'):self.launch(jet,is_nuclear=True,silo_id=silo.id)
        db.session.get(Region,1).region_polozenie_id=2;db.session.commit()
        base=self.source('naval');self.change('sail',base_id=base.id,vessel_kind='warships',x=50,y=0)
        vessel=db.session.query(MilitaryVessel).one()
        with patch('game.military_flights.game_now',return_value=NOW+timedelta(minutes=30)):
            with self.assertRaisesRegex(FinanceError,'wyłącznie rakietą'):self.launch(base,is_nuclear=True,silo_id=silo.id,vessel_id=vessel.id)
        self.assertEqual(db.session.get(ResourceStock,(1,'nuclear_missiles')).quantity,2)

