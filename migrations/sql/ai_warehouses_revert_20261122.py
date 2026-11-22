"""Cofnięcie magazynów PAGA2 ustawionych odgórnie w miastach portowych (UAT / PREPROD, 22 Nov 2026).

    cd ZEUS_UAT && ENV_NAME=UAT venv/bin/python migrations/sql/ai_warehouses_revert_20261122.py
    cd ZEUS_PREPROD && ENV_NAME=PREPROD ../ZEUS_UAT/venv/bin/python migrations/sql/ai_warehouses_revert_20261122.py

Usuwa wiersze game_warehouses państw PAGA2 zapisane skryptem (user_id IS NULL). Państwa PAGA2 wybiorą magazyn same
(game.paga2.warehouse — decyzja wymagana przy najbliższym przebiegu cyklicznym); do tego czasu magazyn jest w stolicy.
Wybory graczy (user_id ustawiony) zostają.
"""
import os, sys
from pathlib import Path
from sqlalchemy import create_engine, text
ROOT = Path(__file__).resolve().parents[2]
ENV = {'UAT': ROOT / '.env.uat', 'PREPROD': ROOT / '.env.preprod'}[os.environ['ENV_NAME']]
url = next(line.split('=', 1)[1].strip().strip('"\'') for line in ENV.read_text().splitlines() if line.startswith('DATABASE_URL='))
with create_engine(url).begin() as connection:
    print('Baza:', connection.execute(text('SELECT DATABASE()')).scalar())
    rows = connection.execute(text('SELECT w.panstwo_id, w.miasto_id FROM game_warehouses w JOIN game_paga_ai_identities i ON i.country_id = w.panstwo_id '
                                   'WHERE w.user_id IS NULL')).all()
    connection.execute(text('DELETE w FROM game_warehouses w JOIN game_paga_ai_identities i ON i.country_id = w.panstwo_id WHERE w.user_id IS NULL'))
    print(f'Usunięto magazyny {len(rows)} państw PAGA2:', [tuple(r) for r in rows])
