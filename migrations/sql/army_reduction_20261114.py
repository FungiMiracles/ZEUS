"""Jednorazowa redukcja uzbrojenia państw (UAT only, 14 Nov 2026, na polecenie administratora).

    venv/bin/python migrations/sql/army_reduction_20261114.py            # podgląd (bez zapisu)
    venv/bin/python migrations/sql/army_reduction_20261114.py --apply    # zapis

Zasady (liczba docelowa nigdy nie przekracza obecnej — redukcja, bez dodawania):
- okręty wojenne i myśliwce: 0 zostaje 0; ≥1 → 1, wyjątki: Ozilandia bez zmian, Hopia 4,
  Tunganiria/Rannisjaon/Sajstan/Dahader/Jowia/Prewaria/Nopalia 3;
- czołgi: najwyżej 25; wozy opancerzone: najwyżej 25;
- okręty podwodne: ≥1 → 1; lotniskowce: ≥1 → 1 (Ozilandia bez zmian);
- broń atomowa: 0 (licznik w tabeli wojsko, magazyn rakiet z głowicą i silosy).

Licznik w tabeli „wojsko” to całość posiadanych jednostek; ich część jest w garnizonach baz, armiach lądowych
(w marszu, obronie miast, okupacji) i okrętach na morzu. Redukcja zabiera najpierw z wolnej puli, potem z garnizonów
(od największego), potem z armii; nadmiarowe okręty (w rejsie i w porcie) są oznaczane jako zatopione, tak jak przy
zniszczeniu bazy. Kopia zmienianych wierszy: backups/army_reduction_20261114/ (pliki 0600). Skrypt jest idempotentny.
"""
from pathlib import Path
import json, os, sys
from datetime import datetime, timezone
from sqlalchemy import select, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]
APPLY = '--apply' in sys.argv

SPECIAL = {'Ozilandia': None, 'Hopia': 4, 'Tunganiria': 3, 'Rannisjaon': 3, 'Sajstan': 3, 'Dahader': 3, 'Jowia': 3, 'Prewaria': 3, 'Nopalia': 3}
LIVE_ARMY = ('MARCHING', 'DEFENDING', 'OCCUPYING')
ACTIVE_VESSEL = ('sailing', 'stationed', 'returning')


def make_app():
    import contextlib, io
    from unittest.mock import patch
    assert ROOT == Path('/home/oskar_zeus_admin/ZEUS_UAT'); sys.path.insert(0, str(ROOT))
    settings = dict(line.split('=', 1) for line in (ROOT / '.env.uat').read_text().splitlines() if line and not line.startswith('#') and '=' in line)
    for key, value in settings.items(): os.environ[key] = value.strip().strip('"\'')
    os.environ['ENV_NAME'] = 'UAT'
    assert make_url(os.environ['DATABASE_URL']).database == 'entenda_uat_db', 'Migracja wyłącznie dla bazy UAT.'
    with contextlib.redirect_stdout(io.StringIO()), patch('engine.generator.start_event_scheduler'), \
            patch('engine.infrastructure_scheduler.start_infrastructure_scheduler'), patch('engine.finance_scheduler.start_finance_scheduler'):
        from zeus_app import app
    return app


def plain(row, columns):
    out = {}
    for column in columns:
        value = getattr(row, column)
        out[column] = value.isoformat() if hasattr(value, 'isoformat') else (int(value) if hasattr(value, 'as_integer_ratio') and not isinstance(value, float) else value)
    return out


