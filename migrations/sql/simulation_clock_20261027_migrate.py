"""UAT only: preserve the legacy date and speed while enabling persistent clock."""
import sys
from pathlib import Path
from datetime import datetime
from dotenv import dotenv_values
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from engine.clock import SimulationClock, ENTENDA_START, REAL_START, TIME_MULTIPLIER

if __name__ == '__main__':
    engine = create_engine(dotenv_values(ROOT / '.env.uat')['DATABASE_URL'])
    if ROOT.name != 'ZEUS_UAT' or engine.url.database != 'entenda_uat_db':
        raise RuntimeError('Migration is restricted to ZEUS_UAT / entenda_uat_db')
    SimulationClock.__table__.create(engine, checkfirst=True)
    with Session(engine) as session, session.begin():
        row = session.scalar(select(SimulationClock).where(SimulationClock.id == 1).with_for_update())
        if row is None:
            now = datetime.now()
            session.add(SimulationClock(id=1, real_anchor=now,
                entenda_anchor=ENTENDA_START + (now-REAL_START)*TIME_MULTIPLIER,
                multiplier=12, revision=0, actor='Migracja UAT'))
            print('UAT persistent clock initialized at the existing date and ×12 speed.')
        else:
            print('UAT clock already initialized; existing date and speed retained:', row.multiplier)
