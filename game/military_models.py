"""Rozmieszczenie baz, garnizonów i wydatki wojskowe gry."""
from extensions import db
from game.models import utc_now


class MilitaryBase(db.Model):
    __tablename__ = 'game_military_bases'
    deployment_request_id=db.Column(db.String(36))
    deployment_payload=db.Column(db.JSON)
    id = db.Column(db.Integer, primary_key=True)
    panstwo_id = db.Column(db.Integer, db.ForeignKey('panstwa.PANSTWO_ID'), nullable=False, index=True)
    region_id = db.Column(db.Integer, db.ForeignKey('regiony.region_id'), nullable=False, index=True)
    kind = db.Column(db.String(16), nullable=False)
    name = db.Column(db.String(120))
    operational = db.Column(db.Boolean, nullable=False, default=True, server_default=db.text('1'))
    level = db.Column(db.Integer, nullable=False, default=1)
    garrison = db.Column(db.JSON, nullable=False, default=dict)
    map_x = db.Column(db.Double)
    map_y = db.Column(db.Double)
    health = db.Column(db.Integer, nullable=False, default=100, server_default=db.text("100"))
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    __table_args__ = (db.CheckConstraint("kind IN ('land','air','naval','nuclear')"), db.CheckConstraint('level BETWEEN 1 AND 7'), db.CheckConstraint('health BETWEEN 0 AND 100',name='ck_military_base_health'), db.CheckConstraint('(map_x IS NULL AND map_y IS NULL) OR (map_x IS NOT NULL AND map_y IS NOT NULL)',name='ck_military_base_position'), {'mysql_engine':'InnoDB'})


