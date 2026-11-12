from flask import (
    render_template,
    jsonify,
    request
)

from extensions import db

from models import (
    DictKontynent,
    Panstwo,
    Region,
    HistoriaPopulacjiPanstw,
    RocznyPrzyrostStateHistory,
    PKBStateHistory,
    PKBPCStateHistory,
    RegionStateHistory,
    Spoleczenstwo,
    ProcentWzrostuStateHistory
)

from permissions import wymaga_roli

def init_wykresy_routes(app):

# ==========================================================
# WYKRESY
# ==========================================================

    @app.route("/wykresy")
    def wykresy():

        kontynenty = (
            DictKontynent.query
            .order_by(DictKontynent.kontynent_nazwa)
            .all()
        )

        return render_template(
            "wykresy.html",
            kontynenty=kontynenty
        )

# ==========================================================
# API
# ==========================================================

    @app.route("/api/wykresy/panstwa")
    def api_wykresy_panstwa():

        scope = request.args.get("kontynent_id", "")
        kontynent_id = request.args.get("kontynent_id", type=int)
        if scope != "all" and (kontynent_id is None or kontynent_id <= 0):
            return jsonify({"success": False, "message": "Wybierz kontynent lub cały świat."}), 400

        query = db.session.query(
            Panstwo.PANSTWO_ID, Panstwo.panstwo_nazwa, Panstwo.panstwo_kod,
        ).filter(Panstwo.czy_suwerenny == "TAK")
        if scope != "all":
            query = query.filter(Panstwo.kontynent_id == kontynent_id)
        panstwa = query.order_by(Panstwo.panstwo_nazwa, Panstwo.PANSTWO_ID).all()

        wynik = []

        for panstwo in panstwa:

            wynik.append({
                "id": panstwo.PANSTWO_ID,
                "nazwa": panstwo.panstwo_nazwa,
                "kod": panstwo.panstwo_kod
            })

        return jsonify({
            "success": True,
            "panstwa": wynik
        })

    @app.route("/api/wykresy/chart")
    def api_wykresy_chart():

        panstwo_id = request.args.get(
            "panstwo_id",
            type=int
        )

        typ = request.args.get(
            "typ",
            type=str
        )

        global_scope = request.args.get("scope") == "world"
        if not panstwo_id and not global_scope:

            return jsonify({
                "success": False,
                "message": "Nie podano państwa."
            }), 400

        if typ not in (
            "populacja",
            "przyrost_ludnosci",
            "wzrost_pkb",
            "pkb",
            "pkbpc",
            "infrastruktura"
        ):

            return jsonify({
                "success": False,
                "message": "Nieprawidłowy typ wykresu."
            }), 400

        if global_scope:
            from services.world_charts import world_chart
            return jsonify(world_chart(db.session, typ))

        if db.session.query(Panstwo.PANSTWO_ID).filter(Panstwo.PANSTWO_ID == panstwo_id).first() is None:
            return jsonify({'success': False, 'message': 'Nie znaleziono państwa.'}), 404

        if typ == "populacja":

            return jsonify(
                _chart_populacja(
                    panstwo_id
                )
            )
        
        if typ == "przyrost_ludnosci":
            return jsonify(_chart_przyrost_ludnosci(panstwo_id))

        if typ == 'wzrost_pkb':
            rows = db.session.query(ProcentWzrostuStateHistory.data_entenda,
                ProcentWzrostuStateHistory.new_wzrost).filter(
                    ProcentWzrostuStateHistory.panstwo_id == panstwo_id).order_by(
                    ProcentWzrostuStateHistory.data_entenda, ProcentWzrostuStateHistory.id).all()
            by_year = {row.data_entenda.year: float(row.new_wzrost) if row.new_wzrost is not None else None for row in rows}
            years = list(range(min([2995, *by_year]), max([3035, *by_year]) + 1))
            return jsonify(success=True, title='Roczny procent wzrostu PKB', unit='gdp_growth_pct',
                labels=years, values=[by_year.get(year) for year in years],
                description='Ostatni zapis współczynnika wzrostu PKB w danym roku Entendy, także po kryzysie. Lata bez danych pozostają puste.')

        if typ == "pkb":

            return jsonify(
                _chart_pkb(
                    panstwo_id
                )
            )
        
        if typ == "pkbpc":

            return jsonify(
                _chart_pkbpc(
                    panstwo_id
                )
            )
        
        if typ == "infrastruktura":

            return jsonify(
                _chart_infrastruktura(
                    panstwo_id
                )
            )

        return jsonify({
            "success": False,
            "message": "Ten typ wykresu nie został jeszcze zaimplementowany."
        })

    @app.route("/api/wykresy/ranking")
    def api_wykresy_ranking():

        typ = request.args.get("typ", "populacja")
        sort = request.args.get("sort", "DESC").upper()

        if typ == "populacja":
            return jsonify(_ranking_populacja(sort))

        elif typ == "pkb":
            return jsonify(_ranking_pkb(sort))

        elif typ == "powierzchnia":
            return jsonify(_ranking_powierzchnia(sort))

        elif typ == "infrastruktura":
            return jsonify(_ranking_infrastruktura(sort))
        
        elif typ == "pkbpc":
            return jsonify(_ranking_pkbpc(sort))

        elif typ == "edukacja":
            return jsonify(_ranking_spoleczenstwo(sort, "poziom_edukacji"))

        elif typ == "zdrowie":
            return jsonify(_ranking_spoleczenstwo(sort, "zdrowie_publiczne"))

        elif typ == "przestepczosc":
            return jsonify(_ranking_spoleczenstwo(sort, "przestepczosc"))

        elif typ == "stabilnosc":
            return jsonify(_ranking_spoleczenstwo(sort, "stabilnosc_spoleczna"))

        return jsonify({
            "success": False,
            "message": "Nieobsługiwany typ rankingu."
        })

    # ==========================================================
    # POPULACJA
    # ==========================================================

    def _chart_przyrost_ludnosci(panstwo_id):
        history = (
            db.session.query(
                RocznyPrzyrostStateHistory.data_entenda,
                RocznyPrzyrostStateHistory.new_roczny_przyrost,
            )
            .filter(RocznyPrzyrostStateHistory.panstwo_id == panstwo_id)
            .order_by(RocznyPrzyrostStateHistory.data_entenda, RocznyPrzyrostStateHistory.id)
            .all()
        )
        by_year = {row.data_entenda.year: row.new_roczny_przyrost for row in history}
        first_year = min([2995, *by_year])
        last_year = max([3035, *by_year])
        years = list(range(first_year, last_year + 1))
        return {
            "success": True,
            "title": "Roczny procent zmiany ludności",
            "unit": "population_growth_pct",
            "labels": years,
            "values": [by_year.get(year) for year in years],
        }

    def _chart_populacja(panstwo_id):

        rekordy = (
            HistoriaPopulacjiPanstw.query
            .filter(
                HistoriaPopulacjiPanstw.panstwo_id == panstwo_id
            )
            .order_by(
                HistoriaPopulacjiPanstw.data_entenda
            )
            .all()
        )

        lata = list(range(2995, 3036))

        mapa = {}

        for r in rekordy:

            mapa[r.data_entenda.year] = (
                r.panstwo_populacja
            )

        labels = []
        values = []

        for rok in lata:

            labels.append(rok)

            values.append(
                mapa.get(rok)
            )

        return {

            "success": True,

            "title": "Zmiana populacji",

            "unit": "population",

            "labels": labels,

            "values": values
        }

