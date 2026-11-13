"""PAGA2 etap 6 — obrona państwa i siły zbrojne: bazy (rozmieszczenie, lokalizacja wg zagrożenia, garnizon, rozbudowa,
wycofanie, likwidacja), obrona przeciwrakietowa, radary, szkolenie oraz wykonanie przez operacje gracza."""
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch
from game.paga2 import defense
from game.paga2.scoring import score
from test_paga2_economy import EconomyCtx
from test_paga2_planner import FakeHoldings


def forces(bases=(),defenses=(),radars=(),slots=None,free=None,soldiers=None,budget=1e11,capital=5,army=None,ammunition=0):
    f=NS(bases=list(bases),defenses=list(defenses),radars=list(radars),capital=capital,budget_available=budget,budget_total=budget,has_budget=True,ammunition=ammunition)
    f.slots=slots if slots is not None else {'land':2,'air':1,'naval':1,'nuclear':None}
    f.free=free if free is not None else {'tanks':500,'launchers':50,'armored':80,'fighters':40,'warships':3,'submarines':2,'warheads':0}
    f.free_soldiers=soldiers if soldiers is not None else {'land':50000,'air':20000,'naval':15000}
    f.army=army if army is not None else {'wyszkolenie_ladowe':300,'wyszkolenie_morskie':200,'wyszkolenie_powietrzne':250}
    return f


def base(id,kind='land',level=1,garrison=None,region=1,health=100,x=1.0):
    return NS(id=id,kind=kind,level=level,garrison=garrison or {},region_id=region,health=health,map_x=x,map_y=x)


def ctx(level='peace',**kwargs):
    c=EconomyCtx(level=level,**kwargs);c.situation.update(at_war=[9] if level=='war' else [],hostile=[],threats=[]);return c


class BaseTests(unittest.TestCase):
    def test_deploy_options_use_free_slots_and_capacity(self):
        options={o.payload['kind']:o for o in defense.base_options(ctx(),forces(),{}) if o.action=='BASE_DEPLOY'}
        self.assertEqual(set(options),{'land','air','naval'})
        self.assertEqual(options['land'].payload['garrison'],{'soldiers':10000,'tanks':100,'launchers':25,'armored':25})
        self.assertEqual(options['naval'].payload['garrison'],{'soldiers':10000,'warships':1,'submarines':0})
        self.assertGreater(options['land'].cost,0);self.assertEqual(options['land'].sector,'armed_forces')
        none=defense.base_options(ctx(),forces(slots={'land':0,'air':0,'naval':0,'nuclear':None}),{})
        self.assertFalse([o for o in none if o.action=='BASE_DEPLOY'])
        silo={o.payload['kind']:o for o in defense.base_options(ctx(),forces(free={'warheads':30}),{}) if o.action=='BASE_DEPLOY'}['nuclear']
        self.assertEqual(silo.payload['garrison'],{'warheads':30});self.assertGreaterEqual(silo.cost,25.5e9)

    def test_peace_uses_only_part_of_base_slots(self):
        existing=[base(i,kind='land',garrison={'soldiers':1}) for i in range(1,5)]
        calm=ctx(traits={'militarism':0})                         # 30% miejsc: 4 z 6 to już za dużo
        self.assertFalse([o for o in defense.base_options(calm,forces(bases=existing,slots={'land':2,'air':0,'naval':0,'nuclear':None}),{}) if o.payload.get('kind')=='land' and o.action=='BASE_DEPLOY'])
        war=ctx('war',traits={'militarism':0})
        self.assertTrue([o for o in defense.base_options(war,forces(bases=existing,slots={'land':2,'air':0,'naval':0,'nuclear':None}),{}) if o.payload.get('kind')=='land' and o.action=='BASE_DEPLOY'])

    def test_war_raises_priority_of_bases(self):
        peace=score(next(o for o in defense.base_options(ctx(),forces(),{}) if o.action=='BASE_DEPLOY'),ctx(priorities=['defensive_army']))
        war_ctx=ctx('war',priorities=['defensive_army'])
        war=score(next(o for o in defense.base_options(war_ctx,forces(),{}) if o.action=='BASE_DEPLOY'),war_ctx)
        self.assertGreater(war.score,peace.score+10)

    def test_reinforce_upgrade_locate_liquidate_withdraw(self):
        full=base(1,garrison={'soldiers':10000,'tanks':100,'launchers':25,'armored':25})
        partial=base(2,garrison={'soldiers':2000,'tanks':10},region=3)
        options=defense.base_options(ctx('war'),forces(bases=[full,partial,base(3,health=0),base(4,x=None)],slots={'land':0,'air':0,'naval':0,'nuclear':None}),{3:200})
        by={(o.action,o.payload.get('base_id')):o for o in options}
        self.assertEqual(by[('BASE_REINFORCE',2)].payload['garrison']['soldiers'],10000)
        self.assertIn(('BASE_UPGRADE',1),by);self.assertNotIn(('BASE_UPGRADE',2),by)
        self.assertIn(('BASE_LIQUIDATE',3),by);self.assertIn(('BASE_LOCATE',4),by)
        broke=defense.base_options(ctx(),forces(bases=[base(5,garrison={'soldiers':1},region=1),base(6,garrison={'soldiers':1},region=2)],budget=0,slots={'land':0,'air':0,'naval':0,'nuclear':None}),{1:100,2:900})
        withdraw=[o for o in broke if o.action=='BASE_WITHDRAW']
        self.assertEqual([o.payload['base_id'] for o in withdraw],[6])  # najdalej od zagrożenia

    def test_base_location_follows_threat(self):
        c=ctx();c._holdings=FakeHoldings(regions=(1,2,3,4,5,6),coastal=(6,))
        threats={1:100,2:200,3:300,4:400,5:500,6:600}
        calls=[]
        def site(h,km,*,seed,regions=None,coastal=False):calls.append((tuple(regions),coastal));return regions[0],[0,0]
        with patch('game.paga2.location.site',site),patch('game.paga2.planner._km',lambda c:1):
            defense.base_site(c,'land',threats);defense.base_site(c,'nuclear',threats);defense.base_site(c,'naval',threats);defense.base_site(c,'air',{})
        self.assertEqual(calls[0],((1,2),False))        # bliżej wroga
        self.assertEqual(calls[1],((6,5),False))        # najdalej od wroga
        self.assertTrue(calls[2][1])                    # baza morska na wybrzeżu
        self.assertEqual(len(calls[3][0]),6)            # bez zagrożenia: dowolny region


