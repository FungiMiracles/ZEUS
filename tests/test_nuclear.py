"""Rakiety z głowicą nuklearną (13 Nov 2026): technologia, powiadomienia, fabryka i produkcja na zamówienie,
rzeczywisty licznik głowic, odpalenie z silosu (3000 km), skutki trafienia, strefa skażenia i PAGA2."""
import unittest
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import patch
from sqlalchemy import select,text
from extensions import db
from models import Region,Wojsko,Panstwo,Miasto
from test_game_military import MilitaryFixture,NOW
from test_game_military_flights import FlightFixture
from test_game_commerce import CommerceFixture
from game.finance_service import FinanceError
from game.forum_models import GameNotification
from game.commerce_models import ResourceStock
from game.research_models import ResearchAccount,AmmunitionFactory
from game.industry_catalog import TECHNOLOGIES,FACTORIES
from game.military_models import MilitaryBase,MilitaryFlight,MilitaryExpense
from game.military_service import create_order
from game.military_flights import complete_flights
from game.nuclear_models import NuclearOrder,NuclearZone
from game import nuclear


def stock(code,country=1):
    db.session.expire_all();row=db.session.get(ResourceStock,(country,code));return int(row.quantity) if row else 0


def put(code,quantity,country=1):
    row=db.session.get(ResourceStock,(country,code))
    if row is None:db.session.add(ResourceStock(panstwo_id=country,resource=code,quantity=quantity))
    else:row.quantity=quantity
    db.session.commit()


class NuclearResearchTests(MilitaryFixture):
    def setUp(self):
        super().setUp()
        db.session.execute(text("INSERT INTO game_state_budget_allocations(id,budget_id,category_code,amount) VALUES(2,1,'research',1000000000000)"))
        db.session.execute(text("UPDATE panstwa SET status='aktywne'"));db.session.commit()
        for target in ['game.research_service.game_now','game.research.game_now']:
            clock=patch(target,return_value=NOW);clock.start();self.addCleanup(clock.stop)

    def invest(self,count=1):
        from game.research_service import change_research
        change_research(1,{'action':'invest','node':'nuclear_missiles','count':count,'request_id':str(uuid4())});db.session.expire_all()

    def test_technology_cost_and_three_requirements(self):
        rule=TECHNOLOGIES['nuclear_missiles']
        self.assertEqual((rule['label'],rule['cost'],rule['requires']),('Rakieta z głowicą nuklearną',750,['long_missiles','mine_uranium','chip_cemium_i']))
        from game.research_timing import DURATION_DAYS
        self.assertEqual(DURATION_DAYS['nuclear_missiles'],132)
        nodes={key:TECHNOLOGIES[key]['cost'] for key in ('method','arms_industry','short_missiles','medium_missiles','long_missiles')}
        db.session.add(ResearchAccount(panstwo_id=1,points=1000,ammunition=0,nodes=nodes,timers={}));db.session.commit()
        with self.assertRaisesRegex(FinanceError,'Wydobycie uranu, Chip cemium I'):self.invest()
        self.assertEqual(db.session.get(ResearchAccount,1).points,1000)

    def test_first_investment_notifies_every_other_country_once(self):
        db.session.add(ResearchAccount(panstwo_id=1,points=1000,ammunition=0,nodes={key:value['cost'] for key,value in TECHNOLOGIES.items() if key!='nuclear_missiles'},timers={}))
        db.session.commit()
        self.invest(10)
        texts=lambda user:[n.system_text for n in db.session.scalars(select(GameNotification).where(GameNotification.user_id==user))]
        self.assertTrue(any(t.startswith('Badania atomowe:') and 'Rakieta z głowicą nuklearną' in t for t in texts(2)))
        self.assertTrue(any(t.startswith('Badania atomowe:') for t in texts(3)))
        self.assertFalse(any(t.startswith('Badania atomowe:') for t in texts(1)))
        self.invest(10)   # kolejne inwestycje — bez ponownego powiadomienia
        self.assertEqual(sum(t.startswith('Badania atomowe:') for t in texts(2)),1)


