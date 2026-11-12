"""Coal power plant air pollution and pollution filters (UAT only): additive, reversible, with a JSON backup first.

    venv/bin/python migrations/sql/power_plant_pollution_20261110.py            # backup + migrate (+ retroactive pollution)
    venv/bin/python migrations/sql/power_plant_pollution_20261110.py --rollback # subtract the added points, drop the columns

Adds game_power_plants.air_filter and game_power_plants.pollution_points (server defaults, compatible with the code
still running). Retroactive rule approved by the administrator (10 Nov 2026): every active coal plant without a filter
receives 2 points and its region's air pollution grows by 2 per such plant (capped at 100; missing data counts as 0).
The retroactive step runs only in the run that adds the columns, so a second run does not add pollution twice.
Does NOT touch PROD, the AI switch or any other data.
"""
from pathlib import Path
from datetime import datetime,timezone
from collections import Counter
import sys,json,argparse
from sqlalchemy import inspect,text
from sqlalchemy.engine import make_url

ROOT=Path(__file__).resolve().parents[2]
TABLE='game_power_plants'
COLUMNS=[('air_filter','TINYINT(1) NOT NULL DEFAULT 0'),('pollution_points','INT NOT NULL DEFAULT 0')]
POINTS=2


def make_app():
    assert ROOT==Path('/home/oskar_zeus_admin/ZEUS_UAT');sys.path.insert(0,str(ROOT))
    from flask import Flask
    from extensions import db
    settings=dict(line.split('=',1) for line in (ROOT/'.env.uat').read_text().splitlines() if line and not line.startswith('#') and '=' in line)
    url=settings['DATABASE_URL'].strip().strip('"\'');assert make_url(url).database=='entenda_uat_db','Migracja wyłącznie dla bazy UAT.'
    app=Flask('power-pollution-migration',root_path=str(ROOT));app.config.update(SQLALCHEMY_DATABASE_URI=url,SQLALCHEMY_ENGINE_OPTIONS={'hide_parameters':True},ENV_NAME='UAT')
    db.init_app(app);return app


def backup(connection,label):
    data={TABLE:[dict(row) for row in connection.execute(text(f'SELECT * FROM `{TABLE}`')).mappings()],
          'regiony':[dict(row) for row in connection.execute(text('SELECT region_id,region_zanieczyszczenie_powietrza FROM regiony')).mappings()]}
    target=ROOT/'backups'/f'power_pollution_{label}_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json'
    target.parent.mkdir(exist_ok=True);target.write_text(json.dumps(data,ensure_ascii=False,default=str,indent=1))
    return target,{name:len(rows) for name,rows in data.items()}


def change_regions(connection,deltas):
    for region_id,delta in sorted(deltas.items()):
        old=connection.execute(text('SELECT region_zanieczyszczenie_powietrza FROM regiony WHERE region_id=:id FOR UPDATE'),{'id':region_id}).scalar()
        new=max(0,min(100,int(old or 0)+delta))
        connection.execute(text('UPDATE regiony SET region_zanieczyszczenie_powietrza=:v WHERE region_id=:id'),{'v':new,'id':region_id})
        print(f'Region {region_id}: zanieczyszczenie powietrza {old} → {new}')


def migrate():
    app=make_app()
    from extensions import db
    with app.app_context():
        engine=db.engine
        with engine.begin() as connection:target,counts=backup(connection,'before')
        print('Kopia zapasowa:',target,counts)
        existing={column['name'] for column in inspect(engine).get_columns(TABLE)}
        added=[name for name,_ in COLUMNS if name not in existing]
        with engine.begin() as connection:
            for name,ddl in COLUMNS:
                if name in added:connection.execute(text(f'ALTER TABLE `{TABLE}` ADD COLUMN `{name}` {ddl}'));print('Dodano kolumnę',TABLE+'.'+name)
        if 'pollution_points' not in added:
            print('Kolumny już istniały — pomijam naliczenie wsteczne (zapobiega podwójnemu naliczeniu).');return
        with engine.begin() as connection:
            plants=connection.execute(text(f"SELECT id,region_id FROM `{TABLE}` WHERE kind='coal' AND removed_at IS NULL AND air_filter=0 FOR UPDATE")).all()
            for plant_id,_ in plants:connection.execute(text(f'UPDATE `{TABLE}` SET pollution_points=:p WHERE id=:id'),{'p':POINTS,'id':plant_id})
            change_regions(connection,{region:count*POINTS for region,count in Counter(region for _,region in plants).items()})
        print(f'Naliczono wstecz: {len(plants)} elektrowni węglowych × {POINTS} pkt.')


def rollback():
    app=make_app()
    from extensions import db
    with app.app_context():
        engine=db.engine
        existing={column['name'] for column in inspect(engine).get_columns(TABLE)}
        with engine.begin() as connection:target,counts=backup(connection,'before_rollback')
        print('Kopia zapasowa przed wycofaniem:',target,counts)
        with engine.begin() as connection:
            if 'pollution_points' in existing:
                rows=connection.execute(text(f'SELECT region_id,SUM(pollution_points) FROM `{TABLE}` WHERE removed_at IS NULL AND pollution_points>0 GROUP BY region_id')).all()
                change_regions(connection,{region:-int(total) for region,total in rows})
            for name,_ in COLUMNS:
                if name in existing:connection.execute(text(f'ALTER TABLE `{TABLE}` DROP COLUMN `{name}`'));print('Usunięto kolumnę',TABLE+'.'+name)
        print('Wycofano zanieczyszczenie elektrowni (punkty aktywnych elektrowni odjęte od regionów).')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--rollback',action='store_true');args=parser.parse_args()
    rollback() if args.rollback else migrate()
