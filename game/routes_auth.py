"""ENTENDA GAME: rejestracja kont graczy (niezależna od ZEUS WIKI)."""
import hmac
import re
import secrets
from game.governance import controlled_ids
from datetime import datetime, timezone

from flask import (
    jsonify,
    request,
    session,
    redirect,
    url_for,
    render_template,
    flash,
    abort,
)
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash, check_password_hash

from flask import (
    jsonify,
    request,
    session,
    redirect,
    url_for,
    render_template,
    flash,
    abort,
    current_app,
)

from extensions import db
from game.country_summary import country_summary
from game.models import GameUser, GamePlayerCountry, GameLoginEvent
from models import Panstwo, Region, Miasto
from sqlalchemy import select
from sqlalchemy.orm import lazyload
from game.finanse import build_panel_finance_context


def init_game_auth_routes(app):
    @app.get('/game/api/rejestracja/csrf')
    def game_registration_csrf():
        token = session.get('game_registration_csrf')
        if not token:
            token = secrets.token_urlsafe(32)
            session['game_registration_csrf'] = token
        return jsonify({'csrf_token': token})
    
    def game_csrf_token():
        token = session.get("game_csrf_token")
        if not token:
            token = secrets.token_urlsafe(32)
            session["game_csrf_token"] = token
        return token

    def validate_game_csrf():
        expected = session.get("game_csrf_token")
        provided = request.form.get("csrf_token", "")
        if not expected or not hmac.compare_digest(expected, provided):
            abort(400, description="Sesja formularza wygasła. Odśwież stronę.")

    @app.context_processor
    def inject_game_csrf():
        return {"game_csrf_token": game_csrf_token()}

    @app.post("/game/logowanie")
    def game_login_submit():
        validate_game_csrf()

        username = request.form.get("game_login", "").strip()
        password = request.form.get("game_password", "")

        if not username or len(username) > 50 or not 1 <= len(password) <= 128:
            flash("Podaj poprawny login i hasło.", "game_error")
            return redirect(url_for("wejscie"), code=303)

        user = GameUser.query.filter_by(
            username_normalized=username.casefold()
        ).first()

        if (
            user is None
            or not user.is_active
            or not user.password_hash
            or not check_password_hash(user.password_hash, password)
        ):
            flash("Nieprawidłowy login lub hasło.", "game_error")
            return redirect(url_for("wejscie"), code=303)

        try:
            user.last_login_at = datetime.now(timezone.utc)
            db.session.add(
                GameLoginEvent(user_id=user.id, event_type="login")
            )
            db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.exception("Błąd logowania ENTENDA GAME")
            flash("Nie udało się zalogować. Spróbuj ponownie.", "game_error")
            return redirect(url_for("wejscie"), code=303)

        session["game_user_id"] = user.id
        session.pop("game_csrf_token", None)

        return redirect(url_for("game_main_page"), code=303)

    @app.get("/game/panel")
    def game_main_page():
        user_id = session.get("game_user_id")
        user = db.session.get(GameUser, user_id) if user_id else None

        if user is None or not user.is_active:
            session.pop("game_user_id", None)
            return redirect(url_for("wejscie"))

        assignment = user.country_assignment
        from game.paga_ai_actor import assigned_country
        country=assigned_country(db.session,user.id)
        if country is None:country = assignment.panstwo if assignment else None
        if country is not None and country.czy_suwerenny != "TAK":
            abort(403, description="Państwo niesuwerenne jest zarządzane przez państwo zwierzchnie.")
        country_data = country_summary(country)

        region_names = {
            str(region.region_id): region.region_nazwa
            for region in db.session.scalars(select(Region).where(Region.panstwo_id.in_(controlled_ids(db.session, country.PANSTWO_ID)))) if not region.terytorium_zamorskie
        } if country else {}

        city_data = {
            str(city.miasto_id): {
                "nazwa": city.miasto_nazwa,
                "populacja": city.miasto_populacja,
                "stolica": city.miasto_typ_id == 1,
            }
            for city in db.session.scalars(select(Miasto).where(Miasto.panstwo_id.in_(controlled_ids(db.session, country.PANSTWO_ID)))) if str(city.region_id) in region_names
        } if country else {}
    
        finance_context = {}

        if current_app.config.get("GAME_FINANCE_ENABLED", False):
            finance_context = build_panel_finance_context(user.id)

        panel={'regions':{},'objects':[],'dashboard':{},'filters':[]}
        if country:
            from game.commerce import settle_own
            settle_own(country.PANSTWO_ID)   # rozliczenie produkcji i dostaw przy wejściu do panelu
            db.session.commit()
            # 13 Nov 2026: mapa z obiektami i kontenery informacyjne panelu państwa
            from game import main_panel
            icon=lambda name:url_for('static',filename='icons/'+name)
            panel={'regions':main_panel.region_info(country.PANSTWO_ID),'objects':main_panel.map_objects(country.PANSTWO_ID,icon),
                   'dashboard':main_panel.dashboard(country.PANSTWO_ID),
                   'filters':[(group,[(code,label,icon(file)) for code,label,file in items]) for group,items in main_panel.MAP_FILTERS]}
            db.session.rollback()
        return render_template(
            "game/game_main_page.html",
            game_user=user,
            game_country=country_data,
            game_home_url=url_for("game_main_page"),
            game_logout_url=url_for("game_logout"),
            game_events=[],
            game_region_names=region_names,
            game_city_data=city_data,
            game_panel=panel,
            **finance_context,
        )

    @app.post("/game/wyloguj")
    def game_logout():
        validate_game_csrf()
        session.pop("game_user_id", None)
        session.pop("game_csrf_token", None)
        return redirect(url_for("wejscie"), code=303)

    @app.post('/game/api/rejestracja')
    def game_registration_submit():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(
                ok=True,
                message="Konto utworzone.",
                redirect_url=url_for("game_main_page"),
            ), 201

        expected = session.get('game_registration_csrf', '')
        provided = request.headers.get('X-CSRF-Token', '')
        if not expected or not hmac.compare_digest(expected, provided):
            return jsonify(error='Sesja formularza wygasła. Odśwież stronę.'), 403

        username = str(data.get('username') or '').strip()
        email = str(data.get('email') or '').strip()
        password = data.get('password')
        password_confirm = data.get('password_confirm')
        panstwo_id = data.get('panstwo_id')

        if not re.fullmatch(r'[\w-]{3,50}', username, flags=re.UNICODE):
            return jsonify(error='Login: 3–50 znaków (litery, cyfry, _ lub -).'), 400
        if len(email) > 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
            return jsonify(error='Podaj poprawny adres e-mail.'), 400
        if not isinstance(password, str) or not 12 <= len(password) <= 128:
            return jsonify(error='Hasło musi mieć od 12 do 128 znaków.'), 400
        if password != password_confirm:
            return jsonify(error='Podane hasła nie są identyczne.'), 400
        if isinstance(panstwo_id, bool) or not str(panstwo_id).isdigit():
            return jsonify(error='Wybierz państwo na mapie.'), 400
        panstwo_id = int(panstwo_id)

        chosen = db.session.scalar(select(Panstwo).options(lazyload("*")).where(Panstwo.PANSTWO_ID == panstwo_id).with_for_update())
        if chosen is None:
            return jsonify(error='Wybrane państwo nie istnieje.'), 400
        if chosen.czy_suwerenny != 'TAK':
            return jsonify(error='Państwo niesuwerenne jest zarządzane razem z państwem zwierzchnim. Wybierz państwo suwerenne.'), 400
        territory_ids = controlled_ids(db.session, panstwo_id)
        list(db.session.scalars(select(Panstwo.PANSTWO_ID).where(Panstwo.PANSTWO_ID.in_(territory_ids)).order_by(Panstwo.PANSTWO_ID).with_for_update()))

        username_norm = username.casefold()
        email_norm = email.casefold()
        if GameUser.query.filter_by(username_normalized=username_norm).first():
            return jsonify(error='Ta nazwa użytkownika jest zajęta.'), 409
        if GameUser.query.filter_by(email_normalized=email_norm).first():
            return jsonify(error='Ten adres e-mail jest już zarejestrowany.'), 409
        if db.session.scalar(select(GamePlayerCountry.id).where(GamePlayerCountry.panstwo_id.in_(territory_ids))):
            return jsonify(error='To państwo zostało już wybrane przez innego gracza.'), 409

        try:
            user = GameUser(
                username=username,
                username_normalized=username_norm,
                email=email,
                email_normalized=email_norm,
                password_hash=generate_password_hash(password),
                is_active=True,
                email_verified_at=None,
                last_login_at=datetime.now(timezone.utc),
            )
            db.session.add(user)
            db.session.flush()
            db.session.add(GamePlayerCountry(user_id=user.id, panstwo_id=panstwo_id))
            db.session.add(GameLoginEvent(user_id=user.id, event_type='registration'))
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return jsonify(error='Login, e-mail lub państwo zostały właśnie zajęte. Spróbuj ponownie.'), 409
        except Exception:
            db.session.rollback()
            app.logger.exception('Błąd rejestracji ENTENDA GAME')
            return jsonify(error='Nie udało się utworzyć konta. Spróbuj później.'), 500

        session['game_user_id'] = user.id
        session.pop('game_registration_csrf', None)
        return jsonify(
            ok=True,
            message='Konto utworzone. Jesteś zalogowany(-a) do ENTENDA GAME.',
            redirect_url=url_for('game_main_page'),
        ), 201
