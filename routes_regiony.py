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
    RegionZasob,
    DictZasob,
    RegionBudzet,
    RegionInfrastruktura,
    DictInfrastruktura,
    RegionMagazyn,
    BudynekProdukcja,
    RegionStateHistory,
    SpoleczenstwoStateHistory
)

from sqlalchemy import exists
from sqlalchemy.orm import aliased

from permissions import wymaga_roli
from flask import Response, send_file
import os
from sqlalchemy.orm import selectinload
from sqlalchemy import func

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PLACEHOLDER_PATH = os.path.join(BASE_DIR, "static", "region_placeholder.jpg")

with open(PLACEHOLDER_PATH, "rb") as f:
    REGION_PLACEHOLDER_BYTES = f.read()

def init_regiony_routes(app):
    from routes_region_secession import region_sovereignty_bp
    if region_sovereignty_bp.name not in app.blueprints:
        app.register_blueprint(region_sovereignty_bp)


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
        region_id = request.args.get("region_id")

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
        bez_stolicy = request.args.get("bez_stolicy")

        page = request.args.get("page", 1, type=int)
        per_page = 25

        # ===== LISTY DO FILTRÓW =====
        kontynenty = DictKontynent.query.order_by(
            DictKontynent.kontynent_nazwa
        ).all()

        uksztaltowania = DictRegionTeren.query.all()
        polozenia = DictRegionPolozenie.query.all()
        typy = DictRegionTyp.query.all()
        polkula = request.args.get("polkula")

        # ===== WYLICZANA POPULACJA REGIONU =====

        region_pop_expr = (
            Region.region_ludnosc_pozamiejska +
            func.coalesce(func.sum(Miasto.miasto_populacja), 0)
        )

        # ===== BAZOWE ZAPYTANIE =====

        query = (
            db.session.query(
                Region.region_id,
                Region.region_nazwa,
                Region.region_ludnosc_pozamiejska,

                Panstwo.panstwo_nazwa,

                region_pop_expr.label("region_populacja_calc")
            )
            .join(
                Panstwo,
                Region.panstwo_id == Panstwo.PANSTWO_ID
            )
            .outerjoin(
                Miasto,
                Miasto.region_id == Region.region_id
            )
            .group_by(
                Region.region_id,
                Region.region_nazwa,
                Region.region_ludnosc_pozamiejska,
                Panstwo.panstwo_nazwa
            )
        )

        if panstwo_nazwa:
            query = query.filter(
                Panstwo.panstwo_nazwa.like(f"%{panstwo_nazwa}%")
            )

        if region_nazwa:
            query = query.filter(
                Region.region_nazwa.like(f"%{region_nazwa}%")
            )
        
        if region_id and region_id.isdigit():
            query = query.filter(Region.region_id == int(region_id))

        if kontynent:
            query = query.filter(Panstwo.kontynent_id == kontynent)

        if panstwo_id and panstwo_id.isdigit():
            query = query.filter(Region.panstwo_id == int(panstwo_id))

        if populacja_od and populacja_od.isdigit():
            query = query.having(
                region_pop_expr >= int(populacja_od)
            )

        if populacja_do and populacja_do.isdigit():
            query = query.having(
                region_pop_expr <= int(populacja_do)
            )

        if uksztaltowanie and uksztaltowanie.isdigit():
            query = query.filter(
                Region.region_teren_id == int(uksztaltowanie)
            )

        if polkula:
            query = query.filter(Region.polkula == polkula)


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
            infra_porty,
            bez_stolicy,
            region_id
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

        if bez_stolicy:

            query = query.filter(
                ~Region.miasta.any(
                    Miasto.miasto_typ_id.in_([1, 2])
                )
            )

        if any_filter:
            query = query.order_by(
                region_pop_expr.desc()
            )
        else:
            query = query.order_by(
                Region.region_id.asc()
            )

        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        rows = pagination.items

        results = [
            {
                "region_id": region_id,

                "region_nazwa": region_nazwa,

                "region_populacja": region_pop_calc or 0,

                "region_ludnosc_pozamiejska":
                    region_ludnosc_pozamiejska or 0,

                "panstwo_nazwa": panstwo_nazwa,
            }

            for (
                region_id,
                region_nazwa,
                region_ludnosc_pozamiejska,
                panstwo_nazwa,
                region_pop_calc
            ) in rows
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
            region_id=region_id,
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
            polkula = request.form.get("polkula")

            # ===== WALIDACJA PODSTAWOWA =====
            if request.form.get("terytorium_zamorskie", "NIE") not in ("TAK", "NIE"):
                errors.append("Nieprawidłowa wartość pola Terytorium zamorskie.")
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
                "region_zanieczyszczenie_powietrza",
                "region_degradacja_srodowiska",
            ]

            DECIMAL_FIELDS = [
                "roczny_przyrost_miasto_pct",
                "roczny_przyrost_wies_pct",
                "roczna_urbanizacja_pct",
            ]

            decimal_values = {}

            for field in DECIMAL_FIELDS:

                val = request.form.get(field)

                if val == "" or val is None:
                    decimal_values[field] = None

                else:
                    try:
                        parsed = float(val)

                        if -100 <= parsed <= 100:
                            decimal_values[field] = parsed
                        else:
                            errors.append(
                                f"Wartość pola {field} musi być w zakresie -100 do 100."
                            )

                    except ValueError:
                        errors.append(
                            f"Wartość pola {field} musi być liczbą."
                        )

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
            
            polkula_val = request.form.get("polkula")

            # ===== UTWORZENIE REGIONU =====
            new_region = Region(
                region_nazwa=nazwa,
                terytorium_zamorskie=request.form.get("terytorium_zamorskie", "NIE") == "TAK",
                panstwo_id=panstwo_id,
                region_teren_id=region_teren_id or None,
                region_polozenie_id=region_polozenie_id or None,
                region_typ_nadrz_id=region_typ_nadrz_id or None,
                region_typ_podrz_id=region_typ_podrz_id or None,
                polkula=polkula_val if polkula_val in ("NORTH", "SOUTH") else None,
            )

            for field, value in int_values.items():
                setattr(new_region, field, value)
            
            for field, value in decimal_values.items():
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
            polkula=None,
            event_changes=changes_map
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

        # ==========================================
        # ZASOBY NATURALNE
        # ==========================================

        zasoby = (
            db.session.query(
                RegionZasob,
                DictZasob
            )
            .join(
                DictZasob,
                RegionZasob.zasob_id == DictZasob.zasob_id
            )
            .filter(
                RegionZasob.region_id == region.region_id
            )
            .order_by(DictZasob.zasob_nazwa)
            .all()
        )

        # ==========================================
        # BUDŻET
        # ==========================================

        budzet = (
            RegionBudzet.query
            .filter_by(region_id=region.region_id)
            .order_by(RegionBudzet.rok.desc())
            .first()
        )

        # ==========================================
        # INFRASTRUKTURA
        # ==========================================

        infrastruktura = (
            db.session.query(
                RegionInfrastruktura,
                DictInfrastruktura
            )
            .join(
                DictInfrastruktura,
                RegionInfrastruktura.budynek_id == DictInfrastruktura.budynek_id
            )
            .filter(
                RegionInfrastruktura.region_id == region.region_id
            )
            .order_by(DictInfrastruktura.budynek_nazwa)
            .all()
        )

        # ==========================================
        # MAGAZYNY
        # ==========================================

        magazyny = (
            db.session.query(
                RegionMagazyn,
                DictZasob
            )
            .join(
                DictZasob,
                RegionMagazyn.zasob_id == DictZasob.zasob_id
            )
            .filter(
                RegionMagazyn.region_id == region.region_id
            )
            .order_by(DictZasob.zasob_nazwa)
            .all()
        )

        # ==========================================
        # PRODUKCJA
        # ==========================================

        magazyn_lookup = {
            mag.RegionMagazyn.zasob_id: mag.RegionMagazyn.zasob_ilosc
            for mag in magazyny
        }

        produkcja = []

        for infra, budynek in infrastruktura:

            receptury = (
                BudynekProdukcja.query
                .filter_by(
                    budynek_id=budynek.budynek_id
                )
                .all()
            )

            for rec in receptury:

                if not rec.ilosc_wejsciowa:
                    continue

                dostepne = magazyn_lookup.get(
                    rec.zasob_wejsciowy_id,
                    0
                )

                mozliwa_produkcja = (
                    dostepne /
                    float(rec.ilosc_wejsciowa)
                )

                limit_budynku = (
                    float(rec.max_produkcja_miesieczna)
                    * infra.budynek_poziom
                    * (infra.budynek_sprawnosc / 100)
                )

                wynik = min(
                    mozliwa_produkcja,
                    limit_budynku
                )

                produkt = DictZasob.query.get(
                    rec.zasob_wyjsciowy_id
                )

                if produkt:

                    produkcja.append({
                        "budynek": budynek.budynek_nazwa,
                        "produkt": produkt.zasob_nazwa,
                        "jednostka": produkt.zasob_jednostka,
                        "ilosc": round(wynik, 2)
                    })

        if request.method == "POST":

            nazwa = request.form.get("region_nazwa")
            panstwo_id = request.form.get("panstwo_id")

            region_teren_id = request.form.get("region_teren_id")
            region_polozenie_id = request.form.get("region_polozenie_id")
            region_typ_nadrz_id = request.form.get("region_typ_nadrz_id")
            region_typ_podrz_id = request.form.get("region_typ_podrz_id")
            
            polkula = request.form.get("polkula")
            region.polkula = polkula if polkula in ("NORTH", "SOUTH") else None

            # ===== WALIDACJA =====
            errors = []

            if request.form.get("terytorium_zamorskie", "NIE") not in ("TAK", "NIE"):
                errors.append("Nieprawidłowa wartość pola Terytorium zamorskie.")
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
                "region_zanieczyszczenie_powietrza",
                "region_degradacja_srodowiska"
            ]

            DECIMAL_FIELDS = [
                "roczny_przyrost_miasto_pct",
                "roczny_przyrost_wies_pct",
                "roczna_urbanizacja_pct",
            ]

            decimal_values = {}

            for field in DECIMAL_FIELDS:

                val = request.form.get(field)

                if val == "" or val is None:
                    decimal_values[field] = None

                else:
                    try:
                        parsed = float(val)

                        if -100 <= parsed <= 100:
                            decimal_values[field] = parsed
                        else:
                            errors.append(
                                f"Wartość pola {field} musi być w zakresie -100 do 100."
                            )

                    except ValueError:
                        errors.append(
                            f"Wartość pola {field} musi być liczbą."
                        )

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
                    zasoby=zasoby,
                    budzet=budzet,
                    infrastruktura=infrastruktura,
                    magazyny=magazyny,
                    produkcja=produkcja
                )

            # ===== KONWERSJE =====
            panstwo_id = int(panstwo_id)

            # ===== AKTUALIZACJA PODSTAWOWA =====
            region.terytorium_zamorskie = request.form.get("terytorium_zamorskie", "NIE") == "TAK"
            region.region_nazwa = nazwa
            region.panstwo_id = panstwo_id
            region.region_teren_id = request.form.get("region_teren_id") or None
            region.region_polozenie_id = request.form.get("region_polozenie_id") or None
            region.region_typ_nadrz_id = request.form.get("region_typ_nadrz_id") or None
            region.region_typ_podrz_id = request.form.get("region_typ_podrz_id") or None

            for field, value in int_values.items():
                setattr(region, field, value)
            
            for field, value in decimal_values.items():
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
                        zasoby=zasoby,
                        budzet=budzet,
                        infrastruktura=infrastruktura,
                        magazyny=magazyny,
                        produkcja=produkcja
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
                        zasoby=zasoby,
                        budzet=budzet,
                        infrastruktura=infrastruktura,
                        magazyny=magazyny,
                        produkcja=produkcja
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
            zasoby=zasoby,
            budzet=budzet,
            infrastruktura=infrastruktura,
            magazyny=magazyny,
            produkcja=produkcja
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
        miasta = region.miasta
        back_url = request.referrer

        events = (
            Zdarzenie.query
            .filter(Zdarzenie.region_id == region.region_id,
                    Zdarzenie.zdarzenie_typ != "nowa_ustawa",
                    Zdarzenie.status != "archiwalne",
                    Zdarzenie.status != "zakonczone"
            )
            .order_by(Zdarzenie.data_entenda.desc())
            .limit(50)
            .all()
        )

        # ==========================================
        # ZASOBY NATURALNE
        # ==========================================

        zasoby = (
            db.session.query(
                RegionZasob,
                DictZasob
            )
            .join(
                DictZasob,
                RegionZasob.zasob_id == DictZasob.zasob_id
            )
            .filter(
                RegionZasob.region_id == region.region_id
            )
            .order_by(DictZasob.zasob_nazwa)
            .all()
        )

        # ==========================================
        # BUDŻET
        # ==========================================

        budzet = (
            RegionBudzet.query
            .filter_by(region_id=region.region_id)
            .order_by(RegionBudzet.rok.desc())
            .first()
        )

        # ==========================================
        # INFRASTRUKTURA
        # ==========================================

        infrastruktura = (
            db.session.query(
                RegionInfrastruktura,
                DictInfrastruktura
            )
            .join(
                DictInfrastruktura,
                RegionInfrastruktura.budynek_id == DictInfrastruktura.budynek_id
            )
            .filter(
                RegionInfrastruktura.region_id == region.region_id
            )
            .order_by(DictInfrastruktura.budynek_nazwa)
            .all()
        )

        # ==========================================
        # MAGAZYNY
        # ==========================================

        magazyny = (
            db.session.query(
                RegionMagazyn,
                DictZasob
            )
            .join(
                DictZasob,
                RegionMagazyn.zasob_id == DictZasob.zasob_id
            )
            .filter(
                RegionMagazyn.region_id == region.region_id
            )
            .order_by(DictZasob.zasob_nazwa)
            .all()
        )

        social_changes = (
            SpoleczenstwoStateHistory.query
            .filter(
                SpoleczenstwoStateHistory.event_id.in_(
                    [e.zdarzenie_id for e in events]
                )
            )
            .all()
        )

        changes = (
            RegionStateHistory.query
            .filter(
                RegionStateHistory.event_id.in_(
                    [e.zdarzenie_id for e in events]
                )
            )
            .all()
        )

        changes_map = {}

        for c in changes:

            delta = []

            def add(name, old, new, suffix=""):
                if old is None or new is None:
                    return

                diff = new - old

                if diff != 0:
                    delta.append({
                        "label": name,
                        "value": diff,
                        "suffix": suffix
                    })

            add("Ludność", c.old_ludnosc, c.new_ludnosc)

            add("Drogi", c.old_drogi, c.new_drogi)
            add("Kolej", c.old_kolej, c.new_kolej)
            add("Energia", c.old_energia, c.new_energia)
            add("Mieszkania", c.old_mieszkania, c.new_mieszkania)
            add("Porty", c.old_porty, c.new_porty)

            add(
                "Degradacja środowiska",
                c.old_degradacja_srodowiska,
                c.new_degradacja_srodowiska
            )

            add(
                "Zanieczyszczenie powietrza",
                c.old_zanieczyszczenie_powietrza,
                c.new_zanieczyszczenie_powietrza
            )

            changes_map[c.event_id] = delta
        
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

        # ==========================================
        # PRODUKCJA
        # ==========================================

        magazyn_lookup = {
            m.RegionMagazyn.zasob_id: m.RegionMagazyn.zasob_ilosc
            for m in magazyny
        }

        produkcja = []

        for infra, budynek in infrastruktura:

            receptury = (
                BudynekProdukcja.query
                .filter_by(
                    budynek_id=budynek.budynek_id
                )
                .all()
            )

            for rec in receptury:

                dostepne = magazyn_lookup.get(
                    rec.zasob_wejsciowy_id,
                    0
                )

                if rec.ilosc_wejsciowa <= 0:
                    continue

                mozliwa_produkcja = (
                    dostepne / float(rec.ilosc_wejsciowa)
                )

                limit_budynku = (
                    float(rec.max_produkcja_miesieczna)
                    * infra.budynek_poziom
                    * (infra.budynek_sprawnosc / 100)
                )

                wynik = min(
                    mozliwa_produkcja,
                    limit_budynku
                )

                produkt = DictZasob.query.get(
                    rec.zasob_wyjsciowy_id
                )

                produkcja.append({
                    "budynek": budynek.budynek_nazwa,
                    "produkt": produkt.zasob_nazwa,
                    "jednostka": produkt.zasob_jednostka,
                    "ilosc": round(wynik, 2)
                })

        from routes_region_secession import form_context
        sovereignty_context = form_context(region)
        return render_template(
            "region_form.html",
            **sovereignty_context,
            region=region,
            panstwo=panstwo,
            miasta=miasta,
            events=events,
            back_url=back_url,
            zasoby=zasoby,
            budzet=budzet,
            infrastruktura=infrastruktura,
            magazyny=magazyny,
            produkcja=produkcja,
            event_changes=changes_map
        )
    
    @app.route("/api/regiony_meta")
    def api_regiony_meta():

        regions = (
            Region.query
            .options(
                selectinload(Region.miasta),
                selectinload(Region.teren),
                selectinload(Region.panstwo)
            )
            .all()
        )

        result = {}

        for r in regions:

            infra_values = []

            if r.region_stan_infra_drogowej is not None:
                infra_values.append(r.region_stan_infra_drogowej)

            if r.region_stan_infra_kolejowej is not None:
                infra_values.append(r.region_stan_infra_kolejowej)

            if r.region_stan_infra_energetycznej is not None:
                infra_values.append(r.region_stan_infra_energetycznej)

            if r.region_stan_infra_mieszkalnej is not None:
                infra_values.append(r.region_stan_infra_mieszkalnej)

            if r.region_poziom_skomunikowania is not None:
                infra_values.append(r.region_poziom_skomunikowania)
            
            if r.region_ryzyko_powodzi is not None:
                infra_values.append(r.region_ryzyko_powodzi)
            
            if r.region_ryzyko_lawin is not None:
                infra_values.append(r.region_ryzyko_lawin)

            # region wewnętrzny -> bez portów
            if (
                r.region_polozenie_id != 1
                and r.region_stan_infra_portowej is not None
            ):
                infra_values.append(r.region_stan_infra_portowej)

            infra_avg = (
                round(sum(infra_values) / len(infra_values), 1)
                if infra_values else 0
            )

            growth_values = []

            if r.roczny_przyrost_miasto_pct is not None:
                growth_values.append(float(r.roczny_przyrost_miasto_pct))

            if r.roczny_przyrost_wies_pct is not None:
                growth_values.append(float(r.roczny_przyrost_wies_pct))

            growth_avg = (
                round(sum(growth_values) / len(growth_values), 2)
                if growth_values else 0
            )

            city_population = sum(
                (m.miasto_populacja or 0)
                for m in r.miasta
            )

            urbanizacja = 0

            if r.region_populacja and r.region_populacja > 0:
                urbanizacja = round(
                    (city_population / r.region_populacja) * 100,
                    1
                )

            result[r.region_id] = {
                "region_id": r.region_id,
                "panstwo_id": r.panstwo_id,
                "nazwa": r.region_nazwa,
                "panstwo_nazwa": (
                    r.panstwo.panstwo_nazwa
                    if r.panstwo else ""
                ),
                "populacja": r.region_populacja,
                "urbanizacja": urbanizacja,
                "przyrost_ludnosci": growth_avg,
                "poziom_infrastruktury": infra_avg,

                "infra_portowa": r.region_stan_infra_portowej or 0,
                "infra_drogowa": r.region_stan_infra_drogowej or 0,
                "infra_kolejowa": r.region_stan_infra_kolejowej or 0,
                "infra_energetyczna": r.region_stan_infra_energetycznej or 0,

                "ryzyko_mrozu": r.region_ryzyko_mrozu or 0,
                "ryzyko_upalu": r.region_ryzyko_upalu or 0,
                "sejsmicznosc": r.region_sejsmicznosc or 0,
                "poziom_skomunikowania": r.region_poziom_skomunikowania or 0,
                "ryzyko_powodzi": r.region_ryzyko_powodzi or 0,
                "ryzyko_lawin": r.region_ryzyko_lawin or 0,

                "polkula": r.polkula or "",

                "teren": (
                    r.teren.nazwa.lower()
                    if r.teren and r.teren.nazwa
                    else ""
                ),

                "typ_nadrz_id": r.region_typ_nadrz_id,
                "typ_podrz_id": r.region_typ_podrz_id,

                "typ_nadrz_nazwa":
                    r.typ_nadrz.nazwa if r.typ_nadrz else None,

                "typ_podrz_nazwa":
                    r.typ_podrz.nazwa if r.typ_podrz else None,
            }

        return jsonify(result)

    @app.route("/api/mapa/typy-regionow")
    def api_typy_regionow():

        nadrzedne = (
            DictRegionTyp.query
            .filter_by(poziom="NADRZ")
            .order_by(DictRegionTyp.nazwa)
            .all()
        )

        podrzedne = (
            DictRegionTyp.query
            .filter_by(poziom="PODRZ")
            .order_by(DictRegionTyp.nazwa)
            .all()
        )

        return jsonify({
            "nadrzedne": [
                {
                    "id": x.id,
                    "nazwa": x.nazwa
                }
                for x in nadrzedne
            ],
            "podrzedne": [
                {
                    "id": x.id,
                    "nazwa": x.nazwa
                }
                for x in podrzedne
            ]
        })
            


            

