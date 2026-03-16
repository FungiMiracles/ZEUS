# routes_regiony.py
from flask import render_template, request, redirect, url_for, flash, abort, jsonify
from extensions import db
from models import (
    Region,
    Panstwo,
    Miasto,
    DictRegionTeren,
    DictRegionPolozenie,
    DictRegionTyp,
    DictKontynent,
    Zdarzenie,
)

from permissions import wymaga_roli
from flask import Response, send_file
import os
from sqlalchemy.orm import selectinload

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PLACEHOLDER_PATH = os.path.join(BASE_DIR, "static", "region_placeholder.jpg")

with open(PLACEHOLDER_PATH, "rb") as f:
    REGION_PLACEHOLDER_BYTES = f.read()

def init_regiony_routes(app):

            ### WYSZUKIWANIE REGIONU ###

    @app.route("/wyniki_wyszukiwania_region", methods=["GET"])
    def wyniki_wyszukiwania_region():

        panstwo_nazwa = request.args.get("panstwo_nazwa", "").strip()
        region_nazwa = request.args.get("region_nazwa", "").strip()
        kontynent = request.args.get("kontynent_id")
        panstwo_id = request.args.get("panstwo_id")
        populacja_od = request.args.get("populacja_od")
        populacja_do = request.args.get("populacja_do")
        uksztaltowanie = request.args.get("ukszaltowanie")

        polozenie = request.args.get("polozenie")
        typ_nadrz = request.args.get("typ_nadrz")
        typ_podrz = request.args.get("typ_podrz")

        sejsmicznosc = request.args.get("sejsmicznosc")
        powodz = request.args.get("powodz")
        lawiny = request.args.get("lawiny")
        upal = request.args.get("upal")
        mroz = request.args.get("mroz")
        wulkan = request.args.get("wulkan")

        skomunikowanie = request.args.get("skomunikowanie")

        infra_kolej = request.args.get("infra_kolej")
        infra_drogi = request.args.get("infra_drogi")
        infra_energia = request.args.get("infra_energia")
        infra_mieszkania = request.args.get("infra_mieszkania")
        infra_porty = request.args.get("infra_porty")

        page = request.args.get("page", 1, type=int)
        per_page = 25

        # ===== LISTY DO FILTRÓW =====
        kontynenty = DictKontynent.query.order_by(
            DictKontynent.kontynent_nazwa
        ).all()

        uksztaltowania = DictRegionTeren.query.all()
        polozenia = DictRegionPolozenie.query.all()
        typy = DictRegionTyp.query.all()

        # ===== BAZOWE ZAPYTANIE =====
        query = (
            db.session.query(Region, Panstwo)
            .join(Panstwo, Region.panstwo_id == Panstwo.PANSTWO_ID)
        )

        if panstwo_nazwa:
            query = query.filter(
                Panstwo.panstwo_nazwa.like(f"%{panstwo_nazwa}%")
            )

        if region_nazwa:
            query = query.filter(
                Region.region_nazwa.like(f"%{region_nazwa}%")
            )

        if kontynent:
            query = query.filter(Panstwo.kontynent_id == kontynent)

        if panstwo_id and panstwo_id.isdigit():
            query = query.filter(Region.panstwo_id == int(panstwo_id))

        if populacja_od and populacja_od.isdigit():
            query = query.filter(Region.region_populacja >= int(populacja_od))

        if populacja_do and populacja_do.isdigit():
            query = query.filter(Region.region_populacja <= int(populacja_do))

        if uksztaltowanie and uksztaltowanie.isdigit():
            query = query.filter(
                Region.region_teren_id == int(uksztaltowanie)
            )


        any_filter = any([
            kontynent,
            panstwo_id,
            populacja_od,
            populacja_do,
            uksztaltowanie,
            panstwo_nazwa,
            region_nazwa,
            polozenie,
            typ_nadrz,
            typ_podrz,
            sejsmicznosc,
            powodz,
            lawiny,
            upal,
            mroz,
            wulkan,
            skomunikowanie,
            infra_kolej,
            infra_drogi,
            infra_energia,
            infra_mieszkania,
            infra_porty
        ])

        if polozenie and polozenie.isdigit():
            query = query.filter(Region.region_polozenie_id == int(polozenie))

        if typ_nadrz and typ_nadrz.isdigit():
            query = query.filter(Region.region_typ_nadrz_id == int(typ_nadrz))

        if typ_podrz and typ_podrz.isdigit():
            query = query.filter(Region.region_typ_podrz_id == int(typ_podrz))


        if sejsmicznosc and sejsmicznosc.isdigit():
            query = query.filter(Region.region_sejsmicznosc >= int(sejsmicznosc))

        if powodz and powodz.isdigit():
            query = query.filter(Region.region_ryzyko_powodzi >= int(powodz))

        if lawiny and lawiny.isdigit():
            query = query.filter(Region.region_ryzyko_lawin >= int(lawiny))

        if upal and upal.isdigit():
            query = query.filter(Region.region_ryzyko_upalu >= int(upal))

        if mroz and mroz.isdigit():
            query = query.filter(Region.region_ryzyko_mrozu >= int(mroz))

        if wulkan and wulkan.isdigit():
            query = query.filter(Region.region_aktywny_wulkan >= int(wulkan))


        if skomunikowanie and skomunikowanie.isdigit():
            query = query.filter(Region.region_poziom_skomunikowania >= int(skomunikowanie))


        if infra_kolej and infra_kolej.isdigit():
            query = query.filter(Region.region_stan_infra_kolejowej >= int(infra_kolej))

        if infra_drogi and infra_drogi.isdigit():
            query = query.filter(Region.region_stan_infra_drogowej >= int(infra_drogi))

        if infra_energia and infra_energia.isdigit():
            query = query.filter(Region.region_stan_infra_energetycznej >= int(infra_energia))

        if infra_mieszkania and infra_mieszkania.isdigit():
            query = query.filter(Region.region_stan_infra_mieszkalnej >= int(infra_mieszkania))

        if infra_porty and infra_porty.isdigit():
            query = query.filter(Region.region_stan_infra_portowej >= int(infra_porty))

        if any_filter:
            query = query.order_by(Region.region_populacja.desc())
        else:
            query = query.order_by(Region.region_id.asc())

        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        rows = pagination.items

        results = [
            {
                "region_id": r.region_id,
                "region_nazwa": r.region_nazwa,
                "region_populacja": r.region_populacja or 0,
                "region_ludnosc_pozamiejska": getattr(r, "region_ludnosc_pozamiejska", 0),
                "panstwo_nazwa": p.panstwo_nazwa,
            }
            for r, p in rows
        ]

        total = pagination.total

        args = request.args.to_dict()
        args.pop("page", None)

        return render_template(
            "wyniki_wyszukiwania_region.html",
            results=results,
            pagination=pagination,
            total=total,
            args=args,
            empty=len(results) == 0,
            kontynenty=kontynenty,
            uksztaltowania=uksztaltowania,
            polozenia=polozenia,
            typy=typy
        )


    @app.route("/region_form_add", methods=["GET", "POST"])
    @wymaga_roli("tworzyciel", "wszechmocny")
    def region_add_form():

        if request.method == "POST":
            errors = []

            # ===== PODSTAWOWE POLA =====
            nazwa = request.form.get("region_nazwa")
            panstwo_id = request.form.get("panstwo_id")

            region_teren_id = request.form.get("region_teren_id")
            region_polozenie_id = request.form.get("region_polozenie_id")
            region_typ_nadrz_id = request.form.get("region_typ_nadrz_id")
            region_typ_podrz_id = request.form.get("region_typ_podrz_id")

            # ===== WALIDACJA PODSTAWOWA =====
            if not nazwa:
                errors.append("Pole 'Nazwa regionu' jest wymagane.")

            if not panstwo_id or not panstwo_id.isdigit():
                errors.append("Pole 'ID państwa' musi być liczbą.")

            if region_teren_id and not DictRegionTeren.query.get(region_teren_id):
                errors.append("Nieprawidłowe ukształtowanie terenu.")

            if region_polozenie_id and not DictRegionPolozenie.query.get(region_polozenie_id):
                errors.append("Nieprawidłowe położenie regionu.")

            if region_typ_nadrz_id and not DictRegionTyp.query.get(region_typ_nadrz_id):
                errors.append("Nieprawidłowy typ nadrzędny regionu.")

            if region_typ_podrz_id and not DictRegionTyp.query.get(region_typ_podrz_id):
                errors.append("Nieprawidłowy typ podrzędny regionu.")
                
            # ===== WSKAŹNIKI 0–100 =====
            INT_FIELDS = [
                "region_poziom_skomunikowania",
                "region_sejsmicznosc",
                "region_ryzyko_powodzi",
                "region_ryzyko_lawin",
                "region_ryzyko_upalu",
                "region_ryzyko_mrozu",
                "region_aktywny_wulkan",
                "region_stan_infra_kolejowej",
                "region_stan_infra_drogowej",
                "region_stan_infra_energetycznej",
                "region_stan_infra_mieszkalnej",
                "region_stan_infra_portowej",
            ]

            int_values = {}

            for field in INT_FIELDS:
                val = request.form.get(field)
                if not val:
                    int_values[field] = None
                elif val.isdigit() and 0 <= int(val) <= 100:
                    int_values[field] = int(val)
                else:
                    errors.append(f"Wartość pola {field} musi być liczbą 0–100.")

            if errors:
                return render_template(
                    "region_form_add.html",
                    error=" ".join(errors),
                    form_data=request.form,
                    tereny=DictRegionTeren.query.all(),
                    polozenia=DictRegionPolozenie.query.all(),
                    typy_nadrz=DictRegionTyp.query.filter_by(poziom="NADRZ").all(),
                    typy_podrz=DictRegionTyp.query.filter_by(poziom="PODRZ").all(),
                )

            # ===== KONWERSJE =====
            panstwo_id = int(panstwo_id)

            panstwo = Panstwo.query.get(panstwo_id)
            if not panstwo:
                return render_template(
                    "region_form_add.html",
                    error=f"Państwo o ID {panstwo_id} nie istnieje.",
                    form_data=request.form,
                    tereny=DictRegionTeren.query.all(),
                    polozenia=DictRegionPolozenie.query.all(),
                    typy_nadrz=DictRegionTyp.query.filter_by(poziom="NADRZ").all(),
                    typy_podrz=DictRegionTyp.query.filter_by(poziom="PODRZ").all(),
                )

            duplicates = (
                db.session.query(Region)
                .filter(Region.region_nazwa == nazwa)
                .first()
            )

            if duplicates:
                return render_template(
                    "region_form_add.html",
                    error="Region o takiej nazwie już istnieje.",
                    form_data=request.form,
                    tereny=DictRegionTeren.query.all(),
                    polozenia=DictRegionPolozenie.query.all(),
                    typy_nadrz=DictRegionTyp.query.filter_by(poziom="NADRZ").all(),
                    typy_podrz=DictRegionTyp.query.filter_by(poziom="PODRZ").all(),
                )

            # ===== UTWORZENIE REGIONU =====
            new_region = Region(
                region_nazwa=nazwa,
                panstwo_id=panstwo_id,
                region_teren_id=region_teren_id or None,
                region_polozenie_id=region_polozenie_id or None,
                region_typ_nadrz_id=region_typ_nadrz_id or None,
                region_typ_podrz_id=region_typ_podrz_id or None,
            )

            for field, value in int_values.items():
                setattr(new_region, field, value)

            # ===== MAPA (OPCJONALNA) =====
            file = request.files.get("region_map")

            if file and file.filename:
                if file.mimetype not in ("image/jpeg", "image/png"):
                    return render_template(
                        "region_form_add.html",
                        error="Mapa regionu musi być plikiem JPG lub PNG.",
                        form_data=request.form,
                        tereny=DictRegionTeren.query.all(),
                        polozenia=DictRegionPolozenie.query.all(),
                        typy_nadrz=DictRegionTyp.query.filter_by(poziom="NADRZ").all(),
                        typy_podrz=DictRegionTyp.query.filter_by(poziom="PODRZ").all(),
                    )

                file_bytes = file.read()
                MAX_SIZE = 2 * 1024 * 1024  # 2 MB

                if len(file_bytes) > MAX_SIZE:
                    return render_template(
                        "region_form_add.html",
                        error="Mapa regionu jest za duża (maks. 2 MB).",
                        form_data=request.form,
                        tereny=DictRegionTeren.query.all(),
                        polozenia=DictRegionPolozenie.query.all(),
                        typy_nadrz=DictRegionTyp.query.filter_by(poziom="NADRZ").all(),
                        typy_podrz=DictRegionTyp.query.filter_by(poziom="PODRZ").all(),
                    )

                new_region.region_mapa = file_bytes
                new_region.region_mapa_mime = file.mimetype

            # ===== ZAPIS =====
            try:
                db.session.add(new_region)
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                return render_template(
                    "region_form_add.html",
                    error=f"Błąd podczas zapisu regionu: {e}",
                    form_data=request.form,
                    tereny=DictRegionTeren.query.all(),
                    polozenia=DictRegionPolozenie.query.all(),
                    typy_nadrz=DictRegionTyp.query.filter_by(poziom="NADRZ").all(),
                    typy_podrz=DictRegionTyp.query.filter_by(poziom="PODRZ").all(),
                )

            flash("Region został dodany.", "success")
            return redirect(url_for("region_form", region_id=new_region.region_id))

        # ===== GET =====
        return render_template(
            "region_form_add.html",
            tereny=DictRegionTeren.query.all(),
            polozenia=DictRegionPolozenie.query.all(),
            typy_nadrz=DictRegionTyp.query.filter_by(poziom="NADRZ").all(),
            typy_podrz=DictRegionTyp.query.filter_by(poziom="PODRZ").all(),
        )



    # --------------------------------
    # Usuwanie regionu
    # --------------------------------
    @app.route("/usun_region/<int:region_id>", methods=["POST"])
    @wymaga_roli("wszechmocny")
    def usun_region(region_id):
        region = Region.query.get_or_404(region_id)
        try:
            db.session.delete(region)
            db.session.commit()
            flash(f"Region {region.region_nazwa} został usunięty.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Wystąpił błąd podczas usuwania regionu: {e}", "error")

        return redirect(url_for("wyniki_wyszukiwania_region"))

