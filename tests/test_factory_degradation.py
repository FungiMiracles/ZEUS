"""Factory degradation, waste filters, environment branch, public-trust transfer rule and UI clean-up (10 Nov 2026)."""
import unittest
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
from sqlalchemy import select,text
from extensions import db
from models import Region
import test_industry_0011 as industry_fixture
import test_game_budget_transfers as transfer_fixture
from game.industry_catalog import TECHNOLOGIES,FACTORIES,WASTE_FILTER_COSTS
from game.industry_models import IndustryMovement
from game.research_models import ResearchAccount,AmmunitionFactory
from game.finance_service import FinanceError

ROOT=Path(__file__).resolve().parents[1]


class FactoryDegradationTests(unittest.TestCase):
    def setUp(self):
        self.base=industry_fixture.IndustryTests();self.base.setUp()
        db.session.execute(text("INSERT INTO game_state_budget_allocations (id,budget_id,category_code,amount) VALUES (91,1,'environment',20000000000)"))
        db.session.get(Region,1).region_degradacja_srodowiska=10;db.session.commit()
    def tearDown(self):self.base.tearDown()
    def degradation(self):db.session.expire_all();return db.session.get(Region,1).region_degradacja_srodowiska
    def build(self,kind='chips',level=1):return self.base.operation(kind=kind,level=level)
    def act(self,action,id):return self.base.operation(action=action,category='factory',object_id=id)
    def last(self):return db.session.execute(select(IndustryMovement.sector,IndustryMovement.amount).order_by(IndustryMovement.id.desc()).limit(1)).one()

    def test_tree_and_prices(self):
        self.assertEqual((TECHNOLOGIES['armored']['parent'],TECHNOLOGIES['tanks']['parent']),('arms_industry','armored'))
        self.assertEqual({key:(TECHNOLOGIES[key]['cost'],TECHNOLOGIES[key]['parent']) for key in ('environment_tech','air_filters','waste_filters')},
                         {'environment_tech':(30,'method'),'air_filters':(150,'environment_tech'),'waste_filters':(120,'environment_tech')})
        self.assertEqual((TECHNOLOGIES['environment_tech']['label'],TECHNOLOGIES['waste_filters']['label']),('Technologie ochrony środowiska','Filtr odpadów fabrycznych'))
        self.assertEqual(WASTE_FILTER_COSTS,[1100000000,1300000000,1500000000,1700000000,1900000000])
        self.assertEqual(max(len(rule['levels']) for rule in FACTORIES.values()),len(WASTE_FILTER_COSTS),'every factory level has a price')

    def test_armored_needs_arms_industry(self):
        from game.research_service import change_research
        account=db.session.get(ResearchAccount,1);account.nodes={'method':25};db.session.commit()
        with self.assertRaises(FinanceError):change_research(1,dict(action='invest',node='armored',count=1,request_id=str(uuid4())))

    def test_factory_adds_degradation_and_liquidation_removes_it(self):
        first=self.build();self.assertEqual(self.degradation(),12)
        self.build('tanks');self.assertEqual(self.degradation(),14)
        self.act('remove',first);self.assertEqual(self.degradation(),12)

    def test_waste_filter_requires_technology(self):
        id=self.build()
        account=db.session.get(ResearchAccount,1);nodes=dict(account.nodes);nodes.pop('waste_filters');account.nodes=nodes;db.session.commit()
        with self.assertRaises(FinanceError) as error:self.act('waste_filter',id)
        self.assertIn('Filtr odpadów fabrycznych',str(error.exception))
        self.assertEqual(self.degradation(),12)

    def test_waste_filter_price_by_level_environment_budget_and_no_refund(self):
        for level in (1,5):
            with self.subTest(level=level):
                id=self.build('chips',level)
                self.act('waste_filter',id);self.assertEqual(self.last(),('environment',Decimal(WASTE_FILTER_COSTS[level-1])))
                db.session.expire_all();factory=db.session.get(AmmunitionFactory,id)
                self.assertTrue(factory.waste_filter);self.assertEqual(factory.degradation_points,0)
                with self.assertRaises(FinanceError):self.act('waste_filter',id)
                before=self.degradation();self.act('remove',id)
                self.assertEqual(self.last(),('infrastructure',-Decimal(FACTORIES['chips']['levels'][level-1]['cost'])/4),'refund covers the factory only')
                self.assertEqual(self.degradation(),before,'a filtered factory added nothing')
        self.assertEqual(self.degradation(),10)

    def test_environment_budget_must_cover_the_filter(self):
        db.session.execute(text("UPDATE game_state_budget_allocations SET amount=1000 WHERE id=91"));db.session.commit()
        id=self.build()
        with self.assertRaises(FinanceError) as error:self.act('waste_filter',id)
        self.assertIn('ochrony środowiska',str(error.exception))

    def test_state_and_environment_screen_points(self):
        from game.industry_service import industry_state
        from game.srodowisko import generated_points
        id=self.build();self.base.operation(category='power',kind='coal')
        with self.base.app.test_request_context():row=next(r for r in industry_state(db.session,1)['objects'] if r['category']=='factory' and r['id']==id)
        self.assertEqual((row['degradation'],row['wasteFilter'],row['wasteFilterCost']),(2,False,1100000000))
        self.assertEqual(generated_points(db.session,[1]),{'air':2,'degradation':2})
        self.act('waste_filter',id);self.assertEqual(generated_points(db.session,[1]),{'air':2,'degradation':0})


