"""Drogi i audytowane korekty finansów przez administratora WIKI."""
from extensions import db
from game.models import utc_now


class Road(db.Model):
    __tablename__='game_roads'
    id=db.Column(db.Integer,primary_key=True)
    panstwo_id=db.Column(db.Integer,db.ForeignKey('panstwa.PANSTWO_ID'),nullable=False,index=True)
    kind=db.Column(db.String(16),nullable=False)
    start_x=db.Column(db.Double,nullable=False)
    start_y=db.Column(db.Double,nullable=False)
    end_x=db.Column(db.Double,nullable=False)
    end_y=db.Column(db.Double,nullable=False)
    path=db.Column(db.JSON)
    distance_km=db.Column(db.Numeric(16,3),nullable=False)
    cost=db.Column(db.Numeric(30,2),nullable=False)
    budget_id=db.Column(db.BigInteger,db.ForeignKey('game_state_budgets.id'),index=True)
    user_id=db.Column(db.Integer,db.ForeignKey('game_users.id'))
    admin_actor=db.Column(db.String(120))
    request_id=db.Column(db.String(36),nullable=False)
    created_at=db.Column(db.DateTime,nullable=False,default=utc_now)
    __table_args__=(db.UniqueConstraint('panstwo_id','request_id',name='uq_road_request'),db.CheckConstraint("kind IN ('motorway','national') AND distance_km>0 AND cost>=0",name='ck_road_values'),{'mysql_engine':'InnoDB'})


class TreasuryAdjustment(db.Model):
    __tablename__='game_treasury_adjustments'
    id=db.Column(db.Integer,primary_key=True)
    panstwo_id=db.Column(db.Integer,db.ForeignKey('panstwa.PANSTWO_ID'),nullable=False,index=True)
    budget_id=db.Column(db.BigInteger,db.ForeignKey('game_state_budgets.id'),index=True)
    category=db.Column(db.String(48),nullable=False)
    amount=db.Column(db.Numeric(30,2),nullable=False)
    admin_actor=db.Column(db.String(120),nullable=False)
    reason=db.Column(db.String(500),nullable=False)
    request_id=db.Column(db.String(36),nullable=False,unique=True)
    policy_before=db.Column(db.JSON)
    policy_after=db.Column(db.JSON)
    created_at=db.Column(db.DateTime,nullable=False,default=utc_now)
    __table_args__=({'mysql_engine':'InnoDB'},)


class CountryTaxPolicy(db.Model):
    __tablename__='game_country_tax_policies'
    panstwo_id=db.Column(db.Integer,db.ForeignKey('panstwa.PANSTWO_ID'),primary_key=True)
    pit_rate=db.Column(db.Numeric(5,2),nullable=False)
    cit_rate=db.Column(db.Numeric(5,2),nullable=False)
    version=db.Column(db.Integer,nullable=False,default=1)
    __table_args__=(db.CheckConstraint('pit_rate BETWEEN 0 AND 100 AND cit_rate BETWEEN 0 AND 100',name='ck_country_tax_policy'),{'mysql_engine':'InnoDB'})


class RoadInvestment(db.Model):
    __tablename__='game_road_investments'
    id=db.Column(db.Integer,primary_key=True)
    panstwo_id=db.Column(db.Integer,db.ForeignKey('panstwa.PANSTWO_ID'),nullable=False,index=True)
    budget_id=db.Column(db.BigInteger,db.ForeignKey('game_state_budgets.id'),index=True)
    road_id=db.Column(db.Integer,db.ForeignKey('game_roads.id'),nullable=False)
    amount=db.Column(db.Numeric(30,2),nullable=False)
    request_id=db.Column(db.String(36),nullable=False)
    created_at=db.Column(db.DateTime,nullable=False,default=utc_now)
    __table_args__=(db.UniqueConstraint('panstwo_id','request_id',name='uq_road_investment_request'),db.CheckConstraint('amount>=0',name='ck_road_investment_amount'),{'mysql_engine':'InnoDB'})


class RoadProposal(db.Model):
    __tablename__='game_road_proposals'
    id=db.Column(db.Integer,primary_key=True)
    initiator_id=db.Column(db.Integer,db.ForeignKey('panstwa.PANSTWO_ID'),nullable=False,index=True)
    partner_id=db.Column(db.Integer,db.ForeignKey('panstwa.PANSTWO_ID'),nullable=False,index=True)
    kind=db.Column(db.String(16),nullable=False)
    path=db.Column(db.JSON,nullable=False)
    control_points=db.Column(db.JSON)
    shares=db.Column(db.JSON,nullable=False)
    total_cost=db.Column(db.Numeric(30,2),nullable=False)
    status=db.Column(db.String(20),nullable=False,default='pending')
    request_id=db.Column(db.String(36),nullable=False)
    created_at=db.Column(db.DateTime,nullable=False,default=utc_now)
    resolved_at=db.Column(db.DateTime)
    __table_args__=(db.UniqueConstraint('initiator_id','request_id',name='uq_road_proposal_request'),db.CheckConstraint("status IN ('pending','accepted','rejected','border_built','cancelled') AND initiator_id<>partner_id",name='ck_road_proposal_state'),{'mysql_engine':'InnoDB'})
