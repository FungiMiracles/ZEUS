from flask import render_template, request, redirect, url_for
from extensions import db
from models import Zdarzenie, Panstwo, Region, Miasto
from engine.generator import generate_events
from sqlalchemy import extract


def init_zdarzenia_routes(app):

    # =====================================================
    # LISTA ZDARZEŃ + FILTROWANIE
    # =====================================================
    @app.route("/zdarzenia")
    def zdarzenia_list():

        kontynent = request.args.get("kontynent")
        panstwo_id = request.args.get("panstwo_id")
        region = request.args.get("region")
        miesiac = request.args.get("miesiac")
        typ = request.args.get("typ")
        skala = request.args.get("skala")

        query = (
            db.session.query(Zdarzenie, Region, Panstwo)
            .join(Region, Zdarzenie.region_id == Region.region_id)
            .join(Panstwo, Region.panstwo_id == Panstwo.PANSTWO_ID)
        )

        if kontynent:
            query = query.filter(Panstwo.kontynent == kontynent)

        if panstwo_id:
            query = query.filter(Panstwo.PANSTWO_ID == panstwo_id)

        if region:
            query = query.filter(Region.region_nazwa.ilike(f"%{region}%"))

        if miesiac:
            query = query.filter(extract("month", Zdarzenie.data_entenda) == int(miesiac))

        if typ:
            query = query.filter(Zdarzenie.zdarzenie_typ == typ)

        if skala and skala.isdigit():
            query = query.filter(Zdarzenie.skala == int(skala))

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