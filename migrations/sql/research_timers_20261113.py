"""Czas rozwoju technologii (UAT, 13 Nov 2026): kolumna game_research_accounts.timers (JSON).

    venv/bin/python migrations/sql/research_timers_20261113.py             # dodanie kolumny
    venv/bin/python migrations/sql/research_timers_20261113.py --rollback  # usunięcie kolumny
"""
from pathlib import Path
import argparse,importlib.util
from sqlalchemy import inspect,text

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('foundation',ROOT/'migrations/sql/paga2_foundation_20261111.py');foundation=importlib.util.module_from_spec(spec);spec.loader.exec_module(foundation)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--rollback',action='store_true');args=parser.parse_args()
    app=foundation.make_app()
    from extensions import db
    with app.app_context():
        columns={c['name'] for c in inspect(db.engine).get_columns('game_research_accounts')}
        with db.engine.begin() as c:
            if args.rollback:
                if 'timers' in columns:c.execute(text('ALTER TABLE game_research_accounts DROP COLUMN timers'))
                print('Usunięto timers.')
            elif 'timers' not in columns:
                c.execute(text('ALTER TABLE game_research_accounts ADD COLUMN timers JSON NULL'));print('Dodano timers.')
            else:print('Kolumna timers już istnieje.')
