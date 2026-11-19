"""Handel drogą lądową (18 Nov 2026) — UAT i PREPROD.

    venv/bin/python migrations/sql/land_trade_20261118.py             # podgląd
    venv/bin/python migrations/sql/land_trade_20261118.py --apply     # zmiana (idempotentna)
    venv/bin/python migrations/sql/land_trade_20261118.py --rollback  # wycofanie (tylko bez przesyłek lądowych)

game_trade_shipments.transport: 'sea' (statek, dotychczasowe przesyłki) albo 'land' (transport lądowy między stolicami
państw z granicą lądową). Istniejące przesyłki dostają 'sea'. Środowisko wynika z katalogu skryptu (ZEUS_UAT / ZEUS_PREPROD).
"""
import argparse
from pathlib import Path
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]
TARGETS = {'ZEUS_UAT': ('.env.uat', 'entenda_uat_db'), 'ZEUS_PREPROD': ('.env.preprod', 'entenda_preprod_db')}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--rollback', action='store_true')
    args = parser.parse_args()
    env_file, database = TARGETS[ROOT.name]
    settings = dict(line.split('=', 1) for line in (ROOT / env_file).read_text().splitlines() if line and not line.startswith('#') and '=' in line)
    url = settings['DATABASE_URL'].strip().strip('"\'')
    assert make_url(url).database == database, f'Migracja wyłącznie dla bazy {database}.'
    engine = create_engine(url, hide_parameters=True)
    with engine.begin() as connection:
        assert connection.execute(text('SELECT DATABASE()')).scalar() == database
        present = 'transport' in {c['name'] for c in inspect(connection).get_columns('game_trade_shipments')}
        if args.rollback:
            if present:
                land = connection.execute(text("SELECT COUNT(*) FROM game_trade_shipments WHERE transport = 'land'")).scalar()
                assert land == 0, f'{land} przesyłek lądowych — wycofanie przerwane.'
                connection.execute(text('ALTER TABLE game_trade_shipments DROP CHECK ck_trade_shipment_transport, DROP COLUMN transport'))
            print(f'{database}: kolumna transport usunięta.')
            return
        statement = ("ALTER TABLE game_trade_shipments ADD COLUMN transport VARCHAR(8) NOT NULL DEFAULT 'sea', "
                     "ADD CONSTRAINT ck_trade_shipment_transport CHECK (transport IN ('sea','land'))")
        print(f'{database}: ' + ('kolumna transport już istnieje.' if present else statement))
        if args.apply and not present:
            connection.execute(text(statement))
            assert 'transport' in {c['name'] for c in inspect(connection).get_columns('game_trade_shipments')}
            print(f'{database}: kolumna transport dodana i zweryfikowana.')


if __name__ == '__main__':
    main()
