"""Międzynarodowy Fundusz Walutowy (18 Nov 2026) — UAT i PREPROD.

    venv/bin/python migrations/sql/imf_20261118.py              # podgląd zmian
    venv/bin/python migrations/sql/imf_20261118.py --apply      # kopia schematu do ~/backups + zmiany (idempotentne)
    venv/bin/python migrations/sql/imf_20261118.py --rollback   # wycofanie (tylko gdy MFW niczego jeszcze nie pobrał z budżetu)

Środowisko wynika z katalogu skryptu: ZEUS_UAT → entenda_uat_db (.env.uat), ZEUS_PREPROD → entenda_preprod_db (.env.preprod).
Zmiany:
- nowe tabele game_imf_fund_years, game_imf_loans, game_imf_movements;
- game_state_budgets: kolumna imf_collection (DEFAULT 0) i ograniczenia
  budget_total = opening_reserve + tax_total - imf_collection, imf_collection >= 0;
- game_state_financial_transactions: dozwolona operacja IMF_COLLECTION (DEBIT, bez sektora).
Istniejące budżety mają imf_collection = 0, więc nowe ograniczenia są spełnione bez zmiany danych.
"""
import argparse, gzip, sys
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]
TARGETS = {'ZEUS_UAT': ('.env.uat', 'entenda_uat_db'), 'ZEUS_PREPROD': ('.env.preprod', 'entenda_preprod_db')}
BUDGET_AMOUNTS = ('opening_reserve >= 0 AND tax_total >= 0 AND budget_total >= 0 AND expenditure_total >= 0 '
                  'AND closing_reserve >= 0 AND imf_collection >= 0')
OLD_BUDGET_AMOUNTS = 'opening_reserve >= 0 AND tax_total >= 0 AND budget_total >= 0 AND expenditure_total >= 0 AND closing_reserve >= 0'
BUDGET_BALANCE = 'budget_total = opening_reserve + tax_total - imf_collection AND budget_total = expenditure_total + closing_reserve'
OLD_BUDGET_BALANCE = 'budget_total = opening_reserve + tax_total AND budget_total = expenditure_total + closing_reserve'
OPERATION = ("(operation_type IN ('TAX_PIT', 'TAX_CIT', 'TAX_GENERAL') AND direction = 'CREDIT' AND category_code IS NULL) "
             "OR (operation_type = 'BUDGET_ALLOCATION' AND direction = 'DEBIT' AND category_code IS NOT NULL AND category_code <> 'reserve') "
             "OR (operation_type = 'IMF_COLLECTION' AND direction = 'DEBIT' AND category_code IS NULL)")
OLD_OPERATION = ("(operation_type IN ('TAX_PIT', 'TAX_CIT', 'TAX_GENERAL') AND direction = 'CREDIT' AND category_code IS NULL) "
                 "OR (operation_type = 'BUDGET_ALLOCATION' AND direction = 'DEBIT' AND category_code IS NOT NULL AND category_code <> 'reserve')")


def engine_for_root():
    env_file, database = TARGETS[ROOT.name]
    settings = dict(line.split('=', 1) for line in (ROOT / env_file).read_text().splitlines() if line and not line.startswith('#') and '=' in line)
    url = settings['DATABASE_URL'].strip().strip('"\'')
    assert make_url(url).database == database, f'Migracja wyłącznie dla bazy {database}.'
    return create_engine(url, hide_parameters=True), database


def checks(connection, table):
    return {c['name']: (c.get('sqltext') or '') for c in inspect(connection).get_check_constraints(table)}