class MilitaryExpense(db.Model):
    __tablename__ = 'game_military_expenses'
    id = db.Column(db.Integer, primary_key=True)
    panstwo_id = db.Column(db.Integer, nullable=False, index=True)
    budget_id = db.Column(db.BigInteger, nullable=False, index=True)
    base_id = db.Column(db.Integer, db.ForeignKey('game_military_bases.id',ondelete='SET NULL'), nullable=True)
    level = db.Column(db.Integer, nullable=False)
    amount = db.Column(db.Numeric(30,2), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    __table_args__ = (db.UniqueConstraint('base_id','level',name='uq_military_base_upgrade'), db.CheckConstraint('amount >= 0'), {'mysql_engine':'InnoDB'})


class MilitaryMaintenance(db.Model):
    __tablename__ = 'game_military_maintenance'
    id = db.Column(db.Integer, primary_key=True)
    panstwo_id = db.Column(db.Integer, nullable=False, index=True)
    game_year = db.Column(db.Integer, nullable=False)
    period = db.Column(db.Integer, nullable=False)
    budget_id = db.Column(db.BigInteger, index=True)
    amount = db.Column(db.Numeric(30,2), nullable=False)
    assessed_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    __table_args__ = (db.UniqueConstraint('panstwo_id','game_year','period',name='uq_military_maintenance_period'),db.CheckConstraint('amount >= 0'),{'mysql_engine':'InnoDB'})


class MilitaryOrder(db.Model):
    __tablename__ = 'game_military_orders'
    id = db.Column(db.Integer, primary_key=True)
    panstwo_id = db.Column(db.Integer, nullable=False, index=True)
    user_id = db.Column(db.Integer, nullable=False)
    region_id = db.Column(db.Integer, nullable=False)
    kind = db.Column(db.String(16), nullable=False)
    payload = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    __table_args__ = (db.CheckConstraint("kind IN ('air','missile','naval','land')"),{'mysql_engine':'InnoDB'})



class MapCalibration(db.Model):
    __tablename__ = 'game_map_calibration'
    id = db.Column(db.Integer, primary_key=True)
    reference_city_a = db.Column(db.Integer, nullable=False)
    reference_city_b = db.Column(db.Integer, nullable=False)
    reference_km = db.Column(db.Double, nullable=False)
    km_per_unit = db.Column(db.Double, nullable=False)
    reference_a_x = db.Column(db.Double, nullable=False)
    reference_a_y = db.Column(db.Double, nullable=False)
    reference_b_x = db.Column(db.Double, nullable=False)
    reference_b_y = db.Column(db.Double, nullable=False)
    __table_args__ = (db.CheckConstraint('reference_km > 0 AND km_per_unit > 0'), {'mysql_engine':'InnoDB'})


class MilitaryFlight(db.Model):
    __tablename__ = 'game_military_flights'
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('game_military_orders.id'), nullable=False, unique=True)
    panstwo_id = db.Column(db.Integer, nullable=False, index=True)
    target_country_id = db.Column(db.Integer, nullable=False, index=True)
    source_base_id = db.Column(db.Integer, db.ForeignKey('game_military_bases.id',ondelete='SET NULL'), nullable=True)
    target_base_id = db.Column(db.Integer, db.ForeignKey('game_military_bases.id',ondelete='SET NULL'))
    target_defense_id = db.Column(db.Integer, db.ForeignKey('game_missile_defenses.id',ondelete='SET NULL'))
    target_power_id = db.Column(db.Integer,db.ForeignKey('game_power_plants.id',ondelete='SET NULL'))
    target_radar_id = db.Column(db.Integer,db.ForeignKey('game_radars.id',ondelete='SET NULL'))
    target_factory_id = db.Column(db.Integer,db.ForeignKey('game_ammunition_factories.id',ondelete='SET NULL'))
    target_shipment_id = db.Column(db.Integer,db.ForeignKey('game_trade_shipments.id',ondelete='SET NULL'))
    target_mine_id = db.Column(db.Integer, db.ForeignKey('game_mines.id',ondelete='SET NULL'))
    target_vessel_id = db.Column(db.Integer, db.ForeignKey('game_military_vessels.id'))
    intercepted = db.Column(db.Integer, nullable=False, default=0, server_default=db.text('0'))
    damage = db.Column(db.JSON)
    source_vessel_id = db.Column(db.Integer, db.ForeignKey('game_military_vessels.id'))
    is_nuclear = db.Column(db.Boolean, nullable=False, default=False, server_default=db.text('0'))
    city_id = db.Column(db.Integer, db.ForeignKey('miasta.miasto_id'))
    target_kind = db.Column(db.String(16), nullable=False, default='region',server_default=db.text("'region'"))
    target_name = db.Column(db.String(255), nullable=False, default="")
    kind = db.Column(db.String(16), nullable=False)
    missile_type = db.Column(db.String(16), nullable=False)
    missiles = db.Column(db.Integer, nullable=False)
    source_x = db.Column(db.Double, nullable=False)
    source_y = db.Column(db.Double, nullable=False)
    target_x = db.Column(db.Double, nullable=False)
    target_y = db.Column(db.Double, nullable=False)
    distance_km = db.Column(db.Double, nullable=False)
    starts_at = db.Column(db.DateTime, nullable=False)
    impact_at = db.Column(db.DateTime, nullable=False, index=True)
    fighter_arrives_at = db.Column(db.DateTime)
    returns_at = db.Column(db.DateTime)
    impacted_at = db.Column(db.DateTime)
    returned_at = db.Column(db.DateTime)
    casualties = db.Column(db.Integer)
    __table_args__ = (db.CheckConstraint('missiles > 0 AND distance_km >= 0'),db.CheckConstraint('casualties IS NULL OR casualties >= 0'), db.Index('ix_flight_impact_due','impacted_at','impact_at'),db.Index('ix_flight_return_due','returned_at','returns_at'), {'mysql_engine':'InnoDB'})


