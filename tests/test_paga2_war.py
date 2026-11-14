"""PAGA2 etap 8 — wojna: wypowiedzenie (tylko tryb doraźny, warunki gry, zdolność wojskowa), uderzenia rakietowe
i lotnicze (zasięg, zapas, cele z wywiadu, miasta tylko dla państw bezwzględnych), najazdy lądowe z przewagą,
okupacja, aneksja, odbijanie własnych miast i baz."""
import unittest
from datetime import datetime,timedelta
from types import SimpleNamespace as NS
from unittest.mock import patch
from game.paga2 import war
from game.paga2.scoring import score
from test_paga2_defense import forces,base
from test_paga2_diplomacy import dctx


def wctx(level='war',enemies=(7,),mode='CYCLIC',**kwargs):
    c=dctx({e:{'relation':'wrogie','state':'wojnakinetyczna'} for e in enemies},level=level,**kwargs)
    c.mode=mode;c.triggers=[];c.now=datetime(3000,6,1);c._screens={}
    c.world_summary=lambda session=None:{'neighbor_countries':[7,8]}
    return c


def screen(**extra):
    data={'missiles':{'short':{'count':100},'medium':{'count':50},'long':{'count':0}},'bases':[],'defenses':[],'power':[],'factories':[],'mines':[],'radars':[],'armies':[]}
    data.update(extra);return data


CONFIG={'cities':{'500':{'countryId':7,'regionId':'70','point':[3,0]}}}


class StrikeTests(unittest.TestCase):
    def setUp(self):
        self.distance=patch('game.paga2.war.km',lambda ctx,a,b:((a[0]-b[0])**2+(a[1]-b[1])**2)**.5*100);self.distance.start();self.addCleanup(self.distance.stop)

    def test_missile_type_follows_range_and_stock(self):
        self.assertEqual(war.missile_for(300,{'short':1}),'short')
        self.assertEqual(war.missile_for(800,{'short':5,'medium':1}),'medium')
        self.assertIsNone(war.missile_for(3000,{'short':5,'medium':5,'long':0}))

    def test_strikes_use_known_targets_and_capable_bases(self):
        launchers=base(1,kind='land',garrison={'launchers':5},x=0.0);launchers.operational=True
        empty=base(2,kind='land',garrison={'soldiers':10},x=0.0);empty.operational=True
        known=screen(bases=[{'id':9,'countryId':7,'regionId':'71','position':[2,0],'health':100},{'id':10,'countryId':8,'regionId':'80','position':[1,0],'health':100}],
                     defenses=[{'targetKind':'base','targetId':9,'countryId':7}])
        options=war.strike_options(wctx(),forces(bases=[launchers,empty]),known,CONFIG,{7})
        by={o.payload.get('target_base_id'):o for o in options}
        self.assertEqual(set(by),{9})                                   # tylko wróg, z którym trwa wojna; miasto pominięte (państwo umiarkowane)
        strike=by[9]
        self.assertEqual((strike.payload['kind'],strike.payload['source_base_id'],strike.payload['missile_type'],strike.payload['region_id']),('missile',1,'short',71))
        undefended=war.salvo(wctx(),100,False);self.assertGreater(strike.payload['missiles'],undefended)  # cel chroniony: większa salwa
        self.assertLessEqual(strike.payload['missiles'],100)

    def test_cities_only_for_ruthless_states(self):
        launchers=base(1,kind='land',garrison={'launchers':5},x=0.0);launchers.operational=True
        ruthless=wctx(traits={'agreeableness':0,'provocation':100},categories=['terrorist'])
        options=war.strike_options(ruthless,forces(bases=[launchers]),screen(),CONFIG,{7})
        self.assertEqual([o.payload.get('city_id') for o in options],[500])
        self.assertEqual(war.strike_options(wctx(traits={'agreeableness':90}),forces(bases=[launchers]),screen(),CONFIG,{7}),[])

    def test_no_strike_without_missiles_or_capable_base(self):
        launchers=base(1,kind='land',garrison={'launchers':5},x=0.0);launchers.operational=True
        self.assertEqual(war.strike_options(wctx(),forces(bases=[launchers]),screen(missiles={'short':{'count':0}}),CONFIG,{7}),[])
        self.assertEqual(war.strike_options(wctx(),forces(bases=[]),screen(),CONFIG,{7}),[])


