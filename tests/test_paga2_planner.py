"""PAGA2 etap 4 — planowanie wieloetapowe: rozkład celu na etapy, rozpoznawanie celów niemożliwych, wybór lokalizacji,
realizacja kolejnych etapów przez silnik i porzucanie planów."""
import unittest
from datetime import datetime
from unittest.mock import patch
from sqlalchemy import select
from extensions import db
from game.industry_catalog import TECHNOLOGIES
from game.paga2 import planner
from game.paga2.models import Paga2Plan,Paga2Decision,Paga2Profile
from test_paga2_foundation import Paga2Fixture


class FakeHoldings:
    def __init__(self,nodes=None,points=0,factories=(),mines=(),plants=(),stock=None,deposits=None,coastal=(1,),regions=(1,2),energy=(0.0,0.0)):
        self.nodes={k:TECHNOLOGIES[k]['cost'] if v is True else v for k,v in (nodes or {}).items()};self.points=points
        self.factories=[{'kind':k,'health':100,'region':1,'x':0,'y':0} for k in factories]
        self.mines=[{'resource':r,'ready':True,'region':1,'x':0,'y':0} for r in mines]
        self.plants=[{'kind':k,'health':3,'region':1,'x':0,'y':0} for k in plants]
        self.stock=stock or {};self.deposits=deposits or {};self.energy={'production':energy[0],'demand':energy[1]}
        self.regions=[{'id':r,'coastal':r in coastal} for r in regions];self.objects=[]
    def developed(self,node):return int(self.nodes.get(node,0))>=TECHNOLOGIES[node]['cost']
    def missing_points(self,node):return max(0,TECHNOLOGIES[node]['cost']-int(self.nodes.get(node,0)))
    def has_factory(self,kind):return any(f['kind']==kind for f in self.factories)
    def has_mine(self,resource):return any(m['resource']==resource for m in self.mines)
    def mine_ready(self,resource):return self.has_mine(resource)
    def has_plant(self,kind):return any(p['kind']==kind for p in self.plants)
    def energy_surplus(self):return self.energy['production']-self.energy['demand']
    def coastal_regions(self):return [r['id'] for r in self.regions if r['coastal']]
    def deposit_regions(self,resource):return self.deposits.get(resource,[])
    def objects_in(self,region):return 0


def statuses(plan):return [(s['key'],s['status']) for s in plan.steps]


