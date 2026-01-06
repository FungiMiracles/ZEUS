from flask import render_template
from extensions import db

def init_kultura_routes(app):

    # ===============================
    # MODUŁ KULTURY – STRONA GŁÓWNA
    # ===============================

    @app.route("/kultura")
    def kultura_home():
        return render_template("kultura.html")

    # ===============================
    # MODUŁ KULTURY – JĘZYKI
    # ===============================

    @app.route("/kultura/jezyki")
    def kultura_jezyki():
        return render_template("kultura_jezyki.html")
