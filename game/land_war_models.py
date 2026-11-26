"""Wojska lądowe poza bazami: obrona miast, inwazje (przemarsz + bitwa) oraz okupacje (UAT, 11 Nov 2026).

Jedna armia = jeden wiersz LandArmy. Jednostki armii nadal należą do zasobów państwa (Wojsko) i są liczone jako
zajęte (active_counts), dopóki armia istnieje; polegli są odejmowani od zasobów państwa.
"""
from extensions import db
from game.models import utc_now


class LandArmy(db.Model):
    __tablename__ = 'game_land_armies'
    id = db.Column(db.Integer, primary_key=True)
    panstwo_id = db.Column(db.Integer, db.ForeignKey('panstwa.PANSTWO_ID'), nullable=False, index=True)
    user_id = db.Column(db.Integer, nullable=True)
    request_id = db.Column(db.String(36), nullable=False)
    # invasion: przemarsz do celu; city_defense: obrona własnego miasta; intercept: przechwycenie wrogiej armii w marszu (22 Nov 2026)
    role = db.Column(db.String(16), nullable=False)
    # MARCHING -> (bitwa) OCCUPYING / DESTROYED; DEFENDING (obrona miasta); WITHDRAWN (powrót do bazy); MERGED (wcielona po aneksji/odbiciu)
    status = db.Column(db.String(16), nullable=False, index=True)
    source_base_id = db.Column(db.Integer, db.ForeignKey('game_military_bases.id', ondelete='SET NULL'))
    soldiers = db.Column(db.BigInteger, nullable=False, default=0)
    armored = db.Column(db.BigInteger, nullable=False, default=0)
    tanks = db.Column(db.BigInteger, nullable=False, default=0)
    target_kind = db.Column(db.String(8), nullable=False)          # base / city / army (przechwycenie)
    target_army_id = db.Column(db.Integer, db.ForeignKey('game_land_armies.id', ondelete='SET NULL'))   # 22 Nov 2026
    target_base_id = db.Column(db.Integer, db.ForeignKey('game_military_bases.id', ondelete='SET NULL'))
    target_city_id = db.Column(db.Integer, db.ForeignKey('miasta.miasto_id'))
    target_country_id = db.Column(db.Integer, nullable=False)
    target_region_id = db.Column(db.Integer, nullable=False)
    target_name = db.Column(db.String(255), nullable=False, default='')
    source_x = db.Column(db.Double)
    source_y = db.Column(db.Double)
    target_x = db.Column(db.Double)
    target_y = db.Column(db.Double)
    # 26 Nov 2026: droga przemarszu po lądzie [[x, y], …] (game.land_routes); NULL — armie sprzed zmiany (odcinek prosty)
    route = db.Column(db.JSON)
    distance_km = db.Column(db.Double, nullable=False, default=0)
    speed_kmh = db.Column(db.Integer, nullable=False, default=0)
    starts_at = db.Column(db.DateTime, nullable=False)
    border_at = db.Column(db.DateTime)
    border_notified = db.Column(db.Boolean, nullable=False, default=False, server_default=db.text('0'))
    arrives_at = db.Column(db.DateTime, nullable=False, index=True)
    resolved_at = db.Column(db.DateTime)
    cost = db.Column(db.Numeric(30, 2), nullable=False, default=0)
    budget_id = db.Column(db.BigInteger, db.ForeignKey('game_state_budgets.id'), nullable=True, index=True)
    battle = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    __table_args__ = (db.UniqueConstraint('panstwo_id', 'request_id', name='uq_land_army_request'),
                      db.CheckConstraint('soldiers >= 0 AND armored >= 0 AND tanks >= 0', name='ck_land_army_units'),
                      db.CheckConstraint("role IN ('invasion','city_defense','intercept')", name='ck_land_army_role'),
                      db.CheckConstraint("target_kind IN ('base','city','army')", name='ck_land_army_target'),
                      {'mysql_engine': 'InnoDB'})


class Occupation(db.Model):
    __tablename__ = 'game_occupations'
    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(8), nullable=False)                  # base / city / region
    base_id = db.Column(db.Integer, db.ForeignKey('game_military_bases.id', ondelete='SET NULL'))
    city_id = db.Column(db.Integer, db.ForeignKey('miasta.miasto_id'))
    region_id = db.Column(db.Integer, nullable=False, index=True)
    owner_id = db.Column(db.Integer, nullable=False, index=True)      # dotychczasowy właściciel
    occupier_id = db.Column(db.Integer, nullable=False, index=True)
    # ACTIVE; region: PENDING (czeka na decyzję okupanta) / DECLINED; ENDED (odbite); ANNEXED
    status = db.Column(db.String(10), nullable=False, index=True)
    started_at = db.Column(db.DateTime, nullable=False)              # czas Entendy
    ended_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    __table_args__ = (db.CheckConstraint("kind IN ('base','city','region')", name='ck_occupation_kind'), {'mysql_engine': 'InnoDB'})


class TrainingExpense(db.Model):
    """Zakup poziomów wyszkolenia sił zbrojnych (budżet sił zbrojnych), 11 Nov 2026."""
    __tablename__ = 'game_training_expenses'
    id = db.Column(db.Integer, primary_key=True)
    panstwo_id = db.Column(db.Integer, db.ForeignKey('panstwa.PANSTWO_ID'), nullable=False, index=True)
    user_id = db.Column(db.Integer, nullable=True)
    budget_id = db.Column(db.BigInteger, db.ForeignKey('game_state_budgets.id'), nullable=False, index=True)
    branch = db.Column(db.String(8), nullable=False)          # land / naval / air
    levels = db.Column(db.Integer, nullable=False)
    level_after = db.Column(db.Integer, nullable=False)
    amount = db.Column(db.Numeric(30, 2), nullable=False)
    request_id = db.Column(db.String(36), nullable=False)
    game_at = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    __table_args__ = (db.UniqueConstraint('panstwo_id', 'request_id', name='uq_training_request'),
                      db.CheckConstraint("branch IN ('land','naval','air')", name='ck_training_branch'),
                      db.CheckConstraint('levels > 0 AND amount > 0', name='ck_training_amount'),
                      {'mysql_engine': 'InnoDB'})


class SovereigntyLoss(db.Model):
    """Utrata suwerenności po aneksji regionu stołecznego (11 Nov 2026): całe terytorium i majątek przechodzą do anektującego,
    a gracz pokonanego państwa zachowuje tylko forum i wiadomości prywatne."""
    __tablename__ = 'game_sovereignty_losses'
    panstwo_id = db.Column(db.Integer, db.ForeignKey('panstwa.PANSTWO_ID'), primary_key=True)
    annexed_by = db.Column(db.Integer, db.ForeignKey('panstwa.PANSTWO_ID'), nullable=False, index=True)
    capital_region_id = db.Column(db.Integer, nullable=False)
    occupation_id = db.Column(db.Integer, db.ForeignKey('game_occupations.id'), nullable=True)
    transferred = db.Column(db.JSON)                                  # liczby przekazanych obiektów (audyt)
    lost_at = db.Column(db.DateTime, nullable=False)                  # czas Entendy
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    __table_args__ = ({'mysql_engine': 'InnoDB'},)