class BaseLimitTests(unittest.TestCase):
    """13 Nov 2026: utrzymanie baz ≤ 50% budżetu wojska; priorytet nowej bazy maleje z liczbą baz."""
    def test_upkeep_cap_blocks_new_bases_and_reinforcements(self):
        heavy=[base(i,garrison={'soldiers':10000,'tanks':100}) for i in range(1,4)]   # 3 × (40 mln + 0,8 mln) ≈ 0,12 MLD
        rich=defense.base_options(ctx('war'),forces(bases=heavy,budget=1e11),{})
        self.assertTrue([o for o in rich if o.action=='BASE_DEPLOY'])
        poor=defense.base_options(ctx('war'),forces(bases=heavy,budget=2e8),{})              # 50% z 0,2 MLD = 100 mln < utrzymanie istniejących (122 mln)
        self.assertFalse([o for o in poor if o.action in ('BASE_DEPLOY','BASE_REINFORCE')])

    def test_priority_of_new_base_falls_with_number_of_bases(self):
        few=[o for o in defense.base_options(ctx('war'),forces(bases=[base(1)]),{}) if o.key=='base:deploy:land'][0]
        many=[o for o in defense.base_options(ctx('war'),forces(bases=[base(i) for i in range(1,41)]),{}) if o.key=='base:deploy:land'][0]
        self.assertGreater(few.base,many.base+15)


