"""PAGA2 — satelity szpiegowskie (26 Nov 2026).

Ścieżka jak u gracza (game.satellites):
* technologia „Satelita szpiegowski” i fabryka satelitów — cel planera (game.paga2.planner: factory:satellites,
  priorytety „Rozwój wywiadu” i „Rozwój armii ofensywnej”);
* zamówienie produkcji w gotowej fabryce (1 sztuka, 90 dni Entendy), gdy państwo ma mniej satelitów, niż chce
  (1, a przy dużej skłonności do szpiegostwa 2) i surowce w magazynie;
* wyniesienie satelity z magazynu na orbitę z własnej, sprawnej bazy lotniczej w kraju (1 rakieta dalekiego zasięgu,
  300 ropy naftowej);
* misje rozpoznawcze satelity dryfującego na orbicie (120 mln ROI z budżetu służb): cele planów wojennych, państwa,
  z którymi trwa wojna, zagrożenia, a w pokoju — sąsiedzi (przy skłonności do szpiegostwa). Wyniki misji trafiają do
  known_ids (cele w panelu wojennym), tak samo jak raporty agentów.
"""
from datetime import timedelta
from uuid import uuid5, NAMESPACE_URL
from sqlalchemy import select
from sqlalchemy.orm import Session
from extensions import db
from game.paga2.engine import Adapter, register
from game.paga2.scoring import Option
from game.paga2.finance import result

LAUNCH = '/game/satelity/wystrzel'
MISSION = '/game/satelity/misja'
REPEAT_DAYS = 30                                    # ten sam rodzaj rozpoznania tego samego państwa najwyżej raz na 30 dni
WAR_KINDS = ('bases', 'defenses', 'silos', 'power', 'mines')
PEACE_KINDS = ('bases', 'silos', 'power')


def rid(ctx, option):
    return str(uuid5(NAMESPACE_URL, f'paga2:{ctx.request_key}:{option.key}'))


def wanted(ctx):
    return 2 if ctx.traits.get('espionage', 50) >= 70 else 1


def order_options(ctx, session, have):
    from game.research_models import AmmunitionFactory
    from game.nuclear import on_demand_spec, factory_ready_at, _active_order
    from game.industry_service import available
    from game.satellites import FACTORY_KIND
    if have >= wanted(ctx):
        return []
    spec = on_demand_spec(FACTORY_KIND)
    options = []
    for factory in session.scalars(select(AmmunitionFactory).where(AmmunitionFactory.panstwo_id == ctx.country_id, AmmunitionFactory.kind == FACTORY_KIND,
                                                                    AmmunitionFactory.removed_at.is_(None), AmmunitionFactory.health > 0)):
        if ctx.now is not None and ctx.now < factory_ready_at(factory):
            continue
        if _active_order(session, factory.id) is not None:
            return []                                   # satelita już w produkcji
        missing = [code for code, need in spec['inputs'].items() if available(session, ctx.country_id, code) < need]
        if missing:
            continue                                    # surowce uzupełnia handel / kopalnie (planer)
        options.append(Option(key=f'sat:order:{factory.id}', domain='intelligence', action='SATELLITE_ORDER',
                              label=f'Produkcja satelity szpiegowskiego (fabryka #{factory.id}, 90 dni Entendy)',
                              cost=0.0, effects={'intelligence': 1.0, 'offensive_army': .3, 'defensive_army': .3},
                              traits={'espionage': .8, 'secrecy': .3, 'ambition': .2}, base=3.0,
                              notes=[f'Satelity: {have} (pożądane {wanted(ctx)}). Surowce: ' +
                                     ', '.join(f'{code} {need}' for code, need in spec['inputs'].items()) + '.'],
                              payload={'factory_id': factory.id, 'count': 1, 'group': 'sat:order'}))
        break
    return options


def launch_base(session, country_id):
    """Własna, sprawna baza lotnicza na terytorium kraju (nie pod okupacją), z której można wynieść satelitę."""
    from game.military_models import MilitaryBase
    from game.base_permits import own_region_ids
    from game.land_war import active_occupation
    own = set(own_region_ids(session, country_id))
    for base in session.scalars(select(MilitaryBase).where(MilitaryBase.panstwo_id == country_id, MilitaryBase.kind == 'air',
                                                           MilitaryBase.health > 0, MilitaryBase.map_x.is_not(None)).order_by(MilitaryBase.id)):
        if base.operational and base.region_id in own and active_occupation(session, 'region', base.region_id) is None \
                and active_occupation(session, 'base', base.id) is None:
            return base
    return None


def launch_options(ctx, session):
    from game.satellites import in_stock, LAUNCH_INPUTS, LAUNCH_MISSILE_FIELD, LAUNCH_MISSILES
    from game.industry_service import available
    from game.governance import army_for_country
    if in_stock(session, ctx.country_id) < 1:
        return []
    army = army_for_country(session, ctx.country_id)
    if army is None or (getattr(army, LAUNCH_MISSILE_FIELD) or 0) < LAUNCH_MISSILES:
        return []
    if any(available(session, ctx.country_id, code) < need for code, need in LAUNCH_INPUTS.items()):
        return []
    base = launch_base(session, ctx.country_id)
    if base is None:
        return []
    return [Option(key=f'sat:launch:{base.id}', domain='intelligence', action='SATELLITE_LAUNCH',
                   label=f'Wyniesienie satelity szpiegowskiego na orbitę z bazy lotniczej #{base.id}',
                   cost=0.0, effects={'intelligence': 1.0, 'offensive_army': .3, 'defensive_army': .3},
                   traits={'espionage': .8, 'ambition': .3}, base=6.0,
                   notes=['Satelita w magazynie nie prowadzi rozpoznania — dopiero na orbicie. Koszt: 1 rakieta dalekiego zasięgu i 300 ropy.'],
                   payload={'base_id': base.id, 'group': 'sat:launch'})]


