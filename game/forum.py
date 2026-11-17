"""Publiczne forum: publikowanie, odpowiedzi, adresaci i edycja własnych wpisów."""

import hmac
import re
from datetime import timezone
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload, lazyload, selectinload
from sqlalchemy.orm.exc import StaleDataError

from extensions import db
from game.country_summary import country_summary
from engine.clock import get_current_entenda_date
from game.forum_models import ForumMessage, ForumMessageRecipient, GameNotification
from game.models import GamePlayerCountry, GameUser, utc_now
from models import Panstwo

forum_bp = Blueprint("game_forum", __name__, url_prefix="/game/forum")
PAGE_SIZE = 20


def real_date(value):
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(ZoneInfo("Europe/Warsaw")).strftime("%d.%m.%Y %H:%M:%S")


forum_bp.add_app_template_filter(real_date, "forum_real_date")


def player():
    user_id = session.get("game_user_id")
    if isinstance(user_id, bool) or not isinstance(user_id, int):
        return None, None
    user = db.session.get(GameUser, user_id)
    if user is None or not user.is_active:
        return None, None
    from game.paga_ai_actor import assigned_country
    ai_country=assigned_country(db.session,user.id)
    if ai_country is not None:return user,ai_country
    assignment = user.country_assignment
    if assignment is None:
        abort(403, description="Do konta nie przypisano państwa.")
    country = db.session.scalar(
        select(Panstwo).where(Panstwo.PANSTWO_ID == assignment.panstwo_id)
        .options(lazyload("*"))
    )
    if country is None or country.czy_suwerenny != "TAK":
        abort(403, description="Brak suwerennego państwa przypisanego do konta.")
    return user, country


def mark_forum_seen(user_id):
    """Otwarcie forum zeruje plakietkę nowych wpisów w menu (14 Nov 2026).
    Osobne połączenie: zapis nie zatwierdza ani nie unieważnia obiektów sesji żądania."""
    from sqlalchemy import update
    try:
        with db.engine.begin() as connection:
            connection.execute(update(GameUser).where(GameUser.id == user_id).values(forum_seen_at=utc_now()))
    except SQLAlchemyError:
        pass


def forum_new_count(user_id):
    """Liczba wpisów innych graczy od ostatniego otwarcia forum (plakietka przy „Forum międzynarodowe”)."""
    # Kolumny wprost z bazy (znacznik zapisuje osobne połączenie — obiekt w sesji może być nieaktualny).
    row = db.session.execute(select(GameUser.forum_seen_at, GameUser.created_at).where(GameUser.id == user_id)).first()
    if row is None:
        return 0
    since = row.forum_seen_at or row.created_at
    if since is not None and since.tzinfo is not None:
        since = since.astimezone(timezone.utc).replace(tzinfo=None)
    query = select(func.count()).select_from(ForumMessage).where(ForumMessage.user_id != user_id)
    if since is not None:
        query = query.where(ForumMessage.created_at > since)
    return db.session.scalar(query) or 0


@forum_bp.app_context_processor
def forum_badge():
    def badge():
        user_id = session.get("game_user_id")
        if isinstance(user_id, bool) or not isinstance(user_id, int):
            return 0
        try:
            return forum_new_count(user_id)
        except SQLAlchemyError:
            db.session.rollback()
            return 0
    return {"forum_new_count": badge}


def validate_csrf():
    expected = session.get("game_csrf_token")
    provided = request.form.get("csrf_token", "")
    if not isinstance(expected, str) or not hmac.compare_digest(expected.encode(), provided.encode()):
        abort(400, description="Sesja formularza wygasła. Odśwież stronę.")


def message_content():
    # Przeglądarka wysyła CRLF; jeden podział wiersza liczymy jako znak.
    content = request.form.get("content", "").replace("\r\n", "\n").replace("\r", "\n")
    if not content.strip():
        return content, "Wiadomość nie może być pusta."
    if len(content) > 1000:
        return content, "Wiadomość może mieć maksymalnie 1000 znaków razem ze spacjami."
    return content, None


def flag_path(country_name):
    return "flags/" + (country_name or "").replace(" ", "_") + ".jpg"