class DecompositionTests(unittest.TestCase):
    def test_technology_path_from_root_with_points(self):
        plan=planner.decompose('tech:tanks',FakeHoldings())
        keys=[s['key'] for s in plan.steps]
        self.assertEqual(keys,['buy:method','invest:method','buy:arms_industry','invest:arms_industry','buy:armored','invest:armored','buy:tanks','invest:tanks'])
        self.assertEqual(plan.next()['key'],'buy:method')
        self.assertEqual(plan.steps[0]['params']['count'],25);self.assertEqual(plan.steps[0]['cost'],25*planner.POINT_PRICE)
        # Wystarczające punkty: od razu inwestycja, bez zakupu.
        plan=planner.decompose('tech:arms_industry',FakeHoldings(nodes={'method':True},points=40))
        self.assertEqual(statuses(plan),[('tech:method','done'),('invest:arms_industry','ready')])
        # Punkty przydzielane od korzenia: brakujące tylko dla technologii potomnej.
        plan=planner.decompose('tech:armored',FakeHoldings(nodes={'method':True},points=30))
        self.assertEqual(statuses(plan),[('tech:method','done'),('invest:arms_industry','ready'),('buy:armored','ready'),('invest:armored','blocked')])
        self.assertEqual(plan.steps[2]['params']['count'],60)

    def test_factory_needs_technology_resources_energy_then_building(self):
        h=FakeHoldings(nodes={'method':True,'arms_industry':True,'armored':True,'tanks':True,'mining_industry':True,'mine_oil':True,'it_industry':True,'chip_simple':True,
                              'mine_surface':True,'energy_industry':True,'power_wind':True},
                       deposits={'ropa_naftowa':[2],'zloto':[1],'srebro':[1]},energy=(0,0))
        plan=planner.decompose('factory:tanks',h)
        kinds=[(s['kind'],s['status']) for s in plan.steps if s['status']!='done']
        self.assertIn(('acquire','external'),kinds)                     # żelazo: brak złóż -> handel
        self.assertEqual(plan.next()['kind'],'build_mine')               # najpierw surowce
        self.assertEqual([s['kind'] for s in plan.steps][-1],'build_factory')
        self.assertIn('build_power',[s['kind'] for s in plan.steps])     # energia dla fabryki
        self.assertIsNone(plan.impossible);self.assertFalse(plan.done())
        # Wszystko gotowe poza budową fabryki.
        h.mines=[{'resource':r,'ready':True,'region':1,'x':0,'y':0} for r in ('ropa_naftowa',)];h.factories=[{'kind':'chips','health':100,'region':1,'x':0,'y':0}]
        h.energy={'production':100,'demand':0};h.stock={'zelazo':5}
        plan=planner.decompose('factory:tanks',h)
        self.assertEqual(plan.next()['kind'],'build_factory');self.assertEqual(plan.next()['status'],'ready')
        h.factories.append({'kind':'tanks','health':100,'region':1,'x':0,'y':0})
        self.assertTrue(planner.decompose('factory:tanks',h).done())

    def test_energy_choice_and_count(self):
        h=FakeHoldings(nodes={'method':True,'energy_industry':True,'power_coal':True,'mining_industry':True,'mine_coal':True},deposits={'wegiel_kamienny':[1]},energy=(0,1000))
        plan=planner.Plan();plan.points={'left':0}
        self.assertFalse(planner.energy(plan,10,h,'x'))
        power=next(s for s in plan.steps if s['kind']=='build_power')
        self.assertEqual(power['params']['kind'],'coal');self.assertIn('ok. 11',power['label'])
        plan=planner.Plan();plan.points={'left':0}
        planner.energy(plan,5,FakeHoldings(energy=(0,0)),'y')
        self.assertEqual(next(s for s in plan.steps if s['kind']=='build_power')['params']['kind'],'wind')

    def test_no_new_plants_while_existing_ones_lack_fuel(self):
        h=FakeHoldings(nodes={'method':True,'energy_industry':True,'power_coal':True,'mining_industry':True,'mine_coal':True},deposits={'wegiel_kamienny':[1]},energy=(0,1000),mines=['wegiel_kamienny'])
        h.plants=[{'kind':'coal','level':1,'health':3,'running':False,'region':1,'x':0,'y':0}]
        h.idle_capacity=lambda:100.0
        plan=planner.Plan();plan.points={'left':0}
        self.assertFalse(planner.energy(plan,10,h,'x'))
        kinds=[s['kind'] for s in plan.steps]
        self.assertNotIn('build_power',kinds);self.assertIn('acquire',kinds)   # najpierw paliwo, nie kolejna elektrownia

    def test_impossible_goals_are_recognised(self):
        self.assertIn('Brak złóż',planner.decompose('mine:zelazo',FakeHoldings()).impossible)
        self.assertIn('nadmorskiego',planner.decompose('factory:shipyard',FakeHoldings(coastal=())).impossible)
        self.assertIn('paliwa',planner.decompose('power:nuclear',FakeHoldings()).impossible)
        self.assertIn('niedostępna',planner.decompose('tech:nuclear_missiles',FakeHoldings()).impossible)
        self.assertTrue(planner.decompose('mine:zloto',FakeHoldings(mines=['zloto'])).done())

    def test_mine_targets_deposit_regions(self):
        plan=planner.decompose('mine:zloto',FakeHoldings(nodes={'method':True,'mining_industry':True,'mine_surface':True},deposits={'zloto':[7]}))
        self.assertEqual(plan.next()['params']['regions'],[7])


