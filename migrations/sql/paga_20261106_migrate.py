"""Create PAGA configuration/audit tables exclusively in ZEUS_UAT."""
from pathlib import Path
import sys
from sqlalchemy import create_engine,text,inspect
from sqlalchemy.engine import make_url


def migrate():
    root=Path(__file__).resolve().parents[2]
    assert root==Path('/home/oskar_zeus_admin/ZEUS_UAT');sys.path.insert(0,str(root))
    settings=dict(line.split('=',1) for line in (root/'.env.uat').read_text().splitlines() if line and not line.startswith('#') and '=' in line)
    url=settings['DATABASE_URL'].strip().strip('\"\'');assert make_url(url).database=='entenda_uat_db'
    import models
    from game.paga import PagaConfiguration,PagaRevision
    engine=create_engine(url,hide_parameters=True)
    with engine.begin() as connection:
        assert connection.scalar(text('SELECT DATABASE()'))=='entenda_uat_db'
        for model in (PagaConfiguration,PagaRevision):model.__table__.create(connection,checkfirst=True)
        columns={column['name'] for column in inspect(connection).get_columns(PagaConfiguration.__tablename__)}
        if 'autonomy_enabled' not in columns:connection.exec_driver_sql('ALTER TABLE game_paga_configurations ADD COLUMN autonomy_enabled BOOLEAN NOT NULL DEFAULT 0')
        if 'draft_autonomy_enabled' not in columns:connection.exec_driver_sql('ALTER TABLE game_paga_configurations ADD COLUMN draft_autonomy_enabled BOOLEAN NULL')
    print('UAT: PAGA configuration, revision and autonomy fields verified.')

if __name__=='__main__':migrate()
