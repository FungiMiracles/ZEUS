"""Utrata suwerenności po aneksji stolicy (UAT only): tabela game_sovereignty_losses.

    venv/bin/python migrations/sql/sovereignty_20261111.py            # create the table
    venv/bin/python migrations/sql/sovereignty_20261111.py --rollback # drop it (only while empty)
"""
from pathlib import Path
import sys,argparse
from sqlalchemy import inspect,text
from sqlalchemy.engine import make_url

ROOT=Path(__file__).resolve().parents[2]


def make_app():
    assert ROOT==Path('/home/oskar_zeus_admin/ZEUS_UAT');sys.path.insert(0,str(ROOT))
    from flask import Flask
    from extensions import db
    settings=dict(line.split('=',1) for line in (ROOT/'.env.uat').read_text().splitlines() if line and not line.startswith('#') and '=' in line)
    url=settings['DATABASE_URL'].strip().strip('"\'');assert make_url(url).database=='entenda_uat_db','Migracja wyłącznie dla bazy UAT.'
    app=Flask('sovereignty-migration',root_path=str(ROOT));app.config.update(SQLALCHEMY_DATABASE_URI=url,SQLALCHEMY_ENGINE_OPTIONS={'hide_parameters':True},ENV_NAME='UAT')
    db.init_app(app);return app


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--rollback',action='store_true');args=parser.parse_args()
    app=make_app()
    from extensions import db
    import models,game.finance_models,game.land_war_models  # noqa: F401
    from game.land_war_models import SovereigntyLoss
    with app.app_context():
        exists=inspect(db.engine).has_table(SovereigntyLoss.__tablename__)
        if args.rollback:
            if exists:
                with db.engine.begin() as connection:
                    count=connection.execute(text('SELECT COUNT(*) FROM game_sovereignty_losses')).scalar()
                    assert count==0,f'Tabela zawiera {count} wierszy — wycofanie przerwane.'
                    connection.execute(text('DROP TABLE game_sovereignty_losses'))
                print('Usunięto tabelę game_sovereignty_losses.')
        elif not exists:SovereigntyLoss.__table__.create(db.engine);print('Utworzono tabelę game_sovereignty_losses.')
        else:print('Tabela game_sovereignty_losses już istnieje.')
