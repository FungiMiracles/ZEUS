"""Create only the UAT WIKI secession audit table; do not secede any real region."""
from pathlib import Path
import sys
from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.schema import CreateTable
root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root))
from services.region_secession import RegionSecession
engine=create_engine(dotenv_values(root/'.env.uat')['DATABASE_URL'])
assert engine.url.database=='entenda_uat_db'
with engine.connect() as connection:
    before=tuple(connection.execute(text('SELECT (SELECT COUNT(*) FROM panstwa),(SELECT COUNT(*) FROM regiony)')).one())
RegionSecession.__table__.create(engine,checkfirst=True)
with engine.connect() as connection:
    after=tuple(connection.execute(text('SELECT (SELECT COUNT(*) FROM panstwa),(SELECT COUNT(*) FROM regiony)')).one())
    assert before==after
    print('UAT schema ready; countries/regions unchanged:',after)
    print('Secession records:',connection.scalar(text('SELECT COUNT(*) FROM wiki_region_secessions')))
(root/'migrations/sql/region_secession_entenda_uat_db.sql').write_text(str(CreateTable(RegionSecession.__table__).compile(engine))+';\n')
