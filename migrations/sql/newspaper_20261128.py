"""Gazeta „Entenda News” (UAT / PREPROD, 28 Nov 2026).

    venv/bin/python migrations/sql/newspaper_20261128.py uat
    venv/bin/python migrations/sql/newspaper_20261128.py preprod

Tworzy tabelę game_newspaper_issues (wydania gazety za kolejne miesiące Entendy: fakty, migawka stanu świata do porównania
z następnym wydaniem, treść). Bez tabeli ekran „Wydarzenia” pokazuje pustą gazetę, a harmonogram nic nie zapisuje.
Skrypt jest idempotentny.
"""
import sys
from pathlib import Path
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
sys.path.insert(0, str(Path(__file__).resolve().parent))
from production_orders_20261122 import TARGETS, database_url

ISSUES = """CREATE TABLE game_newspaper_issues (
  id INTEGER NOT NULL AUTO_INCREMENT,
  game_year INTEGER NOT NULL,
  game_month SMALLINT NOT NULL,
  period_start DATETIME NOT NULL,
  period_end DATETIME NOT NULL,
  status VARCHAR(16) NOT NULL DEFAULT 'PENDING',
  facts JSON NOT NULL,
  snapshot JSON NOT NULL,
  content JSON NULL,
  author VARCHAR(16) NULL,
  provider VARCHAR(32) NULL,
  model VARCHAR(80) NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  next_attempt_at DATETIME NULL,
  error VARCHAR(500) NULL,
  created_at DATETIME NOT NULL,
  published_at DATETIME NULL,
  PRIMARY KEY (id),
  CONSTRAINT uq_newspaper_month UNIQUE (game_year, game_month),
  CONSTRAINT ck_newspaper_status CHECK (status IN ('PENDING','PUBLISHED'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""


def main(target):
    env_file, database = TARGETS[target]
    url = database_url(env_file)
    assert make_url(url).database == database, 'Migracja wyłącznie dla bazy ' + database
    engine = create_engine(url)
    tables = set(inspect(engine).get_table_names())
    with engine.begin() as connection:
        assert connection.execute(text('SELECT DATABASE()')).scalar() == database
        if 'game_newspaper_issues' in tables:
            print(f'{database}: tabela game_newspaper_issues już istnieje.')
        else:
            connection.execute(text(ISSUES)); print(f'{database}: utworzono tabelę game_newspaper_issues.')


if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] not in TARGETS:
        raise SystemExit('Użycie: newspaper_20261128.py uat|preprod')
    main(sys.argv[1])
