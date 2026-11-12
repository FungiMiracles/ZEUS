"""Radary (UAT only): tabele game_radars, game_radar_expenses, game_radar_detections,
kolumna game_military_flights.target_radar_id i rodzaj 'radar' w ck_missile_defense_kind.

    venv/bin/python migrations/sql/radar_20261111.py            # zmiany addytywne
    venv/bin/python migrations/sql/radar_20261111.py --rollback # wycofanie (tylko gdy nie ma radarów)
"""
from pathlib import Path
import sys,argparse
from sqlalchemy import inspect,text
from sqlalchemy.engine import make_url

ROOT=Path(__file__).resolve().parents[2]
OLD_KINDS="'region','city','base','mine','factory','power'"
NEW_KINDS=OLD_KINDS+",'radar'"


def make_app():
    assert ROOT==Path('/home/oskar_zeus_admin/ZEUS_UAT');sys.path.insert(0,str(ROOT))
    from flask import Flask
    from extensions import db
    settings=dict(line.split('=',1) for line in (ROOT/'.env.uat').read_text().splitlines() if line and not line.startswith('#') and '=' in line)
    url=settings['DATABASE_URL'].strip().strip('"\'');assert make_url(url).database=='entenda_uat_db','Migracja wyłącznie dla bazy UAT.'
    app=Flask('radar-migration',root_path=str(ROOT));app.config.update(SQLALCHEMY_DATABASE_URI=url,SQLALCHEMY_ENGINE_OPTIONS={'hide_parameters':True},ENV_NAME='UAT')
    db.init_app(app);return app


def kinds_constraint(connection,kinds):
    connection.execute(text('ALTER TABLE game_missile_defenses DROP CHECK ck_missile_defense_kind'))
    connection.execute(text(f'ALTER TABLE game_missile_defenses ADD CONSTRAINT ck_missile_defense_kind CHECK (target_kind IN ({kinds}))'))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--rollback',action='store_true');args=parser.parse_args()
    app=make_app()
    from extensions import db
    import models,game.finance_models,game.military_models  # noqa: F401
    from game.radar_models import Radar,RadarExpense,RadarDetection
    with app.app_context():
        inspector=inspect(db.engine)
        columns={column['name'] for column in inspector.get_columns('game_military_flights')}
        if args.rollback:
            with db.engine.begin() as connection:
                if inspector.has_table('game_radars'):
                    count=connection.execute(text('SELECT COUNT(*) FROM game_radars')).scalar()
                    assert count==0,f'Istnieje {count} radarów — wycofanie przerwane.'
                assert connection.execute(text("SELECT COUNT(*) FROM game_missile_defenses WHERE target_kind='radar'")).scalar()==0
                if 'target_radar_id' in columns:
                    connection.execute(text('ALTER TABLE game_military_flights DROP FOREIGN KEY fk_flight_target_radar'))
                    connection.execute(text('ALTER TABLE game_military_flights DROP COLUMN target_radar_id'))
                kinds_constraint(connection,OLD_KINDS)
                for table in ('game_radar_detections','game_radar_expenses','game_radars'):connection.execute(text(f'DROP TABLE IF EXISTS {table}'))
            print('Wycofano zmiany radarów.')
        else:
            for model in (Radar,RadarExpense):
                if not inspector.has_table(model.__tablename__):model.__table__.create(db.engine);print('Utworzono',model.__tablename__)
            with db.engine.begin() as connection:
                if 'target_radar_id' not in columns:
                    connection.execute(text('ALTER TABLE game_military_flights ADD COLUMN target_radar_id INT NULL, ADD INDEX ix_flight_target_radar (target_radar_id), '
                                            'ADD CONSTRAINT fk_flight_target_radar FOREIGN KEY (target_radar_id) REFERENCES game_radars(id) ON DELETE SET NULL'))
                    print('Dodano game_military_flights.target_radar_id')
                clause=connection.execute(text("SELECT CHECK_CLAUSE FROM information_schema.CHECK_CONSTRAINTS WHERE CONSTRAINT_SCHEMA=DATABASE() AND CONSTRAINT_NAME='ck_missile_defense_kind'")).scalar() or ''
                if 'radar' not in clause:kinds_constraint(connection,NEW_KINDS);print("Dodano rodzaj 'radar' do obrony przeciwrakietowej")
            if not inspect(db.engine).has_table(RadarDetection.__tablename__):RadarDetection.__table__.create(db.engine);print('Utworzono game_radar_detections')
            print('Gotowe.')
