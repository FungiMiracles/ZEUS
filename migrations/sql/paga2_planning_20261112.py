"""PAGA2 — planowanie wieloetapowe (UAT only): tabela game_paga2_plans.

    venv/bin/python migrations/sql/paga2_planning_20261112.py            # utworzenie tabeli
    venv/bin/python migrations/sql/paga2_planning_20261112.py --rollback # usunięcie (tylko gdy pusta)
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
    import models,game.finance_models  # noqa: F401
    from game.paga2.models import Paga2Plan
    with app.app_context():
        exists=inspect(db.engine).has_table(Paga2Plan.__tablename__)
        if args.rollback:
            if exists:
                with db.engine.begin() as connection:
                    count=connection.execute(text('SELECT COUNT(*) FROM game_paga2_plans')).scalar()
                    assert count==0,f'Tabela zawiera {count} planów — wycofanie przerwane.'
                    connection.execute(text('DROP TABLE game_paga2_plans'))
            print('Usunięto game_paga2_plans.')
        elif not exists:Paga2Plan.__table__.create(db.engine);print('Utworzono game_paga2_plans.')
        else:print('Tabela game_paga2_plans już istnieje.')
