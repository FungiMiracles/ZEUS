"""WYM0060–0071 end-to-end economic and combat invariants on isolated SQLite."""
from datetime import timedelta,datetime
from decimal import Decimal
from uuid import uuid4
from unittest.mock import patch
from sqlalchemy import select,text
from extensions import db
from test_game_commerce import CommerceFixture
from test_game_military import NOW
from models import RegionZasob,Wojsko,Region
from game.industry_catalog import TECHNOLOGIES,MINE_RULES,FACTORIES,POWER_PLANTS
from game.industry_models import PowerPlant,IndustryMovement
from game.research_models import ResearchAccount,AmmunitionFactory
from game.industry_service import change_industry,settle_industry,energy_balance,month_after
from game.mining_service import build_mine,extract_country
from game.research_service import change_research,node_state
from game.commerce_models import ResourceStock,Mine
from game.finance_models import StateBudget
from game.budget_transfers import sector_balances
from game.finance_service import FinanceError,FinanceConflict
from game.forum_models import GameNotification
from game.military_models import MilitaryFlight,MilitaryOrder,MissileDefense
from game.military_flights import apply_structural_damage

class IndustryTests(CommerceFixture):
    def setUp(self):
        super().setUp()
        self.app.register_blueprint(__import__('game.infrastructure',fromlist=['infrastructure_bp']).infrastructure_bp)
        self.app.register_blueprint(__import__('game.research',fromlist=['research_bp']).research_bp)
        self.login(1)
        db.session.add(ResearchAccount(panstwo_id=1,points=10000,ammunition=0,nodes={key:value['cost'] for key,value in TECHNOLOGIES.items()}))
        db.session.commit()
        for target in ['game.research_service.game_now','game.research.game_now','game.industry_service.game_now','game.finance_service.game_now']:
            p=patch(target,return_value=NOW);p.start();self.addCleanup(p.stop)

    def operation(self,action='build',**values):
        data=dict(action=action,category='factory',kind='chips',level=1,region_id=1,x=10,y=10,request_id=str(uuid4()));data.update(values)
        return change_industry(1,data)
    def add_stock(self,code,amount):
        row=db.session.get(ResourceStock,(1,code))
        if row:row.quantity=amount
        else:db.session.add(ResourceStock(panstwo_id=1,resource=code,quantity=amount))
        db.session.commit()
    def refresh(self):db.session.expire_all()

    def test_catalog_exact_counts_and_iron_dependency(self):
        self.assertEqual(len(TECHNOLOGIES),41,'33 + Technologie ochrony środowiska, Filtr zanieczyszczeń, Filtr odpadów fabrycznych (10 Nov 2026) + Rozpoznanie radarowe (11 Nov 2026) + Rakieta z głowicą nuklearną (13 Nov 2026) + Transport i komunikacja, Transport kolejowy (19 Nov 2026) + Transport lotniczy (20 Nov 2026)')
        self.assertNotIn('ammunition',TECHNOLOGIES)
        for factory in FACTORIES.values():
            for level in factory['levels']:self.assertNotIn('ammunition',level['technologies'])
        self.assertEqual(TECHNOLOGIES['mine_iron']['cost'],75)
        self.assertEqual(TECHNOLOGIES['mine_iron']['parent'],'mining_industry')
        self.assertEqual(len(FACTORIES['chips']['levels']),5)
        self.assertEqual(FACTORIES['shipyard']['levels'][2]['inputs']['chip_natsyt'],5)
        self.assertEqual(MINE_RULES['ropa_naftowa'][4],12)
        self.assertEqual(month_after(datetime(2990,1,31)),datetime(2990,2,28))

    def test_research_prerequisites_and_partial_progress(self):
        account=db.session.get(ResearchAccount,1);account.nodes={};db.session.commit()
        def invest(key,count):change_research(1,dict(action='invest',node=key,count=count,request_id=str(uuid4())))
        with self.assertRaises(FinanceError):invest('mine_iron',1)
        invest('method',24)
        with self.assertRaises(FinanceError):invest('mining_industry',1)
        # 13 Nov 2026: po skompletowaniu punktów technologia rozwija się przez określoną liczbę dni Entendy
        moment=[NOW]
        with patch('game.research_service.game_now',side_effect=lambda:moment[0]):
            invest('method',1)
            with self.assertRaisesRegex(FinanceError,'Metoda badawcza'):invest('mining_industry',1)   # metoda jeszcze w rozwoju (1 dzień)
            moment[0]=NOW+timedelta(days=1);invest('mining_industry',25)
            moment[0]=NOW+timedelta(days=3);invest('mine_iron',75)
            self.refresh();account=db.session.get(ResearchAccount,1)
            self.assertTrue(node_state(account.nodes['mine_iron'],'mine_iron',account.timers,moment[0])['researching'])
            self.assertEqual(node_state(account.nodes['mine_iron'],'mine_iron',account.timers,NOW+timedelta(days=10))['level'],1)   # żelazo: 7 dni
            with self.assertRaises(FinanceError):invest('method',1)

    def test_factories_can_build_each_specified_level_and_charge_exact_cost(self):
        db.session.get(Region,1).region_polozenie_id=2;db.session.commit()
        for kind,rule in FACTORIES.items():
            for i,spec in enumerate(rule['levels'],1):
                with patch('game.military_geography.naval_location_allowed',return_value=True):id=self.operation(kind=kind,level=i)
                self.refresh();row=db.session.get(AmmunitionFactory,id)
                self.assertEqual((row.kind,row.level),(kind,i))
                if rule.get('budget_sector')=='armed_forces':   # 13 Nov 2026: fabryka rakiet atomowych — wydatek sił zbrojnych
                    from game.military_models import MilitaryExpense
                    self.assertEqual(db.session.scalar(select(MilitaryExpense.amount).order_by(MilitaryExpense.id.desc()).limit(1)),spec['cost'])
                    self.assertEqual(db.session.scalar(select(IndustryMovement.amount).order_by(IndustryMovement.id.desc()).limit(1)),0)
                else:self.assertEqual(db.session.scalar(select(IndustryMovement.amount).order_by(IndustryMovement.id.desc()).limit(1)),spec['cost'])
        self.assertEqual(db.session.query(AmmunitionFactory).count(),17)

    def test_shipyard_requires_the_same_coastal_band_as_a_naval_base(self):
        with self.assertRaises(FinanceError):self.operation(kind='shipyard')
        self.assertEqual(db.session.query(IndustryMovement).count(),0)
        db.session.get(Region,1).region_polozenie_id=2;db.session.commit()
        with patch('game.military_geography.naval_location_allowed',return_value=False):
            with self.assertRaises(FinanceError):self.operation(kind='shipyard')
        self.assertEqual(db.session.query(AmmunitionFactory).count(),0)
        with patch('game.military_geography.naval_location_allowed',return_value=True) as coast:
            id=self.operation(kind='shipyard');coast.assert_called_once_with(1,10,10,1)
        self.refresh();self.assertEqual(db.session.get(AmmunitionFactory,id).kind,'shipyard')

    def test_auth_location_technology_and_money_fail_atomically(self):
        with self.assertRaises(FinanceError):self.operation(region_id=2)
        account=db.session.get(ResearchAccount,1);account.nodes={};db.session.commit()
        with self.assertRaises(FinanceError):self.operation()
        self.assertEqual(db.session.query(IndustryMovement).count(),0)
        self.assertEqual(db.session.query(AmmunitionFactory).count(),0)

    def test_factory_missing_inputs_are_exact_deficits_and_skip_reserved_recipe(self):
        from game.industry_service import object_data
        id=self.operation(kind='tanks');self.refresh()
        self.add_stock('zelazo',7);self.add_stock('ropa_naftowa',9)
        factory=db.session.get(AmmunitionFactory,id)
        self.assertEqual(object_data(factory,'factory')['missingInputs'],{'zelazo':3,'chip_simple':1})
        self.add_stock('zelazo',10);self.add_stock('chip_simple',1)
        self.assertEqual(object_data(factory,'factory')['missingInputs'],{})
        self.add_stock('zelazo',0);factory.production_progress=1;db.session.commit()
        self.assertEqual(object_data(factory,'factory')['missingInputs'],{})

    def full_power(self):
        """Recipe tests: a grid with enough energy (since 10 Nov 2026 a deficit stops factories; covered by its own tests)."""
        from game import industry_service
        original=industry_service.powered_factories
        def powered(session,factories,production,resident):return {f.id for f in factories if industry_service.factory_can_work(session,f)}
        patcher=patch('game.industry_service.powered_factories',side_effect=powered);patcher.start();self.addCleanup(patcher.stop)

    def test_daily_recipe_pausing_no_retroactive_production_and_notification(self):
        self.full_power()
        id=self.operation(kind='interceptor_ammo');self.add_stock('zelazo',11);self.add_stock('ropa_naftowa',11)
        for days,expected in [(0,0),(1,5),(2,10),(3,11),(4,11),(4,11)]:
            settle_industry(db.session,1,NOW+timedelta(days=days));db.session.commit()
            self.assertEqual(db.session.get(ResearchAccount,1).ammunition,expected)
        self.assertEqual(db.session.query(GameNotification).filter(GameNotification.system_text.like('%brak surowców%')).count(),1)
        self.assertEqual(db.session.get(ResourceStock,(1,'zelazo')).quantity,0)
        with patch('game.industry_service.game_now',return_value=NOW+timedelta(days=4)):
            self.operation('pause',object_id=id)
        self.add_stock('zelazo',20);self.add_stock('ropa_naftowa',20)
        settle_industry(db.session,1,NOW+timedelta(days=6));db.session.commit()
        self.assertEqual(db.session.get(ResearchAccount,1).ammunition,11)

    def test_weekly_production_reserves_recipe_once_and_adds_to_army(self):
        self.full_power()
        self.operation(kind='tanks');self.add_stock('zelazo',10);self.add_stock('ropa_naftowa',5);self.add_stock('chip_simple',1)
        before=db.session.scalar(select(Wojsko.czolgi_ilosc).where(Wojsko.panstwo_id==1))
        settle_industry(db.session,1,NOW+timedelta(days=6));db.session.commit()
        self.assertEqual(db.session.scalar(select(Wojsko.czolgi_ilosc).where(Wojsko.panstwo_id==1)),before)
        settle_industry(db.session,1,NOW+timedelta(days=7));db.session.commit()
        self.assertEqual(db.session.scalar(select(Wojsko.czolgi_ilosc).where(Wojsko.panstwo_id==1)),before+1)
        self.assertEqual(db.session.get(ResourceStock,(1,'chip_simple')).quantity,0)

    def test_energy_stability_counts_only_working_plants_and_ready_mines(self):
        coal=self.operation(category='power',kind='coal')
        self.operation(category='power',kind='wind')
        self.operation(category='power',kind='solar')
        mine_id=self.mine();self.refresh()
        self.add_stock('wegiel_kamienny',10)
        balance=energy_balance(db.session,1)['sources']
        self.assertEqual(balance['coal'],dict(production=100,consumption=1,extraction=0))
        self.assertEqual(balance['wind']['production'],6)    # 21 Nov 2026: wiatrowa 6 e/dzień
        self.assertEqual(balance['solar']['production'],8)   # słoneczna 8 e/dzień
        mine=db.session.get(Mine,mine_id);mine.starts_at=NOW-timedelta(days=5);mine.ready_at=NOW;mine.level=3;db.session.commit()
        self.assertEqual(energy_balance(db.session,1)['sources']['coal']['extraction'],3)
        db.session.get(PowerPlant,coal).health=2;db.session.commit()
        self.assertEqual(energy_balance(db.session,1)['sources']['coal']['consumption'],0)
        self.assertEqual(energy_balance(db.session,1)['sources']['coal']['production'],0)
        mine.health=0;db.session.commit()
        self.assertEqual(energy_balance(db.session,1)['sources']['coal']['extraction'],0)

    def test_power_damage_repair_exact_thirds_and_no_fuel_while_damaged(self):
        id=self.operation(category='power',kind='coal');self.add_stock('wegiel_kamienny',20)
        settle_industry(db.session,1,NOW+timedelta(days=1));db.session.commit()
        plant=db.session.get(PowerPlant,id);plant.health=2;db.session.commit()
        settle_industry(db.session,1,NOW+timedelta(days=2));db.session.commit()
        self.assertEqual(db.session.get(ResourceStock,(1,'wegiel_kamienny')).quantity,19)
        with patch('game.industry_service.game_now',return_value=NOW+timedelta(days=2)):
            self.operation('repair',category='power',object_id=id)
        self.refresh();self.assertEqual(db.session.get(PowerPlant,id).health,3)
        self.assertEqual(db.session.scalar(select(IndustryMovement.amount).order_by(IndustryMovement.id.desc()).limit(1)),Decimal('766666666.67'))   # 1/3 z 2,3 mld (13 Nov 2026)

    def test_power_upgrade_repair_cost_uses_cumulative_investment(self):
        id=self.operation(category='power',kind='solar')
        with self.assertRaises(FinanceError):self.operation(category='power',kind='solar',level=2)
        self.operation('upgrade',category='power',object_id=id);self.refresh()
        plant=db.session.get(PowerPlant,id);self.assertEqual(plant.level,2);self.assertEqual(plant.investment,2500000000)   # 21 Nov 2026: budowa 1,5 mld + rozbudowa 1,0 mld
        plant.health=2;db.session.commit();self.operation('repair',category='power',object_id=id)
        self.assertEqual(db.session.scalar(select(IndustryMovement.amount).order_by(IndustryMovement.id.desc()).limit(1)),Decimal('833333333.33'))

    def test_removal_refunds_current_level_and_is_idempotent(self):
        id=self.operation(category='power',kind='solar');self.operation('upgrade',category='power',object_id=id)
        data=dict(action='remove',category='power',object_id=id,request_id=str(uuid4()))
        change_industry(1,data);change_industry(1,data);self.refresh()
        self.assertIsNotNone(db.session.get(PowerPlant,id).removed_at)
        self.assertEqual(db.session.scalar(select(IndustryMovement.amount).order_by(IndustryMovement.id.desc()).limit(1)),-250000000)
        with self.assertRaises(FinanceError):self.operation('remove',category='power',object_id=id)
        self.assertEqual(db.session.query(IndustryMovement).count(),3)

    def test_mines_need_deposit_and_upgrade_extraction_never_exceeds_deposit(self):
        with self.assertRaises(FinanceError):self.mine(resource='uran')
        id=self.mine();self.refresh();mine=db.session.get(Mine,id)
        with patch('game.industry_service.game_now',return_value=mine.ready_at):self.operation('upgrade',category='mine',object_id=id)
        self.refresh();self.assertEqual(db.session.get(Mine,id).level,2)
        extract_country(db.session,1,NOW+timedelta(days=6));db.session.commit()
        self.assertEqual(db.session.get(ResourceStock,(1,'wegiel_kamienny')).quantity,23)
        self.assertEqual(db.session.scalar(select(RegionZasob.zloze_ilosc).where(RegionZasob.region_id==1,RegionZasob.zasob_id==1)),0)

    def test_power_hit_is_exactly_one_third_and_hidden_without_intelligence(self):
        id=self.operation(category='power',kind='wind');plant=db.session.get(PowerPlant,id)
        from types import SimpleNamespace
        flight=SimpleNamespace(target_kind='power',target_power_id=id,target_country_id=1,impact_at=NOW)
        for remaining in [2,1,0]:
            apply_structural_damage(db.session,flight,None,1);db.session.commit();self.assertEqual(plant.health,remaining)
        self.assertFalse(__import__('game.military',fromlist=['visible_power']).visible_power(2,True))

    def test_proportional_population_and_energy_deficit_stops_factories(self):
        # Rule changed 10 Nov 2026 (administrator): an energy deficit stops factories, largest consumers first.
        self.operation(kind='interceptor_ammo');self.add_stock('zelazo',5);self.add_stock('ropa_naftowa',5)
        with patch('game.industry_service.economy',return_value={'population':12500000}):
            balance=energy_balance(db.session,1);self.assertEqual(balance['residents'],'125');self.assertEqual(balance['demand'],'155')   # 18 Nov 2026: fabryka amunicji przeciwrakietowej 30 e/dzień
            self.assertEqual(balance['consumption'],'125');self.assertEqual(balance['stoppedFactories'],1);self.assertFalse(balance['sufficient'])
            settle_industry(db.session,1,NOW+timedelta(days=1));db.session.commit()
        self.assertEqual(db.session.get(ResearchAccount,1).ammunition,0,'no energy, no production')

    def test_routes_csrf_scope_and_technology_tree(self):
        response=self.client.get('/game/badania');self.assertEqual(response.status_code,200)
        self.assertIn('Chip cemium II',response.text);self.assertIn('Wydobycie żelaza',response.text)
        response=self.client.get('/game/infrastruktura/obiekty/stan');self.assertEqual(response.status_code,200)
        self.assertIn('energy',response.json)
        data=dict(action='build',category='power',kind='solar',region_id=1,x=1,y=2,request_id=str(uuid4()))
        self.assertEqual(self.client.post('/game/infrastruktura/obiekty/zmien',json=data).status_code,403)
        self.assertEqual(self.client.post('/game/infrastruktura/obiekty/zmien',json=data,headers={'X-CSRF-Token':'token'}).status_code,200)

    def test_chips_and_weapons_share_real_stock_and_cannot_sell_garrison(self):
        from game.trade_goods import change_goods,trade_warehouse
        self.add_stock('chip_cemium_ii',7)
        change_goods(db.session,1,'chip_cemium_ii',-2);db.session.commit()
        self.assertEqual(trade_warehouse(db.session,1)['chip_cemium_ii']['available'],5)
        before=db.session.scalar(select(Wojsko.mysliwce_ilosc).where(Wojsko.panstwo_id==1))
        change_goods(db.session,1,'fighters',-3);db.session.commit()
        self.assertEqual(trade_warehouse(db.session,1)['fighters']['available'],before-3)
        with self.assertRaises(FinanceError):change_goods(db.session,1,'fighters',-before)
        db.session.rollback()

    def test_power_can_use_missile_defense(self):
        id=self.operation(category='power',kind='wind')
        self.change('defense_place',target_kind='power',target_id=id)
        defense=db.session.scalar(select(MissileDefense).where(MissileDefense.target_kind=='power'))
        self.assertEqual(defense.target_id,id)
        from game.missile_defense import defense_data
        self.assertEqual(defense_data(defense)['position'],[10,10])

    def test_exhausted_deposit_notifies_once(self):
        mine_id=self.mine();mine=db.session.get(Mine,mine_id)
        deposit=db.session.scalar(select(RegionZasob).where(RegionZasob.region_id==mine.region_id))
        deposit.zloze_ilosc=1;db.session.commit()
        extract_country(db.session,1,mine.ready_at+timedelta(days=1));db.session.commit()
        count=db.session.query(GameNotification).filter(GameNotification.system_text.like('%wyczerpano złoże%')).count()
        self.assertEqual(count,1)
        extract_country(db.session,1,mine.ready_at+timedelta(days=2));db.session.commit()
        self.assertEqual(db.session.query(GameNotification).filter(GameNotification.system_text.like('%wyczerpano złoże%')).count(),count)


    def test_inventory_reports_completed_builds_and_current_output(self):
        coal=self.operation(category='power',kind='coal')
        factory=self.operation(kind='chips')
        for code in ['zelazo','srebro','zloto']:self.add_stock(code,100)
        response=self.client.get('/game/infrastruktura/obiekty/stan')
        self.assertEqual(response.status_code,200)
        objects={(row['category'],row['id']):row for row in response.json['objects']}
        for key in [('power',coal),('factory',factory)]:
            self.assertTrue(objects[key]['ready']);self.assertEqual(objects[key]['progress'],100)
        self.assertEqual(objects[('power',coal)]['effectiveDailyProduction'],100)
        self.assertEqual(objects[('factory',factory)]['effectiveQuantity'],10)
        db.session.get(PowerPlant,coal).health=2
        db.session.get(AmmunitionFactory,factory).paused=True;db.session.commit()
        objects={(row['category'],row['id']):row for row in self.client.get('/game/infrastruktura/obiekty/stan').json['objects']}
        self.assertEqual(objects[('power',coal)]['effectiveDailyProduction'],0)
        self.assertEqual(objects[('factory',factory)]['effectiveQuantity'],0)

    def test_mine_inventory_shares_deposit_without_counting_construction(self):
        ids=[self.mine(x=x) for x in [1,2,3]]
        for id in ids[:2]:
            mine=db.session.get(Mine,id);mine.starts_at=NOW-timedelta(days=5);mine.ready_at=NOW;mine.extracted_at=NOW;mine.level=3
        db.session.commit()
        rows=[row for row in self.client.get('/game/infrastruktura/obiekty/stan').json['objects'] if row['category']=='mine']
        self.assertEqual(len(rows),3)
        self.assertEqual(sum(row['effectiveDailyExtraction'] for row in rows),3)
        building=next(row for row in rows if row['id']==ids[2])
        self.assertFalse(building['ready']);self.assertEqual(building['effectiveDailyExtraction'],0)

    def test_future_research_branches_visible_but_cannot_be_purchased(self):
        from game.industry_catalog import PLANNED_TECHNOLOGIES
        from game.research_service import LEVELS
        from game.research import technology_layout
        response=self.client.get('/game/badania/stan');self.assertEqual(response.status_code,200)
        layout=technology_layout()
        self.assertEqual(len(layout['positions']),41);self.assertEqual(len(layout['edges']),40)   # 19 Nov 2026: + 2 technologie kolei; 20 Nov 2026: + transport lotniczy (nieaktywny)
        before=db.session.get(ResearchAccount,1).points
        # 10 Nov 2026: the planned 'Filtry powietrza' node became the regular technology 'Filtr zanieczyszczeń'.
        self.assertNotIn('air_filters',PLANNED_TECHNOLOGIES)
        self.assertEqual((TECHNOLOGIES['air_filters']['label'],TECHNOLOGIES['air_filters']['cost'],TECHNOLOGIES['air_filters']['parent']),('Filtr zanieczyszczeń',150,'environment_tech'))
        self.assertIn('air_filters',LEVELS);self.assertIn('air_filters',layout['positions'])
        # 13 Nov 2026: „Rakieta z głowicą nuklearną” jest aktywna — 750 pkt, wymaga trzech technologii
        # 20 Nov 2026: „Transport lotniczy” — aktywna technologia za transportem kolejowym (400 pkt, ikona samolotu); brak gałęzi nieaktywnych.
        self.assertEqual(PLANNED_TECHNOLOGIES,{})
        air=response.json['technologies']['air_transport']
        self.assertEqual((air['label'],air['parent'],air['cost'],air['icon']),('Transport lotniczy','rail_transport',400,'airplane'))
        self.assertNotIn('available',air);self.assertIn('air_transport',LEVELS)
        rule=TECHNOLOGIES['nuclear_missiles']
        self.assertEqual((rule['cost'],rule['parent'],rule['requires']),(750,'long_missiles',['long_missiles','mine_uranium','chip_cemium_i']))
        self.assertNotIn('available',response.json['technologies']['nuclear_missiles']);self.assertIn('nuclear_missiles',LEVELS)   # wymagania: tests/test_nuclear.py
        self.refresh();self.assertEqual(db.session.get(ResearchAccount,1).points,before)

    def test_military_factory_product_icons_follow_every_kind_and_level(self):
        import re
        import json
        from urllib.parse import unquote,urlsplit
        from game.military import visible_factories
        from models import Stosunki
        db.session.get(Region,1).region_polozenie_id=2;db.session.commit()
        for kind,rule in FACTORIES.items():
            for level in range(1,len(rule['levels'])+1):
                with patch('game.military_geography.naval_location_allowed',return_value=True):self.operation(kind=kind,level=level)
        expected={'nuclear_missiles':'BROŃ ATOMOWA.svg','chip_simple':'CHIP PROSTY.svg','chip_kerbit':'CHIP KERBITOWY.svg','chip_natsyt':'CHIP NATSYTOWY.svg','chip_cemium_i':'CHIP CEMIUM I.svg','chip_cemium_ii':'CHIP CEMIUM II.svg','tanks':'CZOŁG.svg','fighters':'MYŚLIWIEC.svg','armored':'WÓZ OPANCERZONY.svg','drones':'DRON.svg','short_missiles':'WYRZUTNIA RAKIET.svg','medium_missiles':'WYRZUTNIA RAKIET.svg','long_missiles':'WYRZUTNIA RAKIET.svg','warships':'OKRĘT WOJENNY.svg','submarines':'SUBMARINE.svg','carriers':'LOTNISKOWIEC.svg','interceptor_ammunition':'AMMO.svg'}
        def check(rows):
            self.assertEqual(len(rows),17)
            for row in rows:
                self.assertEqual(unquote(urlsplit(row['productIcon']).path),'/static/icons/'+expected[row['product']])
                self.assertTrue(row['productName'])
        with self.app.test_request_context():
            check(visible_factories(1));check(visible_factories(1,True))
        db.session.add(Stosunki(PANSTWO_ID=1,PANSTWO_ID2=2,stan_id=8));db.session.commit()
        with patch('game.military.land_targets',return_value=[2]):
            for path in ['/game/obrona-panstwa','/game/panel-wojenny']:
                response=self.client.get(path);self.assertEqual(response.status_code,200)
                config=json.loads(re.search(r'<script[^>]+id="military-config"[^>]*>(.*?)</script>',response.text,re.S)[1])
                check(config['visibleFactories'])
        state=self.client.get('/game/panel-wojenny/stan');self.assertEqual(state.status_code,200);check(state.json['factories'])