class NuclearFactoryTests(CommerceFixture):
    def setUp(self):
        super().setUp()
        self.login(1)
        db.session.add(ResearchAccount(panstwo_id=1,points=0,ammunition=0,nodes={key:value['cost'] for key,value in TECHNOLOGIES.items()},timers={}))
        db.session.commit()
        self.now=NOW
        for target in ['game.research_service.game_now','game.industry_service.game_now','game.finance_service.game_now']:
            p=patch(target,side_effect=lambda:self.now);p.start();self.addCleanup(p.stop)

    def op(self,action,**values):
        from game.industry_service import change_industry
        data=dict(action=action,category='factory',request_id=str(uuid4()));data.update(values)
        result=change_industry(1,data);db.session.expire_all();return result

    def build(self):
        return self.op('build',kind='nuclear_missiles',level=1,region_id=1,x=10,y=10)

    def settle(self):
        from game.industry_service import settle_industry
        settle_industry(db.session,1,self.now);db.session.commit();db.session.expire_all()

    def test_catalog_cost_build_time_and_military_budget(self):
        rule=FACTORIES['nuclear_missiles']
        self.assertEqual((rule['label'],rule['levels'][0]['cost'],rule['build_days'],rule['levels'][0]['days'],rule['levels'][0]['inputs']),
                         ('Fabryka rakiet z głowicą nuklearną',37400000000,31,14,{'uran':7,'zelazo':37,'chip_cemium_i':1}))
        id=self.build()
        self.assertEqual(db.session.scalar(select(MilitaryExpense.amount).order_by(MilitaryExpense.id.desc()).limit(1)),Decimal('37400000000'))
        factory=db.session.get(AmmunitionFactory,id)
        self.assertEqual(nuclear.factory_ready_at(factory),NOW+timedelta(days=31))
        put('uran',100);put('zelazo',1000);put('chip_cemium_i',10)
        with self.assertRaisesRegex(FinanceError,'w budowie'):self.op('order',object_id=id,count=1)
        self.now=NOW+timedelta(days=40);self.settle()
        self.assertEqual(nuclear.total(db.session,1),0)   # fabryka nie produkuje stale

    def test_order_consumes_materials_and_produces_one_per_14_days(self):
        id=self.build();put('uran',100);put('zelazo',1000);put('chip_cemium_i',10)
        self.now=NOW+timedelta(days=31)
        self.op('order',object_id=id,count=3)
        self.assertEqual((stock('uran'),stock('zelazo'),stock('chip_cemium_i')),(100-21,1000-111,10-3))
        with self.assertRaisesRegex(FinanceError,'realizuje już zamówienie'):self.op('order',object_id=id,count=1)
        self.now=NOW+timedelta(days=31+13);self.settle();self.assertEqual(nuclear.total(db.session,1),0)
        self.now=NOW+timedelta(days=31+14);self.settle();self.assertEqual(nuclear.total(db.session,1),1)
        self.now=NOW+timedelta(days=31+42);self.settle();self.assertEqual(nuclear.total(db.session,1),3)
        self.assertEqual(db.session.scalar(select(NuclearOrder.status)),'done')

    def test_missing_materials_and_cancel_refunds_unstarted(self):
        id=self.build();put('uran',13);put('zelazo',1000);put('chip_cemium_i',10)
        self.now=NOW+timedelta(days=31)
        with self.assertRaisesRegex(FinanceError,'uran'):self.op('order',object_id=id,count=2)
        put('uran',35);self.op('order',object_id=id,count=5)
        self.now=NOW+timedelta(days=31+15);self.op('cancel_order',object_id=id)
        # 1 ukończona, 1 w produkcji (przepada), 3 niezaczęte — surowce wracają
        self.assertEqual(nuclear.total(db.session,1),1)
        self.assertEqual((stock('uran'),stock('chip_cemium_i')),(21,10-5+3))

    def test_destroyed_factory_stops_production(self):
        id=self.build();put('uran',100);put('zelazo',1000);put('chip_cemium_i',10)
        self.now=NOW+timedelta(days=31);self.op('order',object_id=id,count=3)
        factory=db.session.get(AmmunitionFactory,id);factory.health=0;factory.destroyed_at=NOW+timedelta(days=31+20);db.session.commit()
        self.now=NOW+timedelta(days=31+60);self.settle()
        self.assertEqual(nuclear.total(db.session,1),1);self.assertEqual(db.session.scalar(select(NuclearOrder.status)),'stopped')


