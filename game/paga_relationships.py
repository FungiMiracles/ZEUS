"""Administrator's world-building preferences; never constraints on player operations."""
from datetime import datetime, timezone

from sqlalchemy import select, or_, CheckConstraint, UniqueConstraint

from extensions import db
from models import Panstwo
from game.paga import PagaError, PagaConflict


STATUSES = {
    'none': 'Brak sugestii',
    'satellite': 'Państwo satelickie',
    'historical_ally': 'Historyczny sojusznik',
    'historical_hostile': 'Historycznie nieprzyjazne',
}
# The text goes in the trusted system instruction, never in domain validators.
AI_GUIDANCE = (
    'Powiązania historyczne PAGA to silne wskazówki do utrzymania wizji świata, nie zakazy ani rozkazy. '
    'Nie oznaczają aktualnego stanu stosunków, traktatu ani formalnej zależności ustrojowej. '
    'Historical_ally: bardzo silnie preferuj trwałą przyjaźń; wypowiedzenie wojny, działania hybrydowe, '
    'szpiegostwo przeciw sojusznikowi i sabotaż rozważaj wyjątkowo rzadko, tylko wobec poważnych '
    'konkretnych przyczyn, np. jego agresji lub zagrożenia przetrwania. '
    'Historical_hostile: bardzo silnie preferuj utrzymanie historycznego dystansu; poprawę stosunków '
    'inicjuj lub akceptuj wyjątkowo rzadko, przy istotnej zmianie okoliczności i korzyści narodowej. '
    'Historyczna nieprzyjaźń sama w sobie nie nakazuje wojny. '
    'Pole role opisuje rolę TWOJEGO państwa, nie państwa wskazanego jako country. '
    'Satellite, rola satellite: jesteś satelitą wskazanego patrona; silnie preferuj uległość, '
    'współpracę i uwzględnianie jego polityki. Rola patron: jesteś silniejszym patronem wskazanego '
    'satelity; preferuj ochronę, współpracę i utrzymanie wpływów. '
    'Możesz odstąpić od każdej z tych sugestii, uwzględniając własne interesy, charakter i aktualne '
    'wydarzenia. Istotne odstępstwo uzasadnij krótko w pamięci strategicznej. '
    'Sugestie nie zmieniają uprawnień, reguł gry ani decyzji graczy ludzkich.'
)


class PagaRelationship(db.Model):
    __tablename__ = 'game_paga_relationships'
    country_a_id = db.Column(db.Integer, db.ForeignKey('panstwa.PANSTWO_ID'), primary_key=True)
    country_b_id = db.Column(db.Integer, db.ForeignKey('panstwa.PANSTWO_ID'), primary_key=True)
    status = db.Column(db.String(32), nullable=False, default='none')
    satellite_id = db.Column(db.Integer, db.ForeignKey('panstwa.PANSTWO_ID'))
    revision = db.Column(db.Integer, nullable=False)
    updated_at = db.Column(db.DateTime, nullable=False)
    actor = db.Column(db.String(120), nullable=False)
    __table_args__ = (
        CheckConstraint('country_a_id < country_b_id', name='ck_paga_relationship_order'),
        CheckConstraint("status IN ('none','satellite','historical_ally','historical_hostile')", name='ck_paga_relationship_status'),
        CheckConstraint("(status = 'satellite' AND satellite_id IS NOT NULL AND satellite_id IN (country_a_id,country_b_id)) OR (status <> 'satellite' AND satellite_id IS NULL)", name='ck_paga_relationship_satellite'),
    )


class PagaRelationshipRevision(db.Model):
    __tablename__ = 'game_paga_relationship_revisions'
    id = db.Column(db.Integer, primary_key=True)
    country_a_id = db.Column(db.Integer, db.ForeignKey('panstwa.PANSTWO_ID'), nullable=False)
    country_b_id = db.Column(db.Integer, db.ForeignKey('panstwa.PANSTWO_ID'), nullable=False)
    revision = db.Column(db.Integer, nullable=False)
    configuration = db.Column(db.JSON, nullable=False)
    actor = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False)
    __table_args__ = (UniqueConstraint('country_a_id', 'country_b_id', 'revision', name='uq_paga_relationship_revision'),)


