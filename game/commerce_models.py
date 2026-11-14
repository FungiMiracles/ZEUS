"""Wydobycie, fizyczny magazyn, oferty i transport towarów."""
from extensions import db
from game.models import utc_now


class ResourceStock(db.Model):
    __tablename__='game_resource_stocks'
    panstwo_id=db.Column(db.Integer,db.ForeignKey('panstwa.PANSTWO_ID'),primary_key=True)
    resource=db.Column(db.String(32),primary_key=True)
    quantity=db.Column(db.Numeric(30,0),nullable=False,default=0)
    __table_args__=(db.CheckConstraint('quantity >= 0',name='ck_resource_stock_quantity'),{'mysql_engine':'InnoDB'})


class Mine(db.Model):
    __tablename__='game_mines'
    level=db.Column(db.Integer,nullable=False,default=1,server_default=db.text('1'))
    removed_at=db.Column(db.DateTime)
    investment=db.Column(db.Numeric(29,2),nullable=False,default=0,server_default=db.text('0'))
    id=db.Column(db.Integer,primary_key=True)
    panstwo_id=db.Column(db.Integer,db.ForeignKey('panstwa.PANSTWO_ID'),nullable=False,index=True)
    region_id=db.Column(db.Integer,db.ForeignKey('regiony.region_id'),nullable=False,index=True)
    resource=db.Column(db.String(32),nullable=False)
    map_x=db.Column(db.Double,nullable=False)
    map_y=db.Column(db.Double,nullable=False)
    health=db.Column(db.Integer,nullable=False,default=100,server_default=db.text('100'))
    starts_at=db.Column(db.DateTime,nullable=False)
    ready_at=db.Column(db.DateTime,nullable=False,index=True)
    extracted_at=db.Column(db.DateTime,nullable=False,index=True)
    request_id=db.Column(db.String(36),nullable=False)
    __table_args__=(db.UniqueConstraint('panstwo_id','request_id',name='uq_mine_request'),db.CheckConstraint('health BETWEEN 0 AND 100 AND ready_at > starts_at AND extracted_at >= ready_at',name='ck_mine_values'),{'mysql_engine':'InnoDB'})


class MiningExpense(db.Model):
    __tablename__='game_mining_expenses'
    id=db.Column(db.Integer,primary_key=True)
    panstwo_id=db.Column(db.Integer,nullable=False)
    budget_id=db.Column(db.BigInteger,db.ForeignKey('game_state_budgets.id'),nullable=False,index=True)
    mine_id=db.Column(db.Integer,db.ForeignKey('game_mines.id',ondelete='SET NULL'))
    amount=db.Column(db.Numeric(30,2),nullable=False)
    __table_args__=(db.CheckConstraint('amount > 0',name='ck_mining_expense_amount'),{'mysql_engine':'InnoDB'})


class PortTariff(db.Model):
    __tablename__='game_port_tariffs'
    panstwo_id=db.Column(db.Integer,db.ForeignKey('panstwa.PANSTWO_ID'),primary_key=True)
    rate=db.Column(db.Numeric(5,2),nullable=False,default=0)
    block_foreign=db.Column(db.Boolean,nullable=False,default=False,server_default=db.text('0'))
    blocked_countries=db.Column(db.JSON,nullable=False,default=list)
    __table_args__=(db.CheckConstraint('rate BETWEEN 0 AND 100',name='ck_port_tariff_rate'),{'mysql_engine':'InnoDB'})


