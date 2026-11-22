"""Lokalizacja magazynu państwa (UAT / PREPROD, 22 Nov 2026).

    venv/bin/python migrations/sql/warehouse_20261122.py uat
    venv/bin/python migrations/sql/warehouse_20261122.py preprod

Tworzy tabelę game_warehouses (miasto magazynu państwa). Skrypt jest idempotentny.
"""
import sys
from pathlib import Path
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
sys.path.insert(0, str(Path(__file__).resolve().parent))
from production_orders_20261122 import TARGETS, database_url

DDL = """CREATE TABLE game_warehouses (
  panstwo_id INT NOT NULL PRIMARY KEY,
  miasto_id INT NOT NULL,
  user_id INT NULL,
  chosen_at DATETIME NOT NULL,
  CONSTRAINT fk_game_warehouses_country FOREIGN KEY (panstwo_id) REFERENCES panstwa (PANSTWO_ID),
  CONSTRAINT fk_game_warehouses_city FOREIGN KEY (miasto_id) REFERENCES miasta (miasto_id),
  CONSTRAINT fk_game_warehouses_user FOREIGN KEY (user_id) REFERENCES game_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""


def main(target):
    env_file, database = TARGETS[target]
    url = database_url(env_file)
    assert make_url(url).database == database
    engine = create_engine(url)
    if 'game_warehouses' in inspect(engine).get_table_names():
        print(f'{database}: tabela game_warehouses już istnieje.'); return
    with engine.begin() as connection:
        assert connection.execute(text('SELECT DATABASE()')).scalar() == database
        connection.execute(text(DDL))
    print(f'{database}: utworzono tabelę game_warehouses.')


if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] not in TARGETS:
        raise SystemExit('Użycie: warehouse_20261122.py uat|preprod')
    main(sys.argv[1])