class LocationTests(unittest.TestCase):
    SQUARE={'type':'Polygon','coordinates':[[[0,0],[10,0],[10,10],[0,10],[0,0]]]}
    def features(self,path):return [{'properties':{'region_id':1},'geometry':self.SQUARE}]

    def test_point_inside_region_and_away_from_objects(self):
        from game.paga2 import location
        with patch('game.paga2.location.map_features',self.features):
            point=location.pick_point(1,[(5,5)],km_per_unit=10,seed='a')
            self.assertTrue(0<=point[0]<=10 and 0<=point[1]<=10)
            self.assertGreaterEqual(((point[0]-5)**2+(point[1]-5)**2)**.5*10,location.MIN_DISTANCE_KM)
            self.assertEqual(point,location.pick_point(1,[(5,5)],km_per_unit=10,seed='a'))  # deterministycznie
            crowded=[(x+.5,y+.5) for x in range(10) for y in range(10)]
            relaxed=location.pick_point(1,crowded,km_per_unit=10,seed='b')
            self.assertIsNotNone(relaxed)  # gdy brak miejsca, odstęp jest zmniejszany

    def test_coastal_point_within_three_km(self):
        from game.paga2 import location
        with patch('game.paga2.location.map_features',self.features),patch('game.paga2.location.coastline_segments',return_value=[[[0,0],[10,0]]]):
            point=location.pick_point(1,[],km_per_unit=1,seed='c',coastal=True)
            self.assertIsNotNone(point);self.assertLessEqual(point[1],3.0)

    def test_site_prefers_emptier_region_and_reports_missing_region(self):
        from game.paga2 import location
        h=FakeHoldings(regions=(1,2),coastal=());h.objects_in=lambda r:5 if r==1 else 0
        with patch('game.paga2.location.pick_point',return_value=[1,1]):
            self.assertEqual(location.site(h,10,seed='s')[0],2)
        region,reason=location.site(h,10,seed='s',coastal=True)
        self.assertIsNone(region);self.assertIn('nadmorskiego',reason)


