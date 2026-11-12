"""Prywatna poczta graczy: odczyt, wysłanie i odpowiedź."""
from flask import Blueprint, abort, jsonify, request, url_for
from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from game.communication_models import PrivateMessage
from game.forum import flag_path, player, real_date, recipients, validate_csrf
from game.models import utc_now
from models import DictStosunkiRelacja, DictStosunkiStan, Stosunki

messages_bp = Blueprint("game_messages", __name__, url_prefix="/game/wiadomosci")


def relation_labels(rows):
    country_ids = {value for row in rows for value in [row.sender_country_id, row.recipient_country_id]}
    pairs = db.session.execute(select(Stosunki.PANSTWO_ID, Stosunki.PANSTWO_ID2,
        DictStosunkiRelacja.relacja_nazwa, DictStosunkiStan.stan_nazwa)
        .outerjoin(DictStosunkiRelacja, DictStosunkiRelacja.relacja_id == Stosunki.relacja_id)
        .outerjoin(DictStosunkiStan, DictStosunkiStan.stan_id == Stosunki.stan_id)
        .where(Stosunki.PANSTWO_ID.in_(country_ids), Stosunki.PANSTWO_ID2.in_(country_ids))).all() if country_ids else []
    return {(a, b): (relation or "Neutralne") + " · " + (state or "Pokój") for a, b, relation, state in pairs}


def serialize(message, user, labels, detail=False):
    pair = tuple(sorted([message.sender_country_id, message.recipient_country_id]))
    result = {
        "id": message.id, "sender_id": message.sender_user_id, "recipient_id": message.recipient_user_id,
        "sender_name": message.sender_name, "recipient_name": message.recipient_name,
        "sender_country": message.sender_country_name, "recipient_country": message.recipient_country_name,
        "sender_flag": url_for("static", filename=message.sender_flag_path),
        "recipient_flag": url_for("static", filename=message.recipient_flag_path),
        "received_at": real_date(message.created_at), "relation": labels.get(pair, "Neutralne · Pokój"),
        "unread": message.recipient_user_id == user.id and message.read_at is None,
        "incoming": message.recipient_user_id == user.id,
        "reply_to_id": message.reply_to_id,
        "detail_url": url_for("game_messages.detail", message_id=message.id),
        "read_url": url_for("game_messages.read", message_id=message.id),
    }
    if detail:
        result["content"] = message.content
    return result


@messages_bp.get("")
def index():
    user, country = player()
    if user is None:
        return jsonify(error="Zaloguj się ponownie."), 401
    folder = request.args.get("folder", "inbox")
    if folder not in {"inbox", "sent"}:
        abort(400)
    query = select(PrivateMessage).where(
        PrivateMessage.recipient_user_id == user.id if folder == "inbox" else PrivateMessage.sender_user_id == user.id,
    ).order_by(PrivateMessage.created_at.desc(), PrivateMessage.id.desc())
    result = db.paginate(query, page=max(1, request.args.get("page", 1, type=int) or 1), per_page=20, error_out=False)
    labels = relation_labels(result.items)
    count = db.session.scalar(select(func.count()).select_from(PrivateMessage).where(
        PrivateMessage.recipient_user_id == user.id, PrivateMessage.read_at.is_(None),
    ))
    response = jsonify(items=[serialize(item, user, labels) for item in result.items],
                       unread_count=count, next_page=result.next_num if result.has_next else None)
    response.headers["Cache-Control"] = "no-store"
    return response


@messages_bp.get("/adresaci")
def addressees():
    user, country = player()
    if user is None:
        return jsonify(error="Zaloguj się ponownie."), 401
    response = jsonify(items=[{**item, "flag": url_for("static", filename=item["flag_path"])} for item in recipients(user)])
    response.headers["Cache-Control"] = "no-store"
    return response


def owned_message(message_id, user):
    if not 1 <= message_id <= 2147483647:
        abort(404)
    message = db.session.scalar(select(PrivateMessage).where(
        PrivateMessage.id == message_id,
        or_(PrivateMessage.sender_user_id == user.id, PrivateMessage.recipient_user_id == user.id),
    ))
    if message is None:
        abort(404)
    return message


@messages_bp.get("/<int:message_id>")
def detail(message_id):
    user, country = player()
    if user is None:
        return jsonify(error="Zaloguj się ponownie."), 401
    message = owned_message(message_id, user)
    response = jsonify(message=serialize(message, user, relation_labels([message]), detail=True))
    response.headers["Cache-Control"] = "no-store"
    return response


@messages_bp.post("/<int:message_id>/odczytaj")
def read(message_id):
    user, country = player()
    if user is None:
        return jsonify(error="Zaloguj się ponownie."), 401
    validate_csrf()
    message = owned_message(message_id, user)
    if message.recipient_user_id == user.id and message.read_at is None:
        message.read_at = utc_now()
        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            return jsonify(error="Nie udało się oznaczyć wiadomości jako przeczytanej."), 503
    return jsonify(ok=True)


@messages_bp.post("")
def send():
    user, country = player()
    if user is None:
        return jsonify(error="Zaloguj się ponownie."), 401
    validate_csrf()
    content = request.form.get("content", "").replace("\r\n", "\n").replace("\r", "\n")
    if not content.strip() or len(content) > 3000:
        return jsonify(error="Wiadomość musi zawierać od 1 do 3000 znaków razem ze spacjami."), 400
    recipient_id = request.form.get("recipient_id", type=int)
    recipient = next((item for item in recipients(user) if item["id"] == recipient_id), None)
    if recipient is None:
        return jsonify(error="Wybierz aktywnego użytkownika z przypisanym państwem."), 400
    reply_id = request.form.get("reply_to_id", type=int)
    if request.form.get("reply_to_id") and reply_id is None:
        abort(400)
    if reply_id is not None:
        source = owned_message(reply_id, user)
        if source.recipient_user_id != user.id or source.sender_user_id != recipient_id:
            return jsonify(error="Odpowiedź musi być skierowana do nadawcy wybranej wiadomości."), 400
    from game.models import GamePlayerCountry
    recipient_country_id = recipient['country_id']
    message = PrivateMessage(
        sender_user_id=user.id, recipient_user_id=recipient_id,
        sender_country_id=country.PANSTWO_ID, recipient_country_id=recipient_country_id,
        sender_name=user.username, recipient_name=recipient["name"],
        sender_country_name=country.panstwo_nazwa or "", recipient_country_name=recipient["country_name"],
        sender_flag_path=flag_path(country.panstwo_nazwa), recipient_flag_path=recipient["flag_path"],
        content=content, reply_to_id=reply_id,
    )
    db.session.add(message)
    try:
        db.session.commit()
        return jsonify(message="Wiadomość wysłana.", id=message.id), 201
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify(error="Nie udało się wysłać wiadomości. Spróbuj ponownie."), 503
