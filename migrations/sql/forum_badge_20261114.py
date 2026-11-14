"""Plakietka nowych wpisów forum zamiast powiadomień (UAT only, 14 Nov 2026).

    venv/bin/python migrations/sql/forum_badge_20261114.py

Dodaje kolumnę game_users.forum_seen_at i ustawia ją istniejącym kontom na chwilę migracji (plakietka liczy
tylko wpisy opublikowane od teraz). Oznacza jako przeczytane dotychczasowe powiadomienia FORUM_MESSAGE graczy
(nie kont PAGA, które reagują na forum na podstawie tych powiadomień). Skrypt jest idempotentny.
"""
from pathlib import Path
import sys
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]


def make_app():
    """Pełna aplikacja UAT (bez harmonogramów)."""
    import os, contextlib, io
    from unittest.mock import patch
    assert ROOT == Path('/home/oskar_zeus_admin/ZEUS_UAT'); sys.path.insert(0, str(ROOT))
    settings = dict(line.split('=', 1) for line in (ROOT / '.env.uat').read_text().splitlines() if line and not line.startswith('#') and '=' in line)
    for key, value in settings.items(): os.environ[key] = value.strip().strip('"\'')
    os.environ['ENV_NAME'] = 'UAT'
    assert make_url(os.environ['DATABASE_URL']).database == 'entenda_uat_db', 'Migracja wyłącznie dla bazy UAT.'
    with contextlib.redirect_stdout(io.StringIO()), patch('engine.generator.start_event_scheduler'), \
            patch('engine.infrastructure_scheduler.start_infrastructure_scheduler'), patch('engine.finance_scheduler.start_finance_scheduler'):
        from zeus_app import app
    return app


if __name__ == '__main__':
    app = make_app()
    from extensions import db
    with app.app_context():
        assert db.session.execute(text('SELECT DATABASE()')).scalar() == 'entenda_uat_db'
        columns = {c['name'] for c in inspect(db.engine).get_columns('game_users')}
        with db.engine.begin() as connection:
            if 'forum_seen_at' not in columns:
                connection.execute(text('ALTER TABLE game_users ADD COLUMN forum_seen_at DATETIME NULL'))
                print('Dodano kolumnę forum_seen_at.')
            updated = connection.execute(text('UPDATE game_users SET forum_seen_at = UTC_TIMESTAMP() WHERE forum_seen_at IS NULL')).rowcount
            print(f'Ustawiono forum_seen_at dla {updated} kont.')
            read = connection.execute(text(
                "UPDATE game_notifications SET read_at = UTC_TIMESTAMP() WHERE notification_type = 'FORUM_MESSAGE' AND read_at IS NULL "
                "AND user_id NOT IN (SELECT user_id FROM game_paga_ai_identities)")).rowcount
            print(f'Oznaczono jako przeczytane {read} powiadomień o wpisach na forum (gracze).')
