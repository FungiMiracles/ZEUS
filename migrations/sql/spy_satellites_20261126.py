"""Satelity szpiegowskie (UAT / PREPROD, 26 Nov 2026).

    venv/bin/python migrations/sql/spy_satellites_20261126.py uat
    venv/bin/python migrations/sql/spy_satellites_20261126.py preprod
    venv/bin/python migrations/sql/spy_satellites_20261126.py uat --seed-ozilandia

Tworzy tabele game_spy_satellites (satelity na orbicie, z poziomem 1–4) i game_satellite_missions (misje rozpoznawcze). Satelity
w magazynie to wiersz game_resource_stocks (resource = 'spy_satellites'), a zamówienia fabryki satelitów korzystają
z istniejącej tabeli game_nuclear_orders — bez zmian schematu. Bez tych tabel kod działa, ale satelity są wyłączone.

--seed-ozilandia (tylko UAT, decyzja administratora): Ozilandia (PANSTWO_ID 7) ma opracowaną technologię
„Satelita szpiegowski” (komplet 900 pkt, bez czasu rozwoju) i 1 satelitę w magazynie. Skrypt jest idempotentny.
"""
import sys
from pathlib import Path
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
sys.path.insert(0, str(Path(__file__).resolve().parent))
from production_orders_20261122 import TARGETS, database_url

