"""Add defense health and durable missile target references, only in ZEUS UAT."""
from pathlib import Path
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url


def migrate():
    root=Path(__file__).resolve().parents[2]
    assert root==Path('/home/oskar_zeus_admin/ZEUS_UAT')
    settings=dict(line.split('=',1) for line in (root/'.env.uat').read_text().splitlines() if line and not line.startswith('#') and '=' in line)
    url=settings['DATABASE_URL'].strip().strip('\"\'')
    assert make_url(url).database=='entenda_uat_db'
    with create_engine(url,hide_parameters=True).connect().execution_options(isolation_level='AUTOCOMMIT') as conn:
        assert conn.scalar(text('SELECT DATABASE()'))=='entenda_uat_db'
        columns={c['name'] for c in inspect(conn).get_columns('game_missile_defenses')}
        if 'health' not in columns:
            conn.exec_driver_sql('ALTER TABLE game_missile_defenses ADD COLUMN health INT NOT NULL DEFAULT 100, ADD CONSTRAINT ck_missile_defense_health CHECK (health BETWEEN 0 AND 100)')
        columns={c['name'] for c in inspect(conn).get_columns('game_military_flights')}
        if 'target_defense_id' not in columns:
            conn.exec_driver_sql('ALTER TABLE game_military_flights ADD COLUMN target_defense_id INT NULL, ADD CONSTRAINT fk_flight_target_defense FOREIGN KEY (target_defense_id) REFERENCES game_missile_defenses(id) ON DELETE SET NULL')
        assert conn.scalar(text('SELECT COUNT(*) FROM game_missile_defenses WHERE health IS NULL OR health<0 OR health>100'))==0
        print('UAT defense health and flight target schema verified. Existing defense health defaults to 100%.')


if __name__=='__main__':
    migrate()
