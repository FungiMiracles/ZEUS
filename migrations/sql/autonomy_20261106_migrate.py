"""UAT-only persistent autonomy foundation and nullable NPC diplomacy participants."""
from pathlib import Path
from datetime import datetime,timezone
import sys
from sqlalchemy import create_engine,text,inspect
from sqlalchemy.engine import make_url


def migrate():
    root=Path(__file__).resolve().parents[2]
    assert root==Path('/home/oskar_zeus_admin/ZEUS_UAT');sys.path.insert(0,str(root))
    settings=dict(line.split('=',1) for line in (root/'.env.uat').read_text().splitlines() if line and not line.startswith('#') and '=' in line)
    url=settings['DATABASE_URL'].strip().strip('\"\'');assert make_url(url).database=='entenda_uat_db'
    import models
    from game import autonomy_models as state
    from engine.clock import SimulationClock,get_current_entenda_datetime
    engine=create_engine(url,hide_parameters=True)
    classes=[state.AutonomyControl,state.AutonomySchedule,state.AutonomyEvent,state.AutonomySourceReceipt,state.AutonomyMemory,state.AutonomyAssessment,state.AutonomyReaction,state.AutonomyAnalysis]
    with engine.begin() as connection:
        assert connection.scalar(text('SELECT DATABASE()'))=='entenda_uat_db'
        for model in classes:model.__table__.create(connection,checkfirst=True)
        columns={row['name']:row for row in inspect(connection).get_columns('game_diplomatic_actions')}
        for column in ('sender_user_id','recipient_user_id'):
            if not columns[column]['nullable']:connection.exec_driver_sql(f'ALTER TABLE game_diplomatic_actions MODIFY COLUMN {column} INTEGER NULL')
        if not connection.scalar(text('SELECT id FROM game_autonomy_control WHERE id=1')):
            clock=connection.execute(text('SELECT real_anchor,entenda_anchor,multiplier FROM wiki_simulation_clock WHERE id=1')).first()
            if clock:
                now=datetime.now(timezone.utc).replace(tzinfo=None);game_at=clock.entenda_anchor+(now-clock.real_anchor)*clock.multiplier
            else:raise RuntimeError('Brak trwałego zegara Entendy; nie można uruchomić autonomii.')
            connection.execute(state.AutonomyControl.__table__.insert().values(id=1,enabled=True,revision=0,max_actions=3,window_days=30,cooldown_days=7,max_chain_depth=2,started_at=game_at,updated_actor='Migracja UAT'))
    print('UAT: autonomy tables, global limits and NPC diplomacy participants verified.')

if __name__=='__main__':migrate()
