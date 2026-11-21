"""Harmonogram PAGA2 (UAT): co 30 s sprawdza tryby budżetowy, doraźny i cykliczny państw z autonomią.

Nic nie robi, gdy PAGA2 jest globalnie wyłączone (game_paga2_control.enabled). Jeden przebieg naraz (blokada pliku),
każde państwo osobno — błąd jednego nie zatrzymuje pozostałych.
"""
import fcntl
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from extensions import db

TICK_SECONDS=30
BUDGET_RETRY=timedelta(hours=2)
BUDGET_ERROR='Budżet nie został zatwierdzony.'


def eligible_countries(session):
    from game.paga2.models import Paga2Profile
    from game.diplomacy_service import npc_eligible
    return [id for id in session.scalars(select(Paga2Profile.panstwo_id).where(Paga2Profile.autonomy_enabled.is_(True)).order_by(Paga2Profile.panstwo_id)) if npc_eligible(session,id)]


def budget_needed(session,country_id):
    """Budżet bieżącego półrocza nie jest zatwierdzony, a okres oczekuje na decyzję (jak dla gracza)."""
    from game.finance_service import game_now,period_key
    from game.finance_models import StateBudget,StateFinancialPeriod
    year,period=period_key(game_now())
    if session.scalar(select(StateBudget.id).where(StateBudget.panstwo_id==country_id,StateBudget.game_year==year,StateBudget.period==period)):return None
    status=session.scalar(select(StateFinancialPeriod.status).where(StateFinancialPeriod.panstwo_id==country_id,StateFinancialPeriod.game_year==year,StateFinancialPeriod.period==period))
    if status is not None and status!='PENDING':return None
    return year,period


def country_state(session,country_id,control,now):
    from game.paga2.models import Paga2CountryState
    from game.paga_ai_models import PagaAiIdentity
    from game.paga2.triggers import initial_cursors
    state=session.get(Paga2CountryState,country_id,with_for_update=True)
    if state is None:
        identity=session.get(PagaAiIdentity,country_id)
        notes,messages=initial_cursors(session,country_id,identity.user_id) if identity else (0,0)
        # Rozłożenie pierwszych cykli państw w czasie (stałe przesunięcie w granicach jednego interwału).
        offset=int(sha256(f'paga2:{country_id}'.encode()).hexdigest()[:8],16)%max(60,control.interval_minutes*60)
        state=Paga2CountryState(panstwo_id=country_id,next_cycle_at=now+timedelta(seconds=offset),notification_cursor=notes,message_cursor=messages,updated_at=now)
        session.add(state);session.flush()
    return state


