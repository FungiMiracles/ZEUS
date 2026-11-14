"""Wody terytorialne (UAT only, 15 Nov 2026): tabela game_territorial_incursions.

    venv/bin/python migrations/sql/territorial_waters_20261115.py            # utworzenie tabeli (idempotentne)
    venv/bin/python migrations/sql/territorial_waters_20261115.py --rollback # usunięcie tabeli

Zmiana addytywna: tabela zapisuje wejścia obcych okrętów w wody terytorialne (jedno powiadomienie na okręt, rejs i państwo).
Przy pierwszym uruchomieniu oznacza jako już zgłoszone wejścia z rejsów rozpoczętych przed migracją
(niezależnie od ich daty), żeby gracze nie dostali zaległych powiadomień o starych rejsach.
Z --mark-existing robi to samo na istniejącej tabeli.
"""
from pathlib import Path
import sys, argparse
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]


def make_app():
    assert ROOT == Path('/home/oskar_zeus_admin/ZEUS_UAT'); sys.path.insert(0, str(ROOT))
    from flask import Flask
    from extensions import db
    settings = dict(line.split('=', 1) for line in (ROOT/'.env.uat').read_text().splitlines() if line and not line.startswith('#') and '=' in line)
    url = settings['DATABASE_URL'].strip().strip('"\''); assert make_url(url).database == 'entenda_uat_db', 'Migracja wyłącznie dla bazy UAT.'
    app = Flask('territorial-waters-migration', root_path=str(ROOT))
    app.config.update(SQLALCHEMY_DATABASE_URI=url, SQLALCHEMY_ENGINE_OPTIONS={'hide_parameters': True}, ENV_NAME='UAT')
    db.init_app(app); return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--rollback', action='store_true'); parser.add_argument('--mark-existing', action='store_true'); args = parser.parse_args()
    app = make_app()
    from extensions import db
    import models, game.finance_models, game.military_models  # noqa: F401
    from game.territorial_waters_models import TerritorialIncursion
    with app.app_context():
        assert db.session.execute(text('SELECT DATABASE()')).scalar() == 'entenda_uat_db'
        if args.rollback:
            with db.engine.begin() as connection:
                connection.execute(text('DROP TABLE IF EXISTS game_territorial_incursions'))
            print('Usunięto game_territorial_incursions.')
        elif args.mark_existing or not inspect(db.engine).has_table(TerritorialIncursion.__tablename__):
            if not inspect(db.engine).has_table(TerritorialIncursion.__tablename__):
                TerritorialIncursion.__table__.create(db.engine)
                print('Utworzono game_territorial_incursions.')
            # Wejścia z rejsów rozpoczętych przed migracją (także datowane po bieżącym czasie gry — zegar UAT bywa cofany):
            # zapisane bez powiadomień, żeby gracze nie dostali zaległych komunikatów o starych rejsach.
            from datetime import datetime
            from unittest.mock import patch
            from sqlalchemy.orm import Session
            from game import territorial_waters, land_war
            with Session(db.engine) as session, session.begin():
                with patch.object(land_war, 'notify', lambda *args, **kwargs: None):
                    count = territorial_waters.detect_incursions(session, datetime(9000, 1, 1))
            print(f'Oznaczono {count} wcześniejszych wejść jako zgłoszone (bez powiadomień).')
        else:
            print('Tabela game_territorial_incursions już istnieje.')
