"""Zlecenia produkcji w fabrykach (UAT / PREPROD, 22 Nov 2026).

    venv/bin/python migrations/sql/production_orders_20261122.py uat
    venv/bin/python migrations/sql/production_orders_20261122.py preprod

Dodaje kolumnę game_ammunition_factories.production_target (liczba sztuk do wyprodukowania w bieżącym zleceniu).
Decyzja administratora: tryb ciągłej produkcji znika, więc wszystkie fabryki (poza fabrykami na zamówienie — rakiety
nuklearne) przechodzą we wstrzymanie i czekają na zlecenie. Skrypt jest idempotentny (kolumna dodawana raz; fabryki
bez zlecenia, które nie są wstrzymane, są wstrzymywane przy każdym uruchomieniu).
"""
import sys
from pathlib import Path
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

TARGETS = {'uat': (Path('/home/oskar_zeus_admin/ZEUS_UAT/.env.uat'), 'entenda_uat_db'),
           'preprod': (Path('/home/oskar_zeus_admin/ZEUS_PREPROD/.env.preprod'), 'entenda_preprod_db')}
ON_DEMAND = ('nuclear_missiles',)


def database_url(env_file):
    for line in env_file.read_text().splitlines():
        if line.startswith('DATABASE_URL='):
            return line.split('=', 1)[1].strip().strip('"\'')
    raise SystemExit('Brak DATABASE_URL w ' + str(env_file))


def main(target):
    env_file, database = TARGETS[target]
    url = database_url(env_file)
    assert make_url(url).database == database, 'Migracja wyłącznie dla bazy ' + database
    engine = create_engine(url)
    columns = {c['name'] for c in inspect(engine).get_columns('game_ammunition_factories')}
    with engine.begin() as connection:
        assert connection.execute(text('SELECT DATABASE()')).scalar() == database
        if 'production_target' not in columns:
            connection.execute(text('ALTER TABLE game_ammunition_factories ADD COLUMN production_target INT NULL'))
            print('Dodano kolumnę production_target.')
        paused = connection.execute(text(
            'UPDATE game_ammunition_factories SET paused = 1, running = 0 '
            'WHERE removed_at IS NULL AND paused = 0 AND production_target IS NULL AND kind NOT IN :on_demand'
        ).bindparams(__import__('sqlalchemy').bindparam('on_demand', expanding=True)), {'on_demand': list(ON_DEMAND)}).rowcount
        print(f'{database}: wstrzymano {paused} fabryk bez zlecenia produkcji.')


if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] not in TARGETS:
        raise SystemExit('Użycie: production_orders_20261122.py uat|preprod')
    main(sys.argv[1])
