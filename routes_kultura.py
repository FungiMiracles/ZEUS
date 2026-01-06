from flask import render_template, request, jsonify
from extensions import db
from models import Panstwo, Jezyk

def init_kultura_routes(app):

    # ===============================
    # MODUŁ KULTURY – STRONA GŁÓWNA
    # ===============================

    @app.route("/kultura")
    def kultura_home():
        return render_template("kultura.html")

    # ===============================
    # MODUŁ KULTURY – JĘZYKI
    # ===============================

    @app.route("/kultura/jezyki")
    def kultura_jezyki():
        return render_template("kultura_jezyki.html")

    # ===============================
    # API – PAŃSTWA PO KONTYNENCIE
    # ===============================

    @app.route("/api/kultura/panstwa_by_kontynent")
    def api_kultura_panstwa_by_kontynent():
        kontynent = request.args.get("kontynent")
    
        if not kontynent:
            return jsonify([])
    
        panstwa = (
            Panstwo.query
            .filter(Panstwo.kontynent == kontynent)
            .order_by(Panstwo.panstwo_nazwa.asc())
            .all()
        )
    
        return jsonify([
            {"id": p.PANSTWO_ID, "nazwa": p.panstwo_nazwa}
            for p in panstwa
        ])

    from models import Jezyk


    @app.route("/api/kultura/jezyki")
    def api_kultura_jezyki():
        jezyki = (
            Jezyk.query
            .order_by(Jezyk.jezyk_nazwa.asc())
            .all()
        )
    
        return jsonify([
            {
                "id": j.jezyk_id,
                "nazwa": j.jezyk_nazwa
            }
            for j in jezyki
        ])


