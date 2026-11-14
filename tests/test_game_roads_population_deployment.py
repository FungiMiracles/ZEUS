"""Curvature, shared road consent, upgrades, garrison flow and age allocation."""
from decimal import Decimal
from uuid import uuid4
from unittest.mock import patch
from sqlalchemy import select,text
from extensions import db
from models import Panstwo,Region
from game.civic_models import Road,RoadProposal,RoadInvestment
from game.roads import quote_road,build_road
from game.road_projects import network_quote,submit_road,resolve_proposal,upgrade_road
from game.road_geometry import interpolate
from game.population_structure import PopulationStructure,save_structure,structure_data
from game.finance_models import StateBudget
from game.budget_transfers import infrastructure_balance,sector_balances
from game.finance_service import FinanceError
from game.military_service import change_defense
from game.military_models import MilitaryBase
from test_game_military import MilitaryFixture,NOW


def feature(id,low,high):return {'properties':{'region_id':id},'geometry':{'type':'Polygon','coordinates':[[[low,0],[high,0],[high,100],[low,100],[low,0]]]}}


class RoadProjectTests(MilitaryFixture):
    def setUp(self):
        super().setUp();self.features=[feature(1,0,50),feature(2,50,100)]
        db.session.execute(text("INSERT INTO game_state_budget_allocations(id,budget_id,category_code,amount) VALUES(2,1,'infrastructure',1000000000)"))
        db.session.execute(text("INSERT INTO game_state_budgets(id,panstwo_id,game_year,period) VALUES(2,2,2990,1)"))
        db.session.execute(text("INSERT INTO game_state_budget_allocations(id,budget_id,category_code,amount) VALUES(3,2,'infrastructure',1000000000)"));db.session.commit()
        for target,value in [('game.roads.map_features',self.features),('game.road_projects.neighboring_countries',{2}),('game.road_projects.game_now',NOW),('game.roads.game_now',NOW)]:
            m=patch(target,return_value=value);m.start();self.addCleanup(m.stop)

    def data(self,foreign=True):
        data={'kind':'national','start':[10,50],'end':[90 if foreign else 40,50],'control_points':[[36,53],[64,47]] if foreign else [[20,52],[30,48]]}
        quote=network_quote(db.session,1,data)
        return {**quote,'expected_cost':quote['cost'],'request_id':str(uuid4())}

    def test_curve_passes_two_control_points_and_rejects_water(self):
        data=self.data(False);self.assertEqual(data['path'][8],data['control_points'][0]);self.assertEqual(data['path'][16],data['control_points'][1])
        with self.assertRaises(FinanceError):network_quote(db.session,1,{**data,'control_points':[[30,500],[40,500]]})

    def test_shared_consent_charges_each_country_only_its_piece_once(self):
        data=self.data();proposal=submit_road(1,data)['proposalId'];self.assertEqual(submit_road(1,data)['proposalId'],proposal)
        self.assertEqual(db.session.query(Road).count(),0)
        resolve_proposal(2,{'proposal_id':proposal,'decision':'accept'});resolve_proposal(2,{'proposal_id':proposal,'decision':'accept'});db.session.expire_all()
        roads=list(db.session.scalars(select(Road)));self.assertEqual({road.panstwo_id for road in roads},{1,2})
        self.assertEqual(sum(road.cost for road in roads),Decimal(data['cost']))
        for country in (1,2):
            spent=sum(road.cost for road in roads if road.panstwo_id==country)
            self.assertEqual(spent,Decimal(data['shares'][str(country)]['cost']))
            self.assertEqual(infrastructure_balance(db.session,db.session.get(StateBudget,country))[1],1000000000-spent)

    def test_rejection_border_preview_and_only_own_payment(self):
        data=self.data();id=submit_road(1,data)['proposalId'];resolve_proposal(2,{'proposal_id':id,'decision':'reject'})
        preview=resolve_proposal(1,{'proposal_id':id,'decision':'border'},preview=True);self.assertEqual(db.session.query(Road).count(),0)
        resolve_proposal(1,{'proposal_id':id,'decision':'border','expected_cost':preview['cost']});db.session.expire_all()
        road=db.session.query(Road).one();self.assertEqual(road.panstwo_id,1);self.assertAlmostEqual(road.end_x,50,places=5)
        self.assertEqual(infrastructure_balance(db.session,db.session.get(StateBudget,2))[1],1000000000)
        self.assertEqual(road.cost,Decimal(preview['cost']))

    def test_insufficient_partner_funds_or_wrong_actor_cannot_partially_build(self):
        data=self.data();id=submit_road(1,data)['proposalId']
        with self.assertRaises(FinanceError):resolve_proposal(1,{'proposal_id':id,'decision':'accept'})
        db.session.execute(text('UPDATE game_state_budget_allocations SET amount=0 WHERE budget_id=2'));db.session.commit()
        with self.assertRaises(FinanceError):resolve_proposal(2,{'proposal_id':id,'decision':'accept'})
        self.assertEqual(db.session.query(Road).count(),0);self.assertEqual(db.session.get(RoadProposal,id).status,'pending')
        self.assertEqual(infrastructure_balance(db.session,db.session.get(StateBudget,1))[1],1000000000)

    def test_upgrade_cost_and_preserved_curve_historical_initial_cost(self):
        data=self.data(False);road=build_road(1,data);original=db.session.get(Road,road['id']);old_cost=original.cost;path=original.path
        preview=upgrade_road(1,{'road_id':road['id']},preview=True)
        self.assertEqual(Decimal(preview['cost']),original.distance_km*800000)
        request={'road_id':road['id'],'request_id':str(uuid4()),'expected_cost':preview['cost']}
        upgrade_road(1,request);upgrade_road(1,request);db.session.expire_all()
        road=db.session.get(Road,road['id']);self.assertEqual(road.kind,'motorway');self.assertEqual(road.path,path);self.assertEqual(road.cost,old_cost)
        self.assertEqual(db.session.query(RoadInvestment).count(),1)
        self.assertEqual(sector_balances(db.session,db.session.get(StateBudget,1))['infrastructure']['spent'],old_cost+Decimal(preview['cost']))
        with self.assertRaises(FinanceError):upgrade_road(2,{'road_id':road.id},preview=True)

    def test_domestic_submit_and_idempotency(self):
        data=self.data(False);result=submit_road(1,data);self.assertIn('road',result);self.assertEqual(submit_road(1,data)['road']['id'],result['road']['id'])
        self.assertEqual(db.session.query(RoadProposal).count(),0)


