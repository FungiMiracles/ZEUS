from flask import render_template, request, redirect, url_for
from extensions import db
from models import Panstwo, Region, Miasto
from sqlalchemy import func


def init_demografia_routes(app):

    # --------------------------------
    # KALKULATOR DEMOGRAFICZNY – START
    # --------------------------------
    @app.route("/demografia/kalkulator", methods=["GET", "POST"])
    def demografia_kalkulator_start():

        kontynent = request.form.get("kontynent")
        panstwo_id = request.form.get("panstwo_id")

        kontynenty = (
            db.session.query(Panstwo.kontynent)
            .distinct()
            .all()
        )
        kontynenty = [k[0] for k in kontynenty if k[0]]

        panstwa = []
        if kontynent:
            panstwa = Panstwo.query.filter_by(kontynent=kontynent).order_by(
                Panstwo.panstwo_nazwa
            ).all()

        if request.method == "POST" and panstwo_id:
            return redirect(url_for(
                "demografia_kalkulator_panstwo",
                panstwo_id=panstwo_id
            ))

        return render_template(
            "demografia_kalkulator.html",
            kontynenty=kontynenty,
            panstwa=panstwa,
            selected_kontynent=kontynent
        )

    # --------------------------------
    # KALKULATOR – WIDOK PAŃSTWA
    # --------------------------------
    @app.route("/demografia/kalkulator/<int:panstwo_id>")
    def demografia_kalkulator_panstwo(panstwo_id):

        panstwo = Panstwo.query.get_or_404(panstwo_id)

        regiony = (
            db.session.query(
                Region.region_id,
                Region.region_nazwa,
                func.coalesce(func.sum(Miasto.miasto_populacja), 0).label("ludnosc_miejska")
            )
            .outerjoin(Miasto, Miasto.region_id == Region.region_id)
            .filter(Region.panstwo_id == panstwo_id)
            .group_by(Region.region_id)
            .order_by(Region.region_nazwa)
            .all()
        )

        return render_template(
            "demografia_kalkulator.html",
            panstwo=panstwo,
            regiony=regiony
        )