class LandTests(unittest.TestCase):
    def setUp(self):
        self.intel={'targets':{},'training':{},'marching':set()};self.plans={};self.updates=[]
        for target in (patch('game.paga2.war.km',lambda ctx,a,b:100.0),patch('game.paga2.war.battle_intel',lambda ctx:self.intel),
                       patch('game.paga2.war.war_plans',lambda ctx:self.plans),patch('game.paga2.war.update_plan',lambda *a,**k:self.updates.append((a,k)))):
            target.start();self.addCleanup(target.stop)

    def land_base(self,soldiers=10000,tanks=100):
        b=base(1,kind='land',garrison={'soldiers':soldiers,'tanks':tanks,'armored':0},x=0.0);b.operational=True;return b

    def test_attack_only_with_margin_and_scaled_units(self):
        f=forces(bases=[self.land_base()],army={'wyszkolenie_ladowe':100})
        [attack]=war.land_options(wctx(traits={'loss_tolerance':50}),f,screen(),CONFIG,{7},[])
        self.assertEqual((attack.action,attack.payload['target_kind'],attack.payload['target_id']),('LAND_ATTACK','city',500))
        self.assertLess(attack.payload['soldiers'],10000)                # nie cały garnizon — tyle, ile potrzeba z zapasem
        self.assertEqual(war.land_options(wctx(),forces(bases=[self.land_base(soldiers=100,tanks=0)]),screen(),CONFIG,{7},[]),[])

    def test_already_occupied_enemy_city_is_not_attacked_again(self):
        # 14 Nov 2026: gra odrzucała 906 takich ataków („Ten obiekt jest już pod kontrolą naszego państwa.”).
        f=forces(bases=[self.land_base()],army={'wyszkolenie_ladowe':100})
        mine=screen(occupations=[{'kind':'city','cityId':500,'baseId':None,'occupierId':1,'ownerId':7,'status':'ACTIVE'}])
        self.assertEqual(war.land_options(wctx(),f,mine,CONFIG,{7},[]),[])
        foreign=screen(occupations=[{'kind':'city','cityId':500,'baseId':None,'occupierId':9,'ownerId':7,'status':'ACTIVE'}])
        self.assertEqual(len(war.land_options(wctx(),f,foreign,CONFIG,{7},[])),1)

    def test_visible_occupiers_raise_estimate_and_recapture_preferred(self):
        occupied=screen(armies=[{'status':'OCCUPYING','targetCityId':600,'units':{'soldiers':5000,'tanks':100,'armored':0}}])
        self.assertAlmostEqual(war.battle_estimate(wctx(),'city',None,600,occupied),(5000+500)*1.2)
        f=forces(bases=[self.land_base(soldiers=20000,tanks=300)])
        options=war.land_options(wctx(),f,occupied,{'cities':{}},{7},[('city',600,[1,1],7,None,True)])
        [recapture]=options
        self.assertEqual(recapture.action,'RECAPTURE');self.assertGreater(recapture.base,10)

    def test_known_enemy_training_from_battles_raises_estimate(self):
        occupied=screen(armies=[{'status':'OCCUPYING','targetCityId':600,'units':{'soldiers':1000,'tanks':0,'armored':0}}])
        self.assertAlmostEqual(war.battle_estimate(wctx(),'city',None,600,occupied,7),1200.0)
        self.intel['training']={7:800}
        self.assertAlmostEqual(war.battle_estimate(wctx(),'city',None,600,occupied,7),8000.0)
        self.intel['targets']={('city',601):{'defeats':1,'last':{'strength':4321.0}}}
        self.assertEqual(war.battle_estimate(wctx(),'city',None,601,screen(),7),4321.0)   # bez widocznych jednostek: siła z ostatniej bitwy

    def test_no_new_wave_while_army_is_marching(self):
        self.intel['marching']={('city',500)}
        self.assertEqual(war.land_options(wctx(),forces(bases=[self.land_base()]),screen(),CONFIG,{7},[]),[])

    def test_defeats_raise_margin_and_lead_to_preparation_instead_of_new_attack(self):
        f=forces(bases=[self.land_base(soldiers=10000,tanks=100)],army={'wyszkolenie_ladowe':100},soldiers={'land':5000,'air':0,'naval':0})
        occupied=screen(armies=[{'status':'OCCUPYING','targetCityId':600,'units':{'soldiers':5000,'tanks':0,'armored':0}}])
        target=[('city',600,[1,1],7,None,True)]
        [attack]=war.land_options(wctx(),f,occupied,{'cities':{}},{7},target)
        self.assertEqual(attack.action,'RECAPTURE')                             # 10 500 ≥ 6 000 × 1,5
        self.intel['targets']={('city',600):{'defeats':3,'last':{'strength':9000.0}}}
        [prepare]=war.land_options(wctx(),f,occupied,{'cities':{}},{7},target)
        self.assertEqual(prepare.action,'WAR_PREPARE')                          # po 3 porażkach margines ×2,4 → 14 400 > 10 500: przygotowanie
        self.assertEqual(prepare.payload['goal'],'recapture:city:600');self.assertEqual(prepare.payload['steps'][0]['status'],'blocked')
        self.plans={('city',600):(42,'recapture:city:600')}
        options={o.action:o for o in war.land_options(wctx(),f,occupied,{'cities':{}},{7},target)}
        self.assertEqual(set(options),{'PREPARE_REINFORCE','PREPARE_TRAINING'})
        self.assertEqual(options['PREPARE_REINFORCE'].payload['garrison']['soldiers'],10000)  # garnizon pełny do pojemności poziomu 1
        self.assertEqual(options['PREPARE_TRAINING'].payload['branch'],'land');self.assertEqual(options['PREPARE_TRAINING'].payload['plan_id'],42)

    def test_ready_army_attacks_with_plan_bonus_and_closes_plan(self):
        f=forces(bases=[self.land_base(soldiers=10000,tanks=100)],army={'wyszkolenie_ladowe':300})
        self.intel['targets']={('city',600):{'defeats':2,'last':{'strength':4000.0}}};self.plans={('city',600):(42,'recapture:city:600')}
        [attack]=war.land_options(wctx(),f,screen(),{'cities':{}},{7},[('city',600,[1,1],7,None,True)])
        self.assertEqual(attack.action,'RECAPTURE');self.assertEqual(attack.payload['plan_id'],42)
        c=wctx();c.call=lambda path,**kw:(200,{'ok':True});c._forces=None
        with patch('game.paga2.war.rid',lambda ctx,o:'r'):war.execute(c,attack)
        self.assertTrue(any(k.get('status')=='DONE' for a,k in self.updates))

    def test_finished_target_closes_plan(self):
        self.plans={('city',999):(7,'recapture:city:999')}
        war.land_options(wctx(),forces(bases=[self.land_base()]),screen(),CONFIG,{7},[])
        self.assertTrue(any(a[0]==7 and k.get('status')=='DONE' for a,k in self.updates))

    def test_no_land_attack_on_non_neighbours(self):
        f=forces(bases=[self.land_base()])
        far={'cities':{'900':{'countryId':9,'regionId':'90','point':[5,5]}}}
        self.assertEqual(war.land_options(wctx(enemies=(9,)),f,screen(),far,{9},[]),[])