class TrustTransferTests(unittest.TestCase):
    def setUp(self):
        self.base=transfer_fixture.BudgetTransferTests();self.base.setUp()
    def tearDown(self):self.base.tearDown()
    def trust(self,value):
        from models import Spoleczenstwo
        db.session.add(Spoleczenstwo(panstwo_id=1,zaufanie_do_wladzy=value));db.session.commit()

    def test_sector_transfers_allowed_at_any_trust(self):
        # 21 Nov 2026: próg zaufania 65 zniesiony — przesunięcia działają także przy niskim zaufaniu
        self.trust(10)
        self.base.move(amount='10')
        self.base.move(source='infrastructure',destination='reserve',amount='10')
        self.base.move(source='reserve',destination='infrastructure',amount='10')

    def test_trust_above_threshold_and_missing_data_allow(self):
        self.base.move(amount='10')
        self.trust(66);self.base.move(amount='10')


class InterfaceTests(unittest.TestCase):
    def read(self,path):return (ROOT/path).read_text()

    def test_old_budget_displays_removed(self):
        self.assertNotIn('id="industry-budget"',self.read('templates/game/_factories.html'))
        self.assertNotIn('military-budget',self.read('templates/game/military.html'))
        self.assertNotIn('military-available',self.read('templates/game/military.html'))
        self.assertNotIn('intel-budget',self.read('templates/game/intelligence.html'))
        self.assertNotIn('Dostępne środki ·',self.read('templates/game/research.html'))
        self.assertIn('id="module-funds-available"',self.read('templates/game/_module_funds.html'))

    def test_headings_without_country_name(self):
        self.assertNotIn('game_country.nazwa',self.read('templates/game/_page_heading.html'))

    def test_factory_tooltip_texts_and_icons(self):
        script=self.read('static/js/game_industry.js')
        for text_ in ('Dodaj filtr odpadów fabrycznych',"'DEGRADACJA ŚRODOWISKA.svg'","'FILTR ODPADÓW FABRYCZNYCH.svg'","'waste_filter'",'z budżetu ochrony środowiska'):self.assertIn(text_,script)
        for icon in ('DEGRADACJA ŚRODOWISKA.svg','FILTR ODPADÓW FABRYCZNYCH.svg','ŚRODOWISKO.svg'):self.assertTrue((ROOT/'static/icons'/icon).exists())
        self.assertIn("'waste_filter':'FILTR ODPADÓW FABRYCZNYCH.svg'",self.read('templates/macros/icons.html'))

    def test_trust_refusal_shown_in_red_next_to_the_transfer_form(self):
        form=self.read('templates/game/_finanse_form.html');script=self.read('static/js/game_finanse.js')
        self.assertIn('class="finance-transfer-error" data-transfer-error role="alert"',form)
        self.assertIn('Społeczeństwo nie ufa władzy wystarczająco (',script)
        self.assertIn("sector_transfers_allowed===false",script)
        self.assertIn('.finance-transfer-error',self.read('static/css/game_civic.css'))

    def test_armored_and_tanks_on_one_line_with_arms_industry(self):
        from game.research import technology_layout
        p=technology_layout()['positions'];a,b,c=p['arms_industry'],p['armored'],p['tanks']
        self.assertAlmostEqual((b['x']-a['x'])*(c['y']-a['y'])-(b['y']-a['y'])*(c['x']-a['x']),0,delta=5)
        self.assertLess(abs(c['x']-a['x']),abs(c['x']-a['x'])+1);self.assertLess(c['x'],b['x'])

    def test_waste_filter_icon_centred(self):
        import re
        svg=self.read('static/icons/FILTR ODPADÓW FABRYCZNYCH.svg')
        x,y,w,h=map(float,re.search(r'viewBox="([^"]+)"',svg).group(1).split())
        # Drawing bounding box: x 121–507, y 103–510.
        self.assertAlmostEqual(x+w/2,(121+507)/2,delta=3);self.assertAlmostEqual(y+h/2,(103+510)/2,delta=3)
