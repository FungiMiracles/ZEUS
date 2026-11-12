"""Effects of regional infrastructure on energy, mining and port exports (administrator rules, 10 Nov 2026).

Thresholds: a value of 80 or more is the top tier (the specification left 80 and 80–90 open; decided: ≥80 = top).
Factories are affected indirectly: an energy deficit stops factories, largest consumers first (industry_service).
"""
from decimal import Decimal,ROUND_CEILING

COAL='wegiel_kamienny'


# A region without infrastructure data (NULL) is not penalised: missing data is not weak infrastructure.
NO_DATA=100


def _value(level):
    try:return int(level) if level is not None else NO_DATA
    except (TypeError,ValueError):return NO_DATA


def energy_factor(level):
    """Share of the nominal power plant output (infrastruktura energetyczna)."""
    level=_value(level)
    if level>=80:return Decimal(1)
    if level>=60:return Decimal('0.8')
    if level>=30:return Decimal('0.5')
    if level>=10:return Decimal('0.25')
    return Decimal(0)


def power_output(nominal,level):
    """Effective output of a plant, rounded up to an integer; 0 below 10."""
    factor=energy_factor(level)
    if not factor:return 0
    return int((Decimal(str(nominal))*factor).to_integral_value(rounding=ROUND_CEILING))


def extraction_time_factor(level):
    """Multiplier of the time to extract one unit (infrastruktura kolejowa); None = no extraction in the region."""
    level=_value(level)
    if level>=80:return Decimal(1)
    if level>=60:return Decimal('1.2')
    if level>=30:return Decimal('1.4')
    if level>=10:return Decimal('1.6')
    return None


def port_export_limit(level):
    """(maximum units per offer or None for unlimited, only allowed good or None) for infrastruktura portowa."""
    level=_value(level)
    if level>=80:return None,None
    if level>=60:return 500,None
    if level>=30:return 300,None
    if level>=10:return 100,None
    return 100,COAL


def describe(region):
    """Short player-facing summary of the effects in a region (Region ORM row)."""
    factor=energy_factor(region.region_stan_infra_energetycznej)
    time=extraction_time_factor(region.region_stan_infra_kolejowej)
    limit,only=port_export_limit(region.region_stan_infra_portowej)
    return {'energyPercent':int(factor*100),'extractionTimePercent':int(time*100) if time is not None else None,
            'portLimit':limit,'portOnly':only}
