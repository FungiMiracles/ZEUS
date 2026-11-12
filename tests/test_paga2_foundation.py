"""PAGA2 etap 1 — fundament: katalog profilu, randomizer, geografia, tożsamość wykonawcza i widok państwa."""
import unittest
from datetime import datetime
from decimal import Decimal
from random import Random
from unittest.mock import patch
from sqlalchemy import delete,select
from flask import jsonify
from extensions import db
import paga_multi_ai_env
from test_industry_0011 import IndustryTests as _IndustryFixture
from game.models import GamePlayerCountry
from game.paga import PagaConfiguration,PagaRevision,TRAITS as OLD_TRAITS,INTERESTS
from game.paga_ai_models import PagaAiControl,PagaAiIdentity
from game.paga_ai_actor import AiPermissionError,authorized
from game.autonomy_models import AutonomyEvent,AutonomyAssessment
from game.paga2 import catalog
from game.paga2.models import Paga2Control,Paga2Profile,Paga2ProfileRevision,Paga2Decision,Paga2RandomDraw,migrated_profile
from game.paga2 import randomizer
from models import Panstwo,Region

PAGA2_MODELS=[Paga2Control,Paga2Profile,Paga2ProfileRevision,Paga2Decision,Paga2RandomDraw]


def profile_data(**changes):
    data={'categories':['economic','welfare'],'priorities':['trade','research','financial_stability'],'traits':{key:50 for key in catalog.TRAITS}}
    data.update(changes);return data


class CatalogTests(unittest.TestCase):
    def test_lists_match_specification(self):
        self.assertEqual(len(catalog.CATEGORIES),6)
        self.assertEqual(len(catalog.TRAITS),25)
        self.assertEqual(len(catalog.PRIORITIES),12)
        for key in ('intelligence','financial_stability','alliances'):self.assertIn(key,catalog.PRIORITIES)
        self.assertEqual(list(catalog.TRAITS)[:7],list(OLD_TRAITS))
        self.assertIn('future',catalog.CATEGORIES['hegemonic'])

    def test_validation_accepts_complete_profile(self):
        categories,priorities,traits=catalog.validate_profile(profile_data())
        self.assertEqual(categories,['economic','welfare']);self.assertEqual(priorities[0],'trade');self.assertEqual(len(traits),25)

    def test_validation_rejects_invalid_profiles(self):
        bad=[profile_data(categories=[]),profile_data(categories=['economic','welfare','terrorist','imperialist']),profile_data(categories=['economic','economic']),
             profile_data(categories=['unknown']),profile_data(priorities=[]),profile_data(priorities=['trade','trade']),
             profile_data(traits={**{key:50 for key in catalog.TRAITS},'secrecy':101}),profile_data(traits={key:50 for key in list(catalog.TRAITS)[:24]}),
             profile_data(traits={**{key:50 for key in catalog.TRAITS},'health':'50'}),None]
        for data in bad:
            with self.subTest(data=data),self.assertRaises(catalog.ProfileError):catalog.validate_profile(data)

    def test_priority_weights_decrease_and_sum_to_one(self):
        weights=catalog.priority_weights(['a','b','c'])
        self.assertAlmostEqual(sum(weights.values()),1.0);self.assertGreater(weights['a'],weights['b']);self.assertGreater(weights['b'],weights['c'])
        self.assertEqual(catalog.priority_weights([]),{})

    def test_migrated_profile_keeps_common_traits_and_maps_interests(self):
        class Config:approved_character={**{key:10 for key in OLD_TRAITS},'militarism':90};autonomy_enabled=True
        Config.approved_interests=[{'key':'conquer_neighbors','active':True},{'key':'prosperity','active':True},{'key':'terrorism','active':False}]+[{'key':k,'active':False} for k in INTERESTS if k not in ('conquer_neighbors','prosperity','terrorism')]
        data=migrated_profile(Config)
        self.assertEqual(data['categories'],['imperialist','welfare'])
        self.assertEqual(data['priorities'][:2],['conquest','offensive_army'])
        self.assertEqual(data['traits']['militarism'],90);self.assertEqual(data['traits']['secrecy'],50)
        self.assertTrue(data['autonomy_enabled'])
        catalog.validate_profile(data)


