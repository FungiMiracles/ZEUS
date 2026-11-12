from flask import render_template, session, abort, jsonify
from permissions import wymaga_roli

def init_mapy_routes(app):

    @app.get('/wiki/mapa/drogi.geojson')
    def wiki_world_roads():
        if not session.get('rola'):
            abort(403)
        from sqlalchemy import select
        from extensions import db
        from models import Panstwo
        from game.civic_models import Road
        rows = db.session.execute(select(Road, Panstwo.panstwo_nazwa)
            .join(Panstwo, Panstwo.PANSTWO_ID == Road.panstwo_id)
            .order_by(Road.id)).all()
        features = [dict(type='Feature', geometry=dict(type='LineString',
            coordinates=road.path or [[road.start_x, road.start_y], [road.end_x, road.end_y]]),
            properties=dict(id=road.id, kind=road.kind, country=name,
                distanceKm=str(road.distance_km))) for road, name in rows]
        response = jsonify(type='FeatureCollection', features=features)
        response.headers['Cache-Control'] = 'private, no-store'
        return response

    # Strona z kafelkami map
    @app.route("/mapy")
    def mapy():
        return render_template("mapy.html")
    
    @app.route("/mapy/kao")
    def mapy_kao():
        return render_template("mapy_kao.html")
    
    @app.route("/mapy/beifa")
    def mapy_beifa():
        return render_template("mapy_beifa.html")
    
    @app.route("/mapy/anzinia")
    def mapy_anzinia():
        return render_template("mapy_anzinia.html")
    
    @app.route("/mapy/peryfa")
    def mapy_peryfa():
        return render_template("mapy_peryfa.html")
    
    @app.route("/mapy/wyspy_wieksze")
    def mapy_wyspy_wieksze():
        return render_template("mapy_wieksze.html")

    @app.route("/mapy/wyspy_mniejsze")
    def mapy_wyspy_mniejsze():
        return render_template("mapy_mniejsze.html")
    
    @app.route("/mapy_swiata")
    def mapy_swiata():
        from extensions import db
        from game.military_flights import calibration
        return render_template(
            "mapy_swiata.html",
            km_per_unit=calibration(db.session).km_per_unit,
        )
