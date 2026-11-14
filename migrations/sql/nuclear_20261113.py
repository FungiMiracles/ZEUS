"""Rakiety z głowicą nuklearną (UAT only, 13 Nov 2026).

    venv/bin/python migrations/sql/nuclear_20261113.py            # tabele + wyzerowanie dotychczasowych zapasów broni atomowej
    venv/bin/python migrations/sql/nuclear_20261113.py --rollback # usuwa puste tabele (zerowania nie cofa — dane w kopii JSON)

Tworzy tabele game_nuclear_orders (zamówienia produkcji) i game_nuclear_zones (strefy skażenia).
Decyzja administratora: dotychczasowe zapasy broni atomowej są zerowane — pole wojsko.bron_atomowa_ilosc oraz głowice
w garnizonach silosów. Przed zmianą wartości są zapisywane w backups/nuclear_reset_20261113.json (tylko raz).
Skrypt jest idempotentny.
"""
from pathlib import Path
import sys, argparse, json
from datetime import datetime, timezone
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]
BACKUP = ROOT / 'backups' / 'nuclear_reset_20261113.json'


def make_app():
    assert ROOT == Path('/home/oskar_zeus_admin/ZEUS_UAT'); sys.path.insert(0, str(ROOT))
    from flask import Flask
    from extensions import db
    settings = dict(line.split('=', 1) for line in (ROOT / '.env.uat').read_text().splitlines() if line and not line.startswith('#') and '=' in line)
    url = settings['DATABASE_URL'].strip().strip('"\''); assert make_url(url).database == 'entenda_uat_db', 'Migracja wyłącznie dla bazy UAT.'
    app = Flask('nuclear-migration', root_path=str(ROOT)); app.config.update(SQLALCHEMY_DATABASE_URI=url, SQLALCHEMY_ENGINE_OPTIONS={'hide_parameters': True}, ENV_NAME='UAT')
    db.init_app(app); return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--rollback', action='store_true'); args = parser.parse_args()
    app = make_app()
    from extensions import db
    import models, game.finance_models, game.research_models, game.military_models  # noqa: F401
    from game.nuclear_models import NuclearOrder, NuclearZone
    with app.app_context():
        assert db.session.execute(text('SELECT DATABASE()')).scalar() == 'entenda_uat_db'
        inspector = inspect(db.engine)
        if args.rollback:
            for model in (NuclearOrder, NuclearZone):
                if inspector.has_table(model.__tablename__):
                    count = db.session.execute(text(f'SELECT COUNT(*) FROM {model.__tablename__}')).scalar()
                    assert count == 0, f'Tabela {model.__tablename__} zawiera {count} wierszy — wycofanie przerwane.'
                    model.__table__.drop(db.engine); print('Usunięto', model.__tablename__)
            sys.exit(0)
        for model in (NuclearOrder, NuclearZone):
            if inspector.has_table(model.__tablename__): print('Tabela już istnieje:', model.__tablename__)
            else: model.__table__.create(db.engine); print('Utworzono', model.__tablename__)
        # zerowanie dotychczasowych zapasów (kopia przed pierwszą zmianą)
        army = [dict(row._mapping) for row in db.session.execute(text('SELECT panstwo_id, bron_atomowa_ilosc FROM wojsko WHERE bron_atomowa_ilosc IS NOT NULL AND bron_atomowa_ilosc <> 0'))]
        silos = []
        for row in db.session.execute(text("SELECT id, panstwo_id, garrison FROM game_military_bases WHERE kind='nuclear'")):
            garrison = row.garrison if isinstance(row.garrison, dict) else json.loads(row.garrison or '{}')
            if int(garrison.get('warheads', 0) or 0):
                silos.append({'id': row.id, 'panstwo_id': row.panstwo_id, 'warheads': int(garrison['warheads']), 'garrison': garrison})
        if army or silos:
            if not BACKUP.exists():
                BACKUP.parent.mkdir(exist_ok=True)
                BACKUP.write_text(json.dumps({'created_at': datetime.now(timezone.utc).isoformat(), 'wojsko': army, 'silos': silos}, ensure_ascii=False, indent=1))
                print('Kopia wartości przed zerowaniem:', BACKUP)
            db.session.execute(text('UPDATE wojsko SET bron_atomowa_ilosc = 0 WHERE bron_atomowa_ilosc IS NOT NULL AND bron_atomowa_ilosc <> 0'))
            for silo in silos:
                garrison = {**silo['garrison'], 'warheads': 0}
                db.session.execute(text('UPDATE game_military_bases SET garrison = :g WHERE id = :id'), {'g': json.dumps(garrison), 'id': silo['id']})
            db.session.commit()
            print(f'Wyzerowano: wojsko.bron_atomowa_ilosc w {len(army)} państwach, głowice w {len(silos)} silosach '
                  f'(łącznie {sum(r["bron_atomowa_ilosc"] for r in army)} w tabeli, {sum(s["warheads"] for s in silos)} w silosach).')
        else:
            print('Brak zapasów broni atomowej do wyzerowania.')
