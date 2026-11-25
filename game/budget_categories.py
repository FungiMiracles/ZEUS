"""Current budget sectors and a lossless view of historical allocations."""
from decimal import Decimal
INFRASTRUCTURE_LEGACY=('energy_infrastructure','road_infrastructure','port_infrastructure','rail_infrastructure','housing_infrastructure','mining_infrastructure')
# 25 Nov 2026 (decyzja administratora): sektor „Propaganda” usunięty z podziału budżetu. Budżety zatwierdzone wcześniej
# zachowują swoje wiersze — w widokach udział propagandy liczy się jako rezerwa, a niewydane środki propagandy
# przechodzą do rezerwy przy zatwierdzeniu kolejnego budżetu (game.finance_service.unspent_sectors).
CODES=('administration','infrastructure','armed_forces','social_policy','environment','healthcare','education','research','security_services','reserve')
PROPAGANDA_CODES=('administration','infrastructure','armed_forces','social_policy','environment','healthcare','education','research','security_services','propaganda','reserve')
LEGACY_CODES=('administration',*INFRASTRUCTURE_LEGACY,'armed_forces','social_policy','environment','family_policy','healthcare','education','research','security_services','diplomacy','propaganda','reserve')
RETIRED=('propaganda',)
ALIASES={**{code:'infrastructure' for code in INFRASTRUCTURE_LEGACY},'family_policy':'social_policy','diplomacy':'reserve','propaganda':'reserve'}
def canonical(code):return ALIASES.get(code,code)
def normalize(items):
    result={code:Decimal(0) for code in CODES}
    for code,value in items:
        target=canonical(code)
        if target not in result:raise ValueError('Unknown budget sector')
        result[target]+=value or Decimal(0)
    return result
def complete(rows):
    codes={row.category_code for row in rows}
    return len(codes)==len(rows) and codes in (set(CODES),set(PROPAGANDA_CODES),set(LEGACY_CODES),set(LEGACY_CODES)-{'mining_infrastructure'})