def recipients(user):
    rows = db.session.execute(
        select(GameUser.id, GameUser.username, Panstwo.panstwo_nazwa, Panstwo.PANSTWO_ID)
        .join(GamePlayerCountry, GamePlayerCountry.user_id == GameUser.id)
        .join(Panstwo, Panstwo.PANSTWO_ID == GamePlayerCountry.panstwo_id)
        .where(GameUser.is_active.is_(True), GameUser.id != user.id)
        .order_by(GameUser.username_normalized, GameUser.id)
    ).all()
    choices = [
        {"id": row.id, "name": row.username, "country_id":row.PANSTWO_ID, "country_name": row.panstwo_nazwa or "",
         "flag_path": flag_path(row.panstwo_nazwa)}
        for row in rows
    ]
    from game.paga_ai_actor import configured
    if configured():
        from game.paga_ai_models import PagaAiIdentity
        from game.autonomy_engine import eligible_ids
        rows=db.session.execute(select(GameUser.id,GameUser.username,Panstwo.PANSTWO_ID,Panstwo.panstwo_nazwa).join(PagaAiIdentity,PagaAiIdentity.user_id==GameUser.id).join(Panstwo,Panstwo.PANSTWO_ID==PagaAiIdentity.country_id).where(PagaAiIdentity.country_id.in_(eligible_ids(db.session)),GameUser.is_active.is_(True),GameUser.id!=user.id).order_by(Panstwo.panstwo_nazwa))
        choices.extend({'id':row.id,'name':row.username,'country_id':row.PANSTWO_ID,'country_name':row.panstwo_nazwa,'flag_path':flag_path(row.panstwo_nazwa)} for row in rows)
    return choices


def selected_context(user, choices):
    """Identyfikatory są sprawdzane na serwerze; podpisów nie przyjmujemy z formularza."""
    data = request.form if request.method == "POST" else request.args
    reply_id = data.get("reply_to_id", "")
    recipient_ids = {value for value in data.getlist("recipient_id") if value}
    reply = None
    if reply_id:
        if not reply_id.isascii() or not reply_id.isdigit() or len(reply_id) > 10:
            abort(400, description="Nieprawidłowa wiadomość źródłowa.")
        reply = db.get_or_404(ForumMessage, int(reply_id))
        if reply.user_id == user.id:
            abort(400, description="Możesz odpowiadać na wiadomości innych użytkowników.")
        recipient_ids.add(str(reply.user_id))
    selected = [item for item in choices if str(item["id"]) in recipient_ids]
    if len(selected) != len(recipient_ids):
        return reply, selected, "Adresat jest niedostępny. Wybierz aktywnych graczy z przypisanym państwem."
    return reply, selected, None


def render_page(user, country, *, editing=None, content="", error=None, status=200,
                choices=None, reply=None, recipient=None):
    page = request.args.get("page", 1, type=int)
    page = max(1, page or 1)
    messages = db.paginate(
        select(ForumMessage).options(
            selectinload(ForumMessage.reply_to), selectinload(ForumMessage.addressees),
        )
        .order_by(ForumMessage.created_at.desc(), ForumMessage.id.desc()),
        page=page, per_page=PAGE_SIZE, error_out=False,
    )
    if choices is None:
        choices = recipients(user)
    html = render_template(
        "game/forum.html", game_user=user,
        game_country=country_summary(country),
        game_home_url=url_for("game_main_page"), game_logout_url=url_for("game_logout"),
        game_active_page="forum", messages=messages, editing=editing,
        content=content, error=error, recipients=choices, replying_to=reply,
        selected_recipients=recipient or [],
        selected_recipient_ids=[item["id"] for item in recipient or []],
    )
    mark_forum_seen(user.id)
    return html, status


