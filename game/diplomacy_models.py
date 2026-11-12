"""Trwałe propozycje i jednostronne deklaracje dyplomatyczne."""
from extensions import db
from game.models import utc_now


class DiplomaticAction(db.Model):
    __tablename__ = "game_diplomatic_actions"

    id = db.Column(db.Integer, primary_key=True)
    sender_user_id = db.Column(db.Integer, db.ForeignKey("game_users.id", ondelete="RESTRICT"), nullable=True)
    recipient_user_id = db.Column(db.Integer, db.ForeignKey("game_users.id", ondelete="RESTRICT"), nullable=True)
    source_country_id = db.Column(db.Integer, db.ForeignKey("panstwa.PANSTWO_ID", ondelete="RESTRICT"), nullable=False)
    target_country_id = db.Column(db.Integer, db.ForeignKey("panstwa.PANSTWO_ID", ondelete="RESTRICT"), nullable=False)
    source_country_name = db.Column(db.String(255), nullable=False)
    target_country_name = db.Column(db.String(255), nullable=False)
    kind = db.Column(db.String(32), nullable=False)
    status = db.Column(db.String(16), nullable=False, default="PENDING")
    proposed_relation_id = db.Column(db.Integer, db.ForeignKey("dict_stosunki_relacja.relacja_id", ondelete="RESTRICT"))
    expected_relation_id = db.Column(db.Integer, nullable=False)
    expected_state_id = db.Column(db.Integer, nullable=False)
    expected_audit_id = db.Column(db.Integer, nullable=False)
    params = db.Column(db.JSON)   # JOIN_WAR: enemy_id/enemy_name; BASE_PERMIT: region_id/region_name
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    decided_at = db.Column(db.DateTime)

    __table_args__ = (
        db.Index("ix_diplomatic_pair_status", "source_country_id", "target_country_id", "status"),
        db.Index("ix_diplomatic_recipient", "recipient_user_id", "status"),
        db.Index("ix_diplomatic_sender", "sender_user_id"),
        db.Index("ix_diplomatic_target", "target_country_id"),
        db.Index("ix_diplomatic_relation", "proposed_relation_id"),
        db.CheckConstraint("kind IN ('WAR', 'PEACE', 'CEASEFIRE', 'RELATION', 'JOIN_WAR', 'BASE_PERMIT')", name="ck_diplomatic_kind"),
        db.CheckConstraint("status IN ('PENDING', 'APPLIED', 'ACCEPTED', 'REJECTED', 'EXPIRED')", name="ck_diplomatic_status"),
        db.CheckConstraint("source_country_id <> target_country_id AND (sender_user_id IS NULL OR recipient_user_id IS NULL OR sender_user_id <> recipient_user_id)", name="ck_diplomatic_different_parties"),
    )
