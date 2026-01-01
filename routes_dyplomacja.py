from flask import (
    render_template,
    request,
    redirect,
    url_for,
    flash
)
from extensions import db
from models import Panstwo, Stosunki
from permissions import wymaga_roli
from flask import jsonify


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
    @app.route("/dyplomacja/edit", methods=["GET", "POST"])
    @wymaga_roli("wszechmocny")
    def dyplomacja_edit():

        panstwa = Panstwo.query.order_by(Panstwo.panstwo_nazwa).all()

        if request.method == "POST":
            p1 = request.form.get("panstwo_id")
            p2 = request.form.get("panstwo_id2")
            relacja = request.form.get("relacja")
            stan = request.form.get("stan")

            # ───── WALIDACJA ─────
            if not p1 or not p2:
                flash("Musisz wybrać dwa państwa.", "error")
                return redirect(url_for("dyplomacja_edit"))

            if p1 == p2:
                flash("Państwo nie może mieć relacji samo ze sobą.", "error")
                return redirect(url_for("dyplomacja_edit"))

            p1 = int(p1)
            p2 = int(p2)

            # porządek kanoniczny (A < B)
            a, b = sorted([p1, p2])

            # ───── SPRAWDŹ CZY ISTNIEJE ─────
            stosunek = Stosunki.query.filter_by(
                PANSTWO_ID=a,
                PANSTWO_ID2=b
            ).first()

            if not stosunek:
                stosunek = Stosunki(
                    PANSTWO_ID=a,
                    PANSTWO_ID2=b
                )
                db.session.add(stosunek)

            stosunek.relacja = relacja
            stosunek.stan = stan

            try:
                db.session.commit()
                flash("Stosunki dyplomatyczne zapisane.", "success")
            except Exception as e:
                db.session.rollback()
                flash(f"Błąd zapisu: {e}", "error")

            return redirect(url_for("dyplomacja_list"))

        return render_template(
            "dyplomacja_edit.html",
            panstwa=panstwa,
            relacje=[
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
            ],
            stany=[
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
        )

    @app.route("/dyplomacja/sojusze")
    def dyplomacja_sojusze():
    
        kontynenty = (
            db.session.query(Panstwo.kontynent)
            .distinct()
            .order_by(Panstwo.kontynent)
            .all()
        )
    
        kontynenty = [k[0] for k in kontynenty if k[0]]
    
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
            db.session.query(Panstwo.kontynent)
            .distinct()
            .order_by(Panstwo.kontynent)
            .all()
        )
    
        return jsonify([k[0] for k in kontynenty if k[0]])

    @app.route("/api/dyplomacja/sojusze")
    def api_dyplomacja_sojusze():
    
        panstwo_id = request.args.get("panstwo_id", type=int)
        relacja_f = request.args.get("relacja")
        stan_f = request.args.get("stan")
    
        if not panstwo_id:
            return jsonify([])
    
        # wszystkie relacje, gdzie państwo bierze udział
        stosunki = Stosunki.query.filter(
            (Stosunki.PANSTWO_ID == panstwo_id) |
            (Stosunki.PANSTWO_ID2 == panstwo_id)
        ).all()
    
        wynik = []
    
        for s in stosunki:
    
            # ustalamy "drugie państwo"
            other_id = (
                s.PANSTWO_ID2 if s.PANSTWO_ID == panstwo_id
                else s.PANSTWO_ID
            )
    
            panstwo = Panstwo.query.get(other_id)
            if not panstwo:
                continue
    
            # ─── FILTRY (opcjonalne!) ───
            if relacja_f and s.relacja != relacja_f:
                continue
    
            if stan_f and s.stan != stan_f:
                continue
    
            wynik.append({
                "panstwo": panstwo.panstwo_nazwa,
                "relacja": s.relacja,
                "stan": s.stan
            })
    
        return jsonify(wynik)

    @app.route("/api/dyplomacja/panstwa")
    def api_dyplomacja_panstwa():
        kontynent = request.args.get("kontynent")
    
        if not kontynent:
            return jsonify([])
    
        panstwa = (
            Panstwo.query
            .filter(Panstwo.kontynent == kontynent)
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

