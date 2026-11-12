"""Game ownership follows sovereignty; WIKI country and region records stay separate."""
from sqlalchemy import select
from sqlalchemy.orm import lazyload
from models import Panstwo, Wojsko


def controllers(session):
    actual = session() if callable(session) else session
    token = actual.get_transaction()
    cached = actual.info.get('game_controllers')
    if cached and cached[0] is token and token is not None:
        return cached[1]
    rows = {id: (sovereign, parent) for id, sovereign, parent in actual.execute(select(
        Panstwo.PANSTWO_ID, Panstwo.czy_suwerenny, Panstwo.zwierzch_panstwo_id))}
    result = {}
    for start in rows:
        current, seen = start, set()
        while current in rows and current not in seen:
            seen.add(current)
            sovereign, parent = rows[current]
            if sovereign == 'TAK':
                result[start] = current
                break
            if sovereign != 'NIE':
                break
            current = parent
        else:
            current = None
        result.setdefault(start, None)
    actual.info['game_controllers'] = (actual.get_transaction(), result)
    return result


def controller_id(session, country_id):
    return controllers(session).get(country_id)


def controlled_ids(session, country_id):
    """Only a sovereign assignment grants access; malformed dependencies fail closed."""
    mapping = controllers(session)
    if mapping.get(country_id) != country_id:
        return []
    return sorted(id for id, owner in mapping.items() if owner == country_id)


def economy(session, country_id):
    rows = session.execute(select(Panstwo.panstwo_populacja, Panstwo.panstwo_PKB,
        Panstwo.panstwo_powierzchnia).where(Panstwo.PANSTWO_ID.in_(controlled_ids(session, country_id)))).all()
    def total(index):
        values = [row[index] for row in rows]
        return sum(values) if values and all(value is not None for value in values) else None
    return dict(population=total(0), gdp=total(1), area=total(2))


class CombinedArmy:
    """Shared stock backed by original WIKI rows; consumption never duplicates units."""
    def __init__(self, rows, country_id):
        object.__setattr__(self, '_rows', rows)
        object.__setattr__(self, 'panstwo_id', country_id)

    def __getattr__(self, name):
        if name == 'procent_PKB':
            return next((row.procent_PKB for row in self._rows if row.panstwo_id == self.panstwo_id), None)
        if name in Wojsko.__table__.columns and name not in ('ID', 'panstwo_id'):
            return sum((getattr(row, name) or 0) for row in self._rows)
        raise AttributeError(name)

    def __setattr__(self, name, value):
        if name not in Wojsko.__table__.columns or name in ('ID', 'panstwo_id', 'procent_PKB'):
            raise AttributeError(name)
        delta = int(value) - getattr(self, name)
        if int(value) < 0:
            raise ValueError('Ujemny stan wojska.')
        if delta >= 0:
            setattr(self._rows[0], name, (getattr(self._rows[0], name) or 0) + delta)
        else:
            remaining = -delta
            for row in self._rows:
                taken = min(getattr(row, name) or 0, remaining)
                setattr(row, name, (getattr(row, name) or 0) - taken)
                remaining -= taken
                if not remaining:
                    break


def army_for_country(session, country_id, lock=False):
    query = select(Wojsko).options(lazyload('*')).where(
        Wojsko.panstwo_id.in_(controlled_ids(session, country_id))).order_by(Wojsko.panstwo_id)
    if lock:
        query = query.with_for_update()
    rows = list(session.scalars(query))
    rows.sort(key=lambda row: (row.panstwo_id != country_id, row.panstwo_id))
    if not rows:
        return None
    return rows[0] if len(rows) == 1 else CombinedArmy(rows, country_id)
