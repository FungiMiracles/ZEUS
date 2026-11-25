"""General-tax arithmetic and atomic research/factory production spending."""
from decimal import Decimal
from datetime import timedelta
from uuid import uuid4
from unittest.mock import patch
from sqlalchemy import text,select
from extensions import db
from test_game_military import MilitaryFixture,NOW
from game.finance_service import calculate_budget,FinanceError,FinanceConflict
from game.research_service import change_research,settle_production,node_state
from game.research_models import ResearchAccount,ResearchExpense,ResearchInvestment,AmmunitionFactory
from game.budget_transfers import sector_balances,infrastructure_balance
from game.finance_models import StateBudget
from game.military_models import MissileDefense,MissileDefenseExpense
from game.general_tax import capture_basis
from game.population_structure import PopulationStructure
from models import Spoleczenstwo,Gospodarka


class GeneralTaxTests(MilitaryFixture):
    def setUp(self):
        super().setUp()
        Gospodarka.__table__.create(db.engine,checkfirst=True)
        db.session.add_all([Gospodarka(panstwo_id=i,bezrobocie=3) for i in (1,2)])
        db.session.commit()

    def test_revenue_uses_employment_gdp_and_percentage_bonus(self):
        basis={'algorithm_version':5,'working_population':2837739,'gdp_per_capita':'104579','unemployment_percent':'3','infrastructure':'67','satisfaction':57,'stability':89,'education':58,'public_health':72,'crime':8,'trust':61}
        result=calculate_budget(1,2000000,123,10,99,{'research':20,'reserve':80},revenue_basis=basis)
        annual=Decimal('104579')*2837739*Decimal('.97')*Decimal('.10')*Decimal('1.0335')
        self.assertEqual(result['annual_pit'],annual.quantize(Decimal('.00000001')))
        self.assertEqual(result['revenue_components']['bonus_percent'],'3.35')
        self.assertEqual(result['tax_total'],(annual/2).quantize(Decimal('.01')))
        self.assertEqual(result['annual_cit'],0);self.assertEqual(result['cit_rate'],0)
        self.assertEqual(sum(result['allocations'].values()),result['tax_total']+123)

    def test_capture_requires_configured_age_and_social_data_and_exact_counts(self):
        Spoleczenstwo.__table__.create(db.engine,checkfirst=True)
        with self.assertRaises(FinanceError):capture_basis(db.session,1)
        db.session.execute(text('UPDATE panstwa SET panstwo_populacja=7,panstwo_PKB=70000 WHERE PANSTWO_ID=1'))
        db.session.execute(text('UPDATE regiony SET region_stan_infra_drogowej=50,region_stan_infra_kolejowej=50,region_stan_infra_energetycznej=50,region_stan_infra_mieszkalnej=50,region_stan_infra_portowej=100,region_polozenie_id=1 WHERE region_id=1'))
        db.session.add(PopulationStructure(panstwo_id=1,children=20,working=60,seniors=20,version=1,actor='Test'));db.session.commit()
        with self.assertRaises(FinanceError):capture_basis(db.session,1)
        db.session.add(Spoleczenstwo(panstwo_id=1,zadowolenie_spoleczne=60,stabilnosc_spoleczna=70,poziom_edukacji=80,zdrowie_publiczne=75,przestepczosc=8,zaufanie_do_wladzy=61));db.session.commit()
        basis=capture_basis(db.session,1);self.assertEqual(basis['working_population'],4);self.assertEqual(Decimal(basis['infrastructure']),50)

    def test_general_tax_assessment_constraint_preserves_legacy_rules(self):
        from game.finance_models import StateTaxAssessment
        from sqlalchemy.exc import IntegrityError
        StateTaxAssessment.__table__.create(db.engine,checkfirst=True)
        fields=dict(id=1,budget_id=1,panstwo_id=1,game_year=2990,period=1,pit_rate=10,cit_rate=0,gdp_snapshot=1000,population_snapshot=100,gdp_per_capita_snapshot=10,annual_pit=1234,annual_cit=0,half_year_pit=617,half_year_cit=0,total_amount=617,basis_captured_at=NOW,basis_game_datetime=NOW,assessed_at=NOW,assessed_game_datetime=NOW,calculation_version=4,general_tax_basis={'basis':{},'components':{}})
        db.session.execute(StateTaxAssessment.__table__.insert().values(**fields));db.session.commit()
        with self.assertRaises(IntegrityError):
            with db.session.begin_nested():db.session.execute(StateTaxAssessment.__table__.insert().values(**{**fields,'id':2,'budget_id':2,'panstwo_id':2,'calculation_version':3}))
        with self.assertRaises(IntegrityError):
            with db.session.begin_nested():db.session.execute(StateTaxAssessment.__table__.insert().values(**{**fields,'id':3,'budget_id':3,'panstwo_id':3,'cit_rate':20}))


    def approval_scenario(self,rate=10):
        from sqlalchemy import MetaData,Table,Column,Integer,String
        from game.finance_models import BudgetCategory,StateFinancialPeriod,StateTaxAssessment,StateFinancialTransaction,StateBudgetAllocation,StateFinancialAccount
        from game.finance_service import preview_budget,approve_manual_budget
        # SQLite transaction fixture: use native integer identities and omit MySQL-only date checks.
        db.session.remove()
        for model in (StateBudgetAllocation,StateBudget):model.__table__.drop(db.engine)
        for model in (BudgetCategory,StateFinancialPeriod,StateBudget,StateBudgetAllocation,StateTaxAssessment,StateFinancialTransaction):
            metadata=MetaData()
            Table(model.__tablename__,metadata,*[Column(c.name,Integer() if c.primary_key and c.name=='id' else String(c.type.length) if isinstance(c.type,String) else c.type,primary_key=c.primary_key,nullable=True) for c in model.__table__.columns]).create(db.engine)
        db.session.add_all([BudgetCategory(code=code,name_pl=code,display_order=i+1,is_reserve=code=='reserve') for i,code in enumerate(__import__('game.budget_categories',fromlist=['CODES']).CODES)])
        Spoleczenstwo.__table__.create(db.engine,checkfirst=True)
        db.session.execute(text('UPDATE panstwa SET panstwo_populacja=1000,panstwo_PKB=5000000 WHERE PANSTWO_ID=2'))
        db.session.execute(text('UPDATE regiony SET region_stan_infra_drogowej=50,region_stan_infra_kolejowej=50,region_stan_infra_energetycznej=50,region_stan_infra_mieszkalnej=50,region_polozenie_id=1 WHERE region_id=2'))
        db.session.add(PopulationStructure(panstwo_id=2,children=20,working=60,seniors=20,version=1,actor='Test'))
        db.session.add(Spoleczenstwo(panstwo_id=2,zadowolenie_spoleczne=60,stabilnosc_spoleczna=70,poziom_edukacji=80,zdrowie_publiczne=75,przestepczosc=8,zaufanie_do_wladzy=61));db.session.commit()
        with patch('game.finance_service.game_now',return_value=NOW):
            quote=preview_budget(2,pit_rate=rate,cit_rate=99,shares={'reserve':100})
            db.session.execute(text('UPDATE spoleczenstwo SET zadowolenie_spoleczne=61 WHERE panstwo_id=2'));db.session.commit()
            arguments=dict(year=2990,period=1,expected_basis=quote['basis_token'],pit_rate=rate,cit_rate=99,shares={'reserve':100})
            with self.assertRaises(FinanceConflict):approve_manual_budget(2,**arguments)
            quote=preview_budget(2,pit_rate=rate,cit_rate=99,shares={'reserve':100});arguments['expected_basis']=quote['basis_token']
            if rate>20:
                from game.forum_models import GameNotification
                with patch('game.finance_service._post_transaction',side_effect=FinanceError('rollback test')):
                    with self.assertRaises(FinanceError):approve_manual_budget(2,**arguments)
                db.session.expire_all()
                social=db.session.scalar(select(Spoleczenstwo).where(Spoleczenstwo.panstwo_id==2))
                self.assertEqual(social.zadowolenie_spoleczne,61)
                self.assertEqual(db.session.query(GameNotification).count(),0)
            result=approve_manual_budget(2,**arguments);self.assertTrue(approve_manual_budget(2,**arguments)['already_approved'])
        assessment=db.session.scalar(select(StateTaxAssessment));self.assertEqual(assessment.cit_rate,0);self.assertEqual(assessment.calculation_version,6)
        self.assertEqual(assessment.general_tax_basis['basis']['working_population'],600)
        self.assertEqual(assessment.total_amount,Decimal('15027.24')*rate)
        self.assertEqual(db.session.get(StateFinancialAccount,2).reserve_balance,assessment.total_amount)
        operations=list(db.session.scalars(select(StateFinancialTransaction.operation_type)));self.assertEqual(operations.count('TAX_GENERAL'),1);self.assertNotIn('TAX_CIT',operations)

        if rate>20:
            from game.forum_models import GameNotification
            db.session.expire_all()
            social=db.session.scalar(select(Spoleczenstwo).where(Spoleczenstwo.panstwo_id==2))
            self.assertEqual((social.zadowolenie_spoleczne,social.stabilnosc_spoleczna,social.zaufanie_do_wladzy),(59,68,59))
            notifications=list(db.session.scalars(select(GameNotification)))
            self.assertEqual(len(notifications),1)
            self.assertEqual(notifications[0].user_id,2)
            self.assertEqual(notifications[0].system_text,'Obywatele nie są zadowoleni z wysokiej stawki podatku. Zaufanie do władzy: -2, zadowolenie społeczne: -2')
            self.assertEqual(assessment.general_tax_basis['tax_penalty']['penalty'],2)
            self.login(2)
            response=self.post(f'/game/forum/powiadomienia/{notifications[0].id}/otworz')
            self.assertEqual(response.status_code,303)
            self.assertEqual(response.location,'/game/spoleczenstwo')

    def test_preview_approval_snapshots_and_ledger_use_only_general_tax(self):
        self.approval_scenario()

    def test_penalty_notification_and_ledger_are_atomic_and_idempotent(self):
        self.approval_scenario(57)

    def test_penalty_examples_and_half_up_boundary(self):
        from game.general_tax import tax_penalty
        basis={'trust':61,'satisfaction':57}
        for rate,expected in [(20,0),(27,0),(37,1),(57,3),(36.8,1),(36.79,0)]:
            self.assertEqual(tax_penalty(basis,Decimal(str(rate))),expected)

    def test_zero_employment_zero_tax_and_negative_crime_bonus(self):
        from game.general_tax import annual_revenue
        basis={'working_population':100,'gdp_per_capita':'1000','unemployment_percent':'100','infrastructure':'0','satisfaction':0,'stability':0,'education':0,'public_health':0,'crime':100,'trust':0}
        self.assertEqual(annual_revenue(basis,Decimal(50))[0],0)
        basis['unemployment_percent']='0'
        self.assertEqual(annual_revenue(basis,Decimal(0))[0],0)
        self.assertEqual(annual_revenue(basis,Decimal(50))[0],49500)



