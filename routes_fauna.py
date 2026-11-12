from flask import render_template, request, redirect, url_for, jsonify, flash
from extensions import db
from models import Fauna, Panstwo, DictKontynent
from sqlalchemy.orm import selectinload
from permissions import wymaga_roli


def init_fauna_routes(app):

    # =========================================
    # LISTA + FILTRY
    # =========================================
    @app.route("/fauna")
    def fauna_lista():

        kontynent = request.args.get("kontynent_id")
        panstwo_id = request.args.get("panstwo_id")
        fauna_id = request.args.get("fauna_id")

        query = Fauna.query.options(
            selectinload(Fauna.panstwa),
            selectinload(Fauna.kontynenty)
        )

        if fauna_id:
            query = query.filter(Fauna.fauna_id == fauna_id)

        elif panstwo_id:
            query = query.join(Fauna.panstwa).filter(
                Panstwo.PANSTWO_ID == panstwo_id
            )

        elif kontynent:
            query = query.join(Fauna.kontynenty).filter(
                DictKontynent.kontynent_id == kontynent
            )

        results = query.all()

        kontynenty = DictKontynent.query.order_by(DictKontynent.kontynent_nazwa).all()
        fauna_all = Fauna.query.all()

        return render_template(
            "fauna_lista.html",
            results=results,
            kontynenty=kontynenty,
            fauna_all=fauna_all,
            selected_kontynent=kontynent,
            selected_panstwo=panstwo_id,
            selected_fauna=fauna_id
        )

    # =========================================
    # API: państwa po kontynencie
    # =========================================
    @app.route("/api/fauna/panstwa_by_kontynent")
    def fauna_panstwa_by_kontynent():

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
    @app.route("/fauna/<int:fauna_id>")
    def fauna_form(fauna_id):

        fauna = Fauna.query.options(
            selectinload(Fauna.panstwa),
            selectinload(Fauna.kontynenty)
        ).get_or_404(fauna_id)

        panstwa = ", ".join(p.panstwo_nazwa for p in fauna.panstwa) if fauna.panstwa else None
        kontynenty = ", ".join(k.kontynent_nazwa for k in fauna.kontynenty) if fauna.kontynenty else None

        return render_template(
            "fauna_form.html",
            fauna=fauna,
            panstwa=panstwa,
            kontynenty=kontynenty
        )

    # =========================================
    # DODAWANIE
    # =========================================
    @app.route("/fauna/add", methods=["GET", "POST"])
    @wymaga_roli("tworzyciel", "wszechmocny")
    def fauna_add():

        if request.method == "POST":

            nazwa = request.form.get("nazwa")
            opis = request.form.get("opis")

            if not nazwa or not opis:
                return render_template(
                    "fauna_form_add.html",
                    error="Nazwa i opis są wymagane.",
                    form_data=request.form
                )

            fauna = Fauna(
                nazwa=nazwa,
                opis=opis
            )

            # relacje
            panstwa_ids = request.form.getlist("panstwo_id")
            kontynenty_ids = request.form.getlist("kontynent_id")

            fauna.panstwa = Panstwo.query.filter(
                Panstwo.PANSTWO_ID.in_(panstwa_ids)
            ).all()

            fauna.kontynenty = DictKontynent.query.filter(
                DictKontynent.kontynent_id.in_(kontynenty_ids)
            ).all()

            # obraz
            obraz = request.files.get("obraz")

            if obraz and obraz.filename:
                if obraz.mimetype not in ["image/png", "image/jpeg"]:
                    return render_template(
                        "fauna_form_add.html",
                        error="Dozwolone formaty: JPG, PNG",
                        form_data=request.form
                    )

                fauna.fauna_obraz = obraz.read()
                fauna.fauna_obraz_mime = obraz.mimetype

            try:
                db.session.add(fauna)
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                return render_template(
                    "fauna_form_add.html",
                    error=f"Błąd zapisu: {e}",
                    form_data=request.form
                )

            return redirect(url_for("fauna_lista"))

        kontynenty = DictKontynent.query.order_by(DictKontynent.kontynent_nazwa).all()

        return render_template(
            "fauna_form_add.html",
            kontynenty=kontynenty
        )

    # =========================================
    # EDYCJA
    # =========================================
    @app.route("/fauna/<int:fauna_id>/edit", methods=["GET", "POST"])
    @wymaga_roli("wszechmocny")
    def fauna_edit(fauna_id):

        fauna = Fauna.query.options(
            selectinload(Fauna.panstwa),
            selectinload(Fauna.kontynenty)
        ).get_or_404(fauna_id)

        selected_panstwa = [p.PANSTWO_ID for p in fauna.panstwa]
        selected_kontynenty = [k.kontynent_id for k in fauna.kontynenty]

        if request.method == "POST":

            nazwa = request.form.get("nazwa")
            opis = request.form.get("opis")

            if not nazwa or not opis:
                kontynenty = DictKontynent.query.order_by(DictKontynent.kontynent_nazwa).all()

                return render_template(
                    "fauna_form_edit.html",
                    fauna=fauna,
                    kontynenty=kontynenty,
                    selected_kontynenty=selected_kontynenty,
                    selected_panstwa=selected_panstwa,
                    error="Nazwa i opis są wymagane."
                )

            fauna.nazwa = nazwa
            fauna.opis = opis

            panstwa_ids = request.form.getlist("panstwo_id")
            kontynenty_ids = request.form.getlist("kontynent_id")

            fauna.panstwa = Panstwo.query.filter(
                Panstwo.PANSTWO_ID.in_(panstwa_ids)
            ).all()

            fauna.kontynenty = DictKontynent.query.filter(
                DictKontynent.kontynent_id.in_(kontynenty_ids)
            ).all()

            # obraz
            obraz = request.files.get("obraz")

            if obraz and obraz.filename:
                if obraz.mimetype not in ["image/png", "image/jpeg"]:
                    kontynenty = DictKontynent.query.order_by(DictKontynent.kontynent_nazwa).all()

                    return render_template(
                        "fauna_form_edit.html",
                        fauna=fauna,
                        kontynenty=kontynenty,
                        selected_kontynenty=selected_kontynenty,
                        selected_panstwa=selected_panstwa,
                        error="Dozwolone formaty: JPG, PNG"
                    )

                fauna.fauna_obraz = obraz.read()
                fauna.fauna_obraz_mime = obraz.mimetype

            db.session.commit()

            return redirect(url_for("fauna_form", fauna_id=fauna_id))

        kontynenty = DictKontynent.query.order_by(DictKontynent.kontynent_nazwa).all()

        return render_template(
            "fauna_form_edit.html",
            fauna=fauna,
            kontynenty=kontynenty,
            selected_kontynenty=selected_kontynenty,
            selected_panstwa=selected_panstwa
        )

    # =========================================
    # USUWANIE
    # =========================================
    @app.route("/fauna/<int:fauna_id>/delete", methods=["POST"])
    @wymaga_roli("wszechmocny")
    def fauna_delete(fauna_id):

        fauna = Fauna.query.get_or_404(fauna_id)

        try:
            db.session.delete(fauna)
            db.session.commit()
            flash("Zwierzę zostało usunięte.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Błąd usuwania: {e}", "error")

        return redirect(url_for("fauna_lista"))

    # =========================================
    # OBRAZ
    # =========================================
    @app.route("/fauna/<int:fauna_id>/image")
    def fauna_image(fauna_id):

        fauna = Fauna.query.get_or_404(fauna_id)

        if not fauna.fauna_obraz:
            return "", 404

        return fauna.fauna_obraz, 200, {
            "Content-Type": fauna.fauna_obraz_mime
        }