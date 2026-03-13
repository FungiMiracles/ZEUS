from flask import render_template, request, redirect, url_for, flash
from sqlalchemy import case
from sqlalchemy.orm import joinedload
from extensions import db
from models import Historia
from permissions import wymaga_roli
from datetime import date, datetime
from models import Panstwo, Region, Miasto, DictKontynent
import re

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
    
        query = (
            Historia.query
            .options(
                joinedload(Historia.panstwo),
                joinedload(Historia.region),
                joinedload(Historia.miasto),
            )
        )
    
        if epoka:
            query = query.filter(Historia.epoka == epoka)
    
        wydarzenia = (
            query
            .order_by(Historia.data_od.desc())
            .all()
        )
    
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
    
        h = (
            Historia.query
            .options(
                joinedload(Historia.panstwo),
                joinedload(Historia.region),
                joinedload(Historia.miasto),
            )
            .get_or_404(historia_id)
        )
    
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

        panstwa = Panstwo.query.order_by(Panstwo.panstwo_nazwa).all()

        kontynenty = DictKontynent.query.order_by(
            DictKontynent.kontynent_nazwa
        ).all()

        if request.method == "POST":
            try:
                form = request.form
    
                # ───────────────
                # DATY
                # ───────────────
                data_od = parse_year_or_date(form["data_od"])
                data_do_raw = form.get("data_do")
                data_do = parse_year_or_date(data_do_raw) if data_do_raw else None
    
                if data_do and data_do < data_od:
                    raise ValueError("Data końcowa nie może być wcześniejsza.")
    
                # ───────────────
                # FK PARSE
                # ───────────────
                def parse_fk(v):
                    return int(v) if v and v.isdigit() else None
    
                panstwo_id = parse_fk(form.get("panstwo_id"))
                region_id = parse_fk(form.get("region_id"))
                miasto_id = parse_fk(form.get("miasto_id"))

                kontynenty = DictKontynent.query.order_by(
                    DictKontynent.kontynent_nazwa
                ).all()
    
                # ───────────────
                # HIERARCHIA GEO
                # ───────────────
                panstwo = region = miasto = None
    
                if miasto_id:
                    miasto = Miasto.query.get(miasto_id)
                    if not miasto:
                        raise ValueError("Wybrane miasto nie istnieje.")
    
                    region = miasto.region
                    panstwo = miasto.panstwo
    
                if region_id:
                    region = Region.query.get(region_id)
                    if not region:
                        raise ValueError("Wybrany region nie istnieje.")
    
                    if miasto and miasto.region_id != region.region_id:
                        raise ValueError("Miasto nie należy do wybranego regionu.")
    
                    panstwo = region.panstwo
    
                if panstwo_id:
                    panstwo = Panstwo.query.get(panstwo_id)
                    if not panstwo:
                        raise ValueError("Wybrane państwo nie istnieje.")
    
                    if region and panstwo and region.panstwo_id != panstwo.PANSTWO_ID:
                        raise ValueError("Region nie należy do wybranego państwa.")
    
                # ───────────────
                # ZAPIS
                # ───────────────
                h = Historia(
                    nazwa_wydarzenia=form["nazwa_wydarzenia"],
                    epoka=form["epoka"],
                    data_od=data_od,
                    data_do=data_do,
                    kontynent_id=parse_fk(form.get("kontynent_id")),
                    wydarzenie_opis=form.get("wydarzenie_opis"),
                    panstwo_id=panstwo.PANSTWO_ID if panstwo else None,
                    region_id=region.region_id if region else None,
                    miasto_id=miasto.miasto_id if miasto else None,
                )
    
                db.session.add(h)
                db.session.commit()
    
                flash("Wydarzenie zostało dodane.", "success")
                return redirect(url_for("historia_lista"))
    
            except Exception as e:
                db.session.rollback()
                flash(str(e), "error")

                panstwa = Panstwo.query.order_by(Panstwo.panstwo_nazwa).all()

                return render_template(
                    "historia_form_add.html",
                    panstwa=panstwa,
                    kontynenty=kontynenty,
                    form_data={}
                )
        
        return render_template(
            "historia_form_add.html",
            panstwa=panstwa,
            kontynenty=kontynenty,
            form_data={}
        )

    # --------------------------------------------------------
    # EDYCJA WYDARZENIA
    # --------------------------------------------------------
    @app.route("/historia/<int:historia_id>/edit", methods=["GET", "POST"])
    @wymaga_roli("wszechmocny")
    def historia_edytuj(historia_id):

        def parse_fk(v):
            return int(v) if v and v.isdigit() else None

        panstwa = Panstwo.query.order_by(Panstwo.panstwo_nazwa).all()

        kontynenty = DictKontynent.query.order_by(
            DictKontynent.kontynent_nazwa
        ).all()

        h = Historia.query.get_or_404(historia_id)
    
        if request.method == "POST":
            try:
                form = request.form
    
                # ───────────────
                # POLA PODSTAWOWE
                # ───────────────
                h.nazwa_wydarzenia = form.get("nazwa_wydarzenia")
                h.epoka = form.get("epoka")
                h.kontynent_id = parse_fk(form.get("kontynent_id"))
                h.wydarzenie_opis = form.get("wydarzenie_opis")
    
                # ───────────────
                # DATY
                # ───────────────
                h.data_od = parse_year_or_date(form.get("data_od"))
                data_do_raw = form.get("data_do")
                h.data_do = parse_year_or_date(data_do_raw) if data_do_raw else None
    
                if h.data_do and h.data_do < h.data_od:
                    raise ValueError("Data końcowa nie może być wcześniejsza niż początkowa.")
    
                panstwo_id = parse_fk(form.get("panstwo_id"))
                region_id = parse_fk(form.get("region_id"))
                miasto_id = parse_fk(form.get("miasto_id"))
    
                # ───────────────
                # HIERARCHIA GEO
                # ───────────────
                panstwo = region = miasto = None
    
                if miasto_id:
                    miasto = Miasto.query.get(miasto_id)
                    if not miasto:
                        raise ValueError("Wybrane miasto nie istnieje.")
    
                    region = miasto.region
                    panstwo = miasto.panstwo
    
                if region_id:
                    region = Region.query.get(region_id)
                    if not region:
                        raise ValueError("Wybrany region nie istnieje.")
    
                    if miasto and miasto.region_id != region.region_id:
                        raise ValueError("Miasto nie należy do wybranego regionu.")
    
                    panstwo = region.panstwo
    
                if panstwo_id:
                    panstwo = Panstwo.query.get(panstwo_id)
                    if not panstwo:
                        raise ValueError("Wybrane państwo nie istnieje.")
    
                    if region and panstwo and region.panstwo_id != panstwo.PANSTWO_ID:
                        raise ValueError("Region nie należy do wybranego państwa.")
    
                # ───────────────
                # PRZYPISANIE FK
                # ───────────────
                h.panstwo_id = panstwo.PANSTWO_ID if panstwo else None
                h.region_id = region.region_id if region else None
                h.miasto_id = miasto.miasto_id if miasto else None
    
                # ───────────────
                # ZAPIS
                # ───────────────
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
                    h=h,
                    panstwa=panstwa,
                    kontynenty=kontynenty
                )
    
        # ───────────────
        # GET
        # ───────────────
        return render_template(
            "historia_form_edit.html",
            h=h,
            panstwa=panstwa,
            kontynenty=kontynenty
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