class NuclearStrikeTests(FlightFixture):
    def setUp(self):
        super().setUp()
        db.session.execute(text("UPDATE panstwa SET status='aktywne'"));db.session.commit()
        self.silo=self.base('nuclear');self.silo.map_x=0;self.silo.map_y=0;self.silo.garrison={'warheads':3}
        put('nuclear_missiles',3)
        region=db.session.get(Region,2)
        for field in ('region_stan_infra_drogowej','region_stan_infra_kolejowej','region_stan_infra_energetycznej','region_stan_infra_mieszkalnej','region_stan_infra_portowej','region_poziom_skomunikowania'):setattr(region,field,80)
        region.region_degradacja_srodowiska=10;region.region_zanieczyszczenie_powietrza=20;db.session.commit()

    def strike(self,**extra):
        # cel 150 km od silosu — silos poza promieniem skażenia (100 km)
        with patch('game.military_flights.city_point',return_value=[150,0]):
            return self.launch(self.silo,is_nuclear=True,missile_type='long',**extra)

    def impact(self):
        with patch('game.military_geography.city_point',return_value=[150,0]):
            complete_flights(db.session,NOW+timedelta(hours=2));db.session.commit()
        db.session.expire_all()

    def test_range_3000_km_from_silo_and_real_warheads(self):
        with patch('game.military_flights.city_point',return_value=[3001,0]):
            with self.assertRaisesRegex(FinanceError,'0–3000 km'):self.launch(self.silo,is_nuclear=True,missile_type='long')
        id=self.strike();db.session.expire_all()
        self.assertEqual(nuclear.total(db.session,1),2);self.assertEqual(db.session.get(MilitaryBase,self.silo.id).garrison['warheads'],2)
        self.assertEqual(db.session.get(MilitaryFlight,id).distance_km,150)
        self.assertEqual(db.session.query(Wojsko).filter_by(panstwo_id=1).one().rakiety_dalekiego_zasiegu or 0,0)   # bez rakiety konwencjonalnej

    def test_launch_notifies_all_other_countries(self):
        self.strike()
        texts=lambda user:[n.system_text for n in db.session.scalars(select(GameNotification).where(GameNotification.user_id==user))]
        self.assertTrue(any(t.startswith('Uderzenie atomowe:') for t in texts(2)))
        self.assertTrue(any(t.startswith('Uderzenie atomowe:') for t in texts(3)))
        self.assertFalse(any(t.startswith('Uderzenie atomowe:') for t in texts(1)))

    def test_impact_zone_casualties_objects_environment_and_infrastructure(self):
        enemy=MilitaryBase(panstwo_id=2,region_id=2,kind='land',level=1,garrison={},map_x=200,map_y=0,health=100)
        far=MilitaryBase(panstwo_id=2,region_id=2,kind='land',level=1,garrison={},map_x=400,map_y=0,health=100)
        db.session.add_all([enemy,far]);db.session.commit();enemy_id,far_id=enemy.id,far.id
        id=self.strike();self.impact()
        flight=db.session.get(MilitaryFlight,id)
        self.assertTrue(flight.damage['nuclear']);self.assertEqual(flight.casualties,1000)
        self.assertEqual(db.session.get(Miasto,9001).miasto_populacja,0)
        self.assertIsNone(db.session.get(MilitaryBase,enemy_id))            # 50 km od punktu trafienia — zniszczona
        self.assertIsNotNone(db.session.get(MilitaryBase,far_id))           # 250 km — poza strefą
        self.assertIsNotNone(db.session.get(MilitaryBase,self.silo.id))     # 150 km — silos atakującego ocalał
        zone=db.session.scalar(select(NuclearZone))
        self.assertEqual((zone.x,zone.y,zone.radius_km),(150,0,100));self.assertEqual(zone.until,flight.impact_at+timedelta(days=365*3))
        region=db.session.get(Region,2)
        self.assertEqual((region.region_degradacja_srodowiska,region.region_zanieczyszczenie_powietrza),(60,70))
        for field in ('region_stan_infra_drogowej','region_stan_infra_kolejowej','region_stan_infra_energetycznej','region_stan_infra_mieszkalnej','region_stan_infra_portowej','region_poziom_skomunikowania'):
            self.assertTrue(10<=getattr(region,field)<=40,field)

    def test_intercepted_missile_leaves_no_contamination(self):
        id=self.strike()
        with patch('game.missile_defense.intercept',return_value=0):self.impact()
        self.assertIsNone(db.session.scalar(select(NuclearZone)));self.assertEqual(db.session.get(Miasto,9001).miasto_populacja,1000)
        self.assertFalse((db.session.get(MilitaryFlight,id).damage or {}).get('nuclear'))

    def test_construction_blocked_inside_zone_for_three_years(self):
        self.strike();self.impact()
        with self.assertRaisesRegex(FinanceError,'skażony'):nuclear.require_clear(db.session,170,0,NOW+timedelta(days=1))
        nuclear.require_clear(db.session,300,0,NOW+timedelta(days=1))                         # poza promieniem
        nuclear.require_clear(db.session,170,0,NOW+timedelta(days=365*3+1))                    # po 3 latach
        base=MilitaryBase(panstwo_id=1,region_id=1,kind='land',level=1,garrison={});db.session.add(base);db.session.commit()
        with patch('game.military_geography.region_contains',return_value=True),patch('game.finance_service.game_now',return_value=NOW+timedelta(days=1)):
            with self.assertRaisesRegex(FinanceError,'skażony'):self.change('location',base_id=base.id,x=170,y=0)
            self.change('location',base_id=base.id,x=300,y=0)
        self.assertEqual(db.session.get(MilitaryBase,base.id).map_x,300)

    def test_zones_endpoint_and_army_panel_real_count(self):
        self.strike();self.impact();self.login(1)
        with patch('game.finance_service.game_now',return_value=NOW+timedelta(days=1)):
            data=self.client.get('/game/strefy-skazenia').json
        self.assertEqual(len(data['zones']),1);self.assertEqual(data['zones'][0]['radiusKm'],100)
        db.session.query(Wojsko).filter_by(panstwo_id=1).one().bron_atomowa_ilosc=999;db.session.commit()
        import re
        html=self.client.get('/game/sily-zbrojne').get_data(as_text=True)
        self.assertEqual(re.search(r'Broń atomowa</span></dt>\s*<dd>([^<]*)</dd>',html).group(1).strip(),'2')


