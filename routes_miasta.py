# routes_miasta.py
from flask import render_template, request, redirect, url_for, flash
from extensions import db
from models import Miasto, Panstwo, Region
from permissions import wymaga_roli


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

        query = (
            db.session.query(Miasto, Panstwo, Region)
            .join(Panstwo, Miasto.panstwo_id == Panstwo.PANSTWO_ID)
            .outerjoin(Region, Miasto.region_id == Region.region_id)
        )

        if miasto_nazwa:
            query = query.filter(Miasto.miasto_nazwa.like(f"{miasto_nazwa}%"))

        if miasto_kod:
            query = query.filter(Miasto.miasto_kod.like(f"%{miasto_kod}%"))

        if panstwo_nazwa:
            query = query.filter(Panstwo.panstwo_nazwa.like(f"%{panstwo_nazwa}%"))

        if region_nazwa:
            query = query.filter(Region.region_nazwa.like(f"%{region_nazwa}%"))

        rows = query.all()

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
                }
            )

        empty = len(results) == 0

        return render_template(
            "wyniki_wyszukiwania_miasto.html", results=results, empty=empty
        )

    # --------------------------------
    # Dodawanie miasta – ORM + walidacja duplikatów
    # --------------------------------
    @app.route("/miasto_form_add", methods=["GET", "POST"])
    @wymaga_roli("tworzyciel", "wszechmocny")
    def miasto_form_add():

        # „Puste miasto” do template (żeby Jinja nie krzyczała)
        empty_miasto = Miasto()

        if request.method == "POST":
            nazwa = request.form.get("miasto_nazwa")
            kod = request.form.get("miasto_kod")
            panstwo_id = request.form.get("panstwo_id")
            populacja = request.form.get("miasto_populacja")
            typ = request.form.get("miasto_typ")
            region_id = request.form.get("region_id")
            czy_na_mapie = request.form.get("czy_na_mapie")

            # ───── WALIDACJA PODSTAWOWA ─────
            required_fields = [
                nazwa,
                kod,
                panstwo_id,
                populacja,
                typ,
                region_id,
                czy_na_mapie,
            ]

            if any(not field for field in required_fields):
                return render_template(
                    "miasto_form_add.html",
                    miasto=empty_miasto,
                    error="Wszystkie pola formularza są obowiązkowe.",
                    form_data=request.form,
                )

            errors = []

            if not panstwo_id.isdigit():
                errors.append("Pole „ID państwa” musi być liczbą.")

            if not region_id.isdigit():
                errors.append("Pole „ID regionu” musi być liczbą.")

            if not populacja.isdigit():
                errors.append("Pole „Populacja miasta” musi być liczbą.")

            if czy_na_mapie not in ("TAK", "NIE"):
                errors.append("Nieprawidłowa wartość pola „Na mapie”.")

            if errors:
                return render_template(
                    "miasto_form_add.html",
                    miasto=empty_miasto,
                    error=" ".join(errors),
                    form_data=request.form,
                )

            # ───── KONWERSJE ─────
            panstwo_id = int(panstwo_id)
            region_id = int(region_id)
            populacja = int(populacja)

            # ───── SPRAWDZENIE PAŃSTWA ─────
            panstwo_obj = Panstwo.query.get(panstwo_id)
            if not panstwo_obj:
                return render_template(
                    "miasto_form_add.html",
                    miasto=empty_miasto,
                    error=f"Państwo o ID {panstwo_id} nie istnieje.",
                    form_data=request.form,
                )

            # ───── SPRAWDZENIE REGIONU ─────
            region_obj = Region.query.get(region_id)
            if not region_obj:
                return render_template(
                    "miasto_form_add.html",
                    miasto=empty_miasto,
                    error=f"Region o ID {region_id} nie istnieje.",
                    form_data=request.form,
                )

            # ───── WALIDACJA KLUCZOWA REGION ↔ PAŃSTWO ─────
            if region_obj.panstwo_id != panstwo_obj.PANSTWO_ID:
                return render_template(
                    "miasto_form_add.html",
                    miasto=empty_miasto,
                    error=(
                        f"Region „{region_obj.region_nazwa}” należy do państwa "
                        f"„{region_obj.panstwo.panstwo_nazwa}”, a nie do "
                        f"„{panstwo_obj.panstwo_nazwa}”."
                    ),
                    form_data=request.form,
                )

            # ───── DUPLIKATY ─────
            duplicate_cities = (
                db.session.query(Miasto, Panstwo, Region)
                .join(Panstwo, Miasto.panstwo_id == Panstwo.PANSTWO_ID)
                .outerjoin(Region, Miasto.region_id == Region.region_id)
                .filter(Miasto.miasto_nazwa == nazwa)
                .all()
            )

            if duplicate_cities:
                duplicates_info = [
                    f"{m.miasto_nazwa} — Państwo: {p.panstwo_nazwa}, "
                    f"Region: {r.region_nazwa if r else 'Brak'}"
                    for m, p, r in duplicate_cities
                ]

                return render_template(
                    "miasto_form_add.html",
                    miasto=empty_miasto,
                    error="Miasto o takiej nazwie już istnieje.",
                    duplicates=duplicates_info,
                    form_data=request.form,
                )

            # ───── ZAPIS DO BAZY ─────
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
            db.session.commit()

            return redirect(url_for("miasto_dodano"))

        # ───── GET — pusty formularz ─────
        return render_template(
            "miasto_form_add.html",
            miasto=empty_miasto,
            form_data={}
        )


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
        try:
            db.session.delete(miasto)
            db.session.commit()
            flash(f"Miasto {miasto.miasto_nazwa} zostało usunięte.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Błąd podczas usuwania miasta: {e}", "error")

        return redirect(request.referrer or url_for("wyniki_wyszukiwania_miasto"))
