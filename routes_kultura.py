from flask import render_template, request, redirect, url_for, flash, jsonify
from extensions import db
from models import Panstwo, Jezyk
from sqlalchemy import func

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
    def kultura_jezyk_add():
    
        if request.method == "POST":
            nazwa = request.form.get("jezyk_nazwa", "").strip()
            kod = request.form.get("jezyk_kod", "").strip().upper()
            przyklad_pl = request.form.get("przyklad_polski", "").strip()
            przyklad_doc = request.form.get("przyklad_docelowy", "").strip()
            opis = request.form.get("opis", "").strip()
    
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
                przyklad_polski=przyklad_pl or None,
                przyklad_docelowy=przyklad_doc or None,
                opis=opis or None,
            )
    
            db.session.add(jezyk)
            db.session.commit()
    
            flash("Język został dodany poprawnie.", "success")
            return redirect(url_for("kultura_jezyki"))
    
        return render_template("kultura_jezyk_add.html")


