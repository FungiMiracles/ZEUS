"""Czas rozwoju technologii (13 Nov 2026).

Technologia z kompletem zainwestowanych punktów rozwija się przez określoną liczbę dni Entendy i dopiero wtedy jest
opracowana (dostępna dla budowy, produkcji i technologii potomnych). Technologie opracowane przed wprowadzeniem
czasu rozwoju (bez wpisu w `timers`) pozostają opracowane.
"""
from datetime import datetime,timedelta
from game.industry_catalog import TECHNOLOGIES

DURATION_DAYS={
    'method':1,
    'arms_industry':2,'energy_industry':2,'environment_tech':2,'it_industry':2,'mining_industry':2,
    'mine_coal':1,'mine_oil':3,'mine_surface':1,'mine_kerbit':7,'mine_natsyt':7,'mine_cemium':14,'mine_uranium':16,'mine_iron':7,
    'chip_simple':3,'chip_kerbit':21,'chip_natsyt':28,'chip_cemium_i':45,'chip_cemium_ii':60,
    'power_solar':14,'power_wind':14,'power_nuclear':60,'power_coal':14,
    'armored':14,'tanks':21,'short_missiles':7,'medium_missiles':14,'long_missiles':21,'nuclear_missiles':132,'interceptor_ammo':10,
    'drones':7,'fighters':60,'warship':124,'carrier':182,'submarine':166,
    'waste_filters':7,'air_filters':12,
    'national_hubs':14,'rail_transport':21,   # kolej (19 Nov 2026)
    'air_transport':28,   # transport lotniczy (20 Nov 2026)
    'radar':30,   # nie podano w wymaganiach — przyjęto 30 dni
    'spy_satellite':60,   # satelita szpiegowski (26 Nov 2026)
}


def _parse(value):
    if isinstance(value,datetime):return value
    try:return datetime.fromisoformat(str(value).rstrip('Z'))
    except (TypeError,ValueError):return None


def funded(nodes,node):
    rule=TECHNOLOGIES.get(node)
    return bool(rule) and int((nodes or {}).get(node,0))>=rule['cost']


def ready_at(timers,node):
    return _parse(((timers or {}).get(node) or {}).get('ready'))


def developed(nodes,timers,node,now):
    """Opracowana: komplet punktów i zakończony czas rozwoju (brak wpisu = opracowana wcześniej)."""
    if not funded(nodes,node):return False
    ready=ready_at(timers,node)
    return ready is None or now is None or ready<=now


def researching(nodes,timers,node,now):
    return funded(nodes,node) and not developed(nodes,timers,node,now)


EDUCATION_THRESHOLD=50   # 21 Nov 2026: poziom edukacji powyżej 50 przyspiesza rozwój technologii o (poziom / 5)%


def education_bonus(level):
    """Procent skrócenia czasu rozwoju technologii dla poziomu edukacji (np. 60 → 12, 80 → 16; do 50 — 0)."""
    try:level=float(level or 0)
    except (TypeError,ValueError):return 0.0
    return round(min(level,100)/5,2) if level>EDUCATION_THRESHOLD else 0.0


def effective_days(node,bonus=0):
    days=DURATION_DAYS.get(node,0)
    return round(days*(1-float(bonus or 0)/100),2) if days else 0


def start(timers,node,now,bonus=0):
    """Wpis rozpoczęcia rozwoju po skompletowaniu punktów (bonus: % skrócenia za poziom edukacji)."""
    timers=dict(timers or {})
    days=effective_days(node,bonus)
    if days>0:
        timers[node]={'started':now.isoformat(),'ready':(now+timedelta(days=days)).isoformat()}
        if bonus:timers[node]['bonus']=bonus
    return timers


def timing(timers,node):
    item=(timers or {}).get(node) or {}
    days=DURATION_DAYS.get(node,0)
    started,ready=_parse(item.get('started')),_parse(item.get('ready'))
    if started and ready:days=round((ready-started).total_seconds()/86400,2)   # 21 Nov 2026: czas po bonusie edukacji
    return {'startedAt':item.get('started'),'readyAt':item.get('ready'),'days':days}
