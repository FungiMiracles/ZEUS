"""Collect reproducible write outcomes from selected isolated integration scenarios."""
import sys,json,unittest
from pathlib import Path
from collections import Counter,defaultdict
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'tests'),str(ROOT)]
from test_paga_ai import AiTests
from test_paga_ai_budget import BudgetAdapterTests
from extensions import db
from game.paga_ai_models import PagaAiLog
from sqlalchemy import select
out=[];original=AiTests.tearDown

def capture(self):
    try:
        for row in db.session.scalars(select(PagaAiLog).order_by(PagaAiLog.id)):
            if row.operation.endswith(':GET') or row.operation.startswith('operations.'):continue
            out.append({'operation':row.operation,'validation':row.validation,'reason':row.reason,'status':(row.result or {}).get('status')})
    finally:original(self)

AiTests.tearDown=capture
names=['test_same_build_operation_and_ownership_validation_as_player','test_missing_research_or_budget_cannot_be_bypassed',
       'test_shared_research_trade_mine_loan_and_defense_mutations','test_diplomacy_and_intelligence_use_shared_country_identity',
       'test_military_order_uses_player_war_and_inventory_checks','test_factory_production_through_player_state_consumes_inputs',
       'test_roads_quote_build_upgrade_and_changed_decision','test_forum_version_prepared_from_reviewed_form_and_stale_edit_rejected',
       'test_research_quote_is_server_owned_and_stale_quote_still_fails','test_counterintelligence_uses_reviewed_level']
suite=unittest.TestSuite([AiTests(name) for name in names]);suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(BudgetAdapterTests))
result=unittest.TextTestRunner(verbosity=1).run(suite)
summary=defaultdict(Counter)
for row in out:summary[row['operation']][row['validation']]+=1
report={'database':'isolated SQLite in memory','tests':result.testsRun,'passed':result.wasSuccessful(),'summary':dict(summary),'operations':out}
(ROOT/'docs/paga-write-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in report.items() if k!='operations'},ensure_ascii=False))
if not result.wasSuccessful():raise SystemExit(1)
