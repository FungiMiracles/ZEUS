"""UAT: allow complete credential erasure while keeping historical author foreign keys."""
from pathlib import Path
from sqlalchemy import create_engine,inspect,text
from sqlalchemy.engine import make_url


def migrate():
    root=Path(__file__).resolve().parents[2]
    assert root==Path('/home/oskar_zeus_admin/ZEUS_UAT')
    settings=dict(line.split('=',1) for line in (root/'.env.uat').read_text().splitlines() if line and not line.startswith('#') and '=' in line)
    url=settings['DATABASE_URL'].strip().strip('\"\'')
    assert make_url(url).database=='entenda_uat_db'
    engine=create_engine(url,hide_parameters=True)
    with engine.begin() as connection:
        assert connection.scalar(text('SELECT DATABASE()'))=='entenda_uat_db'
        columns={row['name']:row for row in inspect(connection).get_columns('game_users')}
        for name,length in [('email',254),('email_normalized',254),('password_hash',255)]:
            if not columns[name]['nullable']:
                connection.exec_driver_sql(f'ALTER TABLE game_users MODIFY COLUMN {name} VARCHAR({length}) NULL')
    print('UAT: credential columns allow full erasure. No accounts or credentials changed.')

if __name__=='__main__':migrate()
