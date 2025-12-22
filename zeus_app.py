import os
from datetime import datetime
from sqlalchemy import func
from flask_migrate import Migrate

from flask import (
    Flask,
    redirect,
    url_for,
    session,
    request,
    render_template,
)

from extensions import db
from permissions import wymaga_roli

from routes_auth import init_auth_routes
from routes_main import init_main_routes
from routes_panstwa import init_panstwa_routes
from routes_regiony import init_regiony_routes
from routes_miasta import init_miasta_routes
from routes_armia import init_armia_routes
from routes_gospodarka import init_gospodarka_routes
from routes_mapy import init_mapy_routes
from routes_historia import init_historia_routes
from routes_pliki import init_pliki_routes


# ─────────────────────────────────────────
#  STAŁE KALENDARZA ENTENDY
# ─────────────────────────────────────────
START_REAL = datetime(2025, 11, 28)
START_ENTENDA_YEAR = 3000
START_ENTENDA_MONTH = 1
DNI_NA_MIESIAC = 2


def oblicz_kalendarz_entendy():
    teraz = datetime.now()
    delta_dni = (teraz - START_REAL).days

    miesiace_passed = delta_dni // DNI_NA_MIESIAC

    month = START_ENTENDA_MONTH + miesiace_passed
    year = START_ENTENDA_YEAR

    year += (month - 1) // 12
    month = ((month - 1) % 12) + 1

    return month, year


# ─────────────────────────────────────────
#  FABRYKA APLIKACJI
# ─────────────────────────────────────────
import os

def create_app():
    app = Flask(__name__)

    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-key")

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError("Brak DATABASE_URL w zmiennych środowiskowych")

    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    migrate = Migrate(app, db)


    # ───── FILTRY JINJA ─────
    def spacenum(n):
        try:
            return f"{int(n):,}".replace(",", " ")
        except (ValueError, TypeError):
            return n

    app.jinja_env.filters["spacenum"] = spacenum

    @app.template_filter("attr")
    def attr_filter(obj, attr_name):
        try:
            return getattr(obj, attr_name)
        except Exception:
            return None

    # ───── ROUTES ─────
    init_auth_routes(app)
    init_main_routes(app)
    init_panstwa_routes(app)
    init_regiony_routes(app)
    init_miasta_routes(app)
    init_armia_routes(app)
    init_gospodarka_routes(app)
    init_mapy_routes(app)
    init_historia_routes(app)
    init_pliki_routes(app)

    # ─────────────────────────────────────────
    #  WYMUSZENIE EKRANU WEJŚCIA
    # ─────────────────────────────────────────
    @app.before_request
    def wymus_wejscie():
        publiczne_endpointy = {
            "wejscie",
            "static",
        }

        if request.endpoint is None:
            return

        if request.endpoint in publiczne_endpointy:
            return

        if "rola" not in session:
            return redirect(url_for("wejscie"))

    # ─────────────────────────────────────────
    #  GLOBALNY CONTEXT PROCESSOR
    # ─────────────────────────────────────────
    @app.context_processor
    def inject_global_entenda_data():
        from models import Panstwo, Region, Miasto

        m, y = oblicz_kalendarz_entendy()

        try:
            total_population = (
                db.session.query(func.sum(Panstwo.panstwo_populacja))
                .scalar() or 0
            )

            continents = (
                db.session.query(func.count(func.distinct(Panstwo.kontynent)))
                .scalar() or 0
            )

            countries = db.session.query(func.count(Panstwo.PANSTWO_ID)).scalar() or 0
            regions = Region.query.count()
            cities = Miasto.query.count()

        except Exception as e:
            print("Błąd w statystykach Entendy:", e)
            total_population = continents = countries = regions = cities = 0

        def format_int(n):
            try:
                return f"{int(n):,}".replace(",", " ")
            except Exception:
                return "0"

        return {
            "ENTENDA_MONTH": f"{m:02d}",
            "ENTENDA_YEAR": y,
            "E_WORLD_POP": format_int(total_population),
            "E_WORLD_CONTINENTS": continents,
            "E_WORLD_COUNTRIES": countries,
            "E_WORLD_REGIONS": regions,
            "E_WORLD_CITIES": cities,
        }

    # ─────────────────────────────────────────
    #  OBSŁUGA 403
    # ─────────────────────────────────────────
    @app.errorhandler(403)
    def forbidden(e):
        return render_template("403.html"), 403

    return app


# ─────────────────────────────────────────
#  START APLIKACJI
# ─────────────────────────────────────────
app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
