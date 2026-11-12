"""Additive UAT migration for roads, port policies and audited treasury changes."""
from pathlib import Path
import sys
from sqlalchemy import create_engine,inspect,text
from sqlalchemy.engine import make_url


def migrate():
    root=Path(__file__).resolve().parents[2]
    assert root==Path('/home/oskar_zeus_admin/ZEUS_UAT')
    sys.path.insert(0,str(root))
    settings=dict(line.split('=',1) for line in (root/'.env.uat').read_text().splitlines() if line and not line.startswith('#') and '=' in line)
    url=settings['DATABASE_URL'].strip().strip('\"\'')
    assert make_url(url).database=='entenda_uat_db'
    from models import Panstwo
    from game.models import GameUser
    from game.finance_models import StateBudget
    from game.civic_models import Road,TreasuryAdjustment,CountryTaxPolicy
    engine=create_engine(url,hide_parameters=True)
    with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as conn:
        assert conn.scalar(text('SELECT DATABASE()'))=='entenda_uat_db'
        before=conn.execute(text('SELECT panstwo_id,reserve_balance,last_budget_id,last_transaction_sequence FROM game_state_financial_accounts ORDER BY panstwo_id')).all()
        tariffs=conn.execute(text('SELECT panstwo_id,rate FROM game_port_tariffs ORDER BY panstwo_id')).all()
        for model in (Road,TreasuryAdjustment,CountryTaxPolicy):model.__table__.create(conn,checkfirst=True)
        columns={c['name']:c for c in inspect(conn).get_columns('game_port_tariffs')}
        if 'block_foreign' not in columns:conn.exec_driver_sql('ALTER TABLE game_port_tariffs ADD COLUMN block_foreign BOOLEAN NOT NULL DEFAULT 0')
        if 'blocked_countries' not in columns:conn.exec_driver_sql('ALTER TABLE game_port_tariffs ADD COLUMN blocked_countries JSON NULL')
        conn.exec_driver_sql('UPDATE game_port_tariffs SET blocked_countries=JSON_ARRAY() WHERE blocked_countries IS NULL')
        if inspect(conn).get_columns('game_port_tariffs')[-1]['name']=='blocked_countries':
            column=next(c for c in inspect(conn).get_columns('game_port_tariffs') if c['name']=='blocked_countries')
            if column['nullable']:conn.exec_driver_sql('ALTER TABLE game_port_tariffs MODIFY COLUMN blocked_countries JSON NOT NULL')
        assert before==conn.execute(text('SELECT panstwo_id,reserve_balance,last_budget_id,last_transaction_sequence FROM game_state_financial_accounts ORDER BY panstwo_id')).all()
        assert tariffs==conn.execute(text('SELECT panstwo_id,rate FROM game_port_tariffs ORDER BY panstwo_id')).all()
        print('UAT civic schema verified; reserve balances and port tariffs unchanged.')


if __name__=='__main__':migrate()