class MissileDefenseTests(unittest.TestCase):
    def test_targets_capital_bases_border_regions_first(self):
        c=ctx('war');c._holdings=FakeHoldings()
        options=defense.missile_defense_options(c,forces(bases=[base(1,kind='nuclear'),base(2,region=7)]),{7:300,8:2000})
        targets=[(o.payload['target_kind'],o.payload['target_id']) for o in options if o.action=='DEFENSE_PLACE']
        self.assertEqual(targets[0],('city',5));self.assertIn(('base',1),targets);self.assertEqual(len(targets),3)

    def test_no_defense_in_occupied_regions(self):
        c=ctx('war');c._holdings=FakeHoldings();c.situation['occupied_regions']={'7':9}
        options=defense.missile_defense_options(c,forces(bases=[base(2,region=7),base(3,region=8)],capital=None),{7:300,8:400})
        targets=[(o.payload['target_kind'],o.payload['target_id']) for o in options if o.action=='DEFENSE_PLACE']
        self.assertNotIn(('base',2),targets);self.assertNotIn(('region',7),targets);self.assertIn(('base',3),targets)

    def test_refill_repair_upgrade(self):
        c=ctx('threat');c._holdings=FakeHoldings()
        defenses=[NS(id=1,level=1,health=100,ammunition=10,target_kind='city',target_id=5),NS(id=2,level=1,health=40,ammunition=100,target_kind='region',target_id=1),
                  NS(id=3,level=2,health=100,ammunition=500,target_kind='region',target_id=2)]
        by={o.action:o for o in defense.missile_defense_options(c,forces(defenses=defenses,capital=None),{})}
        self.assertEqual(by['DEFENSE_REFILL'].payload,{'action':'defense_refill','defense_id':1,'count':90,'source':'purchase','group':'defense:1'})
        self.assertEqual(by['DEFENSE_REPAIR'].payload['count'],60)
        self.assertEqual(by['DEFENSE_UPGRADE'].payload['defense_id'],3)
        own=[o for o in defense.missile_defense_options(c,forces(defenses=defenses[:1],capital=None,ammunition=1000),{}) if o.action=='DEFENSE_REFILL'][0]
        self.assertEqual(own.payload['source'],'stock');self.assertEqual(own.cost,0)


class RadarAndTrainingTests(unittest.TestCase):
    def test_radar_requires_technology_and_materials(self):
        c=ctx();c._holdings=FakeHoldings()
        self.assertEqual(defense.radar_options(c,forces(),{}),[])
        c._holdings=FakeHoldings(nodes={'radar':True},stock={'chip_natsyt':1,'zelazo':100})
        [build]=defense.radar_options(c,forces(),{})
        self.assertEqual(build.action,'RADAR_BUILD');self.assertEqual(build.resources,{'chip_natsyt':1,'zelazo':100})
        broken=defense.radar_options(c,forces(radars=[NS(id=4,health=0,level=1)]),{})
        self.assertIn('RADAR_LIQUIDATE',[o.action for o in broken])

    def test_training_in_war_for_weakest_branch_within_limits(self):
        self.assertEqual(defense.training_options(ctx(),forces()),[])
        war=ctx('war')
        [option]=defense.training_options(war,forces(budget=2e10))
        self.assertEqual(option.payload['branch'],'naval')                       # najsłabiej wyszkolone siły
        self.assertLessEqual(option.cost,.4*war.limits['per_action']*2e10)          # w granicach rozwagi finansowej
        self.assertEqual(option.payload['levels'],int(.4*war.limits['per_action']*2e10//1.7e9))


class ExecuteTests(unittest.TestCase):
    def test_deploy_then_location(self):
        c=ctx();calls=[];c.call=lambda path,**kw:(calls.append((path,kw['json'])) or (200,{'ok':True,'base_id':77}))
        option=next(o for o in defense.base_options(c,forces(),{}) if o.action=='BASE_DEPLOY')
        option.payload['site']={'region_id':3,'x':1.5,'y':2.5}
        result=defense.execute(c,option)
        self.assertEqual(result['base_id'],77)
        self.assertEqual(calls[0][1]['action'],'deploy');self.assertEqual(calls[0][1]['region_id'],3);self.assertIn('request_id',calls[0][1])
        self.assertEqual(calls[1][1],{'action':'location','base_id':77,'x':1.5,'y':2.5})

    def test_radar_build_and_training_payloads(self):
        c=ctx();calls=[];c.call=lambda path,**kw:(calls.append((path,kw['json'])) or (200,{}))
        from game.paga2.scoring import Option
        radar=Option('radar:build','defense','RADAR_BUILD','r',payload={'action':'build','site':{'region_id':2,'x':1,'y':2}})
        defense.execute(c,radar)
        self.assertEqual(calls[0][0],'/game/obrona-panstwa/radar');self.assertEqual({k:calls[0][1][k] for k in ('action','region_id','x','y')},{'action':'build','region_id':2,'x':1,'y':2})
        training=Option('train:land','army','TRAINING','t',payload={'branch':'land','levels':3})
        defense.execute(c,training)
        self.assertEqual(calls[1][0],'/game/sily-zbrojne/wyszkol');self.assertEqual((calls[1][1]['branch'],calls[1][1]['levels']),('land',3))


if __name__=='__main__':unittest.main()
