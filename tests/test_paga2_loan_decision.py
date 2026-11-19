"""19 Nov 2026: o udzieleniu pożyczki decyduje wyłącznie PAGA2 — relacja z wnioskującym, rezerwa, konserwatyzm fiskalny, solidarność."""
import unittest
from types import SimpleNamespace as NS

from game.paga2.finance import loan_decision,loan_decision_options,relation_factor,execute

MLD=1e9


class LoanDecisionRuleTests(unittest.TestCase):
    def test_relation_scale(self):
        self.assertEqual(relation_factor('neutralne'),0)
        self.assertEqual(relation_factor('sojusznicze'),1)
        self.assertEqual(relation_factor('egzystencjalnie wrogie'),-1)
        self.assertEqual(relation_factor('chłodne'),-0.2)

    def test_neutral_average_country_lends_quarter_of_reserve(self):
        accept,share,_=loan_decision(25*MLD,100*MLD,'neutralne',50,50)
        self.assertTrue(accept);self.assertEqual(share,.25)
        self.assertFalse(loan_decision(26*MLD,100*MLD,'neutralne',50,50)[0])

    def test_each_factor_moves_the_decision(self):
        base=loan_decision(30*MLD,100*MLD,'neutralne',50,50)[0]
        self.assertFalse(base)
        self.assertTrue(loan_decision(30*MLD,100*MLD,'przyjazne',50,50)[0])      # (i) lepsza relacja
        self.assertTrue(loan_decision(30*MLD,200*MLD,'neutralne',50,50)[0])      # (ii) więcej własnych środków
        self.assertTrue(loan_decision(30*MLD,100*MLD,'neutralne',20,50)[0])      # (iii) mniejszy konserwatyzm fiskalny
        self.assertTrue(loan_decision(30*MLD,100*MLD,'neutralne',50,80)[0])      # (iv) większa solidarność
        self.assertFalse(loan_decision(10*MLD,100*MLD,'neutralne',95,10)[0])     # skrajnie oszczędne i niesolidarne państwo

    def test_bad_relation_war_or_empty_reserve_reject(self):
        self.assertFalse(loan_decision(1*MLD,1000*MLD,'złe',0,100)[0])
        self.assertTrue(loan_decision(1*MLD,1000*MLD,'chłodne',50,50)[0])
        self.assertFalse(loan_decision(1*MLD,1000*MLD,'sojusznicze',0,100,at_war=True)[0])
        self.assertFalse(loan_decision(1*MLD,0,'sojusznicze',0,100)[0])
        self.assertLessEqual(loan_decision(1,100*MLD,'sojusznicze',0,100)[1],.75)


class LoanDecisionOptionTests(unittest.TestCase):
    def ctx(self,loans,reserve=100*MLD,relation='Neutralne',traits=None):
        screen={'data':{'reserve':str(reserve),'loans':loans}}
        return NS(screen=lambda name:screen if name=='loans' else None,traits=traits or {'fiscal_conservatism':50,'solidarity':50},
                  situation={'relations':{7:{'relation':'neutralne','relation_label':relation,'state':'pokoj'}},'at_war':[]})

    def loan(self,id,amount,**extra):
        return {'id':id,'borrowerId':7,'borrower':'Ozilandia','lenderId':2,'amount':str(amount),'status':'pending','ownRequest':False,**extra}

    def test_every_pending_request_gets_a_required_answer(self):
        options=loan_decision_options(self.ctx([self.loan(1,20*MLD),self.loan(2,21*MLD),self.loan(3,1*MLD,status='accepted'),self.loan(4,1*MLD,ownRequest=True)]))
        self.assertEqual([(o.action,o.payload['loan_id']) for o in options],[('LOAN_ACCEPT',1),('LOAN_REJECT',2)])   # druga liczona od rezerwy pomniejszonej o pierwszą (25% z 80 MLD)
        for option in options:
            self.assertTrue(option.payload['required']);self.assertEqual(option.payload['group'],f'loan:decide:{option.payload["loan_id"]}')
            self.assertIn('konserwatyzm fiskalny',option.notes[0])

    def test_execute_calls_player_loan_route(self):
        calls=[]
        ctx=self.ctx([self.loan(1,20*MLD)]);ctx.call=lambda path,json=None,**k:calls.append((path,json)) or (200,{'ok':True})
        option=loan_decision_options(ctx)[0]
        self.assertEqual(execute(ctx,option)['status'],200)
        self.assertEqual(calls,[('/game/pozyczki/zmien',{'action':'accept','loan_id':1})])


if __name__=='__main__':
    unittest.main()
