# ============================================================
# ENTENDA GAME — MODUŁ APLIKACJI
# ============================================================

from flask import Blueprint, render_template, redirect, url_for, session
from game.app import game_bp

app.register_blueprint(game_bp)

game_bp = Blueprint(
    "game",
    __name__,
    url_prefix="/game"
)


# ============================================================
# PANEL GŁÓWNY GRACZA
# ============================================================

@game_bp.route("/panel", methods=["GET"])
def main_page():

    game_user_id = session.get("game_user_id")

    if not game_user_id:
        return redirect("/game/logowanie")

    return render_template(
        "game/game_main_page.html",
        game_user={
            "username": "Gracz"
        },
        game_country={
            "nazwa": "Państwo gracza",
            "skrot": "",
            "flaga": ""
        },
        game_home_url=url_for("game.main_page"),
        game_logout_url="/game/wyloguj",
        game_events=[]
    )