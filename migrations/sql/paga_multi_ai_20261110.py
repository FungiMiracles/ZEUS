"""PAGA MULTI-AI (Gemini, Groq, local Qwen) — additive schema for UAT only.

    venv/bin/python migrations/sql/paga_multi_ai_20261110.py            # backup + migrate
    venv/bin/python migrations/sql/paga_multi_ai_20261110.py --rollback # drop the added columns and table

Adds game_paga_ai_jobs.provider, game_paga_ai_metrics.{provider,model_name,started_at,finished_at,validation}
and the table game_paga_ai_providers (provider pauses after limits/outages; no keys or secrets are stored).
Existing rows keep NULL provider (historical calls were made by the local Qwen). Does NOT touch PROD, the global
AI switch, task statuses or any game data. No API key is read or written by this script.
"""
from pathlib import Path
from datetime import datetime,timezone
import sys,json,argparse
from sqlalchemy import inspect,text
from sqlalchemy.engine import make_url

ROOT=Path(__file__).resolve().parents[2]
COLUMNS={'game_paga_ai_jobs':[('provider','VARCHAR(16) NULL')],
         'game_paga_ai_metrics':[('provider','VARCHAR(16) NULL'),('model_name','VARCHAR(100) NULL'),('started_at','DATETIME NULL'),('finished_at','DATETIME NULL'),('validation','VARCHAR(24) NULL')]}
INDEXES=[('game_paga_ai_jobs','ix_game_paga_ai_jobs_provider','provider'),('game_paga_ai_metrics','ix_game_paga_ai_metrics_provider','provider')]
TABLE='game_paga_ai_providers'


def make_app():
    assert ROOT==Path('/home/oskar_zeus_admin/ZEUS_UAT');sys.path.insert(0,str(ROOT))
    from flask import Flask
    from extensions import db
    settings=dict(line.split('=',1) for line in (ROOT/'.env.uat').read_text().splitlines() if line and not line.startswith('#') and '=' in line)
    url=settings['DATABASE_URL'].strip().strip('"\'');assert make_url(url).database=='entenda_uat_db','Migracja wyłącznie dla bazy UAT.'
    app=Flask('paga-multi-ai-migration',root_path=str(ROOT));app.config.update(SQLALCHEMY_DATABASE_URI=url,SQLALCHEMY_ENGINE_OPTIONS={'hide_parameters':True},ENV_NAME='UAT')
    db.init_app(app);return app


def backup(connection,label):
    data={'columns':{table:[column['name'] for column in inspect(connection).get_columns(table)] for table in COLUMNS},
          'counts':{table:connection.execute(text(f'SELECT COUNT(*) FROM `{table}`')).scalar() for table in COLUMNS}}
    if inspect(connection).has_table(TABLE):data[TABLE]=[dict(row) for row in connection.execute(text(f'SELECT * FROM `{TABLE}`')).mappings()]
    target=ROOT/'backups'/f'paga_multi_ai_{label}_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json'
    target.parent.mkdir(exist_ok=True);target.write_text(json.dumps(data,ensure_ascii=False,default=str,indent=1))
    return target


def migrate():
    app=make_app()
    from extensions import db
    with app.app_context():
        engine=db.engine
        with engine.begin() as connection:print('Kopia zapasowa (schemat i liczności):',backup(connection,'before'))
        with engine.begin() as connection:
            inspector=inspect(connection)
            for table,columns in COLUMNS.items():
                existing={column['name'] for column in inspector.get_columns(table)}
                for name,ddl in columns:
                    if name not in existing:connection.execute(text(f'ALTER TABLE `{table}` ADD COLUMN `{name}` {ddl}'));print('Dodano kolumnę',table+'.'+name)
            for table,index,column in INDEXES:
                if index not in {item['name'] for item in inspect(connection).get_indexes(table)}:
                    connection.execute(text(f'CREATE INDEX `{index}` ON `{table}` (`{column}`)'));print('Dodano indeks',index)
            if not inspector.has_table(TABLE):
                connection.execute(text(f'CREATE TABLE `{TABLE}` (`provider` VARCHAR(16) NOT NULL PRIMARY KEY, `cooldown_until` DATETIME NULL, '
                                        '`last_error` VARCHAR(300) NULL, `updated_at` DATETIME NOT NULL) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4'))
                print('Utworzono tabelę',TABLE)
        print('Migracja PAGA MULTI-AI zakończona.')


def rollback():
    app=make_app()
    from extensions import db
    with app.app_context():
        engine=db.engine
        with engine.begin() as connection:print('Kopia zapasowa przed wycofaniem:',backup(connection,'before_rollback'))
        with engine.begin() as connection:
            inspector=inspect(connection)
            if inspector.has_table(TABLE):connection.execute(text(f'DROP TABLE `{TABLE}`'));print('Usunięto tabelę',TABLE)
            for table,index,_ in INDEXES:
                if index in {item['name'] for item in inspector.get_indexes(table)}:connection.execute(text(f'DROP INDEX `{index}` ON `{table}`'))
            for table,columns in COLUMNS.items():
                existing={column['name'] for column in inspect(connection).get_columns(table)}
                for name,_ in columns:
                    if name in existing:connection.execute(text(f'ALTER TABLE `{table}` DROP COLUMN `{name}`'));print('Usunięto kolumnę',table+'.'+name)
        print('Wycofano schemat PAGA MULTI-AI.')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--rollback',action='store_true');args=parser.parse_args()
    rollback() if args.rollback else migrate()
