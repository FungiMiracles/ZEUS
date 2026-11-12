"""PAGA2 — silnik decyzji (UAT only).

1. Tabela game_paga2_country_states (harmonogram i kursory wyzwalaczy PAGA2).
2. Wyłączenie dotychczasowych mechanizmów (decyzja administratora 11 Nov 2026):
   - otwarte zadania modeli AI spoza zakresu forum / wiadomości prywatnych / pożyczek -> CANCELLED,
   - aktywne plany warunkowe modeli AI -> CANCELLED,
   - oczekujące reakcje dotychczasowego silnika regułowego -> IGNORED.
   Przełączniki globalne (PAGA2 i modele AI) NIE są zmieniane.

    venv/bin/python migrations/sql/paga2_engine_20261112.py            # zmiany
    venv/bin/python migrations/sql/paga2_engine_20261112.py --rollback # usuwa tylko tabelę stanów (anulowanych zadań nie przywraca)
"""
from pathlib import Path
import sys,argparse,importlib.util
from sqlalchemy import inspect,text,select

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('foundation',ROOT/'migrations/sql/paga2_foundation_20261111.py');foundation=importlib.util.module_from_spec(spec);spec.loader.exec_module(foundation)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--rollback',action='store_true');args=parser.parse_args()
    app=foundation.make_app()
    from extensions import db
    import models,game.finance_models  # noqa: F401
    from game.paga2.models import Paga2CountryState,utc_now
    from game.paga_ai_models import PagaAiJob,PagaAiPlan
    from game.paga_ai_tasks import LLM_KINDS
    from game.autonomy_models import AutonomyReaction
    with app.app_context():
        inspector=inspect(db.engine)
        if args.rollback:
            with db.engine.begin() as connection:connection.execute(text('DROP TABLE IF EXISTS game_paga2_country_states'))
            print('Usunięto game_paga2_country_states.')
        else:
            if not inspector.has_table(Paga2CountryState.__tablename__):Paga2CountryState.__table__.create(db.engine);print('Utworzono game_paga2_country_states')
            now=utc_now()
            with db.session.begin():
                jobs=list(db.session.scalars(select(PagaAiJob).where(PagaAiJob.status.in_(['PENDING','QUEUED','BLOCKED']),PagaAiJob.kind.notin_(LLM_KINDS))))
                for job in jobs:job.status='CANCELLED';job.finished_at=now;job.error='Poza zakresem modeli AI: decyzje państwa podejmuje PAGA2.'
                plans=list(db.session.scalars(select(PagaAiPlan).where(PagaAiPlan.status.in_(['ACTIVE','TRIGGERED']))))
                for plan in plans:plan.status='CANCELLED'
                reactions=list(db.session.scalars(select(AutonomyReaction).where(AutonomyReaction.status=='READY')))
                for row in reactions:row.status='IGNORED'
                print(f'Anulowano zadania AI: {len(jobs)}, plany warunkowe: {len(plans)}, reakcje starego silnika: {len(reactions)}.')
            print('Gotowe.')