@forum_bp.route("", methods=["GET", "POST"])
def page():
    user, country = player()
    if user is None:
        return redirect(url_for("wejscie"))
    if request.method == "POST":
        validate_csrf()
    choices = recipients(user)
    reply, recipient, context_error = selected_context(user, choices)
    context = dict(choices=choices, reply=reply, recipient=recipient)
    if request.method == "GET":
        return render_page(user, country, error=context_error,
                           status=400 if context_error else 200, **context)
    content, error = message_content()
    if error or context_error:
        return render_page(user, country, content=content, error=error or context_error,
                           status=400, **context)
    # 16 Nov 2026: globalny dobowy limit wpisów PAGA (odpowiedzi na wpisy graczy ludzkich zawsze dozwolone).
    from game.paga_forum_quota import blocked as paga_quota_blocked
    if (quota_error := paga_quota_blocked(db.session, user.id, reply)):
        return render_page(user, country, content=content, error=quota_error, status=429, **context)
    first_recipient = recipient[0] if recipient else None
    message = ForumMessage(
        user_id=user.id, panstwo_id=country.PANSTWO_ID,
        author_name=user.username, country_name=country.panstwo_nazwa or "",
        flag_path=flag_path(country.panstwo_nazwa),
        recipient_user_id=first_recipient["id"] if first_recipient else None,
        recipient_name=first_recipient["name"] if first_recipient else None,
        recipient_country_name=first_recipient["country_name"] if first_recipient else None,
        recipient_flag_path=first_recipient["flag_path"] if first_recipient else None,
        reply_to_id=reply.id if reply else None,
        content=content, entenda_date=get_current_entenda_date(), created_at=utc_now(),
    )
    db.session.add(message)
    try:
        db.session.flush()
        for item in recipient:
            db.session.add(ForumMessageRecipient(
                message_id=message.id, user_id=item["id"], name=item["name"],
                country_name=item["country_name"], flag_path=item["flag_path"],
            ))
        # 14 Nov 2026: gracze nie dostają powiadomień o wpisach (plakietka w menu); powiadomienie trafia tylko do skrzynek PAGA,
        # które na jego podstawie reagują na forum.
        from game.paga_ai_actor import configured
        ai_users = set()
        if configured():
            from game.paga_ai_models import PagaAiIdentity
            ai_users = set(db.session.scalars(select(PagaAiIdentity.user_id)))
        for item in recipient or choices:
            if item["id"] not in ai_users:
                continue
            db.session.add(GameNotification(
                user_id=item["id"], message_id=message.id,
                notification_type="FORUM_MESSAGE", created_at=message.created_at,
            ))
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        user, country = player()
        return render_page(user, country, content=content,
                           error="Nie udało się opublikować wiadomości. Spróbuj ponownie.",
                           status=503, **context)
    return redirect(url_for("game_forum.page"), code=303)


@forum_bp.get("/<int:message_id>")
def permalink(message_id):
    user, country = player()
    if user is None:
        return redirect(url_for("wejscie"))
    message = db.get_or_404(ForumMessage, message_id)
    newer = db.session.scalar(
        select(func.count()).select_from(ForumMessage).where(or_(
            ForumMessage.created_at > message.created_at,
            (ForumMessage.created_at == message.created_at) & (ForumMessage.id > message.id),
        ))
    )
    return redirect(url_for("game_forum.page", page=newer // PAGE_SIZE + 1,
                            _anchor=f"message-{message.id}"))


@forum_bp.route("/<int:message_id>/edytuj", methods=["GET", "POST"])
def edit(message_id):
    user, country = player()
    if user is None:
        return redirect(url_for("wejscie"))
    message = db.get_or_404(ForumMessage, message_id)
    if message.user_id != user.id:
        abort(403, description="Możesz edytować wyłącznie własne wiadomości.")
    if request.method == "GET":
        return render_page(user, country, editing=message, content=message.content)
    validate_csrf()
    content, error = message_content()
    if request.form.get("version") != str(message.version):
        error = "Wiadomość została już zmieniona. Otwórz edycję ponownie, aby wczytać aktualną treść."
        return render_page(user, country, editing=message, content=content, error=error, status=409)
    if error:
        return render_page(user, country, editing=message, content=content, error=error, status=400)
    if content == message.content:
        return redirect(url_for("game_forum.permalink", message_id=message.id), code=303)
    message.content = content
    message.edited_at = utc_now()
    message.edited_entenda_date = get_current_entenda_date()
    try:
        db.session.commit()
    except StaleDataError:
        db.session.rollback()
        user, country = player()
        return render_page(user, country, editing=message, content=content, error="Wiadomość została zmieniona w innej sesji. Sprawdź jej aktualną treść.", status=409)
    except SQLAlchemyError:
        db.session.rollback()
        user, country = player()
        return render_page(user, country, editing=message, content=content, error="Nie udało się zapisać zmian. Spróbuj ponownie.", status=503)
    return redirect(url_for("game_forum.permalink", message_id=message.id), code=303)


