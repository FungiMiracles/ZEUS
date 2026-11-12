"""Versioned administrative configuration for future autonomous governments."""
from datetime import datetime,timezone
from sqlalchemy import select
from extensions import db

TRAITS={'agreeableness':'Ugodowość','predictability':'Przewidywalność','militarism':'Militaryzm','provocation':'Prowokacyjność','isolationism':'Izolacjonizm','revenge':'Rewanżyzm','ambition':'Ambicja'}
INTERESTS={'world_hegemony':'Światowa hegemonia','conquer_neighbors':'Podbój sąsiadów','resources_economy':'Wydobycie surowców i gospodarka','prosperity':'Budowa dobrobytu','internal_stability':'Stabilność wewnętrzna','survival':'Przetrwanie','regional_hegemony':'Hegemonia regionalna','world_chaos':'Sianie chaosu na świecie','terrorism':'Terroryzm'}


class PagaConfiguration(db.Model):
    __tablename__='game_paga_configurations'
    panstwo_id=db.Column(db.Integer,db.ForeignKey('panstwa.PANSTWO_ID'),primary_key=True)
    revision=db.Column(db.Integer,nullable=False)
    approved_character=db.Column(db.JSON)
    approved_interests=db.Column(db.JSON)
    approved_at=db.Column(db.DateTime)
    autonomy_enabled=db.Column(db.Boolean,nullable=False,default=False,server_default=db.text("0"))
    draft_autonomy_enabled=db.Column(db.Boolean)
    draft_character=db.Column(db.JSON)
    draft_interests=db.Column(db.JSON)
    draft_updated_at=db.Column(db.DateTime)
    updated_at=db.Column(db.DateTime,nullable=False)
    actor=db.Column(db.String(120),nullable=False)


class PagaRevision(db.Model):
    __tablename__='game_paga_revisions'
    id=db.Column(db.Integer,primary_key=True)
    panstwo_id=db.Column(db.Integer,db.ForeignKey('panstwa.PANSTWO_ID'),nullable=False,index=True)
    revision=db.Column(db.Integer,nullable=False)
    mode=db.Column(db.String(16),nullable=False)
    configuration=db.Column(db.JSON,nullable=False)
    actor=db.Column(db.String(120),nullable=False)
    created_at=db.Column(db.DateTime,nullable=False)
    __table_args__=(db.UniqueConstraint('panstwo_id','revision',name='uq_paga_revision'),)


class PagaError(ValueError):pass
class PagaConflict(PagaError):pass


def approved_country_ids(session):
    return set(session.scalars(select(PagaConfiguration.panstwo_id).where(PagaConfiguration.approved_at.is_not(None))))


def enabled_country_ids(session):
    """Approved configurations whose administrator has enabled autonomy."""
    return set(session.scalars(select(PagaConfiguration.panstwo_id).where(PagaConfiguration.approved_at.is_not(None),PagaConfiguration.autonomy_enabled.is_(True))))


def configuration_data(row):
    character={key:None for key in TRAITS}
    interests=[{'key':key,'active':False} for key in INTERESTS]
    if row:
        character=row.draft_character if row.draft_updated_at else row.approved_character
        interests=row.draft_interests if row.draft_updated_at else row.approved_interests
    return {'revision':row.revision if row else 0,'character':character,'interests':interests,
            'autonomyEnabled':bool(row.draft_autonomy_enabled if row and row.draft_updated_at else row.autonomy_enabled if row else False),
            'approvedAutonomyEnabled':bool(row and row.approved_at and row.autonomy_enabled),
            'approvedAt':row.approved_at.isoformat()+'Z' if row and row.approved_at else None,
            'draftUpdatedAt':row.draft_updated_at.isoformat()+'Z' if row and row.draft_updated_at else None}


def validate_configuration(data):
    if not isinstance(data,dict) or data.get('mode') not in ('draft','approve'):raise PagaError('Wybierz zapis roboczy lub zatwierdzenie.')
    if type(data.get('revision')) is not int or data['revision']<0:raise PagaError('Nieprawidłowa wersja konfiguracji.')
    if 'autonomyEnabled' in data and type(data['autonomyEnabled']) is not bool:raise PagaError('Autonomia musi mieć wartość Włączona lub Wyłączona.')
    character=data.get('character');interests=data.get('interests')
    if not isinstance(character,dict) or set(character)!=set(TRAITS):raise PagaError('Przekaż wszystkie cechy charakteru państwa.')
    for key,value in character.items():
        if value is None and data['mode']=='draft':continue
        if type(value) is not int or not 0<=value<=100:raise PagaError(f'{TRAITS[key]}: podaj liczbę całkowitą od 0 do 100.')
    if not isinstance(interests,list) or len(interests)!=len(INTERESTS):raise PagaError('Hierarchia musi zawierać wszystkie interesy narodowe.')
    keys=[]
    for item in interests:
        if not isinstance(item,dict) or set(item)!={'key','active'} or not isinstance(item['key'],str) or type(item['active']) is not bool:raise PagaError('Nieprawidłowy interes narodowy.')
        keys.append(item['key'])
    if set(keys)!=set(INTERESTS) or len(set(keys))!=len(keys):raise PagaError('Interesy narodowe nie mogą się powtarzać ani znikać z hierarchii.')
    if data['mode']=='approve' and not any(item['active'] for item in interests):raise PagaError('Aktywuj co najmniej jeden interes narodowy.')
    return character,interests


def save_configuration(session,country_id,data,actor):
    from models import Panstwo
    character,interests=validate_configuration(data)
    country=session.scalar(select(Panstwo.PANSTWO_ID).where(Panstwo.PANSTWO_ID==country_id,Panstwo.status=='aktywne').with_for_update())
    if country is None:raise PagaError('Nie znaleziono aktywnego państwa.')
    row=session.get(PagaConfiguration,country_id)
    if data['revision']!=(row.revision if row else 0):raise PagaConflict('Konfiguracja została zmieniona w innym oknie. Wybierz ponownie państwo, aby wczytać aktualne dane.')
    now=datetime.now(timezone.utc).replace(tzinfo=None);actor=str(actor)[:120]
    if row is None:row=PagaConfiguration(panstwo_id=country_id,revision=0);session.add(row)
    autonomy=data.get("autonomyEnabled",configuration_data(row)["autonomyEnabled"])
    row.revision+=1;row.updated_at=now;row.actor=actor
    if data['mode']=='approve':
        row.autonomy_enabled=autonomy;row.draft_autonomy_enabled=None
        row.approved_character=character;row.approved_interests=interests;row.approved_at=now
        row.draft_character=None;row.draft_interests=None;row.draft_updated_at=None
    else:
        row.draft_autonomy_enabled=autonomy
        row.draft_character=character;row.draft_interests=interests;row.draft_updated_at=now
    session.add(PagaRevision(panstwo_id=country_id,revision=row.revision,mode=data['mode'],configuration={'character':character,'interests':interests,'autonomyEnabled':autonomy},actor=actor,created_at=now))
    session.flush();return configuration_data(row)
