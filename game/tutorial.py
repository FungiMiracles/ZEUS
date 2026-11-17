"""Samouczek gry (15 Nov 2026): powitanie po pierwszym wejściu i komunikaty przy pierwszym wejściu do sekcji.

Każdy komunikat jest zapamiętywany osobno (game_user_tutorials: użytkownik + klucz). Brak wpisu = gracz go jeszcze
nie widział — dotyczy także kont sprzed wprowadzenia samouczka, więc zobaczą komunikaty przy najbliższym wejściu.
Na ekranie sekcji przed jej komunikatem pokazujemy powitanie, jeśli gracz jeszcze go nie zamknął.
"""
from flask import Blueprint, current_app, jsonify, request, session
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from extensions import db
from game.models import utc_now

MAIN = 'main'
_MAIN_COMMON = ('W sekcji „Badania i rozwój” kupuj punkty rozwoju i rozwiń technologie wojskowe, wydobywcze, energetyczne, środowiskowe '
                'i informatyczne. Gdy rozwiniesz technologie, w sekcji infrastruktury będziesz mógł/mogła budować kopalnie, fabryki '
                'i elektrownie, by rozwijać kraj. W panelu „Obrona państwa” możesz budować bazy wojskowe i ochraniać zbudowaną '
                'infrastrukturę za pomocą obrony przeciwrakietowej. W panelu handlu możesz handlować surowcami i uzbrojeniem z innymi '
                'państwami, a rozwijany panel boczny wyświetli ci obecny stan zasobów państwa. I jest tego jeszcze więcej. Powodzenia!')

# Klucz komunikatu: (endpoint ekranu, tytuł, treść)
SECTIONS = {
    'research': ('game_research.page', 'Badania i rozwój',
                 'Za 150 mln ROI możesz kupić 1 punkt rozwoju. Kup ich wystarczająco, by rozwijać poszczególne technologie.'),
    'forum': ('game_forum.page', 'Forum międzynarodowe',
              'Publikuj posty na forum międzynarodowym. Państwa, które nie posiadają graczy również publikują swoje.'),
    'finance': ('game_finance.page', 'Podatki i budżet',
                'Na tym ekranie zarządzisz finansami państwa. Budżet, który będziesz musiał ustalać co kwartał czasu gry, możesz '
                'wyświetlić właśnie tutaj. Dodatkowo możesz przesuwać środki między sektorami, jeśli społeczeństwo Twojego kraju ma '
                'wystarczająco dużo zaufania do rządu. Jeśli nie, środki możesz przesunąć tylko do i z rezerwy budżetowej. Możesz też '
                'wystąpić o pożyczkę do innego państwa.'),
    'war': ('game_military.war_page', 'Panel wojenny',
            'Na tym ekranie, jeśli prowadzisz z kimś wojnę, możesz atakować obiekty innych państw – okręty, bazy, lotniskowce, '
            'łodzie podwodne, infrastrukturę regionalną. By wiedzieć gdzie są bazy przeciwnika, przejdź do ekranu wywiadu wojskowego.'),
    'intelligence': ('game_intelligence.page', 'Wywiad wojskowy',
                     'Rekrutuj i wysyłaj agentów do regionów innych państw, by sabotować infrastrukturę lub pozyskiwać informacje '
                     'o lokalizacji ważnych obiektów. Tylko wiedząc gdzie są, będziesz mógł/mogła je zaatakować.'),
    'diplomacy': ('game_diplomacy.page', 'Dyplomacja',
                  'Tutaj możesz zarządzać relacjami z innymi państwami. Możesz wypowiedzieć komuś wojnę, próbować zakończyć już '
                  'istniejącą lub budować sojusze.'),
    'defense': ('game_military.defense_page', 'Obrona państwa',
                'Na tym ekranie możesz budować bazy wojskowe w kraju i poza nim lub rozwijać ochronę przeciwrakietową swoich '
                'obiektów infrastrukturalnych.'),
    'trade': ('game_trade.page', 'Handel',
              'Na tym ekranie możesz wystawić własną ofertę sprzedażową lub przyjąć ofertę innego kraju. Możesz też ustawić stawki '
              'celne za korzystanie ze swoich portów przez państwa bez dostępu do morza.'),
}
BY_ENDPOINT = {endpoint: key for key, (endpoint, _, _) in SECTIONS.items()}
KEYS = {MAIN, *SECTIONS}


