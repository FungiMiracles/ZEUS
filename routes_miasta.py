# routes_miasta.py
from flask import render_template, request, redirect, url_for, flash
from extensions import db
from models import Miasto, Panstwo, Region
from permissions import wymaga_roli
from demografia_utils import przelicz_region_demografia
from sqlalchemy import or_


def init_miasta_routes(app):
    # --------------------------------
    # Podgląd miasta – ORM
    # --------------------------------
    @app.route("/miasto/<int:miasto_id>")
    def miasto_form(miasto_id):
        miasto = Miasto.query.get_or_404(miasto_id)

        panstwo = miasto.panstwo      # dzięki relacji ORM
        region = miasto.region        # może być None

        return render_template(
            "miasto_form.html",
            miasto=miasto,
            panstwo=panstwo,
            region=region,
        )
    
    # --------------------------------
    # Edycja miasta – GET i POST
    # --------------------------------
    
    @app.route("/miasto/<int:miasto_id>/edit", methods=["GET", "POST"])
    @wymaga_roli("wszechmocny")
    def miasto_form_edit(miasto_id):
        miasto = Miasto.query.get_or_404(miasto_id)

        if request.method == "POST":
            nazwa = request.form.get("miasto_nazwa")
            kod = request.form.get("miasto_kod")
            panstwo_id = request.form.get("panstwo_id")
            populacja = request.form.get("miasto_populacja")
            typ = request.form.get("miasto_typ")
            region_id = request.form.get("region_id")
            czy_na_mapie = request.form.get("czy_na_mapie")
            stara_populacja = miasto.miasto_populacja or 0
            stary_region = miasto.region

            # Walidacja
            errors = []
            if not nazwa:
                errors.append("Nazwa miasta jest wymagana.")
            if not kod:
                errors.append("Kod miasta jest wymagany.")
            if not panstwo_id or not panstwo_id.isdigit():
                errors.append("ID państwa musi być liczbą.")
            if not populacja or not populacja.isdigit():
                errors.append("Populacja musi być liczbą.")
            if not region_id or not region_id.isdigit():
                errors.append("ID regionu musi być liczbą.")
            if czy_na_mapie not in ("TAK", "NIE"):
                errors.append("Nieprawidłowa wartość pola „Na mapie”.")

            if errors:
                return render_template(
                    "miasto_form_edit.html",
                    error=" ".join(errors),
                    miasto=miasto,
                    form_data=request.form
                )

            # Konwersja
            panstwo_id = int(panstwo_id)
            populacja = int(populacja)
            region_id = int(region_id)

            # Walidacja spójności region–państwo
            region_obj = Region.query.get(region_id)
            if not region_obj:
                return render_template(
                    "miasto_form_edit.html",
                    error=f"Region o ID {region_id} nie istnieje.",
                    miasto=miasto,
                    form_data=request.form
                )

            if region_obj.panstwo_id != panstwo_id:
                return render_template(
                    "miasto_form_edit.html",
                    error="Podany region należy do innego państwa.",
                    miasto=miasto,
                    form_data=request.form
                )

            # Aktualizacja
            miasto.miasto_nazwa = nazwa
            miasto.miasto_kod = kod
            miasto.miasto_populacja = populacja
            miasto.miasto_typ = typ
            miasto.panstwo_id = panstwo_id
            miasto.region_id = region_id
            miasto.czy_na_mapie = czy_na_mapie

            # ───── PRZELICZENIE DEMOGRAFII REGIONU ─────
            try:
                przelicz_region_demografia(stary_region)
            except ValueError as e:
                db.session.rollback()
                return render_template(
                    "miasto_form_edit.html",
                    error=str(e),
                    miasto=miasto,
                    form_data=request.form
                )
            
            db.session.commit()

            flash(f"Zmiany zostały wprowadzone dla miasta o ID {miasto_id}.", "success")
            return redirect(url_for("miasto_form", miasto_id=miasto_id))

        # GET — wyświetlenie formularza
        return render_template("miasto_form_edit.html", miasto=miasto)


    # --------------------------------
    # Wyszukiwarka miast – ORM
    # --------------------------------
    @app.route("/wyniki_wyszukiwania_miasto", methods=["GET"])
    def wyniki_wyszukiwania_miasto():
        miasto_nazwa = request.args.get("miasto_nazwa")
        miasto_kod = request.args.get("miasto_kod")
        panstwo_nazwa = request.args.get("panstwo_nazwa")
        region_nazwa = request.args.get("region_nazwa")
        czy_na_mapie = request.args.get("czy_na_mapie")
        miasto_typ = request.args.get("miasto_typ")
        sort_populacja = request.args.get("sort_populacja")
        populacja_od = request.args.get("populacja_od")
        populacja_do = request.args.get("populacja_do")
        bez_regionu = request.args.get("bez_regionu")
        kontynent = request.args.get("kontynent")
    
        page = request.args.get("page", 1, type=int)
        per_page = 25
    
        # --------------------------------------------------
        # BUDOWA ZAPYTANIA
        # --------------------------------------------------
        query = (
            db.session.query(Miasto, Panstwo, Region)
            .join(Panstwo, Miasto.panstwo_id == Panstwo.PANSTWO_ID)
            .outerjoin(Region, Miasto.region_id == Region.region_id)
        )

        if kontynent:
            query = query.filter(Panstwo.kontynent == kontynent)
    
        if miasto_nazwa:
            query = query.filter(Miasto.miasto_nazwa.like(f"{miasto_nazwa}%"))
    
        if miasto_kod:
            query = query.filter(Miasto.miasto_kod.like(f"%{miasto_kod}%"))
    
        if panstwo_nazwa:
            query = query.filter(Panstwo.panstwo_nazwa.like(f"%{panstwo_nazwa}%"))

        if bez_regionu == "1":
            query = query.filter(
                or_(
                    Miasto.region_id.is_(None),
                    Miasto.region_id == 0
                )
            )
        elif region_nazwa:
            query = query.filter(Region.region_nazwa.like(f"%{region_nazwa}%"))
    
        if czy_na_mapie in ("TAK", "NIE"):
            query = query.filter(Miasto.czy_na_mapie == czy_na_mapie)
    
        if miasto_typ:
            query = query.filter(Miasto.miasto_typ == miasto_typ)
    
        if populacja_od and populacja_od.isdigit():
            query = query.filter(Miasto.miasto_populacja >= int(populacja_od))
    
        if populacja_do and populacja_do.isdigit():
            query = query.filter(Miasto.miasto_populacja <= int(populacja_do))
    
        if sort_populacja == "asc":
            query = query.order_by(Miasto.miasto_populacja.asc())
        elif sort_populacja == "desc":
            query = query.order_by(Miasto.miasto_populacja.desc())
    
        # --------------------------------------------------
        # PAGINACJA
        # --------------------------------------------------
        pagination = query.paginate(
            page=page,
            per_page=per_page,
            error_out=False
        )
    
        rows = pagination.items
    
        results = []
        for m, p, r in rows:
            results.append(
                {
                    "miasto_id": m.miasto_id,
                    "miasto_nazwa": m.miasto_nazwa,
                    "miasto_kod": m.miasto_kod,
                    "miasto_populacja": m.miasto_populacja,
                    "miasto_typ": m.miasto_typ,
                    "czy_na_mapie": m.czy_na_mapie,
                    "panstwo_nazwa": p.panstwo_nazwa,
                    "region_nazwa": r.region_nazwa if r else "Brak przypisania regionalnego",
                    "kontynent": p.kontynent,
                }
            )
        
        kontynenty = (
            db.session.query(Panstwo.kontynent)
            .distinct()
            .order_by(Panstwo.kontynent)
            .all()
        )
        kontynenty = [k[0] for k in kontynenty if k[0]]

        panstwa_query = Panstwo.query

        if kontynent:
            panstwa_query = panstwa_query.filter(Panstwo.kontynent == kontynent)

        panstwa = panstwa_query_order_by(Panstwo.panstwo_nazwa).all()

        regiony_query = Region.query.join(Panstwo)

        if kontynent:
            region_query = regiony_query.filter(Panstwo.kontynent == kontynent)

        if panstwo_nazwa:
            region_query = regiony_query.filter(
                Panstwo.panstwo_nazwa == panstwo_nazwa
            )

        regiony = regiony_query.order_by(Region.region_nazwa).all()
    
        # --------------------------------------------------
        # ARGUMENTY DO PAGINACJI (BEZ page)
        # --------------------------------------------------
        args = request.args.to_dict(flat=True)
        args.pop("page", None)
    
        empty = pagination.total == 0
    
        return render_template(
            "wyniki_wyszukiwania_miasto.html",
            results=results,
            pagination=pagination,
            total=pagination.total,
            args=args,
            empty=empty,

            kontynenty=kontynenty,
            panstwa=panstwa,
            regiony=regiony,

            selected_kontynent=kontynent,
            selected_panstwo_nazwa=panstwo_nazwa,
            selected_region_nazwa=region_nazwa
        )

    # --------------------------------
    # Dodawanie miasta – ORM + walidacja duplikatów
    # --------------------------------
    @app.route("/miasto_form_add", methods=["GET", "POST"])
    @wymaga_roli("tworzyciel", "wszechmocny")
    def miasto_form_add():

        empty_miasto = Miasto()

        # ───── GET ─────
        if request.method == "GET":
            return render_template(
                "miasto_form_add.html",
                miasto=empty_miasto,
                form_data={}
            )

        # ───── POST (DOPIERO OD TĄD ISTNIEJĄ ZMIENNE!) ─────
        nazwa = request.form.get("miasto_nazwa")
        kod = request.form.get("miasto_kod")
        panstwo_id = request.form.get("panstwo_id")
        populacja = request.form.get("miasto_populacja")
        typ = request.form.get("miasto_typ")
        region_id = request.form.get("region_id")
        czy_na_mapie = request.form.get("czy_na_mapie")

        # ↓↓↓ OD TEGO MOMENTU WOLNO UŻYWAĆ `nazwa` ↓↓↓

        # walidacje
        required_fields = [nazwa, kod, panstwo_id, populacja, typ, region_id, czy_na_mapie]
        if any(not f for f in required_fields):
            return render_template(
                "miasto_form_add.html",
                miasto=empty_miasto,
                error="Wszystkie pola formularza są obowiązkowe.",
                form_data=request.form,
            )

        # konwersje
        panstwo_id = int(panstwo_id)
        region_id = int(region_id)
        populacja = int(populacja)

        # duplikaty — TERAZ JUŻ BEZPIECZNIE
        duplicate_cities = (
            db.session.query(Miasto)
            .filter(Miasto.miasto_nazwa == nazwa)
            .all()
        )

        if duplicate_cities:
            return render_template(
                "miasto_form_add.html",
                miasto=empty_miasto,
                error="Miasto o takiej nazwie już istnieje.",
                form_data=request.form,
            )

        # zapis miasta
        miasto = Miasto(
            miasto_nazwa=nazwa,
            miasto_kod=kod,
            panstwo_id=panstwo_id,
            miasto_populacja=populacja,
            miasto_typ=typ,
            region_id=region_id,
            czy_na_mapie=czy_na_mapie,
        )

        db.session.add(miasto)

        try:
            przelicz_region_demografia(Region.query.get(region_id))
        except ValueError as e:
            db.session.rollback()
            return render_template(
                "miasto_form_add.html",
                miasto=empty_miasto,
                error=str(e),
                form_data=request.form,
            )

        db.session.commit()
        return redirect(url_for("miasto_dodano"))
    
    # --------------------------------
    # Przypisanie regionu do miasta – ORM
    # --------------------------------
    @app.route("/przypisz_region/<int:miasto_id>", methods=["POST"])
    @wymaga_roli("wszechmocny")
    def przypisz_region(miasto_id):
        region_input = request.form.get("region_input")

        if not region_input:
            flash("Musisz podać ID lub nazwę regionu.", "error")
            return redirect(request.referrer or url_for("wyniki_wyszukiwania_miasto"))

        miasto = Miasto.query.get_or_404(miasto_id)

        # Szukanie regionu po ID lub nazwie
        if region_input.isdigit():
            region = Region.query.get(int(region_input))
        else:
            region = Region.query.filter_by(region_nazwa=region_input).first()

        if not region:
            flash("Nie znaleziono regionu o takim ID lub nazwie.", "error")
            return redirect(request.referrer or url_for("wyniki_wyszukiwania_miasto"))

        if region.panstwo_id != miasto.panstwo_id:
            flash("Region należy do innego państwa niż to miasto.", "error")
            return redirect(request.referrer or url_for("wyniki_wyszukiwania_miasto"))

        try:
            miasto.region_id = region.region_id
            db.session.commit()
            flash(
                f"Przypisano region: {region.region_nazwa} (ID {region.region_id}) do miasta {miasto.miasto_nazwa}.",
                "success",
            )
        except Exception as e:
            db.session.rollback()
            flash(f"Wystąpił błąd podczas przypisywania regionu: {e}", "error")

        return redirect(request.referrer or url_for("wyniki_wyszukiwania_miasto"))

    # --------------------------------
    # Usuwanie miasta
    # --------------------------------
    @app.route("/usun_miasto/<int:miasto_id>", methods=["POST"])
    @wymaga_roli("wszechmocny")
    def usun_miasto(miasto_id):
        miasto = Miasto.query.get_or_404(miasto_id)
        region = miasto.region
    
        try:
            db.session.delete(miasto)
    
            # 🔥 zwrot ludności przez PRZELICZENIE
            if region:
                przelicz_region_demografia(region)
    
            db.session.commit()
            flash(f"Miasto {miasto.miasto_nazwa} zostało usunięte, a populacja regionu ponownie przeliczona.", "success")
    
        except Exception as e:
            db.session.rollback()
            flash(f"Błąd podczas usuwania miasta: {e}", "error")
    
        return redirect(request.referrer or url_for("wyniki_wyszukiwania_miasto"))
        
