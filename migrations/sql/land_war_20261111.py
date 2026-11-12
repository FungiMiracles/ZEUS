"""Wojska lądowe (UAT only): poziomy wyszkolenia w WIKI, armie lądowe, okupacje.

    venv/bin/python migrations/sql/land_war_20261111.py            # backup + migrate
    venv/bin/python migrations/sql/land_war_20261111.py --rollback # drop the new tables and columns (only while they are empty)

Adds wojsko.wyszkolenie_ladowe / wyszkolenie_morskie / wyszkolenie_powietrzne (INT NOT NULL DEFAULT 100 — existing
countries get 100 = multiplier ×1) and creates game_land_armies and game_occupations. No other data is changed.
"""
from pathlib import Path
from datetime import datetime,timezone
import sys,json,argparse
from sqlalchemy import inspect,text
from sqlalchemy.engine import make_url

ROOT=Path(__file__).resolve().parents[2]
ARMY_TABLE='wojsko'
COLUMNS=['wyszkolenie_ladowe','wyszkolenie_morskie','wyszkolenie_powietrzne']


def make_app():
    assert ROOT==Path('/home/oskar_zeus_admin/ZEUS_UAT');sys.path.insert(0,str(ROOT))
    from flask import Flask
    from extensions import db
    settings=dict(line.split('=',1) for line in (ROOT/'.env.uat').read_text().splitlines() if line and not line.startswith('#') and '=' in line)
    url=settings['DATABASE_URL'].strip().strip('"\'');assert make_url(url).database=='entenda_uat_db','Migracja wyłącznie dla bazy UAT.'
    app=Flask('land-war-migration',root_path=str(ROOT));app.config.update(SQLALCHEMY_DATABASE_URI=url,SQLALCHEMY_ENGINE_OPTIONS={'hide_parameters':True},ENV_NAME='UAT')
    db.init_app(app);return app


def migrate():
    app=make_app()
    from extensions import db
    import models  # noqa: F401  (referenced tables)
    import game.finance_models,game.military_models  # noqa: F401
    from game.land_war_models import LandArmy,Occupation
    with app.app_context():
        engine=db.engine
        with engine.begin() as connection:
            data=[dict(row) for row in connection.execute(text(f'SELECT panstwo_id FROM `{ARMY_TABLE}`')).mappings()]
            target=ROOT/'backups'/f'land_war_before_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json'
            target.write_text(json.dumps({'wojsko_rows':len(data),'columns':[c['name'] for c in inspect(connection).get_columns(ARMY_TABLE)]},ensure_ascii=False,indent=1))
            print('Kopia zapasowa (schemat):',target)
            existing={c['name'] for c in inspect(connection).get_columns(ARMY_TABLE)}
            for name in COLUMNS:
                if name not in existing:
                    connection.execute(text(f'ALTER TABLE `{ARMY_TABLE}` ADD COLUMN `{name}` INT NOT NULL DEFAULT 100'));print('Dodano kolumnę',ARMY_TABLE+'.'+name)
        for model in (LandArmy,Occupation):
            if not inspect(engine).has_table(model.__tablename__):model.__table__.create(engine);print('Utworzono tabelę',model.__tablename__)
        print('Migracja wojsk lądowych zakończona.')


def rollback():
    app=make_app()
    from extensions import db
    with app.app_context(),db.engine.begin() as connection:
        for table in ('game_occupations','game_land_armies'):
            if inspect(connection).has_table(table):
                count=connection.execute(text(f'SELECT COUNT(*) FROM `{table}`')).scalar()
                assert count==0,f'Tabela {table} zawiera {count} wierszy — wycofanie przerwane (najpierw wykonaj kopię danych).'
                connection.execute(text(f'DROP TABLE `{table}`'));print('Usunięto tabelę',table)
        existing={c['name'] for c in inspect(connection).get_columns(ARMY_TABLE)}
        for name in COLUMNS:
            if name in existing:connection.execute(text(f'ALTER TABLE `{ARMY_TABLE}` DROP COLUMN `{name}`'));print('Usunięto kolumnę',ARMY_TABLE+'.'+name)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--rollback',action='store_true');args=parser.parse_args()
    rollback() if args.rollback else migrate()
