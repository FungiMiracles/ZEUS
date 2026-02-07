# routes_regiony.py
from flask import render_template, request, redirect, url_for, flash, abort, jsonify
from extensions import db
from models import Region, Panstwo, Miasto
from permissions import wymaga_roli
from flask import Response, send_file
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PLACEHOLDER_PATH = os.path.join(BASE_DIR, "static", "region_placeholder.jpg")

with open(PLACEHOLDER_PATH, "rb") as f:
    REGION_PLACEHOLDER_BYTES = f.read()

def init_regiony_routes(app):

            ### WYSZUKIWANIE REGIONU ###

    @app.route("/wyniki_wyszukiwania_region", methods=["GET"])
    def wyniki_wyszukiwania_region():

        kontynent = request.args.get("kontynent")
        panstwo_id = request.args.get("panstwo_id")
        populacja_od = request.args.get("populacja_od")
        populacja_do = request.args.get("populacja_do")
        uksztaltowanie = request.args.get("ukszaltowanie")

        # ===== LISTY DO FILTRÓW =====
        kontynenty = [
            k[0] for k in db.session.query(Panstwo.kontynent).distinct().all()
            if k[0]
        ]

        uksztaltowania = [
            u[0] for u in db.session.query(Region.region_teren).distinct().all()
            if u[0]
        ]

        # ===== BAZOWE ZAPYTANIE =====
        query = (
            db.session.query(Region, Panstwo)
            .join(Panstwo, Region.panstwo_id == Panstwo.PANSTWO_ID)
        )

        if kontynent:
            query = query.filter(Panstwo.kontynent == kontynent)

        if panstwo_id and panstwo_id.isdigit():
            query = query.filter(Region.panstwo_id == int(panstwo_id))

        if populacja_od and populacja_od.isdigit():
            query = query.filter(Region.region_populacja >= int(populacja_od))

        if populacja_do and populacja_do.isdigit():
            query = query.filter(Region.region_populacja <= int(populacja_do))

        if uksztaltowanie:
            query = query.filter(Region.region_teren == uksztaltowanie)

        rows = query.order_by(Region.region_populacja.desc()).all()

        results = [
            {
                "region_id": r.region_id,
                "region_nazwa": r.region_nazwa,
                "region_populacja": r.region_populacja or 0,
                "region_ludnosc_pozamiejska": getattr(r, "region_ludnosc_pozamiejska", 0),
                "panstwo_nazwa": p.panstwo_nazwa,
            }
            for r, p in rows
        ]

        return render_template(
            "wyniki_wyszukiwania_region.html",
            results=results,
            empty=len(results) == 0,
            kontynenty=kontynenty,
            uksztaltowania=ukszaltowania
        )


    @app.route("/region_form_add", methods=["GET", "POST"])
    @wymaga_roli("tworzyciel", "wszechmocny")
    def region_add_form():
        if request.method == "POST":
            errors = []
    
            nazwa = request.form.get("region_nazwa")
            populacja = request.form.get("region_populacja")
            panstwo_id = request.form.get("panstwo_id")
            region_teren = request.form.get("region_teren")
    
            if not nazwa:
                errors.append("Pole 'Nazwa regionu' jest wymagane.")
    
            if not populacja:
                errors.append("Pole 'Populacja regionu' jest wymagane.")
            elif not populacja.isdigit():
                errors.append("Pole 'Populacja regionu' musi być liczbą.")
    
            if not panstwo_id:
                errors.append("Pole 'ID państwa' jest wymagane.")
            elif not panstwo_id.isdigit():
                errors.append("Pole 'ID państwa' musi być liczbą.")

            DOZWOLONE_TERENY = {
                "wysokogorski",
                "gorski",
                "wyzynny",
                "pogorski",
                "nizinny",
                "depresyjny"
            }

            if region_teren and region_teren not in DOZWOLONE_TERENY:
                errors.append("Nieprawidłowe ukształtowanie terenu.")
    
            if errors:
                return render_template(
                    "region_form_add.html",
                    error=" ".join(errors),
                    form_data=request.form,
                )
    
            populacja = int(populacja)
            panstwo_id = int(panstwo_id)
    
            panstwo = Panstwo.query.get(panstwo_id)
            if not panstwo:
                return render_template(
                    "region_form_add.html",
                    error=f"Państwo o ID {panstwo_id} nie istnieje.",
                    form_data=request.form,
                )
    
            duplicates = (
                db.session.query(Region)
                .filter(Region.region_nazwa == nazwa)
                .all()
            )
    
            if duplicates:
                return render_template(
                    "region_form_add.html",
                    error="Region o takiej nazwie już istnieje.",
                    form_data=request.form,
                )
    
            # ───── UTWORZENIE REGIONU ─────
            new_region = Region(
                region_nazwa=nazwa,
                region_populacja=populacja,
                panstwo_id=panstwo_id,
                region_teren=region_teren or None
            )
    
            # ───── OPCJONALNA MAPA ─────
            file = request.files.get("region_map")
    
            if file and file.filename:
                if file.mimetype not in ("image/jpeg", "image/png"):
                    return render_template(
                        "region_form_add.html",
                        error="Mapa regionu musi być plikiem JPG lub PNG.",
                        form_data=request.form,
                    )
    
                file_bytes = file.read()
                MAX_SIZE = 2 * 1024 * 1024  # 2 MB
    
                if len(file_bytes) > MAX_SIZE:
                    return render_template(
                        "region_form_add.html",
                        error="Mapa regionu jest za duża (maks. 2 MB).",
                        form_data=request.form,
                    )
    
                new_region.region_mapa = file_bytes
                new_region.region_mapa_mime = file.mimetype
    
            try:
                db.session.add(new_region)
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                return render_template(
                    "region_form_add.html",
                    error=f"Błąd podczas zapisu regionu: {e}",
                    form_data=request.form,
                )
    
            flash("Region został dodany.", "success")
            return redirect(url_for("region_form", region_id=new_region.region_id))
    
        return render_template("region_form_add.html")


    # --------------------------------
    # Usuwanie regionu
    # --------------------------------
    @app.route("/usun_region/<int:region_id>", methods=["POST"])
    @wymaga_roli("wszechmocny")
    def usun_region(region_id):
        region = Region.query.get_or_404(region_id)
        try:
            db.session.delete(region)
            db.session.commit()
            flash(f"Region {region.region_nazwa} został usunięty.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Wystąpił błąd podczas usuwania regionu: {e}", "error")

        return redirect(url_for("wyniki_wyszukiwania_region"))

    # --------------------------------
    # PODGLĄD REGIONU
    # --------------------------------

    @app.route("/region/<int:region_id>")
    def region_form(region_id):
        region = Region.query.get_or_404(region_id)

        panstwo = region.panstwo
        miasta = region.miasta  # lista obiektów Miasto

        return render_template(
            "region_form.html",
            region=region,
            panstwo=panstwo,
            miasta=miasta,
        )


