from flask import request, jsonify
from extensions import db
from models import Panstwo, Region, Miasto



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
    
    @app.route("/api/kontynenty")
    def api_kontynenty():
        rows = (
            db.session.query(Panstwo.kontynent)
            .distinct()
            .order_by(Panstwo.kontynent)
            .all()
        )

        return jsonify([k[0] for k in rows if k[0]])
    
    @app.route("/api/miasta_by_region")
    def api_miasta_by_region():
        region_id = request.args.get("region_id", type=int)

        if not region_id:
            return jsonify([])

        miasta = (
            Miasto.query
            .filter(Miasto.region_id == region_id)
            .order_by(Miasto.miasto_nazwa)
            .all()
        )

        return jsonify([
            {
                "miasto_id": m.miasto_id,
                "miasto_nazwa": m.miasto_nazwa
            }
            for m in miasta
        ])

    