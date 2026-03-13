from flask import (
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify
)
from extensions import db
from models import Panstwo, Stosunki, DictKontynent
from permissions import wymaga_roli
from sqlalchemy import or_


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

        relacje = [
            "sojusznicze",
            "partnerskie_strategiczne",
            "partnerskie",
            "przyjazne",
            "dobre",
            "neutralne",
            "chlodne",
            "zle",
            "napiete",
            "wrogie",
            "egzystencjalnie_wrogie"
        ]

        stany = [
            "pokoj",
            "zawieszenie_broni",
            "konflikt_dyplomatyczny",
            "wojna_handlowa",
            "wojna_informacyjna",
            "wojna_hybrydowa",
            "konflikt_kinetyczny_zamrozony",
            "wojna_kinetyczna",
            "okupacja"
        ]

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
                relacja="neutralne",
                stan="pokoj"
            )
            db.session.add(stosunek)
            db.session.flush()  # ← ważne, bez commit
            
        # ─────────────────────────────
        # POST
        # ─────────────────────────────
        if request.method == "POST":

            relacja = request.form.get("relacja")
            stan = request.form.get("stan")

            stosunek.relacja = relacja
            stosunek.stan = stan

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
            "relacja": stosunek.relacja,
            "stan": stosunek.stan
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
    
        kontynenty = (
            db.session.query(Panstwo.kontynent_id)
            .distinct()
            .order_by(DictKontynent.kontynent_nazwa)
            .all()
        )
    
        return render_template(
            "dyplomacja_sojusze.html",
            kontynenty=kontynenty
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
                "relacja": "neutralne",
                "stan": "pokoj"
            })
    
        # 🔑 KANONICZNY PORZĄDEK — ABSOLUTNIE KLUCZOWE
        a, b = sorted([p1, p2])
    
        rel = Stosunki.query.filter_by(
            PANSTWO_ID=a,
            PANSTWO_ID2=b
        ).first()
    
        if not rel:
            return jsonify({
                "relacja": "neutralne",
                "stan": "pokoj"
            })
    
        return jsonify({
            "relacja": rel.relacja,
            "stan": rel.stan
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

        q = Stosunki.query.filter(
            or_(
                Stosunki.PANSTWO_ID == panstwo_id,
                Stosunki.PANSTWO_ID2 == panstwo_id
            )
        )

        if relacja:
            q = q.filter(Stosunki.relacja == relacja)

        if stan:
            q = q.filter(Stosunki.stan == stan)

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
                "relacja": s.relacja,
                "stan": s.stan
            })

        return jsonify(wyniki)