def changes(connection):
    result = []
    columns = {c['name'] for c in inspect(connection).get_columns('game_state_budgets')}
    budget_checks = checks(connection, 'game_state_budgets')
    clauses = []
    if 'imf_collection' not in columns:
        clauses.append('ADD COLUMN imf_collection DECIMAL(30,2) NOT NULL DEFAULT 0 AFTER budget_total')
    if 'imf_collection' not in budget_checks.get('ck_gsb_balance', ''):
        clauses += ['DROP CHECK ck_gsb_balance', f'ADD CONSTRAINT ck_gsb_balance CHECK ({BUDGET_BALANCE})']
    if 'imf_collection' not in budget_checks.get('ck_gsb_amounts', ''):
        clauses += ['DROP CHECK ck_gsb_amounts', f'ADD CONSTRAINT ck_gsb_amounts CHECK ({BUDGET_AMOUNTS})']
    if clauses:
        result.append('ALTER TABLE game_state_budgets ' + ', '.join(clauses))
    if 'IMF_COLLECTION' not in checks(connection, 'game_state_financial_transactions').get('ck_gsft_operation', ''):
        result.append(f'ALTER TABLE game_state_financial_transactions DROP CHECK ck_gsft_operation, ADD CONSTRAINT ck_gsft_operation CHECK ({OPERATION})')
    return result


def missing_tables(connection):
    from game.imf_models import ImfFundYear, ImfLoan, ImfMovement
    return [model.__table__ for model in (ImfFundYear, ImfLoan, ImfMovement) if not inspect(connection).has_table(model.__tablename__)]


def backup(connection, database):
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    path = ROOT.parent / 'backups' / f'{database}_imf_schema_20261118_{stamp}.sql.gz'
    path.touch(mode=0o600, exist_ok=False)
    with gzip.open(path, 'wt', encoding='utf-8') as output:
        output.write(f'-- Schemat tabel przed migracją MFW ({database}); dane nie są zmieniane przez migrację.\n')
        for table in ('game_state_budgets', 'game_state_financial_transactions'):
            output.write(connection.execute(text(f'SHOW CREATE TABLE `{table}`')).one()[1] + ';\n\n')
    print('Kopia schematu:', path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--rollback', action='store_true')
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    import models, game.models, game.finance_models  # noqa: F401 — klucze obce nowych tabel
    from extensions import db  # noqa: F401
    engine, database = engine_for_root()
    with engine.begin() as connection:
        assert connection.execute(text('SELECT DATABASE()')).scalar() == database
        if args.rollback:
            collected = connection.execute(text('SELECT COUNT(*) FROM game_state_budgets WHERE imf_collection <> 0')).scalar()
            assert collected == 0, f'{collected} budżetów zawiera spłatę MFW — wycofanie przerwane.'
            backup(connection, database)
            connection.execute(text('ALTER TABLE game_state_financial_transactions DROP CHECK ck_gsft_operation, '
                                    f'ADD CONSTRAINT ck_gsft_operation CHECK ({OLD_OPERATION})'))
            connection.execute(text('ALTER TABLE game_state_budgets DROP CHECK ck_gsb_balance, DROP CHECK ck_gsb_amounts, DROP COLUMN imf_collection, '
                                    f'ADD CONSTRAINT ck_gsb_balance CHECK ({OLD_BUDGET_BALANCE}), ADD CONSTRAINT ck_gsb_amounts CHECK ({OLD_BUDGET_AMOUNTS})'))
            for table in ('game_imf_movements', 'game_imf_loans', 'game_imf_fund_years'):
                connection.execute(text(f'DROP TABLE IF EXISTS `{table}`'))
            print(f'{database}: migracja MFW wycofana.')
            return
        statements, tables = changes(connection), missing_tables(connection)
        print(f'{database}: nowe tabele: {[t.name for t in tables]}; zmiany schematu: {len(statements)}')
        for statement in statements:
            print('  ', statement)
        if not args.apply:
            return
        if statements:
            backup(connection, database)
        for table in tables:
            table.create(connection, checkfirst=True)
        for statement in statements:
            connection.execute(text(statement))
        assert not changes(connection) and not missing_tables(connection), 'Weryfikacja schematu nie powiodła się.'
        print(f'{database}: schemat MFW zastosowany i zweryfikowany.')


if __name__ == '__main__':
    main()
