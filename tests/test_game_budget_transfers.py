"""Salda sektorów i przesunięcia: wydatki, rezerwa, autoryzacja i powtórzenia."""
from decimal import Decimal
from datetime import datetime,timedelta
from uuid import uuid4
from unittest.mock import patch
from sqlalchemy import select,text
from test_game_military import MilitaryFixture,NOW
from extensions import db
from game.finance_models import BudgetTransfer,StateBudget,StateFinancialAccount
from game.finance_service import FinanceError,FinanceConflict,_reserve_for_account
from game.budget_transfers import transfer_funds,sector_balances,effective_allocation
from game.military_service import military_budget


class BudgetTransferTests(MilitaryFixture):
    def setUp(self):
        super().setUp()
        self.clock_transfer=patch('game.budget_transfers.game_now',return_value=NOW);self.clock_transfer.start();self.addCleanup(self.clock_transfer.stop)
        db.session.execute(text("INSERT INTO game_state_budget_allocations (id,budget_id,category_code,amount) VALUES (2,1,'infrastructure',1000),(3,1,'reserve',500),(4,1,'healthcare',0)"))
        db.session.execute(text('UPDATE game_state_budgets SET closing_reserve=500 WHERE id=1'))
        db.session.add(StateFinancialAccount(panstwo_id=1,reserve_balance=500,last_budget_id=1,last_transaction_sequence=0))
        db.session.commit()

    def move(self,source='infrastructure',destination='armed_forces',amount='100.25',**extra):
        data={'budget_id':1,'source':source,'destination':destination,'amount':amount,'request_id':str(uuid4()),**extra}
        result=transfer_funds(1,data);db.session.expire_all();return data

    def test_balances_and_spending_use_adjusted_allocations(self):
        self.move();budget=db.session.get(StateBudget,1);balances=sector_balances(db.session,budget)
        self.assertEqual(balances['infrastructure']['remaining'],Decimal('899.75'))
        self.assertEqual(balances['infrastructure']['approved'],1000)
        self.assertEqual(military_budget(db.session,1)[1],Decimal('1000000000100.25'))
        self.assertEqual(sum(b['adjustment'] for b in balances.values()),0)
        self.assertEqual(effective_allocation(db.session,1,'infrastructure'),Decimal('899.75'))

    def test_reserved_military_upkeep_cannot_be_transferred(self):
        self.set_budget(800100);base=self.base();self.change('garrison',base_id=base.id,garrison={'soldiers':10000,'tanks':100})
        with self.assertRaises(FinanceError):self.move(source='armed_forces',destination='healthcare',amount='100.01')
        self.move(source='armed_forces',destination='healthcare',amount='100')
        self.assertEqual(military_budget(db.session,1)[2],0)

    def test_reserve_updates_account_and_next_period_validation(self):
        self.move(source='reserve',destination='healthcare',amount='200')
        account=db.session.get(StateFinancialAccount,1);budget=db.session.get(StateBudget,1)
        self.assertEqual(account.reserve_balance,300)
        self.assertEqual(_reserve_for_account(account,budget),300)
        self.move(source='infrastructure',destination='reserve',amount='100')
        account=db.session.get(StateFinancialAccount,1);budget=db.session.get(StateBudget,1)
        self.assertEqual(_reserve_for_account(account,budget),400)
        self.assertEqual(budget.closing_reserve,500)

    def test_repeated_request_is_not_double_transfer(self):
        data=self.move();transfer_funds(1,data);db.session.expire_all()
        self.assertEqual(db.session.query(BudgetTransfer).count(),1)
        with self.assertRaises(FinanceConflict):transfer_funds(1,{**data,'amount':'1'})

    def test_invalid_amounts_sectors_and_overspend_rollback(self):
        for amount in ['0','-1','0.001','NaN','Infinity',True,'1000.01']:
            with self.assertRaises(FinanceError):self.move(amount=amount)
        for source,destination in [('infrastructure','infrastructure'),('bad','armed_forces'),([], 'armed_forces')]:
            with self.assertRaises(FinanceError):self.move(source=source,destination=destination)
        self.assertEqual(db.session.query(BudgetTransfer).count(),0)

    def test_foreign_budget_and_old_period_rejected(self):
        with self.assertRaises(FinanceError):transfer_funds(2,{'budget_id':1,'source':'reserve','destination':'healthcare','amount':'1','request_id':str(uuid4())})
        with patch('game.budget_transfers.game_now',return_value=datetime(2990,7,1)):
            with self.assertRaises(FinanceConflict):self.move()

    def test_infrastructure_committed_costs_cannot_be_moved(self):
        from game.infrastructure_models import InfrastructureProject
        project=InfrastructureProject(panstwo_id=1,region_id=1,budget_id=1,metric='road',levels=1,cost=1000,budget_spent=900,reserve_spent=100,starts_at=NOW,ends_at=NOW+timedelta(days=4))
        # The project's schema uses its original construction timestamps.
        db.session.add(project);db.session.commit()
        with self.assertRaises(FinanceError):self.move(amount='100.01')
        self.move(amount='100')
        self.assertEqual(sector_balances(db.session,db.session.get(StateBudget,1))['infrastructure']['remaining'],0)

    def test_api_requires_csrf_and_returns_updated_balances(self):
        from game.finanse import finance_bp
        self.app.register_blueprint(finance_bp)
        data={'budget_id':1,'source':'infrastructure','destination':'healthcare','amount':'12.50','request_id':str(uuid4())}
        self.assertEqual(self.client.post('/game/finanse/przesun',json=data).status_code,403)
        with patch('game.finanse._approved_details',side_effect=lambda session,id,country:{'balances':sector_balances(session,session.get(StateBudget,id))}):
            response=self.client.post('/game/finanse/przesun',json=data,headers={'X-CSRF-Token':'token'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(Decimal(response.json['state']['balances']['healthcare']['remaining']),Decimal('12.50'))

    def test_incoming_transfer_funds_upkeep_before_any_automatic_reduction(self):
        base=self.base();self.change('garrison',base_id=base.id,garrison={'soldiers':10000,'tanks':100})
        self.set_budget(799900)
        self.move(amount='100')
        from game.military_models import MilitaryBase
        self.assertEqual(db.session.get(MilitaryBase,base.id).garrison['tanks'],100)
        self.assertEqual(military_budget(db.session,1)[2],0)
