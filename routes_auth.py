import hmac
import time

from flask import render_template, request, redirect, url_for, session, flash, jsonify

HASLA_ROLE = {
    "wszechmocny": "AsDfG!2#4%6",
    "tworzyciel": "tworzyciel!1234",
    "obserwator": "obserwator1234",
}

DOZWOLONE_ROLE = set(HASLA_ROLE.keys())


def init_auth_routes(app):

    @app.route("/wejscie", methods=["GET", "POST"])
    def wejscie():

        if request.method == "GET":
            session.pop("rola", None)

        if request.method == "POST":
            rola = request.form.get("rola")
            haslo = request.form.get("haslo")

            if rola not in DOZWOLONE_ROLE:
                flash("Nieprawidłowa rola.", "error")
                return redirect(url_for("wejscie"))

            if haslo != HASLA_ROLE.get(rola):
                flash("Nieprawidłowe hasło dla wybranej roli.", "error")
                return redirect(url_for("wejscie"))

            session["rola"] = rola
            return redirect(url_for("home_page"))

        return render_template("wejscie.html")

    # 14 Nov 2026: „Panel administratora” w pasku gry — samo hasło; rola wynika z pasującego hasła.
    ADMIN_PANEL_MAX_FAILURES = 5
    ADMIN_PANEL_LOCK_SECONDS = 300

    @app.post("/game/panel-administratora")
    def game_admin_panel():
        user_id = session.get("game_user_id")
        if isinstance(user_id, bool) or not isinstance(user_id, int):
            return jsonify(error="Zaloguj się ponownie."), 401
        expected = session.get("game_csrf_token")
        provided = request.form.get("csrf_token", "")
        if not isinstance(expected, str) or not hmac.compare_digest(expected.encode(), provided.encode()):
            return jsonify(error="Sesja formularza wygasła. Odśwież stronę."), 400
        now = time.time()
        failures, locked_until = session.get("admin_panel_failures", [0, 0])
        if locked_until > now:
            return jsonify(error=f"Zbyt wiele błędnych prób. Spróbuj ponownie za {int(locked_until - now) // 60 + 1} min."), 429
        haslo = request.form.get("haslo", "")
        rola = next((name for name, password in HASLA_ROLE.items()
                     if hmac.compare_digest(password.encode(), haslo.encode())), None)
        if rola is None:
            failures += 1
            session["admin_panel_failures"] = [0, now + ADMIN_PANEL_LOCK_SECONDS] if failures >= ADMIN_PANEL_MAX_FAILURES else [failures, 0]
            return jsonify(error="Nieprawidłowe hasło."), 403
        session.pop("admin_panel_failures", None)
        session["rola"] = rola
        return jsonify(redirect=url_for("home_page"))
