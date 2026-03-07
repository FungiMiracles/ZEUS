from flask import render_template, request, redirect, url_for
from extensions import db
from models import Zdarzenie, Panstwo, Region, Miasto
from engine.generator import generate_events
from sqlalchemy import extract
from datetime import datetime


def init_zdarzenia_routes(app):

    # =====================================================
    # LISTA ZDARZEŃ + FILTROWANIE
    # =====================================================
    @app.route("/zdarzenia")
    def zdarzenia_list():

        region_id = request.args.get("region_id")
        panstwo_id = request.args.get("panstwo_id")
        typ = request.args.get("typ")
        data_od = request.args.get("data_od")
        data_do = request.args.get("data_do")

        # NAJPIERW TWORZYMY QUERY
        query = (
            db.session.query(Zdarzenie, Region, Panstwo)
            .outerjoin(Region, Zdarzenie.region_id == Region.region_id)
            .outerjoin(Panstwo, Region.panstwo_id == Panstwo.PANSTWO_ID)
        )

        # FILTRY
        if region_id and region_id.isdigit():
            query = query.filter(Zdarzenie.region_id == int(region_id))

        if panstwo_id and panstwo_id.isdigit():
            query = query.filter(Panstwo.PANSTWO_ID == int(panstwo_id))

        if typ:
            query = query.filter(Zdarzenie.zdarzenie_typ == typ)

        if data_od:
            data_od = datetime.fromisoformat(data_od)
            query = query.filter(Zdarzenie.data_entenda >= data_od)

        if data_do:
            data_do = datetime.fromisoformat(data_do) + timedelta(days=1)
            query = query.filter(Zdarzenie.data_entenda < data_do)

        zdarzenia = (
            query
            .order_by(Zdarzenie.data_entenda.asc())
            .limit(500)
            .all()
        )

        typy = [
            {"nazwa": "trzesienie_ziemi"},
            {"nazwa": "katastrofa_kolejowa"},
            {"nazwa": "katastrofa_w_ruchu_ladowym"}
        ]

        return render_template(
            "zdarzenia_list.html",
            zdarzenia=zdarzenia,
            typy=typy
        )

    # =====================================================
    # WYWOŁANIE GENERATORA ZDARZEŃ
    # =====================================================
    @app.route("/zdarzenia/generuj", methods=["POST"])
    def zdarzenia_generuj():

        generate_events()

        db.session.commit()

        return redirect(url_for("zdarzenia_list"))