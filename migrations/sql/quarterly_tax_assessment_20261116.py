"""Budżet kwartalny — poprawka ograniczenia kwot podatku okresu (UAT, 16 Nov 2026).

Migracja quarterly_budget_20261113 nie zmieniła ck_gsta_half_year_amounts, które wymagało
kwoty okresu = roczna / 2. Od IV kwartału 3001 kwota okresu = roczna / 4 (game.finance_service.is_quarterly),
więc zatwierdzenie budżetu kwartalnego kończyło się błędem 3819 (Check constraint violated).

    venv/bin/python migrations/sql/quarterly_tax_assessment_20261116.py             # zmiana
    venv/bin/python migrations/sql/quarterly_tax_assessment_20261116.py --rollback  # wycofanie (tylko bez naliczeń kwartalnych)
"""
from pathlib import Path
import argparse,importlib.util
from sqlalchemy import text

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('foundation',ROOT/'migrations/sql/paga2_foundation_20261111.py');foundation=importlib.util.module_from_spec(spec);spec.loader.exec_module(foundation)
QUARTERLY="(game_year > 3001 OR (game_year = 3001 AND period = 4))"
NEW_CHECK=(f"(({QUARTERLY} AND half_year_pit = ROUND(annual_pit / 4, 2) AND half_year_cit = ROUND(annual_cit / 4, 2)) "
           f"OR (NOT {QUARTERLY} AND half_year_pit = ROUND(annual_pit / 2, 2) AND half_year_cit = ROUND(annual_cit / 2, 2))) "
           "AND total_amount = half_year_pit + half_year_cit")
OLD_CHECK="half_year_pit = ROUND(annual_pit / 2, 2) AND half_year_cit = ROUND(annual_cit / 2, 2) AND total_amount = half_year_pit + half_year_cit"

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--rollback',action='store_true');args=parser.parse_args()
    app=foundation.make_app()
    from extensions import db
    with app.app_context():
        with db.engine.begin() as c:
            if args.rollback:
                count=c.execute(text(f"SELECT COUNT(*) FROM game_state_tax_assessments WHERE {QUARTERLY}")).scalar()
                assert count==0,f'Istnieje {count} naliczeń kwartalnych — wycofanie przerwane.'
                check=OLD_CHECK
            else:
                check=NEW_CHECK
            c.execute(text('ALTER TABLE game_state_tax_assessments DROP CHECK ck_gsta_half_year_amounts'))
            c.execute(text(f'ALTER TABLE game_state_tax_assessments ADD CONSTRAINT ck_gsta_half_year_amounts CHECK ({check})'))
            print('Wycofano poprawkę ck_gsta_half_year_amounts.' if args.rollback else 'ck_gsta_half_year_amounts: kwartały = roczna / 4, półrocza = roczna / 2.')
