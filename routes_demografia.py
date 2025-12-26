# routes_demografia.py

from flask import (
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify
)

from extensions import db
from models import Panstwo, Region, Miasto
from permissions import wymaga_roli
from sqlalchemy import func
import random


def init_demografia_routes(app):

    # ============================================================
    # KALKULATOR DEMOGRAFICZNY
    # ============================================================

    @app.route("/demografia/kalkulator", methods=["GET"])
    def demografia_kalkulator():

        kontynent = request.args.get("kontynent")
        panstwo_id = request.args.get("panstwo_id")

        kontynenty = (
            db.session.query(Panstwo.kontynent)
            .distinct()
            .order_by(Panstwo.kontynent)
            .all()
        )
        kontynenty = [k[0] for k in kontynenty if k[0]]

        panstwa = []
        panstwo = None
        regiony = None

        if kontynent:
            panstwa = (
                Panstwo.query
                .filter_by(kontynent=kontynent)
                .order_by(Panstwo.panstwo_nazwa)
                .all()
            )

        if panstwo_id and panstwo_id.isdigit():
            panstwo = Panstwo.query.get(int(panstwo_id))
            if panstwo:
                regiony = (
                    db.session.query(
                        Region.region_id,
                        Region.region_nazwa,
                        Region.region_populacja,
                        Region.region_ludnosc_pozamiejska,
                        func.coalesce(
                            func.sum(Miasto.miasto_populacja), 0
                        ).label("ludnosc_miejska")
                    )
                    .outerjoin(Miasto, Miasto.region_id == Region.region_id)
                    .filter(Region.panstwo_id == panstwo.PANSTWO_ID)
                    .group_by(
                        Region.region_id,
                        Region.region_nazwa,
                        Region.region_populacja,
                        Region.region_ludnosc_pozamiejska
                    )
                    .order_by(Region.region_nazwa)
                    .all()
                )

        return render_template(
            "demografia_kalkulator.html",
            kontynenty=kontynenty,
            panstwa=panstwa,
            selected_kontynent=kontynent,
            panstwo=panstwo,
            regiony=regiony
        )

    # ============================================================
    # GENERATOR MIAST TECHNICZNYCH
    # ============================================================

    @app.route("/demografia/generator_miast", methods=["GET", "POST"])
    @wymaga_roli("tworzyciel", "wszechmocny")
    def demografia_generator_miast():

        kontynenty = (
            db.session.query(Panstwo.kontynent)
            .distinct()
            .order_by(Panstwo.kontynent)
            .all()
        )
        kontynenty = [k[0] for k in kontynenty if k[0]]

        if request.method == "POST":

            kontynent = request.form.get("kontynent")
            panstwo_id = request.form.get("panstwo_id")
            region_id = request.form.get("region_id")
            ilosc = request.form.get("ilosc")
            min_pop = request.form.get("min_pop")
            max_pop = request.form.get("max_pop")
            confirm = request.form.get("confirm")

            errors = []

            if not kontynent or not panstwo_id or not region_id:
                errors.append("Musisz wybrać kontynent, państwo i region.")

            if not ilosc or not ilosc.isdigit() or int(ilosc) <= 0:
                errors.append("Ilość miast musi być dodatnią liczbą.")

            if not min_pop or not max_pop or not min_pop.isdigit() or not max_pop.isdigit():
                errors.append("Zakres ludności musi być liczbowy.")

            if errors:
                return render_template(
                    "demografia_generator.html",
                    error=" ".join(errors),
                    kontynenty=kontynenty
                )

            ilosc = int(ilosc)
            min_pop = int(min_pop)
            max_pop = int(max_pop)

            if min_pop > max_pop:
                return render_template(
                    "demografia_generator.html",
                    error="Minimalna populacja nie może być większa niż maksymalna.",
                    kontynenty=kontynenty
                )

            region = Region.query.get(int(region_id))
            if not region:
                return render_template(
                    "demografia_generator.html",
                    error="Wybrany region nie istnieje.",
                    kontynenty=kontynenty
                )

            populacje = [random.randint(min_pop, max_pop) for _ in range(ilosc)]
            suma_pop = sum(populacje)
            pula = region.region_ludnosc_pozamiejska or 0

            if suma_pop > pula * 0.5 and confirm != "yes":
                return render_template(
                    "demografia_generator.html",
                    warning=(
                        f"Wygenerowanie tych miast odbierze regionowi "
                        f"{region.region_nazwa} ponad 50% jego ludności pozamiejskiej. "
                        f"Czy chcesz kontynuować?"
                    ),
                    confirm_required=True,
                    form_data=request.form,
                    kontynenty=kontynenty
                )

            try:
                for pop in populacje:
                    while True:
                        suffix = random.randint(0, 999_999_999)
                        nazwa = f"Miasto Techniczne {suffix:09d}"
                        if not Miasto.query.filter_by(miasto_nazwa=nazwa).first():
                            break

                    miasto = Miasto(
                        miasto_nazwa=nazwa,
                        miasto_populacja=pop,
                        panstwo_id=region.panstwo_id,
                        region_id=region.region_id,
                        miasto_typ="miasto",
                        czy_na_mapie="NIE",
                        czy_generowane="TAK"
                    )

                    db.session.add(miasto)

                region.region_ludnosc_pozamiejska -= suma_pop
                db.session.commit()

                flash(f"Wygenerowano {ilosc} miast technicznych.", "success")
                return redirect(url_for("demografia_generator_miast"))

            except Exception as e:
                db.session.rollback()
                return render_template(
                    "demografia_generator.html",
                    error=f"Błąd zapisu do bazy: {e}",
                    kontynenty=kontynenty
                )

        return render_template(
            "demografia_generator.html",
            kontynenty=kontynenty
        )

    # ============================================================
    # API – DYNAMICZNE SELECTY (GENERATOR)
    # ============================================================

    @app.route("/api/panstwa_by_kontynent")
    def api_panstwa_by_kontynent():
        kontynent = request.args.get("kontynent")
        if not kontynent:
            return jsonify([])

        panstwa = (
            Panstwo.query
            .filter_by(kontynent=kontynent)
            .order_by(Panstwo.panstwo_nazwa)
            .all()
        )

        return jsonify([
            {"PANSTWO_ID": p.PANSTWO_ID, "panstwo_nazwa": p.panstwo_nazwa}
            for p in panstwa
        ])

    @app.route("/api/regiony_by_panstwo")
    def api_regiony_by_panstwo():
        panstwo_id = request.args.get("panstwo_id")
        if not panstwo_id or not panstwo_id.isdigit():
            return jsonify([])

        regiony = (
            Region.query
            .filter_by(panstwo_id=int(panstwo_id))
            .order_by(Region.region_nazwa)
            .all()
        )

        return jsonify([
            {"region_id": r.region_id, "region_nazwa": r.region_nazwa}
            for r in regiony
        ])
    
        # ============================================================
    # PODSUMOWANIE LUDNOŚCI (KONTYNENT / PAŃSTWO)
    # ============================================================

    @app.route("/demografia/ludnosc", methods=["GET"])
    def demografia_ludnosc():

        kontynent = request.args.get("kontynent")
        panstwo_id = request.args.get("panstwo_id")

        # lista kontynentów
        kontynenty = (
            db.session.query(Panstwo.kontynent)
            .distinct()
            .order_by(Panstwo.kontynent)
            .all()
        )
        kontynenty = [k[0] for k in kontynenty if k[0]]

        # lista państw (jeśli wybrano kontynent)
        panstwa = []
        if kontynent:
            panstwa = (
                Panstwo.query
                .filter_by(kontynent=kontynent)
                .order_by(Panstwo.panstwo_nazwa)
                .all()
            )

        dane = None
        tryb = None

        if kontynent and not panstwo_id:
            dane = licz_dane_kontynentu(kontynent)
            tryb = "kontynent"

        elif kontynent and panstwo_id and panstwo_id.isdigit():
            dane = licz_dane_panstwa(int(panstwo_id))
            tryb = "panstwo"

        return render_template(
            "demografia_ludnosc.html",
            kontynenty=kontynenty,
            panstwa=panstwa,
            selected_kontynent=kontynent,
            selected_panstwo_id=panstwo_id,
            dane=dane,
            tryb=tryb
        )