class OccupationTests(unittest.TestCase):
    def rows(self,*rows):
        class FakeSession:
            def __init__(self,*a):pass
            def __enter__(self):return self
            def __exit__(self,*a):return False
            def scalars(self,q):return list(rows)
            def expunge(self,r):pass
        return patch('game.paga2.war.Session',FakeSession),patch('game.paga2.war.db',NS(engine=None))

    def test_pending_occupation_requires_decision_and_annexation_after_30_days(self):
        c=wctx()
        pending=NS(id=1,kind='region',occupier_id=1,owner_id=7,region_id=70,status='PENDING',started_at=None)
        ready=NS(id=2,kind='region',occupier_id=1,owner_id=7,region_id=71,status='ACTIVE',started_at=c.now-timedelta(days=31))
        early=NS(id=3,kind='region',occupier_id=1,owner_id=7,region_id=72,status='ACTIVE',started_at=c.now-timedelta(days=5))
        a,b=self.rows(pending,ready,early)
        with a,b:options,recapture=war.occupation_options(c)
        actions=[(o.action,o.payload['occupation_id']) for o in options]
        self.assertEqual(actions,[('OCCUPY',1),('OCCUPY_DECLINE',1),('ANNEX',2)])
        self.assertTrue(all(o.payload.get('required') for o in options if o.payload['occupation_id']==1))
        self.assertEqual(recapture,[])

    def test_own_occupied_city_becomes_recapture_target(self):
        a,b=self.rows(NS(id=4,kind='city',occupier_id=7,owner_id=1,city_id=600,base_id=None,region_id=10,status='ACTIVE',started_at=None))
        with a,b,patch('game.military_geography.city_point',return_value=[1,1]):_,recapture=war.occupation_options(wctx())
        self.assertEqual(recapture,[('city',600,[1,1],7,None,True)])


