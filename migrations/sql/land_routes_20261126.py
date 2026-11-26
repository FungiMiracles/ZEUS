"""Droga przemarszu wojsk lądowych (UAT / PREPROD, 26 Nov 2026).

    venv/bin/python migrations/sql/land_routes_20261126.py uat
    venv/bin/python migrations/sql/land_routes_20261126.py preprod

Dodaje kolumnę game_land_armies.route (JSON, NULL): droga lądowa armii [[x, y], …] wyznaczana przez game.land_routes —
armia omija akweny i nie wchodzi na terytorium państw spoza wojny. Armie wysłane wcześniej mają NULL i maszerują
po odcinku prostym jak dotąd. Migracja OBOWIĄZKOWA przed wdrożeniem kodu (model LandArmy czyta tę kolumnę).
Skrypt jest idempotentny.
"""
import sys
from pathlib import Path
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
sys.path.insert(0, str(Path(__file__).resolve().parent))
from production_orders_20261122 import TARGETS, database_url


def main(target):
    env_file, database = TARGETS[target]
    url = database_url(env_file)
    assert make_url(url).database == database, 'Migracja wyłącznie dla bazy ' + database
    engine = create_engine(url)
    with engine.begin() as connection:
        assert connection.execute(text('SELECT DATABASE()')).scalar() == database
        columns = {c['name'] for c in inspect(connection).get_columns('game_land_armies')}
        if 'route' in columns:
            print(f'{database}: kolumna game_land_armies.route już istnieje.')
        else:
            connection.execute(text('ALTER TABLE game_land_armies ADD COLUMN route JSON NULL AFTER target_y'))
            print(f'{database}: dodano kolumnę game_land_armies.route.')


if __name__ == '__main__':
    args = sys.argv[1:]
    if len(args) != 1 or args[0] not in TARGETS:
        raise SystemExit('Użycie: land_routes_20261126.py uat|preprod')
    main(args[0])
