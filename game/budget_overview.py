"""Read-only current-half-year budget amounts for the shared game header."""
from sqlalchemy import select
from game.finance_models import StateBudget
from game.finance_service import game_now,period_key
from game.budget_transfers import sector_balances
from game.budget_categories import CODES

LABELS=dict(zip(CODES,('Administracja','Infrastruktura','Siły zbrojne','Polityka społeczna','Środowisko','Ochrona zdrowia','Edukacja','Badania i rozwój','Służby bezpieczeństwa','Propaganda','Rezerwa')))


def budget_overview(session,country_id):
    year,period=period_key(game_now())
    budget=session.scalar(select(StateBudget).where(StateBudget.panstwo_id==country_id,StateBudget.game_year==year,StateBudget.period==period))
    if budget is None:return {'year':year,'period':period,'items':[]}
    balances=sector_balances(session,budget)
    return {'year':year,'period':period,'items':[{'code':code,'label':LABELS[code],'remaining':balances[code]['remaining']} for code in CODES]}
