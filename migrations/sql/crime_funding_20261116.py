"""Finansowanie walki z przestępczością (UAT only, 16 Nov 2026).

    venv/bin/python migrations/sql/crime_funding_20261116.py              # utworzenie tabeli game_crime_funding (idempotentne)
    venv/bin/python migrations/sql/crime_funding_20261116.py --rollback   # usunięcie tabeli

Zmiana addytywna: budżety zatwierdzone przed migracją nie mają rekordu finansowania — zasada obowiązuje
od najbliższego zatwierdzanego budżetu (gracze i PAGA2). Przy automatycznym powtórzeniu planu bez poprzedniej
kwoty przyjmowane są oczekiwania społeczne (ograniczone przydziałem sektora służb specjalnych i porządkowych).
"""
from pathlib import Path
import sys, argparse
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rollback', action='store_true')
    args = parser.parse_args()
    assert ROOT == Path('/home/oskar_zeus_admin/ZEUS_UAT'); sys.path.insert(0, str(ROOT))
    from zeus_app import app
    from extensions import db
    with app.app_context():
        assert make_url(str(db.engine.url)).database == 'entenda_uat_db', 'Migracja wyłącznie dla bazy UAT.'
        import game.finance_models  # noqa: F401 — klucz obcy do game_state_budgets
        from game.crime_funding import CrimeFunding
        if args.rollback:
            CrimeFunding.__table__.drop(db.engine, checkfirst=True)
            print('UAT: tabela game_crime_funding usunięta.')
        else:
            CrimeFunding.__table__.create(db.engine, checkfirst=True)
            print('UAT: tabela game_crime_funding zweryfikowana.')


if __name__ == '__main__':
    main()
