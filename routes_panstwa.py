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
from models import Panstwo, Miasto, DictKontynent

from paths import (
    FLAGI_DIR,
    MAPY_DIR
)

from permissions import wymaga_roli
from sqlalchemy import inspect
from datetime import datetime, timezone


# ============================================================
# API
# ============================================================

def init_panstwa_api(app):

    @app.route("/api/panstwo_populacja")
    def panstwo_populacja():
        pid = request.args.get("id")
        p = Panstwo.query.get(pid)

        if not p:
            return jsonify({
                "populacja": None,
                "audit": None
            })

        return jsonify({
            "populacja": p.panstwo_populacja,
            "audit": (
                p.panstwo_populacja_audit.isoformat()
                if p.panstwo_populacja_audit
                else None
            )
        })

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

# ============================================================
# ROUTES
# ============================================================

def init_panstwa_routes(app):

    # ================= WYSZUKIWARKA PAŃST =================

    @app.route("/wyniki_wyszukiwania", methods=["GET"])
    def wyniki_wyszukiwania():

        kontynent_id = request.args.get("kontynent_id")
        nazwa = request.args.get("panstwo_nazwa")
        kod = request.args.get("panstwo_kod")

        ustroj = request.args.get("panstwo_ustroj")
        populacja_od = request.args.get("populacja_od")
        populacja_do = request.args.get("populacja_do")
        powierzchnia = request.args.get("panstwo_powierzchnia")
        jezyk = request.args.get("panstwo_jezyk")
        religia = request.args.get("panstwo_religia")
        pkb_od = request.args.get("pkb_od")
        pkb_do = request.args.get("pkb_do")
        pkb_pc_od = request.args.get("pkb_pc_od")
        pkb_pc_do = request.args.get("pkb_pc_do")
        czy_suwerenny = request.args.get("czy_suwerenny")

        kontynenty = DictKontynent.query.order_by(DictKontynent.kontynent_nazwa).all()

        query = Panstwo.query

        if kontynent_id:
            query = query.filter(Panstwo.kontynent_id == kontynent_id)

        if nazwa:
            query = query.filter(Panstwo.panstwo_nazwa.like(f"%{nazwa}%"))

        if kod:
            query = query.filter(Panstwo.panstwo_kod.like(f"%{kod}%"))

        if ustroj:
            query = query.filter(Panstwo.panstwo_ustroj.like(f"%{ustroj}%"))

        if populacja_od:
            query = query.filter(Panstwo.panstwo_populacja >= int(populacja_od))

        if populacja_do:
            query = query.filter(Panstwo.panstwo_populacja <= int(populacja_do))

        if powierzchnia:
            query = query.filter(Panstwo.panstwo_powierzchnia >= int(powierzchnia))

        if jezyk:
            query = query.filter(Panstwo.panstwo_jezyk.like(f"%{jezyk}%"))

        if religia:
            query = query.filter(Panstwo.panstwo_religia.like(f"%{religia}%"))

        if pkb_od:
            query = query.filter(Panstwo.panstwo_PKB >= int(pkb_od))

        if pkb_do:
            query = query.filter(Panstwo.panstwo_PKB <= int(pkb_do))

        if pkb_pc_od:
            query = query.filter(Panstwo.panstwo_PKB_per_capita >= int(pkb_pc_od))

        if pkb_pc_do:
            query = query.filter(Panstwo.panstwo_PKB_per_capita <= int(pkb_pc_do))

        if czy_suwerenny:
            query = query.filter(Panstwo.czy_suwerenny == czy_suwerenny)

        page = request.args.get("page", 1, type=int)
        per_page = 25

        pagination = query.paginate(page=page, per_page=per_page, error_out=False)

        results = pagination.items
        total = pagination.total

        args = request.args.to_dict()
        args.pop("page", None)

        return render_template(
            "wyniki_wyszukiwania.html",
            results=results,
            pagination=pagination,
            total=total,
            args=args,
            kontynenty=kontynenty,
            empty=len(results) == 0
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

        profil_jezykowy = p.profil_jezykowy  # może być None
    
        return render_template(
            "panstwo_form.html",
            p=p,
            miasta=miasta,
            profil_jezykowy=profil_jezykowy,
            ostatnia_edycja=p.opis_updated_at  # opcjonalne, patrz niżej
        )

    # ================= DODAWANIE PAŃSTWA =================

    @app.route("/panstwo_form_add", methods=["GET", "POST"])
    @wymaga_roli("tworzyciel", "wszechmocny")
    def panstwo_add_form():

        kontynenty = DictKontynent.query.order_by(DictKontynent.kontynent_nazwa).all()

        if request.method == "POST":

            nazwa = request.form.get("panstwo_nazwa")
            pelna = request.form.get("panstwo_pelna_nazwa")
            kod = request.form.get("panstwo_kod")
            ustroj = request.form.get("panstwo_ustroj")
            stolica = request.form.get("panstwo_stolica")
            populacja = int(request.form.get("panstwo_populacja"))
            pkb = int(request.form.get("PKB"))
            pkb_pc = int(request.form.get("PKB_per_capita"))
            waluta = request.form.get("panstwo_waluta")
            religia = request.form.get("panstwo_religia")
            kontynent_id_raw = request.form.get("kontynent_id")
            try:
                kontynent_id = int(kontynent_id_raw)
            except (TypeError, ValueError):
                kontynent_id = None
            powierzchnia = int(request.form.get("panstwo_powierzchnia"))
            czy_suwerenny = request.form.get("czy_suwerenny")

            required_fields = [
                nazwa, pelna, kod, ustroj, stolica,
                populacja, pkb, pkb_pc,
                waluta, religia,
                kontynent_id_raw, powierzchnia, czy_suwerenny
            ]

            if any(not field for field in required_fields):
                return render_template(
                    "panstwo_form_add.html",
                    kontynenty=kontynenty,
                    error="Wszystkie pola formularza są obowiązkowe.",
                    form_data=request.form
                )

            flaga = request.files.get("flaga")
            mapa = request.files.get("mapa")

            if czy_suwerenny not in ("TAK", "NIE"):
                return render_template(
                    "panstwo_form_add.html",
                    kontynenty=kontynenty,
                    error="Musisz określić, czy państwo jest suwerenne.",
                    form_data=request.form
                )

            if not flaga or not mapa or flaga.filename == "" or mapa.filename == "":
                return render_template(
                    "panstwo_form_add.html",
                    kontynenty=kontynenty,
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
                    kontynenty=kontynenty,
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
                    panstwo_religia=religia,
                    kontynent_id=kontynent_id,
                    panstwo_powierzchnia=powierzchnia,
                    czy_suwerenny=czy_suwerenny,
                )
                db.session.add(panstwo)
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                return render_template(
                    "panstwo_form_add.html",
                    kontynenty=kontynenty,
                    error=f"Błąd zapisu do bazy: {e}",
                    form_data=request.form
                )

            return redirect(url_for("panstwo_dodano"))

        return render_template(
            "panstwo_form_add.html",
            kontynenty=kontynenty
        )

    @app.route("/panstwo/<int:panstwo_id>/edit", methods=["GET", "POST"])
    def panstwo_form_edit(panstwo_id):
        p = Panstwo.query.get_or_404(panstwo_id)

        kontynenty = DictKontynent.query.order_by(
            DictKontynent.kontynent_nazwa
        ).all()

        if request.method == "POST":
            form = request.form
            czy_suwerenny = form.get("czy_suwerenny")
            errors = []

            required_fields = [
                "panstwo_nazwa",
                "panstwo_pelna_nazwa",
                "panstwo_kod",
                "kontynent_id",
                "panstwo_ustroj",
                "panstwo_stolica",
                "panstwo_powierzchnia",
                "panstwo_waluta",
                "panstwo_religia",
                "panstwo_PKB",
                "panstwo_PKB_per_capita",
                "czy_suwerenny",
            ]

            for f in required_fields:
                if not form.get(f):
                    errors.append("Wszystkie pola formularza są wymagane.")

            if errors:
                return render_template(
                    "panstwo_form_edit.html",
                    p=p,
                    kontynenty=kontynenty,
                    error=" ".join(set(errors)),
                    form_data=form
                )
            
            if czy_suwerenny not in ("TAK", "NIE"):
                return render_template(
                    "panstwo_form_edit.html",
                    p=p,
                    kontynenty=kontynenty,
                    error="Musisz określić status suwerenności państwa.",
                    form_data=form
                )

            try:
                # --- POLA TEKSTOWE / STAŁE ---
                p.panstwo_nazwa = form.get("panstwo_nazwa")
                p.panstwo_pelna_nazwa = form.get("panstwo_pelna_nazwa")
                p.panstwo_kod = form.get("panstwo_kod")
                p.kontynent_id = int(form.get("kontynent_id"))
                p.panstwo_ustroj = form.get("panstwo_ustroj")
                p.panstwo_stolica = form.get("panstwo_stolica")
                p.panstwo_powierzchnia = int(form.get("panstwo_powierzchnia"))
                p.panstwo_waluta = form.get("panstwo_waluta")
                p.panstwo_religia = form.get("panstwo_religia")
                czy_suwerenny = request.form.get("czy_suwerenny")
                p.panstwo_PKB = int(form.get("panstwo_PKB"))
                p.panstwo_PKB_per_capita = int(form.get("panstwo_PKB_per_capita"))

                p.czy_suwerenny = czy_suwerenny

                db.session.commit()

            except Exception as e:
                db.session.rollback()
                return render_template(
                    "panstwo_form_edit.html",
                    p=p,
                    kontynenty=kontynenty,
                    error=" ".join(set(errors)),
                    form_data=form
                )
        

            return redirect(url_for("panstwo_form", panstwo_id=p.PANSTWO_ID))

        return render_template(
            "panstwo_form_edit.html",
            p=p,
            kontynenty=kontynenty
        )

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

        nowy_opis = request.form.get("opis_html", "").strip()

        if not nowy_opis:
            flash("Opis nie może być pusty.", "error")
            return redirect(url_for("panstwo_form", panstwo_id=panstwo_id))

        # ─── AUDYT OPISU (POPRAWNA KOLEJNOŚĆ) ───
        if panstwo.panstwo_opis != nowy_opis:
            panstwo.panstwo_opis = nowy_opis
            panstwo.panstwo_opis_audit = datetime.now(timezone.utc)

        db.session.commit()

        flash("Informacje szczegółowe zostały zapisane.", "success")
        return redirect(url_for("panstwo_form", panstwo_id=panstwo_id))