class TradeOffer(db.Model):
    __tablename__='game_trade_offers'
    id=db.Column(db.Integer,primary_key=True)
    panstwo_id=db.Column(db.Integer,db.ForeignKey('panstwa.PANSTWO_ID'),nullable=False,index=True)
    user_id=db.Column(db.Integer,db.ForeignKey('game_users.id'),nullable=False)
    cargo=db.Column(db.JSON,nullable=False)
    price=db.Column(db.Numeric(30,2),nullable=False)
    excluded=db.Column(db.JSON,nullable=False,default=list)
    port_id=db.Column(db.Integer,db.ForeignKey('miasta.miasto_id'),nullable=False)
    port_country_id=db.Column(db.Integer,nullable=False)
    departure_rate=db.Column(db.Numeric(5,2),nullable=False)
    status=db.Column(db.String(16),nullable=False,default='open',index=True)
    request_id=db.Column(db.String(36),nullable=False)
    created_at=db.Column(db.DateTime,nullable=False,default=utc_now)
    # 13 Nov 2026: czas gry wystawienia i ostatniej zmiany ceny (wycofanie po 14 dniach Entendy, obniżki ceny PAGA2)
    created_game_at=db.Column(db.DateTime,nullable=True,index=True)
    price_changed_game_at=db.Column(db.DateTime,nullable=True)
    __table_args__=(db.UniqueConstraint('panstwo_id','request_id',name='uq_trade_offer_request'),db.CheckConstraint("price > 0 AND status IN ('open','sold','cancelled')",name='ck_trade_offer_values'),{'mysql_engine':'InnoDB'})


class TradeShipment(db.Model):
    __tablename__='game_trade_shipments'
    origin_country_id=db.Column(db.Integer,nullable=True)
    route=db.Column(db.JSON,nullable=True)
    health=db.Column(db.Integer,nullable=False,default=100,server_default=db.text('100'))
    sunk_at=db.Column(db.DateTime,nullable=True)
    id=db.Column(db.Integer,primary_key=True)
    offer_id=db.Column(db.Integer,db.ForeignKey('game_trade_offers.id'),nullable=False,unique=True)
    seller_id=db.Column(db.Integer,nullable=False,index=True)
    buyer_id=db.Column(db.Integer,db.ForeignKey('panstwa.PANSTWO_ID'),nullable=False,index=True)
    cargo=db.Column(db.JSON,nullable=False)
    departure_port_id=db.Column(db.Integer,db.ForeignKey('miasta.miasto_id'),nullable=False)
    arrival_port_id=db.Column(db.Integer,db.ForeignKey('miasta.miasto_id'),nullable=False)
    departure_fee=db.Column(db.Numeric(30,2),nullable=False)
    arrival_fee=db.Column(db.Numeric(30,2),nullable=False)
    source_x=db.Column(db.Double,nullable=False)
    source_y=db.Column(db.Double,nullable=False)
    target_x=db.Column(db.Double,nullable=False)
    target_y=db.Column(db.Double,nullable=False)
    distance_km=db.Column(db.Double,nullable=False)
    starts_at=db.Column(db.DateTime,nullable=False)
    arrives_at=db.Column(db.DateTime,nullable=False,index=True)
    delivered_at=db.Column(db.DateTime)
    request_id=db.Column(db.String(36),nullable=False)
    __table_args__=(db.UniqueConstraint('buyer_id','request_id',name='uq_trade_shipment_request'),db.CheckConstraint('health BETWEEN 0 AND 100',name='ck_trade_ship_health'),db.CheckConstraint('distance_km >= 0 AND departure_fee >= 0 AND arrival_fee >= 0 AND arrives_at > starts_at',name='ck_trade_shipment_values'),{'mysql_engine':'InnoDB'})


class TradeReserveMovement(db.Model):
    __tablename__='game_trade_reserve_movements'
    id=db.Column(db.Integer,primary_key=True)
    panstwo_id=db.Column(db.Integer,nullable=False,index=True)
    budget_id=db.Column(db.BigInteger,db.ForeignKey('game_state_budgets.id'),index=True)
    shipment_id=db.Column(db.Integer,db.ForeignKey('game_trade_shipments.id'),nullable=False)
    amount=db.Column(db.Numeric(30,2),nullable=False)
    created_at=db.Column(db.DateTime,nullable=False,default=utc_now)
    __table_args__=(db.UniqueConstraint('shipment_id','panstwo_id',name='uq_trade_reserve_movement'),db.CheckConstraint('amount <> 0',name='ck_trade_reserve_amount'),{'mysql_engine':'InnoDB'})
