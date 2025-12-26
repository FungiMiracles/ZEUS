from flask import render_template, request
from extensions import db
from models import Panstwo, Region, Miasto
from sqlalchemy import func
from flask import jsonify
from permissions import wymaga_roli
from services.demografia_ludnosc import licz_dane_kontynentu

def init_demografia_routes(app):

    # --------------------------------
    # KALKULATOR DEMOGRAFICZNY
    # --------------------------------
    @app.route("/demografia/kalkulator", methods=["GET"])
    def demografia_kalkulator():

        kontynent = request.args.get("kontynent")
        panstwo_id = request.args.get("panstwo_id")

        # ===== LISTA KONTYNENTÓW =====
        kontynenty = (
            db.session.query(Panstwo.kontynent)
            .distinct()
            .all()
        )
        kontynenty = [k[0] for k in kontynenty if k[0]]

        panstwa = []
        panstwo = None
        regiony = None

        # ===== LISTA PAŃSTW =====
        if kontynent:
            panstwa = Panstwo.query.filter_by(
                kontynent=kontynent
            ).order_by(Panstwo.panstwo_nazwa).all()

        # ===== REGIONY DO KALKULATORA =====
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

    # --------------------------------
    # ZAPIS DANYCH DEMOGRAFICZNYCH
    # --------------------------------
    @app.route("/demografia/kalkulator/<int:panstwo_id>/zapisz", methods=["POST"])
    def demografia_kalkulator_zapisz(panstwo_id):

        data = request.get_json()
        if not data or "regions" not in data:
            return jsonify(success=False, error="Brak danych regionów")

        try:
            total_population = 0

            for r in data["regions"]:
                region = Region.query.get(r["region_id"])
                if not region:
                    raise ValueError(f"Region ID {r['region_id']} nie istnieje")

                region.region_ludnosc_pozamiejska = r["region_ludnosc_pozamiejska"]
                region.region_populacja = r["region_populacja"]
                total_population += r["region_populacja"]

            panstwo = Panstwo.query.get_or_404(panstwo_id)
            panstwo.panstwo_populacja = total_population

            db.session.commit()

            return jsonify(success=True, panstwo_populacja=total_population)

        except Exception as e:
            db.session.rollback()
            return jsonify(success=False, error=str(e))

    @app.route("/demografia/ludnosc", methods=["GET"])
    def demografia_ludnosc():
    
        kontynent = request.args.get("kontynent")
        panstwo_id = request.args.get("panstwo_id")
    
        # lista kontynentów
        kontynenty = (
            db.session.query(Panstwo.kontynent)
            .distinct()
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

    @app.route("/demografia/generator_miast", methods=["GET", "POST"])
    def demografia_generator_miast():
    
            # --------------------------
            # DANE DO SELECTÓW (GET)
            # --------------------------
            kontynenty = (
                db.session.query(Panstwo.kontynent)
                .distinct()
                .order_by(Panstwo.kontynent)
                .all()
            )
            kontynenty = [k[0] for k in kontynenty if k[0]]
    
            panstwa = []
            regiony = []
    
            # --------------------------
            # POST – GENEROWANIE
            # --------------------------
            if request.method == "POST":
    
                kontynent = request.form.get("kontynent")
                panstwo_id = request.form.get("panstwo_id")
                region_id = request.form.get("region_id")
                ilosc = request.form.get("ilosc")
                min_pop = request.form.get("min_pop")
                max_pop = request.form.get("max_pop")
                confirm = request.form.get("confirm")
    
                # --- WALIDACJA PODSTAWOWA ---
                errors = []
    
                if not (kontynent and panstwo_id and region_id):
                    errors.append("Musisz wybrać kontynent, państwo i region.")
    
                if not (ilosc and ilosc.isdigit() and int(ilosc) > 0):
                    errors.append("Ilość miast musi być dodatnią liczbą.")
    
                if not (min_pop and max_pop and min_pop.isdigit() and max_pop.isdigit()):
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
                        error="Minimalna ludność nie może być większa niż maksymalna.",
                        kontynenty=kontynenty
                    )
    
                region = Region.query.get(int(region_id))
                if not region:
                    return render_template(
                        "demografia_generator.html",
                        error="Wybrany region nie istnieje.",
                        kontynenty=kontynenty
                    )
    
                # --------------------------
                # SYMULACJA POPULACJI
                # --------------------------
                populacje = [
                    random.randint(min_pop, max_pop)
                    for _ in range(ilosc)
                ]
    
                suma_pop = sum(populacje)
                pula = region.region_ludnosc_pozamiejska or 0
    
                # OSTRZEŻENIE 50%
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
    
                # --------------------------
                # ZAPIS DO BAZY
                # --------------------------
                try:
                    for pop in populacje:
    
                        # unikalna nazwa
                        while True:
                            suffix = random.randint(0, 999_999_999)
                            nazwa = f"Miasto Techniczne {suffix:09d}"
                            exists = Miasto.query.filter_by(miasto_nazwa=nazwa).first()
                            if not exists:
                                break
    
                        miasto = Miasto(
                            miasto_nazwa=nazwa,
                            miasto_populacja=pop,
                            panstwo_id=region.panstwo_id,
                            region_id=region.region_id,
                            miasto_typ="miasto",
                            czy_na_mapie=False,
                            czy_generowane=True
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
    
            # --------------------------
            # GET
            # --------------------------
            return render_template(
                "demografia_generator.html",
                kontynenty=kontynenty
            )