class DeploymentTests(MilitaryFixture):
    def payload(self):return {'kind':'land','region_id':1,'garrison':{'soldiers':100,'tanks':1,'launchers':0,'armored':0},'request_id':str(uuid4())}

    def test_garrison_is_required_and_allocated_before_map_placement(self):
        self.supply_materials('land')
        data=self.payload();id=change_defense(1,'deploy',data);again=change_defense(1,'deploy',data);self.assertEqual(id,again);db.session.expire_all()
        base=db.session.get(MilitaryBase,id);self.assertEqual(base.garrison['soldiers'],100);self.assertEqual(base.garrison['tanks'],1);self.assertIsNone(base.map_x)
        self.assertEqual(db.session.query(MilitaryBase).count(),1)
        for garrison in ({},{'soldiers':100},{'soldiers':0,'tanks':1},{'soldiers':100,'tanks':999999}):
            with self.assertRaises(FinanceError):change_defense(1,'deploy',{**self.payload(),'garrison':garrison})
        self.assertEqual(db.session.query(MilitaryBase).count(),1)

    def test_cancel_deploy_removes_unplaced_base_and_keeps_the_slot(self):
        from models import Wojsko
        from game.commerce_models import ResourceStock
        self.supply_materials('land')
        id=change_defense(1,'deploy',self.payload());db.session.expire_all()
        self.assertEqual((db.session.get(ResourceStock,(1,'kamien')).quantity,db.session.get(ResourceStock,(1,'zelazo')).quantity),(0,0))
        slots=db.session.query(Wojsko).one().liczba_baz_ladowych
        change_defense(1,'cancel_deploy',{'base_id':id});db.session.expire_all()
        self.assertIsNone(db.session.get(MilitaryBase,id))
        # 13 Nov 2026: rezygnacja zwraca 100% surowców zużytych na budowę
        self.assertEqual((db.session.get(ResourceStock,(1,'kamien')).quantity,db.session.get(ResourceStock,(1,'zelazo')).quantity),(21,16))
        self.assertEqual(db.session.query(Wojsko).one().liczba_baz_ladowych,slots)   # miejsce na bazę nie przepada
        placed=change_defense(1,'deploy',self.payload());base=db.session.get(MilitaryBase,placed);base.map_x=base.map_y=1.0;db.session.commit()
        with self.assertRaisesRegex(FinanceError,'zlikwidować'):change_defense(1,'cancel_deploy',{'base_id':placed})

    def test_wrong_region_and_insufficient_budget_leave_no_empty_base(self):
        data=self.payload()
        with self.assertRaises(FinanceError):change_defense(1,'deploy',{**data,'region_id':2})
        self.set_budget(0)
        with self.assertRaises(FinanceError):change_defense(1,'deploy',data)
        self.assertEqual(db.session.query(MilitaryBase).count(),0)