class Paga2Fixture:
    """Wspólne środowisko PAGA2 (bez metod testowych — do składania z unittest.TestCase)."""
    def setUp(self):
        self.environment=paga_multi_ai_env.start()
        self.fixture=_IndustryFixture();self.fixture.setUp();self.app=self.fixture.app
        self.app.config.update(ENV_NAME='UAT',PAGA_ENABLED=True,PAGA_AI_CONFIGURED=True)
        self.app.url_build_error_handlers.append(lambda error,endpoint,values:'/stub/'+endpoint)
        self.app.context_processor(lambda:{'game_csrf_token':'token'})
        from game.intelligence import intelligence_bp
        from game.loans import loans_bp
        from game.army import army_bp
        from game.research import research_bp
        from game.player_context import player_context_bp
        for blueprint in [intelligence_bp,loans_bp,army_bp,research_bp,player_context_bp]:
            if blueprint.name not in self.app.blueprints:self.app.register_blueprint(blueprint)
        from game.military_models import MapCalibration
        from game.land_war_models import Occupation
        for model in [PagaConfiguration,PagaRevision,PagaAiControl,PagaAiIdentity,AutonomyEvent,AutonomyAssessment,MapCalibration,Occupation,*PAGA2_MODELS]:model.__table__.create(db.engine,checkfirst=True)
        db.session.execute(delete(GamePlayerCountry).where(GamePlayerCountry.panstwo_id==1))
        db.session.add(Paga2Control(id=1,enabled=True,revision=3,interval_minutes=60,actor='test'))
        db.session.add(Paga2Profile(panstwo_id=1,actor='test',autonomy_enabled=True,**profile_data()))
        db.session.commit()
        @self.app.errorhandler(AiPermissionError)
        def forbidden(error):db.session.rollback();return jsonify(error=str(error)),403

    def tearDown(self):self.fixture.tearDown();self.fixture.doCleanups();self.environment.stop()

    def actor(self,view=False):
        from game.paga2.gateway import actor_for
        actor=actor_for(db.session,1,view=view);db.session.commit();return actor


