"""Historia przynależności regionów — wyzwalanie spod aneksji i wskrzeszanie państw (UAT / PREPROD, 23 Nov 2026).

    venv/bin/python migrations/sql/region_history_20261123.py uat [--dry-run]
    venv/bin/python migrations/sql/region_history_20261123.py preprod [--dry-run]

1. Tworzy tabelę game_region_transfers (game.region_history.RegionTransfer).
2. Odtwarza historię sprzed migracji (tylko gdy tabela jest pusta): zaczyna od pierwotnej przynależności regionów
   z mapy static/maps/entenda_regiony.geojson i chronologicznie nakłada zdarzenia gry:
   * aneksje regionów — zakończone okupacje regionów (game_occupations, kind='region', status='ANNEXED') → ANNEX;
   * utraty suwerenności (game_sovereignty_losses) — wszystkie regiony należące w tej chwili do pokonanego państwa
     przechodzą do anektującego → SOVEREIGNTY (przy tej samej chwili aneksja regionu stołecznego idzie pierwsza).
   Na końcu porównuje wynik symulacji z obecną przynależnością regionów (raport rozbieżności, bez zmian w regionach).
Skrypt jest idempotentny.
"""
import json
import sys
from pathlib import Path
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
sys.path.insert(0, str(Path(__file__).resolve().parent))
from production_orders_20261122 import TARGETS, database_url

ROOT = Path(__file__).resolve().parents[2]
DDL = """CREATE TABLE game_region_transfers (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  region_id INT NOT NULL,
  from_country_id INT NOT NULL,
  to_country_id INT NOT NULL,
  kind VARCHAR(12) NOT NULL,
  occupation_id INT NULL,
  actor_country_id INT NULL,
  details JSON NULL,
  game_at DATETIME NOT NULL,
  created_at DATETIME NOT NULL,
  KEY ix_game_region_transfers_region_id (region_id),
  KEY ix_game_region_transfers_to_country_id (to_country_id),
  CONSTRAINT fk_region_transfers_region FOREIGN KEY (region_id) REFERENCES regiony (region_id),
  CONSTRAINT fk_region_transfers_from FOREIGN KEY (from_country_id) REFERENCES panstwa (PANSTWO_ID),
  CONSTRAINT fk_region_transfers_to FOREIGN KEY (to_country_id) REFERENCES panstwa (PANSTWO_ID),
  CONSTRAINT fk_region_transfers_occupation FOREIGN KEY (occupation_id) REFERENCES game_occupations (id),
  CONSTRAINT ck_region_transfer_kind CHECK (kind IN ('ANNEX','SOVEREIGNTY','RESTORE'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""


def original_owners():
    data = json.loads((ROOT / 'static/maps/entenda_regiony.geojson').read_text(encoding='utf-8'))
    owners = {}
    for feature in data['features']:
        props = feature.get('properties') or {}
        if props.get('region_id') is not None and props.get('panstwo_id') is not None:
            owners[int(props['region_id'])] = int(props['panstwo_id'])
    return owners


def history(connection):
    """[(region_id, from, to, kind, occupation_id, game_at)] i raport rozbieżności z obecną przynależnością."""
    owners = original_owners()
    events = []
    for row in connection.execute(text("SELECT id, region_id, owner_id, occupier_id, ended_at FROM game_occupations "
                                       "WHERE kind='region' AND status='ANNEXED' AND ended_at IS NOT NULL")):
        events.append((row.ended_at, 0, row.id, 'ANNEX', row))
    for row in connection.execute(text("SELECT panstwo_id, annexed_by, occupation_id, lost_at FROM game_sovereignty_losses")):
        events.append((row.lost_at, 1, row.panstwo_id, 'SOVEREIGNTY', row))
    events.sort(key=lambda item: item[:3])
    rows = []
    for moment, _, _, kind, row in events:
        if kind == 'ANNEX':
            rows.append((row.region_id, row.owner_id, row.occupier_id, 'ANNEX', row.id, moment))
            owners[row.region_id] = row.occupier_id
        else:
            for region_id, owner in sorted(owners.items()):
                if owner == row.panstwo_id:
                    rows.append((region_id, row.panstwo_id, row.annexed_by, 'SOVEREIGNTY', row.occupation_id, moment))
                    owners[region_id] = row.annexed_by
    current = dict(connection.execute(text('SELECT region_id, panstwo_id FROM regiony')).all())
    mismatches = sorted(region for region, owner in owners.items() if region in current and current[region] != owner)
    return [item for item in rows if item[0] in current and item[1] != item[2]], mismatches, current


def main(target, dry_run=False):
    env_file, database = TARGETS[target]
    url = database_url(env_file)
    assert make_url(url).database == database
    engine = create_engine(url)
    with engine.begin() as connection:
        assert connection.execute(text('SELECT DATABASE()')).scalar() == database
        exists = 'game_region_transfers' in inspect(connection).get_table_names()
        rows, mismatches, current = history(connection)
        print(f'{database}: odtworzone zmiany przynależności: {len(rows)} '
              f'(ANNEX {sum(1 for r in rows if r[3] == "ANNEX")}, SOVEREIGNTY {sum(1 for r in rows if r[3] == "SOVEREIGNTY")}).')
        if mismatches:
            print(f'{database}: regiony, których obecny właściciel różni się od wyniku symulacji ({len(mismatches)}; zmiany spoza gry, '
                  f'np. secesje w WIKI): {mismatches[:40]}{" …" if len(mismatches) > 40 else ""}')
        if dry_run:
            print(f'{database}: --dry-run, bez zmian.'); return
        if not exists:
            connection.execute(text(DDL))
            print(f'{database}: utworzono tabelę game_region_transfers.')
        if connection.execute(text('SELECT COUNT(*) FROM game_region_transfers')).scalar():
            print(f'{database}: historia już zapisana — pomijam odtwarzanie.'); return
        for region_id, source, target_id, kind, occupation_id, moment in rows:
            connection.execute(text('INSERT INTO game_region_transfers (region_id, from_country_id, to_country_id, kind, occupation_id, details, game_at, created_at) '
                                    'VALUES (:r, :f, :t, :k, :o, :d, :g, UTC_TIMESTAMP())'),
                               {'r': region_id, 'f': source, 't': target_id, 'k': kind, 'o': occupation_id, 'g': moment,
                                'd': json.dumps({'backfill': 'region_history_20261123'})})
        print(f'{database}: zapisano {len(rows)} wierszy historii.')


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if a != '--dry-run']
    if len(args) != 1 or args[0] not in TARGETS:
        raise SystemExit('Użycie: region_history_20261123.py uat|preprod [--dry-run]')
    main(args[0], '--dry-run' in sys.argv)
