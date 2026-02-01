# routes_main.py
import os
from flask import render_template, redirect, url_for
from extensions import db
from models import Panstwo
from paths import INFO_FILE
from permissions import wymaga_roli
import markdown
from paths import VERSIONS_FILE


def init_main_routes(app):
    # --------------------------
    # Strony główne / proste
    # --------------------------
    @app.route("/")
    def root():
        return redirect(url_for("wejscie"))
    
    @app.route("/home")
    def home_page():
        return render_template("zeus_home.html")

    @app.route("/historia")
    def historia():
        return render_template("historia.html")

    @app.route("/kultura")
    def kultura():
        return render_template("kultura.html")

    @app.route("/sily_zbrojne")
    def sily_zbrojne():
        return render_template("sily_zbrojne.html")

    @app.route("/demografia")
    def demografia():
        return render_template("demografia.html")

    @app.route("/natura")
    def natura():
        return render_template("natura.html")

    @app.route("/artykuly")
    def artykuly():
        return render_template("artykuly.html")

    @app.route("/pliki")
    def pliki():
        return render_template("pliki.html")

    @app.route("/dyplomacja")
    def dyplomacja():
        return render_template("dyplomacja.html")

    @app.route("/osoba_form")
    def osoba_form():
        return render_template("osoba_form.html")
    
    @app.route("/gospodarka")
    def gospodarka():
        return render_template("gospodarka.html")
    
    # --------------------------
    # Informacje o wersjach – changelog (Markdown)
    # --------------------------
    @app.route("/zeus/versions")
    def zeus_versions():
        try:
            with open(VERSIONS_FILE, "r", encoding="utf-8") as f:
                md_text = f.read()

            changelog_html = markdown.markdown(
                md_text,
                extensions=["extra", "tables", "sane_lists"]
            )

        except FileNotFoundError:
            changelog_html = "<p>Brak pliku changelogu.</p>"
        except Exception as e:
            changelog_html = f"<p>Błąd podczas odczytu changelogu: {e}</p>"

        return render_template(
            "zeus_versions.html",
            changelog_html=changelog_html
        )


    # --------------------------
    # Info – odczyt info.md
    # --------------------------
    @app.route("/info")
    def info():
        try:
            with open(INFO_FILE, "r", encoding="utf-8") as f:
                info_text = f.read()
        except FileNotFoundError:
            info_text = "Brak pliku info.md."
        except Exception as e:
            info_text = f"Błąd podczas odczytywania pliku info.md: {e}"

        return render_template("info.html", info_text=info_text)

    # --------------------------
    # Test bazy
    # --------------------------
    @app.route("/testdb")
    def test_db():
        try:
            # Prosty test, czy można odpytać tabelę
            db.session.query(Panstwo).first()
            return "Połączenie z bazą działa poprawnie"
        except Exception as e:
            return f"Błąd połączenia: {e}"

    # --------------------------
    # Potwierdzenia dodania
    # --------------------------
    @app.route("/panstwo_dodano")
    def panstwo_dodano():
        return render_template("panstwo_dodano.html")

    @app.route("/region_dodano")
    def region_dodano():
        return render_template("region_dodano.html")

    @app.route("/miasto_dodano")
    def miasto_dodano():
        return render_template("miasto_dodano.html")
