"""UAT only: introduce country lifecycle status; retain records and audit IDs."""
from pathlib import Path
from dotenv import dotenv_values
from sqlalchemy import create_engine, inspect, text

ROOT = Path(__file__).resolve().parents[2]


def migrate(engine):
    if engine.url.database != 'entenda_uat_db' or ROOT.name != 'ZEUS_UAT':
        raise RuntimeError('This migration is restricted to ZEUS_UAT / entenda_uat_db')
    with engine.begin() as connection:
        before = connection.scalar(text('SELECT COUNT(*) FROM panstwa'))
        if 'status' not in {c['name'] for c in inspect(connection).get_columns('panstwa')}:
            connection.execute(text("ALTER TABLE panstwa ADD COLUMN status VARCHAR(16) NOT NULL DEFAULT 'aktywne', "
                "ADD CONSTRAINT ck_panstwa_status CHECK (status IN ('aktywne', 'usunięte'))"))
        # Only completed secessions with no remaining territory/cities qualify.
        candidates = list(connection.scalars(text('''SELECT p.PANSTWO_ID FROM panstwa p
            JOIN wiki_region_secessions s ON s.new_country_id = p.PANSTWO_ID
            WHERE s.rejoined_at IS NOT NULL AND p.status = 'aktywne'
            AND NOT EXISTS (SELECT 1 FROM regiony r WHERE r.panstwo_id = p.PANSTWO_ID)
            AND NOT EXISTS (SELECT 1 FROM miasta m WHERE m.panstwo_id = p.PANSTWO_ID)''')))
        for country_id in candidates:
            connection.execute(text("UPDATE panstwa SET status = 'usunięte' WHERE PANSTWO_ID = :id"), {'id': country_id})
        assert connection.scalar(text('SELECT COUNT(*) FROM panstwa')) == before
        print('UAT: archived completed secession country IDs:', candidates)
        print('UAT status counts:', list(connection.execute(text('SELECT status, COUNT(*) FROM panstwa GROUP BY status'))))


if __name__ == '__main__':
    migrate(create_engine(dotenv_values(ROOT / '.env.uat')['DATABASE_URL']))
