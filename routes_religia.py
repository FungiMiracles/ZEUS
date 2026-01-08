from flask import render_template, request, jsonify
from extensions import db
from models import Religia, ReligiaPerPanstwo, Panstwo


def init_religia_routes(app):

    # ============================================================
    # STRONA GŁÓWNA MODUŁU RELIGII
    # ============================================================
    @app.route("/religia")
    def religia_home():
        return render_template("religia.html")

    # ============================================================
    # LISTA RELIGII
    # ============================================================
    @app.route("/religia/list", methods=["GET"])
    def religia_list():

        kontynent = request.args.get("kontynent")
        panstwo_id = request.args.get("panstwo")
        religia_id = request.args.get("religia")

        query = (
            db.session.query(
                Religia.religia_id,
                Religia.religia_nazwa,
                Religia.religia_typ,
                Panstwo.panstwo_nazwa,
                Panstwo.kontynent
            )
            .join(ReligiaPerPanstwo,
                  Religia.religia_id == ReligiaPerPanstwo.religia_id)
            .join(Panstwo,
                  Panstwo.PANSTWO_ID == ReligiaPerPanstwo.panstwo_id)
        )

        if kontynent:
            query = query.filter(Panstwo.kontynent == kontynent)

        if panstwo_id:
            query = query.filter(Panstwo.PANSTWO_ID == panstwo_id)

        if religia_id:
            query = query.filter(Religia.religia_id == religia_id)

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

        kontynenty = (
            db.session.query(Panstwo.kontynent)
            .distinct()
            .order_by(Panstwo.kontynent)
            .all()
        )

        return render_template(
            "religia_list.html",
            results=results,
            kontynenty=[k[0] for k in kontynenty],
        )

    # ============================================================
    # API: PAŃSTWA WG KONTYNENTU
    # ============================================================
    @app.route("/api/religia/panstwa")
    def api_religia_panstwa():
        kontynent = request.args.get("kontynent")

        query = Panstwo.query
        if kontynent:
            query = query.filter(Panstwo.kontynent == kontynent)

        panstwa = query.order_by(Panstwo.panstwo_nazwa).all()

        return jsonify([
            {"id": p.PANSTWO_ID, "nazwa": p.panstwo_nazwa}
            for p in panstwa
        ])

    # ============================================================
    # API: RELIGIE WG PAŃSTWA
    # ============================================================
    @app.route("/api/religia/religie")
    def api_religia_religie():
        panstwo_id = request.args.get("panstwo_id")

        query = (
            db.session.query(
                Religia.religia_id,
                Religia.religia_nazwa
            )
            .join(ReligiaPerPanstwo,
                  Religia.religia_id == ReligiaPerPanstwo.religia_id)
        )

        if panstwo_id:
            query = query.filter(ReligiaPerPanstwo.panstwo_id == panstwo_id)

        religie = (
            query
            .distinct()
            .order_by(Religia.religia_nazwa)
            .all()
        )

        return jsonify([
            {"id": r.religia_id, "nazwa": r.religia_nazwa}
            for r in religie
        ])