# --------------------------------
# EDYCJA REGIONU
# --------------------------------
    @app.route("/region/<int:region_id>/edit", methods=["GET", "POST"])
    @wymaga_roli("wszechmocny")
    def region_form_edit(region_id):
        region = Region.query.get_or_404(region_id)

        if request.method == "POST":

            nazwa = request.form.get("region_nazwa")
            panstwo_id = request.form.get("panstwo_id")
            ludnosc_pozamiejska = request.form.get("region_ludnosc_pozamiejska")
            region_teren = request.form.get("region_teren")

            # ───── WALIDACJA ─────
            errors = []

            if not nazwa:
                errors.append("Nazwa regionu jest wymagana.")

            if not panstwo_id or not panstwo_id.isdigit():
                errors.append("ID państwa musi być liczbą.")

            if not ludnosc_pozamiejska or not ludnosc_pozamiejska.isdigit():
                errors.append("Ludność pozamiejska musi być liczbą.")

            DOZWOLONE_TERENY = {
                "wysokogorski",
                "gorski",
                "wyzynny",
                "pogorski",
                "nizinny",
                "depresyjny"
            }

            if region_teren and region_teren not in DOZWOLONE_TERENY:
                errors.append("Nieprawidłowe ukształtowanie terenu.")

            if errors:
                return render_template(
                    "region_form_edit.html",
                    error=" ".join(errors),
                    region=region,
                    form_data=request.form
                )

            # ───── KONWERSJE ─────
            panstwo_id = int(panstwo_id)
            ludnosc_pozamiejska = int(ludnosc_pozamiejska)

            # ───── WALIDACJA LOGIKI ŚWIATA ─────
            #if ludnosc_pozamiejska > region.region_populacja:
                #return render_template(
                    #"region_form_edit.html",
                    #error="Ludność pozamiejska nie może być większa niż populacja regionu.",
                    #region=region,
                    #form_data=request.form
                #)

            # ───── AKTUALIZACJA ─────
            region.region_nazwa = nazwa
            region.region_ludnosc_pozamiejska = ludnosc_pozamiejska
            region.panstwo_id = panstwo_id
            region.region_teren = region_teren or None

            file = request.files.get("region_map")

            if file and file.filename:
                if file.mimetype not in ("image/jpeg", "image/png"):
                    db.session.rollback()
                    return render_template(
                        "region_form_edit.html",
                        error="Mapa regionu musi być plikiem JPG lub PNG.",
                        region=region,
                        form_data=request.form
                    )
            
                file_bytes = file.read()

                MAX_SIZE = 2 * 1024 * 1024  # 2 MB

                if len(file_bytes) > MAX_SIZE:
                    db.session.rollback()        
                    return render_template(
                        "region_form_edit.html",
                        error="Mapa regionu jest za duża (maks. 2 MB).",
                        region=region,
                        form_data=request.form
                    )

                region.region_mapa = file_bytes
                region.region_mapa_mime = file.mimetype
                                    
            db.session.commit()

            flash(
                f"Pomyślnie zaktualizowano region o ID {region.region_id}.",
                "success"
            )
            return redirect(url_for("region_form", region_id=region.region_id))

        # ───── GET ─────
        return render_template("region_form_edit.html", region=region)

    @app.route("/region/<int:region_id>/mapa")
    def region_mapa(region_id):
        region = Region.query.get_or_404(region_id)

        if not region.region_mapa:
            return Response(
                REGION_PLACEHOLDER_BYTES,
                mimetype="image/jpeg",
                headers={
                    "Cache-Control": "public, max-age=86400"
                }
            )

        return Response(
            region.region_mapa,
            mimetype=region.region_mapa_mime or "image/jpeg",
            headers={
                "Cache-Control": "public, max-age=86400"
            }
        )

    @app.route("/api/panstwa_by_kontynent")
    def api_panstwa_by_kontynent():
        kontynent = request.args.get("kontynent")

        if not kontynent:
            return jsonify([])

        panstwa = (
            db.session.query(Panstwo.PANSTWO_ID, Panstwo.panstwo_nazwa)
            .filter(Panstwo.kontynent == kontynent)
            .order_by(Panstwo.panstwo_nazwa)
            .all()
        )

        return jsonify([
            {"id": p.PANSTWO_ID, "nazwa": p.panstwo_nazwa}
            for p in panstwa
        ])


            