class ShipmentTargetTests(unittest.TestCase):
    def test_enemy_cargo_ships_are_targets(self):
        c=wctx();c.now=datetime(3000,6,1,12)
        screen={'tradeShips':[{'id':5,'canAttack':True,'health':100,'regionId':'71','countryId':9,'route':[[0,0],[100,0]],'startsAt':'3000-06-01T10:00:00Z','arrivesAt':'3000-06-01T14:00:00Z'},
                              {'id':6,'canAttack':False,'health':100,'regionId':'71','countryId':4,'route':[[0,0],[100,0]],'startsAt':'3000-06-01T10:00:00Z','arrivesAt':'3000-06-01T14:00:00Z'}]}
        targets=[t for t in war.enemy_targets(c,screen,{},{9}) if t[0]=='shipment']
        self.assertEqual(targets,[('shipment',5,'71',[50.0,0.0],9,False)])


class NavalTests(unittest.TestCase):
    def test_redirect_far_vessel_sail_free_ship_and_return_in_peace(self):
        c=wctx();c._vessels=[war.NSV(5,'warships','stationed',2,[0,0],[0,0]),war.NSV(6,'warships','stationed',2,[1900,0],[1900,0])]
        naval=base(2,kind='naval',garrison={'soldiers':5,'warships':3},x=0.0)
        targets=[('city',1,'71',[2000,0],9,False)]
        with patch.object(war,'km',lambda ctx,a,b:abs(a[0]-b[0])),patch.object(war,'busy',return_value=2):
            options={o.key:o for o in war.naval_options(c,forces(bases=[naval]),targets,{9})}
        self.assertEqual(options['war:vessel:redirect:5'].payload,{'action':'redirect_vessel','vessel_id':5,'x':2000,'y':0,'group':'vessel:5'})
        self.assertNotIn('war:vessel:redirect:6',options)                       # już blisko wroga
        self.assertEqual(options['war:vessel:sail:2:warships'].payload['action'],'sail')
        peace=war.naval_options(c,forces(bases=[naval]),[],set())
        self.assertEqual({o.payload['action'] for o in peace},{'return_vessel'})


    def test_sail_and_redirect_targets_are_moved_offshore(self):
        # 14 Nov 2026: gra przyjmuje cel rejsu tylko na wodzie ≥2 km od brzegu — miasto/baza wroga leżą na lądzie.
        c=wctx();c._vessels=[war.NSV(5,'warships','stationed',2,[0,0],[0,0])]
        naval=base(2,kind='naval',garrison={'soldiers':5,'warships':3},x=0.0)
        targets=[('city',1,'71',[2000,0],9,False)]
        with patch.object(war,'km',lambda ctx,a,b:abs(a[0]-b[0])),patch.object(war,'busy',return_value=2),\
             patch.object(war,'sea_point',lambda ctx,point:[point[0]-7,point[1]+3]):
            options={o.key:o for o in war.naval_options(c,forces(bases=[naval]),targets,{9})}
        self.assertEqual((options['war:vessel:sail:2:warships'].payload['x'],options['war:vessel:sail:2:warships'].payload['y']),(1993,3))
        self.assertEqual((options['war:vessel:redirect:5'].payload['x'],options['war:vessel:redirect:5'].payload['y']),(1993,3))

    def test_sea_point_uses_navy_router_offshore_and_caches(self):
        calls=[]
        router=type('R',(),{'offshore':lambda self,point:calls.append(point) or [point[0]+1,point[1]]})()
        with patch('game.sea_routes._navy_router',return_value=router),patch('game.military_flights.calibration',return_value=type('C',(),{'km_per_unit':2.0})()),\
             patch.object(war,'Session'),patch.object(war,'db'):
            c=wctx()
            self.assertEqual(war.sea_point(c,[10,20]),[11.0,20.0])
            self.assertEqual(war.sea_point(c,[10,20]),[11.0,20.0])
        self.assertEqual(calls,[[10.0,20.0]])

