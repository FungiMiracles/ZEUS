"""Additive UAT migration: curved roads, captured agents, hybrid operations, loans."""
from pathlib import Path
import sys
from sqlalchemy import create_engine,inspect,text,select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session


def migrate():
    root=Path(__file__).resolve().parents[2];assert root==Path('/home/oskar_zeus_admin/ZEUS_UAT');sys.path.insert(0,str(root))
    settings=dict(line.split('=',1) for line in (root/'.env.uat').read_text().splitlines() if line and not line.startswith('#') and '=' in line)
    url=settings['DATABASE_URL'].strip().strip('\"\'');assert make_url(url).database=='entenda_uat_db'
    from models import Panstwo,Region
    from game.models import GameUser
    from game.finance_models import StateBudget
    from game.loan_models import StateLoan,LoanMovement
    from game.civic_models import Road
    from game.roads import curved_path
    from game.military_geography import map_features,MAP_PATH
    engine=create_engine(url,hide_parameters=True)
    with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as conn:
        assert conn.scalar(text('SELECT DATABASE()'))=='entenda_uat_db'
        before=conn.execute(text('SELECT panstwo_id,reserve_balance,last_budget_id,last_transaction_sequence FROM game_state_financial_accounts ORDER BY panstwo_id')).all()
        for model in (StateLoan,LoanMovement):model.__table__.create(conn,checkfirst=True)
        if 'path' not in {c['name'] for c in inspect(conn).get_columns('game_roads')}:conn.exec_driver_sql('ALTER TABLE game_roads ADD COLUMN path JSON NULL')
        if 'captured_at' not in {c['name'] for c in inspect(conn).get_columns('game_intelligence_agents')}:conn.exec_driver_sql('ALTER TABLE game_intelligence_agents ADD COLUMN captured_at DATETIME NULL')
        checks=inspect(conn).get_check_constraints('game_intelligence_missions')
        kind_check=next(c for c in checks if 'kind' in c['sqltext'])
        if 'cyber_energy' not in kind_check['sqltext']:
            assert kind_check['name'].replace('_','').isalnum()
            kinds="'bases','defenses','nuclear','resources','infrastructure','silos','mines','cyber_energy','cyber_rail','cyber_port','arson','rail_explosive'"
            conn.exec_driver_sql(f"ALTER TABLE game_intelligence_missions DROP CHECK `{kind_check['name']}`, ADD CONSTRAINT ck_intelligence_mission_kind_v3 CHECK (kind IN ({kinds}))")
        assert before==conn.execute(text('SELECT panstwo_id,reserve_balance,last_budget_id,last_transaction_sequence FROM game_state_financial_accounts ORDER BY panstwo_id')).all()
    with Session(engine) as session,session.begin():
        features=map_features(MAP_PATH);owners=dict(session.execute(select(Region.region_id,Region.panstwo_id)).all())
        roads=list(session.scalars(select(Road).where(Road.path.is_(None)).with_for_update()));curved=0
        for road in roads:
            land=[f for f in features if road.admin_actor or owners.get(f.get('properties',{}).get('region_id'))==road.panstwo_id]
            try:road.path=curved_path(land,[road.start_x,road.start_y],[road.end_x,road.end_y]);curved+=1
            except Exception:road.path=[[road.start_x,road.start_y],[road.end_x,road.end_y]]
        print(f'UAT schema verified; curved paths initialized for {curved}/{len(roads)} existing roads. Historical costs, lengths and reserve balances unchanged.')


if __name__=='__main__':migrate()
