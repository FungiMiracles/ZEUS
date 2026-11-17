"""UAT: country-wide warehouse missions with no artificial region target.
Existing missions keep their booked price and deadline.
"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from paga2_foundation_20261111 import make_app
from extensions import db
from sqlalchemy import inspect,text

if __name__=='__main__':
    app=make_app()
    with app.app_context(),db.engine.begin() as connection:
        inspector=inspect(connection)
        checks={c['name']:c['sqltext'] for c in inspector.get_check_constraints('game_intelligence_missions')}
        changes=[]
        region=next(c for c in inspector.get_columns('game_intelligence_missions') if c['name']=='region_id')
        if not region['nullable']:changes.append('MODIFY COLUMN region_id INTEGER NULL')
        if 'warehouses' not in checks.get('ck_intelligence_mission_kind',''):
            if 'ck_intelligence_mission_kind' in checks:changes.append('DROP CONSTRAINT ck_intelligence_mission_kind')
            changes.append("ADD CONSTRAINT ck_intelligence_mission_kind CHECK (kind IN ('bases','defenses','nuclear','resources','infrastructure','silos','mines','cyber_energy','cyber_rail','cyber_port','arson','rail_explosive','power','warehouses'))")
        if 'ck_intelligence_mission_scope' not in checks:
            changes.append("ADD CONSTRAINT ck_intelligence_mission_scope CHECK ((kind = 'warehouses' AND region_id IS NULL) OR (kind <> 'warehouses' AND region_id IS NOT NULL))")
        if changes:connection.execute(text('ALTER TABLE game_intelligence_missions '+', '.join(changes)))
    print('Migracja misji państwowych UAT zakończona.')