class MilitaryVessel(db.Model):
    __tablename__ = 'game_military_vessels'
    id = db.Column(db.Integer, primary_key=True)
    panstwo_id = db.Column(db.Integer, db.ForeignKey('panstwa.PANSTWO_ID'), nullable=False, index=True)
    base_id = db.Column(db.Integer, db.ForeignKey('game_military_bases.id',ondelete='SET NULL'), nullable=True, index=True)
    kind = db.Column(db.String(16), nullable=False)
    name = db.Column(db.String(120))
    health = db.Column(db.Integer, nullable=False, default=100, server_default=db.text('100'))
    status = db.Column(db.String(16), nullable=False, default='sailing')
    source_x = db.Column(db.Double, nullable=False)
    source_y = db.Column(db.Double, nullable=False)
    target_x = db.Column(db.Double, nullable=False)
    target_y = db.Column(db.Double, nullable=False)
    starts_at = db.Column(db.DateTime, nullable=False)
    arrives_at = db.Column(db.DateTime, nullable=False, index=True)
    region_id = db.Column(db.Integer)
    return_base_id = db.Column(db.Integer, db.ForeignKey('game_military_bases.id',ondelete='SET NULL'))
    # Lotniskowiec (12 Nov 2026): myśliwce zarezerwowane w bazie powietrznej air_base_id (najwyżej 5).
    fighters = db.Column(db.Integer, nullable=False, default=0, server_default=db.text('0'))
    air_base_id = db.Column(db.Integer, db.ForeignKey('game_military_bases.id',ondelete='SET NULL'))
    __table_args__ = (db.CheckConstraint("kind IN ('warships','submarines','carriers')",name='ck_vessel_kind'),
        db.CheckConstraint("status IN ('sailing','stationed','returning','docked','sunk')",name='ck_vessel_status'), db.CheckConstraint('health BETWEEN 0 AND 100',name='ck_vessel_health'), {'mysql_engine':'InnoDB'})


class MissileDefense(db.Model):
    __tablename__ = 'game_missile_defenses'
    id = db.Column(db.Integer, primary_key=True)
    panstwo_id = db.Column(db.Integer, db.ForeignKey('panstwa.PANSTWO_ID'), nullable=False, index=True)
    region_id = db.Column(db.Integer, db.ForeignKey('regiony.region_id'), nullable=False, index=True)
    target_kind = db.Column(db.String(16), nullable=False)
    target_id = db.Column(db.Integer, nullable=False)
    level = db.Column(db.Integer, nullable=False, default=1)
    health = db.Column(db.Integer, nullable=False, default=100, server_default=db.text('100'))
    ammunition = db.Column(db.Integer, nullable=False, default=100)
    __table_args__ = (db.UniqueConstraint('target_kind','target_id',name='uq_missile_defense_target'),
        db.CheckConstraint("target_kind IN ('region','city','base','mine','factory','power','radar')",name='ck_missile_defense_kind'),
        db.CheckConstraint('health BETWEEN 0 AND 100',name='ck_missile_defense_health'),
        db.CheckConstraint('level BETWEEN 1 AND 7 AND ammunition BETWEEN 0 AND 10000',name='ck_missile_defense_values'),{'mysql_engine':'InnoDB'})


class MissileDefenseExpense(db.Model):
    __tablename__ = 'game_missile_defense_expenses'
    id = db.Column(db.Integer, primary_key=True)
    panstwo_id = db.Column(db.Integer, nullable=False, index=True)
    budget_id = db.Column(db.BigInteger, nullable=False, index=True)
    defense_id = db.Column(db.Integer, db.ForeignKey('game_missile_defenses.id',ondelete='SET NULL'), nullable=True)
    amount = db.Column(db.Numeric(30,2), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    __table_args__ = (db.CheckConstraint('amount >= 0',name='ck_missile_defense_expense'),{'mysql_engine':'InnoDB'})


# Radar tables are referenced by MilitaryFlight.target_radar_id (11 Nov 2026).
from game import radar_models  # noqa: E402,F401
