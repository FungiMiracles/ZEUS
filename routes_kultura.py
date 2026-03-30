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

        kontynent_id = request.args.get("kontynent_id", type=int)
        panstwo_id = request.args.get("panstwo", type=int)
        jezyk_id = request.args.get("jezyk", type=int)

        query = db.session.query(Jezyk)

        if jezyk_id:
            query = query.filter(Jezyk.jezyk_id == jezyk_id)

        if panstwo_id:
            query = query.join(
                JezykiPerPanstwo,
                (JezykiPerPanstwo.jezyk_urzedowy1 == Jezyk.jezyk_id) |
                (JezykiPerPanstwo.jezyk_urzedowy2 == Jezyk.jezyk_id) |
                (JezykiPerPanstwo.jezyk_urzedowy3 == Jezyk.jezyk_id) |
                (JezykiPerPanstwo.jezyk_mniejszosciowy1 == Jezyk.jezyk_id) |
                (JezykiPerPanstwo.jezyk_mniejszosciowy2 == Jezyk.jezyk_id) |
                (JezykiPerPanstwo.jezyk_mniejszosciowy3 == Jezyk.jezyk_id) |
                (JezykiPerPanstwo.jezyk_mniejszosciowy4 == Jezyk.jezyk_id) |
                (JezykiPerPanstwo.jezyk_mniejszosciowy5 == Jezyk.jezyk_id)
            ).filter(JezykiPerPanstwo.panstwo_id == panstwo_id)

        if kontynent_id:
            query = query.join(
                JezykiPerPanstwo,
                (JezykiPerPanstwo.jezyk_urzedowy1 == Jezyk.jezyk_id) |
                (JezykiPerPanstwo.jezyk_urzedowy2 == Jezyk.jezyk_id) |
                (JezykiPerPanstwo.jezyk_urzedowy3 == Jezyk.jezyk_id) |
                (JezykiPerPanstwo.jezyk_mniejszosciowy1 == Jezyk.jezyk_id) |
                (JezykiPerPanstwo.jezyk_mniejszosciowy2 == Jezyk.jezyk_id) |
                (JezykiPerPanstwo.jezyk_mniejszosciowy3 == Jezyk.jezyk_id) |
                (JezykiPerPanstwo.jezyk_mniejszosciowy4 == Jezyk.jezyk_id) |
                (JezykiPerPanstwo.jezyk_mniejszosciowy5 == Jezyk.jezyk_id)
            ).join(
                Panstwo, Panstwo.PANSTWO_ID == JezykiPerPanstwo.panstwo_id
            ).filter(Panstwo.kontynent_id == kontynent_id)

        wyniki = query.distinct().order_by(Jezyk.jezyk_nazwa.asc()).all()

        return render_template(
            "kultura_jezyki.html",
            wyniki=wyniki,
            selected_kontynent=kontynent_id,
            selected_panstwo=panstwo_id,
            selected_jezyk=jezyk_id
        )

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

        powiazania = JezykiPerPanstwo.query.filter(
            (JezykiPerPanstwo.jezyk_urzedowy1 == jezyk_id) |
            (JezykiPerPanstwo.jezyk_urzedowy2 == jezyk_id) |
            (JezykiPerPanstwo.jezyk_urzedowy3 == jezyk_id) |
            (JezykiPerPanstwo.jezyk_mniejszosciowy1 == jezyk_id) |
            (JezykiPerPanstwo.jezyk_mniejszosciowy2 == jezyk_id) |
            (JezykiPerPanstwo.jezyk_mniejszosciowy3 == jezyk_id) |
            (JezykiPerPanstwo.jezyk_mniejszosciowy4 == jezyk_id) |
            (JezykiPerPanstwo.jezyk_mniejszosciowy5 == jezyk_id)
        ).all()

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
    
    # ===============================
    # PRZYPISANIE
    # ===============================
    
    @app.route("/kultura/jezyki/przypisz", methods=["GET", "POST"])
    @wymaga_roli("wszechmocny")
    def kultura_jezyk_przypisz():

        panstwa = Panstwo.query.order_by(Panstwo.panstwo_nazwa).all()
        jezyki = Jezyk.query.order_by(Jezyk.jezyk_nazwa).all()

        if request.method == "POST":

            panstwo_id = request.form.get("panstwo_id")

            # języki urzędowe
            urzedowe = [
                request.form.get("jezyk_urzedowy1"),
                request.form.get("jezyk_urzedowy2"),
                request.form.get("jezyk_urzedowy3"),
            ]

            # języki mniejszościowe
            mniejszosciowe = [
                request.form.get("jezyk_mniejszosciowy1"),
                request.form.get("jezyk_mniejszosciowy2"),
                request.form.get("jezyk_mniejszosciowy3"),
                request.form.get("jezyk_mniejszosciowy4"),
                request.form.get("jezyk_mniejszosciowy5"),
            ]

            errors = []

            # ===== WALIDACJA PAŃSTWA =====
            if not panstwo_id or not panstwo_id.isdigit():
                errors.append("Wybierz poprawne państwo.")

            # ===== WALIDACJA DUPLIKATÓW =====
            wszystkie = [j for j in urzedowe + mniejszosciowe if j]

            if len(wszystkie) != len(set(wszystkie)):
                errors.append("Nie można przypisać tego samego języka więcej niż raz.")

            # ===== WALIDACJA ISTNIENIA JĘZYKÓW =====
            for j_id in wszystkie:
                if not j_id.isdigit():
                    errors.append("Niepoprawny język.")
                    break

            if errors:
                return render_template(
                    "kultura_jezyk_przypisz.html",
                    panstwa=panstwa,
                    jezyki=jezyki,
                    error=" ".join(errors),
                    form_data=request.form
                )

            # ===== SPRAWDZENIE CZY JUŻ ISTNIEJE PROFIL =====
            profil = JezykiPerPanstwo.query.filter_by(
                panstwo_id=int(panstwo_id)
            ).first()

            if profil:
                return render_template(
                    "kultura_jezyk_przypisz.html",
                    panstwa=panstwa,
                    jezyki=jezyki,
                    error="To państwo ma już przypisane języki.",
                    form_data=request.form
                )

            # ===== ZAPIS =====
            profil = JezykiPerPanstwo.query.filter_by(
                panstwo_id=int(panstwo_id),

                jezyk_urzedowy1=int(urzedowe[0]) if urzedowe[0] else None,
                jezyk_urzedowy2=int(urzedowe[1]) if urzedowe[1] else None,
                jezyk_urzedowy3=int(urzedowe[2]) if urzedowe[2] else None,

                jezyk_mniejszosciowy1=int(mniejszosciowe[0]) if mniejszosciowe[0] else None,
                jezyk_mniejszosciowy2=int(mniejszosciowe[1]) if mniejszosciowe[1] else None,
                jezyk_mniejszosciowy3=int(mniejszosciowe[2]) if mniejszosciowe[2] else None,
                jezyk_mniejszosciowy4=int(mniejszosciowe[3]) if mniejszosciowe[3] else None,
                jezyk_mniejszosciowy5=int(mniejszosciowe[4]) if mniejszosciowe[4] else None,
            )

            db.session.add(profil)
            db.session.commit()

            return redirect(url_for("kultura_jezyki"))

        return render_template(
            "kultura_jezyk_przypisz.html",
            panstwa=panstwa,
            jezyki=jezyki,
            form_data={}
        )