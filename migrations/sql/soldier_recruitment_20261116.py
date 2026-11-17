"""Rekrutacja żołnierzy do służby czynnej (UAT only, 16 Nov 2026).

    venv/bin/python migrations/sql/soldier_recruitment_20261116.py                    # kolumny opłaty za żołnierzy (idempotentne)
    venv/bin/python migrations/sql/soldier_recruitment_20261116.py --reset-reserve    # kopia + wyzerowanie rezerwy żołnierzy
    venv/bin/python migrations/sql/soldier_recruitment_20261116.py --restore-reserve  # przywrócenie liczebności z kopii
    venv/bin/python migrations/sql/soldier_recruitment_20261116.py --rollback         # usunięcie kolumn

1) game_military_maintenance: soldier_count, soldier_rate, soldier_fee, soldiers_assessed_at (zmiana addytywna;
   istniejące okresy mają opłatę 0 i nienaliczoną — zostanie naliczona przy najbliższym rozliczeniu utrzymania).
2) --reset-reserve (decyzja użytkownika, 16 Nov 2026): liczebność wojsk lądowych, morskich i powietrznych każdego
   państwa zostaje zredukowana do żołnierzy przydzielonych (garnizony baz + armie lądowe w operacjach); rezerwa = 0.
   Przed zmianą tabela backup_wojsko_soldiers_20261116 zapisuje dotychczasowe wartości (operacja jednorazowa —
   ponowne uruchomienie nie nadpisuje kopii).
3) Okres przejściowy: bieżący okres rozliczeniowy zostaje oznaczony jako rozliczony z opłatą 0 dla wszystkich państw —
   opłata za żołnierzy obowiązuje od następnego okresu (bez naliczania w trakcie okresu, gdy budżety są już
   częściowo wydane, co od razu zwolniłoby żołnierzy z garnizonów). Wykonywane w ramach --reset-reserve.
"""
from pathlib import Path
import sys, argparse
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]
BACKUP = 'backup_wojsko_soldiers_20261116'
COLUMNS = [('soldier_count', 'BIGINT NOT NULL DEFAULT 0'), ('soldier_rate', 'DECIMAL(30,2) NOT NULL DEFAULT 0'),
           ('soldier_fee', 'DECIMAL(30,2) NOT NULL DEFAULT 0'), ('soldiers_assessed_at', 'DATETIME NULL'),
           ('soldiers_recruited', 'BIGINT NOT NULL DEFAULT 0')]   # 16 Nov 2026: rekruci okresu bez opłaty do następnego okresu


def make_app():
    assert ROOT == Path('/home/oskar_zeus_admin/ZEUS_UAT'); sys.path.insert(0, str(ROOT))
    from zeus_app import app
    from extensions import db
    with app.app_context():
        assert make_url(str(db.engine.url)).database == 'entenda_uat_db', 'Migracja wyłącznie dla bazy UAT.'
    return app


def add_columns(db):
    present = {column['name'] for column in inspect(db.engine).get_columns('game_military_maintenance')}
    missing = [(name, ddl) for name, ddl in COLUMNS if name not in present]
    if not missing:
        print('Kolumny opłaty za żołnierzy już istnieją.'); return
    with db.engine.begin() as connection:
        connection.execute(text('ALTER TABLE game_military_maintenance ' + ', '.join(f'ADD COLUMN {name} {ddl}' for name, ddl in missing)))
    print('Dodano kolumny:', ', '.join(name for name, _ in missing))


def reset_reserve(db):
    from sqlalchemy import select
    from models import Wojsko
    from game.military_recruitment import SOLDIER_FIELDS, assigned
    if inspect(db.engine).has_table(BACKUP):
        raise SystemExit(f'Kopia {BACKUP} już istnieje — rezerwa była już zerowana. Przerwano (bez zmian).')
    with db.engine.begin() as connection:
        connection.execute(text(f'CREATE TABLE {BACKUP} AS SELECT ID, panstwo_id, wojska_ladowe_ilosc, wojska_morskie_ilosc, '
                                f'wojska_powietrzne_ilosc, NOW() AS backup_at FROM wojsko'))
    print(f'Kopia zapasowa: {BACKUP}.')
    before = after = 0
    for army in db.session.scalars(select(Wojsko).with_for_update()):
        used = assigned(db.session, army.panstwo_id)
        for branch, field in SOLDIER_FIELDS.items():
            current = int(getattr(army, field) or 0); new = min(current, used[branch])
            before += current; after += new
            setattr(army, field, new)
    db.session.commit()
    print(f'Żołnierze w służbie czynnej: {before} → {after} (pozostali wyłącznie przydzieleni do baz i operacji).')


def mark_current_period(db):
    from sqlalchemy import select
    from models import Wojsko
    from game.military_models import MilitaryMaintenance
    from game.finance_service import game_now, period_key
    from game.models import utc_now
    year, period = period_key(game_now())
    rows = {r.panstwo_id: r for r in db.session.scalars(select(MilitaryMaintenance).where(MilitaryMaintenance.game_year == year, MilitaryMaintenance.period == period))}
    for country_id in set(db.session.scalars(select(Wojsko.panstwo_id))):
        row = rows.get(country_id)
        if row is None:
            row = MilitaryMaintenance(panstwo_id=country_id, game_year=year, period=period, amount=0); db.session.add(row)
        if row.soldiers_assessed_at is None:
            row.soldier_count, row.soldier_rate, row.soldier_fee, row.soldiers_assessed_at = 0, 0, 0, utc_now()
    db.session.commit()
    print(f'Okres {year}/{period}: opłata za żołnierzy 0 (obowiązuje od następnego okresu).')


def restore_reserve(db):
    if not inspect(db.engine).has_table(BACKUP):raise SystemExit('Brak kopii zapasowej.')
    with db.engine.begin() as connection:
        connection.execute(text(f'UPDATE wojsko w JOIN {BACKUP} b ON b.ID = w.ID SET w.wojska_ladowe_ilosc = b.wojska_ladowe_ilosc, '
                                'w.wojska_morskie_ilosc = b.wojska_morskie_ilosc, w.wojska_powietrzne_ilosc = b.wojska_powietrzne_ilosc'))
    print('Przywrócono liczebność z kopii.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--rollback', action='store_true'); group.add_argument('--reset-reserve', action='store_true'); group.add_argument('--restore-reserve', action='store_true')
    args = parser.parse_args()
    app = make_app()
    from extensions import db
    with app.app_context():
        assert db.session.execute(text('SELECT DATABASE()')).scalar() == 'entenda_uat_db'
        if args.rollback:
            present = {column['name'] for column in inspect(db.engine).get_columns('game_military_maintenance')}
            drop = [name for name, _ in COLUMNS if name in present]
            if drop:
                with db.engine.begin() as connection:
                    connection.execute(text('ALTER TABLE game_military_maintenance ' + ', '.join(f'DROP COLUMN {name}' for name in drop)))
            print('Usunięto kolumny:', ', '.join(drop) or '—')
        elif args.reset_reserve:
            add_columns(db); reset_reserve(db); mark_current_period(db)
        elif args.restore_reserve:
            restore_reserve(db)
        else:
            add_columns(db)
