from flask import render_template, request, redirect, url_for, flash, jsonify
from extensions import db
from models import Panstwo, Jezyk, JezykiPerPanstwo, DictKontynent, DictJezykRodzina
from sqlalchemy import func
from permissions import wymaga_roli


def init_kultura_routes(app):

    # ===============================
    # STRONA GŁÓWNA
    # ===============================
    @app.route("/kultura")
    def kultura_home():
        return render_template("kultura.html")

    # ===============================
    # JĘZYKI – PANEL
    # ===============================
    @app.route("/kultura/jezyki")
    def kultura_jezyki():
        return render_template("kultura_jezyki.html")

    # ===============================
    # API – PAŃSTWA
    # ===============================
    @app.route("/api/kultura/panstwa_by_kontynent")
    def api_kultura_panstwa_by_kontynent():
        kontynent_id = request.args.get("kontynent_id", type=int)

        if not kontynent_id:
            return jsonify([])

        panstwa = (
            Panstwo.query
            .filter(Panstwo.kontynent_id == kontynent_id)
            .order_by(Panstwo.panstwo_nazwa.asc())
            .all()
        )

        return jsonify([
            {"id": p.PANSTWO_ID, "nazwa": p.panstwo_nazwa}
            for p in panstwa
        ])

    # ===============================
    # API – JĘZYKI
    # ===============================
    @app.route("/api/kultura/jezyki")
    def api_kultura_jezyki():
        jezyki = Jezyk.query.order_by(Jezyk.jezyk_nazwa.asc()).all()

        return jsonify([
            {"id": j.jezyk_id, "nazwa": j.jezyk_nazwa}
            for j in jezyki
        ])

    # ===============================
    # ADD JĘZYK
    # ===============================
    @app.route("/kultura/jezyki/add", methods=["GET", "POST"])
    @wymaga_roli("tworzyciel", "wszechmocny")
    def kultura_jezyk_add():

        rodziny = DictJezykRodzina.query.order_by(DictJezykRodzina.nazwa).all()

        if request.method == "POST":
            nazwa = request.form.get("jezyk_nazwa", "").strip()
            kod = request.form.get("jezyk_kod", "").strip().upper()
            rodzina_id = request.form.get("jezyk_rodzina_id")
            przyklad_pl = request.form.get("przyklad_polski", "").strip()
            przyklad_doc = request.form.get("przyklad_docelowy", "").strip()
            opis = request.form.get("opis", "").strip()

            # ===== WALIDACJA =====

            if not nazwa:
                flash("Nazwa języka jest wymagana.", "error")
                return render_template("kultura_jezyk_add.html", rodziny=rodziny)

            istnieje = (
                db.session.query(Jezyk)
                .filter(func.lower(Jezyk.jezyk_nazwa) == nazwa.lower())
                .first()
            )

            if istnieje:
                flash("Taki język już istnieje.", "error")
                return render_template("kultura_jezyk_add.html", rodziny=rodziny)

            if kod and (len(kod) != 2 or not kod.isalpha()):
                flash("Kod musi mieć 2 litery.", "error")
                return render_template("kultura_jezyk_add.html", rodziny=rodziny)

            if not rodzina_id or not rodzina_id.isdigit():
                flash("Wybierz rodzinę językową.", "error")
                return render_template("kultura_jezyk_add.html", rodziny=rodziny)

            # ===== ZAPIS =====

            jezyk = Jezyk(
                jezyk_nazwa=nazwa,
                jezyk_kod=kod or None,
                jezyk_rodzina_id=int(rodzina_id),
                przyklad_polski=przyklad_pl or None,
                przyklad_docelowy=przyklad_doc or None,
                opis=opis or None,
            )

            db.session.add(jezyk)
            db.session.commit()

            flash("Język dodany.", "success")
            return redirect(url_for("kultura_jezyki"))

        return render_template("kultura_jezyk_add.html", rodziny=rodziny)

    # ===============================
    # EDIT JĘZYK
    # ===============================
    @app.route("/kultura/jezyki/edytuj/<int:jezyk_id>", methods=["GET", "POST"])
    @wymaga_roli("wszechmocny")
    def kultura_jezyk_edit(jezyk_id):

        jezyk = Jezyk.query.get_or_404(jezyk_id)
        rodziny = DictJezykRodzina.query.order_by(DictJezykRodzina.nazwa).all()

        if request.method == "POST":

            nazwa = request.form.get("jezyk_nazwa", "").strip()
            kod = request.form.get("jezyk_kod", "").strip().upper()
            rodzina_id = request.form.get("jezyk_rodzina_id")
            przyklad_pl = request.form.get("przyklad_polski", "").strip()
            przyklad_doc = request.form.get("przyklad_docelowy", "").strip()
            opis = request.form.get("opis", "").strip()

            if not nazwa:
                flash("Nazwa wymagana.", "error")
                return redirect(url_for("kultura_jezyk_edit", jezyk_id=jezyk_id))

            istnieje = (
                db.session.query(Jezyk)
                .filter(func.lower(Jezyk.jezyk_nazwa) == nazwa.lower())
                .filter(Jezyk.jezyk_id != jezyk_id)
                .first()
            )

            if istnieje:
                flash("Język już istnieje.", "error")
                return redirect(url_for("kultura_jezyk_edit", jezyk_id=jezyk_id))

            if not rodzina_id or not rodzina_id.isdigit():
                flash("Wybierz rodzinę językową.", "error")
                return redirect(url_for("kultura_jezyk_edit", jezyk_id=jezyk_id))

            jezyk.jezyk_nazwa = nazwa
            jezyk.jezyk_kod = kod or None
            jezyk.jezyk_rodzina_id = int(rodzina_id)
            jezyk.przyklad_polski = przyklad_pl or None
            jezyk.przyklad_docelowy = przyklad_doc or None
            jezyk.opis = opis or None

            db.session.commit()

            flash("Zapisano zmiany.", "success")
            return redirect(url_for("kultura_jezyk_form", jezyk_id=jezyk_id))

        return render_template(
            "kultura_jezyk_edit.html",
            jezyk=jezyk,
            rodziny=rodziny
        )

    # ===============================
    # VIEW
    # ===============================
    @app.route("/kultura/jezyki/<int:jezyk_id>")
    def kultura_jezyk_form(jezyk_id):

        jezyk = Jezyk.query.get_or_404(jezyk_id)

        return render_template(
            "kultura_jezyk_form.html",
            jezyk=jezyk
        )

    # ===============================
    # DELETE
    # ===============================
    @app.route("/kultura/jezyki/usun/<int:jezyk_id>")
    @wymaga_roli("wszechmocny")
    def kultura_jezyk_usun(jezyk_id):

        jezyk = Jezyk.query.get_or_404(jezyk_id)

        powiazania = JezykiPerPanstwo.query.all()

        for p in powiazania:
            for field in [
                "jezyk_urzedowy1", "jezyk_urzedowy2", "jezyk_urzedowy3",
                "jezyk_mniejszosciowy1", "jezyk_mniejszosciowy2",
                "jezyk_mniejszosciowy3", "jezyk_mniejszosciowy4",
                "jezyk_mniejszosciowy5"
            ]:
                if getattr(p, field) == jezyk_id:
                    setattr(p, field, None)

        db.session.delete(jezyk)
        db.session.commit()

        flash("Język usunięty.", "success")
        return redirect(url_for("kultura_jezyki"))