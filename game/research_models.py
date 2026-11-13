"""Country research balances, durable investments and ammunition production."""
from extensions import db
from game.models import utc_now

class ResearchAccount(db.Model):
    __tablename__='game_research_accounts'
    panstwo_id=db.Column(db.Integer,db.ForeignKey('panstwa.PANSTWO_ID'),primary_key=True)
    points=db.Column(db.BigInteger,nullable=False,default=0)
    ammunition=db.Column(db.BigInteger,nullable=False,default=0)
    nodes=db.Column(db.JSON,nullable=False,default=dict)
    timers=db.Column(db.JSON)   # 13 Nov 2026: {technologia: {started, ready}} — czas rozwoju (game/research_timing)
    __table_args__=(db.CheckConstraint('points>=0 AND ammunition>=0',name='ck_research_balances'),{'mysql_engine':'InnoDB'})

class ResearchExpense(db.Model):
    __tablename__='game_research_expenses'
    id=db.Column(db.Integer,primary_key=True)
    panstwo_id=db.Column(db.Integer,db.ForeignKey('panstwa.PANSTWO_ID'),nullable=False,index=True)
    budget_id=db.Column(db.BigInteger,db.ForeignKey('game_state_budgets.id'),nullable=False,index=True)
    amount=db.Column(db.Numeric(29,2),nullable=False)
    points=db.Column(db.BigInteger,nullable=False)
    request_id=db.Column(db.String(36),nullable=False)
    created_at=db.Column(db.DateTime,nullable=False,default=utc_now)
    __table_args__=(db.UniqueConstraint('panstwo_id','request_id',name='uq_research_purchase'),db.CheckConstraint('amount>0 AND points>0',name='ck_research_expense'),{'mysql_engine':'InnoDB'})

class ResearchInvestment(db.Model):
    __tablename__='game_research_investments'
    id=db.Column(db.Integer,primary_key=True)
    panstwo_id=db.Column(db.Integer,db.ForeignKey('panstwa.PANSTWO_ID'),nullable=False,index=True)
    node=db.Column(db.String(32),nullable=False)
    points=db.Column(db.BigInteger,nullable=False)
    request_id=db.Column(db.String(36),nullable=False)
    created_at=db.Column(db.DateTime,nullable=False,default=utc_now)
    __table_args__=(db.UniqueConstraint('panstwo_id','request_id',name='uq_research_investment'),{'mysql_engine':'InnoDB'})

class AmmunitionFactory(db.Model):
    __tablename__='game_ammunition_factories'
    kind=db.Column(db.String(32),nullable=False,default='interceptor_ammo',server_default='interceptor_ammo')
    paused=db.Column(db.Boolean,nullable=False,default=False,server_default=db.text('0'))
    removed_at=db.Column(db.DateTime)
    production_progress=db.Column(db.Integer,nullable=False,default=0,server_default=db.text('0'))
    cycle_days=db.Column(db.Integer,nullable=False,default=0,server_default=db.text('0'))
    running=db.Column(db.Boolean,nullable=False,default=False,server_default=db.text('0'))
    ever_worked=db.Column(db.Boolean,nullable=False,default=False,server_default=db.text('0'))
    health=db.Column(db.Integer,nullable=False,default=100,server_default=db.text('100'))
    destroyed_at=db.Column(db.DateTime,nullable=True)
    # Waste filter and the environmental degradation points this factory actually added to its region (10 Nov 2026).
    waste_filter=db.Column(db.Boolean,nullable=False,default=False,server_default=db.text('0'))
    degradation_points=db.Column(db.Integer,nullable=False,default=0,server_default=db.text('0'))
    id=db.Column(db.Integer,primary_key=True)
    panstwo_id=db.Column(db.Integer,db.ForeignKey('panstwa.PANSTWO_ID'),nullable=False,index=True)
    region_id=db.Column(db.Integer,db.ForeignKey('regiony.region_id'),nullable=False)
    budget_id=db.Column(db.BigInteger,db.ForeignKey('game_state_budgets.id'),nullable=False,index=True)
    map_x=db.Column(db.Double,nullable=False)
    map_y=db.Column(db.Double,nullable=False)
    level=db.Column(db.Integer,nullable=False,default=1)
    cost=db.Column(db.Numeric(29,2),nullable=False)
    produced_at=db.Column(db.DateTime,nullable=False)
    created_game_at=db.Column(db.DateTime,nullable=False)
    request_id=db.Column(db.String(36),nullable=False)
    __table_args__=(db.CheckConstraint('health BETWEEN 0 AND 100',name='ck_factory_health'),db.UniqueConstraint('panstwo_id','request_id',name='uq_ammunition_factory'),{'mysql_engine':'InnoDB'})
