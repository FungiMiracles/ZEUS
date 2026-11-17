"""Zamykanie budów bez uzależnienia od zatwierdzania budżetów lub obecności gracza."""
from sqlalchemy.orm import Session
from extensions import db
from game.finance_service import game_now
from game.infrastructure_service import complete_due


def run_infrastructure_tick(app):
    with app.app_context():
        with Session(db.engine) as session, session.begin():
            complete_due(session, game_now())


def run_military_tick(app):
    from sqlalchemy import select
    from game.military_models import MilitaryBase,MilitaryVessel
    from models import Wojsko
    from game.military_service import reconcile_maintenance
    with app.app_context():
        with Session(db.engine) as session:
            ids = sorted(set(session.scalars(select(MilitaryBase.panstwo_id).distinct())) | set(session.scalars(select(Wojsko.panstwo_id).where(Wojsko.bron_atomowa_ilosc>0))))
            ids=sorted(set(ids)|set(session.scalars(select(MilitaryVessel.panstwo_id).where(MilitaryVessel.base_id.is_(None),MilitaryVessel.status.in_(['sailing','stationed','returning'])))))
            # 16 Nov 2026: opłata za żołnierzy w służbie czynnej — także państwa bez baz.
            ids=sorted(set(ids)|set(session.scalars(select(Wojsko.panstwo_id).where((Wojsko.wojska_ladowe_ilosc>0)|(Wojsko.wojska_morskie_ilosc>0)|(Wojsko.wojska_powietrzne_ilosc>0)))))
            from game.governance import controller_id
            ids=sorted({owner for id in ids if (owner := controller_id(session,id)) is not None})
        for country_id in ids:
            with Session(db.engine) as session, session.begin():
                reconcile_maintenance(session,country_id)


def run_flights_tick(app):
    from game.military_flights import complete_flights
    with app.app_context():
        with Session(db.engine) as session,session.begin():
            complete_flights(session,game_now())
        # Land armies: border notifications and battles that are due.
        try:
            from game.land_war import complete_marches
            with Session(db.engine) as session,session.begin():complete_marches(session,game_now())
        except Exception as exc:app.logger.warning('Wojska lądowe: rozliczenie przerwane: %s',f'{type(exc).__name__}: {exc}'[:300])
        # Radars: one detection notification per country and flight (11 Nov 2026).
        try:
            from game.radar import detect
            with Session(db.engine) as session,session.begin():detect(session,game_now())
        except Exception as exc:app.logger.warning('Radary: wykrywanie przerwane: %s',f'{type(exc).__name__}: {exc}'[:300])
        # Wody terytorialne: jedno powiadomienie przy każdym wejściu obcego okrętu (15 Nov 2026).
        try:
            from game.territorial_waters import detect_incursions
            with Session(db.engine) as session,session.begin():detect_incursions(session,game_now())
        except Exception as exc:app.logger.warning('Wody terytorialne: wykrywanie przerwane: %s',f'{type(exc).__name__}: {exc}'[:300])
        from sqlalchemy import select
        from game.military_models import MilitaryVessel
        from game.military_navy import settle_vessels
        from models import Panstwo
        with Session(db.engine) as session:
            countries=list(session.scalars(select(MilitaryVessel.panstwo_id).where(MilitaryVessel.status.in_(['sailing','returning'])).distinct()))
        for country_id in countries:
            with Session(db.engine) as session,session.begin():
                session.scalar(select(Panstwo.PANSTWO_ID).where(Panstwo.PANSTWO_ID==country_id).with_for_update())
                settle_vessels(session,game_now(),country_id)


def run_intelligence_tick(app):
    from game.intelligence_service import complete_missions
    with app.app_context():
        with Session(db.engine) as session,session.begin():complete_missions(session,game_now())


def run_commerce_tick(app):
    from sqlalchemy import select
    from game.commerce_models import Mine
    from game.mining_service import extract_country
    from game.trade_service import deliver_shipments
    with app.app_context():
        with Session(db.engine) as session:
            from game.industry_models import PowerPlant
            from game.research_models import AmmunitionFactory
            countries=sorted(set(session.scalars(select(Mine.panstwo_id).distinct()))|set(session.scalars(select(PowerPlant.panstwo_id).distinct()))|set(session.scalars(select(AmmunitionFactory.panstwo_id).distinct())))
        for country_id in countries:
            with Session(db.engine) as session,session.begin():
                from game.research_service import settle_production
                settle_production(session,country_id,game_now())
        with Session(db.engine) as session,session.begin():deliver_shipments(session,game_now())


def start_infrastructure_scheduler(app):
    from apscheduler.schedulers.background import BackgroundScheduler
    if app.extensions.get('game_infrastructure_scheduler'):
        return app.extensions['game_infrastructure_scheduler']
    scheduler = BackgroundScheduler()
    scheduler.add_job(run_infrastructure_tick, 'interval', seconds=30, args=[app],
                      id='infrastructure_completion', max_instances=1, coalesce=True)
    scheduler.add_job(run_military_tick, 'interval', seconds=30, args=[app],
                      id='military_maintenance', max_instances=1, coalesce=True)
    scheduler.add_job(run_flights_tick,'interval',seconds=5,args=[app],id='military_flights',max_instances=1,coalesce=True)
    scheduler.add_job(run_intelligence_tick,'interval',seconds=5,args=[app],id='intelligence_completion',max_instances=1,coalesce=True)
    scheduler.add_job(run_commerce_tick,'interval',seconds=5,args=[app],id='commerce',max_instances=1,coalesce=True)
    from game.diplomacy_news import run_news_tick
    scheduler.add_job(run_news_tick,'interval',seconds=30,args=[app],id='diplomacy_news',max_instances=1,coalesce=True)
    app.extensions['game_infrastructure_scheduler'] = scheduler
    scheduler.start()
    return scheduler
