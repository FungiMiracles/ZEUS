"""Current budget sectors and a lossless view of historical allocations."""
from decimal import Decimal
INFRASTRUCTURE_LEGACY=('energy_infrastructure','road_infrastructure','port_infrastructure','rail_infrastructure','housing_infrastructure','mining_infrastructure')
CODES=('administration','infrastructure','armed_forces','social_policy','environment','healthcare','education','research','security_services','propaganda','reserve')
LEGACY_CODES=('administration',*INFRASTRUCTURE_LEGACY,'armed_forces','social_policy','environment','family_policy','healthcare','education','research','security_services','diplomacy','propaganda','reserve')
ALIASES={**{code:'infrastructure' for code in INFRASTRUCTURE_LEGACY},'family_policy':'social_policy','diplomacy':'reserve'}
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
    return len(codes)==len(rows) and codes in (set(CODES),set(LEGACY_CODES),set(LEGACY_CODES)-{'mining_infrastructure'})
