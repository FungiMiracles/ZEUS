import os
from datetime import datetime
from engine.clock import get_current_entenda_date
from engine.clock import get_current_entenda_datetime
from game.finanse import init_finance_routes
from engine.finance_scheduler import start_finance_scheduler
from flask import (
    Flask,
    redirect,
    url_for,
    session,
    request,
    render_template,
    jsonify,
)
from flask_migrate import Migrate
from sqlalchemy import func
from extensions import db
from game.routes_auth import init_game_auth_routes
from permissions import wymaga_roli
from game.models import (
    GameUser,
    GamePlayerCountry,
    GameLoginEvent
)
from routes_auth import init_auth_routes
from game.demografia import demography_bp
from game.srodowisko import environment_bp
from game.army import army_bp
from game.infrastructure import infrastructure_bp
from game.military import military_bp
from game.intelligence import intelligence_bp
from game.world import world_bp
from game.commerce import trade_bp
from game.loans import loans_bp
from game.public_panels import public_panels_bp
from game.diplomacy import diplomacy_bp
from game.forum import forum_bp
from game.communication import messages_bp
from decimal import Decimal, InvalidOperation, ROUND_CEILING, localcontext
from routes_main import init_main_routes
from routes_panstwa import init_panstwa_routes
from routes_regiony import init_regiony_routes
from routes_miasta import init_miasta_routes
from routes_armia import init_armia_routes
from routes_gospodarka import init_gospodarka_routes
from routes_mapy import init_mapy_routes
from routes_historia import init_historia_routes
from routes_pliki import init_pliki_routes
from routes_demografia import init_demografia_routes
from routes_dyplomacja import init_dyplomacja_routes
from routes_kultura import init_kultura_routes
from routes_religia import init_religia_routes
from routes_api import init_api_routes
from routes_zdarzenia import init_zdarzenia_routes
from routes_artykuly import init_artykuly_routes
from routes_natura import init_natura_routes
from routes_fauna import init_fauna_routes
from routes_raporty import init_raporty_routes
from routes_admin import init_admin_routes
from routes_wykresy import init_wykresy_routes
from routes_przywodcy import init_przywodcy_routes
from engine.generator import start_event_scheduler
from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env.uat"))

ENV_NAME = os.getenv("ENV_NAME", "PROD")

# ─────────────────────────────────────────
#  STAŁE KALENDARZA ENTENDY
# ─────────────────────────────────────────
START_REAL = datetime(2025, 11, 28)
START_ENTENDA_YEAR = 2990
START_ENTENDA_MONTH = 1
DNI_NA_MIESIAC = 2

def oblicz_kalendarz_entendy():
    now = get_current_entenda_datetime()
    return now.month, now.year


