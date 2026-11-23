"""Utrzymanie wojska pobierane przed podziałem budżetu (UAT / PREPROD, 23 Nov 2026).

    venv/bin/python migrations/sql/military_upkeep_20261123.py uat [--dry-run]
    venv/bin/python migrations/sql/military_upkeep_20261123.py preprod [--dry-run]

Zmiany (idempotentne; istniejące wiersze spełniają nowe ograniczenia bez zmiany danych):
- game_state_budgets: kolumny military_upkeep DECIMAL(30,2) NULL (NULL = budżet sprzed zasady) i military_upkeep_details JSON NULL;
  ograniczenia: military_upkeep IS NULL OR military_upkeep >= 0;
  budget_total = opening_reserve + tax_total + rail_income + air_income - imf_collection - COALESCE(military_upkeep, 0);
- game_state_financial_transactions: dozwolona operacja MILITARY_UPKEEP (DEBIT, bez sektora).
"""
import sys
from pathlib import Path
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
sys.path.insert(0, str(Path(__file__).resolve().parent))
from production_orders_20261122 import TARGETS, database_url

BUDGET_AMOUNTS = ('opening_reserve >= 0 AND tax_total >= 0 AND budget_total >= 0 AND expenditure_total >= 0 '
                  'AND closing_reserve >= 0 AND imf_collection >= 0 AND rail_income >= 0 AND air_income >= 0 '
                  'AND (military_upkeep IS NULL OR military_upkeep >= 0)')
BUDGET_BALANCE = ('budget_total = opening_reserve + tax_total + rail_income + air_income - imf_collection - COALESCE(military_upkeep, 0) '
                  'AND budget_total = expenditure_total + closing_reserve')
OPERATION = ("(operation_type IN ('TAX_PIT', 'TAX_CIT', 'TAX_GENERAL', 'RAIL_INCOME', 'AIR_INCOME') AND direction = 'CREDIT' AND category_code IS NULL) "
             "OR (operation_type = 'BUDGET_ALLOCATION' AND direction = 'DEBIT' AND category_code IS NOT NULL AND category_code <> 'reserve') "
             "OR (operation_type IN ('IMF_COLLECTION', 'MILITARY_UPKEEP') AND direction = 'DEBIT' AND category_code IS NULL)")


def checks(connection, table):
    return {c['name']: (c.get('sqltext') or '') for c in inspect(connection).get_check_constraints(table)}


def changes(connection):
    result = []
    columns = {c['name'] for c in inspect(connection).get_columns('game_state_budgets')}
    assert 'air_income' in columns, 'Najpierw wykonaj migrację transportu lotniczego (airports_20261120).'
    clauses = []
    if 'military_upkeep' not in columns:
        clauses.append('ADD COLUMN military_upkeep DECIMAL(30,2) NULL AFTER air_income')
    if 'military_upkeep_details' not in columns:
        clauses.append('ADD COLUMN military_upkeep_details JSON NULL AFTER military_upkeep')
    budget_checks = checks(connection, 'game_state_budgets')
    if 'military_upkeep' not in budget_checks.get('ck_gsb_amounts', ''):
        clauses += ['DROP CHECK ck_gsb_amounts', f'ADD CONSTRAINT ck_gsb_amounts CHECK ({BUDGET_AMOUNTS})']
    if 'military_upkeep' not in budget_checks.get('ck_gsb_balance', ''):
        clauses += ['DROP CHECK ck_gsb_balance', f'ADD CONSTRAINT ck_gsb_balance CHECK ({BUDGET_BALANCE})']
    if clauses:
        result.append('ALTER TABLE game_state_budgets ' + ', '.join(clauses))
    if 'MILITARY_UPKEEP' not in checks(connection, 'game_state_financial_transactions').get('ck_gsft_operation', ''):
        result.append(f'ALTER TABLE game_state_financial_transactions DROP CHECK ck_gsft_operation, ADD CONSTRAINT ck_gsft_operation CHECK ({OPERATION})')
    return result


def main(target, dry_run=False):
    env_file, database = TARGETS[target]
    url = database_url(env_file)
    assert make_url(url).database == database
    engine = create_engine(url, hide_parameters=True)
    with engine.begin() as connection:
        assert connection.execute(text('SELECT DATABASE()')).scalar() == database
        pending = changes(connection)
        if not pending:
            print(f'{database}: schemat aktualny.'); return
        for statement in pending:
            print(f'{database}: {statement[:160]}{"…" if len(statement) > 160 else ""}')
            if not dry_run:
                connection.execute(text(statement))
        print(f'{database}: {"--dry-run, bez zmian" if dry_run else "zmiany zastosowane"}.')


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if a != '--dry-run']
    if len(args) != 1 or args[0] not in TARGETS:
        raise SystemExit('Użycie: military_upkeep_20261123.py uat|preprod [--dry-run]')
    main(args[0], '--dry-run' in sys.argv)
