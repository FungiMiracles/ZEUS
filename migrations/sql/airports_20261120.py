"""Transport lotniczy (20 Nov 2026) — UAT i PREPROD.

    venv/bin/python migrations/sql/airports_20261120.py              # podgląd zmian
    venv/bin/python migrations/sql/airports_20261120.py --apply      # kopia schematu do ~/backups + zmiany (idempotentne)
    venv/bin/python migrations/sql/airports_20261120.py --rollback   # wycofanie (tylko gdy nie ma lotnisk, dochodów ani lotów handlowych)

Środowisko wynika z katalogu skryptu: ZEUS_UAT → entenda_uat_db (.env.uat), ZEUS_PREPROD → entenda_preprod_db (.env.preprod).
Zmiany:
- nowe tabele game_airports, game_airport_expenses, game_air_route_suspensions;
- game_state_budgets: kolumna air_income (DEFAULT 0) i ograniczenia
  budget_total = opening_reserve + tax_total + rail_income + air_income - imf_collection, air_income >= 0;
- game_state_financial_transactions: dozwolona operacja AIR_INCOME (CREDIT, bez sektora);
- game_trade_offers: kolumna transport ('sea' | 'air', DEFAULT 'sea');
- game_trade_shipments: transport może mieć wartość 'air';
- game_military_flights: kolumna target_airport_id (klucz obcy do game_airports, ON DELETE SET NULL);
- game_missile_defenses: rodzaj chronionego obiektu 'airport';
- game_airports: kolumna renamed_at (zmiana nazwy lotniska raz na rok Entendy; dodana 20 Nov 2026 po pierwszym wdrożeniu UAT).
Wymaga wcześniejszej migracji kolei (rail_20261119). Istniejące wiersze spełniają nowe ograniczenia bez zmiany danych.
"""
import argparse, gzip, sys
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]
TARGETS = {'ZEUS_UAT': ('.env.uat', 'entenda_uat_db'), 'ZEUS_PREPROD': ('.env.preprod', 'entenda_preprod_db')}
BUDGET_AMOUNTS = ('opening_reserve >= 0 AND tax_total >= 0 AND budget_total >= 0 AND expenditure_total >= 0 '
                  'AND closing_reserve >= 0 AND imf_collection >= 0 AND rail_income >= 0 AND air_income >= 0')
OLD_BUDGET_AMOUNTS = ('opening_reserve >= 0 AND tax_total >= 0 AND budget_total >= 0 AND expenditure_total >= 0 '
                      'AND closing_reserve >= 0 AND imf_collection >= 0 AND rail_income >= 0')
BUDGET_BALANCE = ('budget_total = opening_reserve + tax_total + rail_income + air_income - imf_collection '
                  'AND budget_total = expenditure_total + closing_reserve')
OLD_BUDGET_BALANCE = ('budget_total = opening_reserve + tax_total + rail_income - imf_collection '
                      'AND budget_total = expenditure_total + closing_reserve')
OPERATION = ("(operation_type IN ('TAX_PIT', 'TAX_CIT', 'TAX_GENERAL', 'RAIL_INCOME', 'AIR_INCOME') AND direction = 'CREDIT' AND category_code IS NULL) "
             "OR (operation_type = 'BUDGET_ALLOCATION' AND direction = 'DEBIT' AND category_code IS NOT NULL AND category_code <> 'reserve') "
             "OR (operation_type = 'IMF_COLLECTION' AND direction = 'DEBIT' AND category_code IS NULL)")
OLD_OPERATION = ("(operation_type IN ('TAX_PIT', 'TAX_CIT', 'TAX_GENERAL', 'RAIL_INCOME') AND direction = 'CREDIT' AND category_code IS NULL) "
                 "OR (operation_type = 'BUDGET_ALLOCATION' AND direction = 'DEBIT' AND category_code IS NOT NULL AND category_code <> 'reserve') "
                 "OR (operation_type = 'IMF_COLLECTION' AND direction = 'DEBIT' AND category_code IS NULL)")
SHIPMENT_TRANSPORT = "transport IN ('sea','land','air')"
OLD_SHIPMENT_TRANSPORT = "transport IN ('sea','land')"
DEFENSE_KIND = "target_kind IN ('region','city','base','mine','factory','power','radar','airport')"
OLD_DEFENSE_KIND = "target_kind IN ('region','city','base','mine','factory','power','radar')"
OFFER_TRANSPORT = "transport IN ('sea','air')"


