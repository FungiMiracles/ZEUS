"""Plany wojenne PAGA2 (21 Nov 2026) — UAT i PREPROD.

    venv/bin/python migrations/sql/paga2_war_plans_20261121.py              # podgląd
    venv/bin/python migrations/sql/paga2_war_plans_20261121.py --apply      # nowa tabela (idempotentne)
    venv/bin/python migrations/sql/paga2_war_plans_20261121.py --rollback   # usunięcie tabeli (gdy pusta)

Środowisko wynika z katalogu skryptu: ZEUS_UAT → entenda_uat_db (.env.uat), ZEUS_PREPROD → entenda_preprod_db (.env.preprod).
Zmiana: wyłącznie nowa tabela game_paga2_war_plans (game/paga2/models.py: Paga2WarPlan); istniejące dane bez zmian.
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
    from game.paga2.models import Paga2WarPlan
    engine, database = engine_for_root()
    with engine.begin() as connection:
        assert connection.execute(text('SELECT DATABASE()')).scalar() == database
        exists = inspect(connection).has_table(Paga2WarPlan.__tablename__)
        if args.rollback:
            if exists:
                assert connection.execute(text('SELECT COUNT(*) FROM game_paga2_war_plans')).scalar() == 0, 'Tabela zawiera plany — wycofanie przerwane.'
                connection.execute(text('DROP TABLE game_paga2_war_plans'))
            print(f'{database}: tabela planów wojennych usunięta.')
            return
        print(f'{database}: tabela game_paga2_war_plans do utworzenia: {not exists}')
        if not args.apply:
            return
        Paga2WarPlan.__table__.create(connection, checkfirst=True)
        assert inspect(connection).has_table(Paga2WarPlan.__tablename__)
        print(f'{database}: tabela planów wojennych utworzona i zweryfikowana.')


if __name__ == '__main__':
    main()