def targets(ctx):
    """(państwo, rodzaje rozpoznania, cel, premia) — od najpilniejszych."""
    s = ctx.situation
    result_ = []
    try:
        from game.paga2 import war_plans
        for _plan, other, _region in war_plans.intel_requests(ctx):
            result_.append((other, WAR_KINDS, 'plan', 10.0))
    except Exception:
        pass
    for other in s.get('at_war', []):
        result_.append((other, WAR_KINDS, 'war', 8.0))
    for other in s.get('threats', []):
        result_.append((other, WAR_KINDS, 'threat', 4.0))
    if ctx.traits.get('espionage', 50) >= 60:
        for other in (ctx.world_summary().get('neighbor_countries') or [])[:4]:
            if other not in s.get('allies', []):
                result_.append((other, PEACE_KINDS, 'peace', -1.0))
    seen, ordered = set(), []
    for item in result_:
        if item[0] not in seen and item[0] != ctx.country_id:
            seen.add(item[0]); ordered.append(item)
    return ordered


def mission_options(ctx, session):
    from game.satellite_models import SpySatellite, SatelliteMission
    from game.satellites import settle, MISSION_COST, MISSIONS
    from game.finance_service import game_now
    settle(session, game_now(), ctx.country_id)
    idle = [sat for sat in session.scalars(select(SpySatellite).where(SpySatellite.panstwo_id == ctx.country_id,
                                                                     SpySatellite.status == 'orbit', SpySatellite.mode == 'drift').order_by(SpySatellite.id))]
    if not idle:
        return []
    since = (ctx.now or game_now()) - timedelta(days=REPEAT_DAYS)
    done = {(m.target_country_id, m.kind) for m in session.scalars(select(SatelliteMission).where(
        SatelliteMission.panstwo_id == ctx.country_id, SatelliteMission.starts_at >= since))}
    options, used = [], set()
    for sat in idle:
        for other, kinds, purpose, bonus in targets(ctx):
            kind = next((k for k in kinds if (other, k) not in done and (other, k) not in used), None)
            if kind is None:
                continue
            used.add((other, kind))
            options.append(Option(key=f'sat:mission:{sat.id}:{other}:{kind}', domain='intelligence', action='SATELLITE_MISSION',
                                  label=f'Rozpoznanie satelitarne ({MISSIONS[kind].lower()}) państwa {other} — satelita #{sat.id}',
                                  target=other, stance='neutral', cost=float(MISSION_COST), sector='security_services',
                                  effects={'intelligence': 1.0, 'offensive_army': .5 if purpose != 'peace' else 0,
                                           'defensive_army': .4 if purpose != 'peace' else 0, 'conquest': .3 if purpose in ('plan', 'war') else 0},
                                  traits={'espionage': .9, 'secrecy': .2}, base=bonus,
                                  notes=['Satelita rozpoznaje obiekty na całym terytorium państwa, zawsze skutecznie (kontrwywiad działa tylko na agentów).'],
                                  payload={'satellite_id': sat.id, 'kind': kind, 'country_id': other, 'group': f'sat:mission:{sat.id}'}))
            break                                       # jedna misja na satelitę w przebiegu
    return options


def propose(ctx):
    from game.satellites import tables_ready, summary
    from game.industry_service import researched
    from game.satellites import TECHNOLOGY
    with Session(db.engine) as session:
        if not tables_ready(session) or not researched(session, ctx.country_id, TECHNOLOGY):
            return []
        counts = summary(session, ctx.country_id)
        from game.nuclear_models import NuclearOrder
        from game.research_models import AmmunitionFactory
        from game.satellites import FACTORY_KIND
        producing = session.scalar(select(NuclearOrder.id).join(AmmunitionFactory, AmmunitionFactory.id == NuclearOrder.factory_id).where(
            NuclearOrder.panstwo_id == ctx.country_id, NuclearOrder.status == 'active', AmmunitionFactory.kind == FACTORY_KIND).limit(1))
        options = order_options(ctx, session, counts['total'] + (1 if producing else 0))
        options += launch_options(ctx, session)
        options += mission_options(ctx, session)
        session.rollback()                              # settle() tylko liczy — zapis robią trasy gry
    return options


def execute(ctx, option):
    p = option.payload
    if option.action == 'SATELLITE_ORDER':
        from game.paga2.industry import PATH as INDUSTRY
        status, data = ctx.call(INDUSTRY, json={'action': 'order', 'category': 'factory', 'object_id': p['factory_id'], 'count': p['count'], 'request_id': rid(ctx, option)})
    elif option.action == 'SATELLITE_LAUNCH':
        status, data = ctx.call(LAUNCH, json={'base_id': p['base_id'], 'request_id': rid(ctx, option)})
    elif option.action == 'SATELLITE_MISSION':
        status, data = ctx.call(MISSION, json={'satellite_id': p['satellite_id'], 'kind': p['kind'], 'country_id': p['country_id'], 'request_id': rid(ctx, option)})
    else:
        return {'status': 400, 'error': 'Nieznana operacja satelitarna.'}
    return result(status, data)


ADAPTER = register(Adapter(name='satellites', modes=('CYCLIC', 'IMMEDIATE'), propose=propose, execute=execute))
