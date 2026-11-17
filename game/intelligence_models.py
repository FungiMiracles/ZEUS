"""Agenci, misje, raporty i wydatki wywiadu wojskowego."""
from extensions import db
from game.models import utc_now


class IntelligenceAgent(db.Model):
    __tablename__='game_intelligence_agents'
    id=db.Column(db.Integer,primary_key=True)
    panstwo_id=db.Column(db.Integer,db.ForeignKey('panstwa.PANSTWO_ID'),nullable=False,index=True)
    captured_at=db.Column(db.DateTime)
    name=db.Column(db.String(100))
    level=db.Column(db.Integer,nullable=False)
    created_at=db.Column(db.DateTime,nullable=False,default=utc_now)
    __table_args__=(db.CheckConstraint('level BETWEEN 1 AND 7',name='ck_intelligence_agent_level'),{'mysql_engine':'InnoDB'})


class CounterIntelligence(db.Model):
    __tablename__='game_counterintelligence'
    panstwo_id=db.Column(db.Integer,db.ForeignKey('panstwa.PANSTWO_ID'),primary_key=True)
    level=db.Column(db.Integer,nullable=False,default=1)
    __table_args__=(db.CheckConstraint('level BETWEEN 1 AND 7',name='ck_counterintelligence_level'),{'mysql_engine':'InnoDB'})


class IntelligenceMission(db.Model):
    __tablename__='game_intelligence_missions'
    id=db.Column(db.Integer,primary_key=True)
    panstwo_id=db.Column(db.Integer,db.ForeignKey('panstwa.PANSTWO_ID'),nullable=False,index=True)
    agent_id=db.Column(db.Integer,db.ForeignKey('game_intelligence_agents.id'),nullable=False)
    region_id=db.Column(db.Integer,db.ForeignKey('regiony.region_id'),nullable=True)
    target_country_id=db.Column(db.Integer,nullable=False)
    region_name=db.Column(db.String(255),nullable=False)
    kind=db.Column(db.String(24),nullable=False)
    starts_at=db.Column(db.DateTime,nullable=False)
    ends_at=db.Column(db.DateTime,nullable=False,index=True)
    completed_at=db.Column(db.DateTime)
    success=db.Column(db.Boolean)
    effective_chance=db.Column(db.Integer)
    report=db.Column(db.JSON)
    notification_id=db.Column(db.Integer,db.ForeignKey('game_notifications.id'),unique=True)
    __table_args__=(db.CheckConstraint("(kind = 'warehouses' AND region_id IS NULL) OR (kind <> 'warehouses' AND region_id IS NOT NULL)",name='ck_intelligence_mission_scope'),db.CheckConstraint('ends_at > starts_at',name='ck_intelligence_mission_time'),
        db.CheckConstraint("kind IN ('bases','defenses','nuclear','resources','infrastructure','silos','mines','cyber_energy','cyber_rail','cyber_port','arson','rail_explosive','power','warehouses')",name='ck_intelligence_mission_kind'),
        db.Index('ix_intelligence_mission_due','completed_at','ends_at'),{'mysql_engine':'InnoDB'})


class IntelligenceExpense(db.Model):
    __tablename__='game_intelligence_expenses'
    id=db.Column(db.Integer,primary_key=True)
    panstwo_id=db.Column(db.Integer,nullable=False,index=True)
    budget_id=db.Column(db.BigInteger,db.ForeignKey('game_state_budgets.id'),nullable=False,index=True)
    amount=db.Column(db.Numeric(30,2),nullable=False)
    request_id=db.Column(db.String(36),nullable=False)
    payload=db.Column(db.JSON,nullable=False)
    created_at=db.Column(db.DateTime,nullable=False,default=utc_now)
    __table_args__=(db.UniqueConstraint('panstwo_id','request_id',name='uq_intelligence_expense_request'),
        db.CheckConstraint('amount > 0',name='ck_intelligence_expense_amount'),{'mysql_engine':'InnoDB'})
