"""Allow mine targets in missile defense, strictly in ZEUS_UAT."""
from pathlib import Path
from sqlalchemy import create_engine,text,inspect
from sqlalchemy.engine import make_url


def migrate():
    root=Path(__file__).resolve().parents[2]
    assert root==Path('/home/oskar_zeus_admin/ZEUS_UAT')
    settings=dict(line.split('=',1) for line in (root/'.env.uat').read_text().splitlines() if line and not line.startswith('#') and '=' in line)
    url=settings['DATABASE_URL'].strip().strip('\"\'')
    assert make_url(url).database=='entenda_uat_db'
    with create_engine(url,hide_parameters=True).connect().execution_options(isolation_level='AUTOCOMMIT') as conn:
        assert conn.scalar(text('SELECT DATABASE()'))=='entenda_uat_db'
        clause=next((row['sqltext'] for row in inspect(conn).get_check_constraints('game_missile_defenses') if row['name']=='ck_missile_defense_kind'),None)
        if not clause or "'mine'" not in clause:
            drop='DROP CONSTRAINT' if 'mariadb' in conn.scalar(text('SELECT VERSION()')).lower() else 'DROP CHECK'
            conn.exec_driver_sql(f"ALTER TABLE game_missile_defenses {drop} ck_missile_defense_kind, ADD CONSTRAINT ck_missile_defense_kind CHECK (target_kind IN ('region','city','base','mine'))")
        assert conn.scalar(text("SELECT COUNT(*) FROM game_missile_defenses WHERE target_kind NOT IN ('region','city','base','mine')"))==0
        print('UAT missile-defense target constraint now includes mines. Existing records unchanged.')


if __name__=='__main__':migrate()
