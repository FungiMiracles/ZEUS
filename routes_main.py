# routes_main.py
import os
from flask import render_template, redirect, url_for
from extensions import db
from models import Panstwo
from paths import INFO_FILE
from permissions import wymaga_roli
import markdown
from paths import VERSIONS_FILE
from models import Zdarzenie, DictKontynent
from game.models import GamePlayerCountry


def init_main_routes(app):
    # --------------------------
    # Strony główne / proste
    # --------------------------

    @app.context_processor
    def inject_world_news():
        latest_events = (
            Zdarzenie.query
            .order_by(Zdarzenie.data_entenda.desc())
            .limit(10)
            .all()
        )
        return {"latest_events": latest_events}
    
    # ============================================================
    # ENTENDA GAME — WYBÓR PAŃSTWA
    # ============================================================

    @app.route("/game/rejestracja", methods=["GET"])
    def game_rejestracja():
        return render_template("game/game_wybor_panstwa.html")

    # ============================================================
    # ENTENDA GAME — DANE PAŃSTW DO MAPY
    # ============================================================

        # ============================================================
    # ENTENDA GAME — API PAŃSTW
    # ============================================================

    @app.route("/game/api/panstwa", methods=["GET"])
    def game_api_panstwa():

        from flask import jsonify, url_for
        from models import Panstwo, Miasto, Region
        from sqlalchemy.orm import selectinload
        from game.governance import controlled_ids, controller_id

        # ========================================================
        # POBIERANIE PAŃSTW
        # ========================================================

        panstwa = (
            Panstwo.query
            .options(
                selectinload(Panstwo.regiony),
                selectinload(Panstwo.miasta),
                selectinload(Panstwo.kontynent_rel)
            )
            .all()
        )

        # ========================================================
        # STOLICE PAŃSTW
        # ========================================================

        stolice = (
            Miasto.query
            .filter(Miasto.miasto_typ_id == 1)
            .order_by(Miasto.miasto_id)
            .all()
        )

        stolice_dict = {}

        for miasto in stolice:

            if miasto.panstwo_id not in stolice_dict:

                stolice_dict[miasto.panstwo_id] = (
                    miasto.miasto_nazwa
                )

        # ========================================================
        # GENEROWANIE DANYCH PAŃSTW
        # ========================================================

        zajete_panstwa = {
            assignment.panstwo_id
            for assignment in GamePlayerCountry.query.all()
        }

        wynik = {}
        by_id = {item.PANSTWO_ID: item for item in panstwa}

        for panstwo in panstwa:

            territory_ids = controlled_ids(db.session, panstwo.PANSTWO_ID)
            territories = [by_id[id] for id in territory_ids] or [panstwo]
            manager_id = controller_id(db.session, panstwo.PANSTWO_ID)
            manager = by_id.get(manager_id)
            occupied = bool(set(territory_ids) & zajete_panstwa)
            populacja = sum(item.panstwo_populacja or 0 for item in territories)
            pkb = sum(item.panstwo_PKB or 0 for item in territories)
            powierzchnia = sum(item.panstwo_powierzchnia or 0 for item in territories)
            regiony = [region for item in territories for region in item.regiony]
            miasta = [city for item in territories for city in item.miasta]

            # ====================================================
            # PKB PER CAPITA
            # ====================================================

            pkb_per_capita = (
                round(pkb / populacja, 2)
                if populacja > 0
                else None
            )

            # ====================================================
            # GĘSTOŚĆ ZALUDNIENIA
            # ====================================================

            gestosc_zaludnienia = (
                round(populacja / powierzchnia, 2)
                if powierzchnia > 0
                else None
            )

            # ====================================================
            # URBANIZACJA
            # ====================================================

            populacja_miast = sum(
                miasto.miasto_populacja or 0
                for miasto in miasta
            )

            urbanizacja = (
                round((populacja_miast / populacja) * 100, 2)
                if populacja > 0
                else None
            )

            # ====================================================
            # INFRASTRUKTURA
            # ====================================================

            infrastruktura_regionow = []

            for region in regiony:

                wskazniki = [
                    region.region_stan_infra_kolejowej,
                    region.region_stan_infra_drogowej,
                    region.region_stan_infra_energetycznej,
                    region.region_stan_infra_mieszkalnej,
                    region.region_stan_infra_portowej
                ]

                wskazniki = [
                    wartosc
                    for wartosc in wskazniki
                    if wartosc is not None
                ]

                if wskazniki:

                    srednia_regionu = (
                        sum(wskazniki) / len(wskazniki)
                    )

                    infrastruktura_regionow.append(
                        srednia_regionu
                    )

            infrastruktura = (
                round(
                    sum(infrastruktura_regionow)
                    / len(infrastruktura_regionow),
                    2
                )
                if infrastruktura_regionow
                else None
            )

            # ====================================================
            # KONTYNENT
            # ====================================================

            kontynent = (
                panstwo.kontynent_rel.kontynent_nazwa
                if panstwo.kontynent_rel
                else None
            )

            # ====================================================
            # STATUS NIEZALEŻNOŚCI
            # ====================================================

            czy_suwerenny = (
                panstwo.czy_suwerenny == "TAK"
            )

            # ====================================================
            # DANE JSON
            # ====================================================

            wynik[str(panstwo.PANSTWO_ID)] = {

                # PODSTAWOWE
                "nazwa": panstwo.panstwo_nazwa,
                "pelna_nazwa": panstwo.panstwo_pelna_nazwa,

                "stolica": stolice_dict.get(
                    panstwo.PANSTWO_ID
                ),

                "kontynent": kontynent,

                # DEMOGRAFIA
                "populacja": populacja,
                "niedostepne": not czy_suwerenny or occupied,
                "powod_niedostepnosci": ("Państwo niesuwerenne. Zarząd: " + manager.panstwo_nazwa if manager else "Państwo niesuwerenne — niedostępne do wyboru") if not czy_suwerenny else ("Kraj ma już użytkownika" if occupied else ""),
                "panstwo_zarzadcze_id": manager_id,
                "terytoria_zalezne": [item.panstwo_nazwa for item in territories if item.PANSTWO_ID != panstwo.PANSTWO_ID],
                "powierzchnia": powierzchnia,
                "gestosc_zaludnienia": gestosc_zaludnienia,
                "urbanizacja": urbanizacja,

                # GOSPODARKA
                "pkb": pkb,
                "pkb_per_capita": pkb_per_capita,
                "waluta": panstwo.panstwo_waluta,

                # SPOŁECZEŃSTWO
                "jezyk": panstwo.panstwo_jezyk,
                "religia": panstwo.panstwo_religia,

                # INFRASTRUKTURA
                "infrastruktura": infrastruktura,

                # ADMINISTRACJA
                "liczba_regionow": len(regiony),
                "liczba_miast": len(miasta),

                # NIEZALEŻNOŚĆ
                "czy_suwerenny": czy_suwerenny,

                "status_niezaleznosci": (
                    "Państwo suwerenne"
                    if czy_suwerenny
                    else "Państwo niesuwerenne"
                ),

                # FLAGA
                "flaga": url_for(
                    "static",
                    filename=(
                        "flags/"
                        + panstwo.panstwo_nazwa.replace(" ", "_")
                        + ".jpg"
                    )
                )
            }

        return jsonify(wynik)
    
    @app.route("/")
    def root():
        return redirect(url_for("wejscie"))
    
    @app.route("/home")
    def home_page():
            
            kontynenty = DictKontynent.query.order_by(
                DictKontynent.kontynent_nazwa
            ).all()

            return render_template(
                "zeus_home.html",
                kontynenty=kontynenty
            )

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

    @app.route("/info_test")
    def info_test():
        return str(INFO_FILE)
    
