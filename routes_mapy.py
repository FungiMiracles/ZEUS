# routes_mapy.py
from flask import render_template
from permissions import wymaga_roli

def init_mapy_routes(app):

    # Strona z kafelkami map
    @app.route("/mapy")
    def mapy():
        return render_template("mapy.html")

    # ✔️ Nowa trasa – mapa świata
    @app.route("/mapy_swiata")
    def mapy_swiata():
        return render_template("mapy_swiata.html")
    
    @app.route("/mapy/kao")
    def mapy_kao():
        return render_template("mapy_kao.html")
    
    @app.route("/mapy/beifa")
    def mapy_beifa():
        return render_template("mapy_beifa.html")
    
    @app.route("/mapy/anzinia")
    def mapy_anzinia():
        return render_template("mapy_anzinia.html")
    
    @app.route("/mapy/peryfa")
    def mapy_peryfa():
        return render_template("mapy_peryfa.html")
    
    @app.route("/mapy/wyspy_wieksze")
    def mapy_wyspy_wieksze():
        return render_template("mapy_wieksze.html")

    @app.route("/mapy/wyspy_mniejsze")
    def mapy_wyspy_mniejsze():
        return render_template("mapy_mniejsze.html")