# --------------------------------
# EDYCJA REGIONU
# --------------------------------
    @app.route("/region/<int:region_id>/edit", methods=["GET", "POST"])
    @wymaga_roli("wszechmocny")
    def region_form_edit(region_id):
        region = Region.query.get_or_404(region_id)

        if request.method == "POST":

            # ===== PODSTAWOWE POLA =====
            nazwa = request.form.get("region_nazwa")
            panstwo_id = request.form.get("panstwo_id")
            region_teren_id = request.form.get("region_teren_id")
            region_polozenie_id = request.form.get("region_polozenie_id")
            region_typ_nadrz_id = request.form.get("region_typ_nadrz_id")
            region_typ_podrz_id = request.form.get("region_typ_podrz_id")

            # ===== WALIDACJA =====
            errors = []

            if not nazwa:
                errors.append("Nazwa regionu jest wymagana.")

            if not panstwo_id or not panstwo_id.isdigit():
                errors.append("ID państwa musi być liczbą.")

            if region_teren_id and not DictRegionTeren.query.get(region_teren_id):
                errors.append("Nieprawidłowe ukształtowanie terenu.")

            if region_polozenie_id and not DictRegionPolozenie.query.get(region_polozenie_id):
                errors.append("Nieprawidłowe położenie regionu.")

            if region_typ_nadrz_id and not DictRegionTyp.query.get(region_typ_nadrz_id):
                errors.append("Nieprawidłowy typ nadrzędny regionu.")

            if region_typ_podrz_id and not DictRegionTyp.query.get(region_typ_podrz_id):
                errors.append("Nieprawidłowy typ podrzędny regionu.")

            # ===== WALIDACJA WSKAŹNIKÓW 0–100 =====
            INT_FIELDS = [
                "region_poziom_skomunikowania",
                "region_sejsmicznosc",
                "region_ryzyko_powodzi",
                "region_ryzyko_lawin",
                "region_ryzyko_upalu",
                "region_ryzyko_mrozu",
                "region_aktywny_wulkan",
                "region_stan_infra_kolejowej",
                "region_stan_infra_drogowej",
                "region_stan_infra_energetycznej",
                "region_stan_infra_mieszkalnej",
                "region_stan_infra_portowej",
            ]

            int_values = {}

            for field in INT_FIELDS:
                val = request.form.get(field)
                if val == "" or val is None:
                    int_values[field] = None
                elif val.isdigit() and 0 <= int(val) <= 100:
                    int_values[field] = int(val)
                else:
                    errors.append(f"Wartość pola {field} musi być liczbą 0–100.")

            if errors:
                return render_template(
                    "region_form_edit.html",
                    error=" ".join(errors),
                    region=region,
                    form_data=request.form,
                    tereny=DictRegionTeren.query.all(),
                    polozenia=DictRegionPolozenie.query.all(),
                    typy_nadrz=DictRegionTyp.query.filter_by(poziom="NADRZ").all(),
                    typy_podrz=DictRegionTyp.query.filter_by(poziom="PODRZ").all(),
                )

            # ===== KONWERSJE =====
            panstwo_id = int(panstwo_id)

            # ===== AKTUALIZACJA PODSTAWOWA =====
            region.region_nazwa = nazwa
            region.panstwo_id = panstwo_id
            region.region_teren_id = request.form.get("region_teren_id") or None
            region.region_polozenie_id = request.form.get("region_polozenie_id") or None
            region.region_typ_nadrz_id = request.form.get("region_typ_nadrz_id") or None
            region.region_typ_podrz_id = request.form.get("region_typ_podrz_id") or None

            for field, value in int_values.items():
                setattr(region, field, value)

            # ===== MAPA (BEZ ZMIAN) =====
            file = request.files.get("region_map")

            if file and file.filename:
                if file.mimetype not in ("image/jpeg", "image/png"):
                    return render_template(
                        "region_form_edit.html",
                        error="Mapa regionu musi być plikiem JPG lub PNG.",
                        region=region,
                        form_data=request.form,
                        tereny=DictRegionTeren.query.all(),
                        polozenia=DictRegionPolozenie.query.all(),
                        typy_nadrz=DictRegionTyp.query.filter_by(poziom="NADRZ").all(),
                        typy_podrz=DictRegionTyp.query.filter_by(poziom="PODRZ").all(),
                    )

                file_bytes = file.read()
                MAX_SIZE = 2 * 1024 * 1024  # 2 MB

                if len(file_bytes) > MAX_SIZE:
                    return render_template(
                        "region_form_edit.html",
                        error="Mapa regionu jest za duża (maks. 2 MB).",
                        region=region,
                        form_data=request.form,
                        tereny=DictRegionTeren.query.all(),
                        polozenia=DictRegionPolozenie.query.all(),
                        typy_nadrz=DictRegionTyp.query.filter_by(poziom="NADRZ").all(),
                        typy_podrz=DictRegionTyp.query.filter_by(poziom="PODRZ").all(),
                    )

                region.region_mapa = file_bytes
                region.region_mapa_mime = file.mimetype

            # ===== COMMIT =====
            db.session.commit()

            flash(
                f"Pomyślnie zaktualizowano region o ID {region.region_id}.",
                "success"
            )
            return redirect(url_for("region_form", region_id=region.region_id))

        # ===== GET =====
        return render_template(
            "region_form_edit.html",
            region=region,
            tereny=DictRegionTeren.query.all(),
            polozenia=DictRegionPolozenie.query.all(),
            typy_nadrz=DictRegionTyp.query.filter_by(poziom="NADRZ").all(),
            typy_podrz=DictRegionTyp.query.filter_by(poziom="PODRZ").all(),
        )


    @app.route("/region/<int:region_id>/mapa")
    def region_mapa(region_id):
        region = Region.query.get_or_404(region_id)

        if not region.region_mapa:
            return Response(
                REGION_PLACEHOLDER_BYTES,
                mimetype="image/jpeg",
                headers={
                    "Cache-Control": "public, max-age=86400"
                }
            )

        return Response(
            region.region_mapa,
            mimetype=region.region_mapa_mime or "image/jpeg",
            headers={
                "Cache-Control": "public, max-age=86400"
            }
        )
    
    @app.route("/region/<int:region_id>")
    def region_form(region_id):
        region = (
            Region.query
            .options(
                selectinload(Region.miasta),
                selectinload(Region.panstwo)
            )
            .get_or_404(region_id)
        )

        panstwo = region.panstwo
        miasta=region.miasta
        back_url = request.referrer
        events = (
            Zdarzenie.query
            .filter(Zdarzenie.region_id == region.region_id)
            .order_by(Zdarzenie.data_entenda.desc())
            .limit(50)
            .all()
        )

        return render_template(
            "region_form.html",
            region=region,
            panstwo=panstwo,
            miasta=miasta,
            events=events,
            back_url=back_url
        )
            


            

