"""Read-only current-half-year budget amounts for the shared game header."""
from sqlalchemy import select
from game.finance_models import StateBudget
from game.finance_service import game_now,period_key
from game.budget_transfers import sector_balances
from game.budget_categories import CODES

LABELS={'administration':'Administracja','infrastructure':'Infrastruktura','armed_forces':'Siły zbrojne','social_policy':'Polityka społeczna','environment':'Środowisko',
        'healthcare':'Ochrona zdrowia','education':'Edukacja','research':'Badania i rozwój','security_services':'Służby bezpieczeństwa','reserve':'Rezerwa'}


def budget_overview(session,country_id):
    year,period=period_key(game_now())
    budget=session.scalar(select(StateBudget).where(StateBudget.panstwo_id==country_id,StateBudget.game_year==year,StateBudget.period==period))
    if budget is None:return {'year':year,'period':period,'items':[]}
    balances=sector_balances(session,budget)
    return {'year':year,'period':period,'items':[{'code':code,'label':LABELS[code],'remaining':balances[code]['remaining'],'allocated':balances[code]['allocated'],'spent':balances[code]['spent']} for code in CODES]}
