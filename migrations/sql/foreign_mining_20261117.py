"""UAT: extend diplomatic kinds and track each mine's actual pollution.
Run: venv/bin/python migrations/sql/foreign_mining_20261117.py
"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from paga2_foundation_20261111 import make_app
from extensions import db
from sqlalchemy import inspect,text

if __name__=='__main__':
    app=make_app()
    with app.app_context(),db.engine.begin() as connection:
        inspector=inspect(connection)
        if 'pollution_points' not in {c['name'] for c in inspector.get_columns('game_mines')}:
            connection.execute(text('ALTER TABLE game_mines ADD COLUMN pollution_points INTEGER NOT NULL DEFAULT 0'))
        checks=inspector.get_check_constraints('game_diplomatic_actions')
        constraint=next((c for c in checks if c['name']=='ck_diplomatic_kind'),None)
        if constraint and 'MINING_PERMIT' not in constraint['sqltext']:
            connection.execute(text('ALTER TABLE game_diplomatic_actions DROP CONSTRAINT ck_diplomatic_kind'))
            connection.execute(text("ALTER TABLE game_diplomatic_actions ADD CONSTRAINT ck_diplomatic_kind CHECK (kind IN ('WAR','PEACE','CEASEFIRE','RELATION','JOIN_WAR','BASE_PERMIT','MINING_PERMIT'))"))
    print('Migracja zagranicznego wydobycia zakończona.')