def engine_for_root():
    env_file, database = TARGETS[ROOT.name]
    settings = dict(line.split('=', 1) for line in (ROOT / env_file).read_text().splitlines() if line and not line.startswith('#') and '=' in line)
    url = settings['DATABASE_URL'].strip().strip('"\'')
    assert make_url(url).database == database, f'Migracja wyłącznie dla bazy {database}.'
    return create_engine(url, hide_parameters=True), database


def checks(connection, table):
    return {c['name']: (c.get('sqltext') or '') for c in inspect(connection).get_check_constraints(table)}


def columns(connection, table):
    return {c['name'] for c in inspect(connection).get_columns(table)}


def changes(connection):
    result = []
    budget_columns = columns(connection, 'game_state_budgets')
    assert 'rail_income' in budget_columns, 'Najpierw wykonaj migrację kolei (rail_20261119).'
    budget_checks = checks(connection, 'game_state_budgets')
    clauses = []
    if 'air_income' not in budget_columns:
        clauses.append('ADD COLUMN air_income DECIMAL(30,2) NOT NULL DEFAULT 0 AFTER rail_income')
    if 'air_income' not in budget_checks.get('ck_gsb_balance', ''):
        clauses += ['DROP CHECK ck_gsb_balance', f'ADD CONSTRAINT ck_gsb_balance CHECK ({BUDGET_BALANCE})']
    if 'air_income' not in budget_checks.get('ck_gsb_amounts', ''):
        clauses += ['DROP CHECK ck_gsb_amounts', f'ADD CONSTRAINT ck_gsb_amounts CHECK ({BUDGET_AMOUNTS})']
    if clauses:
        result.append('ALTER TABLE game_state_budgets ' + ', '.join(clauses))
    if 'AIR_INCOME' not in checks(connection, 'game_state_financial_transactions').get('ck_gsft_operation', ''):
        result.append(f'ALTER TABLE game_state_financial_transactions DROP CHECK ck_gsft_operation, ADD CONSTRAINT ck_gsft_operation CHECK ({OPERATION})')
    offer = []
    if 'transport' not in columns(connection, 'game_trade_offers'):
        offer.append("ADD COLUMN transport VARCHAR(8) NOT NULL DEFAULT 'sea'")
    if 'ck_trade_offer_transport' not in checks(connection, 'game_trade_offers'):
        offer.append(f'ADD CONSTRAINT ck_trade_offer_transport CHECK ({OFFER_TRANSPORT})')
    if offer:
        result.append('ALTER TABLE game_trade_offers ' + ', '.join(offer))
    if "'air'" not in checks(connection, 'game_trade_shipments').get('ck_trade_shipment_transport', ''):
        result.append(f'ALTER TABLE game_trade_shipments DROP CHECK ck_trade_shipment_transport, ADD CONSTRAINT ck_trade_shipment_transport CHECK ({SHIPMENT_TRANSPORT})')
    if "'airport'" not in checks(connection, 'game_missile_defenses').get('ck_missile_defense_kind', ''):
        result.append(f'ALTER TABLE game_missile_defenses DROP CHECK ck_missile_defense_kind, ADD CONSTRAINT ck_missile_defense_kind CHECK ({DEFENSE_KIND})')
    if inspect(connection).has_table('game_airports') and 'renamed_at' not in columns(connection, 'game_airports'):
        result.append('ALTER TABLE game_airports ADD COLUMN renamed_at DATETIME NULL AFTER removed_at')
    if 'target_airport_id' not in columns(connection, 'game_military_flights'):
        result.append('ALTER TABLE game_military_flights ADD COLUMN target_airport_id INT NULL, ADD KEY ix_flight_target_airport (target_airport_id), '
                      'ADD CONSTRAINT fk_flight_target_airport FOREIGN KEY (target_airport_id) REFERENCES game_airports (id) ON DELETE SET NULL')
    return result


def missing_tables(connection):
    from game.airport_models import Airport, AirportExpense, AirRouteSuspension
    return [model.__table__ for model in (Airport, AirportExpense, AirRouteSuspension) if not inspect(connection).has_table(model.__tablename__)]


