"""Ataki na wrogie armie w marszu (22 Nov 2026) — UAT i PREPROD.

    venv/bin/python migrations/sql/land_intercept_20261122.py              # podgląd
    venv/bin/python migrations/sql/land_intercept_20261122.py --apply      # zmiana (idempotentna)
    venv/bin/python migrations/sql/land_intercept_20261122.py --rollback   # wycofanie (gdy brak oddziałów przechwytujących)

Środowisko wynika z katalogu skryptu: ZEUS_UAT → entenda_uat_db (.env.uat), ZEUS_PREPROD → entenda_preprod_db (.env.preprod).
Zmiana w game_land_armies: kolumna target_army_id (FK do game_land_armies, ON DELETE SET NULL) oraz rozszerzone
ograniczenia ck_land_army_role (+'intercept') i ck_land_army_target (+'army'). Istniejące dane bez zmian.
"""
import argparse, sys
from pathlib import Path
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]
TARGETS = {'ZEUS_UAT': ('.env.uat', 'entenda_uat_db'), 'ZEUS_PREPROD': ('.env.preprod', 'entenda_preprod_db')}
NEW_CHECKS = {'ck_land_army_role': "role IN ('invasion','city_defense','intercept')", 'ck_land_army_target': "target_kind IN ('base','city','army')"}
OLD_CHECKS = {'ck_land_army_role': "role IN ('invasion','city_defense')", 'ck_land_army_target': "target_kind IN ('base','city')"}


def engine_for_root():
    env_file, database = TARGETS[ROOT.name]
    settings = dict(line.split('=', 1) for line in (ROOT / env_file).read_text().splitlines() if line and not line.startswith('#') and '=' in line)
    url = settings['DATABASE_URL'].strip().strip('"\'')
    assert make_url(url).database == database, f'Migracja wyłącznie dla bazy {database}.'
    return create_engine(url, hide_parameters=True), database


def checks(connection):
    return dict(connection.execute(text("SELECT CONSTRAINT_NAME, CHECK_CLAUSE FROM information_schema.CHECK_CONSTRAINTS "
                                        "WHERE CONSTRAINT_SCHEMA = DATABASE() AND CONSTRAINT_NAME IN ('ck_land_army_role','ck_land_army_target')")).all())


def replace_checks(connection, wanted):
    for name, clause in wanted.items():
        connection.execute(text(f'ALTER TABLE game_land_armies DROP CHECK {name}'))
        connection.execute(text(f'ALTER TABLE game_land_armies ADD CONSTRAINT {name} CHECK ({clause})'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--rollback', action='store_true')
    args = parser.parse_args()
    engine, database = engine_for_root()
    with engine.begin() as connection:
        assert connection.execute(text('SELECT DATABASE()')).scalar() == database
        has_column = 'target_army_id' in {c['name'] for c in inspect(connection).get_columns('game_land_armies')}
        current = checks(connection)
        done = has_column and 'intercept' in current.get('ck_land_army_role', '') and "'army'" in current.get('ck_land_army_target', '')
        if args.rollback:
            used = connection.execute(text("SELECT COUNT(*) FROM game_land_armies WHERE role='intercept' OR target_kind='army'")).scalar()
            assert used == 0, 'Istnieją oddziały przechwytujące — wycofanie przerwane.'
            if has_column:
                connection.execute(text('ALTER TABLE game_land_armies DROP FOREIGN KEY fk_land_army_target_army'))
                connection.execute(text('ALTER TABLE game_land_armies DROP COLUMN target_army_id'))
            replace_checks(connection, OLD_CHECKS)
            print(f'{database}: zmiana wycofana.')
            return
        print(f'{database}: kolumna target_army_id: {has_column}; ograniczenia: {current}; zmiana potrzebna: {not done}')
        if not args.apply or done:
            return
        if not has_column:
            connection.execute(text('ALTER TABLE game_land_armies ADD COLUMN target_army_id INT NULL, '
                                    'ADD CONSTRAINT fk_land_army_target_army FOREIGN KEY (target_army_id) REFERENCES game_land_armies(id) ON DELETE SET NULL'))
        replace_checks(connection, NEW_CHECKS)
        print(f'{database}: zmiana zastosowana: {checks(connection)}')


if __name__ == '__main__':
    main()
