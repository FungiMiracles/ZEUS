"""MFW — nowe zasady (18 Nov 2026): odsetki 5% za cykl, pula 1 000 MLD — UAT i PREPROD.

    venv/bin/python migrations/sql/imf_rules_20261118.py             # podgląd
    venv/bin/python migrations/sql/imf_rules_20261118.py --apply     # zmiana (idempotentna)
    venv/bin/python migrations/sql/imf_rules_20261118.py --rollback  # wycofanie (tylko gdy nie naliczono żadnych odsetek)

- game_imf_loans: interest_rate (pożyczki sprzed zmiany: 0), interest (naliczone odsetki), interest_year/interest_period
  (ostatni okres naliczenia); ograniczenie: outstanding <= amount + interest;
- game_imf_fund_years: pula 1 000 MLD dla lat, w których dotąd pożyczono nie więcej niż nowa pula.
Środowisko wynika z katalogu skryptu (ZEUS_UAT / ZEUS_PREPROD).
"""
import argparse
from pathlib import Path
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]
TARGETS = {'ZEUS_UAT': ('.env.uat', 'entenda_uat_db'), 'ZEUS_PREPROD': ('.env.preprod', 'entenda_preprod_db')}
POOL = '1000000000000.00'
OLD_POOL = '10000000000000.00'
CHECK = ("amount > 0 AND outstanding >= 0 AND interest >= 0 AND interest_rate >= 0 AND outstanding <= amount + interest "
         "AND status IN ('active','repaid','rejected') AND (status <> 'active' OR outstanding > 0) AND (status = 'active' OR outstanding = 0)")
OLD_CHECK = ("amount > 0 AND outstanding >= 0 AND outstanding <= amount AND status IN ('active','repaid','rejected') "
             "AND (status <> 'active' OR outstanding > 0) AND (status = 'active' OR outstanding = 0)")


def engine():
    env_file, database = TARGETS[ROOT.name]
    settings = dict(line.split('=', 1) for line in (ROOT / env_file).read_text().splitlines() if line and not line.startswith('#') and '=' in line)
    url = settings['DATABASE_URL'].strip().strip('"\'')
    assert make_url(url).database == database, f'Migracja wyłącznie dla bazy {database}.'
    return create_engine(url, hide_parameters=True), database


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--rollback', action='store_true')
    args = parser.parse_args()
    eng, database = engine()
    with eng.begin() as c:
        assert c.execute(text('SELECT DATABASE()')).scalar() == database
        columns = {col['name'] for col in inspect(c).get_columns('game_imf_loans')}
        if args.rollback:
            if 'interest' in columns:
                charged = c.execute(text('SELECT COUNT(*) FROM game_imf_loans WHERE interest > 0')).scalar()
                assert charged == 0, f'{charged} pożyczek ma naliczone odsetki — wycofanie przerwane.'
                c.execute(text('ALTER TABLE game_imf_loans DROP CHECK ck_imf_loan_values, DROP COLUMN interest_rate, DROP COLUMN interest, '
                               f'DROP COLUMN interest_year, DROP COLUMN interest_period, ADD CONSTRAINT ck_imf_loan_values CHECK ({OLD_CHECK})'))
            c.execute(text(f'UPDATE game_imf_fund_years SET pool = {OLD_POOL} WHERE pool = {POOL}'))
            print(f'{database}: zasady MFW wycofane (pula 10 bln, bez odsetek).')
            return
        statements = []
        if 'interest' not in columns:
            statements.append('ALTER TABLE game_imf_loans ADD COLUMN interest_rate DECIMAL(6,4) NOT NULL DEFAULT 0, '
                              'ADD COLUMN interest DECIMAL(30,2) NOT NULL DEFAULT 0, ADD COLUMN interest_year INT NULL, '
                              f'ADD COLUMN interest_period SMALLINT NULL, DROP CHECK ck_imf_loan_values, ADD CONSTRAINT ck_imf_loan_values CHECK ({CHECK})')
        pools = c.execute(text(f'SELECT game_year, pool, lent FROM game_imf_fund_years WHERE pool <> {POOL}')).all()
        too_much = [row for row in pools if row.lent > float(POOL)]
        if pools:
            statements.append(f'UPDATE game_imf_fund_years SET pool = {POOL} WHERE pool <> {POOL} AND lent <= {POOL}')
        print(f'{database}: lata z pulą do zmiany: {[(r.game_year, float(r.lent) / 1e9) for r in pools]} (pożyczono MLD)')
        if too_much:
            print('UWAGA: lata, w których pożyczono więcej niż nowa pula — pula bez zmian:', [r.game_year for r in too_much])
        for statement in statements:
            print('  ', statement)
        if args.apply:
            for statement in statements:
                c.execute(text(statement))
            assert 'interest' in {col['name'] for col in inspect(c).get_columns('game_imf_loans')}
            print(f'{database}: zasady MFW zastosowane.')


if __name__ == '__main__':
    main()