class ResearchTests(MilitaryFixture):
    def setUp(self):
        super().setUp()
        db.session.execute(text("INSERT INTO game_state_budget_allocations(id,budget_id,category_code,amount) VALUES(2,1,'research',100000000000),(3,1,'infrastructure',10000000000)"));db.session.commit()
        for target in ['game.research_service.game_now','game.research.game_now']:
            clock=patch(target,return_value=NOW);clock.start();self.addCleanup(clock.stop)

    def change_research(self,action,**extra):
        data={'action':action,'request_id':str(uuid4()),'expected_point_price':150000000,**extra};change_research(1,data);db.session.expire_all();return data

    def finish_research(self):
        # 13 Nov 2026: technologie mają czas rozwoju — tu symulujemy jego upływ (pole timers opróżnione = rozwój zakończony)
        account=db.session.get(ResearchAccount,1);account.timers={};db.session.commit()

    def unlock(self):
        self.change_research('buy',count=120)
        for node,count in (('method',25),('arms_industry',25),('interceptor_ammo',20)):
            self.change_research('invest',node=node,count=count);self.finish_research()

    def test_buy_partial_investment_level_prices_and_idempotence(self):
        data=self.change_research('buy',count=40);change_research(1,data)
        self.assertEqual(db.session.get(ResearchAccount,1).points,40)
        self.assertEqual(sector_balances(db.session,db.session.get(StateBudget,1))['research']['spent'],6000000000)   # 40 × 150 mln ROI
        data=self.change_research('invest',node='method',count=4);change_research(1,data)
        self.assertEqual(node_state(db.session.get(ResearchAccount,1).nodes['method'],'method')['progress'],4)
        self.change_research('invest',node='method',count=6);self.change_research('invest',node='method',count=15)
        self.assertEqual(node_state(db.session.get(ResearchAccount,1).nodes['method'],'method')['level'],1)
        self.assertEqual(db.session.get(ResearchAccount,1).points,15)
        self.assertEqual(db.session.query(ResearchExpense).count(),1);self.assertEqual(db.session.query(ResearchInvestment).count(),3)
        with self.assertRaises(FinanceConflict):change_research(1,{**data,'count':5})

    def test_locked_nodes_overinvestment_bad_counts_and_no_money_have_no_effect(self):
        for action,extra in [('buy',{'count':0}),('buy',{'count':True}),('buy',{'count':1000}),('invest',{'node':'interceptor_ammo','count':1}),('invest',{'node':'medical','count':1})]:
            with self.assertRaises(FinanceError):self.change_research(action,**extra)
        self.assertIsNone(db.session.get(ResearchAccount,1))
        self.change_research('buy',count=40)
        with self.assertRaises(FinanceError):self.change_research('invest',node='method',count=26)
        self.assertEqual(db.session.get(ResearchAccount,1).points,40)
        self.assertEqual(node_state(25,'method')['level'],1)
        self.assertTrue(node_state(25,'method')['maximum'])

    # Production test: grid with enough energy (since 10 Nov 2026 a deficit stops factories; see test_infrastructure_effects).
    @patch('game.industry_service.powered_factories',new=lambda session,factories,production,resident:{f.id for f in factories})
    def test_factory_unlock_cost_ownership_and_exact_daily_production(self):
        with self.assertRaises(FinanceError):self.change_research('factory',region_id=1,x=10,y=20)
        self.unlock()
        from game.commerce_models import ResourceStock
        db.session.add_all([ResourceStock(panstwo_id=1,resource=code,quantity=100) for code in ('zelazo','ropa_naftowa')]);db.session.commit()
        with patch('game.military_geography.region_contains',return_value=True):
            with self.assertRaises(FinanceError):self.change_research('factory',region_id=2,x=10,y=20)
            data=self.change_research('factory',region_id=1,x=10,y=20);change_research(1,data)
        self.assertEqual(db.session.query(AmmunitionFactory).count(),1)
        db.session.query(AmmunitionFactory).one().paused=True;db.session.commit()
        from game.industry_service import change_industry   # 22 Nov 2026: zlecenie produkcji
        change_industry(1,dict(action='resume',category='factory',object_id=db.session.query(AmmunitionFactory).one().id,quantity=10**6,request_id=str(uuid4())))
        self.assertEqual(infrastructure_balance(db.session,db.session.get(StateBudget,1))[1],8000000000)
        self.assertEqual(sector_balances(db.session,db.session.get(StateBudget,1))['infrastructure']['spent'],2000000000)
        for hours,expected in [(23,0),(49,10),(50,10),(72,15)]:
            settle_production(db.session,1,NOW+timedelta(hours=hours));db.session.commit()
            self.assertEqual(db.session.get(ResearchAccount,1).ammunition,expected)
        settle_production(db.session,2,NOW+timedelta(days=100));self.assertEqual(db.session.get(ResearchAccount,1).ammunition,15)

    def test_refill_from_own_stock_without_charging_military_budget(self):
        self.unlock();account=db.session.get(ResearchAccount,1);account.ammunition=20;db.session.commit()
        self.change('defense_place',target_kind='region',target_id=1)
        defense=db.session.scalar(select(MissileDefense));defense.ammunition=90;db.session.commit()
        self.set_budget(0)
        self.change('defense_refill',defense_id=defense.id,count=10,source='stock');db.session.expire_all()
        self.assertEqual(db.session.get(ResearchAccount,1).ammunition,10);self.assertEqual(db.session.get(MissileDefense,defense.id).ammunition,100)
        self.assertEqual(db.session.query(MissileDefenseExpense).count(),1)
        defense=db.session.get(MissileDefense,defense.id);defense.ammunition=0;db.session.commit()
        with self.assertRaises(FinanceError):self.change('defense_refill',defense_id=defense.id,count=11,source='stock')
        self.assertEqual(db.session.get(ResearchAccount,1).ammunition,10)

    def test_research_http_scope_csrf_and_repeat_purchase(self):
        from game.research import research_bp
        self.app.register_blueprint(research_bp)
        data={'action':'buy','count':2,'expected_point_price':150000000,'request_id':str(uuid4())}
        self.assertEqual(self.client.post('/game/badania/zmien',json=data).status_code,403)
        for _ in range(2):self.assertEqual(self.client.post('/game/badania/zmien',json=data,headers={'X-CSRF-Token':'token'}).status_code,200)
        state=self.client.get('/game/badania/stan');self.assertEqual(state.status_code,200);self.assertEqual(state.json['points'],2)
        self.login(2);other=self.client.get('/game/badania/stan');self.assertEqual(other.json['points'],0)
        self.assertEqual(db.session.get(ResearchAccount,1).points,2)

    def test_stale_point_price_cannot_charge_the_updated_price_silently(self):
        with self.assertRaises(FinanceConflict):change_research(1,{'action':'buy','count':1,'expected_point_price':200000000,'request_id':str(uuid4())})
        self.assertIsNone(db.session.get(ResearchAccount,1))
