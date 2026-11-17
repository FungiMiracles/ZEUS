from flask import (
    jsonify,
    request
)

from extensions import db

from engine.clock import get_current_entenda_date

from models import (
    Przywodztwo,
    Panstwo,
    DictPrzywodcaTyp
)

from engine.leadership import (
    get_expired_leaders
)

from datetime import timedelta
from dateutil.relativedelta import relativedelta
from datetime import datetime

def init_przywodcy_routes(app):

    @app.route(
        "/api/przywodcy/do_uzupelnienia",
        methods=["GET"]
    )
    def przywodcy_do_uzupelnienia():

        # 16 Nov 2026: moduł cyklicznego wpisywania przywódców wyłączony na UAT i PREPROD.
        from flask import current_app
        if not current_app.config.get("LEADERSHIP_PROMPT_ENABLED", True):
            return jsonify([])
        data = get_expired_leaders()
        return jsonify(data)
    
    @app.route(
    "/api/przywodcy/historia/<int:panstwo_id>",
    methods=["GET"]
    )
    def historia_przywodcow(panstwo_id):

        historia = (
            Przywodztwo.query
            .filter_by(
                panstwo_id=panstwo_id
            )
            .order_by(
                Przywodztwo.data_entenda_od.asc()
            )
            .all()
        )

        wynik = []

        for leader in historia:

            wynik.append({

                "typ": leader.typ.przywodca_typ,

                "imie": leader.przywodca_imie,

                "nazwisko": leader.przywodca_nazwisko,

                "data_od": leader.data_entenda_od.isoformat(),

                "data_do": leader.data_entenda_do.isoformat()

            })

        return jsonify(wynik)
    
    @app.route(
        "/api/przywodcy/dodaj",
        methods=["POST"]
    )
    def dodaj_przywodce():

        body = request.get_json()

        if body is None:
            return jsonify({
                "success": False,
                "message": "Brak danych."
            }), 400

        panstwo_id = body["panstwo_id"]
        imie = body["imie"]
        nazwisko = body["nazwisko"]
        typ = body["typ"]

        typ_obj = db.session.get(DictPrzywodcaTyp, typ)

        if typ_obj is None:
            return jsonify({
                "success": False,
                "message": "Niepoprawny typ przywódcy."
            }), 400

        previous = (
            Przywodztwo.query
            .filter_by(
                panstwo_id=panstwo_id
            )
            .order_by(
                Przywodztwo.data_entenda_do.desc()
            )
            .first()
        )

        if previous is None:

            if "data_od" not in body:
                return jsonify({
                    "success": False,
                    "message": "Brak daty rozpoczęcia kadencji."
                }), 400

            start = datetime.strptime(
                body["data_od"],
                "%Y-%m-%d"
            ).date()

        else:

            start = previous.data_entenda_do + timedelta(days=1)

        panstwo = db.session.get(Panstwo, panstwo_id)

        if panstwo is None:
            return jsonify({
                "success": False,
                "message": "Państwo nie istnieje."
            }), 404

        if panstwo.kadencja_przywodcy is not None:
            end = (
                start
                + relativedelta(
                    years=panstwo.kadencja_przywodcy
                )
                - timedelta(days=1)
            )
        else:
            end = datetime.strptime(
                body["data_do"],
                "%Y-%m-%d"
            ).date()

        leader = Przywodztwo(
            panstwo_id=panstwo_id,
            przywodca_imie=imie,
            przywodca_nazwisko=nazwisko,
            przywodca_typ_id=typ,
            data_entenda_od=start,
            data_entenda_do=end
        )

        try:
            db.session.add(leader)
            db.session.commit()

        except Exception as e:
            db.session.rollback()

            return jsonify({
                "success": False,
                "message": str(e)
            }), 500

        return jsonify({
            "success": True,
            "przywodca_id": leader.przywodca_id,
            "panstwo_id": panstwo_id,
            "data_od": leader.data_entenda_od.isoformat(),
            "data_do": leader.data_entenda_do.isoformat()
        })