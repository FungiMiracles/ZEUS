"""PAGA AI rebuild schema (UAT only): additive, reversible, with a JSON backup first.

    venv/bin/python migrations/sql/paga_ai_rebuild_20261110.py            # backup + migrate
    venv/bin/python migrations/sql/paga_ai_rebuild_20261110.py --rollback # drop added columns/tables

Compatible with the previous code while it still runs: new columns have server defaults, legacy statuses stay valid.
Does NOT change the global AI switch, identities, game data or PROD.
"""
from pathlib import Path
from datetime import datetime,timezone
import sys,json,argparse
from sqlalchemy import inspect,text,select,func
from sqlalchemy.engine import make_url

ROOT=Path(__file__).resolve().parents[2]

COLUMNS={
    'game_paga_ai_control':[('review_interval_minutes','INT NOT NULL DEFAULT 180'),('max_model_calls','INT NOT NULL DEFAULT 3')],
    'game_paga_ai_identities':[('notification_cursor','INT NOT NULL DEFAULT 0'),('last_review_at','DATETIME NULL'),('last_probe_at','DATETIME NULL'),('strategy','JSON NULL')],
    'game_paga_ai_jobs':[('kind',"VARCHAR(40) NOT NULL DEFAULT 'legacy'"),('source',"VARCHAR(40) NOT NULL DEFAULT 'legacy'"),('object_ref','VARCHAR(100) NULL'),
                         ('context','JSON NULL'),('journal','JSON NULL'),('result','JSON NULL'),('attempts','INT NOT NULL DEFAULT 0'),('model_calls','INT NOT NULL DEFAULT 0'),
                         ('retries','INT NOT NULL DEFAULT 0'),('duration_ms','INT NULL'),('not_before','DATETIME NULL'),('expires_at','DATETIME NULL'),('goal_id','INT NULL')],
}
INDEXES=[('game_paga_ai_jobs','ix_game_paga_ai_jobs_kind','kind'),('game_paga_ai_jobs','ix_game_paga_ai_jobs_goal_id','goal_id')]
BACKUP_TABLES=['game_paga_ai_control','game_paga_ai_identities','game_paga_ai_jobs','game_paga_ai_logs']


def make_app():
    assert ROOT==Path('/home/oskar_zeus_admin/ZEUS_UAT');sys.path.insert(0,str(ROOT))
    from flask import Flask
    from extensions import db
    import models,game.models
    settings=dict(line.split('=',1) for line in (ROOT/'.env.uat').read_text().splitlines() if line and not line.startswith('#') and '=' in line)
    url=settings['DATABASE_URL'].strip().strip('"\'');assert make_url(url).database=='entenda_uat_db','Migracja wyłącznie dla bazy UAT.'
    app=Flask('paga-ai-rebuild-migration',root_path=str(ROOT));app.config.update(SQLALCHEMY_DATABASE_URI=url,SQLALCHEMY_ENGINE_OPTIONS={'hide_parameters':True},ENV_NAME='UAT')
    db.init_app(app);return app


def backup(connection):
    data={}
    for table in BACKUP_TABLES:
        data[table]=[dict(row) for row in connection.execute(text(f'SELECT * FROM `{table}`')).mappings()]
    target=ROOT/'backups'/f'paga_ai_before_rebuild_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json'
    target.parent.mkdir(exist_ok=True);target.write_text(json.dumps(data,ensure_ascii=False,default=str,indent=1))
    return target,{table:len(rows) for table,rows in data.items()}


def migrate():
    app=make_app()
    from extensions import db
    from game.paga_ai_models import PagaAiWrite,PagaAiGoal,PagaAiPlan,PagaAiMetric,PagaAiIdentity
    from game.forum_models import GameNotification
    with app.app_context():
        engine=db.engine
        with engine.begin() as connection:target,counts=backup(connection)
        print('Kopia zapasowa:',target,counts)
        inspector=inspect(engine)
        with engine.begin() as connection:
            for table,columns in COLUMNS.items():
                existing={column['name'] for column in inspector.get_columns(table)}
                for name,ddl in columns:
                    if name not in existing:connection.execute(text(f'ALTER TABLE `{table}` ADD COLUMN `{name}` {ddl}'));print('Dodano kolumnę',table+'.'+name)
            indexes={index['name'] for index in inspector.get_indexes('game_paga_ai_jobs')}
            for table,name,column in INDEXES:
                if name not in indexes:connection.execute(text(f'CREATE INDEX `{name}` ON `{table}` (`{column}`)'));print('Dodano indeks',name)
        for model in (PagaAiWrite,PagaAiGoal,PagaAiPlan,PagaAiMetric):
            model.__table__.create(engine,checkfirst=True)
        # Start each AI inbox at "now": historical notifications are not new situations.
        with engine.begin() as connection:
            for identity_country,user_id,cursor in connection.execute(select(PagaAiIdentity.country_id,PagaAiIdentity.user_id,PagaAiIdentity.notification_cursor)):
                latest=connection.scalar(select(func.max(GameNotification.id)).where(GameNotification.user_id==user_id)) or 0
                if cursor<latest:connection.execute(text('UPDATE game_paga_ai_identities SET notification_cursor=:c WHERE country_id=:id'),{'c':latest,'id':identity_country})
            enabled,revision=connection.execute(text('SELECT enabled,revision FROM game_paga_ai_control WHERE id=1')).one()
        print('Schemat PAGA AI gotowy. Globalne AI:', 'WŁĄCZONE' if enabled else 'WYŁĄCZONE','rewizja',revision,'(bez zmian).')


def rollback():
    app=make_app()
    from extensions import db
    with app.app_context():
        engine=db.engine
        with engine.begin() as connection:target,counts=backup(connection)
        print('Kopia zapasowa przed wycofaniem:',target,counts)
        inspector=inspect(engine)
        with engine.begin() as connection:
            for table in ('game_paga_ai_writes','game_paga_ai_goals','game_paga_ai_plans','game_paga_ai_metrics'):
                connection.execute(text(f'DROP TABLE IF EXISTS `{table}`'))
            indexes={index['name'] for index in inspector.get_indexes('game_paga_ai_jobs')}
            for table,name,_ in INDEXES:
                if name in indexes:connection.execute(text(f'DROP INDEX `{name}` ON `{table}`'))
            for table,columns in COLUMNS.items():
                existing={column['name'] for column in inspector.get_columns(table)}
                for name,_ in columns:
                    if name in existing:connection.execute(text(f'ALTER TABLE `{table}` DROP COLUMN `{name}`'))
        print('Wycofano schemat przebudowy PAGA AI.')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--rollback',action='store_true');args=parser.parse_args()
    rollback() if args.rollback else migrate()
