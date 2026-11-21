"""Tabele PAGA2 (UAT). Migracja: migrations/sql/paga2_foundation_20261111.py."""
from datetime import datetime,timezone
from extensions import db


def utc_now():return datetime.now(timezone.utc).replace(tzinfo=None)


_READY=set()
def table_ready(session,model):
    """Czy tabela PAGA2 istnieje (przed migracją kod działa jak dotąd). Zapamiętywane tylko pozytywne wyniki."""
    from sqlalchemy import inspect
    bind=session.get_bind();key=(id(bind),model.__tablename__)
    if key in _READY:return True
    if inspect(session.connection()).has_table(model.__tablename__):_READY.add(key);return True
    return False


class Paga2Control(db.Model):
    """Globalna konfiguracja PAGA2 (jeden wiersz, id=1). Domyślnie wyłączona."""
    __tablename__='game_paga2_control'
    __table_args__={'mysql_engine':'InnoDB'}
    id=db.Column(db.Integer,primary_key=True)
    enabled=db.Column(db.Boolean,nullable=False,default=False,server_default=db.text('0'))
    interval_minutes=db.Column(db.Integer,nullable=False,default=60,server_default=db.text('60'))
    revision=db.Column(db.Integer,nullable=False,default=0,server_default=db.text('0'))
    last_cycle_at=db.Column(db.DateTime)
    updated_at=db.Column(db.DateTime,nullable=False,default=utc_now)
    actor=db.Column(db.String(120),nullable=False,default='system')


class Paga2Profile(db.Model):
    """Profil państwa: ogólny charakter (≤3), uszeregowane priorytety, 25 cech 0–100 i flaga autonomii."""
    __tablename__='game_paga2_profiles'
    __table_args__={'mysql_engine':'InnoDB'}
    panstwo_id=db.Column(db.Integer,db.ForeignKey('panstwa.PANSTWO_ID'),primary_key=True)
    categories=db.Column(db.JSON,nullable=False)
    priorities=db.Column(db.JSON,nullable=False)
    traits=db.Column(db.JSON,nullable=False)
    autonomy_enabled=db.Column(db.Boolean,nullable=False,default=False,server_default=db.text('0'))
    source=db.Column(db.String(16),nullable=False,default='admin')  # 'migrated' = przeniesiony z PAGA, do przeglądu
    revision=db.Column(db.Integer,nullable=False,default=1)
    updated_at=db.Column(db.DateTime,nullable=False,default=utc_now)
    actor=db.Column(db.String(120),nullable=False)


class Paga2ProfileRevision(db.Model):
    __tablename__='game_paga2_profile_revisions'
    id=db.Column(db.Integer,primary_key=True)
    panstwo_id=db.Column(db.Integer,db.ForeignKey('panstwa.PANSTWO_ID'),nullable=False,index=True)
    revision=db.Column(db.Integer,nullable=False)
    configuration=db.Column(db.JSON,nullable=False)
    actor=db.Column(db.String(120),nullable=False)
    created_at=db.Column(db.DateTime,nullable=False,default=utc_now)
    __table_args__=(db.UniqueConstraint('panstwo_id','revision',name='uq_paga2_profile_revision'),{'mysql_engine':'InnoDB'})


class Paga2Decision(db.Model):
    """Historia decyzji: rozważone opcje z punktacją, dane wejściowe i wynik wykonania."""
    __tablename__='game_paga2_decisions'
    id=db.Column(db.Integer,primary_key=True)
    request_key=db.Column(db.String(160),nullable=False,unique=True)
    country_id=db.Column(db.Integer,db.ForeignKey('panstwa.PANSTWO_ID'),nullable=False,index=True)
    mode=db.Column(db.String(16),nullable=False)          # CYCLIC / IMMEDIATE / BUDGET
    trigger=db.Column(db.String(80),nullable=False)
    domain=db.Column(db.String(32),nullable=False,index=True)
    action=db.Column(db.String(60),nullable=False)
    target_id=db.Column(db.Integer)
    status=db.Column(db.String(16),nullable=False,index=True)  # EXECUTED / REJECTED / PASSIVE / ERROR
    score=db.Column(db.Float)
    options=db.Column(db.JSON,nullable=False)
    inputs=db.Column(db.JSON,nullable=False)
    result=db.Column(db.JSON)
    randomized=db.Column(db.Boolean,nullable=False,default=False)
    error=db.Column(db.Text)
    game_at=db.Column(db.DateTime,index=True)
    created_at=db.Column(db.DateTime,nullable=False,default=utc_now,index=True)
    __table_args__=({'mysql_engine':'InnoDB'},)


