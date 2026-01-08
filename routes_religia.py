from flask import render_template
from extensions import db


def init_religia_routes(app):

    # ------------------------------------------------------------
    # STRONA GŁÓWNA MODUŁU RELIGIJNEGO
    # ------------------------------------------------------------
    @app.route("/religia")
    def religia_home():
        return render_template("religia.html")
