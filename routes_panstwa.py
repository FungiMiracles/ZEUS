# routes_panstwa.py

import os

from flask import (
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify
)
from werkzeug.utils import secure_filename

from utils.autolink import autolink_description

from sqlalchemy.orm import selectinload

from collections import defaultdict

from extensions import db
from models import (
    Panstwo,
    Region,
    Miasto,
    DictKontynent,
    DictPanstwoUstroj,
    OrganizacjaPanstwo,
    OrganizacjaMiedzynarodowa,
    Spoleczenstwo,
    Wojsko,
    Gospodarka,
    Zdarzenie,
    JezykiPerPanstwo,
    Jezyk,
    RegionStateHistory,
    SpoleczenstwoStateHistory,
    Przywodztwo,
    DictPrzywodcaTyp
)

from paths import (
    FLAGI_DIR,
    MAPY_DIR
)

from permissions import wymaga_roli
from sqlalchemy import inspect, cast, Float
from datetime import datetime, timezone
from sqlalchemy.orm import joinedload

from flask import jsonify
from models import (
    Stosunki,
    DictStosunkiStan,
    DictStosunkiRelacja
)

# ============================================================
# API
# ============================================================

def init_panstwa_api(app):

    @app.route("/api/panstwo_populacja")
    def panstwo_populacja():
        pid = request.args.get("id")
        p = Panstwo.query.get(pid)

        if not p:
            return jsonify({
                "populacja": None,
                "audit": None
            })

        return jsonify({
            "populacja": p.panstwo_populacja,
            "audit": (
                p.panstwo_populacja_audit.isoformat()
                if p.panstwo_populacja_audit
                else None
            )
        })

    @app.route("/api/panstwo_suggest")
    def panstwo_suggest():
        q = request.args.get("q", "")
        rows = (
            Panstwo.query
            .filter(Panstwo.panstwo_nazwa.like(f"%{q}%"))
            .limit(10)
            .all()
        )

        return jsonify([
            {"PANSTWO_ID": p.PANSTWO_ID, "panstwo_nazwa": p.panstwo_nazwa}
            for p in rows
        ])

# ============================================================
# ROUTES
# ============================================================

