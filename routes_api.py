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

    