class Paga2NuclearTests(unittest.TestCase):
    def test_strike_only_in_losing_war(self):
        from game.paga2 import war
        ctx=SimpleNamespace(situation={'level':'war','occupied_regions':{}},triggers=[])
        self.assertFalse(war.losing_war(ctx,{2}))
        ctx.situation['occupied_regions']={'5':2};self.assertTrue(war.losing_war(ctx,{2}))
        ctx=SimpleNamespace(situation={'level':'war','occupied_regions':{}},triggers=[{'kind':'nuclear_strike'}]);self.assertTrue(war.losing_war(ctx,{2}))
        peace=SimpleNamespace(situation={'level':'peace','occupied_regions':{'5':2}},triggers=[])
        self.assertEqual(war.nuclear_strike_options(peace,SimpleNamespace(bases=[]),{},{},{2}),[])

    def test_triggers_classify_nuclear_events(self):
        from game.paga2 import triggers
        row=SimpleNamespace(notification_type='SYSTEM',system_text='Uderzenie atomowe: A wystrzeliło …',infrastructure_text=None)
        self.assertEqual(triggers.classify(None,row)[0],'nuclear_strike');self.assertIn('nuclear_strike',triggers.SECURITY)
        row.system_text='Badania atomowe: A rozpoczęło badania …';self.assertEqual(triggers.classify(None,row)[0],'nuclear_research')


if __name__=='__main__':unittest.main()
