from flask import render_template, request, redirect, url_for, session, flash

HASLA_ROLE = {
    "wszechmocny": "AsDfG!2#4%6",
    "tworzyciel": "tworzyciel!1234",
    "obserwator": "obserwator1234",
}

DOZWOLONE_ROLE = set(HASLA_ROLE.keys())


def init_auth_routes(app):

    @app.route("/wejscie", methods=["GET", "POST"])
    def wejscie():

        # 🔥 USUWAMY TYLKO ROLĘ, NIE CAŁĄ SESJĘ
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