class DeclareTests(unittest.TestCase):
    def test_declaration_only_in_immediate_mode_and_for_war_relations(self):
        relations={7:{'relation':'wrogie','state':'pokoj'},8:{'relation':'dobre','state':'pokoj'},9:{'relation':'zle','state':'wojnakinetyczna'}}
        staffed=forces(bases=[base(1,garrison={'soldiers':5})])
        c=wctx(level='threat',enemies=());c.situation['relations']=relations
        self.assertEqual(war.declare_options(c,staffed),[])
        c.mode='IMMEDIATE'
        [declare]=war.declare_options(c,staffed)
        self.assertEqual(declare.payload['target_id'],7);self.assertIsNone(war.check(c,declare))

    def test_no_capability_blocks_declaration(self):
        c=wctx(level='threat',enemies=(),mode='IMMEDIATE');c.situation['relations']={7:{'relation':'wrogie','state':'pokoj'}}
        [declare]=war.declare_options(c,forces(bases=[],budget=0))
        self.assertIn('Brak zdolności',war.check(c,declare))

    def test_distant_country_needs_long_range_means(self):
        c=wctx(level='threat',enemies=(),mode='IMMEDIATE');c.situation['relations']={30:{'relation':'wrogie','state':'pokoj'}}
        [declare]=war.declare_options(c,forces(bases=[base(1,garrison={'soldiers':5,'tanks':10})]),{'missiles':{'short':{'count':50}}})
        self.assertIn('odległym',war.check(c,declare))                      # tylko czołgi i rakiety krótkiego zasięgu
        [declare]=war.declare_options(c,forces(bases=[base(1,garrison={'soldiers':5})]),{'missiles':{'long':{'count':4}}})
        self.assertIsNone(war.check(c,declare))
        [declare]=war.declare_options(c,forces(bases=[base(1,kind='naval',garrison={'soldiers':5,'submarines':2})]),{})
        self.assertIsNone(war.check(c,declare));self.assertIn('okręty podwodne 2',declare.notes[0])

    def test_imperialist_scores_war_higher_than_pacifist(self):
        def option(**kw):
            c=wctx(level='threat',enemies=(),mode='IMMEDIATE',**kw);c.situation['relations']={7:{'relation':'wrogie','state':'pokoj'}}
            return score(war.declare_options(c,forces(bases=[base(1,garrison={'soldiers':5})]))[0],c)
        hawk=option(traits={'militarism':95,'expansionism':95,'agreeableness':5},categories=['imperialist'],priorities=['conquest'])
        dove=option(traits={'militarism':5,'expansionism':5,'agreeableness':95},categories=['welfare'],priorities=['welfare'])
        self.assertGreater(hawk.score,dove.score+40)


