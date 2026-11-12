"""Reproduce real hybrid-runner rejections and verify native writes on isolated SQLite."""
import unittest
from unittest.mock import patch
from datetime import datetime
from decimal import Decimal
from sqlalchemy import select
from extensions import db
import test_paga_ai_budget as fixtures
from game.paga_ai_actor import AiActor
from game.paga_ai_models import PagaAiJob,PagaAiWrite
from game.paga_ai_runner import act,decision_schema

class HybridContractTests(unittest.TestCase):
    def setUp(self):
        self.base=fixtures.BudgetAdapterTests();self.base.setUp();self.app=self.base.app
        clock=patch('game.budget_transfers.game_now',return_value=datetime(2990,1,1));clock.start();self.addCleanup(clock.stop)
        db.session.add(PagaAiJob(id=900,country_id=1,revision=0,kind='strategic_review',trigger='contracts',status='RUNNING'));db.session.commit()
        self.actor=AiActor(1,self.base.actor.user_id,0,900);self.step=0
    def tearDown(self):self.base.tearDown()
    def call(self,operation,data):
        self.step+=1
        return act(self.app,self.actor,900,{'operation_id':operation,'path':{},'data':data},allowed=[operation],reads=[],step=self.step,model_id='test')
    def approved(self):
        self.assertEqual(self.base.plan()['status'],200)
        self.assertEqual(self.base.call('game_finance.approve:POST',{'rationale':self.base.reason})['status'],200)
    def test_transfer_uses_mld_destination_and_server_budget_id(self):
        from game.finance_models import BudgetTransfer,StateFinancialAccount
        self.approved();before=db.session.get(StateFinancialAccount,1).reserve_balance
        data={'source':'reserve','destination':'research','amount_mld':0.1}
        result=self.call('game_finance.transfer:POST',data)
        self.assertEqual(result['outcome'],'OK',result)
        row=db.session.scalar(select(BudgetTransfer));self.assertEqual(row.amount,Decimal(100000000));self.assertEqual(row.budget_id,1)
        self.assertEqual(db.session.get(StateFinancialAccount,1,populate_existing=True).reserve_balance,before-100000000)
        self.assertEqual(self.call('game_finance.transfer:POST',data)['outcome'],'ALREADY_DONE')
        self.assertEqual(db.session.query(BudgetTransfer).count(),1)
        from game.paga_ai_context import read
        current=read(self.app,self.actor,'game_finance.page:GET',step=90,model_id='test')
        # The decision context shows MLD with two decimals (administrator decision 10 Nov 2026); the game keeps exact amounts.
        self.assertAlmostEqual(current['available_by_sector_mld']['reserve'],float((before-100000000)/1000000000),places=2)
    def test_invalid_transfer_contract_does_not_reach_game_and_budget_still_checks_funds(self):
        self.approved()
        for data in ({'source':'reserve','target':'social_policy','amount':'1.5'},
                     {'source':'reserve','destination':'defense','amount_mld':1.5},
                     {'source':'reserve','destination':'research','amount_mld':'},'}):
            result=self.call('game_finance.transfer:POST',data);self.assertEqual(result['outcome'],'DECISION',result)
        self.assertEqual(db.session.query(PagaAiWrite).count(),0)
        rejected=self.call('game_finance.transfer:POST',{'source':'reserve','destination':'research','amount_mld':100})
        self.assertEqual(rejected['outcome'],'DECISION',rejected);self.assertIn('Za mało',str(rejected))
    def test_reply_requires_content_then_posts_to_actual_message(self):
        from game.forum_models import ForumMessage
        from datetime import date
        db.session.add(ForumMessage(user_id=2,panstwo_id=2,author_name='Test',country_name='Dwa',flag_path='f',content='Wiadomość testowa.',entenda_date=date(2990,1,1)));db.session.commit()
        source=db.session.scalar(select(ForumMessage))
        result=self.call('game_forum.page:POST',{'reply_to_id':source.id})
        self.assertEqual(result['outcome'],'DECISION');self.assertIn('content',str(result));self.assertEqual(db.session.query(PagaAiWrite).count(),0)
        result=self.call('game_forum.page:POST',{'reply_to_id':source.id,'content':'Potwierdzamy gotowość do rozmów.'})
        self.assertEqual(result['outcome'],'OK',result)
        reply=db.session.scalar(select(ForumMessage).where(ForumMessage.user_id==self.actor.user_id));self.assertEqual(reply.reply_to_id,source.id)
    def test_native_html_error_reaches_ai_as_specific_reason(self):
        response=self.base.call('game_forum.page:POST')
        self.assertEqual(response['status'],400);self.assertIn('Wiadomość nie może być pusta',response['reason'])
    def test_research_requires_real_node_and_count_then_invests(self):
        from game.research_models import ResearchAccount,ResearchInvestment
        account=db.session.get(ResearchAccount,1);account.nodes={};db.session.commit()
        for data in ({'action':'invest','node':'research_node_1','count':1},{'action':'invest','node':'method'}):
            self.assertEqual(self.call('game_research.change:POST',data)['outcome'],'DECISION')
        result=self.call('game_research.change:POST',{'action':'invest','node':'method','count':1})
        self.assertEqual(result['outcome'],'OK',result);self.assertEqual(db.session.query(ResearchInvestment).count(),1)
    def test_loan_and_offer_scale_only_money_not_ids_or_quantities(self):
        from game.loan_models import StateLoan
        from game.commerce_models import TradeOffer
        loan=self.call('game_loans.change:POST',{'action':'request','lender_id':2,'amount_mld':0.2})
        self.assertEqual(loan['outcome'],'OK',loan)
        row=db.session.scalar(select(StateLoan));self.assertEqual(row.amount,200000000);self.assertEqual(row.lender_id,2)
        offer=self.call('game_trade.change:POST',{'action':'offer','cargo':{'wegiel_kamienny':2},'price_mld':0.000001,'port_id':101,'departure_rate':0})
        self.assertEqual(offer['outcome'],'OK',offer)
        row=db.session.scalar(select(TradeOffer));self.assertEqual(row.price,1000);self.assertEqual(row.cargo['wegiel_kamienny'],2);self.assertEqual(row.port_id,101)
    def test_money_projection_never_rescales_research_cost_in_points(self):
        from game.paga_ai_context import money_view
        state=money_view('game_research.state:GET',{'budget':'1000000000','pointPrice':400000000,'nodes':{'method':{'required':25,'cost':25}}})
        self.assertEqual(state['pointPrice_mld'],0.4);self.assertEqual(state['nodes']['method']['cost'],25)
        trade=money_view('game_trade.state:GET',{'offers':[{'id':7,'price':'1500000000','cargo':{'coal':20}}]})
        self.assertEqual(trade['offers'][0]['price_mld'],1.5);self.assertEqual(trade['offers'][0]['id'],7);self.assertEqual(trade['offers'][0]['cargo']['coal'],20)
        small=money_view('game_trade.state:GET',{'offers':[{'id':8,'price':'1000.00'}]})
        self.assertEqual(small['offers'][0]['price_mld'],0.000001)
    def test_grammar_and_context_offer_the_same_strict_contract(self):
        from game.paga_ai_context import operations_view
        names=['game_finance.transfer:POST','game_forum.page:POST','game_research.change:POST']
        choices=decision_schema(self.app,names,[])['properties']['actions']['items']['anyOf']
        schemas={row['properties']['operation_id']['enum'][0]:row['properties']['data'] for row in choices}
        self.assertEqual(set(schemas[names[0]]['required']),{'source','destination','amount_mld'})
        self.assertIn('content',schemas[names[1]]['required'])
        offered=operations_view(self.app,names)
        self.assertIn('amount_mld',offered[names[0]]);self.assertNotIn('budget_id',offered[names[0]]);self.assertNotIn('target',offered[names[0]])

    def test_rejected_decision_reopens_only_after_observed_state_change(self):
        from game.finance_models import BudgetTransfer
        from game.paga_ai_context import read
        self.approved()
        wanted={'source':'reserve','destination':'research','amount_mld':0.5}
        self.assertEqual(self.call('game_finance.transfer:POST',wanted)['outcome'],'DECISION')
        read(self.app,self.actor,'game_finance.page:GET',step=80,model_id='test')
        self.assertEqual(self.call('game_finance.transfer:POST',wanted)['outcome'],'BLOCKED')
        funded=self.call('game_finance.transfer:POST',{'source':'social_policy','destination':'reserve','amount_mld':0.2})
        self.assertEqual(funded['outcome'],'OK',funded)
        read(self.app,self.actor,'game_finance.page:GET',step=81,model_id='test')
        retry=self.call('game_finance.transfer:POST',wanted)
        self.assertEqual(retry['outcome'],'OK',retry)
        self.assertEqual(self.call('game_finance.transfer:POST',wanted)['outcome'],'ALREADY_DONE')
        self.assertEqual(db.session.query(BudgetTransfer).count(),2)
