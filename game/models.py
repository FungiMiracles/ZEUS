# game/models.py

from datetime import datetime, timezone

from extensions import db


def utc_now():
    return datetime.now(timezone.utc)


# ============================================================
# ENTENDA GAME — KONTA GRACZY
# ============================================================

class GameUser(db.Model):

    __tablename__ = "game_users"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    username = db.Column(
        db.String(50),
        nullable=False
    )

    username_normalized = db.Column(
        db.String(50),
        nullable=False,
        unique=True,
        index=True
    )

    email = db.Column(
        db.String(254),
        nullable=True
    )

    email_normalized = db.Column(
        db.String(254),
        nullable=True,
        unique=True,
        index=True
    )

    password_hash = db.Column(
        db.String(255),
        nullable=True
    )

    is_active = db.Column(
        db.Boolean,
        nullable=False,
        default=True,
        server_default=db.true()
    )

    email_verified_at = db.Column(
        db.DateTime(timezone=True),
        nullable=True
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now
    )

    last_login_at = db.Column(
        db.DateTime(timezone=True),
        nullable=True
    )

    # 14 Nov 2026: ostatnie otwarcie forum — plakietka liczby nowych wpisów w menu zamiast powiadomień.
    forum_seen_at = db.Column(
        db.DateTime,
        nullable=True
    )

    country_assignment = db.relationship(
        "GamePlayerCountry",
        back_populates="user",
        uselist=False
    )


# ============================================================
# ENTENDA GAME — PAŃSTWA GRACZY
# ============================================================

class GamePlayerCountry(db.Model):

    __tablename__ = "game_player_countries"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "game_users.id",
            ondelete="RESTRICT"
        ),
        nullable=False,
        unique=True
    )

    panstwo_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "panstwa.PANSTWO_ID",
            ondelete="RESTRICT"
        ),
        nullable=False,
        unique=True
    )

    assigned_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now
    )

    user = db.relationship(
        "GameUser",
        back_populates="country_assignment"
    )

    panstwo = db.relationship(
        "Panstwo"
    )


# ============================================================
# ENTENDA GAME — HISTORIA LOGOWANIA
# ============================================================

class GameLoginEvent(db.Model):

    __tablename__ = "game_login_events"

    id = db.Column(
        db.BigInteger,
        primary_key=True,
        autoincrement=True
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "game_users.id",
            ondelete="SET NULL"
        ),
        nullable=True,
        index=True
    )

    event_type = db.Column(
        db.String(30),
        nullable=False
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        index=True
    )

    user = db.relationship("GameUser")
