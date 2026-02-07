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
from services.demografia_ludnosc import licz_dane_kontynentu, licz_dane_panstwa
import random
from flask import jsonify
from datetime import datetime


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
    @wymaga_roli("wszechmocny")
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

            if ilosc > 100:
                return render_template(
                    "demografia_generator.html",
                    error="Nie można wygenerować więcej niż 100 miast za jednym razem.",
                    form_data=request.form,
                    kontynenty=kontynenty
                )
            
            # miękkie ostrzeżenie
            if ilosc > 50 and confirm is None:
                return render_template(
                    "demografia_generator.html",
                    warning=(
                        f"Zamierzasz wygenerować {ilosc} miast. "
                        "Może to istotnie wpłynąć na strukturę demograficzną regionu. "
                        "Czy chcesz kontynuować?"
                    ),
                    confirm_required=True,
                    form_data=request.form,
                    kontynenty=kontynenty
                )

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

            if confirm == "no":
                return render_template(
                    "demografia_generator.html",
                    info="Anulowano generowanie miast.",
                    form_data=request.form,
                    kontynenty=kontynenty
                )

            if suma_pop > pula * 0.9 and confirm is None:
                return render_template(
                    "demografia_generator.html",
                    warning=(
                        f"Wygenerowanie tych miast odbierze regionowi "
                        f"{region.region_nazwa} ponad 90% jego ludności pozamiejskiej. "
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

    from datetime import datetime

    @app.route("/demografia/kalkulator/<int:panstwo_id>/zapisz", methods=["POST"])
    def demografia_kalkulator_zapisz(panstwo_id):
        data = request.get_json()

        if not data or "regions" not in data:
            return jsonify(success=False, error="Brak danych regionów"), 400

        try:
            total_population = 0

            for r in data["regions"]:
                region_id = r.get("region_id")
                if not region_id:
                    raise ValueError("Brak region_id w payloadzie")

                region = Region.query.get(region_id)
                if not region:
                    raise ValueError(f"Region ID {region_id} nie istnieje")

                # ─── ODCZYT + WALIDACJA ───
                pop_region = int(r.get("region_populacja", 0))
                pop_pozam = int(r.get("region_ludnosc_pozamiejska", 0))

                if pop_region < 0:
                    raise ValueError(
                        f"Populacja regionu (ID {region_id}) nie może być ujemna"
                    )

                if pop_pozam < 0:
                    raise ValueError(
                        f"Ludność pozamiejska regionu (ID {region_id}) nie może być ujemna"
                    )

                # ─── ZAPIS DO MODELU ───
                region.region_populacja = pop_region
                region.region_ludnosc_pozamiejska = pop_pozam

                total_population += pop_region

            # ─── PAŃSTWO + AUDYT POPULACJI ───
            panstwo = Panstwo.query.get_or_404(panstwo_id)

            if panstwo.panstwo_populacja != total_population:
                panstwo.panstwo_populacja = total_population
                panstwo.panstwo_populacja_audit = datetime.utcnow()

            db.session.commit()

            return jsonify(
                success=True,
                panstwo_populacja=total_population
            )

        except Exception as e:
            db.session.rollback()
            return jsonify(
                success=False,
                error=str(e)
            ), 500


    def licz_dane_panstwa(panstwo_id):
        p = Panstwo.query.get_or_404(panstwo_id)

        regiony = (
            db.session.query(
                Region.region_nazwa,
                Region.region_populacja
            )
            .filter(Region.panstwo_id == panstwo_id)
            .all()
        )

        liczba_regionow = len(regiony)
        populacja = p.panstwo_populacja or 0
        powierzchnia = p.panstwo_powierzchnia or 0

        gestosc = round(populacja / powierzchnia, 2) if powierzchnia else 0

        liczba_miast = Miasto.query.filter_by(panstwo_id=panstwo_id).count()

        ludnosc_miejska = (
            db.session.query(func.coalesce(func.sum(Miasto.miasto_populacja), 0))
            .filter(Miasto.panstwo_id == panstwo_id)
            .scalar()
        )

        urbanizacja = round((ludnosc_miejska / populacja) * 100, 2) if populacja else 0
        srednia_region = round(populacja / liczba_regionow) if liczba_regionow else 0

        top_miasta = (
            Miasto.query
            .filter_by(panstwo_id=panstwo_id)
            .order_by(Miasto.miasto_populacja.desc())
            .limit(3)
            .all()
        )

        return {
            "nazwa": p.panstwo_nazwa,
            "populacja": populacja,
            "powierzchnia": powierzchnia,
            "gestosc": gestosc,
            "liczba_regionow": liczba_regionow,
            "regiony": [
                {"nazwa": r.region_nazwa, "populacja": r.region_populacja}
                for r in regiony
            ],
            "liczba_miast": liczba_miast,
            "urbanizacja_pct": urbanizacja,
            "srednia_region": srednia_region,
            "top_miasta": [
                {
                    "miasto_nazwa": m.miasto_nazwa,
                    "miasto_populacja": m.miasto_populacja
                }
                for m in top_miasta
            ]
        }


