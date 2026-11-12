from flask import render_template, request, redirect, url_for, flash
from permissions import wymaga_roli
from routes_resources_admin import init_resources_admin_routes
from extensions import db
from flask import jsonify
from models import Region
from sqlalchemy.orm import joinedload

from models import (
    Panstwo,
    Region,
    DictZdarzeniaSystemowe,
    ZdarzeniaSystemowe
)

def init_admin_routes(app):
    init_resources_admin_routes(app)
    from routes_civic_admin import wiki_civic_bp
    app.register_blueprint(wiki_civic_bp)

    @app.route("/admin_panel_form")
    @wymaga_roli("wszechmocny")
    def admin_panel():

        panstwa = (
            Panstwo.query
            .order_by(Panstwo.panstwo_nazwa)
            .all()
        )

        logi_systemowe = (
            ZdarzeniaSystemowe.query
            .options(
                joinedload(ZdarzeniaSystemowe.zdarzenie)
            )
            .order_by(
                ZdarzeniaSystemowe.data_rzeczywista.desc()
            )
            .all()
        )

        return render_template(
            "admin_panel_form.html",
            panstwa=panstwa,
            logi_systemowe=logi_systemowe
        )

