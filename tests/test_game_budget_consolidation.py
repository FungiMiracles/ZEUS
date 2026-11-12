"""Merged infrastructure/social budgets and preserved historical balances."""
from decimal import Decimal
from unittest.mock import patch
from sqlalchemy import text,select
from extensions import db
from test_game_commerce import CommerceFixture
from test_game_military import NOW
from game.finance_models import StateBudget,StateFinancialAccount,BudgetTransfer
from game.budget_categories import normalize,CODES,LEGACY_CODES
from game.budget_transfers import infrastructure_balance,sector_balances,refund_retired_diplomacy
from game.finance_service import _reserve_for_account,FinanceError
from game.infrastructure_service import start_project
from models import Region

class BudgetConsolidationTests(CommerceFixture):
    def test_legacy_shares_sum_without_loss(self):
        old={code:Decimal(0) for code in LEGACY_CODES};old.update(road_infrastructure=Decimal('20'),mining_infrastructure=Decimal('10'),social_policy=Decimal('10'),family_policy=Decimal('15'),diplomacy=Decimal('5'),reserve=Decimal('40'))
        merged=normalize(old.items());self.assertEqual(set(merged),set(CODES));self.assertEqual(sum(merged.values()),100)
        self.assertEqual(merged['infrastructure'],30);self.assertEqual(merged['social_policy'],25);self.assertEqual(merged['reserve'],45)
    def test_mines_and_all_infrastructure_share_one_balance(self):
        db.session.execute(text("UPDATE game_state_budget_allocations SET amount=6000000000 WHERE category_code='mining_infrastructure'"))
        region=db.session.get(Region,1);region.region_ludnosc_pozamiejska=10000000;region.region_stan_infra_drogowej=50;region.region_stan_infra_kolejowej=50;db.session.commit()
        self.mine();db.session.expire_all()
        with patch('game.infrastructure_service.game_now',return_value=NOW):
            start_project(1,1,'road',1,False)
            with self.assertRaises(FinanceError):start_project(1,1,'rail',2,False)
        db.session.expire_all();budget=db.session.get(StateBudget,1)
        self.assertEqual(infrastructure_balance(db.session,budget),(6000000000,2000000000))
        self.assertEqual(sector_balances(db.session,budget)['infrastructure']['spent'],4000000000)
    def test_diplomacy_refund_keeps_history_and_is_idempotent(self):
        db.session.execute(text("INSERT INTO game_state_budget_allocations (id,budget_id,category_code,amount) VALUES (3,1,'diplomacy',1000),(4,1,'reserve',500)"))
        db.session.execute(text('UPDATE game_state_budgets SET closing_reserve=500 WHERE id=1'))
        db.session.add(StateFinancialAccount(panstwo_id=1,reserve_balance=500,last_budget_id=1,last_transaction_sequence=0,created_at=NOW,updated_at=NOW))
        db.session.add(BudgetTransfer(budget_id=1,user_id=1,source='diplomacy',destination='healthcare',amount=200,request_id='legacy-transfer',created_at=NOW,game_datetime=NOW));db.session.commit()
        self.assertEqual(refund_retired_diplomacy(db.session,1,NOW),800);db.session.commit()
        self.assertEqual(refund_retired_diplomacy(db.session,1,NOW),0);db.session.commit()
        account=db.session.get(StateFinancialAccount,1);budget=db.session.get(StateBudget,1)
        self.assertEqual(account.reserve_balance,1300);self.assertEqual(budget.closing_reserve,500)
        self.assertEqual(_reserve_for_account(account,budget),1300)
        self.assertEqual(sector_balances(db.session,budget)['reserve']['remaining'],1300)
