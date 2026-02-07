from flask import render_template, request, jsonify, url_for, redirect, abort, Response
from extensions import db
from models import Religia, ReligiaPerPanstwo, Panstwo
from permissions import wymaga_roli

def init_religia_routes(app):

    # ============================================================
    # STRONA GŁÓWNA MODUŁU RELIGII
    # ============================================================
    @app.route("/religia")
    def religia_home():
        return render_template("religia.html")

    # ============================================================
    # LISTA RELIGII
    # ============================================================
    @app.route("/religia/list", methods=["GET"])
    def religia_list():

        kontynent = request.args.get("kontynent")
        panstwo_id = request.args.get("panstwo")
        religia_id = request.args.get("religia")

        ReligiaNadrzedna = aliased(Religia)

        query = (
            db.session.query(
                Religia.religia_id,
                Religia.religia_nazwa,
                Religia.religia_typ,

                ReligiaNadrzedna.religia_nazwa.label("religia_nadrzedna_nazwa"),

                db.func.min(Panstwo.panstwo_nazwa).label("panstwo_nazwa"),
                db.func.min(Panstwo.kontynent).label("kontynent"),
            )
            .outerjoin(
                ReligiaNadrzedna,
                Religia.religia_nadrzedna_id == ReligiaNadrzedna.religia_id
            )
            .outerjoin(
                ReligiaPerPanstwo,
                Religia.religia_id == ReligiaPerPanstwo.religia_id
            )
            .outerjoin(
                Panstwo,
                Panstwo.PANSTWO_ID == ReligiaPerPanstwo.panstwo_id
            )
            .group_by(
                Religia.religia_id,
                Religia.religia_nazwa,
                Religia.religia_typ,
                ReligiaNadrzedna.religia_nazwa
            )
        )

        if kontynent:
            query = query.filter(Panstwo.kontynent == kontynent)

        if panstwo_id and panstwo_id.isdigit():
            query = query.filter(Panstwo.PANSTWO_ID == int(panstwo_id))

        if religia_id and religia_id.isdigit():
            query = query.filter(Religia.religia_id == int(religia_id))

        rows = query.order_by(Religia.religia_nazwa.asc()).all()

        results = [
            {
                "religia_id": r.religia_id,
                "religia_nazwa": r.religia_nazwa,
                "religia_typ": r.religia_typ,
                "religia_nadrzedna": r.religia_nadrzedna_nazwa,
                "panstwo_nazwa": r.panstwo_nazwa,
                "kontynent": r.kontynent,
            }
            for r in rows
        ]

        kontynenty = (
            db.session.query(Panstwo.kontynent)
            .distinct()
            .order_by(Panstwo.kontynent)
            .all()
        )

        religie = (
            db.session.query(Religia.religia_id, Religia.religia_nazwa)
            .order_by(Religia.religia_nazwa)
            .all()
        )

        return render_template(
            "religia_list.html",
            results=results,
            kontynenty=[k[0] for k in kontynenty],
            religie=religie
        )

    # ============================================================
    # API: PAŃSTWA WG KONTYNENTU
    # ============================================================
    @app.route("/api/religia/panstwa")
    def api_religia_panstwa():
        kontynent = request.args.get("kontynent")

        query = Panstwo.query
        if kontynent:
            query = query.filter(Panstwo.kontynent == kontynent)

        panstwa = query.order_by(Panstwo.panstwo_nazwa).all()

        return jsonify([
            {"id": p.PANSTWO_ID, "nazwa": p.panstwo_nazwa}
            for p in panstwa
        ])

    # ============================================================
    # API: RELIGIE WG PAŃSTWA
    # ============================================================
    @app.route("/api/religia/religie")
    def api_religia_religie():
        panstwo_id = request.args.get("panstwo_id")

        query = (
            db.session.query(
                Religia.religia_id,
                Religia.religia_nazwa
            )
            .outerjoin(ReligiaPerPanstwo,
                  Religia.religia_id == ReligiaPerPanstwo.religia_id)
        )

        if panstwo_id and panstwo_id.isdigit():
            query = query.filter(ReligiaPerPanstwo.panstwo_id == int(panstwo_id))

        religie = (
            query
            .distinct()
            .order_by(Religia.religia_nazwa)
            .all()
        )

        return jsonify([
            {"id": r.religia_id, "nazwa": r.religia_nazwa}
            for r in religie
        ])

    @app.route("/religia_form_add", methods=["GET", "POST"])
    @wymaga_roli("wszechmocny")
    def religia_form_add():

        religie = Religia.query.order_by(Religia.religia_nazwa).all()

        if request.method == "POST":

            nazwa = request.form.get("religia_nazwa")
            typ = request.form.get("religia_typ")
            opis = request.form.get("opis")
            nadrzedna_id = request.form.get("religia_nadrzedna_id") or None

            obraz = request.files.get("religia_obraz")

            if not nazwa or not typ:
                return render_template(
                    "religia_form_add.html",
                    error="Nazwa i typ religii są wymagane.",
                    religie=religie,
                    form_data=request.form
                )

            # obraz (opcjonalny)
            obraz_data = None
            obraz_mime = None
            if obraz and obraz.filename:
                obraz_data = obraz.read()
                obraz_mime = obraz.mimetype

            try:
                religia = Religia(
                    religia_nazwa=nazwa,
                    religia_typ=typ,
                    opis=opis,
                    religia_nadrzedna_id=int(nadrzedna_id) if nadrzedna_id else None,
                    religia_obraz=obraz_data,
                    religia_obraz_mime=obraz_mime
                )

                db.session.add(religia)
                db.session.commit()

            except Exception as e:
                db.session.rollback()
                return render_template(
                    "religia_form_add.html",
                    error=f"Błąd zapisu religii: {e}",
                    religie=religie,
                    form_data=request.form
                )

            return redirect(
                    url_for("religia_form", religia_id=religia.religia_id)
                )

        return render_template(
            "religia_form_add.html",
            religie=religie,
            form_data={}
        )

    @app.route("/religia_przypisz", methods=["GET", "POST"])
    @wymaga_roli("wszechmocny")
    def religia_przypisz_form():

        religie = Religia.query.order_by(Religia.religia_nazwa).all()
        panstwa = Panstwo.query.order_by(Panstwo.panstwo_nazwa).all()

        if request.method == "POST":

            panstwo_id = request.form.get("panstwo_id")
            religia_id = request.form.get("religia_id")
            status = request.form.get("status")
            udzial_proc = request.form.get("udzial_proc")

            errors = []

            if not panstwo_id or not panstwo_id.isdigit():
                errors.append("Wybierz poprawne państwo.")

            if not religia_id or not religia_id.isdigit():
                errors.append("Wybierz poprawną religię.")

            if status not in [
                "dominujaca",
                "oficjalna",
                "mniejszosciowa",
                "historyczna"
            ]:
                errors.append("Wybierz status religii.")

            # udział procentowy – opcjonalny
            if udzial_proc:
                try:
                    udzial_proc = float(udzial_proc)
                    if udzial_proc < 0 or udzial_proc > 100:
                        errors.append("Udział procentowy musi być w zakresie 0–100.")
                except ValueError:
                    errors.append("Udział procentowy musi być liczbą.")
            else:
                udzial_proc = None

            if errors:
                return render_template(
                    "religia_przypisz_form.html",
                    religie=religie,
                    panstwa=panstwa,
                    error=" ".join(errors),
                    form_data=request.form
                )

            # BLOKADA DUPLIKATU (ważne)
            istnieje = ReligiaPerPanstwo.query.filter_by(
                panstwo_id=int(panstwo_id),
                religia_id=int(religia_id)
            ).first()

            if istnieje:
                return render_template(
                    "religia_przypisz_form.html",
                    religie=religie,
                    panstwa=panstwa,
                    error="Ta religia jest już przypisana do wybranego państwa.",
                    form_data=request.form
                )

            przypisanie = ReligiaPerPanstwo(
                panstwo_id=int(panstwo_id),
                religia_id=int(religia_id),
                status=status,
                udzial_proc=udzial_proc
            )

            db.session.add(przypisanie)
            db.session.commit()

            return redirect(url_for("religia_list"))

        return render_template(
            "religia_przypisz_form.html",
            religie=religie,
            panstwa=panstwa,
            form_data={}
        )
    
    @app.route("/religia/<int:religia_id>")
    def religia_form(religia_id):

        religia = Religia.query.get_or_404(religia_id)

        przypisania = ReligiaPerPanstwo.query.filter_by(
            religia_id=religia_id
        ).all()

        return render_template(
            "religia_form.html",
            religia=religia,
            przypisania=przypisania
        )
    
    @app.route("/religia/<int:religia_id>/edit", methods=["GET", "POST"])
    @wymaga_roli("wszechmocny")
    def religia_edit(religia_id):

        religia = Religia.query.get_or_404(religia_id)
        religie = Religia.query.order_by(Religia.religia_nazwa).all()

        if request.method == "POST":

            religia.religia_nazwa = request.form.get("religia_nazwa")
            religia.religia_typ = request.form.get("religia_typ")
            religia.opis = request.form.get("opis")
            religia.religia_nadrzedna_id = (
                int(request.form.get("religia_nadrzedna_id"))
                if request.form.get("religia_nadrzedna_id")
                else None
            )

            obraz = request.files.get("religia_obraz")
            if obraz and obraz.filename:
                religia.religia_obraz = obraz.read()
                religia.religia_obraz_mime = obraz.mimetype

            db.session.commit()

            return redirect(url_for("religia_form", religia_id=religia_id))

        return render_template(
            "religia_form_edit.html",
            religia=religia,
            religie=religie
        )
    
    @app.route("/religia/<int:religia_id>/delete", methods=["POST"])
    @wymaga_roli("wszechmocny")
    def religia_delete(religia_id):

        religia = Religia.query.get_or_404(religia_id)

        db.session.delete(religia)
        db.session.commit()

        return redirect(url_for("religia_list"))
    
    @app.route("/religia/<int:religia_id>/image")
    def religia_image(religia_id):
        religia = Religia.query.get_or_404(religia_id)
        return Response(religia.religia_obraz, mimetype=religia.religia_obraz_mime)


