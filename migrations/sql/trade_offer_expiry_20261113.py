"""Wycofywanie ofert handlowych po 14 dniach Entendy (UAT only, 13 Nov 2026).

    venv/bin/python migrations/sql/trade_offer_expiry_20261113.py

Dodaje kolumny game_trade_offers.created_game_at i price_changed_game_at (czas gry) oraz uzupełnia created_game_at
otwartych ofert: czas gry teraz − (czas rzeczywisty od wystawienia × bieżący mnożnik czasu). Skrypt jest idempotentny.
"""
from pathlib import Path
import sys
from datetime import datetime, timezone
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]


def make_app():
    """Pełna aplikacja UAT (bez harmonogramów) — zegar Entendy wymaga konfiguracji aplikacji."""
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
        columns = {c['name'] for c in inspect(db.engine).get_columns('game_trade_offers')}
        with db.engine.begin() as connection:
            if 'created_game_at' not in columns:
                connection.execute(text('ALTER TABLE game_trade_offers ADD COLUMN created_game_at DATETIME NULL, ADD INDEX ix_game_trade_offers_created_game_at (created_game_at)'))
                print('Dodano kolumnę created_game_at.')
            if 'price_changed_game_at' not in columns:
                connection.execute(text('ALTER TABLE game_trade_offers ADD COLUMN price_changed_game_at DATETIME NULL'))
                print('Dodano kolumnę price_changed_game_at.')
        from engine.clock import get_current_entenda_datetime, get_time_multiplier
        game_now = get_current_entenda_datetime(); multiplier = float(get_time_multiplier() or 1)
        real_now = datetime.now(timezone.utc).replace(tzinfo=None)
        rows = db.session.execute(text("SELECT id, created_at FROM game_trade_offers WHERE status='open' AND created_game_at IS NULL")).all()
        for row in rows:
            game_at = game_now - (real_now - row.created_at) * multiplier
            db.session.execute(text('UPDATE game_trade_offers SET created_game_at = :g WHERE id = :id'), {'g': game_at, 'id': row.id})
        db.session.commit()
        print(f'Uzupełniono czas gry dla {len(rows)} otwartych ofert (mnożnik {multiplier}, czas gry {game_now:%Y-%m-%d %H:%M}).')
