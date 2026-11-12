"""Road modernization debits the shared infrastructure budget (service used by the WIKI road builder).
The player road routes were removed from the game on 10 Nov 2026; the budget rule itself is unchanged."""
from decimal import Decimal
from uuid import uuid4
from unittest.mock import patch
from sqlalchemy import text
from extensions import db
from test_game_military import MilitaryFixture,NOW
from game.civic_models import Road
from game.road_projects import upgrade_road
from game.budget_overview import budget_overview


class RoadBudgetRefreshTests(MilitaryFixture):
    def test_upgrade_debit_is_visible_in_shared_budget_overview(self):
        db.session.execute(text("INSERT INTO game_state_budget_allocations(id,budget_id,category_code,amount) VALUES(2,1,'infrastructure',10000000000)"))
        road=Road(panstwo_id=1,kind='national',start_x=0,start_y=0,end_x=10,end_y=0,path=[[0,0],[10,0]],distance_km=10,cost=2500000,budget_id=1,user_id=1,request_id=str(uuid4()));db.session.add(road);db.session.commit();id=road.id
        def funds():return Decimal(next(item['remaining'] for item in budget_overview(db.session,1)['items'] if item['code']=='infrastructure'))
        with patch('game.budget_overview.game_now',return_value=NOW),patch('game.road_projects.game_now',return_value=NOW),patch('game.road_projects.neighboring_countries',return_value={2}):
            before=funds();self.assertEqual(before,9997500000)
            upgrade_road(1,{'road_id':id,'request_id':str(uuid4()),'expected_cost':'8000000.00'})
            db.session.expire_all()
            self.assertEqual(before-funds(),8000000)
            self.assertEqual(db.session.get(Road,id).kind,'motorway')

    def test_infrastructure_page_has_no_road_tab(self):
        from pathlib import Path
        page=(Path(__file__).resolve().parents[1]/'templates/game/infrastructure.html').read_text()
        self.assertNotIn('infrastructure-tab-roads',page);self.assertNotIn('road_builder',page);self.assertIn('game_infrastructure_tabs.js',page)
