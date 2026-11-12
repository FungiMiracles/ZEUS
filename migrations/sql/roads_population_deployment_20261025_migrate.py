"""Additive UAT schema for shared roads, upgrades, age shares and deployment flow."""
from pathlib import Path
import sys
from sqlalchemy import create_engine,inspect,text
from sqlalchemy.engine import make_url


def migrate():
    root=Path(__file__).resolve().parents[2];assert root==Path('/home/oskar_zeus_admin/ZEUS_UAT');sys.path.insert(0,str(root))
    settings=dict(line.split('=',1) for line in (root/'.env.uat').read_text().splitlines() if line and not line.startswith('#') and '=' in line)
    url=settings['DATABASE_URL'].strip().strip('\"\'');assert make_url(url).database=='entenda_uat_db'
    from models import Panstwo
    from game.models import GameUser
    from game.finance_models import StateBudget
    from game.civic_models import Road,RoadInvestment,RoadProposal
    from game.population_structure import PopulationStructure
    engine=create_engine(url,hide_parameters=True)
    with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as conn:
        assert conn.scalar(text('SELECT DATABASE()'))=='entenda_uat_db'
        before=conn.execute(text('SELECT panstwo_id,reserve_balance,last_budget_id,last_transaction_sequence FROM game_state_financial_accounts ORDER BY panstwo_id')).all()
        for model in (RoadInvestment,RoadProposal,PopulationStructure):model.__table__.create(conn,checkfirst=True)
        columns={c['name'] for c in inspect(conn).get_columns('game_military_bases')}
        if 'deployment_request_id' not in columns:conn.exec_driver_sql('ALTER TABLE game_military_bases ADD COLUMN deployment_request_id VARCHAR(36) NULL')
        if 'deployment_payload' not in columns:conn.exec_driver_sql('ALTER TABLE game_military_bases ADD COLUMN deployment_payload JSON NULL')
        assert before==conn.execute(text('SELECT panstwo_id,reserve_balance,last_budget_id,last_transaction_sequence FROM game_state_financial_accounts ORDER BY panstwo_id')).all()
    print('UAT schema verified; existing road costs, population data, garrisons and reserve balances unchanged.')


if __name__=='__main__':migrate()
