from flask import (
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify
)

from extensions import db
from models import Panstwo, Region, Miasto, DictKontynent, Spoleczenstwo, DictMiastoTyp
from permissions import wymaga_roli
from sqlalchemy import func
from services.demografia_ludnosc import licz_dane_kontynentu
import random
from datetime import datetime


def init_demografia_routes(app):

    # ============================================================
    # KALKULATOR DEMOGRAFICZNY
    # ============================================================

    @app.route("/demografia/kalkulator", methods=["GET"])
    def demografia_kalkulator():

        kontynent = request.args.get("kontynent", type=int)
        panstwo_id = request.args.get("panstwo_id", type=int)

        kontynenty = (
            DictKontynent.query
            .order_by(DictKontynent.kontynent_nazwa)
            .all()
        )

        panstwa = []
        panstwo = None
        regiony = None

        if kontynent:
            panstwa = (
                Panstwo.query
                .filter_by(kontynent_id=kontynent)
                .order_by(Panstwo.panstwo_nazwa)
                .all()
            )

        if panstwo_id:
            panstwo = Panstwo.query.get(int(panstwo_id))
            if panstwo:
                    regiony = (
                        db.session.query(
                            Region.region_id,
                            Region.region_nazwa,

                            Region.region_ludnosc_pozamiejska,

                            func.coalesce(
                                func.sum(Miasto.miasto_populacja), 0
                            ).label("ludnosc_miejska"),

                            (
                                Region.region_ludnosc_pozamiejska +
                                func.coalesce(func.sum(Miasto.miasto_populacja), 0)
                            ).label("region_populacja")

                        )
                        .outerjoin(Miasto, Miasto.region_id == Region.region_id)
                        .filter(Region.panstwo_id == panstwo.PANSTWO_ID)
                        .group_by(
                            Region.region_id,
                            Region.region_nazwa,
                            Region.region_ludnosc_pozamiejska
                        )
                        .order_by(Region.region_nazwa)
                        .all()
                    )
                        

        return render_template(
            "demografia_kalkulator.html",
            kontynenty=kontynenty,
            panstwa=panstwa,
            selected_kontynent=kontynent,
            panstwo=panstwo,
            regiony=regiony
        )

    # ============================================================
    # GENERATOR MIAST TECHNICZNYCH
    # ============================================================

    @app.route("/demografia/generator_miast", methods=["GET", "POST"])
    @wymaga_roli("wszechmocny")
    def demografia_generator_miast():

        kontynenty = (
            DictKontynent.query
            .order_by(DictKontynent.kontynent_nazwa)
            .all()
        )

        if request.method == "POST":

            kontynent = request.form.get("kontynent_id")
            panstwo_id = request.form.get("panstwo_id")
            
            confirm = request.form.get("confirm")

            errors = []

            if not kontynent or not panstwo_id:
                return render_template(
                    "demografia_generator.html",
                    error="Musisz wybrać kontynent i państwo.",
                    kontynenty=kontynenty,
                    regiony=regiony
                )

            regiony = Region.query.filter_by(
                panstwo_id=int(panstwo_id)
            ).all()

            zadania = []
            laczna_ilosc_miast = 0

            for region in regiony:

                ilosc = request.form.get(
                    f"ilosc_{region.region_id}",
                    "0"
                )

                min_pop = request.form.get(
                    f"min_pop_{region.region_id}",
                    "0"
                )

                max_pop = request.form.get(
                    f"max_pop_{region.region_id}",
                    "0"
                )

                if not ilosc.isdigit():
                    continue

                ilosc = int(ilosc)

                if ilosc <= 0:
                    continue

                if not min_pop.isdigit() or not max_pop.isdigit():
                    continue
                
                if int(min_pop) > int(max_pop):
                    return render_template(
                        "demografia_generator.html",
                        error=(
                            f"Region {region.region_nazwa}: "
                            "minimalna ludność nie może być większa od maksymalnej."
                        ),
                        form_data=request.form,
                        kontynenty=kontynenty,
                        regiony=regiony
                    )

                zadania.append({
                    "region": region,
                    "ilosc": ilosc,
                    "min_pop": int(min_pop),
                    "max_pop": int(max_pop)
                })

                laczna_ilosc_miast += ilosc
            
            if not zadania:
                return render_template(
                    "demografia_generator.html",
                    error="Nie podano żadnych regionów do generowania.",
                    form_data=request.form,
                    kontynenty=kontynenty,
                    regiony=regiony
                )

            if laczna_ilosc_miast > 100:
                return render_template(
                    "demografia_generator.html",
                    error="Nie można wygenerować więcej niż 100 miast za jednym razem.",
                    form_data=request.form,
                    kontynenty=kontynenty,
                    regiony=regiony
                )

            if laczna_ilosc_miast > 50 and confirm is None:
                return render_template(
                    "demografia_generator.html",
                    warning=(
                        f"Zamierzasz wygenerować "
                        f"{laczna_ilosc_miast} miast. "
                        "Czy chcesz kontynuować?"
                    ),
                    confirm_required=True,
                    form_data=request.form,
                    kontynenty=kontynenty,
                    regiony=regiony
                )

            if confirm == "no":
                return render_template(
                    "demografia_generator.html",
                    info="Anulowano generowanie miast.",
                    form_data=request.form,
                    kontynenty=kontynenty,
                    regiony=regiony
                )

            try:
                typ_miasto = DictMiastoTyp.query.filter_by(
                    miasto_typ_nazwa="miasto"
                ).first()

                if not typ_miasto:
                    raise RuntimeError(
                        "Brak typu miasta 'miasto' w dict_miasto_typ"
                    )

                for zadanie in zadania:

                    region = zadanie["region"]

                    populacje = [
                        random.randint(
                            zadanie["min_pop"],
                            zadanie["max_pop"]
                        )
                        for _ in range(zadanie["ilosc"])
                    ]

                    suma_pop = sum(populacje)

                    region.region_ludnosc_pozamiejska -= suma_pop

                    for pop in populacje:

                        while True:
                            suffix = random.randint(0, 999_999_999)
                            nazwa = f"Miasto Techniczne {suffix:09d}"

                            if not Miasto.query.filter_by(
                                miasto_nazwa=nazwa
                            ).first():
                                break

                        miasto = Miasto(
                            miasto_nazwa=nazwa,
                            miasto_populacja=pop,
                            panstwo_id=region.panstwo_id,
                            region_id=region.region_id,
                            miasto_typ_id=typ_miasto.miasto_typ_id,
                            czy_na_mapie="NIE",
                            czy_generowane="TAK"
                        )

                        db.session.add(miasto)

                db.session.commit()

                flash(
                    f"Wygenerowano łącznie {laczna_ilosc_miast} miast technicznych.",
                    "success"
                )
                return redirect(url_for("demografia_generator_miast"))

            except Exception as e:
                db.session.rollback()
                return render_template(
                    "demografia_generator.html",
                    error=f"Błąd zapisu do bazy: {e}",
                    kontynenty=kontynenty,
                    regiony=regiony
                )

        return render_template(
            "demografia_generator.html",
            kontynenty=kontynenty
        )
    
    # ============================================================
    # PODSUMOWANIE LUDNOŚCI (KONTYNENT / PAŃSTWO)
    # ============================================================

    @app.route("/demografia/ludnosc", methods=["GET"])
    def demografia_ludnosc():

        kontynent = request.args.get("kontynent_id", type=int)
        panstwo_id = request.args.get("panstwo_id", type=int)

        # lista kontynentów
        kontynenty = (
            DictKontynent.query
            .order_by(DictKontynent.kontynent_nazwa)
            .all()
        )

        # lista państw (jeśli wybrano kontynent)
        panstwa = []
        if kontynent:
            panstwa = (
                Panstwo.query
                .filter(Panstwo.kontynent_id == kontynent)
                .order_by(Panstwo.panstwo_nazwa)
                .all()
            )

        dane = None
        tryb = None

        if kontynent and not panstwo_id:
            dane = licz_dane_kontynentu(kontynent)
            tryb = "kontynent"

        elif kontynent and panstwo_id:
            dane = licz_dane_panstwa(panstwo_id)
            tryb = "panstwo"

        return render_template(
            "demografia_ludnosc.html",
            kontynenty=kontynenty,
            panstwa=panstwa,
            selected_kontynent=kontynent,
            selected_panstwo_id=panstwo_id,
            dane=dane,
            tryb=tryb
        )

    @app.route("/demografia/kalkulator/<int:panstwo_id>/zapisz", methods=["POST"])
    def demografia_kalkulator_zapisz(panstwo_id):

        data = request.get_json()

        if not data or "regions" not in data:
            return jsonify(
                success=False,
                error="Brak danych regionów"
            ), 400

        try:

            # ─────────────────────────────────────────
            # AKTUALIZACJA REGIONÓW
            # ─────────────────────────────────────────

            for r in data["regions"]:

                region_id = r.get("region_id")

                if not region_id:
                    raise ValueError("Brak region_id w payloadzie")

                region = Region.query.get(region_id)

                if not region:
                    raise ValueError(
                        f"Region ID {region_id} nie istnieje"
                    )

                pop_pozam = int(
                    r.get("region_ludnosc_pozamiejska", 0)
                )

                if pop_pozam < 0:
                    raise ValueError(
                        f"Ludność pozamiejska regionu "
                        f"(ID {region_id}) nie może być ujemna"
                    )

                region.region_ludnosc_pozamiejska = pop_pozam

            # ważne:
            db.session.flush()

            # ─────────────────────────────────────────
            # PRZELICZENIE POPULACJI PAŃSTWA
            # ─────────────────────────────────────────

            panstwo = Panstwo.query.get_or_404(panstwo_id)

            total_population = sum(
                region.region_populacja
                for region in panstwo.regiony
            )

            if panstwo.panstwo_populacja != total_population:

                panstwo.panstwo_populacja = total_population
                panstwo.panstwo_populacja_audit = datetime.now()

            db.session.commit()

            return jsonify(
                success=True,
                panstwo_populacja=total_population
            )

        except Exception as e:

            db.session.rollback()

            return jsonify(
                success=False,
                error=str(e)
            ), 500


    def licz_dane_panstwa(panstwo_id):

        p = Panstwo.query.get_or_404(panstwo_id)

        regiony = (
            Region.query
            .filter(Region.panstwo_id == panstwo_id)
            .all()
        )

        liczba_regionow = len(regiony)

        populacja = p.panstwo_populacja or 0
        powierzchnia = p.panstwo_powierzchnia or 0

        gestosc = (
            round(populacja / powierzchnia, 2)
            if powierzchnia else 0
        )

        liczba_miast = (
            Miasto.query
            .filter_by(panstwo_id=panstwo_id)
            .count()
        )

        ludnosc_miejska = (
            db.session.query(
                func.coalesce(
                    func.sum(Miasto.miasto_populacja),
                    0
                )
            )
            .filter(Miasto.panstwo_id == panstwo_id)
            .scalar()
        )

        urbanizacja = (
            round((ludnosc_miejska / populacja) * 100, 2)
            if populacja else 0
        )

        srednia_region = (
            round(populacja / liczba_regionow)
            if liczba_regionow else 0
        )

        top_miasta = (
            Miasto.query
            .filter_by(panstwo_id=panstwo_id)
            .order_by(Miasto.miasto_populacja.desc())
            .limit(3)
            .all()
        )

        return {
            "nazwa": p.panstwo_nazwa,

            "populacja": populacja,

            "powierzchnia": powierzchnia,

            "gestosc": gestosc,

            "liczba_regionow": liczba_regionow,

            "regiony": [
                {
                    "nazwa": r.region_nazwa,
                    "populacja": r.region_populacja
                }
                for r in regiony
            ],

            "liczba_miast": liczba_miast,

            "urbanizacja_pct": urbanizacja,

            "srednia_region": srednia_region,

            "top_miasta": [
                {
                    "miasto_nazwa": m.miasto_nazwa,
                    "miasto_populacja": m.miasto_populacja
                }
                for m in top_miasta
            ]
        }
    
    @app.route("/api/regiony_by_panstwo")
    def api_regiony_by_panstwo():
        panstwo_id = request.args.get("panstwo_id", type=int)
        if not panstwo_id:
            return jsonify([])

        regiony = (
            Region.query
            .filter_by(panstwo_id=int(panstwo_id))
            .order_by(Region.region_nazwa)
            .all()
        )

        return jsonify([
            {
                "region_id": r.region_id,
                "region_nazwa": r.region_nazwa,
                "region_ludnosc_pozamiejska":
                    r.region_ludnosc_pozamiejska or 0
            }
            for r in regiony
        ])

