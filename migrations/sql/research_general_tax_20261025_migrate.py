"""Add research/factory records and tax-basis snapshots, exclusively in UAT."""
from pathlib import Path
from sqlalchemy import create_engine,inspect,text
from sqlalchemy.engine import make_url
import sys


def migrate():
    root=Path(__file__).resolve().parents[2]
    assert root==Path('/home/oskar_zeus_admin/ZEUS_UAT');sys.path.insert(0,str(root))
    settings=dict(line.split('=',1) for line in (root/'.env.uat').read_text().splitlines() if line and not line.startswith('#') and '=' in line)
    url=settings['DATABASE_URL'].strip().strip('\"\'');assert make_url(url).database=='entenda_uat_db'
    import models
    from game.finance_models import StateBudget,StateTaxAssessment
    from game.research_models import ResearchAccount,ResearchExpense,ResearchInvestment,AmmunitionFactory
    engine=create_engine(url,hide_parameters=True)
    with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as connection:
        assert connection.scalar(text('SELECT DATABASE()'))=='entenda_uat_db'
        reserves=list(connection.execute(text('SELECT panstwo_id,reserve_balance FROM game_state_financial_accounts ORDER BY panstwo_id')))
        for model in (ResearchAccount,ResearchExpense,ResearchInvestment,AmmunitionFactory):model.__table__.create(connection,checkfirst=True)
        if 'general_tax_basis' not in {c['name'] for c in inspect(connection).get_columns(StateTaxAssessment.__tablename__)}:connection.exec_driver_sql('ALTER TABLE game_state_tax_assessments ADD COLUMN general_tax_basis JSON NULL')
        clause=next((row['sqltext'] for row in inspect(connection).get_check_constraints(StateTaxAssessment.__tablename__) if row['name']=='ck_gsta_annual_amounts'),None)
        if clause and 'general_tax_basis' not in clause:
            drop='DROP CONSTRAINT' if 'mariadb' in connection.scalar(text('SELECT VERSION()')).lower() else 'DROP CHECK'
            connection.exec_driver_sql(f"ALTER TABLE game_state_tax_assessments {drop} ck_gsta_annual_amounts, ADD CONSTRAINT ck_gsta_annual_amounts CHECK (annual_pit>=0 AND annual_cit>=0 AND ((calculation_version<4 AND annual_pit=gdp_snapshot*pit_rate/200 AND annual_cit=gdp_snapshot*cit_rate/200) OR (calculation_version>=4 AND cit_rate=0 AND annual_cit=0 AND general_tax_basis IS NOT NULL)))")
        operation=next((row['sqltext'] for row in inspect(connection).get_check_constraints('game_state_financial_transactions') if row['name']=='ck_gsft_operation'),None)
        if operation and 'TAX_GENERAL' not in operation:
            drop='DROP CONSTRAINT' if 'mariadb' in connection.scalar(text('SELECT VERSION()')).lower() else 'DROP CHECK'
            connection.exec_driver_sql(f"ALTER TABLE game_state_financial_transactions {drop} ck_gsft_operation, ADD CONSTRAINT ck_gsft_operation CHECK ((operation_type IN ('TAX_PIT','TAX_CIT','TAX_GENERAL') AND direction='CREDIT' AND category_code IS NULL) OR (operation_type='BUDGET_ALLOCATION' AND direction='DEBIT' AND category_code IS NOT NULL AND category_code<>'reserve'))")
        assert any('general_tax_basis' in row['sqltext'] for row in inspect(connection).get_check_constraints(StateTaxAssessment.__tablename__) if row['name']=='ck_gsta_annual_amounts')
        assert reserves==list(connection.execute(text('SELECT panstwo_id,reserve_balance FROM game_state_financial_accounts ORDER BY panstwo_id')))
        print('UAT research/factory tables and general-tax snapshot column verified. Existing budgets and reserve balances unchanged.')


if __name__=='__main__':migrate()