class GameUserTutorial(db.Model):
    __tablename__ = 'game_user_tutorials'
    user_id = db.Column(db.Integer, db.ForeignKey('game_users.id', ondelete='CASCADE'), primary_key=True)
    tutorial = db.Column(db.String(32), primary_key=True, default=MAIN, server_default=MAIN)
    seen_at = db.Column(db.DateTime, nullable=False, default=utc_now)


tutorial_bp = Blueprint('game_tutorial', __name__, url_prefix='/game/samouczek')


def seen_keys(user_id):
    return set(db.session.scalars(select(GameUserTutorial.tutorial).where(GameUserTutorial.user_id == user_id)))


def main_message(country_genitive):
    return {'key': MAIN, 'title': 'Witaj w grze',
            'mobile': f'Zostałeś przywódcą {country_genitive}. Zarządzaj wszystkimi sektorami państwa z poziomu menu w prawym górnym rogu ekranu głównego. {_MAIN_COMMON}',
            'desktop': f'Zostałeś przywódcą {country_genitive}. Zarządzaj wszystkimi sektorami państwa z poziomu menu u góry ekranu. {_MAIN_COMMON}'}


def pending(user_id, country_name, endpoint):
    """Komunikaty do pokazania na tym ekranie, w kolejności: powitanie, potem komunikat sekcji."""
    from game.country_names import genitive
    done = seen_keys(user_id);items = []
    if MAIN not in done:items.append(main_message(genitive(country_name)))
    key = BY_ENDPOINT.get(endpoint)
    if key and key not in done:
        _, title, text = SECTIONS[key];items.append({'key': key, 'title': title, 'mobile': text, 'desktop': text})
    return items


@tutorial_bp.app_context_processor
def tutorial_context():
    """game_tutorials: lista komunikatów samouczka dla bieżącego ekranu gry (pusta po ich zamknięciu)."""
    if not request.path.startswith('/game/') or request.method != 'GET':return {}
    user_id = session.get('game_user_id')
    if type(user_id) is not int:return {}
    try:
        from game.models import GamePlayerCountry
        from models import Panstwo
        name = db.session.scalar(select(Panstwo.panstwo_nazwa).join(GamePlayerCountry, GamePlayerCountry.panstwo_id == Panstwo.PANSTWO_ID)
                                 .where(GamePlayerCountry.user_id == user_id))
        if name is None:return {}
        items = pending(user_id, name, request.endpoint)
        return {'game_tutorials': items, 'game_tutorial_url': '/game/samouczek/przeczytany'} if items else {}
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('Samouczek: odczyt stanu')   # np. migracja niewykonana — gra działa bez samouczka
        return {}


@tutorial_bp.post('/przeczytany')
def mark_seen():
    user_id = session.get('game_user_id')
    if type(user_id) is not int:return jsonify(error='Zaloguj się ponownie.'), 401
    from game.forum import validate_csrf
    validate_csrf()
    key = request.form.get('tutorial', MAIN)
    if key not in KEYS:return jsonify(error='Nieznany komunikat samouczka.'), 400
    if key not in seen_keys(user_id):
        db.session.add(GameUserTutorial(user_id=user_id, tutorial=key, seen_at=utc_now()))
        try:db.session.commit()
        except IntegrityError:db.session.rollback()   # równoległe zamknięcie w drugiej karcie
    return jsonify(ok=True)
