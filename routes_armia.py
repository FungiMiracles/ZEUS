# routes_armia.py
from flask import render_template, request, jsonify, redirect, url_for, flash
from extensions import db
from models import Panstwo, Wojsko
from permissions import wymaga_roli

def init_armia_routes(app):

    # ------------------------------------------------------------
    # AUTOCOMPLETE – lista państw do wyszukiwarki
    # ------------------------------------------------------------
    @app.route("/api/panstwa_autocomplete")
    def panstwa_autocomplete():
        q = request.args.get("query", "").strip()

        if not q or len(q) < 1:
            return jsonify([])

        query = Panstwo.query

        if q.isdigit():
            query = query.filter(Panstwo.PANSTWO_ID.like(f"%{q}%"))
        else:
            query = query.filter(Panstwo.panstwo_nazwa.like(f"%{q}%"))

        results = query.limit(20).all()

        return jsonify([
            {
                "id": p.PANSTWO_ID,
                "nazwa": p.panstwo_nazwa,
                "populacja": p.panstwo_populacja or 0
            }
            for p in results
        ])

    # ------------------------------------------------------------
    # API – pobranie populacji państwa
    # ------------------------------------------------------------
    @app.route("/api/panstwo_populacja")
    def panstwo_populacja():
        panstwo_id = request.args.get("id")

        if not panstwo_id or not panstwo_id.isdigit():
            return jsonify({"populacja": 0})

        p = Panstwo.query.get(int(panstwo_id))
        if not p:
            return jsonify({"populacja": 0})

        return jsonify({"populacja": p.panstwo_populacja or 0})

    # ------------------------------------------------------------
    # DODAWANIE WOJSKA — GET + POST
    # ------------------------------------------------------------
    @app.route("/wojsko_form_add", methods=["GET", "POST"])
    @wymaga_roli("tworzyciel", "wszechmocny")
    def wojsko_form_add():
        form_data = request.form

        if request.method == "POST":

            # 1. Sprawdzenie państwa
            panstwo_id = form_data.get("panstwo_id", "").strip()
            if not panstwo_id.isdigit():
                return render_template(
                    "wojsko_form_add.html",
                    error="Musisz wybrać poprawne państwo z listy.",
                    form_data=form_data
                )

            panstwo_id = int(panstwo_id)
            panstwo = Panstwo.query.get(panstwo_id)
            if not panstwo:
                return render_template(
                    "wojsko_form_add.html",
                    error="Wybrane państwo nie istnieje.",
                    form_data=form_data
                )

            # 🔥🔥🔥 2. BLOKADA DUPLIKATU
            istnieje = Wojsko.query.filter_by(panstwo_id=panstwo_id).first()
            if istnieje:
                return render_template(
                    "wojsko_form_add.html",
                    error=(
                        f"Dla państwa {panstwo.panstwo_nazwa} "
                        "istnieją już dane wojskowe. "
                        "Możesz je edytować w widoku państwa."
                    ),
                    form_data=form_data
                )
            # 🔥🔥🔥 KONIEC BLOKADY

            # 3. Walidacja procentu PKB
            try:
                procent_PKB = float(form_data.get("procent_PKB"))
                if procent_PKB < 0 or procent_PKB > 100:
                    raise ValueError
            except:
                return render_template(
                    "wojsko_form_add.html",
                    error="Pole 'Procent PKB' musi mieć wartość 0–100.",
                    form_data=form_data
                )

            # 4. Pola numeryczne
            numeric_fields = [
                "wojska_ladowe_ilosc", "wojska_morskie_ilosc", "wojska_powietrzne_ilosc",
                "liczba_baz_ladowych", "liczba_baz_morskich", "liczba_baz_powietrznych",
                "czolgi_ilosc", "mysliwce_ilosc", "wozy_opancerzone_ilosc",
                "wyrzutnie_rakiet_ilosc", "okrety_wojenne_ilosc", "lotniskowce_ilosc",
                "okrety_podwodne_ilosc", "drony_ilosc", "bron_atomowa_ilosc"
            ]

            numeric_values = {}
            for field in numeric_fields:
                val = form_data.get(field)
                if val is None or val == "":
                    return render_template(
                        "wojsko_form_add.html",
                        error="Wszystkie pola są wymagane.",
                        form_data=form_data
                    )
                if not val.isdigit():
                    return render_template(
                        "wojsko_form_add.html",
                        error=f"Pole '{field}' musi być liczbą ≥ 0.",
                        form_data=form_data
                    )
                numeric_values[field] = int(val)

            # 5. Zapis
            try:
                wojsko = Wojsko(
                    panstwo_id=panstwo_id,
                    procent_PKB=procent_PKB,
                    **numeric_values
                )
                db.session.add(wojsko)
                db.session.commit()

                flash("Dane o zasobach wojskowych zostały pomyślnie dodane.", "success")

            except Exception as e:
                db.session.rollback()
                return render_template(
                    "wojsko_form_add.html",
                    error=f"Błąd zapisu: {e}",
                    form_data=form_data
                )

            return render_template(
                "wojsko_form_add.html",
                form_data={},
                success="Dane zostały pomyślnie dodane."
            )

        return render_template("wojsko_form_add.html", form_data={})


     # ------------------------------------------------------------
    # PODGLĄD DANYCH WOJSKOWYCH
    # ------------------------------------------------------------
    @app.route("/wojsko/<int:panstwo_id>")
    def wojsko_form(panstwo_id):
        panstwo = Panstwo.query.get_or_404(panstwo_id)
        wojsko = Wojsko.query.filter_by(panstwo_id=panstwo_id).first()

        return render_template(
            "wojsko_form.html",
            panstwo=panstwo,
            wojsko=wojsko
        )

        # ------------------------------------------------------------
    # LISTA SIŁ ZBROJNYCH
    # ------------------------------------------------------------
    
    @app.route("/sily_zbrojne_list")
    def sily_zbrojne_list():
        kontynent = request.args.get("kontynent", "").strip()
        panstwo_q = request.args.get("panstwo", "").strip()

        # Pobranie listy kontynentów (zgodnie z Twoim modelem)
        kontynenty = (
            db.session.query(Panstwo.kontynent_id)
            .distinct()
            .all()
        )
        kontynenty = [k[0] for k in kontynenty if k[0]]

        # ---- BAZOWE ZAPYTANIE ----
        query = (
            db.session.query(
                Panstwo.PANSTWO_ID.label("panstwo_id"),
                Panstwo.panstwo_nazwa.label("panstwo_nazwa"),
                Wojsko.wojska_ladowe_ilosc.label("ladowe"),
                Wojsko.wojska_morskie_ilosc.label("morskie"),
                Wojsko.wojska_powietrzne_ilosc.label("powietrzne"),
                Wojsko.procent_PKB.label("procent_PKB"),
                Wojsko.czolgi_ilosc.label("czolgi"),
                Wojsko.mysliwce_ilosc.label("mysliwce"),
                Wojsko.okrety_wojenne_ilosc.label("okrety"),
            )
            .join(Wojsko, Wojsko.panstwo_id == Panstwo.PANSTWO_ID)
        )

        # ---- FILTR KONTYNENTU ----
        if kontynent:
            query = query.filter(Panstwo.kontynent_id == kontynent)

        # ---- FILTR PAŃSTWA / ID ----
        if panstwo_q:
            if panstwo_q.isdigit():
                query = query.filter(Panstwo.PANSTWO_ID == int(panstwo_q))
            else:
                query = query.filter(Panstwo.panstwo_nazwa.like(f"%{panstwo_q}%"))

        rows = query.all()

        results = []
        for r in rows:
            lacznie = (r.ladowe or 0) + (r.morskie or 0) + (r.powietrzne or 0)

            results.append({
                "panstwo_id": r.panstwo_id,
                "panstwo_nazwa": r.panstwo_nazwa,
                "lacznie": lacznie,
                "procent_PKB": r.procent_PKB or 0,
                "czolgi": r.czolgi or 0,
                "mysliwce": r.mysliwce or 0,
                "okrety": r.okrety or 0,
            })

        empty = len(results) == 0

        return render_template(
            "sily_zbrojne_list.html",
            results=results,
            empty=empty,
            kontynenty=kontynenty
        )
    
        # ------------------------------------------------------------
    # PORÓWNYWARKA – STRONA GŁÓWNA
    # ------------------------------------------------------------
    @app.route("/porownywarka_panstw")
    def porownywarka_panstw():
        return render_template("porownywarka_panstw.html")
    
        # ------------------------------------------------------------
    # API: pobieranie pełnego zestawu danych o państwie
    # ------------------------------------------------------------
    @app.route("/api/panstwo_full")
    def panstwo_full():
        panstwo_id = request.args.get("id", "")

        if not panstwo_id.isdigit():
            return jsonify({"error": "Invalid ID"}), 400

        panstwo = Panstwo.query.get(int(panstwo_id))
        if not panstwo:
            return jsonify({"error": "Not found"}), 404

        wojsko = Wojsko.query.filter_by(panstwo_id=panstwo.PANSTWO_ID).first()

        return jsonify({
            "id": panstwo.PANSTWO_ID,
            "nazwa": panstwo.panstwo_nazwa,
            "kontynent": panstwo.kontynent_id,
            "populacja": panstwo.panstwo_populacja or 0,

            "wojsko": {
                "ladowe": wojsko.wojska_ladowe_ilosc if wojsko else 0,
                "morskie": wojsko.wojska_morskie_ilosc if wojsko else 0,
                "powietrzne": wojsko.wojska_powietrzne_ilosc if wojsko else 0,
                "czolgi": wojsko.czolgi_ilosc if wojsko else 0,
                "mysliwce": wojsko.mysliwce_ilosc if wojsko else 0,
                "okrety": wojsko.okrety_wojenne_ilosc if wojsko else 0,
                "lotniskowce": wojsko.lotniskowce_ilosc if wojsko else 0,
                "atom": wojsko.bron_atomowa_ilosc if wojsko else 0,
                "drony": wojsko.drony_ilosc if wojsko else 0,
                "bazy_ladowe" : wojsko.liczba_baz_ladowych if wojsko else 0,
                "bazy_morskie" : wojsko.liczba_baz_morskich if wojsko else 0,
                "bazy_powietrzne" : wojsko.liczba_baz_powietrznych if wojsko else 0,
                "pkb": wojsko.procent_PKB if wojsko else 0

            }
        })
    
        # ------------------------------------------------------------
    # EDYCJA DANYCH WOJSKOWYCH (GET + POST)
    # ------------------------------------------------------------
    @app.route("/wojsko/<int:panstwo_id>/edit", methods=["GET", "POST"])
    @wymaga_roli("tworzyciel", "wszechmocny")
    def wojsko_form_edit(panstwo_id):
        panstwo = Panstwo.query.get_or_404(panstwo_id)
        wojsko = Wojsko.query.filter_by(panstwo_id=panstwo_id).first()

        if not wojsko:
            flash("To państwo nie posiada jeszcze danych wojskowych.", "warning")
            return redirect(url_for("wojsko_form", panstwo_id=panstwo_id))

        if request.method == "POST":

            form = request.form
            errors = []

            # procent PKB
            try:
                procent_PKB = float(form.get("procent_PKB"))
                if procent_PKB < 0 or procent_PKB > 100:
                    errors.append("Procent PKB musi być w zakresie 0–100.")
            except:
                errors.append("Procent PKB musi być liczbą.")

            # pola numeryczne
            numeric_fields = [
                "wojska_ladowe_ilosc", "wojska_morskie_ilosc", "wojska_powietrzne_ilosc",
                "liczba_baz_ladowych", "liczba_baz_morskich", "liczba_baz_powietrznych",
                "czolgi_ilosc", "mysliwce_ilosc", "okrety_wojenne_ilosc",
                "lotniskowce_ilosc", "okrety_podwodne_ilosc", "wyrzutnie_rakiet_ilosc",
                "wozy_opancerzone_ilosc", "drony_ilosc", "bron_atomowa_ilosc",
            ]

            values = {}

            for field in numeric_fields:
                value = form.get(field, "").strip()

                if not value.isdigit():
                    errors.append(f"Pole '{field}' musi być liczbą całkowitą ≥ 0.")
                else:
                    values[field] = int(value)

            if errors:
                return render_template(
                    "wojsko_form_edit.html",
                    error=" | ".join(errors),
                    panstwo=panstwo,
                    wojsko=wojsko,
                    form_data=form
                )

            # zapis zmian
            wojsko.procent_PKB = procent_PKB

            for field, val in values.items():
                setattr(wojsko, field, val)

            db.session.commit()

            flash("Dane wojskowe zostały zaktualizowane.", "success")
            return redirect(url_for("wojsko_form", panstwo_id=panstwo_id))

        # GET
        return render_template("wojsko_form_edit.html", panstwo=panstwo, wojsko=wojsko)







   
