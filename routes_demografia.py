from flask import render_template, request
from extensions import db
from models import Panstwo, Region, Miasto
from sqlalchemy import func
from flask import jsonify
from permissions import wymaga_roli


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