class ExecuteTests(unittest.TestCase):
    def test_payloads(self):
        from game.paga2.scoring import Option
        c=wctx();calls=[];c.call=lambda path,**kw:(calls.append((path,kw.get('json') or kw.get('form'))) or (200,{}))
        c._forces=None
        war.execute(c,Option('a','war','WAR','w',payload={'kind':'WAR','target_id':7,'group':'g','capable':True}))
        war.execute(c,Option('b','war','STRIKE_BASE','s',payload={'kind':'missile','region_id':71,'source_base_id':1,'missile_type':'short','missiles':5,'target_base_id':9,'group':'g'}))
        war.execute(c,Option('c','war','RECAPTURE','r',payload={'target_kind':'city','target_id':600,'source_base_id':1,'soldiers':10,'tanks':0,'armored':0,'group':'g'}))
        war.execute(c,Option('d','war','OCCUPY','o',payload={'occupation_id':1,'occupy':True,'group':'g','required':True}))
        war.execute(c,Option('e','war','ANNEX','x',payload={'action':'annex','occupation_id':2,'group':'g'}))
        self.assertEqual(calls[0],('/game/dyplomacja/akcje',{'kind':'WAR','target_id':'7'}))
        self.assertEqual(calls[1][0],'/game/panel-wojenny/rozkaz');self.assertNotIn('group',calls[1][1])
        self.assertEqual(calls[2][0],'/game/panel-wojenny/armia-ladowa');self.assertIn('request_id',calls[2][1])
        self.assertEqual(calls[3][1],{'occupation_id':1,'occupy':True});self.assertEqual(calls[4][1],{'action':'annex','occupation_id':2})


if __name__=='__main__':unittest.main()


class WithdrawalTests(unittest.TestCase):
    def setUp(self):
        self.rows=[];self.prepare={}
        class FakeSession:
            def __init__(inner,*a):pass
            def __enter__(inner):return inner
            def __exit__(inner,*a):return False
            def scalars(inner,q):return list(self.rows)
            def expunge(inner,r):pass
        for target in (patch('game.paga2.war.Session',FakeSession),patch('game.paga2.war.db',NS(engine=None)),patch('game.paga2.war.preparation_bases',lambda ctx:self.prepare)):
            target.start();self.addCleanup(target.stop)

    def occupation(self,owner=7,region=70,status='ACTIVE',kind='city'):
        return NS(id=1,kind=kind,city_id=600,base_id=None,region_id=region,owner_id=owner,occupier_id=1,status=status)

    def armies(self,soldiers=500):
        return screen(armies=[{'status':'OCCUPYING','countryId':1,'targetCityId':600,'units':{'soldiers':soldiers,'tanks':3,'armored':0}}])

    def home(self,soldiers=9800,kind='land'):
        b=base(5,kind=kind,garrison={'soldiers':soldiers,'tanks':99,'armored':0},x=0.0);b.operational=True;return b

    def test_withdraw_after_war_ends_only_what_fits(self):
        self.rows=[self.occupation(owner=7)]
        [option]=war.withdraw_options(wctx(level='peace',enemies=()),forces(bases=[self.home()]),self.armies())
        self.assertEqual(option.action,'OCCUPATION_WITHDRAW')
        self.assertEqual((option.payload['soldiers'],option.payload['tanks'],option.payload['base_id']),(200,1,5))  # tylko wolne miejsca bazy
        self.assertEqual(option.payload['action'],'withdraw')

    def test_no_withdrawal_during_war_without_reason(self):
        self.rows=[self.occupation(owner=7)]
        self.assertEqual(war.withdraw_options(wctx(),forces(bases=[self.home()]),self.armies()),[])

    def test_withdraw_after_declining_region_unless_imperialist(self):
        self.rows=[self.occupation(owner=7),NS(id=2,kind='region',region_id=70,owner_id=7,occupier_id=1,status='DECLINED',city_id=None,base_id=None)]
        self.assertEqual(len(war.withdraw_options(wctx(),forces(bases=[self.home(soldiers=0)]),self.armies())),1)
        self.assertEqual(war.withdraw_options(wctx(categories=['imperialist']),forces(bases=[self.home(soldiers=0)]),self.armies()),[])

    def test_troops_go_to_preparation_base_for_own_recapture(self):
        self.rows=[self.occupation(owner=7)];self.prepare={9:42}
        other=self.home(soldiers=0);other.id=8;prep=self.home(soldiers=0);prep.id=9
        [option]=war.withdraw_options(wctx(),forces(bases=[other,prep]),self.armies())
        self.assertEqual(option.payload['base_id'],9);self.assertIn('odbicia',option.notes[0])
