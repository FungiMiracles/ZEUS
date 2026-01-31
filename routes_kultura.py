from flask import render_template, request, redirect, url_for, flash, jsonify
from extensions import db
from models import Panstwo, Jezyk, JezykiPerPanstwo
from sqlalchemy import func
from permissions import wymaga_roli

def init_kultura_routes(app):

    # ===============================
    # MODUŁ KULTURY – STRONA GŁÓWNA
    # ===============================

    @app.route("/kultura")
    def kultura_home():
        return render_template("kultura.html")

    # ===============================
    # MODUŁ KULTURY – JĘZYKI
    # ===============================

    @app.route("/kultura/jezyki")
    def kultura_jezyki():
        return render_template("kultura_jezyki.html")

    # ===============================
    # API – PAŃSTWA PO KONTYNENCIE
    # ===============================

    @app.route("/api/kultura/panstwa_by_kontynent")
    def api_kultura_panstwa_by_kontynent():
        kontynent = request.args.get("kontynent")
    
        if not kontynent:
            return jsonify([])
    
        panstwa = (
            Panstwo.query
            .filter(Panstwo.kontynent == kontynent)
            .order_by(Panstwo.panstwo_nazwa.asc())
            .all()
        )
    
        return jsonify([
            {"id": p.PANSTWO_ID, "nazwa": p.panstwo_nazwa}
            for p in panstwa
        ])

    from models import Jezyk


    @app.route("/api/kultura/jezyki")
    def api_kultura_jezyki():
        jezyki = (
            Jezyk.query
            .order_by(Jezyk.jezyk_nazwa.asc())
            .all()
        )
    
        return jsonify([
            {
                "id": j.jezyk_id,
                "nazwa": j.jezyk_nazwa
            }
            for j in jezyki
        ])

    @app.route("/kultura/jezyki/add", methods=["GET", "POST"])
    @wymaga_roli("tworzyciel", "wszechmocny")
    def kultura_jezyk_add():
    
        if request.method == "POST":
            nazwa = request.form.get("jezyk_nazwa", "").strip()
            kod = request.form.get("jezyk_kod", "").strip().upper()
            przyklad_pl = request.form.get("przyklad_polski", "").strip()
            przyklad_doc = request.form.get("przyklad_docelowy", "").strip()
            opis = request.form.get("opis", "").strip()
            rodzina = request.form.get("jezyk_rodzina", "").strip()
    
            # ===============================
            # WALIDACJA
            # ===============================
    
            if not nazwa:
                flash("Nazwa języka jest wymagana.", "error")
                return redirect(url_for("kultura_jezyk_add"))
    
            # brak duplikatów (case-insensitive)
            istnieje = (
                db.session.query(Jezyk)
                .filter(func.lower(Jezyk.jezyk_nazwa) == nazwa.lower())
                .first()
            )
    
            if istnieje:
                flash("Taki język już istnieje w bazie.", "error")
                return redirect(url_for("kultura_jezyk_add"))
    
            if kod and (len(kod) != 2 or not kod.isalpha()):
                flash("Kod języka musi składać się z dwóch liter.", "error")
                return redirect(url_for("kultura_jezyk_add"))
    
            # ===============================
            # ZAPIS
            # ===============================
    
            jezyk = Jezyk(
                jezyk_nazwa=nazwa,
                jezyk_kod=kod or None,
                jezyk_rodzina=rodzina or None,
                przyklad_polski=przyklad_pl or None,
                przyklad_docelowy=przyklad_doc or None,
                opis=opis or None,
            )
    
            db.session.add(jezyk)
            db.session.commit()
    
            flash("Język został dodany poprawnie.", "success")
            return redirect(url_for("kultura_jezyki"))
    
        return render_template("kultura_jezyk_add.html")

    @app.route("/kultura/jezyki/przypisz", methods=["GET", "POST"])
    @wymaga_roli("wszechmocny")
    def kultura_jezyk_przypisz():
    
        def normalize(v):
            return v if v else None
    
        if request.method == "POST":
            panstwo_id = request.form.get("panstwo_id")
    
            # języki urzędowe
            urz1 = normalize(request.form.get("jezyk_urzedowy1"))
            urz2 = normalize(request.form.get("jezyk_urzedowy2"))
            urz3 = normalize(request.form.get("jezyk_urzedowy3"))
    
            # języki mniejszościowe
            min1 = normalize(request.form.get("jezyk_mniejszosciowy1"))
            min2 = normalize(request.form.get("jezyk_mniejszosciowy2"))
            min3 = normalize(request.form.get("jezyk_mniejszosciowy3"))
            min4 = normalize(request.form.get("jezyk_mniejszosciowy4"))
            min5 = normalize(request.form.get("jezyk_mniejszosciowy5"))
    
            # ===============================
            # WALIDACJA
            # ===============================
    
            if not panstwo_id:
                flash("Musisz wybrać państwo.", "error")
                return redirect(url_for("kultura_jezyk_przypisz"))
    
            if not urz1:
                flash("Musisz wybrać co najmniej język urzędowy 1.", "error")
                return redirect(url_for("kultura_jezyk_przypisz"))
    
            wszystkie = [urz1, urz2, urz3, min1, min2, min3, min4, min5]
            wszystkie = [j for j in wszystkie if j]
    
            if len(wszystkie) != len(set(wszystkie)):
                flash("Ten sam język nie może być przypisany wielokrotnie.", "error")
                return redirect(url_for("kultura_jezyk_przypisz"))
    
            # ===============================
            # ZAPIS / UPDATE
            # ===============================
    
            rekord = JezykiPerPanstwo.query.filter_by(panstwo_id=panstwo_id).first()
    
            if not rekord:
                rekord = JezykiPerPanstwo(panstwo_id=panstwo_id)
    
            rekord.jezyk_urzedowy1 = urz1
            rekord.jezyk_urzedowy2 = urz2
            rekord.jezyk_urzedowy3 = urz3
    
            rekord.jezyk_mniejszosciowy1 = min1
            rekord.jezyk_mniejszosciowy2 = min2
            rekord.jezyk_mniejszosciowy3 = min3
            rekord.jezyk_mniejszosciowy4 = min4
            rekord.jezyk_mniejszosciowy5 = min5
    
            db.session.add(rekord)
            db.session.commit()
    
            flash("Profil językowy państwa został zapisany.", "success")
            return redirect(url_for("kultura_jezyki"))
    
        return render_template("kultura_jezyk_przypisz.html")

    @app.route("/kultura/jezyki/search", methods=["POST"])
    def kultura_jezyki_search():
    
        kontynent = request.form.get("kontynent")
        panstwo_id = request.form.get("panstwo")
        jezyk_id = request.form.get("jezyk")
    
        query = db.session.query(Jezyk).distinct()
    
        # ===============================
        # FILTR PO JĘZYKU
        # ===============================
        if jezyk_id:
            query = query.filter(Jezyk.jezyk_id == jezyk_id)
    
        # ===============================
        # FILTR PO PAŃSTWIE / KONTYNENCIE
        # ===============================
        if panstwo_id or kontynent:
            query = query.join(
                JezykiPerPanstwo,
                db.or_(
                    Jezyk.jezyk_id == JezykiPerPanstwo.jezyk_urzedowy1,
                    Jezyk.jezyk_id == JezykiPerPanstwo.jezyk_urzedowy2,
                    Jezyk.jezyk_id == JezykiPerPanstwo.jezyk_urzedowy3,
                    Jezyk.jezyk_id == JezykiPerPanstwo.jezyk_mniejszosciowy1,
                    Jezyk.jezyk_id == JezykiPerPanstwo.jezyk_mniejszosciowy2,
                    Jezyk.jezyk_id == JezykiPerPanstwo.jezyk_mniejszosciowy3,
                    Jezyk.jezyk_id == JezykiPerPanstwo.jezyk_mniejszosciowy4,
                    Jezyk.jezyk_id == JezykiPerPanstwo.jezyk_mniejszosciowy5,
                )
            )
    
            query = query.join(Panstwo, Panstwo.PANSTWO_ID == JezykiPerPanstwo.panstwo_id)
    
            if panstwo_id:
                query = query.filter(Panstwo.PANSTWO_ID == panstwo_id)
            elif kontynent:
                query = query.filter(Panstwo.kontynent == kontynent)
    
        wyniki = query.order_by(Jezyk.jezyk_nazwa).all()
    
        return render_template(
            "kultura_jezyki.html",
            wyniki=wyniki
        )

    @app.route("/kultura/jezyki/usun/<int:jezyk_id>")
    @wymaga_roli("wszechmocny")
    def kultura_jezyk_usun(jezyk_id):
    
        jezyk = Jezyk.query.get(jezyk_id)
    
        if not jezyk:
            flash("Nie znaleziono wskazanego języka.", "error")
            return redirect(url_for("kultura_jezyki"))
    
        powiazania = JezykiPerPanstwo.query.all()
    
        for p in powiazania:
            if p.jezyk_urzedowy1 == jezyk_id:
                p.jezyk_urzedowy1 = None
            if p.jezyk_urzedowy2 == jezyk_id:
                p.jezyk_urzedowy2 = None
            if p.jezyk_urzedowy3 == jezyk_id:
                p.jezyk_urzedowy3 = None
    
            if p.jezyk_mniejszosciowy1 == jezyk_id:
                p.jezyk_mniejszosciowy1 = None
            if p.jezyk_mniejszosciowy2 == jezyk_id:
                p.jezyk_mniejszosciowy2 = None
            if p.jezyk_mniejszosciowy3 == jezyk_id:
                p.jezyk_mniejszosciowy3 = None
            if p.jezyk_mniejszosciowy4 == jezyk_id:
                p.jezyk_mniejszosciowy4 = None
            if p.jezyk_mniejszosciowy5 == jezyk_id:
                p.jezyk_mniejszosciowy5 = None
    
        # ===============================
        # USUNIĘCIE JĘZYKA
        # ===============================
    
        db.session.delete(jezyk)
        db.session.commit()
    
        flash("Język został usunięty.", "success")
        return redirect(url_for("kultura_jezyki"))

    @app.route("/kultura/jezyki/<int:jezyk_id>")
    def kultura_jezyk_form(jezyk_id):
    
        jezyk = Jezyk.query.get(jezyk_id)
    
        if not jezyk:
            flash("Nie znaleziono wskazanego języka.", "error")
            return redirect(url_for("kultura_jezyki"))
    
        return render_template(
            "kultura_jezyk_form.html",
            jezyk=jezyk
        )

    @app.route("/kultura/jezyki/edytuj/<int:jezyk_id>", methods=["GET", "POST"])
    @wymaga_roli("wszechmocny")
    def kultura_jezyk_edit(jezyk_id):
    
        jezyk = Jezyk.query.get(jezyk_id)
    
        if not jezyk:
            flash("Nie znaleziono wskazanego języka.", "error")
            return redirect(url_for("kultura_jezyki"))
    
        # ===============================
        # POST — zapis zmian
        # ===============================
        if request.method == "POST":
    
            nazwa = request.form.get("jezyk_nazwa", "").strip()
            kod = request.form.get("jezyk_kod", "").strip().upper()
            rodzina = request.form.get("jezyk_rodzina", "").strip()
            przyklad_pl = request.form.get("przyklad_polski", "").strip()
            przyklad_doc = request.form.get("przyklad_docelowy", "").strip()
            opis = request.form.get("opis", "").strip()
    
            # ===== WALIDACJA =====
    
            if not nazwa:
                flash("Nazwa języka jest wymagana.", "error")
                return redirect(url_for("kultura_jezyk_edit", jezyk_id=jezyk_id))
    
            # unikalność nazwy (pomijamy aktualny rekord)
            istnieje = (
                db.session.query(Jezyk)
                .filter(func.lower(Jezyk.jezyk_nazwa) == nazwa.lower())
                .filter(Jezyk.jezyk_id != jezyk_id)
                .first()
            )
    
            if istnieje:
                flash("Język o tej nazwie już istnieje.", "error")
                return redirect(url_for("kultura_jezyk_edit", jezyk_id=jezyk_id))
    
            if kod and (len(kod) != 2 or not kod.isalpha()):
                flash("Kod języka musi składać się z dwóch liter.", "error")
                return redirect(url_for("kultura_jezyk_edit", jezyk_id=jezyk_id))
    
            # ===== ZAPIS =====
    
            jezyk.jezyk_nazwa = nazwa
            jezyk.jezyk_kod = kod or None
            jezyk.jezyk_rodzina = rodzina or None
            jezyk.przyklad_polski = przyklad_pl or None
            jezyk.przyklad_docelowy = przyklad_doc or None
            jezyk.opis = opis or None
    
            db.session.commit()
    
            flash("Zmiany zostały zapisane.", "success")
            return redirect(url_for("kultura_jezyk_form", jezyk_id=jezyk.jezyk_id))
    
        # ===============================
        # GET — formularz edycji
        # ===============================
        return render_template(
            "kultura_jezyk_edit.html",
            jezyk=jezyk,
            tryb="edit"
        )
    
    @app.route(
    "/kultura/jezyk/przypisz/<int:panstwo_id>/edit",
    methods=["GET", "POST"]
    )
    def kultura_jezyk_przypisz_edit(panstwo_id):

        panstwo = Panstwo.query.get_or_404(panstwo_id)
        profil = JezykiPerPanstwo.query.filter_by(panstwo_id=panstwo_id).first()
        jezyki = Jezyk.query.order_by(Jezyk.jezyk_nazwa).all()

        if request.method == "POST":
            try:
                if not profil:
                    profil = JezykiPerPanstwo(panstwo_id=panstwo_id)
                    db.session.add(profil)

                # Języki urzędowe
                for i in range(1,4):
                    val = request.form.get(f"jezyk_urzedowy{i}")
                    setattr(
                        profil,
                        f"jezyk_urzedowy{i}",
                        int(val) if val else None
                    )

                # Języki mniejszościowe
                for i in range(1,6):
                    val = request.form.get(f"jezyk_mniejszosciowy{i}")
                    setattr(
                        profil,
                        f"jezyk_mniejszosciowy{i}",
                        int(val) if val else None
                    )

                db.session.commit()

            except Exception as e:
                db.session.rollback()
                return render_template(
                    "kultura_jezyk_przypisz_edit.html",
                    panstwo=panstwo,
                    profil=profil,
                    jezyki=jezyki,
                    error=f"Błąd zapisu: {e}"
                )

            return redirect(url_for("kultura_jezyk_list"))

        return render_template(
            "kultura_jezyk_przypisz_edit.html",
            panstwo=panstwo,
            profil=profil,
            jezyki=jezyki
        )