class PlannerEngineTests(Paga2Fixture,unittest.TestCase):
    def setUp(self):
        super().setUp()
        from game.paga_relationships import PagaRelationship
        from game.paga2.models import Paga2CountryState
        from models import Stosunki,DictStosunkiRelacja,DictStosunkiStan
        for model in (PagaRelationship,Paga2CountryState,Paga2Plan,Stosunki,DictStosunkiRelacja,DictStosunkiStan):model.__table__.create(db.engine,checkfirst=True)
        profile=db.session.get(Paga2Profile,1);profile.priorities=['offensive_army','trade'];db.session.commit()
        self.holdings=FakeHoldings();self.calls=[]
        def call(ctx,path,*,method='POST',json=None,form=None):self.calls.append((path,json));return 200,{'ok':True}
        for target in (patch('game.paga2.planner._holdings',lambda ctx:self.holdings),patch('game.paga2.planner._km',lambda ctx:10),
                       patch('game.paga2.engine.Context.call',call),patch('game.paga2.engine.Context.sector_start',lambda ctx,s:1e12),
                       patch('game.paga2.engine.Context.available',lambda ctx,s:1e12),patch('game.paga2.location.site',return_value=(1,[5,5]))):
            target.start();self.addCleanup(target.stop)
        self.counter=0

    def cycle(self):
        from game.paga2.engine import run
        self.counter+=1
        return db.session.get(Paga2Decision,run(self.app,1,'CYCLIC','test',request_key=f'c{self.counter}',adapters=[planner.ADAPTER],now=datetime(3000,1,1)),populate_existing=True)

    def test_plan_is_started_then_steps_executed_in_order(self):
        decision=self.cycle()
        self.assertEqual(decision.action,'PLAN_START')
        plan=db.session.scalar(select(Paga2Plan));self.assertEqual(plan.goal,'factory:tanks');self.assertEqual(plan.priority,'offensive_army')
        self.assertEqual(self.calls,[])  # rozpoczęcie planu nie jest operacją w grze
        decision=self.cycle()
        self.assertIn('BUY_POINTS',decision.action)
        path,body=self.calls[0]
        self.assertEqual(path,'/game/badania/zmien');self.assertEqual(body['action'],'buy');self.assertEqual(body['count'],25)
        self.assertEqual(body['expected_point_price'],planner.POINT_PRICE)
        # Kolejny przebieg po zakupie: inwestycja w tę samą technologię.
        self.holdings.points=25
        self.cycle()
        self.assertEqual(self.calls[-1][1],{'action':'invest','node':'method','count':25,'request_id':self.calls[-1][1]['request_id']})

    def test_build_step_uses_chosen_site(self):
        self.holdings=FakeHoldings(nodes={'method':True,'mining_industry':True,'mine_surface':True},deposits={'zloto':[1]})
        db.session.add(Paga2Plan(country_id=1,goal='mine:zloto',priority='trade',status='ACTIVE',steps=[]));db.session.commit()
        self.cycle()
        path,body=next(c for c in self.calls if c[0]=='/game/handel/wydobycie/buduj')
        self.assertEqual((body['resource'],body['region_id'],body['x'],body['y'],body['level']),('zloto',1,5,5,1))

    def test_impossible_done_and_abandoned_plans_are_closed(self):
        db.session.add_all([Paga2Plan(country_id=1,goal='mine:zelazo',priority='trade',status='ACTIVE',steps=[]),
                            Paga2Plan(country_id=1,goal='tech:method',priority='trade',status='ACTIVE',steps=[]),
                            Paga2Plan(country_id=1,goal='factory:chips',priority='environment',status='ACTIVE',steps=[])])
        db.session.commit()
        self.holdings=FakeHoldings(nodes={'method':True})
        self.cycle()
        rows={row.goal:row for row in db.session.scalars(select(Paga2Plan).execution_options(populate_existing=True))}
        self.assertEqual(rows['mine:zelazo'].status,'IMPOSSIBLE');self.assertIn('żelazo',rows['mine:zelazo'].reason)
        self.assertEqual(rows['tech:method'].status,'DONE')
        self.assertEqual(rows['factory:chips'].status,'ABANDONED')

    def test_research_purchase_respects_spending_limit(self):
        with patch('game.paga2.engine.Context.sector_start',lambda ctx,s:10*planner.POINT_PRICE),patch('game.paga2.engine.Context.available',lambda ctx,s:10*planner.POINT_PRICE):
            db.session.add(Paga2Plan(country_id=1,goal='tech:method',priority='offensive_army',status='ACTIVE',steps=[]));db.session.commit()
            decision=self.cycle()
        buy=next(o for o in decision.options if o['key'].endswith('buy:method'))
        self.assertLess(buy['payload']['count'],25)  # zakup częściowy w granicach rozwagi
        self.assertTrue(any('częściowy' in note for note in buy['notes']))

    def test_plan_without_progress_is_abandoned(self):
        self.holdings=FakeHoldings()
        with patch('game.paga2.engine.Context.sector_start',lambda ctx,s:0),patch('game.paga2.engine.Context.available',lambda ctx,s:0):
            db.session.add(Paga2Plan(country_id=1,goal='tech:method',priority='offensive_army',status='ACTIVE',steps=[],idle_cycles=planner.ABANDON_AFTER));db.session.commit()
            self.cycle()
        row=db.session.scalar(select(Paga2Plan).where(Paga2Plan.goal=='tech:method').execution_options(populate_existing=True))
        self.assertEqual(row.status,'ABANDONED');self.assertIn('Brak postępu',row.reason)

    def test_number_of_active_plans_is_limited_by_ambition(self):
        profile=db.session.get(Paga2Profile,1);profile.traits={**profile.traits,'ambition':0};db.session.commit()
        db.session.add(Paga2Plan(country_id=1,goal='tech:radar',priority='offensive_army',status='ACTIVE',steps=[]));db.session.commit()
        decision=self.cycle()
        self.assertFalse(any(o['action']=='PLAN_START' for o in decision.options))


if __name__=='__main__':unittest.main()