SATELLITES = """CREATE TABLE game_spy_satellites (
  id INTEGER NOT NULL AUTO_INCREMENT,
  panstwo_id INTEGER NOT NULL,
  base_id INTEGER NULL,
  status VARCHAR(16) NOT NULL DEFAULT 'launching',
  level INTEGER NOT NULL DEFAULT 1,
  mode VARCHAR(16) NOT NULL DEFAULT 'drift',
  mission_id INTEGER NULL,
  launched_at DATETIME NOT NULL,
  orbit_at DATETIME NOT NULL,
  from_x DOUBLE NOT NULL,
  from_y DOUBLE NOT NULL,
  to_x DOUBLE NOT NULL,
  to_y DOUBLE NOT NULL,
  seg_start DATETIME NOT NULL,
  seg_end DATETIME NOT NULL,
  request_id VARCHAR(36) NOT NULL,
  created_at DATETIME NOT NULL,
  PRIMARY KEY (id),
  KEY ix_game_spy_satellites_panstwo_id (panstwo_id),
  CONSTRAINT uq_spy_satellite_request UNIQUE (panstwo_id, request_id),
  CONSTRAINT ck_spy_satellite_status CHECK (status IN ('launching','orbit','lost')),
  CONSTRAINT ck_spy_satellite_mode CHECK (mode IN ('drift','mission')),
  CONSTRAINT ck_spy_satellite_segment CHECK (seg_end >= seg_start),
  CONSTRAINT ck_spy_satellite_level CHECK (level BETWEEN 1 AND 4),
  CONSTRAINT fk_spy_satellite_country FOREIGN KEY (panstwo_id) REFERENCES panstwa (PANSTWO_ID),
  CONSTRAINT fk_spy_satellite_base FOREIGN KEY (base_id) REFERENCES game_military_bases (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""

MISSIONS = """CREATE TABLE game_satellite_missions (
  id INTEGER NOT NULL AUTO_INCREMENT,
  panstwo_id INTEGER NOT NULL,
  satellite_id INTEGER NOT NULL,
  kind VARCHAR(16) NOT NULL,
  target_country_id INTEGER NOT NULL,
  target_name VARCHAR(255) NOT NULL,
  cost NUMERIC(30, 2) NOT NULL,
  starts_at DATETIME NOT NULL,
  arrives_at DATETIME NOT NULL,
  completed_at DATETIME NULL,
  report JSON NULL,
  notification_id INTEGER NULL,
  request_id VARCHAR(36) NOT NULL,
  created_at DATETIME NOT NULL,
  PRIMARY KEY (id),
  KEY ix_game_satellite_missions_panstwo_id (panstwo_id),
  KEY ix_game_satellite_missions_satellite_id (satellite_id),
  KEY ix_game_satellite_missions_arrives_at (arrives_at),
  CONSTRAINT uq_satellite_mission_request UNIQUE (panstwo_id, request_id),
  CONSTRAINT ck_satellite_mission_kind CHECK (kind IN ('bases','defenses','mines','power','silos')),
  CONSTRAINT ck_satellite_mission_time CHECK (arrives_at >= starts_at),
  CONSTRAINT fk_satellite_mission_country FOREIGN KEY (panstwo_id) REFERENCES panstwa (PANSTWO_ID),
  CONSTRAINT fk_satellite_mission_satellite FOREIGN KEY (satellite_id) REFERENCES game_spy_satellites (id) ON DELETE CASCADE,
  CONSTRAINT fk_satellite_mission_notification FOREIGN KEY (notification_id) REFERENCES game_notifications (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""

OZILANDIA = 7
TECHNOLOGY, COST = 'spy_satellite', 900


def seed(connection):
    import json
    row = connection.execute(text('SELECT nodes FROM game_research_accounts WHERE panstwo_id = :c FOR UPDATE'), {'c': OZILANDIA}).first()
    if row is None:
        raise SystemExit('Ozilandia nie ma konta badań.')
    nodes = row[0] if isinstance(row[0], dict) else json.loads(row[0] or '{}')
    if int(nodes.get(TECHNOLOGY, 0)) < COST:
        nodes[TECHNOLOGY] = COST
        connection.execute(text('UPDATE game_research_accounts SET nodes = :n WHERE panstwo_id = :c'), {'n': json.dumps(nodes), 'c': OZILANDIA})
        print('Ozilandia: opracowano technologię „Satelita szpiegowski”.')
    stock = connection.execute(text("SELECT quantity FROM game_resource_stocks WHERE panstwo_id = :c AND resource = 'spy_satellites' FOR UPDATE"), {'c': OZILANDIA}).scalar()
    if stock is None:
        connection.execute(text("INSERT INTO game_resource_stocks (panstwo_id, resource, quantity) VALUES (:c, 'spy_satellites', 1)"), {'c': OZILANDIA})
        print('Ozilandia: 1 satelita szpiegowski w magazynie.')
    elif int(stock) < 1:
        connection.execute(text("UPDATE game_resource_stocks SET quantity = 1 WHERE panstwo_id = :c AND resource = 'spy_satellites'"), {'c': OZILANDIA})
        print('Ozilandia: 1 satelita szpiegowski w magazynie.')
    else:
        print(f'Ozilandia: w magazynie już {stock} satelitów.')


def main(target, seed_ozilandia=False):
    env_file, database = TARGETS[target]
    url = database_url(env_file)
    assert make_url(url).database == database, 'Migracja wyłącznie dla bazy ' + database
    engine = create_engine(url)
    tables = set(inspect(engine).get_table_names())
    with engine.begin() as connection:
        assert connection.execute(text('SELECT DATABASE()')).scalar() == database
        for name, ddl in (('game_spy_satellites', SATELLITES), ('game_satellite_missions', MISSIONS)):
            if name in tables:
                print(f'{database}: tabela {name} już istnieje.')
            else:
                connection.execute(text(ddl)); print(f'{database}: utworzono tabelę {name}.')
        # 26 Nov 2026 (druga wersja): poziomy satelity 1–4 — kolumna level dla tabel utworzonych wcześniej
        columns = {c['name'] for c in inspect(connection).get_columns('game_spy_satellites')}
        if 'level' not in columns:
            connection.execute(text('ALTER TABLE game_spy_satellites ADD COLUMN level INTEGER NOT NULL DEFAULT 1 AFTER status, '
                                    'ADD CONSTRAINT ck_spy_satellite_level CHECK (level BETWEEN 1 AND 4)'))
            print(f'{database}: dodano kolumnę game_spy_satellites.level.')
        if seed_ozilandia:
            if target != 'uat':
                raise SystemExit('Dane Ozilandii ustawia się wyłącznie na UAT.')
            seed(connection)


if __name__ == '__main__':
    args = sys.argv[1:]
    if not args or args[0] not in TARGETS or any(a != '--seed-ozilandia' for a in args[1:]):
        raise SystemExit('Użycie: spy_satellites_20261126.py uat|preprod [--seed-ozilandia]')
    main(args[0], '--seed-ozilandia' in args[1:])