class PopulationStructureTests(MilitaryFixture):
    def setUp(self):
        super().setUp();db.session.execute(text("UPDATE panstwa SET panstwo_populacja=7 WHERE PANSTWO_ID=1"));db.session.commit()

    def test_hundred_percent_and_counts_sum_to_actual_population(self):
        data=save_structure(db.session,1,{'children':'33.33','working':'33.33','seniors':'33.34','version':0},'Administrator');db.session.commit()
        self.assertEqual([group['count'] for group in data['groups']],[2,2,3]);self.assertEqual(sum(group['count'] for group in data['groups']),7)
        db.session.execute(text("UPDATE panstwa SET panstwo_populacja=11 WHERE PANSTWO_ID=1"));db.session.commit()
        self.assertEqual(sum(group['count'] for group in structure_data(db.session,1)['groups']),11)

    def test_invalid_sum_negative_precision_and_stale_version_are_rejected(self):
        for shares in [('30','60','9'),('-1','100','1'),('33.333','33.333','33.334')]:
            with self.assertRaises(FinanceError):save_structure(db.session,1,dict(zip(('children','working','seniors'),shares),version=0),'Admin')
        save_structure(db.session,1,{'children':20,'working':60,'seniors':20,'version':0},'Admin');db.session.commit()
        with self.assertRaises(FinanceError):save_structure(db.session,1,{'children':10,'working':70,'seniors':20,'version':0},'Admin')

    def test_wiki_role_and_csrf(self):
        from routes_civic_admin import wiki_civic_bp
        self.app.register_blueprint(wiki_civic_bp)
        self.assertEqual(self.client.get('/admin/struktura-ludnosci').status_code,403)
        with self.client.session_transaction() as browser:browser['rola']='wszechmocny'
        self.assertEqual(self.client.post('/admin/struktura-ludnosci/zapisz',json={}).status_code,403)


class AbroadBaseTests(MilitaryFixture):
    """Bazy w krajach sojuszniczych (12 Nov 2026)."""
    def setUp(self):
        super().setUp()
        from game.base_permits import BasePermit,_READY
        BasePermit.__table__.create(db.engine,checkfirst=True);_READY.clear()
        from game.forum_models import GameNotification
        GameNotification.__table__.create(db.engine,checkfirst=True)

    def payload(self,region=2):return {'kind':'land','region_id':region,'garrison':{'soldiers':100,'tanks':1,'launchers':0,'armored':0},'request_id':str(uuid4())}

    def permit(self,status='ACTIVE'):
        from game.base_permits import BasePermit
        db.session.add(BasePermit(host_country_id=2,guest_country_id=1,region_id=2,status=status));db.session.commit()

    def test_build_only_with_active_permit_and_double_upkeep(self):
        with self.assertRaises(FinanceError):change_defense(1,'deploy',self.payload())
        self.permit();self.supply_materials('land')
        id=change_defense(1,'deploy',self.payload());db.session.expire_all()
        base=db.session.get(MilitaryBase,id);self.assertEqual(base.region_id,2)
        from game.military import base_data
        from game.base_permits import own_region_ids
        with self.app.test_request_context():
            data=base_data(base,own_region_ids(db.session,1))
        self.assertTrue(data['abroad']);self.assertEqual(Decimal(data['upkeep']),2*(100*4000+8000))
        self.supply_materials('land');home=change_defense(1,'deploy',self.payload(1));db.session.expire_all()
        with self.app.test_request_context():
            self.assertFalse(base_data(db.session.get(MilitaryBase,home))['abroad'])

    def test_relation_change_freezes_or_liquidates(self):
        from game.base_permits import on_relation_change,BasePermit,permitted_region_ids
        self.permit();self.supply_materials('land');id=change_defense(1,'deploy',self.payload())
        on_relation_change(db.session,1,2,'Przyjazne');db.session.commit()
        self.assertEqual(db.session.query(BasePermit).one().status,'FROZEN');self.assertIsNotNone(db.session.get(MilitaryBase,id))
        self.assertEqual(permitted_region_ids(db.session,1),set())
        with self.assertRaises(FinanceError):change_defense(1,'deploy',self.payload())   # nie można budować nowych
        on_relation_change(db.session,1,2,'Sojusznicze');db.session.commit()
        self.assertEqual(db.session.query(BasePermit).one().status,'ACTIVE')
        on_relation_change(db.session,1,2,'Neutralne');db.session.commit()
        self.assertEqual(db.session.query(BasePermit).one().status,'REVOKED');self.assertIsNone(db.session.get(MilitaryBase,id))