def init_panstwa_routes(app):

    # ================= WYSZUKIWARKA PAŃST =================

    @app.route("/wyniki_wyszukiwania", methods=["GET"])
    def wyniki_wyszukiwania():

        kontynent_id = request.args.get("kontynent_id")
        nazwa = request.args.get("panstwo_nazwa")
        kod = request.args.get("panstwo_kod")

        ustroj_id = request.args.get("ustroj_id", type=int)
        populacja_od = request.args.get("populacja_od")
        populacja_do = request.args.get("populacja_do")
        powierzchnia = request.args.get("panstwo_powierzchnia")
        jezyk = request.args.get("panstwo_jezyk")
        religia = request.args.get("panstwo_religia")
        pkb_od = request.args.get("pkb_od")
        pkb_do = request.args.get("pkb_do")
        pkb_pc_od = request.args.get("pkb_pc_od")
        pkb_pc_do = request.args.get("pkb_pc_do")

        def parse_float(val):
            if not val:
                return None
            return float(val.replace(" ", "").replace(",", "."))

        pkb_pc_od_val = parse_float(pkb_pc_od)
        pkb_pc_do_val = parse_float(pkb_pc_do)

        czy_suwerenny = request.args.get("czy_suwerenny")
        status = request.args.get('status', 'aktywne')
        if status not in ('aktywne', 'usunięte'):
            status = 'aktywne'
        ustroje = DictPanstwoUstroj.query.order_by(
            DictPanstwoUstroj.ustroj_nazwa
        ).all()

        kontynenty = DictKontynent.query.order_by(DictKontynent.kontynent_nazwa).all()

        query = Panstwo.query.filter(Panstwo.status == status)
        if status == 'usunięte':
            query = query.execution_options(include_deleted_countries=True)

        if kontynent_id:
            query = query.filter(Panstwo.kontynent_id == kontynent_id)

        if nazwa:
            query = query.filter(Panstwo.panstwo_nazwa.like(f"%{nazwa}%"))

        if kod:
            query = query.filter(Panstwo.panstwo_kod.like(f"%{kod}%"))

        if ustroj_id:
            query = query.filter(Panstwo.ustroj_id == ustroj_id)

        if populacja_od:
            query = query.filter(Panstwo.panstwo_populacja >= int(populacja_od))

        if populacja_do:
            query = query.filter(Panstwo.panstwo_populacja <= int(populacja_do))

        if powierzchnia:
            query = query.filter(Panstwo.panstwo_powierzchnia >= int(powierzchnia))

        if jezyk:
            query = query.filter(Panstwo.panstwo_jezyk.like(f"%{jezyk}%"))

        if religia:
            query = query.filter(Panstwo.panstwo_religia.like(f"%{religia}%"))

        pkb_pc_expr = cast(Panstwo.panstwo_PKB, Float) / cast(Panstwo.panstwo_populacja, Float)

        if pkb_pc_od_val is not None:
            query = query.filter(
                Panstwo.panstwo_populacja.isnot(None),
                Panstwo.panstwo_populacja != 0,
                Panstwo.panstwo_PKB.isnot(None),
                pkb_pc_expr >= pkb_pc_od_val
            )

        if pkb_pc_do_val is not None:
            query = query.filter(
                Panstwo.panstwo_populacja.isnot(None),
                Panstwo.panstwo_populacja != 0,
                Panstwo.panstwo_PKB.isnot(None),
                pkb_pc_expr <= pkb_pc_do_val
            )

        if czy_suwerenny:
            query = query.filter(Panstwo.czy_suwerenny == czy_suwerenny)

        page = request.args.get("page", 1, type=int)
        per_page = 25

        pagination = query.paginate(page=page, per_page=per_page, error_out=False)

        results = pagination.items
        total = pagination.total

        args = request.args.to_dict()
        args.pop("page", None)

        return render_template(
            "wyniki_wyszukiwania.html",
            results=results,
            pagination=pagination,
            total=total,
            ustroje=ustroje,
            args=args,
            kontynenty=kontynenty,
            selected_status=status,
            empty=len(results) == 0
        )

    # ================= FORMULARZ PAŃSTWA =================

    @app.route("/panstwo/<int:panstwo_id>")
    def panstwo_form(panstwo_id):

        p = Panstwo.query.get_or_404(panstwo_id)

        regiony = p.regiony

        miasta = (
            Miasto.query
            .filter_by(panstwo_id=panstwo_id)
            .order_by(Miasto.miasto_populacja.desc())
            .all()
        )

        aktualny_przywodca = (
            Przywodztwo.query
            .filter_by(panstwo_id=p.PANSTWO_ID)
            .order_by(Przywodztwo.data_entenda_do.desc())
            .first()
        )

        stolica = next(
            (m for m in miasta if m.miasto_typ_id == 1),
            None)
        

        print("PAŃSTWO:", p.PANSTWO_ID, p.panstwo_nazwa)

        for m in miasta:
            print(
                "MIASTO:",
                m.miasto_nazwa,
                "typ=", m.miasto_typ_id,
                "panstwo=", m.panstwo_id
            )

        print("STOLICA:", stolica)

        infra_sum = 0
        infra_count = 0

        for r in regiony:

            if r.region_stan_infra_kolejowej is not None:
                infra_sum += r.region_stan_infra_kolejowej
                infra_count += 1

            if r.region_stan_infra_drogowej is not None:
                infra_sum += r.region_stan_infra_drogowej
                infra_count += 1

            if r.region_stan_infra_energetycznej is not None:
                infra_sum += r.region_stan_infra_energetycznej
                infra_count += 1

            if r.region_stan_infra_mieszkalnej is not None:
                infra_sum += r.region_stan_infra_mieszkalnej
                infra_count += 1

            if r.region_polozenie_id and r.region_polozenie_id != 1:
                if r.region_stan_infra_portowej is not None:
                    infra_sum += r.region_stan_infra_portowej
                    infra_count += 1

        miasto_values = [
            r.roczny_przyrost_miasto_pct
            for r in regiony
            if r.roczny_przyrost_miasto_pct is not None
        ]

        wies_values = [
            r.roczny_przyrost_wies_pct
            for r in regiony
            if r.roczny_przyrost_wies_pct is not None
        ]

        if miasto_values and wies_values:
            przyrost_avg = round(
                (
                    sum(miasto_values) / len(miasto_values)
                    +
                    sum(wies_values) / len(wies_values)
                ) / 2,
                2
            )
        else:
            przyrost_avg = None

        infra_avg = round(infra_sum / infra_count, 1) if infra_count > 0 else None

        profil_jezykowy = p.profil_jezykowy

        organizacje = (
            OrganizacjaPanstwo.query
            .filter_by(
                panstwo_id=panstwo_id,
                czy_aktywny=True
            )
            .all()
        )

        ustroje = DictPanstwoUstroj.query.order_by(
            DictPanstwoUstroj.ustroj_nazwa
        ).all()

        pkb_per_capita = None

        if (
            p.panstwo_PKB is not None
            and p.panstwo_populacja not in (None, 0)
        ):
            pkb_per_capita = int(
                p.panstwo_PKB / p.panstwo_populacja
            )

        zwierzch_panstwo = None

        if p.zwierzch_panstwo_id:
            zwierzch_panstwo = Panstwo.query.get(
                p.zwierzch_panstwo_id
            )
        
        jezyki = JezykiPerPanstwo.query.filter_by(
            panstwo_id=panstwo_id
        ).first()

        jezyki_lista = []

        if jezyki:

            pola = [
                "jezyk_urzedowy1",
                "jezyk_urzedowy2",
                "jezyk_urzedowy3",
                "jezyk_mniejszosciowy1",
                "jezyk_mniejszosciowy2",
                "jezyk_mniejszosciowy3",
                "jezyk_mniejszosciowy4",
                "jezyk_mniejszosciowy5",
            ]

            for pole in pola:
                jezyk_id = getattr(jezyki, pole)

                if jezyk_id:
                    jezyk = Jezyk.query.get(jezyk_id)

                    if jezyk:
                        jezyki_lista.append(jezyk.jezyk_nazwa)
            
        opis_html = autolink_description(
            p.panstwo_opis or ""
        )

        from services.region_secession import RegionSecession
        secession_media = db.session.query(RegionSecession.id).filter_by(new_country_id=panstwo_id).first()
        return render_template(
            "panstwo_form.html",
            secession_media=secession_media,
            secession_map_missing=bool(secession_media and not os.path.isfile(os.path.join(MAPY_DIR, p.panstwo_nazwa.replace(' ', '_') + '.jpg'))),
            p=p,
            miasta=miasta,
            profil_jezykowy=profil_jezykowy,
            ustroje=ustroje,
            ostatnia_edycja=p.opis_updated_at,
            infra_avg=infra_avg,
            pkb_per_capita=pkb_per_capita,
            stolica=stolica,
            organizacje=organizacje,
            zwierzch_panstwo=zwierzch_panstwo,
            przyrost_avg=przyrost_avg,
            jezyki_lista=jezyki_lista,
            opis_html=opis_html,
            aktualny_przywodca=aktualny_przywodca,
        )

    # ================= DODAWANIE PAŃSTWA =================

    @app.route("/panstwo_form_add", methods=["GET", "POST"])
    @wymaga_roli("tworzyciel", "wszechmocny")
    def panstwo_add_form():

        kontynenty = DictKontynent.query.order_by(DictKontynent.kontynent_nazwa).all()

        ustroje = DictPanstwoUstroj.query.order_by(
            DictPanstwoUstroj.ustroj_nazwa
        ).all()

        panstwa_suwerenne = (
            Panstwo.query
            .filter_by(czy_suwerenny="TAK")
            .order_by(Panstwo.panstwo_nazwa)
            .all()
        )

        if request.method == "POST":

            nazwa = request.form.get("panstwo_nazwa")
            pelna = request.form.get("panstwo_pelna_nazwa")
            kod = request.form.get("panstwo_kod")
            ustroj_id = request.form.get("ustroj_id")
            stolica = request.form.get("panstwo_stolica")
            populacja = int(request.form.get("panstwo_populacja"))
            pkb = int(request.form.get("PKB"))
            waluta = request.form.get("panstwo_waluta")
            religia = request.form.get("panstwo_religia")
            kontynent_id_raw = request.form.get("kontynent_id")
            kadencja_przywodcy = request.form.get("kadencja_przywodcy")
            try:
                kontynent_id = int(kontynent_id_raw)
            except (TypeError, ValueError):
                kontynent_id = None
            powierzchnia = int(request.form.get("panstwo_powierzchnia"))
            czy_suwerenny = request.form.get("czy_suwerenny")
            zwierzch_panstwo_id = request.form.get(
                "zwierzch_panstwo_id"
            )

            required_fields = [
                nazwa, pelna, kod, ustroj_id, populacja, pkb,
                waluta, religia,
                kontynent_id_raw, powierzchnia, czy_suwerenny, kadencja_przywodcy
            ]

            if any(not field for field in required_fields):
                return render_template(
                    "panstwo_form_add.html",
                    kontynenty=kontynenty,
                    error="Wszystkie pola formularza są obowiązkowe.",
                    form_data=request.form
                )

            flaga = request.files.get("flaga")
            mapa = request.files.get("mapa")

            if czy_suwerenny not in ("TAK", "NIE"):
                return render_template(
                    "panstwo_form_add.html",
                    kontynenty=kontynenty,
                    error="Musisz określić, czy państwo jest suwerenne.",
                    form_data=request.form
                )

            if (
                czy_suwerenny == "NIE"
                and not zwierzch_panstwo_id
            ):
                return render_template(
                    "panstwo_form_add.html",
                    kontynenty=kontynenty,
                    ustroje=ustroje,
                    panstwa_suwerenne=panstwa_suwerenne,
                    error=(
                        "Dla państwa niesuwerennego należy "
                        "wskazać państwo zwierzchnicze."
                    ),
                    form_data=request.form
                )

            if not flaga or not mapa or flaga.filename == "" or mapa.filename == "":
                return render_template(
                    "panstwo_form_add.html",
                    kontynenty=kontynenty,
                    error="Dodaj flagę i mapę państwa.",
                    form_data=request.form
                )

            filename_base = secure_filename(nazwa.replace(" ", "_"))

            try:
                flaga.save(os.path.join(FLAGI_DIR, f"{filename_base}.jpg"))
                mapa.save(os.path.join(MAPY_DIR, f"{filename_base}.jpg"))
            except Exception as e:
                return render_template(
                    "panstwo_form_add.html",
                    kontynenty=kontynenty,
                    ustroje=ustroje,
                    error=f"Błąd zapisu plików: {e}",
                    form_data=request.form
                )

            try:
                panstwo = Panstwo(
                    panstwo_nazwa=nazwa,
                    panstwo_pelna_nazwa=pelna,
                    panstwo_kod=kod,
                    ustroj_id=ustroj_id,
                    panstwo_populacja=populacja,
                    panstwo_PKB=pkb,
                    panstwo_waluta=waluta,
                    panstwo_religia=religia,
                    kontynent_id=kontynent_id,
                    panstwo_powierzchnia=powierzchnia,
                    czy_suwerenny=czy_suwerenny,
                    kadencja_przywodcy=kadencja_przywodcy,
                    zwierzch_panstwo_id=(
                        None
                        if czy_suwerenny == "TAK"
                        else int(zwierzch_panstwo_id)
                    ),
                )
                db.session.add(panstwo)
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                return render_template(
                    "panstwo_form_add.html",
                    kontynenty=kontynenty,
                    ustroje=ustroje,
                    error=f"Błąd zapisu do bazy: {e}",
                    form_data=request.form
                )

            return redirect(url_for("panstwo_dodano"))

        return render_template(
            "panstwo_form_add.html",
            kontynenty=kontynenty,
            ustroje=ustroje,
            panstwa_suwerenne=panstwa_suwerenne
        )

    @app.route("/panstwo/<int:panstwo_id>/edit", methods=["GET", "POST"])
    def panstwo_form_edit(panstwo_id):

        p = Panstwo.query.get_or_404(panstwo_id)

        kontynenty = DictKontynent.query.order_by(
            DictKontynent.kontynent_nazwa
        ).all()

        ustroje = DictPanstwoUstroj.query.order_by(
            DictPanstwoUstroj.ustroj_nazwa
        ).all()

        panstwa_suwerenne = (
            Panstwo.query
            .filter_by(czy_suwerenny="TAK")
            .order_by(Panstwo.panstwo_nazwa)
            .all()
        )

        if request.method == "POST":

            flaga = request.files.get("flaga")
            mapa = request.files.get("mapa")

            form = request.form

            czy_suwerenny = form.get("czy_suwerenny")
            zwierzch_panstwo_id = form.get("zwierzch_panstwo_id")
            kadencja_przywodcy = form.get("kadencja_przywodcy")

            errors = []

            required_fields = [
                "panstwo_nazwa",
                "panstwo_pelna_nazwa",
                "panstwo_kod",
                "kontynent_id",
                "ustroj_id",
                "panstwo_powierzchnia",
                "panstwo_waluta",
                "panstwo_religia",
                "panstwo_PKB",
                "czy_suwerenny",
                "kadencja_przywodcy"
            ]

            for f in required_fields:
                if not form.get(f):
                    errors.append(
                        "Wszystkie pola formularza są wymagane."
                    )

            if errors:
                return render_template(
                    "panstwo_form_edit.html",
                    p=p,
                    kontynenty=kontynenty,
                    ustroje=ustroje,
                    panstwa_suwerenne=panstwa_suwerenne,
                    error=" ".join(set(errors)),
                    form_data=form
                )

            if czy_suwerenny not in ("TAK", "NIE"):
                return render_template(
                    "panstwo_form_edit.html",
                    p=p,
                    kontynenty=kontynenty,
                    ustroje=ustroje,
                    panstwa_suwerenne=panstwa_suwerenne,
                    error="Musisz określić status suwerenności państwa.",
                    form_data=form
                )

            if (
                czy_suwerenny == "NIE"
                and not zwierzch_panstwo_id
            ):
                return render_template(
                    "panstwo_form_edit.html",
                    p=p,
                    kontynenty=kontynenty,
                    ustroje=ustroje,
                    panstwa_suwerenne=panstwa_suwerenne,
                    error=(
                        "Dla państwa niesuwerennego należy "
                        "wskazać państwo zwierzchnicze."
                    ),
                    form_data=form
                )

            try:

                p.panstwo_nazwa = form.get("panstwo_nazwa")

                filename_base = secure_filename(
                    p.panstwo_nazwa.replace(" ", "_")
                )

                if flaga and flaga.filename:
                    flaga.save(
                        os.path.join(
                            FLAGI_DIR,
                            f"{filename_base}.jpg"
                        )
                    )

                if mapa and mapa.filename:
                    mapa.save(
                        os.path.join(
                            MAPY_DIR,
                            f"{filename_base}.jpg"
                        )
                    )

                p.panstwo_pelna_nazwa = form.get("panstwo_pelna_nazwa")
                p.panstwo_kod = form.get("panstwo_kod")

                p.kontynent_id = int(
                    form.get("kontynent_id")
                )

                p.ustroj_id = int(
                    form.get("ustroj_id")
                )

                p.kadencja_przywodcy = int(
                    form.get("kadencja_przywodcy")
                )

                p.panstwo_stolica = form.get(
                    "panstwo_stolica"
                )

                p.panstwo_powierzchnia = int(
                    form.get("panstwo_powierzchnia")
                )

                p.panstwo_waluta = form.get(
                    "panstwo_waluta"
                )

                p.panstwo_religia = form.get(
                    "panstwo_religia"
                )

                p.panstwo_PKB = int(
                    form.get("panstwo_PKB")
                )

                p.czy_suwerenny = czy_suwerenny

                if czy_suwerenny == "TAK":
                    p.zwierzch_panstwo_id = None
                else:
                    p.zwierzch_panstwo_id = int(
                        zwierzch_panstwo_id
                    )

                db.session.commit()

            except Exception as e:

                db.session.rollback()

                return render_template(
                    "panstwo_form_edit.html",
                    p=p,
                    kontynenty=kontynenty,
                    ustroje=ustroje,
                    panstwa_suwerenne=panstwa_suwerenne,
                    error=f"Błąd zapisu: {e}",
                    form_data=form
                )

            return redirect(
                url_for(
                    "panstwo_form",
                    panstwo_id=p.PANSTWO_ID
                )
            )

        return render_template(
            "panstwo_form_edit.html",
            p=p,
            kontynenty=kontynenty,
            ustroje=ustroje,
            panstwa_suwerenne=panstwa_suwerenne,
        )

    # ================= USUWANIE PAŃSTWA =================

    @app.route("/usun_panstwo/<int:panstwo_id>", methods=["POST"])
    @wymaga_roli("wszechmocny")
    def usun_panstwo(panstwo_id):
        panstwo = Panstwo.query.get_or_404(panstwo_id)

        try:
            db.session.delete(panstwo)
            db.session.commit()
            flash(
                f"Państwo {panstwo.panstwo_nazwa} zostało usunięte.",
                "success"
            )
        except Exception as e:
            db.session.rollback()
            flash(f"Wystąpił błąd podczas usuwania: {e}", "error")

        return redirect(url_for("wyniki_wyszukiwania"))

    # ================= EDYCJA OPISU (MARKDOWN) =================

    @app.route("/panstwo/<int:panstwo_id>/opis/edit", methods=["POST"])
    @wymaga_roli("wszechmocny")
    def panstwo_opis_edit(panstwo_id):
        panstwo = Panstwo.query.get_or_404(panstwo_id)

        nowy_opis = request.form.get("opis_html", "").strip()

        if not nowy_opis:
            flash("Opis nie może być pusty.", "error")
            return redirect(url_for("panstwo_form", panstwo_id=panstwo_id))

        # ─── AUDYT OPISU (POPRAWNA KOLEJNOŚĆ) ───
        if panstwo.panstwo_opis != nowy_opis:
            panstwo.panstwo_opis = nowy_opis
            panstwo.panstwo_opis_audit = datetime.now()

        db.session.commit()

        flash("Informacje szczegółowe zostały zapisane.", "success")
        return redirect(url_for("panstwo_form", panstwo_id=panstwo_id))
    
    @app.route("/api/panstwa_nazwy")
    def api_panstwa_nazwy():
        rows = Panstwo.query.with_entities(
            Panstwo.PANSTWO_ID,
            Panstwo.panstwo_nazwa
        ).all()

        return jsonify({
            row.PANSTWO_ID: row.panstwo_nazwa
            for row in rows
        })

    @app.route("/api/panstwa_meta")
    def api_panstwa_meta():
        rows = (
            db.session.query(
                Panstwo.PANSTWO_ID,
                Panstwo.panstwo_nazwa,
                Panstwo.panstwo_PKB,
                Panstwo.panstwo_populacja,
                Spoleczenstwo.stabilnosc_spoleczna,
                Spoleczenstwo.przestepczosc,
                Wojsko.bron_atomowa_ilosc,
                Wojsko.procent_PKB,
                Gospodarka.wzrost_pkb,
                Region.region_ryzyko_upalu,
                Region.region_ryzyko_mrozu,
                Region.roczny_przyrost_miasto_pct,
                Region.roczny_przyrost_wies_pct,
                Region.region_stan_infra_drogowej,
                Region.region_stan_infra_kolejowej,
                Region.region_stan_infra_energetycznej,
                Region.region_stan_infra_mieszkalnej,
                Region.region_stan_infra_portowej,
                Region.region_polozenie_id
            )
            .outerjoin(
                Spoleczenstwo,
                Spoleczenstwo.panstwo_id == Panstwo.PANSTWO_ID
            )
            .outerjoin(
                Wojsko,
                Wojsko.panstwo_id == Panstwo.PANSTWO_ID
            )
            .outerjoin(
                Gospodarka,
                Gospodarka.panstwo_id == Panstwo.PANSTWO_ID
            )
            .outerjoin(
                Region,
                Region.panstwo_id == Panstwo.PANSTWO_ID
            )
            .all()
        )

        result = {}

        for row in rows:
            pid = row.PANSTWO_ID

            if pid not in result:
                pkb = row.panstwo_PKB or 0
                populacja = row.panstwo_populacja or 0

                result[pid] = {
                    "nazwa": row.panstwo_nazwa,
                    "pkb": pkb,
                    "populacja": populacja,
                    "pkb_pc": pkb / populacja if populacja > 0 else 0,
                    "stabilnosc_spoleczna": row.stabilnosc_spoleczna or 0,
                    "przestepczosc": row.przestepczosc or 0,
                    "bron_atomowa_ilosc": row.bron_atomowa_ilosc or 0,
                    "procent_pkb_wojsko": row.procent_PKB or 0,
                    "wzrost_pkb": row.wzrost_pkb or 0,

                    "_upal_sum": 0,
                    "_upal_count": 0,
                    "_mroz_sum": 0,
                    "_mroz_count": 0,
                    "_przyrost_sum": 0,
                    "_przyrost_count": 0,
                    "_infra_sum": 0,
                    "_infra_count": 0
                }

            if row.region_ryzyko_upalu is not None:
                result[pid]["_upal_sum"] += row.region_ryzyko_upalu
                result[pid]["_upal_count"] += 1

            if row.region_ryzyko_mrozu is not None:
                result[pid]["_mroz_sum"] += row.region_ryzyko_mrozu
                result[pid]["_mroz_count"] += 1

            if (
                row.roczny_przyrost_miasto_pct is not None
                and row.roczny_przyrost_wies_pct is not None
            ):
                regional_growth = (
                    float(row.roczny_przyrost_miasto_pct)
                    + float(row.roczny_przyrost_wies_pct)
                ) / 2

                result[pid]["_przyrost_sum"] += regional_growth
                result[pid]["_przyrost_count"] += 1
            
            infra_values = []

            if row.region_stan_infra_drogowej is not None:
                infra_values.append(row.region_stan_infra_drogowej)

            if row.region_stan_infra_kolejowej is not None:
                infra_values.append(row.region_stan_infra_kolejowej)

            if row.region_stan_infra_energetycznej is not None:
                infra_values.append(row.region_stan_infra_energetycznej)

            if row.region_stan_infra_mieszkalnej is not None:
                infra_values.append(row.region_stan_infra_mieszkalnej)

            if (
                row.region_polozenie_id != 1
                and row.region_stan_infra_portowej is not None
            ):
                infra_values.append(row.region_stan_infra_portowej)

            if infra_values:
                region_avg = sum(infra_values) / len(infra_values)

                result[pid]["_infra_sum"] += region_avg
                result[pid]["_infra_count"] += 1

        for pid in result:
            up_count = result[pid]["_upal_count"]
            mr_count = result[pid]["_mroz_count"]
            infra_count = result[pid]["_infra_count"]

            result[pid]["poziom_infrastruktury"] = round(
                result[pid]["_infra_sum"] / infra_count,
                1
            ) if infra_count else 0

            result[pid]["ryzyko_upalu"] = round(
                result[pid]["_upal_sum"] / up_count, 1
            ) if up_count else 0

            result[pid]["ryzyko_mrozu"] = round(
                result[pid]["_mroz_sum"] / mr_count, 1
            ) if mr_count else 0

            growth_count = result[pid]["_przyrost_count"]

            result[pid]["przyrost_ludnosci"] = round(
                result[pid]["_przyrost_sum"] / growth_count,
                2
            ) if growth_count else 0

            del result[pid]["_upal_sum"]
            del result[pid]["_upal_count"]
            del result[pid]["_mroz_sum"]
            del result[pid]["_mroz_count"]
            del result[pid]["_przyrost_sum"]
            del result[pid]["_przyrost_count"]
            del result[pid]["_infra_sum"]
            del result[pid]["_infra_count"]

        return jsonify(result)

    @app.route("/api/mapa/stosunki/<int:panstwo_id>")
    def api_mapa_stosunki(panstwo_id):

        rows = (
            db.session.query(
                Stosunki.PANSTWO_ID,
                Stosunki.PANSTWO_ID2,
                DictStosunkiRelacja.relacja_nazwa
            )
            .join(
                DictStosunkiRelacja,
                Stosunki.relacja_id == DictStosunkiRelacja.relacja_id
            )
            .filter(
                (Stosunki.PANSTWO_ID == panstwo_id) |
                (Stosunki.PANSTWO_ID2 == panstwo_id)
            )
            .all()
        )

        COLOR_MAP = {
            "sojusznicze": "#006400",
            "partnerskie_strategiczne": "#228b22",
            "partnerskie": "#32cd32",
            "przyjazne": "#66bb6a",
            "dobre": "#9ccc65",
            "neutralne": "#d4af37",
            "chlodne": "#ffb74d",
            "zle": "#ff8a65",
            "napiete": "#ff5722",
            "wrogie": "#c62828",
            "egzystencjalnie_wrogie": "#6a0000"
        }

        result = {}

        for row in rows:

            other_id = (
                row.PANSTWO_ID2
                if row.PANSTWO_ID == panstwo_id
                else row.PANSTWO_ID
            )

            relacja = (
                (row.relacja_nazwa or "")
                .strip()
                .lower()
                .replace("ą", "a")
                .replace("ć", "c")
                .replace("ę", "e")
                .replace("ł", "l")
                .replace("ń", "n")
                .replace("ó", "o")
                .replace("ś", "s")
                .replace("ż", "z")
                .replace("ź", "z")
                .replace(" ", "_")
            )

            result[other_id] = {
                "relacja": relacja,
                "kolor": COLOR_MAP.get(relacja, "#999999")
            }

        return jsonify({
            "selected_country": panstwo_id,
            "relations": result
        })
    
    def avg_delta(rows, old_attr, new_attr):

        values = []

        for r in rows:
            old = getattr(r, old_attr)
            new = getattr(r, new_attr)

            if old is None or new is None:
                continue

            values.append(float(new - old))

        if not values:
            return None

        return round(sum(values) / len(values), 2)
    
    def sum_delta(rows, old_attr, new_attr):

        total = 0

        found = False

        for r in rows:

            old = getattr(r, old_attr)
            new = getattr(r, new_attr)

            if old is None or new is None:
                continue

            total += new - old
            found = True

        return total if found else None
    

    @app.route("/panstwo_dziennik_ustaw/<int:panstwo_id>")
    def panstwo_dziennik_ustaw(panstwo_id):

        panstwo = Panstwo.query.get_or_404(panstwo_id)

        ustawy = (
            Zdarzenie.query
            .filter_by(
                panstwo_id=panstwo_id,
                zdarzenie_typ="nowa_ustawa"
            )
            .order_by(Zdarzenie.data_entenda.desc())
            .all()
        )

        event_ids = [u.zdarzenie_id for u in ustawy]
        
        events = (
            Zdarzenie.query
            .filter(
                Zdarzenie.panstwo_id == panstwo_id,
                Zdarzenie.zdarzenie_typ != "nowa_ustawa",
                Zdarzenie.status != "archiwalne",
                Zdarzenie.status != "zakonczone"
            )
            .all()
        )

        event_ids = [u.zdarzenie_id for u in ustawy]
        
        changes = (
            RegionStateHistory.query
            .filter(RegionStateHistory.event_id.in_(event_ids))
            .all()
        )

        social_changes = (
            SpoleczenstwoStateHistory.query
            .filter(SpoleczenstwoStateHistory.event_id.in_(event_ids))
            .all()
        )

        region_map = defaultdict(list)

        for r in changes:
            region_map[r.event_id].append(r)

        changes_map = {}

        for event_id, rows in region_map.items():

            delta = []

            def add(label, value, suffix=""):

                if value is None or value == 0:
                    return

                delta.append({
                    "label": label,
                    "value": value,
                    "suffix": suffix
                })

            add(
                "Ludność",
                sum_delta(rows, "old_ludnosc", "new_ludnosc")
            )

            add(
                "Drogi",
                avg_delta(rows, "old_drogi", "new_drogi")
            )

            add(
                "Kolej",
                avg_delta(rows, "old_kolej", "new_kolej")
            )

            add(
                "Energia",
                avg_delta(rows, "old_energia", "new_energia")
            )

            add(
                "Mieszkania",
                avg_delta(rows, "old_mieszkania", "new_mieszkania")
            )

            add(
                "Porty",
                avg_delta(rows, "old_porty", "new_porty")
            )

            add(
                "Degradacja",
                avg_delta(
                    rows,
                    "old_degradacja_srodowiska",
                    "new_degradacja_srodowiska"
                )
            )

            add(
                "Powietrze",
                avg_delta(
                    rows,
                    "old_zanieczyszczenie_powietrza",
                    "new_zanieczyszczenie_powietrza"
                )
            )

            changes_map[event_id] = delta
        
        for c in social_changes:

            delta = changes_map.setdefault(c.event_id, [])

            def add(name, old, new):
                if old is None or new is None:
                    return

                diff = new - old

                if diff != 0:
                    delta.append({
                        "label": name,
                        "value": int(diff) if diff == int(diff) else float(diff)
                    })

            add("Stabilność", c.old_stabilnosc, c.new_stabilnosc)
            add("Zadowolenie", c.old_zadowolenie, c.new_zadowolenie)
            add("Nierówności", c.old_nierownosci, c.new_nierownosci)
            add("Edukacja", c.old_edukacja, c.new_edukacja)
            add("Świadomość", c.old_swiadomosc, c.new_swiadomosc)
            add("Zaufanie", c.old_zaufanie, c.new_zaufanie)

            add("Napięcia religijne", c.old_napiecia_religijne, c.new_napiecia_religijne)
            add("Napięcia etniczne", c.old_napiecia_etniczne, c.new_napiecia_etniczne)
            add("Napięcia klasowe", c.old_napiecia_klasowe, c.new_napiecia_klasowe)

            add("Przestępczość", c.old_przestepczosc, c.new_przestepczosc)
            add("Radykalizacja", c.old_radykalizacja, c.new_radykalizacja)

            add("Spójność", c.old_spojnosc, c.new_spojnosc)
            add("Tożsamość", c.old_tozsamosc, c.new_tozsamosc)
            add("Konserwatyzm", c.old_konserwatyzm, c.new_konserwatyzm)
            add("Otwartość", c.old_otwartosc, c.new_otwartosc)

            add("Spożycie alkoholu", c.old_spozycie_alkoholu, c.new_spozycie_alkoholu)
            add("Spożycie narkotyków", c.old_spozycie_narkotykow, c.new_spozycie_narkotykow)
            add("Zdrowie publiczne", c.old_zdrowie_publiczne, c.new_zdrowie_publiczne)
        
        for ustawa in ustawy:
            print("USTAWA", ustawa.zdarzenie_id)
            print(changes_map.get(ustawa.zdarzenie_id))

        return render_template(
            "dziennik_ustaw.html",
            panstwo=panstwo,
            ustawy=ustawy,
            event_changes=changes_map
        )
    


