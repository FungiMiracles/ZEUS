from game.paga_ai_actor import country_user_id
"""Atomowe finansowanie i kończenie rozbudowy według zegara Entendy."""
from game.governance import controlled_ids, controller_id
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from extensions import db
from game.finance_models import StateBudget, StateBudgetAllocation, StateFinancialAccount
from game.finance_service import FinanceError, game_now, period_key, _country_for_user
from game.infrastructure_models import InfrastructureProject as Project
from models import Region, Miasto
from sqlalchemy.orm import lazyload

INFRASTRUCTURE_NAMES = dict(road='drogowej', rail='kolejowej', energy='energetycznej',
                            housing='mieszkaniowej', port='portowej', connection='skomunikowania')

FIELDS = dict(road='region_stan_infra_drogowej', rail='region_stan_infra_kolejowej',
              energy='region_stan_infra_energetycznej', housing='region_stan_infra_mieszkalnej',
              port='region_stan_infra_portowej', connection='region_poziom_skomunikowania')


def region_population(session, region):
    cities = session.scalar(select(func.coalesce(func.sum(Miasto.miasto_populacja), 0)).where(Miasto.region_id == region.region_id))
    return (region.region_ludnosc_pozamiejska or 0) + cities


def quote(population, metric):
    population = Decimal(population)
    if population <= 0:
        raise FinanceError('Brak dodatniej populacji regionu.')
    rate = Decimal('2000000000') if metric in ('road', 'rail', 'energy') else Decimal('2500000000')
    return ((population / 10000000 * rate).quantize(Decimal('.01'), rounding=ROUND_HALF_UP),
            4)


def reserve_spent(session, budget_id):
    return session.scalar(select(func.coalesce(func.sum(Project.reserve_spent), 0)).where(Project.budget_id == budget_id))


def complete_due(session, now, country_id=None):
    # Blokada regionu poprzedza blokadę zlecenia również przy rozpoczynaniu prac.
    ids = select(Project.region_id).where(Project.completed_at.is_(None), Project.ends_at <= now)
    if country_id is not None:
        ids = ids.where(Project.panstwo_id == country_id)
    for region in session.scalars(select(Region).options(lazyload("*")).where(Region.region_id.in_(ids)).order_by(Region.region_id).with_for_update()):
        for project in session.scalars(select(Project).where(Project.region_id == region.region_id, Project.completed_at.is_(None), Project.ends_at <= now).with_for_update()):
            field = FIELDS[project.metric]
            setattr(region, field, min(100, (getattr(region, field) or 0) + project.levels))
            project.completed_at = now
            from game.forum_models import GameNotification
            from game.models import GamePlayerCountry, utc_now
            owner = country_user_id(session,project.panstwo_id)
            if owner is not None:
                session.add(GameNotification(
                    user_id=owner, infrastructure_project_id=project.id,
                    infrastructure_text=f'Zakończyła się rozbudowa infrastruktury {INFRASTRUCTURE_NAMES[project.metric]} w regionie {region.region_nazwa}',
                    notification_type='INFRASTRUCTURE_COMPLETED', created_at=utc_now(),
                ))
    session.flush()


def start_project(user_id, region_id, metric, levels, use_reserve):
    # 'connection' (poziom skomunikowania) can be expanded since 10 Nov 2026; it has no game effect yet.
    if not isinstance(metric, str) or metric not in FIELDS or isinstance(levels, bool) or not isinstance(levels, int) or levels < 1:
        raise FinanceError('Nieprawidłowy rodzaj lub liczba poziomów.')
    with Session(db.engine) as session, session.begin():
        country = _country_for_user(session, user_id, lock=True)
        now = game_now()
        complete_due(session, now, country.PANSTWO_ID)
        region = session.scalar(select(Region).options(lazyload("*")).where(Region.region_id == region_id, Region.panstwo_id.in_(controlled_ids(session, country.PANSTWO_ID))).with_for_update())
        if region is None:
            raise FinanceError('Region nie należy do państwa gracza.')
        from game.land_war import require_buildable
        require_buildable(session, region.region_id, country.PANSTWO_ID)
        value = getattr(region, FIELDS[metric])
        if value is None or not 0 <= value <= 100 or value + levels > 100:
            raise FinanceError('Docelowy poziom nie może przekraczać 100; wymagane są poprawne dane infrastruktury.')
        if metric == 'port' and region.region_polozenie_id in (None, 1):
            raise FinanceError('Infrastrukturę portową można rozbudowywać tylko w regionie nadmorskim.')
        if session.scalar(select(Project.id).where(Project.region_id == region_id, Project.metric == metric, Project.completed_at.is_(None))):
            raise FinanceError('Ten rodzaj infrastruktury jest już rozbudowywany.')
        unit, days = quote(region_population(session, region), metric)
        cost = unit * levels
        year, period = period_key(now)
        budget = session.scalar(select(StateBudget).where(StateBudget.panstwo_id == country.PANSTWO_ID, StateBudget.game_year == year, StateBudget.period == period).with_for_update())
        if budget is None:
            raise FinanceError('Najpierw zatwierdź budżet na bieżący okres budżetowy.')
        from game.budget_transfers import infrastructure_balance
        allocated,available=infrastructure_balance(session,budget)
        from_budget = min(cost, max(Decimal(0), available))
        from_reserve = cost - from_budget
        account = session.scalar(select(StateFinancialAccount).where(StateFinancialAccount.panstwo_id == country.PANSTWO_ID).with_for_update())
        reserve_balance = account.reserve_balance if account else Decimal(0)
        if from_reserve > reserve_balance:
            raise FinanceError('Budżet infrastruktury i rezerwa budżetowa łącznie nie pokrywają kosztów rozbudowy. Zmniejsz liczbę poziomów.')
        if from_reserve and not use_reserve:
            raise FinanceError('Za mało środków w budżecie infrastruktury. Zaznacz zgodę na użycie rezerwy budżetowej.')
        if from_reserve:
            account.reserve_balance -= from_reserve
        session.add(Project(panstwo_id=country.PANSTWO_ID, region_id=region_id, budget_id=budget.id,
                            metric=metric, levels=levels, cost=cost, budget_spent=from_budget,
                            reserve_spent=from_reserve, starts_at=now, ends_at=now + timedelta(days=days * levels)))