from test_game_military_flights import FlightFixture

class PowerCombatTests(FlightFixture):
    def setUp(self):
        super().setUp()
        plant=PowerPlant(panstwo_id=2,region_id=2,kind='wind',level=1,health=3,map_x=100,map_y=0,investment=800000000,created_game_at=NOW,checked_at=NOW)
        db.session.add(plant);db.session.commit();self.plant_id=plant.id;self.source_base=self.source()
    def launch_power(self,count=1):
        from game.military_service import create_order
        return create_order(1,dict(kind='missile',target_power_id=self.plant_id,source_base_id=self.source_base.id,missile_type='short',missiles=count))
    def test_knowledge_required_then_one_hit_third_and_three_hits_destroy(self):
        from game.intelligence_models import IntelligenceAgent,IntelligenceMission
        from game.military_flights import complete_flights
        with self.assertRaises(FinanceError):self.launch_power()
        agent=IntelligenceAgent(panstwo_id=1,level=1);db.session.add(agent);db.session.flush()
        db.session.add(IntelligenceMission(panstwo_id=1,agent_id=agent.id,region_id=2,target_country_id=2,region_name='Cel',kind='power',starts_at=NOW-timedelta(days=7),ends_at=NOW,completed_at=NOW,success=True,report={'power_ids':[self.plant_id]}));db.session.commit()
        id=self.launch_power();flight=db.session.get(MilitaryFlight,id)
        complete_flights(db.session,flight.impact_at);db.session.commit()
        self.assertEqual(db.session.get(PowerPlant,self.plant_id).health,2)
        complete_flights(db.session,flight.impact_at);db.session.commit()
        self.assertEqual(db.session.get(PowerPlant,self.plant_id).health,2)
        id=self.launch_power(2);flight=db.session.get(MilitaryFlight,id)
        complete_flights(db.session,flight.impact_at);db.session.commit()
        self.assertEqual(db.session.get(PowerPlant,self.plant_id).health,0)


