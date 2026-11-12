"""Lotniskowce na morzu (UAT, 12 Nov 2026): game_military_vessels.fighters, air_base_id i rodzaj 'carriers'.

    venv/bin/python migrations/sql/carriers_20261112.py             # zmiana
    venv/bin/python migrations/sql/carriers_20261112.py --rollback  # wycofanie (tylko bez lotniskowców)
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
        columns={c['name'] for c in inspect(db.engine).get_columns('game_military_vessels')}
        with db.engine.begin() as c:
            if args.rollback:
                count=c.execute(text("SELECT COUNT(*) FROM game_military_vessels WHERE kind='carriers'")).scalar()
                assert count==0,f'Istnieje {count} lotniskowców — wycofanie przerwane.'
                c.execute(text('ALTER TABLE game_military_vessels DROP CHECK ck_vessel_kind'))
                c.execute(text("ALTER TABLE game_military_vessels ADD CONSTRAINT ck_vessel_kind CHECK (kind IN ('warships','submarines'))"))
                if 'air_base_id' in columns:
                    c.execute(text('ALTER TABLE game_military_vessels DROP FOREIGN KEY fk_vessel_air_base'))
                    c.execute(text('ALTER TABLE game_military_vessels DROP COLUMN air_base_id'))
                if 'fighters' in columns:c.execute(text('ALTER TABLE game_military_vessels DROP COLUMN fighters'))
                print('Wycofano.')
            else:
                if 'fighters' not in columns:c.execute(text('ALTER TABLE game_military_vessels ADD COLUMN fighters INT NOT NULL DEFAULT 0'))
                if 'air_base_id' not in columns:
                    c.execute(text('ALTER TABLE game_military_vessels ADD COLUMN air_base_id INT NULL'))
                    c.execute(text('ALTER TABLE game_military_vessels ADD CONSTRAINT fk_vessel_air_base FOREIGN KEY (air_base_id) REFERENCES game_military_bases (id) ON DELETE SET NULL'))
                c.execute(text('ALTER TABLE game_military_vessels DROP CHECK ck_vessel_kind'))
                c.execute(text("ALTER TABLE game_military_vessels ADD CONSTRAINT ck_vessel_kind CHECK (kind IN ('warships','submarines','carriers'))"))
                print('Dodano lotniskowce (fighters, air_base_id, rodzaj carriers).')
