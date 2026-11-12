"""UAT only: create the annual crisis guard; never generate a real crisis."""
import sys
from pathlib import Path
from dotenv import dotenv_values
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from services.global_economic_crisis import GlobalEconomicCrisis

if __name__ == '__main__':
    engine = create_engine(dotenv_values(ROOT / '.env.uat')['DATABASE_URL'])
    if ROOT.name != 'ZEUS_UAT' or engine.url.database != 'entenda_uat_db':
        raise RuntimeError('Migration is restricted to ZEUS_UAT / entenda_uat_db')
    with engine.connect() as connection:
        before = connection.scalar(text('SELECT COUNT(*) FROM zdarzenia'))
    GlobalEconomicCrisis.__table__.create(engine, checkfirst=True)
    with engine.connect() as connection:
        print('UAT annual crisis guard ready; recorded crises:', connection.scalar(
            text('SELECT COUNT(*) FROM wiki_global_economic_crises')))
        print('Events before/after migration:', before, connection.scalar(text('SELECT COUNT(*) FROM zdarzenia')))
    print('No crisis generated; no growth values changed.')
