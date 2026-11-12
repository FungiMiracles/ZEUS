"""Prośba o dołączenie do wojny i pozwolenia na bazy (UAT, 12 Nov 2026):
kolumna game_diplomatic_actions.params (JSON), rozszerzona lista rodzajów (JOIN_WAR, BASE_PERMIT) i tabela game_base_permits.

    venv/bin/python migrations/sql/join_war_20261112.py             # zmiana
    venv/bin/python migrations/sql/join_war_20261112.py --rollback  # wycofanie (tylko bez nowych rodzajów)
"""
from pathlib import Path
import argparse,importlib.util
from sqlalchemy import inspect,text

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('foundation',ROOT/'migrations/sql/paga2_foundation_20261111.py');foundation=importlib.util.module_from_spec(spec);spec.loader.exec_module(foundation)
OLD="('WAR','PEACE','CEASEFIRE','RELATION')"
NEW="('WAR','PEACE','CEASEFIRE','RELATION','JOIN_WAR','BASE_PERMIT')"

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--rollback',action='store_true');args=parser.parse_args()
    app=foundation.make_app()
    from extensions import db
    import models,game.finance_models  # noqa: F401
    from game.base_permits import BasePermit
    with app.app_context():
        has_permits=inspect(db.engine).has_table(BasePermit.__tablename__)
        columns={c['name'] for c in inspect(db.engine).get_columns('game_diplomatic_actions')}
        with db.engine.begin() as c:
            if args.rollback:
                count=c.execute(text("SELECT COUNT(*) FROM game_diplomatic_actions WHERE kind IN ('JOIN_WAR','BASE_PERMIT')")).scalar()
                assert count==0,f'Istnieje {count} akcji nowych rodzajów — wycofanie przerwane.'
                c.execute(text('ALTER TABLE game_diplomatic_actions DROP CHECK ck_diplomatic_kind'))
                c.execute(text(f'ALTER TABLE game_diplomatic_actions ADD CONSTRAINT ck_diplomatic_kind CHECK (kind IN {OLD})'))
                if 'params' in columns:c.execute(text('ALTER TABLE game_diplomatic_actions DROP COLUMN params'))
                if has_permits:
                    count=c.execute(text('SELECT COUNT(*) FROM game_base_permits')).scalar()
                    assert count==0,f'Tabela game_base_permits zawiera {count} wpisów — wycofanie przerwane.'
                    c.execute(text('DROP TABLE game_base_permits'))
                print('Wycofano.')
            else:
                if 'params' not in columns:c.execute(text('ALTER TABLE game_diplomatic_actions ADD COLUMN params JSON NULL'))
                c.execute(text('ALTER TABLE game_diplomatic_actions DROP CHECK ck_diplomatic_kind'))
                c.execute(text(f'ALTER TABLE game_diplomatic_actions ADD CONSTRAINT ck_diplomatic_kind CHECK (kind IN {NEW})'))
                print('Dodano params i rodzaje JOIN_WAR, BASE_PERMIT.')
        if not args.rollback and not has_permits:BasePermit.__table__.create(db.engine);print('Utworzono game_base_permits.')
