"""Opt-in real Qwen acceptance on an isolated in-memory DB, never the UAT DB."""
import sys,json,argparse,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT)]
from test_paga_ai_budget import BudgetAdapterTests
from game.qwen_runtime import generate
from game.player_operations import catalogue,decision_schema
from game.finance_models import StateBudget,StateTaxAssessment
from extensions import db
from sqlalchemy import select

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--correct-invalid',action='store_true');args=parser.parse_args()
    test=BudgetAdapterTests();test.setUp()
    source_files=['game/paga_ai_budget.py','game/paga_ai_executor.py','game/player_operations.py','game/paga_ai_quotes.py','game/paga_ai_retry.py','game/paga_ai_observation.py']
    source_hashes={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in source_files}
    evidence={'passed':False,'source_sha256':source_hashes,'real_model':True,'database':'sqlite:///:memory:','correction_scenario':args.correct_invalid,'steps':[]}
    try:
        assert db.engine.url.drivername=='sqlite' and db.engine.url.database==':memory:'
        operations={k:v for k,v in catalogue(test.app).items() if k in ['game_finance.page:GET','game_finance.preview:POST','game_finance.approve:POST']}
        from game.paga_ai_budget import BUDGET_GUIDANCE
        system='Jesteś autonomicznym graczem ZEUS. Zarządzasz Państwem 1. Wykonaj pełny plan budżetu i zatwierdź go po ocenie. Zwracaj wyłącznie JSON operation_id,path,data,memory. '+BUDGET_GUIDANCE
        user={'państwo':'Państwo 1','interesy_PAGA':['Przetrwanie','Rozwój gospodarczy','Stabilność społeczna'],'sytuacja':'Potrzebne finansowanie świadczeń i inwestycji. Masz 6 kroków na analizę, plan, ocenę i zatwierdzenie.','operacje':list(operations)}
        result=test.call('game_finance.page:GET');evidence['steps'].append({'operation':'initial_finance_read','result':result})
        history=[]
        if args.correct_invalid:
            bad={'pit_rate':15,'shares':{'social_policy':80,'infrastructure':80}}
            rejected=test.call('game_finance.preview:POST',bad)
            assert rejected['status']==400
            repeated=test.call('game_finance.preview:POST',bad)
            assert repeated['status']==409
            evidence['steps'].extend([{'operation':'injected_invalid_plan','result':rejected},{'operation':'repeated_invalid_plan','result':repeated}])
            history=[{'role':'user','content':'Początkowy odczyt finansów państwa: '+json.dumps(result,ensure_ascii=False)}]
            result=rejected
            user['sytuacja']+=' Poprzedni plan z social_policy=80 i infrastructure=80 odrzucono: suma 160%. Skoryguj go i ukończ zatwierdzenie.'
        for step in range(6):
            messages=[{'role':'system','content':system},{'role':'user','content':json.dumps(user,ensure_ascii=False)},*history,{'role':'user','content':'Ostatni wynik ZEUS: '+json.dumps(result,ensure_ascii=False)}]
            decision=generate(messages,schema=decision_schema(operations))
            memory=decision.pop('memory',None)
            print(json.dumps({'step':step,'decision':decision},ensure_ascii=False),flush=True)
            if decision['operation_id']=='finish':break
            result=test.call(decision['operation_id'],decision.get('data',{}))
            evidence['steps'].append({'decision':decision,'memory':memory,'result':result})
            print(json.dumps({'step':step,'status':result['status']},ensure_ascii=False),flush=True)
            history=[{'role':'assistant','content':json.dumps(decision,ensure_ascii=False)}]
            if db.session.query(StateBudget).count():break
            if result['status']>=500:break
        db.session.expire_all()
        evidence['budgets']=db.session.query(StateBudget).count();evidence['assessments']=db.session.query(StateTaxAssessment).count()
        budget=db.session.scalar(select(StateBudget))
        if budget:
            from game.social_benefits import BenefitPayment
            evidence['saved']={'id':budget.id,'pit_rate':str(db.session.scalar(select(StateTaxAssessment.pit_rate))),'year':budget.game_year,'period':budget.period,'benefit_payments':{row.kind:str(row.paid) for row in db.session.scalars(select(BenefitPayment))}}
        evidence['source_unchanged']=all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest for name,digest in source_hashes.items())
        evidence['passed']=evidence['budgets']==1 and evidence['assessments']==1 and evidence['source_unchanged']
    finally:
        target=ROOT/'docs'/('paga-budget-real-correction.json' if args.correct_invalid else 'paga-budget-real-acceptance.json')
        target.write_text(json.dumps(evidence,ensure_ascii=False,indent=2,default=str))
        test.tearDown()
    print(json.dumps({k:v for k,v in evidence.items() if k!='steps'},ensure_ascii=False),flush=True)
    if not evidence['passed']:raise SystemExit(1)
if __name__=='__main__':main()
