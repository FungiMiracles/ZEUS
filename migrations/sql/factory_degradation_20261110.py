"""Factory environmental degradation, waste filters and budget sectors of industry movements (UAT only).

    venv/bin/python migrations/sql/factory_degradation_20261110.py            # backup + migrate (+ retroactive degradation)
    venv/bin/python migrations/sql/factory_degradation_20261110.py --rollback # subtract the added points, drop the columns

Adds game_ammunition_factories.waste_filter, game_ammunition_factories.degradation_points and
game_industry_movements.sector (server defaults; existing movements stay charged to 'infrastructure', including the
pollution filters installed before 10 Nov 2026 under the previous rule).
Retroactive rule approved by the administrator (10 Nov 2026): every active factory without a waste filter receives
2 points and its region's environmental degradation grows by 2 per such factory (capped at 100; missing data = 0).
The retroactive step runs only in the run that adds degradation_points, so a second run does not add it twice.
Does NOT touch PROD, the AI switch or any other data.
"""
from pathlib import Path
from datetime import datetime,timezone
from collections import Counter
import sys,json,argparse
from sqlalchemy import inspect,text
from sqlalchemy.engine import make_url

ROOT=Path(__file__).resolve().parents[2]
FACTORIES='game_ammunition_factories'
MOVEMENTS='game_industry_movements'
COLUMNS={FACTORIES:[('waste_filter','TINYINT(1) NOT NULL DEFAULT 0'),('degradation_points','INT NOT NULL DEFAULT 0')],
         MOVEMENTS:[('sector',"VARCHAR(32) NOT NULL DEFAULT 'infrastructure'")]}
POINTS=2
FIELD='region_degradacja_srodowiska'


def make_app():
    assert ROOT==Path('/home/oskar_zeus_admin/ZEUS_UAT');sys.path.insert(0,str(ROOT))
    from flask import Flask
    from extensions import db
    settings=dict(line.split('=',1) for line in (ROOT/'.env.uat').read_text().splitlines() if line and not line.startswith('#') and '=' in line)
    url=settings['DATABASE_URL'].strip().strip('"\'');assert make_url(url).database=='entenda_uat_db','Migracja wyłącznie dla bazy UAT.'
    app=Flask('factory-degradation-migration',root_path=str(ROOT));app.config.update(SQLALCHEMY_DATABASE_URI=url,SQLALCHEMY_ENGINE_OPTIONS={'hide_parameters':True},ENV_NAME='UAT')
    db.init_app(app);return app


def backup(connection,label):
    data={FACTORIES:[dict(row) for row in connection.execute(text(f'SELECT * FROM `{FACTORIES}`')).mappings()],
          MOVEMENTS:[dict(row) for row in connection.execute(text(f'SELECT id,panstwo_id,budget_id,amount,request_id FROM `{MOVEMENTS}`')).mappings()],
          'regiony':[dict(row) for row in connection.execute(text(f'SELECT region_id,{FIELD} FROM regiony')).mappings()]}
    target=ROOT/'backups'/f'factory_degradation_{label}_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json'
    target.parent.mkdir(exist_ok=True);target.write_text(json.dumps(data,ensure_ascii=False,default=str,indent=1))
    return target,{name:len(rows) for name,rows in data.items()}


def change_regions(connection,deltas):
    for region_id,delta in sorted(deltas.items()):
        old=connection.execute(text(f'SELECT {FIELD} FROM regiony WHERE region_id=:id FOR UPDATE'),{'id':region_id}).scalar()
        new=max(0,min(100,int(old or 0)+delta))
        connection.execute(text(f'UPDATE regiony SET {FIELD}=:v WHERE region_id=:id'),{'v':new,'id':region_id})
        print(f'Region {region_id}: degradacja środowiska {old} → {new}')


def migrate():
    app=make_app()
    from extensions import db
    with app.app_context():
        engine=db.engine
        with engine.begin() as connection:target,counts=backup(connection,'before')
        print('Kopia zapasowa:',target,counts)
        inspector=inspect(engine);added=set()
        with engine.begin() as connection:
            for table,columns in COLUMNS.items():
                existing={column['name'] for column in inspector.get_columns(table)}
                for name,ddl in columns:
                    if name not in existing:
                        connection.execute(text(f'ALTER TABLE `{table}` ADD COLUMN `{name}` {ddl}'));added.add(name);print('Dodano kolumnę',table+'.'+name)
        if 'degradation_points' not in added:
            print('Kolumna degradation_points już istniała — pomijam naliczenie wsteczne (zapobiega podwójnemu naliczeniu).');return
        with engine.begin() as connection:
            factories=connection.execute(text(f'SELECT id,region_id FROM `{FACTORIES}` WHERE removed_at IS NULL AND waste_filter=0 FOR UPDATE')).all()
            for factory_id,_ in factories:connection.execute(text(f'UPDATE `{FACTORIES}` SET degradation_points=:p WHERE id=:id'),{'p':POINTS,'id':factory_id})
            change_regions(connection,{region:count*POINTS for region,count in Counter(region for _,region in factories).items()})
        print(f'Naliczono wstecz: {len(factories)} fabryk × {POINTS} pkt degradacji środowiska.')


def rollback():
    app=make_app()
    from extensions import db
    with app.app_context():
        engine=db.engine;inspector=inspect(engine)
        with engine.begin() as connection:target,counts=backup(connection,'before_rollback')
        print('Kopia zapasowa przed wycofaniem:',target,counts)
        with engine.begin() as connection:
            existing={table:{column['name'] for column in inspector.get_columns(table)} for table in COLUMNS}
            if 'degradation_points' in existing[FACTORIES]:
                rows=connection.execute(text(f'SELECT region_id,SUM(degradation_points) FROM `{FACTORIES}` WHERE removed_at IS NULL AND degradation_points>0 GROUP BY region_id')).all()
                change_regions(connection,{region:-int(total) for region,total in rows})
            for table,columns in COLUMNS.items():
                for name,_ in columns:
                    if name in existing[table]:connection.execute(text(f'ALTER TABLE `{table}` DROP COLUMN `{name}`'));print('Usunięto kolumnę',table+'.'+name)
        print('Wycofano degradację fabryk i sektory ruchów przemysłowych.')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--rollback',action='store_true');args=parser.parse_args()
    rollback() if args.rollback else migrate()
