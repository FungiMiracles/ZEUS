# routes_api.py
from flask import jsonify, request
from extensions import db
from models import Panstwo, Region



def init_api_routes(app):

    @app.route("/api/panstwa_by_kontynent")
    def api_panstwa_by_kontynent():
        kontynent = request.args.get("kontynent")

        if not kontynent:
            return jsonify([])

        panstwa = (
            db.session.query(Panstwo.PANSTWO_ID, Panstwo.panstwo_nazwa)
            .filter(Panstwo.kontynent == kontynent)
            .order_by(Panstwo.panstwo_nazwa)
            .all()
        )

        return jsonify([
            {"id": p.PANSTWO_ID, "nazwa": p.panstwo_nazwa}
            for p in panstwa
        ])

    @app.route("/api/regiony_by_panstwo")
    def api_regiony_by_panstwo():
        panstwo_id = request.args.get("panstwo_id")
        if not panstwo_id or not panstwo_id.isdigit():
            return jsonify([])

        regiony = (
            Region.query
            .filter_by(panstwo_id=int(panstwo_id))
            .order_by(Region.region_nazwa)
            .all()
        )

        return jsonify([
            {"region_id": r.region_id, "region_nazwa": r.region_nazwa}
            for r in regiony
        ])