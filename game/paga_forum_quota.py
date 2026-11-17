"""Globalny limit wpisów PAGA na forum międzynarodowym (16 Nov 2026).

Wszystkie państwa PAGA (tożsamości AI) razem mogą opublikować najwyżej GLOBAL_DAILY_LIMIT wpisów w ciągu ostatnich
24 godzin (czas rzeczywisty). Po wyczerpaniu limitu dozwolone są wyłącznie odpowiedzi na wpisy graczy ludzkich.
Limit obowiązuje przy publikacji (game.forum — ten sam endpoint co dla gracza) oraz przy zlecaniu zadań AI
(game.paga2.communication, game.paga_ai_detector), aby nie zużywać zapytań do modeli na wpisy, które i tak nie powstaną.
Gracze ludzcy nie podlegają limitowi.
"""
from datetime import timedelta
from sqlalchemy import func, inspect, select

GLOBAL_DAILY_LIMIT = 30
LIMIT_MESSAGE = (f'Wyczerpano dobowy limit wpisów PAGA na forum międzynarodowym ({GLOBAL_DAILY_LIMIT}). '
                 'Do czasu zwolnienia limitu państwa PAGA mogą jedynie odpowiadać na wpisy graczy.')


_READY = set()   # silniki baz z tabelą tożsamości PAGA (sprawdzane bez wycofywania transakcji żądania)


def ai_user_ids(session):
    """Konta techniczne państw PAGA; pusty zbiór, gdy PAGA nie jest skonfigurowana (brak tabeli)."""
    from game.paga_ai_models import PagaAiIdentity
    key = id(session.get_bind())
    if key not in _READY:
        if not inspect(session.connection()).has_table(PagaAiIdentity.__tablename__):
            return set()
        _READY.add(key)
    return set(session.scalars(select(PagaAiIdentity.user_id)))


def ai_posts_last_day(session, ai_ids=None):
    from game.forum_models import ForumMessage
    from game.models import utc_now
    ai_ids = ai_user_ids(session) if ai_ids is None else ai_ids
    if not ai_ids:
        return 0
    return session.scalar(select(func.count(ForumMessage.id)).where(
        ForumMessage.user_id.in_(ai_ids), ForumMessage.created_at >= utc_now() - timedelta(days=1))) or 0


def exhausted(session, ai_ids=None):
    return ai_posts_last_day(session, ai_ids) >= GLOBAL_DAILY_LIMIT


PUBLIC_REACTIONS = 3   # ilu państw PAGA reaguje na publiczny wpis gracza (bez adresata, bez wzmianki)


def public_reactors(message_id, country_ids, limit=PUBLIC_REACTIONS):
    """Powtarzalny (dla danego wpisu) wybór państw PAGA, które zareagują na publiczny wpis gracza."""
    from hashlib import sha256
    return set(sorted(country_ids, key=lambda c: sha256(f'forum:{message_id}:{c}'.encode()).hexdigest())[:limit])


def reaction_allowed(session, message, identity_user_id, country_id, ai_ids, country_ids):
    """16 Nov 2026 — naprawa lawiny: czy państwo PAGA ma odpowiedzieć na wpis z powiadomienia FORUM_MESSAGE.
    Wpis innej AI: tylko gdy skierowany do nas albo odpowiada na nasz wpis; łańcuch AI–AI kończy się po jednej
    wymianie. Wpis gracza: skierowany do nas / odpowiedź na nasz — zawsze; publiczny — najwyżej PUBLIC_REACTIONS państw."""
    from game.forum_models import ForumMessage
    if message is None or message.user_id == identity_user_id:
        return False
    addressed = message.recipient_user_id == identity_user_id or any(item.user_id == identity_user_id for item in message.addressees)
    parent = session.get(ForumMessage, message.reply_to_id) if message.reply_to_id else None
    reply_to_us = parent is not None and parent.user_id == identity_user_id
    if message.user_id in ai_ids:
        if not (addressed or reply_to_us):
            return False
        grandparent = session.get(ForumMessage, parent.reply_to_id) if parent is not None and parent.reply_to_id else None
        if parent is not None and parent.user_id in ai_ids and grandparent is not None and grandparent.user_id in ai_ids:
            return False
        return True
    if addressed or reply_to_us:
        return True
    return country_id in public_reactors(message.id, country_ids)


def blocked(session, user_id, reply=None):
    """Powód odmowy publikacji albo None. Dotyczy tylko kont PAGA; odpowiedź na wpis człowieka jest zawsze dozwolona."""
    ai_ids = ai_user_ids(session)
    if user_id not in ai_ids:
        return None
    if reply is not None and reply.user_id not in ai_ids:
        return None
    return LIMIT_MESSAGE if exhausted(session, ai_ids) else None
