"""Obiekty miejskie — etap 1 (21 Nov 2026) — UAT i PREPROD.

    venv/bin/python migrations/sql/cities_20261121.py              # podgląd zmian
    venv/bin/python migrations/sql/cities_20261121.py --apply      # nowe tabele (idempotentne)
    venv/bin/python migrations/sql/cities_20261121.py --rollback   # wycofanie (tylko gdy nie ma obiektów ani wydatków miast)

Środowisko wynika z katalogu skryptu: ZEUS_UAT → entenda_uat_db (.env.uat), ZEUS_PREPROD → entenda_preprod_db (.env.preprod).
Zmiany: wyłącznie nowe tabele game_city_buildings, game_city_expenses, game_city_effects (game/city_models.py);
istniejące tabele i dane nie są zmieniane, dlatego kopia schematu nie jest potrzebna.
21 Nov 2026 (2): kolumna game_city_buildings.underfunded_at (status „Niedofinansowany”) — dodawana także w bazach,
w których tabele już istnieją.
Uwaga przy wycofaniu: efekty obiektów dodane do wskaźników społecznych (game_city_effects.applied) nie są cofane.
"""
import argparse, sys
from pathlib import Path
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]
TARGETS = {'ZEUS_UAT': ('.env.uat', 'entenda_uat_db'), 'ZEUS_PREPROD': ('.env.preprod', 'entenda_preprod_db')}
TABLES = ('game_city_buildings', 'game_city_expenses', 'game_city_effects')


def engine_for_root():
    env_file, database = TARGETS[ROOT.name]
    settings = dict(line.split('=', 1) for line in (ROOT / env_file).read_text().splitlines() if line and not line.startswith('#') and '=' in line)
    url = settings['DATABASE_URL'].strip().strip('"\'')
    assert make_url(url).database == database, f'Migracja wyłącznie dla bazy {database}.'
    return create_engine(url, hide_parameters=True), database


def missing_tables(connection):
    from game.city_models import CityBuilding, CityExpense, CityEffectState
    return [model.__table__ for model in (CityBuilding, CityExpense, CityEffectState) if not inspect(connection).has_table(model.__tablename__)]


def rollback(connection, database):
    for table in ('game_city_buildings', 'game_city_expenses'):
        if inspect(connection).has_table(table):
            assert connection.execute(text(f'SELECT COUNT(*) FROM `{table}`')).scalar() == 0, f'Tabela {table} zawiera dane — wycofanie przerwane.'
    for table in ('game_city_effects', 'game_city_expenses', 'game_city_buildings'):
        connection.execute(text(f'DROP TABLE IF EXISTS `{table}`'))
    print(f'{database}: migracja obiektów miejskich wycofana.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--rollback', action='store_true')
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    import models, game.models, game.finance_models  # noqa: F401 — klucze obce nowych tabel
    from extensions import db  # noqa: F401
    engine, database = engine_for_root()
    with engine.begin() as connection:
        assert connection.execute(text('SELECT DATABASE()')).scalar() == database
        if args.rollback:
            rollback(connection, database)
            return
        tables = missing_tables(connection)
        column = not tables and 'underfunded_at' not in {c['name'] for c in inspect(connection).get_columns('game_city_buildings')}
        print(f'{database}: nowe tabele: {[t.name for t in tables]}; kolumna underfunded_at do dodania: {column}')
        if not args.apply:
            return
        for table in tables:            # kolejność: obiekty, wydatki (klucz obcy do obiektów), efekty
            table.create(connection, checkfirst=True)
        if column:
            connection.execute(text('ALTER TABLE game_city_buildings ADD COLUMN underfunded_at DATETIME NULL'))
        assert not missing_tables(connection), 'Weryfikacja schematu nie powiodła się.'
        assert 'underfunded_at' in {c['name'] for c in inspect(connection).get_columns('game_city_buildings')}, 'Brak kolumny underfunded_at.'
        print(f'{database}: schemat obiektów miejskich zastosowany i zweryfikowany.')


if __name__ == '__main__':
    main()
