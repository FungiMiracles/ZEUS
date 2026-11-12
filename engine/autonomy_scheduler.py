"""UAT-only background autonomy, independent of browser sessions."""
from sqlalchemy import select
from sqlalchemy.orm import Session
from extensions import db
from game.finance_service import game_now
from game.autonomy_models import AutonomySchedule,AutonomyReaction,AutonomyControl
from game.autonomy_engine import collect_and_schedule,eligible_ids,analyze,record_failure


def run_autonomy_tick(app):
    if not app.config.get('AUTONOMY_ENABLED') or app.config.get('ENV_NAME')!='UAT':return
    with app.app_context():
        now=game_now()
        try:
            with Session(db.engine) as session,session.begin():collect_and_schedule(session,now)
            with Session(db.engine) as session:
                control=session.get(AutonomyControl,1)
                if not control or not control.enabled:return
                countries=eligible_ids(session)
                reactions=list(session.execute(select(AutonomyReaction.country_id,AutonomyReaction.event_id).where(AutonomyReaction.country_id.in_(countries),AutonomyReaction.status=='READY',AutonomyReaction.ready_at<=now).order_by(AutonomyReaction.ready_at,AutonomyReaction.country_id).limit(20)))
                periodic=list(session.scalars(select(AutonomySchedule.country_id).where(AutonomySchedule.country_id.in_(countries),AutonomySchedule.next_at<=now).order_by(AutonomySchedule.next_at,AutonomySchedule.country_id).limit(20)))
            for country,event_id in [*reactions,*[(country,None) for country in periodic]]:
                try:
                    with Session(db.engine) as session,session.begin():analyze(session,country,now,event_id=event_id)
                except Exception as error:
                    app.logger.exception('Autonomia: błąd państwa %s',country)
                    try:record_failure(country,now,error,event_id)
                    except Exception:app.logger.exception('Autonomia: nie udało się zapisać błędu państwa %s',country)
        except Exception:app.logger.exception('Autonomia: błąd zbierania zdarzeń; pozostałe moduły działają niezależnie.')


def start_autonomy_scheduler(app):
    if not app.config.get('AUTONOMY_ENABLED') or app.config.get('ENV_NAME')!='UAT':return None
    if app.extensions.get('autonomy_scheduler'):return app.extensions['autonomy_scheduler']
    from apscheduler.schedulers.background import BackgroundScheduler
    scheduler=BackgroundScheduler(timezone='UTC')
    scheduler.add_job(run_autonomy_tick,'interval',seconds=30,args=[app],id='autonomy',max_instances=1,coalesce=True,misfire_grace_time=30)
    app.extensions['autonomy_scheduler']=scheduler;scheduler.start();return scheduler