# ─────────────────────────────────────────
#  FABRYKA APLIKACJI
# ─────────────────────────────────────────
def create_app():
    app = Flask(__name__)

    # Interfejs i ręczne zatwierdzanie dostępne wyłącznie w UAT.
    app.config["GAME_FINANCE_ENABLED"] = ENV_NAME == "UAT"
    app.config['ENTENDA_CLOCK_CONTROL_ENABLED'] = ENV_NAME == 'UAT'

    # Automatyczne księgowanie włączymy po testach.
    app.config["GAME_FINANCE_SCHEDULER_ENABLED"] = False

    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-key")

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError("Brak DATABASE_URL w zmiennych środowiskowych")

    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    Migrate(app, db)

    # ───── FILTRY JINJA ─────
    def spacenum(n):
        try:
            return f"{int(n):,}".replace(",", " ")
        except (ValueError, TypeError):
            return n

    app.jinja_env.filters["spacenum"] = spacenum

    @app.template_global("period_label")
    def period_label_global(year, period):
        # 13 Nov 2026: „II półrocze 3001” albo „IV kwartał 3001”
        from game.finance_service import period_label
        try:return period_label(int(year), int(period))
        except Exception:return f"{period}. okres {year}"

    @app.template_global("game_period")
    def game_period_global(year=None, period=None):
        # 16 Nov 2026: nazwa bieżącego okresu budżetowego (kwartał/półrocze) w odmianie
        from game.finance_service import period_words
        try:return period_words(int(year) if year is not None else None, int(period) if period is not None else None)
        except Exception:return {'nom':'okres','gen':'okresu','loc':'okresie','current':'bieżący okres','adj':'okresowe','months':6,'share':50,'per_year':'przy każdym budżecie','label':''}

    @app.template_filter("game_money")
    def game_money(value):
        from game.money_display import format_money
        return format_money(value)

    @app.template_filter("attr")
    def attr_filter(obj, attr_name):
        try:
            return getattr(obj, attr_name)
        except Exception:
            return None

    # ───── ROUTES ─────
    init_auth_routes(app)
    init_main_routes(app)
    init_game_auth_routes(app)
    if app.config["GAME_FINANCE_ENABLED"]:
        init_finance_routes(app)
    init_panstwa_routes(app)
    init_regiony_routes(app)
    init_miasta_routes(app)
    init_armia_routes(app)
    init_gospodarka_routes(app)
    init_mapy_routes(app)
    init_historia_routes(app)
    init_pliki_routes(app)
    init_demografia_routes(app)
    init_dyplomacja_routes(app)
    init_kultura_routes(app)
    init_religia_routes(app)
    init_api_routes(app)
    init_zdarzenia_routes(app)
    from routes_clock import clock_bp
    app.register_blueprint(clock_bp)
    init_artykuly_routes(app)
    init_natura_routes(app)
    init_fauna_routes(app)
    init_raporty_routes(app)
    init_admin_routes(app)
    app.config["PAGA_ENABLED"] = ENV_NAME == "UAT"
    app.config["AUTONOMY_ENABLED"] = ENV_NAME == "UAT"
    app.config["DIPLOMACY_NEWS_ENABLED"] = ENV_NAME == "UAT"
    # 16 Nov 2026: cykliczne wpisywanie przywódców (okno po wygaśnięciu kadencji) wyłączone na UAT i PREPROD.
    app.config["LEADERSHIP_PROMPT_ENABLED"] = ENV_NAME not in ("UAT", "PREPROD")
    app.config["ENV_NAME"] = ENV_NAME
    if app.config["PAGA_ENABLED"]:
        from routes_paga import paga_bp
        app.register_blueprint(paga_bp)
        from game.account import account_bp
        app.register_blueprint(account_bp)
    init_wykresy_routes(app)
    init_przywodcy_routes(app)
    app.register_blueprint(demography_bp)
    app.register_blueprint(environment_bp)
    app.register_blueprint(army_bp)
    app.register_blueprint(infrastructure_bp)
    app.register_blueprint(military_bp)
    app.register_blueprint(intelligence_bp)
    app.register_blueprint(world_bp)
    app.register_blueprint(trade_bp)
    app.register_blueprint(loans_bp)
    from game.industry_models import PowerPlant,IndustryClock,IndustryMovement
    from game.research import research_bp
    app.register_blueprint(research_bp)
    app.register_blueprint(public_panels_bp)
    app.register_blueprint(diplomacy_bp)
    app.config['PAGA_AI_CONFIGURED']=ENV_NAME=='UAT' and os.environ.get('PAGA_AI_CONFIGURED','1')=='1'
    from game.module_funds import register as register_module_funds
    register_module_funds(app)
    # Measured 2026-11-09: one model process per tick (closed at its end), up to 3 tasks back to back.
    app.config['PAGA_AI_PERSISTENT_MODEL']=True
    app.config['PAGA_AI_TASKS_PER_TICK']=int(os.environ.get('PAGA_AI_TASKS_PER_TICK','3'))
    from game.player_context import player_context_bp
    app.register_blueprint(player_context_bp)
    app.register_blueprint(forum_bp)
    from game.tutorial import tutorial_bp   # 15 Nov 2026: samouczek po pierwszym wejściu
    app.register_blueprint(tutorial_bp)
    app.register_blueprint(messages_bp)
    from game.sovereignty import register as register_sovereignty
    register_sovereignty(app)

    @app.context_processor
    def military_navigation():
        from flask import session
        from sqlalchemy import select
        from game.models import GamePlayerCountry
        from game.military_service import enemies
        user_id = session.get('game_user_id')
        if type(user_id) is not int:
            return {'game_can_war':False}
        country_id = db.session.scalar(select(GamePlayerCountry.panstwo_id).where(GamePlayerCountry.user_id == user_id))
        return {'game_can_war':bool(country_id and enemies(db.session,country_id))}

    @app.context_processor
    def game_budget_navigation():
        from flask import request,session
        if not (request.path.startswith('/game/') or request.path=='/game'):return {}
        user_id=session.get('game_user_id')
        if type(user_id) is not int:return {}
        from sqlalchemy import select
        from game.models import GamePlayerCountry
        from game.budget_overview import budget_overview
        country_id=db.session.scalar(select(GamePlayerCountry.panstwo_id).where(GamePlayerCountry.user_id==user_id))
        return {'game_budget_overview':budget_overview(db.session,country_id)} if country_id else {}

    @app.context_processor
    def game_sidebar():
        # 13 Nov 2026: stały lewy pasek gry — magazyn (odczyt) i wykres budżetu na każdym ekranie gry.
        from flask import request,session
        if not request.path.startswith('/game/') and request.path!='/game':return {}
        user_id=session.get('game_user_id')
        if type(user_id) is not int:return {}
        try:
            from sqlalchemy import select
            from game.models import GamePlayerCountry
            from game.sidebar import warehouse_items
            country_id=db.session.scalar(select(GamePlayerCountry.panstwo_id).where(GamePlayerCountry.user_id==user_id))
            from game.sidebar import budget_pie
            return {'game_sidebar_warehouse':warehouse_items(db.session,country_id),'game_budget_pie':budget_pie} if country_id else {}
        except Exception:
            app.logger.exception('Pasek boczny gry: magazyn')
            return {}

    @app.context_processor
    def inject_entenda_clock():

        from engine.clock import get_clock_snapshot
        snapshot = get_clock_snapshot()
        entenda_now = datetime.fromisoformat(snapshot['entenda'])
        if app.config['ENTENDA_CLOCK_CONTROL_ENABLED'] and session.get('rola') == 'wszechmocny':
            import secrets
            session.setdefault('clock_csrf', secrets.token_urlsafe(32))

        return {
            "entenda_time_description": snapshot['description'],
            "ENTENDA_TIME_MULTIPLIER": snapshot['multiplier'],
            "ENTENDA_CLOCK_REVISION": snapshot['revision'],
            "ENTENDA_DATE": entenda_now.strftime("%d.%m.%Y"),
            "ENTENDA_DATETIME": entenda_now.isoformat()
        }
    
    @app.context_processor
    def inject_env():
        return dict(ENV_NAME=ENV_NAME)

    @app.route("/health")
    def health():
        return "OK", 200
    
    # ───── BEFORE REQUEST ─────
    @app.before_request
    def wymus_wejscie():

        # Endpointy dostępne bez logowania do ZEUS WIKI
        publiczne_endpointy = {
            "wejscie",
            "static",
            "region_sovereignty.country_boundaries",
            "entenda_clock.state",

            # ENTENDA GAME
            "game_rejestracja",
            "game_api_panstwa",
            "game_registration_csrf",
            "game_registration_submit",
            "game_login_submit",
            "game_main_page",
            "game_logout",
            "game_admin_panel",  # 14 Nov 2026: trasa sama sprawdza sesję gracza, CSRF i hasło
        }

        if request.endpoint is None:
            return
        
        if request.blueprint in {"game_player", "game_account", "game_research", "game_loans", "game_public", "game_trade", "game_intelligence", "game_military", "game_infrastructure", "game_army", "game_resources", "game_demography", "game_forum", "game_environment", "game_diplomacy", "game_messages", "game_world", "game_tutorial"}:   # 15 Nov 2026: game_tutorial sam sprawdza sesję gracza i CSRF
            return

        # Blueprint sam sprawdza sesję gracza i token CSRF.
        if request.blueprint == "game_finance":
            return

        if request.endpoint in publiczne_endpointy:
            return

        game_map_routes = {
            "/mapy_swiata",
            "/api/panstwa_meta",
            "/wiki/mapa/panstwa.geojson",
            "/api/regiony_meta",
            "/api/miasta_meta",
            "/api/mapa/typy-regionow",
            "/api/kontynenty",
            "/api/panstwa",
            "/api/regiony",
            "/api/region/<int:region_id>/miasta",
            "/api/miasto_suggest",
            "/api/mapa/stosunki/<int:panstwo_id>",
        }

        if (
            request.method == "GET"
            and request.url_rule is not None
            and request.url_rule.rule in game_map_routes
        ):
            game_user_id = session.get("game_user_id")
            game_user = (
                db.session.get(GameUser, game_user_id)
                if game_user_id else None
            )

            if game_user is not None and game_user.is_active:
                return

        if "rola" not in session:
            return redirect(url_for("wejscie"))

        


    @app.context_processor
    def inject_global_entenda_data():
        try:
            from models import Panstwo, Region, Miasto, DictKontynent

            entenda_now = get_current_entenda_datetime()

            total_population = (
                db.session.query(func.sum(Panstwo.panstwo_populacja))
                .scalar()
            ) or 0

            from services.wiki_world_stats import world_gdp, world_current_metrics
            gdp = world_gdp(db.session, entenda_now.year)
            metrics = world_current_metrics(db.session)

            continents = DictKontynent.query.count()

            countries = db.session.query(Panstwo.PANSTWO_ID).count()
            regions = Region.query.count()
            cities = Miasto.query.count()

            def format_int(n):
                return f"{int(n):,}".replace(",", " ")

            def format_metric(value):
                return '—' if value is None else f'{value:,.2f}'.replace(',', ' ').replace('.', ',')

            return {
                "ENTENDA_DATE": entenda_now.strftime("%d.%m.%Y"),
                "ENTENDA_DATETIME": entenda_now.isoformat(),
                "E_WORLD_POP": format_int(total_population),
                "E_WORLD_GDP": format_metric(Decimal(gdp['total']) / Decimal('1000000000000')) + ' BLN',
                "E_WORLD_GDP_TREND": gdp['trend'],
                "E_WORLD_GDP_PREVIOUS_YEAR": gdp['previousYear'],
                "E_WORLD_GDP_COMPARISON_YEAR": gdp.get('comparisonYear', entenda_now.year),
                "E_WORLD_CONTINENTS": continents,
                "E_WORLD_COUNTRIES": countries,
                "E_WORLD_REGIONS": regions,
                "E_WORLD_CITIES": cities,
                "E_WORLD_GDP_PC": format_metric(metrics['gdp_per_capita']),
                "E_WORLD_INFRASTRUCTURE": format_metric(metrics['infrastructure']),
                "E_WORLD_URBANIZATION": format_metric(metrics['urbanization']),
                "E_WORLD_POP_GROWTH": format_metric(metrics['population_growth']),
                "E_WORLD_EVENTS": format_int(metrics['events']),
            }

        except Exception as e:
            print("Context processor error:", e)
            return {}

    from game.paga_ai_actor import AiPermissionError
    @app.errorhandler(AiPermissionError)
    def ai_forbidden(error):
        db.session.rollback()
        return jsonify(error=str(error)),403

    # ───── ERROR HANDLER ─────
    @app.errorhandler(403)
    def forbidden(e):
        return render_template("403.html"), 403
    
    if ENV_NAME == 'UAT':
        from engine.infrastructure_scheduler import start_infrastructure_scheduler
        start_infrastructure_scheduler(app)
        from engine.autonomy_scheduler import start_autonomy_scheduler
        start_autonomy_scheduler(app)
        from engine.paga_ai_scheduler import start_paga_ai_scheduler
        start_paga_ai_scheduler(app)
        from engine.paga2_scheduler import start_paga2_scheduler
        start_paga2_scheduler(app)

    start_event_scheduler(app)  # ODBLOKOWUJE/ZABLOKOWUJE GENERATOR ZDARZEŃ

    if (
        app.config["GAME_FINANCE_ENABLED"]
        and app.config["GAME_FINANCE_SCHEDULER_ENABLED"]
    ):
        start_finance_scheduler(app)

    return app


# ─────────────────────────────────────────
#  START APLIKACJI
# ─────────────────────────────────────────
app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)

