from flask import render_template, request
from extensions import db
from models import Religia, ReligiaPerPanstwo, Panstwo


def init_religia_routes(app):

    # ------------------------------------------------------------
    # STRONA GŁÓWNA MODUŁU RELIGIJNEGO
    # ------------------------------------------------------------
    @app.route("/religia")
    def religia_home():
        return render_template("religia.html")

    def init_religia_routes(app):

    # ============================================================
    # LISTA RELIGII – FILTRY + WYNIKI
    # ============================================================
    @app.route("/religia/list", methods=["GET"])
    def religia_list():

        # --------- POBRANIE FILTRÓW ---------
        kontynent = request.args.get("kontynent")
        panstwo_id = request.args.get("panstwo")
        religia_id = request.args.get("religia")

        # --------- QUERY BAZOWE ---------
        query = (
            db.session.query(
                Religia.religia_id,
                Religia.religia_nazwa,
                Religia.religia_typ,
                Panstwo.panstwo_nazwa,
                Panstwo.kontynent
            )
            .join(ReligiaPerPanstwo, Religia.religia_id == ReligiaPerPanstwo.religia_id)
            .join(Panstwo, Panstwo.PANSTWO_ID == ReligiaPerPanstwo.panstwo_id)
        )

        # --------- FILTRY ---------
        if kontynent:
            query = query.filter(Panstwo.kontynent == kontynent)

        if panstwo_id:
            query = query.filter(Panstwo.PANSTWO_ID == panstwo_id)

        if religia_id:
            query = query.filter(Religia.religia_id == religia_id)

        # --------- WYNIKI ---------
        rows = query.order_by(Religia.religia_nazwa.asc()).all()

        results = [
            {
                "religia_id": r.religia_id,
                "religia_nazwa": r.religia_nazwa,
                "religia_typ": r.religia_typ,
                "panstwo_nazwa": r.panstwo_nazwa,
                "kontynent": r.kontynent,
            }
            for r in rows
        ]

        # --------- DANE DO SELECTÓW ---------
        kontynenty = (
            db.session.query(Panstwo.kontynent)
            .distinct()
            .order_by(Panstwo.kontynent)
            .all()
        )

        panstwa = (
            Panstwo.query
            .order_by(Panstwo.panstwo_nazwa)
            .all()
        )

        religie = (
            Religia.query
            .order_by(Religia.religia_nazwa)
            .all()
        )

        return render_template(
            "religia_list.html",
            results=results,
            kontynenty=[k[0] for k in kontynenty],
            panstwa=panstwa,
            religie=religie,
            selected_kontynent=kontynent,
            selected_panstwo=panstwo_id,
            selected_religia=religia_id,
        )

