"""UAT-only factory damage and attached missile-defense schema."""
from pathlib import Path
from sqlalchemy import create_engine,text,inspect
from sqlalchemy.engine import make_url


def migrate():
    root=Path(__file__).resolve().parents[2];assert root==Path('/home/oskar_zeus_admin/ZEUS_UAT')
    settings=dict(line.split('=',1) for line in (root/'.env.uat').read_text().splitlines() if line and not line.startswith('#') and '=' in line)
    url=settings['DATABASE_URL'].strip().strip('\"\'');assert make_url(url).database=='entenda_uat_db'
    with create_engine(url,hide_parameters=True).connect().execution_options(isolation_level='AUTOCOMMIT') as connection:
        assert connection.scalar(text('SELECT DATABASE()'))=='entenda_uat_db'
        columns={row['name'] for row in inspect(connection).get_columns('game_ammunition_factories')}
        if 'health' not in columns:connection.exec_driver_sql('ALTER TABLE game_ammunition_factories ADD COLUMN health INT NOT NULL DEFAULT 100, ADD CONSTRAINT ck_factory_health CHECK (health BETWEEN 0 AND 100)')
        if 'destroyed_at' not in columns:connection.exec_driver_sql('ALTER TABLE game_ammunition_factories ADD COLUMN destroyed_at DATETIME NULL')
        if 'target_factory_id' not in {row['name'] for row in inspect(connection).get_columns('game_military_flights')}:connection.exec_driver_sql('ALTER TABLE game_military_flights ADD COLUMN target_factory_id INT NULL, ADD CONSTRAINT fk_flight_target_factory FOREIGN KEY (target_factory_id) REFERENCES game_ammunition_factories(id) ON DELETE SET NULL')
        clause=next(row['sqltext'] for row in inspect(connection).get_check_constraints('game_missile_defenses') if row['name']=='ck_missile_defense_kind')
        if "'factory'" not in clause:
            drop='DROP CONSTRAINT' if 'mariadb' in connection.scalar(text('SELECT VERSION()')).lower() else 'DROP CHECK'
            connection.exec_driver_sql(f"ALTER TABLE game_missile_defenses {drop} ck_missile_defense_kind, ADD CONSTRAINT ck_missile_defense_kind CHECK (target_kind IN ('region','city','base','mine','factory'))")
        print('UAT factory health/defense targets verified. Existing factories have 100% life; historical point purchases, ammunition and budgets unchanged.')


if __name__=='__main__':migrate()