class Paga2RandomDraw(db.Model):
    """Każde wywołanie randomizera (rozstrzygnięcie konfliktu priorytetów)."""
    __tablename__='game_paga2_random_draws'
    id=db.Column(db.Integer,primary_key=True)
    country_id=db.Column(db.Integer,db.ForeignKey('panstwa.PANSTWO_ID'),nullable=False,index=True)
    decision_key=db.Column(db.String(160))
    reason=db.Column(db.String(200),nullable=False)
    candidates=db.Column(db.JSON,nullable=False)
    chosen=db.Column(db.String(120),nullable=False)
    created_at=db.Column(db.DateTime,nullable=False,default=utc_now,index=True)
    __table_args__=({'mysql_engine':'InnoDB'},)


# Mapowanie dotychczasowych interesów narodowych PAGA na profil PAGA2 (tylko do wstępnego wypełnienia).
LEGACY_INTERESTS={
    'world_hegemony':(['hegemonic'],['alliances','offensive_army']),
    'conquer_neighbors':(['imperialist'],['conquest','offensive_army']),
    'resources_economy':(['economic'],['production','trade']),
    'prosperity':(['welfare'],['welfare','infrastructure']),
    'internal_stability':([],['financial_stability','welfare']),
    'survival':(['isolationist'],['defensive_army']),
    'regional_hegemony':(['hegemonic'],['alliances','defensive_army']),
    'world_chaos':(['terrorist'],['intelligence']),
    'terrorism':(['terrorist'],['intelligence']),
}


def migrated_profile(config):
    """Profil PAGA2 z zatwierdzonej konfiguracji PAGA: kolejność aktywnych interesów wyznacza priorytety."""
    from game.paga2.catalog import default_profile,MAX_CATEGORIES
    categories=[];priorities=[]
    for item in config.approved_interests or []:
        if not item.get('active'):continue
        cats,prios=LEGACY_INTERESTS.get(item.get('key'),([],[]))
        categories+=[c for c in cats if c not in categories];priorities+=[p for p in prios if p not in priorities]
    return {'categories':categories[:MAX_CATEGORIES] or ['economic'],'priorities':priorities or ['financial_stability'],
            'traits':default_profile(config.approved_character),'autonomy_enabled':bool(config.autonomy_enabled)}


class Paga2CountryState(db.Model):
    """Stan harmonogramu PAGA2 dla państwa: ostatni cykl, kursory wyzwalaczy doraźnych i próby budżetu."""
    __tablename__='game_paga2_country_states'
    __table_args__={'mysql_engine':'InnoDB'}
    panstwo_id=db.Column(db.Integer,db.ForeignKey('panstwa.PANSTWO_ID'),primary_key=True)
    next_cycle_at=db.Column(db.DateTime)
    last_cycle_at=db.Column(db.DateTime)
    notification_cursor=db.Column(db.Integer,nullable=False,default=0,server_default=db.text('0'))
    message_cursor=db.Column(db.Integer,nullable=False,default=0,server_default=db.text('0'))
    event_cursor=db.Column(db.Integer,nullable=False,default=0,server_default=db.text('0'))
    budget_retry_at=db.Column(db.DateTime)
    last_error=db.Column(db.Text)
    updated_at=db.Column(db.DateTime,nullable=False,default=utc_now)


