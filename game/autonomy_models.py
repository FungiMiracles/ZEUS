"""Durable UAT autonomy state. No scheduler or schema changes on import."""
from extensions import db

class AutonomyControl(db.Model):
    __tablename__='game_autonomy_control'
    __table_args__={'mysql_engine':'InnoDB'}
    id=db.Column(db.Integer,primary_key=True)
    enabled=db.Column(db.Boolean,nullable=False,default=True)
    revision=db.Column(db.Integer,nullable=False,default=0)
    max_actions=db.Column(db.Integer,nullable=False,default=3)
    window_days=db.Column(db.Integer,nullable=False,default=30)
    cooldown_days=db.Column(db.Integer,nullable=False,default=7)
    max_chain_depth=db.Column(db.Integer,nullable=False,default=2)
    started_at=db.Column(db.DateTime,nullable=False)
    updated_actor=db.Column(db.String(120))

class AutonomySchedule(db.Model):
    __tablename__='game_autonomy_schedules'
    __table_args__={'mysql_engine':'InnoDB'}
    country_id=db.Column(db.Integer,db.ForeignKey('panstwa.PANSTWO_ID'),primary_key=True)
    next_at=db.Column(db.DateTime,nullable=False,index=True)
    last_at=db.Column(db.DateTime)
    last_error=db.Column(db.Text)

class AutonomyEvent(db.Model):
    __tablename__='game_autonomy_events'
    __table_args__={'mysql_engine':'InnoDB'}
    id=db.Column(db.Integer,primary_key=True)
    source_key=db.Column(db.String(100),nullable=False,unique=True)
    kind=db.Column(db.String(40),nullable=False)
    actor_id=db.Column(db.Integer)
    target_id=db.Column(db.Integer)
    occurred_at=db.Column(db.DateTime,nullable=False,index=True)
    public=db.Column(db.Boolean,nullable=False)
    audience=db.Column(db.JSON,nullable=False)
    private_country_id=db.Column(db.Integer,index=True)
    payload=db.Column(db.JSON,nullable=False)
    depth=db.Column(db.Integer,nullable=False,default=0)
    root_id=db.Column(db.Integer)

class AutonomySourceReceipt(db.Model):
    __tablename__='game_autonomy_source_receipts'
    __table_args__={'mysql_engine':'InnoDB'}
    source=db.Column(db.String(32),primary_key=True)
    source_id=db.Column(db.Integer,primary_key=True)
    context=db.Column(db.JSON)

class AutonomyMemory(db.Model):
    __tablename__='game_autonomy_memories'
    __table_args__={'mysql_engine':'InnoDB'}
    country_id=db.Column(db.Integer,db.ForeignKey('panstwa.PANSTWO_ID'),primary_key=True)
    event_id=db.Column(db.Integer,db.ForeignKey('game_autonomy_events.id'),primary_key=True)
    other_id=db.Column(db.Integer)
    importance=db.Column(db.Float,nullable=False)
    trust_delta=db.Column(db.Float,nullable=False)
    threat_delta=db.Column(db.Float,nullable=False)
    confidence=db.Column(db.Float,nullable=False)

class AutonomyAssessment(db.Model):
    __tablename__='game_autonomy_assessments'
    __table_args__={'mysql_engine':'InnoDB'}
    country_id=db.Column(db.Integer,db.ForeignKey('panstwa.PANSTWO_ID'),primary_key=True)
    other_id=db.Column(db.Integer,primary_key=True)
    trust=db.Column(db.Float,nullable=False)
    threat=db.Column(db.Float,nullable=False)
    confidence=db.Column(db.Float,nullable=False)
    updated_at=db.Column(db.DateTime,nullable=False)

class AutonomyReaction(db.Model):
    __tablename__='game_autonomy_reactions'
    __table_args__={'mysql_engine':'InnoDB'}
    country_id=db.Column(db.Integer,db.ForeignKey('panstwa.PANSTWO_ID'),primary_key=True)
    event_id=db.Column(db.Integer,db.ForeignKey('game_autonomy_events.id'),primary_key=True)
    ready_at=db.Column(db.DateTime,nullable=False,index=True)
    status=db.Column(db.String(16),nullable=False,default='READY',index=True)
    error=db.Column(db.Text)

class AutonomyAnalysis(db.Model):
    __tablename__='game_autonomy_analyses'
    __table_args__={'mysql_engine':'InnoDB'}
    id=db.Column(db.Integer,primary_key=True)
    request_key=db.Column(db.String(120),nullable=False,unique=True)
    country_id=db.Column(db.Integer,db.ForeignKey('panstwa.PANSTWO_ID'),nullable=False,index=True)
    game_at=db.Column(db.DateTime,nullable=False,index=True)
    trigger=db.Column(db.String(16),nullable=False)
    event_id=db.Column(db.Integer,db.ForeignKey('game_autonomy_events.id'))
    action=db.Column(db.String(40),nullable=False,index=True)
    target_id=db.Column(db.Integer)
    score=db.Column(db.Float)
    status=db.Column(db.String(16),nullable=False)
    factors=db.Column(db.JSON,nullable=False)
    candidates=db.Column(db.JSON,nullable=False)
    result=db.Column(db.JSON)
    error=db.Column(db.Text)
