# routes_regiony.py
from flask import render_template, request, redirect, url_for, flash, abort
from extensions import db
from models import Region, Panstwo, Miasto
from permissions import wymaga_roli


def init_regiony_routes(app):

            ### WYSZUKIWANIE REGIONU ###

    @app.route("/wyniki_wyszukiwania_region", methods=["GET"])
    def wyniki_wyszukiwania_region():
        panstwo_nazwa = request.args.get("panstwo_nazwa")
        region_nazwa = request.args.get("region_nazwa")
        region_ludnosc_pozamiejska = request.form.get("region_ludnosc_pozamiejska")

        query = db.session.query(Region, Panstwo).join(
            Panstwo, Region.panstwo_id == Panstwo.PANSTWO_ID
        )

        if panstwo_nazwa:
            query = query.filter(Panstwo.panstwo_nazwa.like(f"%{panstwo_nazwa}%"))

        if region_nazwa:
            query = query.filter(Region.region_nazwa.like(f"%{region_nazwa}%"))

        rows = query.all()

        results = [
            {
                "region_id": r.region_id,
                "region_nazwa": r.region_nazwa,
                "region_populacja": r.region_populacja or 0,
                "panstwo_nazwa": p.panstwo_nazwa,
                "region_ludnosc_pozamiejska": r.region_ludnosc_pozamiejska or 0,
            }
            for r, p in rows
        ]

        empty = len(results) == 0

        return render_template(
            "wyniki_wyszukiwania_region.html", results=results, empty=empty
        )

        ### DODAWANIE REGIONU ###

    @app.route("/region_form_add", methods=["GET", "POST"])
    @wymaga_roli("tworzyciel", "wszechmocny")
    def region_add_form():
        if request.method == "POST":
            errors = []

            nazwa = request.form.get("region_nazwa")
            populacja = request.form.get("region_populacja")
            panstwo_id = request.form.get("panstwo_id")

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
                db.session.query(Region, Panstwo)
                .join(Panstwo, Region.panstwo_id == Panstwo.PANSTWO_ID)
                .filter(Region.region_nazwa == nazwa)
                .all()
            )

            if duplicates:
                duplicates_info = [
                    f"{reg.region_nazwa} — państwo: {pan.panstwo_nazwa}, populacja regionu: {reg.region_populacja}"
                    for reg, pan in duplicates
                ]

                return render_template(
                    "region_form_add.html",
                    error="Region o takiej nazwie już istnieje.",
                    duplicates=duplicates_info,
                    form_data=request.form,
                )

            try:
                new_region = Region(
                    region_nazwa=nazwa,
                    region_populacja=populacja,
                    panstwo_id=panstwo_id,
                )
                db.session.add(new_region)
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                return render_template(
                    "region_form_add.html",
                    error=f"Błąd podczas zapisu regionu: {e}",
                    form_data=request.form,
                )

            return redirect(url_for("region_dodano"))

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

            # ───── WALIDACJA ─────
            errors = []

            if not nazwa:
                errors.append("Nazwa regionu jest wymagana.")

            if not panstwo_id or not panstwo_id.isdigit():
                errors.append("ID państwa musi być liczbą.")

            if not ludnosc_pozamiejska or not ludnosc_pozamiejska.isdigit():
                errors.append("Ludność pozamiejska musi być liczbą.")

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

            db.session.commit()

            flash(
                f"Pomyślnie zaktualizowano region o ID {region.region_id}.",
                "success"
            )
            return redirect(url_for("region_form", region_id=region.region_id))

        # ───── GET ─────
        return render_template("region_form_edit.html", region=region)

@app.route("/api/panstwa_by_kontynent")
def api_panstwa_by_kontynent():
    kontynent = request.args.get("kontynent")
    if not kontynent:
        return jsonify([])

    panstwa = Panstwo.query.filter_by(kontynent=kontynent).order_by(Panstwo.panstwo_nazwa).all()

    return jsonify([
        {
            "PANSTWO_ID": p.PANSTWO_ID,
            "panstwo_nazwa": p.panstwo_nazwa
        }
        for p in panstwa
    ])