def main():
    app = make_app()
    from extensions import db
    from models import Wojsko, Panstwo
    from game.military_models import MilitaryBase, MilitaryVessel
    from game.land_war_models import LandArmy
    from game.commerce_models import ResourceStock
    from game.nuclear import STOCK_CODE
    with app.app_context():
        session = db.session
        assert session.execute(text('SELECT DATABASE()')).scalar() == 'entenda_uat_db'
        names = dict(session.execute(select(Panstwo.PANSTWO_ID, Panstwo.panstwo_nazwa)).all())
        by_name = {name: id for id, name in names.items()}
        missing = [name for name in SPECIAL if name not in by_name]
        assert not missing, f'Nie znaleziono państw: {missing}'
        special = {by_name[name]: target for name, target in SPECIAL.items()}
        ozilandia = by_name['Ozilandia']

        armies_rows = list(session.scalars(select(Wojsko).order_by(Wojsko.panstwo_id).with_for_update()))
        bases = list(session.scalars(select(MilitaryBase).order_by(MilitaryBase.id).with_for_update()))
        vessels = list(session.scalars(select(MilitaryVessel).where(MilitaryVessel.status.in_(ACTIVE_VESSEL + ('docked',))).order_by(MilitaryVessel.id).with_for_update()))
        land_armies = list(session.scalars(select(LandArmy).where(LandArmy.status.in_(LIVE_ARMY)).order_by(LandArmy.id).with_for_update()))
        stocks = list(session.scalars(select(ResourceStock).where(ResourceStock.resource == STOCK_CODE).with_for_update()))

        backup = {'created_at': datetime.now(timezone.utc).isoformat(),
                  'wojsko': [plain(r, ['panstwo_id', 'okrety_wojenne_ilosc', 'mysliwce_ilosc', 'czolgi_ilosc', 'wozy_opancerzone_ilosc', 'okrety_podwodne_ilosc', 'lotniskowce_ilosc', 'bron_atomowa_ilosc']) for r in armies_rows],
                  'bases': [{'id': b.id, 'panstwo_id': b.panstwo_id, 'kind': b.kind, 'garrison': dict(b.garrison or {})} for b in bases],
                  'vessels': [plain(v, ['id', 'panstwo_id', 'kind', 'status', 'health', 'base_id', 'fighters', 'air_base_id']) for v in vessels],
                  'land_armies': [plain(a, ['id', 'panstwo_id', 'status', 'soldiers', 'armored', 'tanks']) for a in land_armies],
                  'nuclear_stocks': [{'panstwo_id': s.panstwo_id, 'quantity': int(s.quantity)} for s in stocks]}

        report = []
        def note(country, text_):report.append(f'{names.get(country, country)}: {text_}')

        def target_for(country, kind, current):
            if current <= 0:return 0
            if kind in ('warships', 'fighters'):
                if country in special:
                    goal = special[country]
                    return current if goal is None else min(current, goal)
                return 1
            if kind in ('tanks', 'armored'):return min(current, 25)
            if kind == 'submarines':return 1
            if kind == 'carriers':return current if country == ozilandia else 1
            raise ValueError(kind)

        fields = {'warships': 'okrety_wojenne_ilosc', 'fighters': 'mysliwce_ilosc', 'tanks': 'czolgi_ilosc', 'armored': 'wozy_opancerzone_ilosc',
                  'submarines': 'okrety_podwodne_ilosc', 'carriers': 'lotniskowce_ilosc'}
        sunk = 0
        for army in armies_rows:
            country = army.panstwo_id
            own_bases = [b for b in bases if b.panstwo_id == country]
            for kind, field in fields.items():
                current = int(getattr(army, field) or 0)
                goal = target_for(country, kind, current)
                if kind == 'carriers':
                    active = [v for v in vessels if v.panstwo_id == country and v.kind == 'carriers' and v.status in ACTIVE_VESSEL]
                    for vessel in active[goal:]:
                        if vessel.air_base_id:
                            base = next((b for b in own_bases if b.id == vessel.air_base_id), None)
                            if base:base.garrison = {**base.garrison, 'fighters': max(0, int(base.garrison.get('fighters', 0)) - (vessel.fighters or 0))}
                        vessel.status = 'sunk';vessel.health = 0;vessel.fighters = 0;sunk += 1
                        note(country, f'lotniskowiec #{vessel.id} wycofany')
                    if goal != current:note(country, f'lotniskowce {current} → {goal}');setattr(army, field, goal)
                    continue
                garrisoned = sum(int((b.garrison or {}).get(kind, 0) or 0) for b in own_bases)
                in_armies = sum(int(getattr(a, kind) or 0) for a in land_armies if a.panstwo_id == country) if kind in ('tanks', 'armored') else 0
                ships = [v for v in vessels if v.panstwo_id == country and v.kind == kind] if kind in ('warships', 'submarines') else []
                nobase = [v for v in ships if v.base_id is None and v.status in ACTIVE_VESSEL]
                held = garrisoned + in_armies + len(nobase)
                if goal == current and held <= goal:continue
                # Okręty w rejsie bez bazy macierzystej (liczone poza garnizonem)
                keep = goal
                for vessel in nobase:
                    if keep > 0:keep -= 1;continue
                    vessel.status = 'sunk';vessel.health = 0;sunk += 1
                # Garnizony: najpierw zachowujemy okręty w rejsie (zajęte), redukcja od największego garnizonu
                budget = keep
                if kind in ('warships', 'submarines'):
                    at_sea = {b.id: [v for v in ships if v.base_id == b.id and v.status in ACTIVE_VESSEL] for b in own_bases}
                    plan = {b.id: 0 for b in own_bases}
                    for b in sorted(own_bases, key=lambda b: -len(at_sea[b.id])):   # okręty w rejsie mają pierwszeństwo
                        take = min(budget, len(at_sea[b.id]), int((b.garrison or {}).get(kind, 0) or 0));plan[b.id] += take;budget -= take
                    for b in sorted(own_bases, key=lambda b: -int((b.garrison or {}).get(kind, 0) or 0)):
                        room = int((b.garrison or {}).get(kind, 0) or 0) - plan[b.id];take = min(budget, max(0, room));plan[b.id] += take;budget -= take
                    for b in own_bases:
                        old = int((b.garrison or {}).get(kind, 0) or 0)
                        if old == plan[b.id]:continue
                        b.garrison = {**b.garrison, kind: plan[b.id]}
                        sea = at_sea[b.id];keep_sea = min(len(sea), plan[b.id])
                        for vessel in sea[keep_sea:]:vessel.status = 'sunk';vessel.health = 0;sunk += 1
                        docked = [v for v in ships if v.base_id == b.id and v.status == 'docked']
                        for vessel in docked[max(0, plan[b.id] - keep_sea):]:vessel.status = 'sunk';vessel.health = 0;sunk += 1
                        note(country, f'{kind} w bazie #{b.id}: {old} → {plan[b.id]}')
                else:
                    plan = {}
                    for b in sorted(own_bases, key=lambda b: -int((b.garrison or {}).get(kind, 0) or 0)):
                        old = int((b.garrison or {}).get(kind, 0) or 0)
                        reserved = sum(v.fighters or 0 for v in vessels if kind == 'fighters' and v.air_base_id == b.id and v.status in ACTIVE_VESSEL)
                        take = min(old, max(budget, min(old, reserved)) if reserved else budget);plan[b.id] = take;budget -= take
                    for b in own_bases:
                        old = int((b.garrison or {}).get(kind, 0) or 0)
                        if b.id in plan and plan[b.id] != old:
                            b.garrison = {**b.garrison, kind: plan[b.id]};note(country, f'{kind} w bazie #{b.id}: {old} → {plan[b.id]}')
                    if kind in ('tanks', 'armored'):
                        for unit in sorted((a for a in land_armies if a.panstwo_id == country), key=lambda a: -int(getattr(a, kind) or 0)):
                            old = int(getattr(unit, kind) or 0);new = min(old, max(0, budget));budget -= new
                            if new != old:setattr(unit, kind, new);note(country, f'{kind} w armii #{unit.id} ({unit.status}): {old} → {new}')
                new_total = max(goal, 0)
                if new_total != current:note(country, f'{kind} {current} → {new_total}');setattr(army, field, new_total)
            if army.bron_atomowa_ilosc:note(country, f'broń atomowa {army.bron_atomowa_ilosc} → 0');army.bron_atomowa_ilosc = 0
        for stock in stocks:
            if stock.quantity:note(stock.panstwo_id, f'rakiety z głowicą nuklearną {int(stock.quantity)} → 0');stock.quantity = 0
        for b in bases:
            if b.kind == 'nuclear' and int((b.garrison or {}).get('warheads', 0) or 0):
                note(b.panstwo_id, f'głowice w silosie #{b.id} → 0');b.garrison = {**b.garrison, 'warheads': 0}

        print('\n'.join(report))
        print(f'--- zmian: {len(report)}, okrętów oznaczonych jako zatopione: {sunk}')
        if not APPLY:
            session.rollback();print('PODGLĄD — nic nie zapisano. Uruchom z --apply, aby zapisać.');return
        folder = ROOT / 'backups' / 'army_reduction_20261114';folder.mkdir(parents=True, exist_ok=True)
        path = folder / ('before_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.json')
        path.write_text(json.dumps(backup, ensure_ascii=False, indent=1, default=str));os.chmod(path, 0o600)
        session.commit()
        print(f'ZAPISANO. Kopia stanu sprzed zmian: {path}')


if __name__ == '__main__':
    main()