class Paga2Plan(db.Model):
    """Plan wieloetapowy: cel, priorytet, któremu służy, i ostatnio wyliczone kroki (przeliczane przy każdym przebiegu)."""
    __tablename__='game_paga2_plans'
    id=db.Column(db.Integer,primary_key=True)
    country_id=db.Column(db.Integer,db.ForeignKey('panstwa.PANSTWO_ID'),nullable=False,index=True)
    goal=db.Column(db.String(60),nullable=False)
    priority=db.Column(db.String(32))
    status=db.Column(db.String(16),nullable=False,index=True)   # ACTIVE / DONE / IMPOSSIBLE / ABANDONED
    steps=db.Column(db.JSON,nullable=False)
    reason=db.Column(db.Text)
    idle_cycles=db.Column(db.Integer,nullable=False,default=0,server_default=db.text('0'))
    created_at=db.Column(db.DateTime,nullable=False,default=utc_now)
    updated_at=db.Column(db.DateTime,nullable=False,default=utc_now)
    finished_at=db.Column(db.DateTime)
    game_created_at=db.Column(db.DateTime)
    __table_args__=({'mysql_engine':'InnoDB'},)


class Paga2WarPlan(db.Model):
    """21 Nov 2026: plan wojenny PAGA2 (game.paga2.war_plans) — cel, cele militarne, ocena gotowości w pięciu obszarach,
    etap (PLANNING → INTELLIGENCE → PREPARATION → READY → ACTIVE → NEGOTIATION → COMPLETED / ABANDONED) i historia.
    `active_key` = 'kraj:przeciwnik' dla planu w toku (NULL po zakończeniu) — unikalny: jeden plan na parę państw naraz."""
    __tablename__='game_paga2_war_plans'
    id=db.Column(db.Integer,primary_key=True)
    country_id=db.Column(db.Integer,db.ForeignKey('panstwa.PANSTWO_ID'),nullable=False,index=True)
    enemy_id=db.Column(db.Integer,nullable=False,index=True)
    kind=db.Column(db.String(16),nullable=False,default='OFFENSIVE')        # OFFENSIVE / ALLY_SUPPORT
    ally_id=db.Column(db.Integer)
    stage=db.Column(db.String(16),nullable=False,index=True)
    active_key=db.Column(db.String(40),unique=True)
    reason=db.Column(db.Text,nullable=False)
    goal=db.Column(db.JSON,nullable=False)            # {type, label, region_id?, target_ids?}
    extra_goals=db.Column(db.JSON,nullable=False)
    targets=db.Column(db.JSON,nullable=False)         # [{kind, id, region, label}]
    assessment=db.Column(db.JSON,nullable=False)      # {areas:{combat,reach,finance,supply,intel}, own, enemy, risk, notes}
    readiness=db.Column(db.Float,nullable=False,default=0)
    shortfalls=db.Column(db.JSON,nullable=False)
    history=db.Column(db.JSON,nullable=False)         # [{at, text}]
    intel_attempts=db.Column(db.Integer,nullable=False,default=0,server_default=db.text('0'))
    stale_cycles=db.Column(db.Integer,nullable=False,default=0,server_default=db.text('0'))   # przeglądy bez postępu przygotowań
    idle_cycles=db.Column(db.Integer,nullable=False,default=0,server_default=db.text('0'))    # cykle wojenne bez skutecznej operacji
    first_operation_pending=db.Column(db.Boolean,nullable=False,default=False,server_default=db.text('0'))
    first_operation_attempts=db.Column(db.Integer,nullable=False,default=0,server_default=db.text('0'))
    operations=db.Column(db.Integer,nullable=False,default=0,server_default=db.text('0'))
    power_at_start=db.Column(db.Float)
    declared_at=db.Column(db.DateTime)                # czas gry
    last_operation_at=db.Column(db.DateTime)          # czas gry
    end_reason=db.Column(db.Text)
    game_created_at=db.Column(db.DateTime)
    created_at=db.Column(db.DateTime,nullable=False,default=utc_now)
    updated_at=db.Column(db.DateTime,nullable=False,default=utc_now)
    finished_at=db.Column(db.DateTime)
    __table_args__=({'mysql_engine':'InnoDB'},)