@forum_bp.get("/powiadomienia")
def notifications():
    user, country = player()
    if user is None:
        return jsonify(error="Zaloguj się ponownie."), 401
    country_id=country.PANSTWO_ID
    from game.infrastructure_service import complete_due
    from game.finance_service import game_now
    complete_due(db.session, game_now(), country_id)
    db.session.commit()
    from game.intelligence_service import complete_missions
    complete_missions(db.session,game_now(),country_id)
    db.session.commit()
    page_number = max(1, request.args.get("page", 1, type=int) or 1)
    result = db.paginate(
        select(GameNotification).where(GameNotification.user_id == user.id, GameNotification.notification_type != "FORUM_MESSAGE")
        .options(joinedload(GameNotification.message), joinedload(GameNotification.diplomatic_action), joinedload(GameNotification.generated_event))
        .order_by(GameNotification.created_at.desc(), GameNotification.id.desc()),
        page=page_number, per_page=20, error_out=False,
    )
    count = db.session.scalar(select(func.count()).select_from(GameNotification).where(
        GameNotification.user_id == user.id, GameNotification.read_at.is_(None),
        GameNotification.notification_type != "FORUM_MESSAGE",
    ))
    from game.diplomacy import notification_text
    from game.intelligence_models import IntelligenceMission
    intelligence_notifications=set(db.session.scalars(select(IntelligenceMission.notification_id).where(IntelligenceMission.panstwo_id==country_id,IntelligenceMission.notification_id.in_([item.id for item in result.items]))))
    items = []
    news_kinds={}
    from game.diplomacy_news import enabled,NewsNotice,NewsEvent
    if enabled():
        news_kinds=dict(db.session.execute(select(NewsNotice.main_notification_id,NewsEvent.kind).join(NewsEvent,NewsEvent.id==NewsNotice.event_id).where(NewsNotice.user_id==user.id,NewsNotice.main_notification_id.in_([item.id for item in result.items]))).all())
    for item in result.items:
        if item.notification_type == "SYSTEM":
            text = item.system_text
        elif item.notification_type == "INFRASTRUCTURE_COMPLETED":
            text = item.infrastructure_text
        elif item.notification_type == "GENERATED_EVENT":
            text = "Generator Zdarzeń · " + item.generated_event.region_name + ": " + item.generated_event.content
        elif item.notification_type == "DIPLOMACY":
            text = notification_text(item.diplomatic_action,user.id)
        else:
            text = f"{item.message.author_name} ({item.message.country_name}): nowa wiadomość na forum."
        items.append({
            "id": item.id, "text": text, "kind": "INTELLIGENCE_REPORT" if item.id in intelligence_notifications else item.notification_type,
            "severity": ('war' if news_kinds[item.id]=='WAR_STARTED' else 'info') if item.id in news_kinds else notification_severity(item),
            "icon_url": notification_icon(item, intelligence=item.id in intelligence_notifications),
            "effects": item.generated_event.effects if item.notification_type == "GENERATED_EVENT" else [],
            "received_at": real_date(item.created_at), "unread": item.read_at is None,
            "open_url": url_for("game_forum.open_notification", notification_id=item.id),
        })
    response = jsonify(unread_count=count, next_page=result.next_num if result.has_next else None, items=items)
    response.headers["Cache-Control"] = "no-store"
    return response


@forum_bp.post("/powiadomienia/odczytaj")
def read_notifications():
    user, country = player()
    if user is None:
        return jsonify(error="Zaloguj się ponownie."), 401
    validate_csrf()
    from sqlalchemy import update
    if request.form.get("all") == "1":
        # „Oznacz wszystkie jako przeczytane” (12 Nov 2026).
        db.session.execute(update(GameNotification).where(
            GameNotification.user_id == user.id, GameNotification.read_at.is_(None),
        ).values(read_at=utc_now()))
    else:
        ids = request.form.getlist("ids")
        if not ids or len(ids) > 20 or any(not value.isdecimal() for value in ids):
            return jsonify(error="Nieprawidłowa lista powiadomień."), 400
        db.session.execute(update(GameNotification).where(
            GameNotification.id.in_([int(value) for value in ids]),
            GameNotification.user_id == user.id, GameNotification.read_at.is_(None),
        ).values(read_at=utc_now()))
    db.session.commit()
    count = db.session.scalar(select(func.count()).select_from(GameNotification).where(
        GameNotification.user_id == user.id, GameNotification.read_at.is_(None),
        GameNotification.notification_type != "FORUM_MESSAGE",
    ))
    return jsonify(unread_count=count)


# 16 Nov 2026: zatrzymanie produkcji w fabryce, wydobycia w kopalni lub produkcji energii w elektrowni
# (game.industry_service, game.mining_service, game.military_flights) — powiadomienie prowadzi do ekranu
# „Infrastruktura i energetyka”.
PRODUCTION_STOPPED = re.compile(r"^[^:\n]+ #\d+: (?:produkcja(?: energii)? (?:została )?wstrzymana|wydobycie zatrzymane)\b")


def production_stopped(text):
    return bool(PRODUCTION_STOPPED.match(text or ""))