########################################################################

                        ### SPOŁECZEŃSTWO ###

########################################################################

    @app.route("/demografia/spoleczenstwo")
    def demografia_spoleczenstwo_lista():

        kontynent = request.args.get("kontynent", "").strip()
        panstwo_q = request.args.get("panstwo_id", "").strip()

        # 1. query
        query = db.session.query(Panstwo)

        if kontynent and kontynent.isdigit():
            query = query.filter(Panstwo.kontynent_id == int(kontynent))

        if panstwo_q:
            if panstwo_q.isdigit():
                query = query.filter(Panstwo.PANSTWO_ID == int(panstwo_q))
            else:
                query = query.filter(Panstwo.panstwo_nazwa.ilike(f"%{panstwo_q}%"))

        # 2. wynik
        panstwa = query.order_by(Panstwo.panstwo_nazwa).all()

        # 3. dane społeczeństwa (dopiero teraz!)
        spoleczenstwa = {
            s.panstwo_id: s
            for s in Spoleczenstwo.query.filter(
                Spoleczenstwo.panstwo_id.in_([p.PANSTWO_ID for p in panstwa])
            ).all()
        }

        def has_missing(s):
            if not s:
                return True
            return any(v is None for v in [
                s.stabilnosc_spoleczna, s.zadowolenie_spoleczne, s.nierownosci_spoleczne,
                s.poziom_edukacji, s.swiadomosc_spoleczna, s.zaufanie_do_wladzy,
                s.napiecia_religijne, s.napiecia_etniczne, s.napiecia_klasowe,
                s.przestepczosc, s.radykalizacja_spoleczna,
                s.spojnosc_spoleczna, s.tozsamosc_narodowa,
                s.konserwatyzm_spoleczny, s.otwartosc_spoleczna, s.spozycie_alkoholu, s.spozycie_narkotykow, s.zdrowie_publiczne
            ])

        missing_map = {
            p.PANSTWO_ID: has_missing(spoleczenstwa.get(p.PANSTWO_ID))
            for p in panstwa
        }

        # 4. słowniki
        kontynenty = DictKontynent.query.order_by(DictKontynent.kontynent_nazwa).all()
        panstwa_all = Panstwo.query.order_by(Panstwo.panstwo_nazwa).all()

        return render_template(
            "demografia_spoleczenstwo_lista.html",
            panstwa=panstwa,
            kontynenty=kontynenty,
            panstwa_all=panstwa_all,
            missing_map=missing_map,
            kontynent_selected=kontynent
        )

    @app.route("/demografia/spoleczenstwo/<int:panstwo_id>")
    def demografia_spoleczenstwo_form(panstwo_id):

        kontynent = request.args.get("kontynent", "")

        panstwo = Panstwo.query.get_or_404(panstwo_id)
        s = Spoleczenstwo.query.filter_by(panstwo_id=panstwo_id).first()

        return render_template(
            "demografia_spoleczenstwo_form.html",
            panstwo=panstwo,
            s=s,
            kontynent=kontynent
        )
    
    @app.route("/demografia/spoleczenstwo/<int:panstwo_id>/edit", methods=["GET", "POST"])
    @wymaga_roli("wszechmocny")
    def demografia_spoleczenstwo_edit(panstwo_id):

        panstwo = Panstwo.query.get_or_404(panstwo_id)
        kontynent = request.args.get("kontynent", "")
        s = Spoleczenstwo.query.filter_by(panstwo_id=panstwo_id).first()

        if request.method == "POST":

            if not s:
                s = Spoleczenstwo(panstwo_id=panstwo_id)
                db.session.add(s)

            fields = [
                "stabilnosc_spoleczna", "zadowolenie_spoleczne", "nierownosci_spoleczne",
                "poziom_edukacji", "swiadomosc_spoleczna", "zaufanie_do_wladzy",
                "napiecia_religijne", "napiecia_etniczne", "napiecia_klasowe",
                "przestepczosc", "radykalizacja_spoleczna",
                "spojnosc_spoleczna", "tozsamosc_narodowa",
                "konserwatyzm_spoleczny", "otwartosc_spoleczna", "spozycie_narkotykow", "spozycie_alkoholu", "zdrowie_publiczne"
            ]

            for f in fields:
                val = request.form.get(f)

                if val is None or val == "":
                    setattr(s, f, None)
                    continue

                if not val.isdigit():
                    setattr(s, f, None)
                    continue

                val = int(val)

                # WALIDACJA 0–100
                if val < 0 or val > 100:
                    setattr(s, f, None)
                else:
                    setattr(s, f, val)

            db.session.commit()

            return redirect(url_for(
                "demografia_spoleczenstwo_form",
                panstwo_id=panstwo_id,
                kontynent=kontynent
            ))

        return render_template(
            "demografia_spoleczenstwo_form_edit.html",
            panstwo=panstwo,
            kontynent=kontynent,
            s=s
        )


