"""Samouczek gry (UAT only, 15 Nov 2026): tabela game_user_tutorials (użytkownik + klucz komunikatu).

    venv/bin/python migrations/sql/game_tutorial_20261115.py            # utworzenie tabeli (idempotentne)
    venv/bin/python migrations/sql/game_tutorial_20261115.py --rollback # usunięcie tabeli

Zmiana addytywna. Tabela startuje pusta: brak wpisu = gracz nie widział komunikatu, więc istniejący gracze
zobaczą powitanie i komunikaty sekcji przy najbliższym wejściu (wymaganie). Bez tabeli gra działa, tylko bez samouczka.
Tabela z pierwszej wersji (tylko user_id) dostaje kolumnę tutorial (dotychczasowe wpisy = 'main') i klucz (user_id, tutorial).
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
    app = Flask('game-tutorial-migration', root_path=str(ROOT))
    app.config.update(SQLALCHEMY_DATABASE_URI=url, SQLALCHEMY_ENGINE_OPTIONS={'hide_parameters': True}, ENV_NAME='UAT')
    db.init_app(app); return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--rollback', action='store_true'); args = parser.parse_args()
    app = make_app()
    from extensions import db
    import models, game.models  # noqa: F401
    from game.tutorial import GameUserTutorial
    with app.app_context():
        assert db.session.execute(text('SELECT DATABASE()')).scalar() == 'entenda_uat_db'
        if args.rollback:
            with db.engine.begin() as connection:connection.execute(text('DROP TABLE IF EXISTS game_user_tutorials'))
            print('Usunięto game_user_tutorials.')
        elif inspect(db.engine).has_table(GameUserTutorial.__tablename__):
            columns = {column['name'] for column in inspect(db.engine).get_columns(GameUserTutorial.__tablename__)}
            if 'tutorial' in columns:
                print('Tabela game_user_tutorials już istnieje.')
            else:
                with db.engine.begin() as connection:
                    connection.execute(text("ALTER TABLE game_user_tutorials ADD COLUMN tutorial VARCHAR(32) NOT NULL DEFAULT 'main', "
                                            "DROP PRIMARY KEY, ADD PRIMARY KEY (user_id, tutorial)"))
                print('Dodano kolumnę tutorial i klucz (user_id, tutorial).')
        else:
            GameUserTutorial.__table__.create(db.engine)
            print('Utworzono game_user_tutorials.')
