from flask import render_template, request, redirect, url_for, jsonify, flash
from extensions import db
from models import Flora, Panstwo, DictKontynent
from sqlalchemy.orm import selectinload
from permissions import wymaga_roli


def init_natura_routes(app):

    # =========================================
    # LISTA + FILTRY
    # =========================================
    @app.route("/flora")
    def flora_lista():

        kontynent = request.args.get("kontynent_id")
        panstwo_id = request.args.get("panstwo_id")
        flora_id = request.args.get("flora_id")
        selected_kontynent = kontynent
        selected_panstwo = panstwo_id
        selected_flora = flora_id

        query = Flora.query.options(
            selectinload(Flora.panstwa),
            selectinload(Flora.kontynenty)
        )

        if flora_id:
            query = query.filter(Flora.flora_id == flora_id)

        elif panstwo_id:
            query = query.join(Flora.panstwa).filter(
                Panstwo.PANSTWO_ID == panstwo_id
            )

        elif kontynent:
            query = query.join(Flora.kontynenty).filter(
                DictKontynent.kontynent_id == kontynent
            )

        results = query.all()

        for f in results:
            f.panstwa_names = ", ".join(p.panstwo_nazwa for p in f.panstwa) if f.panstwa else None
            f.kontynenty_names = ", ".join(k.kontynent_nazwa for k in f.kontynenty) if f.kontynenty else None

        # ✅ POPRAWNIE – obiekty Kontynent (z nazwą)
        kontynenty = DictKontynent.query.order_by(DictKontynent.kontynent_nazwa).all()

        flora_all = Flora.query.all()

        return render_template(
            "flora_lista.html",
            results=results,
            kontynenty=kontynenty,
            flora_all=flora_all,
            selected_kontynent=selected_kontynent,
            selected_panstwo=selected_panstwo,
            selected_flora=selected_flora
        )

    # =========================================
    # API: państwa po kontynencie (do selecta)
    # =========================================
    @app.route("/api/panstwa_by_kontynent")
    def panstwa_by_kontynent():

        kontynent = request.args.get("kontynent_id", type=int)

        if not kontynent:
            return jsonify([])

        panstwa = Panstwo.query.filter_by(kontynent_id=kontynent).all()

        return jsonify([
            {"id": p.PANSTWO_ID, "nazwa": p.panstwo_nazwa}
            for p in panstwa
        ])


    # =========================================
    # PODGLĄD
    # =========================================
    @app.route("/flora/<int:flora_id>")
    def flora_form(flora_id):

        flora = Flora.query.options(
            selectinload(Flora.panstwa),
            selectinload(Flora.kontynenty)
        ).get_or_404(flora_id)

        panstwa = ", ".join(p.panstwo_nazwa for p in flora.panstwa) if flora.panstwa else None
        kontynenty = ", ".join(k.kontynent_nazwa for k in flora.kontynenty) if flora.kontynenty else None

        return render_template(
            "flora_form.html",
            flora=flora,
            panstwa=panstwa,
            kontynenty=kontynenty
        )

    # =========================================
    # DODAWANIE
    # =========================================
    @app.route("/flora/add", methods=["GET", "POST"])
    @wymaga_roli("tworzyciel", "wszechmocny")
    def flora_add():

        if request.method == "POST":

            nazwa = request.form.get("nazwa")
            opis = request.form.get("opis")

            if not nazwa or not opis:
                return render_template(
                    "flora_form_add.html",
                    error="Nazwa i opis są wymagane.",
                    form_data=request.form
                )

            flora = Flora(
                nazwa=nazwa,
                opis=opis
            )

            # ===== RELACJE =====
            panstwa_ids = request.form.getlist("panstwo_id")
            kontynenty_ids = request.form.getlist("kontynent_id")

            flora.panstwa = Panstwo.query.filter(
                Panstwo.PANSTWO_ID.in_(panstwa_ids)
            ).all()

            flora.kontynenty = DictKontynent.query.filter(
                DictKontynent.kontynent_id.in_(kontynenty_ids)
            ).all()

            # ===== OBRAZ =====
            obraz = request.files.get("obraz")

            if obraz and obraz.filename:
                if obraz.mimetype not in ["image/png", "image/jpeg"]:
                    return render_template(
                        "flora_form_add.html",
                        error="Dozwolone formaty: JPG, PNG",
                        form_data=request.form
                    )

                flora.flora_obraz = obraz.read()
                flora.flora_obraz_mime = obraz.mimetype

            # ===== SAVE =====
            try:
                db.session.add(flora)
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                return render_template(
                    "flora_form_add.html",
                    error=f"Błąd zapisu: {e}",
                    form_data=request.form
                )

            return redirect(url_for("flora_lista"))

        # ===== GET =====
        kontynenty = DictKontynent.query.order_by(DictKontynent.kontynent_nazwa).all()

        return render_template(
            "flora_form_add.html",
            kontynenty=kontynenty
        )

    # =========================================
    # EDYCJA
    # =========================================
    @app.route("/flora/<int:flora_id>/edit", methods=["GET", "POST"])
    @wymaga_roli("wszechmocny")
    def flora_edit(flora_id):

        flora = Flora.query.options(
            selectinload(Flora.panstwa),
            selectinload(Flora.kontynenty)
        ).get_or_404(flora_id)

        selected_panstwa = [p.PANSTWO_ID for p in flora.panstwa]
        selected_kontynenty = [k.kontynent_id for k in flora.kontynenty]

        # =========================
        # POST – ZAPIS
        # =========================
        if request.method == "POST":

            nazwa = request.form.get("nazwa")
            opis = request.form.get("opis")

            # --- WALIDACJA ---
            if not nazwa or not opis:
                kontynenty = DictKontynent.query.order_by(DictKontynent.kontynent_nazwa).all()

                return render_template(
                    "flora_form_edit.html",
                    flora=flora,
                    kontynenty=kontynenty,
                    selected_kontynenty=selected_kontynenty,
                    selected_panstwa=selected_panstwa,
                    error="Nazwa i opis są wymagane."
                )

            # --- AKTUALIZACJA ---
            flora.nazwa = nazwa
            flora.opis = opis

            panstwa_ids = request.form.getlist("panstwo_id")
            kontynenty_ids = request.form.getlist("kontynent_id")

            flora.panstwa = Panstwo.query.filter(
                Panstwo.PANSTWO_ID.in_(panstwa_ids)
            ).all()

            flora.kontynenty = DictKontynent.query.filter(
                DictKontynent.kontynent_id.in_(kontynenty_ids)
            ).all()

            # --- OBRAZ ---
            obraz = request.files.get("obraz")

            if obraz and obraz.filename:
                if obraz.mimetype not in ["image/png", "image/jpeg"]:
                    kontynenty = DictKontynent.query.order_by(DictKontynent.kontynent_nazwa).all()

                    return render_template(
                        "flora_form_edit.html",
                        flora=flora,
                        kontynenty=kontynenty,
                        selected_kontynenty=selected_kontynenty,
                        selected_panstwa=selected_panstwa,
                        error="Dozwolone formaty: JPG, PNG"
                    )

                flora.flora_obraz = obraz.read()
                flora.flora_obraz_mime = obraz.mimetype

            # --- SAVE ---
            db.session.commit()

            return redirect(url_for("flora_form", flora_id=flora_id))

        # =========================
        # GET – FORMULARZ
        # =========================

        kontynenty = DictKontynent.query.order_by(DictKontynent.kontynent_nazwa).all()

        selected_kontynenty = [k.kontynent_id for k in flora.kontynenty]
        selected_panstwa = [p.PANSTWO_ID for p in flora.panstwa]

        return render_template(
            "flora_form_edit.html",
            flora=flora,
            kontynenty=kontynenty,
            selected_kontynenty=selected_kontynenty,
            selected_panstwa=selected_panstwa
        )


    # =========================================
    # USUWANIE
    # =========================================
    @app.route("/flora/<int:flora_id>/delete", methods=["POST"])
    @wymaga_roli("wszechmocny")
    def flora_delete(flora_id):

        flora = Flora.query.get_or_404(flora_id)

        try:
            db.session.delete(flora)
            db.session.commit()
            flash("Roślina została usunięta.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Błąd usuwania: {e}", "error")

        return redirect(url_for("flora_lista"))


    # =========================================
    # OBRAZ (endpoint do <img>)
    # =========================================
    @app.route("/flora/<int:flora_id>/image")
    def flora_image(flora_id):

        flora = Flora.query.get_or_404(flora_id)

        if not flora.flora_obraz:
            return "", 404

        return flora.flora_obraz, 200, {
            "Content-Type": flora.flora_obraz_mime
        }