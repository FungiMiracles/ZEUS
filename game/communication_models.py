"""Prywatne wiadomości pomiędzy kontami graczy."""
from extensions import db
from game.models import utc_now


class PrivateMessage(db.Model):
    __tablename__ = "game_private_messages"

    id = db.Column(db.Integer, primary_key=True)
    sender_user_id = db.Column(db.Integer, db.ForeignKey("game_users.id", ondelete="RESTRICT"), nullable=False)
    recipient_user_id = db.Column(db.Integer, db.ForeignKey("game_users.id", ondelete="RESTRICT"), nullable=False)
    sender_country_id = db.Column(db.Integer, nullable=False)
    recipient_country_id = db.Column(db.Integer, nullable=False)
    sender_name = db.Column(db.String(50), nullable=False)
    recipient_name = db.Column(db.String(50), nullable=False)
    sender_country_name = db.Column(db.String(255), nullable=False)
    recipient_country_name = db.Column(db.String(255), nullable=False)
    sender_flag_path = db.Column(db.String(512), nullable=False)
    recipient_flag_path = db.Column(db.String(512), nullable=False)
    content = db.Column(db.String(3000), nullable=False)
    reply_to_id = db.Column(db.Integer, db.ForeignKey("game_private_messages.id", ondelete="RESTRICT"))
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    read_at = db.Column(db.DateTime)

    __table_args__ = (
        db.Index("ix_pm_inbox", "recipient_user_id", "created_at", "id"),
        db.Index("ix_pm_sent", "sender_user_id", "created_at", "id"),
        db.Index("ix_pm_unread", "recipient_user_id", "read_at"),
        db.Index("ix_pm_reply", "reply_to_id"),
        db.CheckConstraint("CHAR_LENGTH(content) BETWEEN 1 AND 3000", name="ck_pm_content_length"),
        db.CheckConstraint("sender_user_id <> recipient_user_id", name="ck_pm_different_users"),
    )
