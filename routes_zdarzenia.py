from flask import render_template, request, redirect, url_for
from extensions import db
from models import Zdarzenie, Panstwo, Region, Miasto
from engine.generator import generate_events


def init_zdarzenia_routes(app):

    # =====================================================
    # LISTA ZDARZEŃ + FILTROWANIE
    # =====================================================
    @app.route("/zdarzenia")
    def zdarzenia_list():

        kontynent = request.args.get("kontynent")
        panstwo = request.args.get("panstwo")
        region = request.args.get("region")
        miesiac = request.args.get("miesiac")
        typ = request.args.get("typ")
        skala = request.args.get("skala")

        query = (
            db.session.query(Zdarzenie)
            .outerjoin(Panstwo, Zdarzenie.panstwo_id == Panstwo.PANSTWO_ID)
            .outerjoin(Region, Zdarzenie.region_id == Region.region_id)
        )

        if kontynent:
            query = query.filter(Panstwo.kontynent == kontynent)

        if panstwo:
            query = query.filter(Panstwo.panstwo_nazwa.ilike(f"%{panstwo}%"))

        if region:
            query = query.filter(Region.region_nazwa.ilike(f"%{region}%"))

        if miesiac:
            query = query.filter(db.func.month(Zdarzenie.data_entenda) == miesiac)

        if typ:
            query = query.filter(Zdarzenie.zdarzenie_typ == typ)

        if skala:
            query = query.filter(Zdarzenie.skala == skala)

        zdarzenia = query.order_by(Zdarzenie.data_entenda.desc()).limit(500).all()

        return render_template(
            "zdarzenia_list.html",
            zdarzenia=zdarzenia
        )

    # =====================================================
    # WYWOŁANIE GENERATORA ZDARZEŃ
    # =====================================================
    @app.route("/zdarzenia/generuj", methods=["POST"])
    def zdarzenia_generuj():

        generate_events()

        db.session.commit()

        return redirect(url_for("zdarzenia_list"))