def notification_icon(item, *, intelligence=False):
    text=(item.system_text or '').casefold() if item.notification_type=='SYSTEM' else ''
    filename=None
    if ' zakupił/a ' in text and 'cło portowe:' in text:filename='CARGO SHIP.svg'
    elif intelligence or item.notification_type=='INTELLIGENCE_REPORT' or any(word in text for word in ('wywiad','kontrwywiad','hybryd','agent','sabota')):
        filename='WYWIAD WOJSKOWY.svg'
    elif 'pożycz' in text:filename='POŻYCZKA.svg'
    elif item.notification_type=='INFRASTRUCTURE_COMPLETED' or notification_severity(item)=='construction':filename='PRACE BUDOWLANE 2.svg'
    return url_for('static',filename='icons/'+filename) if filename else None


def notification_severity(item):
    if item.notification_type == "DIPLOMACY" and item.diplomatic_action.kind == "WAR":
        return "war"
    if item.notification_type == "INFRASTRUCTURE_COMPLETED":
        return "construction"
    if item.notification_type == "SYSTEM":
        text = (item.system_text or "").casefold()
        if any(word in text for word in ("budow", "rozbudow", "kopalnia gotowa")):
            return "construction"
        if any(word in text for word in ("atak", "zniszcz", "wojsk", "rakiet", "okręt", "wywiad", "obron", "hybryd")):
            return "war"
    return "info"


@forum_bp.post("/powiadomienia/<int:notification_id>/otworz")
def open_notification(notification_id):
    user, country = player()
    if user is None:
        return redirect(url_for("wejscie"))
    country_id=country.PANSTWO_ID
    validate_csrf()
    notification = db.session.scalar(select(GameNotification).where(
        GameNotification.id == notification_id, GameNotification.user_id == user.id,
    ))
    if notification is None:
        abort(404)
    message_id = notification.message_id
    if notification.read_at is None:
        notification.read_at = utc_now()
        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            abort(503, description="Nie udało się oznaczyć powiadomienia jako przeczytanego.")
    if notification.notification_type == "SYSTEM":
        from game.diplomacy_news import enabled,NewsNotice
        if enabled() and db.session.scalar(select(NewsNotice.event_id).where(NewsNotice.user_id==user.id,NewsNotice.main_notification_id==notification.id)) is not None:return redirect(url_for('game_diplomacy.page'),code=303)
        if " zakupił/a " in (notification.system_text or "") and "Cło portowe:" in (notification.system_text or ""):return redirect("/game/handel",code=303)
        if (notification.system_text or "").startswith("Obywatele nie są zadowoleni z wysokiej stawki podatku."):return redirect("/game/spoleczenstwo",code=303)
        if (notification.system_text or "").startswith("Droga:"):return redirect("/game/infrastruktura?tab=roads",code=303)
        if production_stopped(notification.system_text):return redirect("/game/infrastruktura",code=303)
        if (notification.system_text or "").startswith("Pożyczka:"):return redirect("/game/finanse#state-loans",code=303)
        from game.intelligence_models import IntelligenceMission
        from game.intelligence_service import mission_details
        mission=db.session.scalar(select(IntelligenceMission).where(IntelligenceMission.notification_id==notification.id,IntelligenceMission.panstwo_id==country_id))
        if mission is not None:
            if request.accept_mimetypes.best=='application/json':return jsonify(report=mission_details(mission))
            return redirect('/game/wywiad-wojskowy?raport='+str(mission.id),code=303)
        return redirect("/game/obrona-panstwa",code=303)
    if notification.notification_type == "INFRASTRUCTURE_COMPLETED":
        return redirect(url_for("game_infrastructure.page"), code=303)
    if notification.notification_type == "GENERATED_EVENT":
        snapshot = notification.generated_event
        if request.accept_mimetypes.best == "application/json":
            return jsonify(event={
                "title": "Generator Zdarzeń · " + snapshot.region_name,
                "content": snapshot.content, "effects": snapshot.effects,
                "country": snapshot.country_name,
                "entenda_date": snapshot.entenda_date.strftime("%d.%m.%Y") if snapshot.entenda_date else "Brak danych",
                "received_at": real_date(notification.created_at),
            })
        return redirect(url_for("game_environment.page"), code=303)
    if notification.notification_type == "DIPLOMACY":
        if request.accept_mimetypes.best == "application/json":
            from game.diplomacy import action_details
            user, country = player()
            return jsonify(dialog=action_details(notification.diplomatic_action, user, country))
        return redirect(url_for("game_diplomacy.page"), code=303)
    return redirect(url_for("game_forum.permalink", message_id=message_id), code=303)
