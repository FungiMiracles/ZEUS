from flask import (
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify
)
from extensions import db

from models import (
    Panstwo,
    Stosunki,
    DictKontynent,
    DictStosunkiStan,
    DictStosunkiRelacja,
    OrganizacjaMiedzynarodowa,
    OrganizacjaPanstwo
)

from permissions import wymaga_roli
from sqlalchemy import or_
from sqlalchemy.orm import joinedload
from datetime import datetime


def init_dyplomacja_routes(app):

    # ============================================================
    # LISTA STOSUNKÓW
    # ============================================================
    @app.route("/dyplomacja/list")
    def dyplomacja_list():
        panstwa = Panstwo.query.order_by(Panstwo.panstwo_nazwa).all()
        
        stosunki = (
            Stosunki.query
            .join(Panstwo, Stosunki.PANSTWO_ID == Panstwo.PANSTWO_ID)
            .order_by(Stosunki.PANSTWO_ID, Stosunki.PANSTWO_ID2)
            .all()
        )

        return render_template(
            "dyplomacja_list.html",
            stosunki=stosunki,
            panstwa=panstwa
        )

    # ============================================================
    # FORMULARZ DODAWANIA / EDYCJI
    # ============================================================
    @app.route("/dyplomacja/edit/<int:p1>/<int:p2>", methods=["GET", "POST"])
    @wymaga_roli("wszechmocny")
    def dyplomacja_edit(p1, p2):

        panstwa = Panstwo.query.order_by(Panstwo.panstwo_nazwa).all()

        relacje = DictStosunkiRelacja.query.order_by(
            DictStosunkiRelacja.relacja_nazwa
        ).all()

        stany = DictStosunkiStan.query.order_by(
            DictStosunkiStan.stan_nazwa
        ).all()

        # ─────────────────────────────
        # NORMALIZACJA PAR
        # ─────────────────────────────
        a, b = sorted([p1, p2])

        stosunek = Stosunki.query.filter_by(
            PANSTWO_ID=a,
            PANSTWO_ID2=b
        ).first()

        if not stosunek:
            stosunek = Stosunki(
                PANSTWO_ID=a,
                PANSTWO_ID2=b,
                relacja_id=6,   # neutralne
                stan_id=1       # pokoj
            )
            db.session.add(stosunek)
            db.session.flush()  # ← ważne, bez commit
            
        # ─────────────────────────────
        # POST
        # ─────────────────────────────
        if request.method == "POST":

            relacja_id = request.form.get("relacja_id")
            stan_id = request.form.get("stan_id")

            stosunek.relacja_id = int(relacja_id)
            stosunek.stan_id = int(stan_id)

            try:
                db.session.commit()
                flash("Stosunki dyplomatyczne zapisane.", "success")
                return redirect(url_for("dyplomacja_list"))
            except Exception as e:
                db.session.rollback()
                flash(f"Błąd zapisu: {e}", "error")

                return render_template(
                    "dyplomacja_edit.html",
                    panstwa=panstwa,
                    relacje=relacje,
                    stany=stany,
                    form_data=request.form
                )

        # ─────────────────────────────
        # GET
        # ─────────────────────────────
        form_data = {
            "panstwo_id": str(p1),
            "panstwo_id2": str(p2),
            "relacja_id": stosunek.relacja_id,
            "stan_id": stosunek.stan_id
        }

        return render_template(
            "dyplomacja_edit.html",
            panstwa=panstwa,
            relacje=relacje,
            stany=stany,
            form_data=form_data
        )
    

    @app.route("/dyplomacja/sojusze")
    def dyplomacja_sojusze():

        panstwo_id = request.args.get("panstwo_id", type=int)
        kontynent_id = request.args.get("kontynent_id", type=int)

        kontynenty = (
            DictKontynent.query
            .order_by(DictKontynent.kontynent_nazwa)
            .all()
        )

        return render_template(
            "dyplomacja_sojusze.html",
            kontynenty=kontynenty,
            panstwo_id=panstwo_id,
            kontynent_id=kontynent_id
        )


    # ============================================================
    # USUWANIE RELACJI
    # ============================================================
    @app.route("/dyplomacja/delete/<int:p1>/<int:p2>", methods=["POST"])
    @wymaga_roli("wszechmocny")
    def dyplomacja_delete(p1, p2):

        a, b = sorted([p1, p2])

        stosunek = Stosunki.query.filter_by(
            PANSTWO_ID=a,
            PANSTWO_ID2=b
        ).first_or_404()

        try:
            db.session.delete(stosunek)
            db.session.commit()
            flash("Relacja dyplomatyczna usunięta.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Błąd usuwania: {e}", "error")

        return redirect(url_for("dyplomacja_list"))

    @app.route("/api/dyplomacja")
    def api_dyplomacja():

        p1 = request.args.get("p1", type=int)
        p2 = request.args.get("p2", type=int)

        if not p1 or not p2 or p1 == p2:
            return jsonify({
                "relacja": "Neutralne",
                "stan": "Pokój"
            })

        # 🔑 kanoniczna kolejność
        a, b = sorted([p1, p2])

        rel = (
            Stosunki.query
            .filter_by(PANSTWO_ID=a, PANSTWO_ID2=b)
            .first()
        )

        if not rel:
            return jsonify({
                "relacja": "Neutralne",
                "stan": "Pokój"
            })

        return jsonify({
            "relacja": rel.relacja.relacja_nazwa if rel.relacja else "Neutralne",
            "stan": rel.stan.stan_nazwa if rel.stan else "Pokój"
        })

    @app.route("/api/dyplomacja/kontynenty")
    def api_dyplomacja_kontynenty():

        kontynenty = (
            DictKontynent.query
            .order_by(DictKontynent.kontynent_nazwa)
            .all()
        )

        return jsonify([
            {
                "id": k.kontynent_id,
                "nazwa": k.kontynent_nazwa
            }
            for k in kontynenty
        ])

    @app.route("/api/dyplomacja/sojusze")
    def api_dyplomacja_sojusze():

        panstwo_id = request.args.get("panstwo_id", type=int)
        relacja = request.args.get("relacja")
        stan = request.args.get("stan")

        if not panstwo_id:
            return jsonify([])

        # 🔧 NORMALIZACJA (underscore → spacje + kapitalizacja)
        def normalize(v):
            if not v:
                return v
            return v.replace("_", " ").capitalize()

        relacja_norm = normalize(relacja)
        stan_norm = normalize(stan)

        # 🔍 baza zapytania
        q = Stosunki.query.filter(
            or_(
                Stosunki.PANSTWO_ID == panstwo_id,
                Stosunki.PANSTWO_ID2 == panstwo_id
            )
        )

        # 🔍 filtr relacji
        if relacja_norm:
            q = q.join(Stosunki.relacja).filter(
                DictStosunkiRelacja.relacja_nazwa == relacja_norm
            )

        # 🔍 filtr stanu
        if stan_norm:
            q = q.join(Stosunki.stan).filter(
                DictStosunkiStan.stan_nazwa == stan_norm
            )

        wyniki = []

        for s in q.all():

            other_id = (
                s.PANSTWO_ID2 if s.PANSTWO_ID == panstwo_id else s.PANSTWO_ID
            )

            p = db.session.get(Panstwo, other_id)

            if not p:
                continue

            wyniki.append({
                "panstwo_id": p.PANSTWO_ID,
                "panstwo_nazwa": p.panstwo_nazwa,
                "relacja": s.relacja.relacja_nazwa if s.relacja else "Neutralne",
                "stan": s.stan.stan_nazwa if s.stan else "Pokój"
            })

        return jsonify(wyniki)
    
    @app.route("/api/dyplomacja/panstwa")
    def api_dyplomacja_panstwa():

        kontynent_id = request.args.get("kontynent_id", type=int)

        if not kontynent_id:
            return jsonify([])

        panstwa = (
            Panstwo.query
            .filter(Panstwo.kontynent_id == kontynent_id)
            .order_by(Panstwo.panstwo_nazwa)
            .all()
        )

        return jsonify([
            {
                "id": p.PANSTWO_ID,
                "nazwa": p.panstwo_nazwa
            }
            for p in panstwa
        ])
    
    @app.route("/dyplomacja/organizacje")
    def organizacje_view():

        kontynenty = DictKontynent.query.order_by(DictKontynent.kontynent_nazwa).all()
        organizacje = OrganizacjaMiedzynarodowa.query.order_by(
            OrganizacjaMiedzynarodowa.org_nazwa
        ).all()

        # 🔽 PARAMETRY Z FORMULARZA
        panstwo_id = request.args.get("panstwo_id", type=int)
        org_id = request.args.get("org_id", type=int)
        status = request.args.get("status")

        query = OrganizacjaMiedzynarodowa.query

        # 🔽 FILTR: organizacja
        if org_id:
            query = query.filter_by(ORG_ID=org_id)

        # 🔽 FILTR: status
        if status == "1":
            query = query.filter_by(czy_aktywna=True)
        elif status == "0":
            query = query.filter_by(czy_aktywna=False)

        orgs = query.order_by(OrganizacjaMiedzynarodowa.org_nazwa).all()

        results = []

        for org in orgs:

            members = (
                OrganizacjaPanstwo.query
                .filter_by(org_id=org.ORG_ID)
                .options(joinedload(OrganizacjaPanstwo.panstwo))
                .all()
            )

            # 🔽 FILTR: państwo (ważne!)
            if panstwo_id:
                exists = any(m.panstwo_id == panstwo_id for m in members)
                if not exists:
                    continue

            # 🔽 wrzucamy members do obiektu
            org.members = members

            results.append(org)

        return render_template(
            "dyplomacja_organizacje_miedzynarodowe.html",
            kontynenty=kontynenty,
            organizacje=organizacje,
            results=results
        )


    # =========================
    # API: ORGANIZACJE
    # =========================
    @app.route("/api/dyplomacja/organizacje")
    def api_organizacje():

        panstwo_id = request.args.get("panstwo_id", type=int)
        org_id = request.args.get("org_id", type=int)
        active = request.args.get("active")
        inactive = request.args.get("inactive")

        query = OrganizacjaMiedzynarodowa.query

        if org_id:
            query = query.filter_by(ORG_ID=org_id)

        if active and not inactive:
            query = query.filter_by(czy_aktywna=True)

        if inactive and not active:
            query = query.filter_by(czy_aktywna=False)

        orgs = query.order_by(OrganizacjaMiedzynarodowa.org_nazwa).all()

        wynik = []

        for org in orgs:

            # sprawdzenie czy organizacja ma dane państwo
            if panstwo_id:
                exists = OrganizacjaPanstwo.query.filter_by(
                    org_id=org.ORG_ID,
                    panstwo_id=panstwo_id
                ).first()

                if not exists:
                    continue

            # pobierz wszystkich członków (1 query)
            members = (
                OrganizacjaPanstwo.query
                .filter_by(org_id=org.ORG_ID)
                .options(joinedload(OrganizacjaPanstwo.panstwo))
                .all()
            )

            wynik.append({
                "id": org.ORG_ID,
                "nazwa": org.org_nazwa,
                "skrot": org.org_skrot,
                "typ": org.org_typ,
                "opis": org.org_opis,
                "aktywna": org.czy_aktywna,
                "czlonkowie": [m.panstwo.panstwo_nazwa for m in members]
            })

        return jsonify(wynik)
    
    @app.route("/dyplomacja/organizacja/<int:org_id>")
    def organizacja_form(org_id):

        org = OrganizacjaMiedzynarodowa.query.get_or_404(org_id)

        members = (
            OrganizacjaPanstwo.query
            .filter_by(org_id=org_id)
            .options(joinedload(OrganizacjaPanstwo.panstwo))
            .all()
        )

        return render_template(
            "organizacja_form.html",
            org=org,
            members=members
        )
    
    @app.route("/dyplomacja/organizacja/<int:org_id>/edit", methods=["GET", "POST"])
    @wymaga_roli("wszechmocny")
    def organizacja_form_edit(org_id):

        org = OrganizacjaMiedzynarodowa.query.get_or_404(org_id)

        if request.method == "POST":

            org.org_nazwa = request.form.get("org_nazwa")
            org.org_skrot = request.form.get("org_skrot")
            org.org_typ = request.form.get("org_typ")
            org.org_opis = request.form.get("org_opis")
            org.siedziba = request.form.get("siedziba")

            value = request.form.get("czy_aktywna")
            org.czy_aktywna = True if value == "1" else False

            try:
                db.session.commit()
                flash("Organizacja zaktualizowana.", "success")
                return redirect(url_for("organizacja_form", org_id=org_id))
            except Exception as e:
                db.session.rollback()
                flash(f"Błąd zapisu: {e}", "error")

        return render_template("organizacja_form_edit.html", org=org)
    
    @app.route("/dyplomacja/organizacja/<int:org_id>/delete", methods=["POST"])
    @wymaga_roli("wszechmocny")
    def organizacja_delete(org_id):

        org = OrganizacjaMiedzynarodowa.query.get_or_404(org_id)

        # 🔍 sprawdzenie czy są członkowie
        members_exist = OrganizacjaPanstwo.query.filter_by(org_id=org_id).first()

        if members_exist:
            flash(
                "Nie możesz usunąć organizacji, do której należą państwa. "
                "Wszystkie państwa muszą najpierw odejść z organizacji.",
                "error"
            )
            return redirect(request.referrer or url_for("organizacje_view"))

        try:
            db.session.delete(org)
            db.session.commit()
            flash("Organizacja usunięta.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Błąd usuwania: {e}", "error")

        return redirect(request.referrer or url_for("organizacje_view"))
    
    @app.route("/dyplomacja/organizacja/<int:org_id>/add_country", methods=["GET", "POST"])
    @wymaga_roli("wszechmocny")
    def organizacja_add_country(org_id):

        org = OrganizacjaMiedzynarodowa.query.get_or_404(org_id)

        kontynenty = (
            DictKontynent.query
            .order_by(DictKontynent.kontynent_nazwa)
            .all()
        )

        if request.method == "POST":

            panstwo_id = request.form.get("panstwo_id", type=int)
            data_raw = request.form.get("data_dolaczenia")

            if not data_raw:
                flash("Podaj datę dołączenia państwa do organizacji.", "error")
                return redirect(request.url)

            try:
                data_dolaczenia = datetime.strptime(data_raw, "%Y-%m-%d")
            except Exception:
                flash("Niepoprawny format daty.", "error")
                return redirect(request.url)

            # ❗ walidacja
            if not panstwo_id:
                flash("Musisz wybrać państwo.", "error")
                return redirect(request.url)

            # ❗ sprawdzenie czy już istnieje
            exists = OrganizacjaPanstwo.query.filter_by(
                org_id=org_id,
                panstwo_id=panstwo_id
            ).first()

            if exists:
                flash("To państwo już należy do tej organizacji.", "error")
                return redirect(request.url)

            try:
                rel = OrganizacjaPanstwo(
                    org_id=org_id,
                    panstwo_id=panstwo_id,
                    status_czlonkostwa="czlonek",
                    data_dolaczenia=data_dolaczenia
                )

                db.session.add(rel)
                db.session.commit()

                flash("Państwo dodane do organizacji.", "success")
                return redirect(url_for("organizacja_form", org_id=org_id))

            except Exception as e:
                db.session.rollback()
                flash(f"Błąd: {e}", "error")

        return render_template(
            "organizacja_add_country.html",
            org=org,
            kontynenty=kontynenty
        )
    
    @app.route("/dyplomacja/organizacja/add", methods=["GET", "POST"])
    @wymaga_roli("wszechmocny")
    def organizacja_add():

        if request.method == "POST":

            nazwa = request.form.get("org_nazwa")
            skrot = request.form.get("org_skrot")
            typ = request.form.get("org_typ")
            opis = request.form.get("org_opis")
            aktywna = True if request.form.get("czy_aktywna") else False
            siedziba = request.form.get("siedziba")

            if not nazwa:
                flash("Podaj nazwę organizacji.", "error")
                return redirect(request.url)

            org = OrganizacjaMiedzynarodowa(
                org_nazwa=nazwa,
                org_skrot=skrot,
                org_typ=typ,
                org_opis=opis,
                czy_aktywna=aktywna,
                siedziba=siedziba
            )

            db.session.add(org)
            db.session.commit()

            flash("Organizacja została dodana.", "success")
            return redirect("/dyplomacja/organizacje")

        return render_template("organizacja_form_add.html")
    
    @app.route("/dyplomacja/organizacja/<int:org_id>/member/<int:panstwo_id>/leave", methods=["POST"])
    @wymaga_roli("wszechmocny")
    def organizacja_member_leave(org_id, panstwo_id):

        rel = OrganizacjaPanstwo.query.filter_by(
            org_id=org_id,
            panstwo_id=panstwo_id
        ).first()

        if not rel:
            flash("Nie znaleziono członka organizacji.", "error")
            return redirect(request.referrer or url_for("organizacje_view"))

        rel.status_czlonkostwa = "byly_czlonek"

        db.session.commit()

        flash("Państwo opuściło organizację.", "success")
        return redirect(request.referrer or url_for("organizacje_view"))
    
    @app.route("/dyplomacja/organizacja/<int:org_id>/member/<int:panstwo_id>/suspend", methods=["POST"])
    @wymaga_roli("wszechmocny")
    def organizacja_member_suspend(org_id, panstwo_id):

        rel = OrganizacjaPanstwo.query.filter_by(
            org_id=org_id,
            panstwo_id=panstwo_id
        ).first()

        if not rel:
            flash("Nie znaleziono członka organizacji.", "error")
            return redirect(request.referrer or url_for("organizacje_view"))

        rel.status_czlonkostwa = "zawieszony"

        db.session.commit()

        flash("Członkostwo państwa zostało zawieszone.", "success")
        return redirect(request.referrer or url_for("organizacje_view"))
    
    @app.route("/dyplomacja/organizacja/<int:org_id>/member/<int:panstwo_id>/unsuspend", methods=["POST"])
    @wymaga_roli("wszechmocny")
    def organizacja_member_unsuspend(org_id, panstwo_id):

        rel = OrganizacjaPanstwo.query.filter_by(
            org_id=org_id,
            panstwo_id=panstwo_id
        ).first()

        if not rel:
            flash("Nie znaleziono członka organizacji.", "error")
            return redirect(request.referrer or url_for("organizacje_view"))

        rel.status_czlonkostwa = "czlonek"

        db.session.commit()

        flash("Zawieszenie zostało wycofane.", "success")
        return redirect(request.referrer or url_for("organizacje_view"))
    
    @app.route("/dyplomacja/organizacja/<int:org_id>/member/<int:panstwo_id>/rejoin", methods=["POST"])
    @wymaga_roli("wszechmocny")
    def organizacja_member_rejoin(org_id, panstwo_id):

        rel = OrganizacjaPanstwo.query.filter_by(
            org_id=org_id,
            panstwo_id=panstwo_id
        ).first()

        if not rel:
            flash("Nie znaleziono członka organizacji.", "error")
            return redirect(request.referrer or url_for("organizacje_view"))

        rel.status_czlonkostwa = "czlonek"

        db.session.commit()

        flash("Państwo ponownie dołączyło do organizacji.", "success")
        return redirect(request.referrer or url_for("organizacje_view"))
    

    
    

