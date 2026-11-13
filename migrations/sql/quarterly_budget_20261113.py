"""Budżet kwartalny od 1 października 3001 (UAT, 13 Nov 2026).

- game_state_financial_periods: okres 1–4 (zamiast 1–2), daty okresu sprawdzane tylko co do spójności
  (granice liczy game.finance_service.period_bounds: półrocza do 1.10.3001, potem kwartały),
- II półrocze 3001 kończy się 1 października 3001 (ends_at_game).

    venv/bin/python migrations/sql/quarterly_budget_20261113.py             # zmiana
    venv/bin/python migrations/sql/quarterly_budget_20261113.py --rollback  # wycofanie (tylko bez okresów kwartalnych)
"""
from pathlib import Path
import argparse,importlib.util
from sqlalchemy import text

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('foundation',ROOT/'migrations/sql/paga2_foundation_20261111.py');foundation=importlib.util.module_from_spec(spec);spec.loader.exec_module(foundation)
OLD_DATES=("(starts_at_game = CASE period WHEN 1 THEN CAST(CONCAT(game_year, '-01-01 00:00:00') AS DATETIME) ELSE CAST(CONCAT(game_year, '-07-01 00:00:00') AS DATETIME) END "
           "AND ends_at_game = CASE period WHEN 1 THEN CAST(CONCAT(game_year, '-07-01 00:00:00') AS DATETIME) ELSE CAST(CONCAT(game_year + 1, '-01-01 00:00:00') AS DATETIME) END)")

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--rollback',action='store_true');args=parser.parse_args()
    app=foundation.make_app()
    from extensions import db
    with app.app_context():
        with db.engine.begin() as c:
            if args.rollback:
                count=c.execute(text("SELECT COUNT(*) FROM game_state_financial_periods WHERE period>2 OR (game_year>3001)")).scalar()
                assert count==0,f'Istnieje {count} okresów kwartalnych — wycofanie przerwane.'
                c.execute(text("UPDATE game_state_financial_periods SET ends_at_game='3002-01-01 00:00:00' WHERE game_year=3001 AND period=2"))
                c.execute(text('ALTER TABLE game_state_financial_periods DROP CHECK ck_gsfp_dates'))
                c.execute(text(f'ALTER TABLE game_state_financial_periods ADD CONSTRAINT ck_gsfp_dates CHECK {OLD_DATES}'))
                c.execute(text('ALTER TABLE game_state_financial_periods DROP CHECK ck_gsfp_period'))
                c.execute(text('ALTER TABLE game_state_financial_periods ADD CONSTRAINT ck_gsfp_period CHECK (period IN (1, 2))'))
                print('Wycofano budżet kwartalny.')
            else:
                c.execute(text('ALTER TABLE game_state_financial_periods DROP CHECK ck_gsfp_period'))
                c.execute(text('ALTER TABLE game_state_financial_periods ADD CONSTRAINT ck_gsfp_period CHECK (period IN (1, 2, 3, 4))'))
                c.execute(text('ALTER TABLE game_state_financial_periods DROP CHECK ck_gsfp_dates'))
                c.execute(text('ALTER TABLE game_state_financial_periods ADD CONSTRAINT ck_gsfp_dates CHECK (ends_at_game > starts_at_game)'))
                n=c.execute(text("UPDATE game_state_financial_periods SET ends_at_game='3001-10-01 00:00:00' WHERE game_year=3001 AND period=2")).rowcount
                print(f'Okresy 1–4 dozwolone; II półrocze 3001 kończy się 1.10.3001 (zmieniono {n} okresów).')
