"""Wiadomości wspólnego forum przywódców."""

from extensions import db
from game.diplomacy_models import DiplomaticAction
from game.event_models import GeneratedEventSnapshot
from game.infrastructure_models import InfrastructureProject
from game.models import utc_now


class ForumMessage(db.Model):
    __tablename__ = "game_forum_messages"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("game_users.id", ondelete="RESTRICT"), nullable=False)
    panstwo_id = db.Column(db.Integer, db.ForeignKey("panstwa.PANSTWO_ID", ondelete="RESTRICT"), nullable=False)
    author_name = db.Column(db.String(50), nullable=False)
    country_name = db.Column(db.String(255), nullable=False)
    flag_path = db.Column(db.String(512), nullable=False)
    recipient_user_id = db.Column(
        db.Integer, db.ForeignKey("game_users.id", ondelete="RESTRICT"), nullable=True,
    )
    recipient_name = db.Column(db.String(50))
    recipient_country_name = db.Column(db.String(255))
    recipient_flag_path = db.Column(db.String(512))
    reply_to_id = db.Column(
        db.Integer, db.ForeignKey("game_forum_messages.id", ondelete="RESTRICT"), nullable=True,
    )
    reply_to = db.relationship(
        "ForumMessage", remote_side=[id], foreign_keys=[reply_to_id],
    )
    addressees = db.relationship(
        "ForumMessageRecipient", back_populates="message", order_by="ForumMessageRecipient.id",
    )
    content = db.Column(db.String(1000), nullable=False)
    entenda_date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    edited_at = db.Column(db.DateTime)
    edited_entenda_date = db.Column(db.Date)
    version = db.Column(db.Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": version}
    __table_args__ = (
        db.CheckConstraint("CHAR_LENGTH(content) BETWEEN 1 AND 1000", name="ck_forum_content_length"),
        db.Index("ix_forum_created_id", "created_at", "id"),
        db.Index("ix_forum_recipient", "recipient_user_id"),
        db.Index("ix_forum_reply", "reply_to_id"),
        db.Index("ix_forum_user", "user_id"),
        db.Index("ix_forum_country", "panstwo_id"),
    )


class ForumMessageRecipient(db.Model):
    __tablename__ = "game_forum_message_recipients"

    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey("game_forum_messages.id", ondelete="RESTRICT"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("game_users.id", ondelete="RESTRICT"), nullable=False)
    name = db.Column(db.String(50), nullable=False)
    country_name = db.Column(db.String(255), nullable=False)
    flag_path = db.Column(db.String(512), nullable=False)
    message = db.relationship("ForumMessage", back_populates="addressees")

    __table_args__ = (
        db.UniqueConstraint("message_id", "user_id", name="uq_forum_message_recipient"),
        db.Index("ix_forum_recipient_user", "user_id"),
    )


class GameNotification(db.Model):
    __tablename__ = "game_notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("game_users.id", ondelete="RESTRICT"), nullable=False)
    message_id = db.Column(db.Integer, db.ForeignKey("game_forum_messages.id", ondelete="RESTRICT"), nullable=True)
    diplomatic_action_id = db.Column(db.Integer, db.ForeignKey("game_diplomatic_actions.id", ondelete="RESTRICT"))
    diplomatic_action = db.relationship("DiplomaticAction")
    generated_event_id = db.Column(db.Integer, db.ForeignKey("game_generated_event_snapshots.id", ondelete="RESTRICT"))
    generated_event = db.relationship("GeneratedEventSnapshot")
    infrastructure_project_id = db.Column(db.Integer, db.ForeignKey('game_infrastructure_projects.id', ondelete='RESTRICT'))
    infrastructure_text = db.Column(db.String(512))
    system_text = db.Column(db.String(1000))
    notification_type = db.Column(db.String(32), nullable=False, default="FORUM_MESSAGE")
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    read_at = db.Column(db.DateTime)
    message = db.relationship("ForumMessage")

    __table_args__ = (
        db.UniqueConstraint('user_id', 'infrastructure_project_id', name='uq_notification_user_infrastructure'),
        db.UniqueConstraint("user_id", "generated_event_id", name="uq_notification_user_event"),
        db.Index("ix_notification_event", "generated_event_id"),
        db.UniqueConstraint("user_id", "diplomatic_action_id", name="uq_notification_user_diplomacy"),
        db.Index("ix_notification_diplomacy", "diplomatic_action_id"),
        db.CheckConstraint(
            "((notification_type = 'FORUM_MESSAGE' AND message_id IS NOT NULL AND diplomatic_action_id IS NULL AND generated_event_id IS NULL AND infrastructure_project_id IS NULL AND infrastructure_text IS NULL) OR "
            "(notification_type = 'DIPLOMACY' AND diplomatic_action_id IS NOT NULL AND message_id IS NULL AND generated_event_id IS NULL AND infrastructure_project_id IS NULL AND infrastructure_text IS NULL) OR "
            "(notification_type = 'GENERATED_EVENT' AND generated_event_id IS NOT NULL AND message_id IS NULL AND diplomatic_action_id IS NULL AND infrastructure_project_id IS NULL AND infrastructure_text IS NULL) OR "
            "(notification_type = 'INFRASTRUCTURE_COMPLETED' AND infrastructure_project_id IS NOT NULL AND infrastructure_text IS NOT NULL AND message_id IS NULL AND diplomatic_action_id IS NULL AND generated_event_id IS NULL)) AND system_text IS NULL OR "
            "(notification_type = 'SYSTEM' AND system_text IS NOT NULL AND message_id IS NULL AND diplomatic_action_id IS NULL AND generated_event_id IS NULL AND infrastructure_project_id IS NULL AND infrastructure_text IS NULL)",
            name="ck_notification_target",
        ),
        db.UniqueConstraint("user_id", "message_id", name="uq_notification_user_message"),
        db.Index("ix_notification_user_created", "user_id", "created_at", "id"),
        db.Index("ix_notification_user_unread", "user_id", "read_at"),
        db.Index("ix_notification_message", "message_id"),
    )
