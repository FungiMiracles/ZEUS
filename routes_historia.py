from flask import render_template, request, redirect, url_for, flash
from sqlalchemy import case
from datetime import datetime
import os
import re

from extensions import db
from models import Historia
from permissions import wymaga_roli
from paths import EVENTS_DESCRIPTIONS_FOLDER
from datetime import date, datetime

def parse_year_or_date(value: str) -> date:
    """
    Akceptuje:
    - Y
    - YY
    - YYY
    - YYYY
    - DD-MM-YYYY
    - YYYY-MM-DD

    Zawsze zwraca datetime.date
    """
    if not value:
        raise ValueError("Data jest wymagana.")

    value = value.strip()

    # ───────────────
    # SAM ROK
    # ───────────────
    if value.isdigit() and 1 <= len(value) <= 4:
        return date(int(value), 1, 1)

    # ───────────────
    # DD-MM-YYYY
    # ───────────────
    m = re.fullmatch(r"(\d{1,2})-(\d{1,2})-(\d{4})", value)
    if m:
        day, month, year = map(int, m.groups())

        if month < 1 or month > 12:
            raise ValueError("Nieprawidłowy format daty")

        if day < 1 or day > 31:
            raise ValueError("Nieprawidłowy format daty")

        try:
            return date(year, month, day)
        except ValueError:
            raise ValueError("Nieprawidłowy format daty")

    # ───────────────
    # YYYY-MM-DD
    # ───────────────
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", value)
    if m:
        year, month, day = map(int, m.groups())

        if month < 1 or month > 12:
            raise ValueError("Nieprawidłowy format daty")

        if day < 1 or day > 31:
            raise ValueError("Nieprawidłowy format daty")

        try:
            return date(year, month, day)
        except ValueError:
            raise ValueError("Nieprawidłowy format daty")

    raise ValueError(
        "Nieprawidłowy format daty. "
        "Dozwolone: RRRR, DD-MM-RRRR, RRRR-MM-DD."
    )


# ============================================================
#  ROUTES HISTORII
# ============================================================

def init_historia_routes(app):

    # --------------------------------------------------------
    # LISTA WYDARZEŃ
    # --------------------------------------------------------
    @app.route("/historia/lista")
    def historia_lista():
        epoka = request.args.get("epoka")

        query = Historia.query
        if epoka:
            query = query.filter(Historia.epoka == epoka)

        wydarzenia = query.order_by(
            Historia.data_od.desc()
        ).all()

        return render_template(
            "historia_lista.html",
            wydarzenia=wydarzenia,
            epoka=epoka
        )

    # --------------------------------------------------------
    # PODGLĄD WYDARZENIA
    # --------------------------------------------------------
    @app.route("/historia/<int:historia_id>")
    def historia_podglad(historia_id):
    
        h = Historia.query.get_or_404(historia_id)
    
        return render_template(
            "historia_form.html",
            h=h
        )

    # --------------------------------------------------------
    # DODAWANIE WYDARZENIA
    # --------------------------------------------------------
    @app.route("/historia/dodaj", methods=["GET", "POST"])
    @wymaga_roli("tworzyciel", "wszechmocny")
    def historia_dodaj():
    
        if request.method == "POST":
            try:
                form = request.form
    
                data_od = parse_year_or_date(form["data_od"])
                data_do_raw = form.get("data_do")
                data_do = parse_year_or_date(data_do_raw) if data_do_raw else None
    
                if data_do and data_do < data_od:
                    raise ValueError("Data końcowa nie może być wcześniejsza.")
    
                h = Historia(
                    nazwa_wydarzenia=form["nazwa_wydarzenia"],
                    epoka=form["epoka"],
                    data_od=data_od,
                    data_do=data_do,
                    kontynent=form.get("kontynent") or None,
    
                    # 🔥 KLUCZOWA LINIA
                    wydarzenie_opis=form.get("wydarzenie_opis")
                )
    
                db.session.add(h)
                db.session.commit()
    
                flash("Wydarzenie zostało dodane.", "success")
                return redirect(url_for("historia_lista"))
            
            
            except Exception as e:
                db.session.rollback()
                flash(str(e), "error")
                return render_template(
                "historia_form_add.html",
                form_data=request.form
            )
    
        return render_template("historia_form_add.html")



    # --------------------------------------------------------
    # EDYCJA WYDARZENIA
    # --------------------------------------------------------
    @app.route("/historia/<int:historia_id>/edit", methods=["GET", "POST"])
    @wymaga_roli("wszechmocny")
    def historia_edytuj(historia_id):
    
        h = Historia.query.get_or_404(historia_id)
    
        if request.method == "POST":
            try:
                # ====== DANE FORMULARZA ======
                h.nazwa_wydarzenia = request.form.get("nazwa_wydarzenia")
                h.epoka = request.form.get("epoka")
                h.kontynent = request.form.get("kontynent") or None
    
                # DATA
                h.data_od = parse_year_or_date(request.form.get("data_od"))
                data_do_raw = request.form.get("data_do")
                h.data_do = parse_year_or_date(data_do_raw) if data_do_raw else None
    
                if h.data_do and h.data_do < h.data_od:
                    raise ValueError("Data końcowa nie może być wcześniejsza niż początkowa.")
    
                # ====== OPIS (NOWA ARCHITEKTURA) ======
                h.wydarzenie_opis = request.form.get("wydarzenie_opis")
    
                # ====== ZAPIS DO BAZY ======
                db.session.commit()
    
                flash("Wydarzenie zostało zaktualizowane.", "success")
                return redirect(
                    url_for("historia_podglad", historia_id=h.HISTORIA_ID)
                )
    
            except Exception as e:
                db.session.rollback()
                flash(str(e), "error")
                return render_template(
                "historia_form_edit.html",
                form_data=request.form
            )
    
        # ====== GET ======
        return render_template(
            "historia_form_edit.html",
            h=h
        )



    # --------------------------------------------------------
    # USUWANIE WYDARZENIA
    # --------------------------------------------------------
    @app.route("/historia/<int:historia_id>/delete", methods=["POST"])
    @wymaga_roli("wszechmocny")
    def historia_usun(historia_id):
    
        h = Historia.query.get_or_404(historia_id)
    
        try:
            db.session.delete(h)
            db.session.commit()
    
            flash("Wydarzenie historyczne zostało usunięte.", "success")
    
        except Exception as e:
            db.session.rollback()
            flash(f"Błąd podczas usuwania wydarzenia: {e}", "error")
    
        return redirect(url_for("historia_lista"))

