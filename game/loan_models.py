"""Wnioski o pożyczkę i dwustronna historia ruchów rezerwy."""
from extensions import db
from game.models import utc_now


class StateLoan(db.Model):
    __tablename__='game_state_loans'
    id=db.Column(db.Integer,primary_key=True)
    borrower_id=db.Column(db.Integer,db.ForeignKey('panstwa.PANSTWO_ID'),nullable=False,index=True)
    lender_id=db.Column(db.Integer,db.ForeignKey('panstwa.PANSTWO_ID'),nullable=False,index=True)
    requested_by=db.Column(db.Integer,db.ForeignKey('game_users.id'),nullable=False)
    amount=db.Column(db.Numeric(30,2),nullable=False)
    status=db.Column(db.String(16),nullable=False,default='pending')
    request_id=db.Column(db.String(36),nullable=False)
    created_at=db.Column(db.DateTime,nullable=False,default=utc_now)
    resolved_at=db.Column(db.DateTime)
    __table_args__=(db.UniqueConstraint('borrower_id','request_id',name='uq_state_loan_request'),db.CheckConstraint("amount>0 AND borrower_id<>lender_id AND status IN ('pending','accepted','rejected','cancelled','repaid')",name='ck_state_loan_values'),{'mysql_engine':'InnoDB'})


class LoanMovement(db.Model):
    __tablename__='game_loan_movements'
    id=db.Column(db.Integer,primary_key=True)
    loan_id=db.Column(db.Integer,db.ForeignKey('game_state_loans.id'),nullable=False)
    panstwo_id=db.Column(db.Integer,db.ForeignKey('panstwa.PANSTWO_ID'),nullable=False,index=True)
    budget_id=db.Column(db.BigInteger,db.ForeignKey('game_state_budgets.id'),index=True)
    stage=db.Column(db.String(16),nullable=False)
    amount=db.Column(db.Numeric(30,2),nullable=False)
    created_at=db.Column(db.DateTime,nullable=False,default=utc_now)
    __table_args__=(db.UniqueConstraint('loan_id','panstwo_id','stage',name='uq_loan_movement'),db.CheckConstraint("amount<>0 AND stage IN ('disbursement','repayment')",name='ck_loan_movement'),{'mysql_engine':'InnoDB'})
