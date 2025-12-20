# routes_panstwa.py

import os

from flask import (
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify
)
from werkzeug.utils import secure_filename

from extensions import db
from models import Panstwo, Miasto
from datetime import datetime

from markdown_utils import (
    get_panstwo_description,
    get_panstwo_description_raw
)

from paths import (
    FLAGI_DIR,
    MAPY_DIR,
    DESCRIPTIONS_FOLDER
)

from permissions import wymaga_roli


# ============================================================
# API
# ============================================================

def init_panstwa_api(app):

    @app.route("/api/panstwo_suggest")
    def panstwo_suggest():
        q = request.args.get("q", "")
        rows = (
            Panstwo.query
            .filter(Panstwo.panstwo_nazwa.like(f"%{q}%"))
            .limit(10)
            .all()
        )

        return jsonify([
            {"PANSTWO_ID": p.PANSTWO_ID, "panstwo_nazwa": p.panstwo_nazwa}
            for p in rows
        ])

    @app.route("/api/panstwo_populacja")
    def panstwo_populacja():
        pid = request.args.get("id")
        p = Panstwo.query.get(pid)
        if not p:
            return jsonify({"populacja": None})

        return jsonify({"populacja": p.panstwo_populacja})


# ============================================================
# ROUTES
# ============================================================