class Paga2Tests(Paga2Fixture,unittest.TestCase):

    # ---- kwalifikacja i autoryzacja ----
    def test_paga2_profile_makes_country_npc_eligible(self):
        from game.diplomacy_service import npc_eligible
        with self.app.app_context():
            self.assertTrue(npc_eligible(db.session,1))
            db.session.get(Paga2Profile,1).autonomy_enabled=False;db.session.commit()
            self.assertFalse(npc_eligible(db.session,1))

    def test_paga2_actor_requires_enabled_control_and_current_revision(self):
        actor=self.actor()
        self.assertEqual(actor.engine,'paga2');self.assertEqual(actor.revision,3)
        authorized(db.session,actor)
        control=db.session.get(Paga2Control,1);control.enabled=False;db.session.commit()
        with self.assertRaises(AiPermissionError):authorized(db.session,actor)
        control.enabled=True;control.revision=4;db.session.commit()
        with self.assertRaises(AiPermissionError):authorized(db.session,actor)

    def test_paga2_actor_does_not_depend_on_llm_switch(self):
        db.session.add(PagaAiControl(id=1,enabled=False,revision=0,model_id='x'));db.session.commit()
        authorized(db.session,self.actor())

    def test_view_actor_works_while_paga2_disabled_but_cannot_write(self):
        from game.paga2.gateway import call,GatewayError
        db.session.get(Paga2Control,1).enabled=False;db.session.commit()
        actor=self.actor(view=True)
        authorized(db.session,actor)
        with self.assertRaises(GatewayError):call(self.app,actor,'/game/badania/zmiana',method='POST',json={'action':'buy','count':1})
        with self.assertRaises(GatewayError):call(self.app,actor,'/wejscie')

    # ---- widok państwa ----
    def test_view_reads_player_screens_as_country_identity(self):
        from game.paga2.view import read
        actor=self.actor()
        research=read(self.app,actor,'research')
        self.assertEqual(research['status'],200,research);self.assertIn('budget',research['data'])
        army=read(self.app,actor,'army')
        self.assertEqual(army['status'],200,army)
        self.assertIsInstance(army['data'].get('army'),dict)  # własny rekord wojska jako słownik kolumn
        self.assertEqual(army['data']['army']['panstwo_id'],1)
        events=read(self.app,actor,'events')
        self.assertEqual(events['status'],200);self.assertIn('items',events['data'])

    def test_disabled_paga2_cannot_commit_through_screens(self):
        from game.paga2.view import read
        actor=self.actor()
        db.session.get(Paga2Control,1).enabled=False;db.session.commit()
        self.assertEqual(read(self.app,actor,'research')['status'],403)

    def test_private_events_of_other_countries_are_invisible(self):
        from game.paga2.view import read
        db.session.add_all([AutonomyEvent(source_key='a',kind='HYBRID_DETECTED',actor_id=1,target_id=2,occurred_at=datetime(3000,1,1),public=False,audience=[2],private_country_id=2,payload={}),
                            AutonomyEvent(source_key='b',kind='WAR',actor_id=2,target_id=3,occurred_at=datetime(3000,1,2),public=True,audience=[],payload={})])
        db.session.commit()
        items=read(self.app,self.actor(),'events')['data']['items']
        self.assertEqual([item['kind'] for item in items],['WAR'])

    def test_plain_drops_foreign_orm_records(self):
        from game.paga2.gateway import plain
        country=Panstwo(PANSTWO_ID=2,panstwo_nazwa='Obce')  # rekord innego państwa
        self.assertIsNone(plain(country))
        self.assertEqual(plain({'a':Decimal('1.5'),'b':country,'c':[datetime(3000,1,1)]}),{'a':1.5,'c':['3000-01-01T00:00:00']})

    # ---- randomizer ----
    def test_randomizer_draws_only_on_ties_and_counts_calls(self):
        with self.app.app_context():
            key,drawn=randomizer.resolve(db.session,1,[('a',70),('b',50)],reason='test')
            self.assertEqual((key,drawn),('a',False))
            self.assertEqual(randomizer.calls(db.session),0)
            key,drawn=randomizer.resolve(db.session,1,[('a',70),('b',69.5),('c',40)],reason='konflikt',rng=Random(1))
            self.assertTrue(drawn);self.assertIn(key,('a','b'))
            self.assertEqual(randomizer.calls(db.session),1);self.assertEqual(randomizer.calls(db.session,country_id=2),0)
            row=db.session.scalar(select(Paga2RandomDraw))
            self.assertEqual([item[0] for item in row.candidates],['a','b']);self.assertEqual(row.reason,'konflikt')
            self.assertEqual(randomizer.resolve(db.session,1,[],reason='pusto'),(None,False))

    # ---- geografia ----
    def test_world_geography(self):
        from game.paga2.geography import World
        from game.military_models import MapCalibration
        regions={row.region_id:row.panstwo_id for row in db.session.scalars(select(Region))}
        ids=sorted(regions)
        own=[r for r in ids if regions[r]==1];foreign=[r for r in ids if regions[r] not in (1,None)]
        self.assertTrue(own and foreign)
        a,b=own[0],foreign[0]
        graph={a:{b},b:{a}}
        scale=db.session.get(MapCalibration,1)
        if scale is None:scale=MapCalibration(id=1,reference_city_a=1,reference_city_b=2,reference_km=100,reference_a_x=0,reference_a_y=0,reference_b_x=10,reference_b_y=0);db.session.add(scale)
        scale.km_per_unit=10;db.session.commit()
        centers={r:[float(i*3),4.0] for i,r in enumerate(ids)};centers[a]=[0.0,0.0];centers[b]=[3.0,4.0]
        with patch('game.paga2.geography.region_adjacency',return_value=graph),patch('game.paga2.geography.region_centers',return_value=centers),\
             patch('game.paga2.geography.coastline_segments',side_effect=lambda region:[[[0,0],[1,0]]] if region==a else []):
            world=World(db.session)
            self.assertEqual(world.km_per_unit,10)
            self.assertEqual(world.neighbors(1),[regions[b]])
            self.assertIn(1,world.country_graph()[regions[b]])
            self.assertEqual(world.neighbor_regions(1),[b]);self.assertEqual(world.border_regions(1),[a])
            self.assertEqual(world.region_neighbors(a),[b])
            self.assertAlmostEqual(world.region_distance_km(a,b),50.0)
            self.assertEqual(world.country_distance_km(1,regions[b]),0.0)
            self.assertTrue(world.coastal(a));self.assertFalse(world.coastal(b))
            self.assertAlmostEqual(world.coast_distance_km(a,[0.5,2]),20.0)
            summary=world.summary(1)
            self.assertEqual(summary['neighbor_countries'],[regions[b]]);self.assertIn(a,summary['coastal_regions'])

    # ---- pamięć ----
    def test_memory_recalls_own_decisions_and_actions_against_country(self):
        from game.paga2.memory import recall,history_with
        db.session.add_all([AutonomyEvent(source_key='w',kind='WAR',actor_id=2,target_id=1,occurred_at=datetime(3000,1,1),public=True,audience=[],payload={'parties':[2,1]}),
                            AutonomyEvent(source_key='x',kind='BOMBARDMENT',actor_id=3,target_id=2,occurred_at=datetime(3000,1,2),public=True,audience=[],payload={}),
                            Paga2Decision(request_key='k',country_id=1,mode='CYCLIC',trigger='test',domain='economy',action='BUILD_MINE',status='EXECUTED',options=[],inputs={},game_at=datetime(3000,1,3))])
        db.session.commit()
        memory=recall(db.session,1,datetime(3000,2,1))
        self.assertEqual([d['action'] for d in memory['own_decisions']],['BUILD_MINE'])
        self.assertEqual([e['kind'] for e in memory['actions_against_us']],['WAR'])
        self.assertEqual([e['kind'] for e in memory['relation_changes']],['WAR'])
        self.assertEqual([e['kind'] for e in memory['world_conflicts']],['BOMBARDMENT'])
        self.assertEqual(history_with(db.session,1,2,datetime(3000,2,1))['hostile_from'],1)


class SourceRoutesTests(unittest.TestCase):
    def test_every_view_source_is_a_registered_player_route(self):
        """Ścieżki widoku muszą istnieć w aplikacji (statycznie, bez uruchamiania schedulerów)."""
        import re
        from pathlib import Path
        from game.paga2.view import SOURCES
        root=Path(__file__).resolve().parents[1]
        declared=set()
        for path in (root/'game').glob('*.py'):
            text=path.read_text()
            prefixes=dict(re.findall(r"(\w+)\s*=\s*Blueprint\([^)]*?url_prefix\s*=\s*['\"]([^'\"]+)['\"]",text,re.S))
            for name,rule in re.findall(r"@(\w+)\.(?:get|route)\(\s*['\"]([^'\"]*)['\"]",text):
                if name in prefixes:declared.add(prefixes[name]+rule)
        for name,(path,method,keep) in SOURCES.items():
            with self.subTest(source=name):self.assertIn(path,declared)


if __name__=='__main__':unittest.main()
