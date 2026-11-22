"""Trendy wskaźników społecznych (22 Nov 2026) — UAT i PREPROD.

    venv/bin/python migrations/sql/society_trends_20261122.py              # podgląd
    venv/bin/python migrations/sql/society_trends_20261122.py --apply      # nowa tabela + zasiew z historii (idempotentne)
    venv/bin/python migrations/sql/society_trends_20261122.py --rollback   # usunięcie tabeli

Środowisko wynika z katalogu skryptu: ZEUS_UAT → entenda_uat_db (.env.uat), ZEUS_PREPROD → entenda_preprod_db (.env.preprod).
Zmiana: wyłącznie nowa tabela game_society_trends (game/society_strip.py: GameSocietyTrend); zasiew — dwie ostatnie
zmiany ośmiu wskaźników z spoleczenstwo_state_history. Istniejące dane bez zmian.
"""
import argparse, sys
from pathlib import Path
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]
TARGETS = {'ZEUS_UAT': ('.env.uat', 'entenda_uat_db'), 'ZEUS_PREPROD': ('.env.preprod', 'entenda_preprod_db')}


def engine_for_root():
    env_file, database = TARGETS[ROOT.name]
    settings = dict(line.split('=', 1) for line in (ROOT / env_file).read_text().splitlines() if line and not line.startswith('#') and '=' in line)
    url = settings['DATABASE_URL'].strip().strip('"\'')
    assert make_url(url).database == database, f'Migracja wyłącznie dla bazy {database}.'
    return create_engine(url, hide_parameters=True), database


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--rollback', action='store_true')
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    import models, game.models  # noqa: F401 — klucze obce
    from game.society_strip import GameSocietyTrend, seed_from_history
    engine, database = engine_for_root()
    with engine.begin() as connection:
        assert connection.execute(text('SELECT DATABASE()')).scalar() == database
        exists = inspect(connection).has_table(GameSocietyTrend.__tablename__)
        if args.rollback:
            if exists:
                connection.execute(text('DROP TABLE game_society_trends'))
            print(f'{database}: tabela trendów usunięta.')
            return
        print(f'{database}: tabela game_society_trends do utworzenia: {not exists}')
        if not args.apply:
            return
        if exists:
            print(f'{database}: tabela już istnieje — bez zmian.')
            return
        GameSocietyTrend.__table__.create(connection)
        print(f'{database}: utworzono tabelę, zasiano trendów z historii: {seed_from_history(connection)}')


if __name__ == '__main__':
    main()