# ==========================================================
# PKB
# ==========================================================

    def _chart_pkb(panstwo_id):

        rekordy = (
            PKBStateHistory.query
            .filter(
                PKBStateHistory.panstwo_id == panstwo_id
            )
            .order_by(
                PKBStateHistory.data_entenda
            )
            .all()
        )

        lata = list(range(2995, 3036))

        mapa = {}

        for r in rekordy:

            mapa[r.data_entenda.year] = r.new_pkb

        labels = []
        values = []

        for rok in lata:

            labels.append(rok)
            values.append(
                mapa.get(rok)
            )

        return {

            "success": True,

            "title": "Zmiana PKB",

            "unit": "pkb",

            "labels": labels,

            "values": values

        }
    
    def _chart_pkbpc(panstwo_id):

        rekordy = (
            PKBPCStateHistory.query
            .filter(
                PKBPCStateHistory.panstwo_id == panstwo_id
            )
            .order_by(
                PKBPCStateHistory.data_entenda
            )
            .all()
        )

        lata = list(range(2995, 3036))

        mapa = {}

        for r in rekordy:
            mapa[r.data_entenda.year] = r.new_pkbpc

        labels = []
        values = []

        for rok in lata:
            labels.append(rok)
            values.append(
                mapa.get(rok)
            )

        return {

            "success": True,

            "title": "PKB per capita",

            "unit": "pkbpc",

            "labels": labels,

            "values": values

        }

    def _chart_infrastruktura(panstwo_id):

        lata = list(range(2995, 3036))

        labels = []
        values = []

        regiony = Region.query.filter_by(
            panstwo_id=panstwo_id
        ).all()

        region_ids = [r.region_id for r in regiony]

        for rok in lata:

            labels.append(rok)

            rekordy = (
                RegionStateHistory.query
                .filter(
                    RegionStateHistory.region_id.in_(region_ids),
                    db.extract("year", RegionStateHistory.data_entenda) == rok,
                    db.extract("month", RegionStateHistory.data_entenda) == 12,
                    db.extract("day", RegionStateHistory.data_entenda) == 31,
                )
                .all()
            )

            if not rekordy:
                values.append(None)
                continue

            infra_sum = 0
            infra_count = 0

            for r in rekordy:

                if r.old_kolej is not None:
                    infra_sum += r.old_kolej
                    infra_count += 1

                if r.old_drogi is not None:
                    infra_sum += r.old_drogi
                    infra_count += 1

                if r.old_energia is not None:
                    infra_sum += r.old_energia
                    infra_count += 1

                if r.old_mieszkania is not None:
                    infra_sum += r.old_mieszkania
                    infra_count += 1

                region = next(
                    (reg for reg in regiony if reg.region_id == r.region_id),
                    None
                )

                if (
                    region
                    and region.region_polozenie_id
                    and region.region_polozenie_id != 1
                ):
                    if r.old_porty is not None:
                        infra_sum += r.old_porty
                        infra_count += 1

            values.append(
                round(infra_sum / infra_count, 1)
                if infra_count > 0
                else None
            )

        return {

            "success": True,

            "title": "Poziom infrastruktury",

            "unit": "infra",

            "labels": labels,

            "values": values

        }

    def _ranking_populacja(sort):

        query = Panstwo.query.filter(
            Panstwo.czy_suwerenny == "TAK"
        )

        if sort == "ASC":

            query = query.order_by(
                Panstwo.panstwo_populacja.asc()
            )

        else:

            query = query.order_by(
                Panstwo.panstwo_populacja.desc()
            )

        wynik = []

        for lp, panstwo in enumerate(query.all(), start=1):

            wynik.append({

                "lp": lp,

                "id": panstwo.PANSTWO_ID,

                "nazwa": panstwo.panstwo_nazwa,

                "kod": panstwo.panstwo_kod,

                "wartosc": panstwo.panstwo_populacja

            })

        return {

            "success": True,

            "ranking": wynik

        }

    def _ranking_powierzchnia(sort):
        area = Panstwo.panstwo_powierzchnia
        query = db.session.query(
            Panstwo.PANSTWO_ID, Panstwo.panstwo_nazwa, Panstwo.panstwo_kod, area,
        ).filter(Panstwo.czy_suwerenny == "TAK").order_by(
            area.is_(None),
            area.asc() if sort == "ASC" else area.desc(),
            Panstwo.panstwo_nazwa.asc(),
            Panstwo.PANSTWO_ID.asc(),
        )
        return {
            "success": True,
            "ranking": [
                {"lp": lp, "id": country.PANSTWO_ID,
                 "nazwa": country.panstwo_nazwa, "kod": country.panstwo_kod,
                 "wartosc": country.panstwo_powierzchnia}
                for lp, country in enumerate(query.all(), start=1)
            ],
        }

    def _ranking_pkb(sort):

        query = Panstwo.query.filter(
            Panstwo.czy_suwerenny == "TAK"
        )

        if sort == "ASC":
            query = query.order_by(Panstwo.panstwo_PKB.asc())
        else:
            query = query.order_by(Panstwo.panstwo_PKB.desc())

        ranking = []

        for lp, panstwo in enumerate(query.all(), start=1):

            ranking.append({
                "lp": lp,
                "id": panstwo.PANSTWO_ID,
                "nazwa": panstwo.panstwo_nazwa,
                "kod": panstwo.panstwo_kod,
                "wartosc": panstwo.panstwo_PKB
            })

        return {
            "success": True,
            "ranking": ranking
        }
    
    def _ranking_infrastruktura(sort):

        ranking = []

        panstwa = (
            Panstwo.query
            .filter(Panstwo.czy_suwerenny == "TAK")
            .all()
        )

        for panstwo in panstwa:

            regiony = Region.query.filter_by(
                panstwo_id=panstwo.PANSTWO_ID
            ).all()

            if not regiony:
                srednia = None

            else:

                infra_sum = 0
                infra_count = 0

                for region in regiony:

                    if region.region_stan_infra_kolejowej is not None:
                        infra_sum += region.region_stan_infra_kolejowej
                        infra_count += 1

                    if region.region_stan_infra_drogowej is not None:
                        infra_sum += region.region_stan_infra_drogowej
                        infra_count += 1

                    if region.region_stan_infra_energetycznej is not None:
                        infra_sum += region.region_stan_infra_energetycznej
                        infra_count += 1

                    if region.region_stan_infra_mieszkalnej is not None:
                        infra_sum += region.region_stan_infra_mieszkalnej
                        infra_count += 1

                    if (
                        region.region_polozenie_id
                        and region.region_polozenie_id != 1
                    ):
                        if region.region_stan_infra_portowej is not None:
                            infra_sum += region.region_stan_infra_portowej
                            infra_count += 1

                srednia = (
                    round(infra_sum / infra_count, 1)
                    if infra_count > 0
                    else None
                )

            ranking.append({
                "id": panstwo.PANSTWO_ID,
                "nazwa": panstwo.panstwo_nazwa,
                "kod": panstwo.panstwo_kod,
                "wartosc": srednia
            })

        if sort == "DESC":

            ranking.sort(
                key=lambda x: x["wartosc"] if x["wartosc"] is not None else -1,
                reverse=True
            )

            ranking = (
                [r for r in ranking if r["wartosc"] not in (0, 0.0)]
                + [r for r in ranking if r["wartosc"] in (0, 0.0)]
            )

        else:

            ranking.sort(
                key=lambda x: x["wartosc"] if x["wartosc"] is not None else float("inf")
            )

        for lp, row in enumerate(ranking, start=1):
            row["lp"] = lp

        return {
            "success": True,
            "ranking": ranking
        }

    def _ranking_pkbpc(sort):

        ranking = []

        panstwa = (
            Panstwo.query
            .filter(Panstwo.czy_suwerenny == "TAK")
            .all()
        )

        for panstwo in panstwa:

            if (
                panstwo.panstwo_populacja
                and panstwo.panstwo_populacja > 0
                and panstwo.panstwo_PKB is not None
            ):

                wartosc = round(
                    panstwo.panstwo_PKB / panstwo.panstwo_populacja,
                    2
                )

            else:
                wartosc = None

            ranking.append({
                "id": panstwo.PANSTWO_ID,
                "nazwa": panstwo.panstwo_nazwa,
                "kod": panstwo.panstwo_kod,
                "wartosc": wartosc
            })

        if sort == "ASC":

            ranking.sort(
                key=lambda x: (
                    x["wartosc"] is None,
                    x["wartosc"] if x["wartosc"] is not None else float("inf")
                )
            )

        else:

            ranking.sort(
                key=lambda x: (
                    x["wartosc"] is None,
                    -(x["wartosc"] or 0)
                )
            )

        for lp, row in enumerate(ranking, start=1):
            row["lp"] = lp

        return {
            "success": True,
            "ranking": ranking
        }
    
    def _ranking_spoleczenstwo(sort, pole):

        ranking = []

        panstwa = (
            Panstwo.query
            .filter(Panstwo.czy_suwerenny == "TAK")
            .outerjoin(Spoleczenstwo)
            .all()
        )

        for panstwo in panstwa:

            wartosc = None

            if panstwo.spoleczenstwo:
                wartosc = getattr(
                    panstwo.spoleczenstwo,
                    pole,
                    None
                )

            ranking.append({
                "id": panstwo.PANSTWO_ID,
                "nazwa": panstwo.panstwo_nazwa,
                "kod": panstwo.panstwo_kod,
                "wartosc": wartosc
            })

        if sort == "ASC":

            ranking.sort(
                key=lambda x: (
                    x["wartosc"] is None,
                    x["wartosc"] if x["wartosc"] is not None else float("inf")
                )
            )

        else:

            ranking.sort(
                key=lambda x: (
                    x["wartosc"] is None,
                    -(x["wartosc"] or 0)
                )
            )

        for lp, row in enumerate(ranking, start=1):
            row["lp"] = lp

        return {
            "success": True,
            "ranking": ranking
        }
