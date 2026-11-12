from extensions import db
from game.models import utc_now
class IndustryClock(db.Model):
    __tablename__='game_industry_clocks'
    panstwo_id=db.Column(db.Integer,db.ForeignKey('panstwa.PANSTWO_ID'),primary_key=True)
    settled_at=db.Column(db.DateTime,nullable=False)
class IndustryMovement(db.Model):
    __tablename__='game_industry_movements'
    id=db.Column(db.Integer,primary_key=True)
    panstwo_id=db.Column(db.Integer,nullable=False,index=True)
    budget_id=db.Column(db.BigInteger,db.ForeignKey('game_state_budgets.id'),nullable=False,index=True)
    amount=db.Column(db.Numeric(29,2),nullable=False)
    request_id=db.Column(db.String(36),nullable=False)
    payload=db.Column(db.JSON,nullable=False)
    created_at=db.Column(db.DateTime,nullable=False,default=utc_now)
    # Budget sector charged by the movement (filters are paid from 'environment', since 10 Nov 2026).
    sector=db.Column(db.String(32),nullable=False,default='infrastructure',server_default='infrastructure')
    __table_args__=(db.UniqueConstraint('panstwo_id','request_id',name='uq_industry_request'),{'mysql_engine':'InnoDB'})
class PowerPlant(db.Model):
    __tablename__='game_power_plants'
    id=db.Column(db.Integer,primary_key=True)
    panstwo_id=db.Column(db.Integer,db.ForeignKey('panstwa.PANSTWO_ID'),nullable=False,index=True)
    region_id=db.Column(db.Integer,db.ForeignKey('regiony.region_id'),nullable=False)
    kind=db.Column(db.String(16),nullable=False)
    level=db.Column(db.Integer,nullable=False,default=1)
    health=db.Column(db.Integer,nullable=False,default=3)
    map_x=db.Column(db.Double,nullable=False)
    map_y=db.Column(db.Double,nullable=False)
    investment=db.Column(db.Numeric(29,2),nullable=False)
    created_game_at=db.Column(db.DateTime,nullable=False)
    removed_at=db.Column(db.DateTime)
    checked_at=db.Column(db.DateTime,nullable=False)
    running=db.Column(db.Boolean,nullable=False,default=False)
    ever_worked=db.Column(db.Boolean,nullable=False,default=False)
    # Pollution filter (coal plants) and the air pollution points this plant actually added to its region.
    air_filter=db.Column(db.Boolean,nullable=False,default=False,server_default=db.text('0'))
    pollution_points=db.Column(db.Integer,nullable=False,default=0,server_default=db.text('0'))
    __table_args__=(db.CheckConstraint('health BETWEEN 0 AND 3 AND level BETWEEN 1 AND 3',name='ck_power_values'),{'mysql_engine':'InnoDB'})