def backup(connection, database):
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    path = ROOT.parent / 'backups' / f'{database}_airports_schema_20261120_{stamp}.sql.gz'
    path.touch(mode=0o600, exist_ok=False)
    with gzip.open(path, 'wt', encoding='utf-8') as output:
        output.write(f'-- Schemat tabel przed migracją transportu lotniczego ({database}); dane nie są zmieniane przez migrację.\n')
        for table in ('game_state_budgets', 'game_state_financial_transactions', 'game_trade_offers', 'game_trade_shipments',
                      'game_military_flights', 'game_missile_defenses'):
            output.write(connection.execute(text(f'SHOW CREATE TABLE `{table}`')).one()[1] + ';\n\n')
    print('Kopia schematu:', path)


def rollback(connection, database):
    count = lambda sql: connection.execute(text(sql)).scalar()
    assert count('SELECT COUNT(*) FROM game_state_budgets WHERE air_income <> 0') == 0, 'Budżety zawierają dochody z lotnictwa — wycofanie przerwane.'
    if inspect(connection).has_table('game_airports'):
        assert count('SELECT COUNT(*) FROM game_airports') == 0, 'W bazie są lotniska — wycofanie przerwane.'
    assert count("SELECT COUNT(*) FROM game_trade_shipments WHERE transport = 'air'") == 0, 'W bazie są ładunki lotnicze — wycofanie przerwane.'
    assert count("SELECT COUNT(*) FROM game_trade_offers WHERE transport = 'air'") == 0, 'W bazie są oferty lotnicze — wycofanie przerwane.'
    backup(connection, database)
    if 'target_airport_id' in columns(connection, 'game_military_flights'):
        connection.execute(text('ALTER TABLE game_military_flights DROP FOREIGN KEY fk_flight_target_airport'))
        connection.execute(text('ALTER TABLE game_military_flights DROP KEY ix_flight_target_airport, DROP COLUMN target_airport_id'))
    connection.execute(text(f'ALTER TABLE game_missile_defenses DROP CHECK ck_missile_defense_kind, ADD CONSTRAINT ck_missile_defense_kind CHECK ({OLD_DEFENSE_KIND})'))
    connection.execute(text(f'ALTER TABLE game_trade_shipments DROP CHECK ck_trade_shipment_transport, ADD CONSTRAINT ck_trade_shipment_transport CHECK ({OLD_SHIPMENT_TRANSPORT})'))
    if 'transport' in columns(connection, 'game_trade_offers'):
        connection.execute(text('ALTER TABLE game_trade_offers DROP CHECK ck_trade_offer_transport, DROP COLUMN transport'))
    connection.execute(text(f'ALTER TABLE game_state_financial_transactions DROP CHECK ck_gsft_operation, ADD CONSTRAINT ck_gsft_operation CHECK ({OLD_OPERATION})'))
    connection.execute(text('ALTER TABLE game_state_budgets DROP CHECK ck_gsb_balance, DROP CHECK ck_gsb_amounts, DROP COLUMN air_income, '
                            f'ADD CONSTRAINT ck_gsb_balance CHECK ({OLD_BUDGET_BALANCE}), ADD CONSTRAINT ck_gsb_amounts CHECK ({OLD_BUDGET_AMOUNTS})'))
    for table in ('game_air_route_suspensions', 'game_airport_expenses', 'game_airports'):
        connection.execute(text(f'DROP TABLE IF EXISTS `{table}`'))
    print(f'{database}: migracja transportu lotniczego wycofana.')


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
            rollback(connection, database)
            return
        tables = missing_tables(connection)
        statements = changes(connection)
        print(f'{database}: nowe tabele: {[t.name for t in tables]}; zmiany schematu: {len(statements)}')
        for statement in statements:
            print('  ', statement)
        if not args.apply:
            return
        if statements:
            backup(connection, database)
        for table in tables:                       # tabele najpierw — klucz obcy lotów wskazuje na game_airports
            table.create(connection, checkfirst=True)
        for statement in statements:
            connection.execute(text(statement))
        assert not changes(connection) and not missing_tables(connection), 'Weryfikacja schematu nie powiodła się.'
        print(f'{database}: schemat transportu lotniczego zastosowany i zweryfikowany.')


if __name__ == '__main__':
    main()