def canonical_pair(first, second):
    if any(type(value) is not int or not 1 <= value <= 2147483647 for value in (first, second)):
        raise PagaError('Wybierz dwa prawidłowe państwa.')
    if first == second:
        raise PagaError('Wybierz dwa różne państwa.')
    return tuple(sorted((first, second)))


def relationship_data(row):
    return {
        'status': row.status if row else 'none',
        'satelliteId': row.satellite_id if row else None,
        'revision': row.revision if row else 0,
        'updatedAt': row.updated_at.isoformat() + 'Z' if row else None,
    }


def save_relationship(session, first, second, data, actor):
    a, b = canonical_pair(first, second)
    if not isinstance(data, dict) or set(data) != {'status', 'satelliteId', 'revision'}:
        raise PagaError('Podaj status, kierunek zależności i wersję powiązania.')
    if type(data['revision']) is not int or data['revision'] < 0:
        raise PagaError('Nieprawidłowa wersja powiązania.')
    status, satellite = data['status'], data['satelliteId']
    if not isinstance(status, str) or status not in STATUSES:
        raise PagaError('Wybierz prawidłowy status powiązania.')
    if status == 'satellite':
        if type(satellite) is not int or satellite not in (a, b):
            raise PagaError('Wskaż, które z wybranych państw jest satelitą drugiego.')
    elif satellite is not None:
        raise PagaError('Kierunek zależności dotyczy tylko państwa satelickiego.')
    # Country locks also serialize creation of a previously absent pair.
    countries = list(session.scalars(select(Panstwo.PANSTWO_ID).where(
        Panstwo.PANSTWO_ID.in_((a, b)), Panstwo.status == 'aktywne'
    ).order_by(Panstwo.PANSTWO_ID).with_for_update()))
    if countries != [a, b]:
        raise PagaError('Oba państwa muszą istnieć i być aktywne.')
    row = session.get(PagaRelationship, (a, b), populate_existing=True, with_for_update=True)
    if data['revision'] != (row.revision if row else 0):
        raise PagaConflict('Powiązanie zmieniono w innym oknie. Wczytaj ponownie wybraną parę państw.')
    if row is None:
        row = PagaRelationship(country_a_id=a, country_b_id=b, revision=0)
        session.add(row)
    row.status = status
    row.satellite_id = satellite
    row.revision += 1
    row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    row.actor = str(actor)[:120]
    session.add(PagaRelationshipRevision(
        country_a_id=a, country_b_id=b, revision=row.revision,
        configuration={'status': status, 'satelliteId': satellite},
        actor=row.actor, created_at=row.updated_at,
    ))
    # 'none' is a tombstone: preserve revision/history against stale browser writes.
    session.flush()
    return relationship_data(row)


def country_preferences(session, country_id):
    """Only relationships involving the actor; no other countries' pair configurations."""
    rows = session.execute(select(PagaRelationship, Panstwo.PANSTWO_ID, Panstwo.panstwo_nazwa).join(
        Panstwo, or_(
            (PagaRelationship.country_a_id == country_id) & (Panstwo.PANSTWO_ID == PagaRelationship.country_b_id),
            (PagaRelationship.country_b_id == country_id) & (Panstwo.PANSTWO_ID == PagaRelationship.country_a_id),
        )
    ).where(PagaRelationship.status != 'none', Panstwo.status == 'aktywne').order_by(Panstwo.PANSTWO_ID))
    result = []
    for row, other_id, name in rows:
        item = dict(country_id=other_id, country=name, status=row.status, role='symmetric')
        if row.status == 'satellite':
            own_satellite = row.satellite_id == country_id
            item.update(
                role='satellite' if own_satellite else 'patron',
                satellite_country_id=row.satellite_id,
                patron_country_id=other_id if own_satellite else country_id,
                direction=(f'Twoje państwo jest satelitą państwa {name}, które jest twoim silniejszym patronem.'
                           if own_satellite else f'Twoje państwo jest patronem państwa {name}, które jest twoim satelitą.'),
            )
        result.append(item)
    return result