def process_country(app,country_id,control,now):
    from game.paga2.engine import run
    from game.paga2.models import Paga2CountryState,Paga2Decision
    from game.paga2.triggers import collect,security
    from game.paga2.gateway import actor_for
    # 1. Tryb budżetowy: budżet półrocza, gdy wymaga tego przebieg gry.
    with Session(db.engine) as session,session.begin():
        actor_for(session,country_id)  # tożsamość państwa (skrzynka powiadomień) musi istnieć przed kursorami
        state=country_state(session,country_id,control,now)
        needed=budget_needed(session,country_id)
        # 17 Nov 2026: budżet bieżącego okresu jest zatwierdzony — błąd poprzedniej próby budżetowej jest nieaktualny.
        if not needed and (state.budget_retry_at is not None or state.last_error==BUDGET_ERROR):
            state.budget_retry_at=None
            if state.last_error is not None:state.last_error=None
        retry=state.budget_retry_at
        attempt=None
        if needed and (retry is None or retry<=now):
            year,period=needed
            attempt=session.scalar(select(func.count(Paga2Decision.id)).where(Paga2Decision.country_id==country_id,Paga2Decision.mode=='BUDGET',
                                                                               Paga2Decision.trigger==f'budżet {year}/{period}'))
    if needed and attempt is not None:
        year,period=needed
        decision=run(app,country_id,'BUDGET',f'budżet {year}/{period}',request_key=f'BUDGET:{country_id}:{year}:{period}:{attempt}')
        with Session(db.engine) as session,session.begin():
            row=session.get(Paga2Decision,decision) if decision else None
            state=session.get(Paga2CountryState,country_id)
            if row is not None and row.status!='EXECUTED':state.budget_retry_at=now+BUDGET_RETRY;state.last_error=row.error or BUDGET_ERROR
            elif row is not None:
                if state.budget_retry_at is not None or state.last_error==BUDGET_ERROR:state.last_error=None
                state.budget_retry_at=None
    # 2. Tryb doraźny: zagrożenia, wiadomości, wpisy forum i powiadomienia od ostatniego przebiegu.
    from game.paga_ai_models import PagaAiIdentity
    with Session(db.engine) as session,session.begin():
        state=session.get(Paga2CountryState,country_id,with_for_update=True)
        identity=session.get(PagaAiIdentity,country_id)
        triggers=collect(session,country_id,state,identity.user_id) if identity else []
        key=f'IMMEDIATE:{country_id}:n{state.notification_cursor}:m{state.message_cursor}'
    if triggers:
        lead=(security(triggers) or triggers)[0]
        run(app,country_id,'IMMEDIATE',lead['label'],request_key=key,triggers=triggers)
    # 3. Tryb cykliczny.
    with Session(db.engine) as session,session.begin():
        state=session.get(Paga2CountryState,country_id,with_for_update=True)
        due=state.next_cycle_at is None or state.next_cycle_at<=now
        key=f'CYCLIC:{country_id}:{(state.next_cycle_at or now).isoformat()}'
        if due:
            state.last_cycle_at=now;state.next_cycle_at=now+timedelta(minutes=control.interval_minutes);state.updated_at=now
    if due:run(app,country_id,'CYCLIC','przegląd cykliczny',request_key=key)


def run_tick(app):
    if app.config.get('ENV_NAME')!='UAT' or not app.config.get('PAGA_ENABLED'):return
    from game.paga2.models import Paga2Control,Paga2CountryState,utc_now
    root=Path(app.root_path)/'runtime/paga2';root.mkdir(parents=True,exist_ok=True)
    with (root/'tick.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        with app.app_context():
            try:
                with Session(db.engine) as session:
                    control=session.get(Paga2Control,1)
                    if control is None or not control.enabled:return
                    session.expunge(control)
                    countries=eligible_countries(session)
            except Exception:
                app.logger.exception('PAGA2: odczyt konfiguracji');return
            now=utc_now()
            for country_id in countries:
                try:process_country(app,country_id,control,now)
                except Exception as error:
                    app.logger.exception('PAGA2: błąd państwa %s',country_id)
                    try:
                        with Session(db.engine) as session,session.begin():
                            state=session.get(Paga2CountryState,country_id)
                            if state is not None:state.last_error=f'{type(error).__name__}: {error}'[:2000];state.updated_at=now
                    except Exception:app.logger.exception('PAGA2: zapis błędu państwa %s',country_id)
            try:
                with Session(db.engine) as session,session.begin():
                    row=session.get(Paga2Control,1,with_for_update=True)
                    if row is not None:row.last_cycle_at=now
            except Exception:app.logger.exception('PAGA2: zapis czasu przebiegu')


def start_paga2_scheduler(app):
    if app.config.get('ENV_NAME')!='UAT' or not app.config.get('PAGA_ENABLED'):return None
    if app.extensions.get('paga2_scheduler'):return app.extensions['paga2_scheduler']
    import game.paga2.budget,game.paga2.planner,game.paga2.finance,game.paga2.industry,game.paga2.trade,game.paga2.defense,game.paga2.diplomacy,game.paga2.intelligence,game.paga2.war,game.paga2.communication,game.paga2.bases_abroad,game.paga2.mines_abroad,game.paga2.rail,game.paga2.airports,game.paga2.cities  # noqa: F401  rejestracja adapterów
    from apscheduler.schedulers.background import BackgroundScheduler
    scheduler=BackgroundScheduler(timezone='UTC')
    scheduler.add_job(run_tick,'interval',seconds=TICK_SECONDS,args=[app],id='paga2',max_instances=1,coalesce=True,misfire_grace_time=TICK_SECONDS)
    app.extensions['paga2_scheduler']=scheduler;scheduler.start();return scheduler
