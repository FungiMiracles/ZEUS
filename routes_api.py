from flask import request, jsonify
from extensions import db
from models import Panstwo, Region, Miasto, DictKontynent




def init_api_routes(app):

    @app.route("/api/panstwa_by_kontynent")
    def api_panstwa_by_kontynent():

        kontynent_id = request.args.get("kontynent_id", type=int)

        if not kontynent_id:
            return jsonify([])

        panstwa = (
            db.session.query(Panstwo.PANSTWO_ID, Panstwo.panstwo_nazwa)
            .filter(Panstwo.kontynent_id == kontynent_id)
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
            DictKontynent.query
            .order_by(DictKontynent.kontynent_nazwa)
            .all()
        )

        return jsonify([
            {
                "id": k.kontynent_id,
                "nazwa": k.kontynent_nazwa
            }
            for k in rows
        ])
    
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

    