def init_panstwa_routes(app):

    # ================= WYSZUKIWARKA PAŃST =================

    @app.route("/wyniki_wyszukiwania", methods=["GET"])
    def wyniki_wyszukiwania():
        kontynent = request.args.get("kontynent")
        nazwa = request.args.get("panstwo_nazwa")
        kod = request.args.get("panstwo_kod")

        query = Panstwo.query

        if kontynent:
            query = query.filter(Panstwo.kontynent == kontynent)

        if nazwa:
            query = query.filter(Panstwo.panstwo_nazwa.like(f"%{nazwa}%"))

        if kod:
            query = query.filter(Panstwo.panstwo_kod.like(f"%{kod}%"))

        results = query.all()
        empty = len(results) == 0

        return render_template(
            "wyniki_wyszukiwania.html",
            results=results,
            empty=empty
        )

    # ================= FORMULARZ PAŃSTWA =================

    @app.route("/panstwo/<int:panstwo_id>")
    def panstwo_form(panstwo_id):
        p = Panstwo.query.get_or_404(panstwo_id)

        miasta = (
            Miasto.query
            .filter_by(panstwo_id=panstwo_id)
            .order_by(Miasto.miasto_populacja.desc())
            .all()
        )

        # 🔑 HTML do podglądu, RAW MD do edycji
        opis_html = get_panstwo_description(p.panstwo_nazwa)
        opis_md = get_panstwo_description_raw(p.panstwo_nazwa)

        # ===== DATA OSTATNIEJ EDYCJI OPISU =====
        filename = p.panstwo_nazwa.replace(" ", "_") + ".md"
        filepath = os.path.join(DESCRIPTIONS_FOLDER, filename)

        ostatnia_edycja = None
        if os.path.exists(filepath):
            ts = os.path.getmtime(filepath)  # timestamp
            ostatnia_edycja = datetime.fromtimestamp(ts)

        return render_template(
            "panstwo_form.html",
            p=p,
            miasta=miasta,
            opis_html=opis_html,
            opis_md=opis_md,
            ostatnia_edycja=ostatnia_edycja
        )

    # ================= DODAWANIE PAŃSTWA =================

    @app.route("/panstwo_form_add", methods=["GET", "POST"])
    @wymaga_roli("tworzyciel", "wszechmocny")
    def panstwo_add_form():
        if request.method == "POST":

            nazwa = request.form.get("panstwo_nazwa")
            pelna = request.form.get("panstwo_pelna_nazwa")
            kod = request.form.get("panstwo_kod")
            ustroj = request.form.get("panstwo_ustroj")
            stolica = request.form.get("panstwo_stolica")
            populacja = request.form.get("panstwo_populacja")
            pkb = request.form.get("PKB")
            pkb_pc = request.form.get("PKB_per_capita")
            waluta = request.form.get("panstwo_waluta")
            jezyk = request.form.get("panstwo_jezyk")
            religia = request.form.get("panstwo_religia")
            kontynent = request.form.get("kontynent")
            powierzchnia = request.form.get("panstwo_powierzchnia")

            required_fields = [
                nazwa, pelna, kod, ustroj, stolica,
                populacja, pkb, pkb_pc,
                waluta, jezyk, religia,
                kontynent, powierzchnia
            ]

            if any(not field for field in required_fields):
                return render_template(
                    "panstwo_form_add.html",
                    error="Wszystkie pola formularza są obowiązkowe.",
                    form_data=request.form
                )

            flaga = request.files.get("flaga")
            mapa = request.files.get("mapa")

            if not flaga or not mapa or flaga.filename == "" or mapa.filename == "":
                return render_template(
                    "panstwo_form_add.html",
                    error="Dodaj flagę i mapę państwa.",
                    form_data=request.form
                )

            filename_base = secure_filename(nazwa.replace(" ", "_"))

            try:
                flaga.save(os.path.join(FLAGI_DIR, f"{filename_base}.jpg"))
                mapa.save(os.path.join(MAPY_DIR, f"{filename_base}.jpg"))
            except Exception as e:
                return render_template(
                    "panstwo_form_add.html",
                    error=f"Błąd zapisu plików: {e}",
                    form_data=request.form
                )

            try:
                panstwo = Panstwo(
                    panstwo_nazwa=nazwa,
                    panstwo_pelna_nazwa=pelna,
                    panstwo_kod=kod,
                    panstwo_ustroj=ustroj,
                    panstwo_stolica=stolica,
                    panstwo_populacja=populacja,
                    panstwo_PKB=pkb,
                    panstwo_PKB_per_capita=pkb_pc,
                    panstwo_waluta=waluta,
                    panstwo_jezyk=jezyk,
                    panstwo_religia=religia,
                    kontynent=kontynent,
                    panstwo_powierzchnia=powierzchnia,
                )
                db.session.add(panstwo)
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                return render_template(
                    "panstwo_form_add.html",
                    error=f"Błąd zapisu do bazy: {e}",
                    form_data=request.form
                )

            return redirect(url_for("panstwo_dodano"))

        return render_template("panstwo_form_add.html")

    # ================= USUWANIE PAŃSTWA =================

    @app.route("/usun_panstwo/<int:panstwo_id>", methods=["POST"])
    @wymaga_roli("wszechmocny")
    def usun_panstwo(panstwo_id):
        panstwo = Panstwo.query.get_or_404(panstwo_id)

        try:
            db.session.delete(panstwo)
            db.session.commit()
            flash(
                f"Państwo {panstwo.panstwo_nazwa} zostało usunięte.",
                "success"
            )
        except Exception as e:
            db.session.rollback()
            flash(f"Wystąpił błąd podczas usuwania: {e}", "error")

        return redirect(url_for("wyniki_wyszukiwania"))

    # ================= EDYCJA OPISU (MARKDOWN) =================

    @app.route("/panstwo/<int:panstwo_id>/opis/edit", methods=["POST"])
    @wymaga_roli("wszechmocny")
    def panstwo_opis_edit(panstwo_id):
        panstwo = Panstwo.query.get_or_404(panstwo_id)

        nowy_opis = request.form.get("opis_md", "")

        # 🔥 NORMALIZACJA NOWYCH LINII (CRLF -> LF)
        nowy_opis = nowy_opis.replace("\r\n", "\n").strip()
        if not nowy_opis:
            flash("Opis nie może być pusty.", "error")
            return redirect(url_for("panstwo_form", panstwo_id=panstwo_id))

        filename = panstwo.panstwo_nazwa.replace(" ", "_") + ".md"
        filepath = os.path.join(DESCRIPTIONS_FOLDER, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(nowy_opis)

        flash("Informacje szczegółowe zostały zapisane.", "success")
        return redirect(url_for("panstwo_form", panstwo_id=panstwo_id))
