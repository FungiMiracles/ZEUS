"""PAGA2 — fundament (UAT only): tabele konfiguracji, profili, historii decyzji i losowań.

Tworzy wiersz game_paga2_control (id=1, PAGA2 WYŁĄCZONE) i przenosi zatwierdzone konfiguracje PAGA
do profili PAGA2 (source='migrated': siedem wspólnych cech, interesy -> charakter i priorytety, ta sama flaga autonomii).

    venv/bin/python migrations/sql/paga2_foundation_20261111.py            # zmiany addytywne
    venv/bin/python migrations/sql/paga2_foundation_20261111.py --rollback # usunięcie tabel (tylko bez decyzji i losowań)
"""
from pathlib import Path
import sys,argparse
from sqlalchemy import inspect,text,select
from sqlalchemy.engine import make_url

ROOT=Path(__file__).resolve().parents[2]
TABLES=('game_paga2_random_draws','game_paga2_decisions','game_paga2_profile_revisions','game_paga2_profiles','game_paga2_control')


def make_app():
    assert ROOT==Path('/home/oskar_zeus_admin/ZEUS_UAT');sys.path.insert(0,str(ROOT))
    from flask import Flask
    from extensions import db
    settings=dict(line.split('=',1) for line in (ROOT/'.env.uat').read_text().splitlines() if line and not line.startswith('#') and '=' in line)
    url=settings['DATABASE_URL'].strip().strip('"\'');assert make_url(url).database=='entenda_uat_db','Migracja wyłącznie dla bazy UAT.'
    app=Flask('paga2-migration',root_path=str(ROOT));app.config.update(SQLALCHEMY_DATABASE_URI=url,SQLALCHEMY_ENGINE_OPTIONS={'hide_parameters':True},ENV_NAME='UAT')
    db.init_app(app);return app


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--rollback',action='store_true');args=parser.parse_args()
    app=make_app()
    from extensions import db
    import models,game.finance_models  # noqa: F401
    from game.paga import PagaConfiguration
    from game.paga2.models import Paga2Control,Paga2Profile,Paga2ProfileRevision,Paga2Decision,Paga2RandomDraw,migrated_profile,utc_now
    with app.app_context():
        inspector=inspect(db.engine)
        if args.rollback:
            with db.engine.begin() as connection:
                for table in ('game_paga2_decisions','game_paga2_random_draws'):
                    if inspector.has_table(table):
                        count=connection.execute(text(f'SELECT COUNT(*) FROM {table}')).scalar()
                        assert count==0,f'{table} zawiera {count} wierszy — wycofanie przerwane.'
                for table in TABLES:connection.execute(text(f'DROP TABLE IF EXISTS {table}'))
            print('Usunięto tabele PAGA2.')
        else:
            for model in (Paga2Control,Paga2Profile,Paga2ProfileRevision,Paga2Decision,Paga2RandomDraw):
                if not inspector.has_table(model.__tablename__):model.__table__.create(db.engine);print('Utworzono',model.__tablename__)
            with db.session.begin():
                if db.session.get(Paga2Control,1) is None:
                    db.session.add(Paga2Control(id=1,enabled=False,interval_minutes=60,revision=0,updated_at=utc_now(),actor='migracja'));print('Utworzono konfigurację PAGA2 (wyłączona).')
                moved=0
                for config in db.session.scalars(select(PagaConfiguration).where(PagaConfiguration.approved_at.is_not(None))):
                    if db.session.get(Paga2Profile,config.panstwo_id) is not None:continue
                    data=migrated_profile(config);now=utc_now()
                    db.session.add(Paga2Profile(panstwo_id=config.panstwo_id,categories=data['categories'],priorities=data['priorities'],traits=data['traits'],
                                                autonomy_enabled=data['autonomy_enabled'],source='migrated',revision=1,updated_at=now,actor='migracja'))
                    db.session.add(Paga2ProfileRevision(panstwo_id=config.panstwo_id,revision=1,configuration={**data,'source':'migrated'},actor='migracja',created_at=now))
                    moved+=1
                print('Przeniesiono profile PAGA:',moved)
            print('Gotowe.')
