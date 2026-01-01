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


def init_dyplomacja_routes(app):

    # ============================================================
    # LISTA STOSUNKÓW
    # ============================================================
    @app.route("/dyplomacja")
    def dyplomacja_list():
        stosunki = (
            Stosunki.query
            .join(Panstwo, Stosunki.PANSTWO_ID == Panstwo.PANSTWO_ID)
            .order_by(Stosunki.PANSTWO_ID, Stosunki.PANSTWO_ID2)
            .all()
        )

        return render_template(
            "dyplomacja_list.html",
            stosunki=stosunki
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
