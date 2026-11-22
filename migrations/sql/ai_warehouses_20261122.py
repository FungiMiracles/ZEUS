"""Magazyny państw PAGA2 w miastach portowych (UAT / PREPROD, 22 Nov 2026).

    cd ZEUS_UAT && ENV_NAME=UAT venv/bin/python migrations/sql/ai_warehouses_20261122.py
    cd ZEUS_PREPROD && ENV_NAME=PREPROD ../ZEUS_UAT/venv/bin/python migrations/sql/ai_warehouses_20261122.py

Dla każdego państwa PAGA2 bez magazynu w mieście portowym zapisuje magazyn w największym własnym mieście portowym
(bez portu — w stolicy). Uruchamiane w katalogu środowiska (kod i baza tego środowiska). Skrypt jest idempotentny.
"""
import contextlib, io, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); os.chdir(ROOT)
assert os.environ.get('ENV_NAME') in ('UAT', 'PREPROD'), 'Ustaw ENV_NAME=UAT albo PREPROD.'

if __name__ == '__main__':
    from apscheduler.schedulers.background import BackgroundScheduler
    BackgroundScheduler.start = lambda *a, **k: None   # bez harmonogramów gry w procesie skryptu
    with contextlib.redirect_stdout(io.StringIO()):
        from zeus_app import app
    from extensions import db
    from sqlalchemy import text
    with app.app_context():
        print('Baza:', db.session.execute(text('SELECT DATABASE()')).scalar())
        from game.warehouse import assign_ai_warehouses
        changed = assign_ai_warehouses(db.session)
        db.session.commit()
        print(f'Zapisano magazyny {len(changed)} państw PAGA2:', changed)
