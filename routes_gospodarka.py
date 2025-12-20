from flask import render_template, flash, redirect, url_for, request, jsonify
from extensions import db
from models import Panstwo, Gospodarka
from permissions import wymaga_roli


def format_num(x):
    try:
        return f"{int(x):,}".replace(",", " ")
    except:
        return str(x)

def init_gospodarka_routes(app):

    # --- LISTA PAŃSTW ---

    
    # --- WYŚWIETLENIE FORMULARZA DANYCH GOSPODARCZYCH
    @app.route("/gospodarka_form/<int:panstwo_id>", methods=["GET", "POST"])
    def gospodarka_form(panstwo_id):

        # pobierz państwo
        panstwo = Panstwo.query.get_or_404(panstwo_id)

        # pobierz istniejące dane gospodarcze (lub None)
        gosp = Gospodarka.query.filter_by(panstwo_id=panstwo_id).first()

        if request.method == "POST":
            form = request.form

            # jeśli brak → dodaj nowe
            if not gosp:
                gosp = Gospodarka(panstwo_id=panstwo_id)
                db.session.add(gosp)

            # lista pól w modelu
            fields = [
                "wzrost_pkb", "bezrobocie",
                "sektor_uslugi_pct", "sektor_przemysl_pct", "sektor_rolnictwo_pct",
                "eksport_wartosc", "import_wartosc",
                "ropa_wydobycie", "gaz_wydobycie", "wegiel_wydobycie",
                "uran_wydobycie", "zloto_wydobycie",
                "kerbit_wydobycie", "natsyt_wydobycie", "cemium_wydobycie",
                "technologie_wartosc_prod", "uzbrojenie_wartosc_prod",
                "budownictwo_wartosc_prod", "przemysl_ciezki_wartosc_prod",
                "przemysl_lekki_wartosc_prod", "produkcja_zywnosci_wartosc_prod",
                "uslugi_finansowe_wartosc_prod", "przemysl_farmaceut_wartosc_prod",
                "przemysl_samochodowy_wartosc_prod", "przemysl_rozrywkowy_wartosc_prod",
                "dlug_pct_pkb",
                "energia_nieodnawialne_pct", "energia_odnawialne_pct", "energia_atomowa_pct",
                "indeks_stabilnosci_gosp", "indeks_korupcji_gosp",
                "indeks_innowacji_gosp", "indeks_rozwoju_ludzkiego",
            ]

            # przypisywanie wartości
            for field in fields:
                setattr(gosp, field, form.get(field) or None)

            db.session.commit()

            flash("Dane gospodarcze zostały zapisane.", "success")

            return redirect(url_for("gospodarka_form", panstwo_id=panstwo_id))

        # GET → wyświetlenie
        return render_template(
            "gospodarka_form.html",
            panstwo=panstwo,
            g=gosp
        )
    
     # --- FORULARZ EDYCJI DANYCH GOSPODARCZYCH
    @app.route("/gospodarka/<int:panstwo_id>/edit", methods=["GET", "POST"])
    @wymaga_roli("wszechmocny")
    def gospodarka_edit(panstwo_id):
        panstwo = Panstwo.query.get_or_404(panstwo_id)
        g = Gospodarka.query.filter_by(panstwo_id=panstwo_id).first()

        # jeśli nie ma rekordu g — stwórz tymczasowy (nie commitujemy dopóki nie ma ok)
        if not g:
            g = Gospodarka(panstwo_id=panstwo_id)

        # Helper: lista pól
        float_fields = [
            "wzrost_pkb", "bezrobocie",
            "sektor_uslugi_pct", "sektor_przemysl_pct", "sektor_rolnictwo_pct",
            "dlug_pct_pkb",
            "energia_nieodnawialne_pct", "energia_odnawialne_pct", "energia_atomowa_pct",
            "indeks_stabilnosci_gosp", "indeks_korupcji_gosp",
            "indeks_innowacji_gosp", "indeks_rozwoju_ludzkiego",
        ]

        int_fields = [
            "eksport_wartosc", "import_wartosc",
            "ropa_wydobycie", "gaz_wydobycie", "wegiel_wydobycie",
            "uran_wydobycie", "zloto_wydobycie", "kerbit_wydobycie",
            "natsyt_wydobycie", "cemium_wydobycie",
            "technologie_wartosc_prod", "uzbrojenie_wartosc_prod",
            "budownictwo_wartosc_prod", "przemysl_ciezki_wartosc_prod",
            "przemysl_lekki_wartosc_prod", "produkcja_zywnosci_wartosc_prod",
            "uslugi_finansowe_wartosc_prod", "przemysl_farmaceut_wartosc_prod",
            "przemysl_samochodowy_wartosc_prod", "przemysl_rozrywkowy_wartosc_prod"
        ]

        if request.method == "POST":
            form = request.form

            # Zbiór błędów pogrupowanych per sekcja
            errors = {
                "struktura": [],
                "produkcja": [],
                "budzet": [],
                "indeksy": [],
                "pars": []  # błędy parsowania / formatów
            }

            # Przechowamy sparsowane wartości tymczasowo tutaj
            parsed = {}

            # ---------- Parsowanie pól float ----------
            for f in float_fields:
                raw = form.get(f)
                if raw is None or raw == "":
                    parsed[f] = None
                    continue
                try:
                    # akceptujemy przecinek jako separator dzies.
                    val = float(raw.replace(",", ".").strip())
                    parsed[f] = val
                except Exception:
                    parsed[f] = None
                    errors["pars"].append(f"Pole '{f}' musi być liczbą (użyj cyfry i opcjonalnie przecinka/kropki).")

            # ---------- Parsowanie pól int (wartości, produkcja, wydobycie) ----------
            for f in int_fields:
                raw = form.get(f)
                if raw is None or raw == "":
                    parsed[f] = None
                    continue
                try:
                    # dopuszczamy wpisanie "1234.0" -> int
                    val = int(float(raw.replace(",", ".").strip()))
                    parsed[f] = val
                except Exception:
                    parsed[f] = None
                    errors["pars"].append(f"Pole '{f}' musi być liczbą całkowitą.")

            # Jeżeli są błędy parsowania → pokaż je od razu nad formularzem (ale zbieramy też dalsze walidacje)
            # (nie przerywamy, bo chcemy zebrać wszystkie błędy)
            
            # ---------- WALIDACJA: Struktura = 100% ----------
            su = parsed.get("sektor_uslugi_pct") or 0
            sp = parsed.get("sektor_przemysl_pct") or 0
            sr = parsed.get("sektor_rolnictwo_pct") or 0
            # porównanie z tolerancją float
            if round(su + sp + sr, 6) != 100.0:
                errors["struktura"].append("Wartości w tej sekcji musza sumować się do 100%")

            # ---------- WALIDACJA: Produkcja sum <= panstwo.PKB ----------
            suma_produkcji = sum([
                parsed.get("technologie_wartosc_prod") or 0,
                parsed.get("uzbrojenie_wartosc_prod") or 0,
                parsed.get("budownictwo_wartosc_prod") or 0,
                parsed.get("przemysl_ciezki_wartosc_prod") or 0,
                parsed.get("przemysl_lekki_wartosc_prod") or 0,
                parsed.get("produkcja_zywnosci_wartosc_prod") or 0,
                parsed.get("uslugi_finansowe_wartosc_prod") or 0,
                parsed.get("przemysl_farmaceut_wartosc_prod") or 0,
                parsed.get("przemysl_samochodowy_wartosc_prod") or 0,
                parsed.get("przemysl_rozrywkowy_wartosc_prod") or 0
            ])

            # jeśli panstwo.PKB nie jest puste - sprawdzamy
            if panstwo.panstwo_PKB:
                try:
                    pkb_val = float(panstwo.panstwo_PKB)
                except Exception:
                    pkb_val = None

                if pkb_val is not None and suma_produkcji > pkb_val:

                    przekroczenie = suma_produkcji - pkb_val

                    errors["produkcja"].append(
                        f"Roczna wartość wszystkich sektorów produkcji nie może przekraczać "
                        f"całościowego rocznego produktu krajowego brutto danego państwa. "
                        f"Dla {panstwo.panstwo_nazwa} jest to {format_num(panstwo.panstwo_PKB)}. "
                        f"Sumaryczna wartość w poniższym przypadku została przekroczona o "
                        f"{format_num(przekroczenie)}."
                    )


            # ---------- WALIDACJA: pola budżetowe i energetyczne 0..100 ----------
            budzet_pola = [
                
                "energia_nieodnawialne_pct", "energia_odnawialne_pct", "energia_atomowa_pct"
            ]
            for f in budzet_pola:
                v = parsed.get(f)
                if v is None:
                    continue
                try:
                    if not (0 <= float(v) <= 100):
                        errors["budzet"].append(f"Wskazany indeks '{f}' musi zawierać się w przedziale 0-100")
                except Exception:
                    errors["budzet"].append(f"Wskazany indeks '{f}' musi zawierać się w przedziale 0-100")

            # ---------- WALIDACJA: indeksy rozwojowe 0..100 ----------
            indeksy_pola = [
                "indeks_stabilnosci_gosp", "indeks_korupcji_gosp",
                "indeks_innowacji_gosp", "indeks_rozwoju_ludzkiego"
            ]
            for f in indeksy_pola:
                v = parsed.get(f)
                if v is None:
                    continue
                try:
                    if not (0 <= float(v) <= 100):
                        errors["indeksy"].append(f"Wskazany indeks '{f}' musi zawierać się w przedziale 0-100")
                except Exception:
                    errors["indeksy"].append(f"Wskazany indeks '{f}' musi zawierać się w przedziale 0-100")

            # ---------- Jeżeli są jakiekolwiek błędy -> wyświetlamy je (nad odpowiednimi sekcjami) ----------
            any_errors = any(len(lst) > 0 for lst in errors.values())
            if any_errors:
                # przekażemy także form_data (surowe wartości) żeby wypełnić pola bezpośrednio
                form_data = {k: (request.form.get(k) or "") for k in (float_fields + int_fields)}
                # render z errors per-sekcja oraz form_data
                return render_template(
                    "gospodarka_edit.html",
                    panstwo=panstwo,
                    g=g,
                    errors=errors,
                    form_data=form_data
                )

            # ---------- JEŚLI BRAK BŁĘDÓW -> zapiszemy wartości do modelu i commit ----------
            # float_fields -> zapis
            for f in float_fields:
                setattr(g, f, parsed.get(f))

            # int_fields -> zapis
            for f in int_fields:
                setattr(g, f, parsed.get(f))

            # commit
            try:
                db.session.add(g)
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                # ogólny błąd zapisu
                return render_template(
                    "gospodarka_edit.html",
                    panstwo=panstwo,
                    g=g,
                    errors={"pars":[f"Błąd zapisu do bazy: {e}"]},
                    form_data={k: (request.form.get(k) or "") for k in (float_fields + int_fields)}
                )

            return redirect(url_for("gospodarka_form", panstwo_id=panstwo_id))

        # GET -> przygotuj domyślne form_data z obiektu g (żeby pola były wypełnione)
        form_data = {}
        for f in float_fields + int_fields:
            val = getattr(g, f, None)
            form_data[f] = "" if val is None else str(val)

        return render_template("gospodarka_edit.html", panstwo=panstwo, g=g, errors={}, form_data=form_data)


    
    ### LISTA PAŃSTW Z DANYMI GOSPODARCZYMI + FILTR ###

    @app.route("/gospodarka_list")
    def gospodarka_list():
        kontynent = request.args.get("kontynent", "").strip()
        panstwo_q = request.args.get("panstwo", "").strip()
        panstwo_id = request.args.get("panstwo_id", "").strip()

        # Lista dostępnych kontynentów
        kontynenty = (
            db.session.query(Panstwo.kontynent)
            .distinct()
            .all()
        )
        kontynenty = [k[0] for k in kontynenty if k[0]]

        # Bazowe zapytanie
        query = (
            db.session.query(Panstwo)
            .outerjoin(Gospodarka, Gospodarka.panstwo_id == Panstwo.PANSTWO_ID)
        )

        # Filtrowanie
        if kontynent:
            query = query.filter(Panstwo.kontynent == kontynent)

        if panstwo_q:
            query = query.filter(Panstwo.panstwo_nazwa.like(f"%{panstwo_q}%"))

        if panstwo_id.isdigit():
            query = query.filter(Panstwo.PANSTWO_ID == int(panstwo_id))

        panstwa = query.order_by(Panstwo.panstwo_nazwa).all()
        empty = len(panstwa) == 0

        return render_template(
            "gospodarka_list.html",
            panstwa=panstwa,
            kontynenty=kontynenty,
            empty=empty,
            kontynent_selected=kontynent,
            panstwo_q=panstwo_q,
            panstwo_id=panstwo_id
        )
    
######## PORÓWNYWARKA ################

    @app.route("/gospodarka/porownaj", methods=["GET", "POST"])
    def gospodarka_porownaj():
        panstwa = Panstwo.query.order_by(Panstwo.panstwo_nazwa).all()
        wyniki = None
        wybrane_ids = []

        if request.method == "POST":
            wybrane_ids = request.form.getlist("panstwa")

            if len(wybrane_ids) < 2:
                error = "Aby przeprowadzić porównanie, wybierz przynajmniej dwa państwa."
                return render_template("gospodarka_porownaj.html",
                                    panstwa=panstwa,
                                    wyniki=None,
                                    wybrane_ids=wybrane_ids,
                                    error=error)

            wyniki = (
                db.session.query(Panstwo)
                .filter(Panstwo.PANSTWO_ID.in_(wybrane_ids))
                .outerjoin(Gospodarka, Gospodarka.panstwo_id == Panstwo.PANSTWO_ID)
                .order_by(Panstwo.panstwo_nazwa)
                .all()
            )

        return render_template("gospodarka_porownaj.html",
                            panstwa=panstwa,
                            wyniki=wyniki,
                            wybrane_ids=wybrane_ids,
                            error=None)
    
    @app.route("/api/panstwo_gospodarka")
    def api_panstwo_gospodarka():
        """
        API dla porównywarki gospodarczej.
        Zwraca:
        - dane państwa,
        - dane gospodarcze,
        - listę pól, w których "mniej = lepiej".
        """

        panstwo_id = request.args.get("id", "")

        if not panstwo_id.isdigit():
            return jsonify({"error": "Invalid ID"}), 400

        pan = Panstwo.query.get(int(panstwo_id))
        if not pan:
            return jsonify({"error": "Not found"}), 404

        g = Gospodarka.query.filter_by(panstwo_id=pan.PANSTWO_ID).first()

        # wszystkie pola gospodarki
        def safe(v):
            return v if v is not None else 0

        gospodarka = {
            "wzrost_pkb": safe(g.wzrost_pkb) if g else 0,
            "bezrobocie": safe(g.bezrobocie) if g else 0,

            "sektor_uslugi_pct": safe(g.sektor_uslugi_pct) if g else 0,
            "sektor_przemysl_pct": safe(g.sektor_przemysl_pct) if g else 0,
            "sektor_rolnictwo_pct": safe(g.sektor_rolnictwo_pct) if g else 0,

            "eksport_wartosc": safe(g.eksport_wartosc) if g else 0,
            "import_wartosc": safe(g.import_wartosc) if g else 0,

            "ropa_wydobycie": safe(g.ropa_wydobycie) if g else 0,
            "gaz_wydobycie": safe(g.gaz_wydobycie) if g else 0,
            "wegiel_wydobycie": safe(g.wegiel_wydobycie) if g else 0,
            "uran_wydobycie": safe(g.uran_wydobycie) if g else 0,
            "zloto_wydobycie": safe(g.zloto_wydobycie) if g else 0,
            "kerbit_wydobycie": safe(g.kerbit_wydobycie) if g else 0,
            "natsyt_wydobycie": safe(g.natsyt_wydobycie) if g else 0,
            "cemium_wydobycie": safe(g.cemium_wydobycie) if g else 0,

            "technologie_wartosc_prod": safe(g.technologie_wartosc_prod) if g else 0,
            "uzbrojenie_wartosc_prod": safe(g.uzbrojenie_wartosc_prod) if g else 0,
            "budownictwo_wartosc_prod": safe(g.budownictwo_wartosc_prod) if g else 0,
            "przemysl_ciezki_wartosc_prod": safe(g.przemysl_ciezki_wartosc_prod) if g else 0,
            "przemysl_lekki_wartosc_prod": safe(g.przemysl_lekki_wartosc_prod) if g else 0,
            "produkcja_zywnosci_wartosc_prod": safe(g.produkcja_zywnosci_wartosc_prod) if g else 0,
            "uslugi_finansowe_wartosc_prod": safe(g.uslugi_finansowe_wartosc_prod) if g else 0,
            "przemysl_farmaceut_wartosc_prod": safe(g.przemysl_farmaceut_wartosc_prod) if g else 0,
            "przemysl_samochodowy_wartosc_prod": safe(g.przemysl_samochodowy_wartosc_prod) if g else 0,
            "przemysl_rozrywkowy_wartosc_prod": safe(g.przemysl_rozrywkowy_wartosc_prod) if g else 0,

            "dlug_pct_pkb": safe(g.dlug_pct_pkb) if g else 0,
            "energia_nieodnawialne_pct": safe(g.energia_nieodnawialne_pct) if g else 0,
            "energia_odnawialne_pct": safe(g.energia_odnawialne_pct) if g else 0,
            "energia_atomowa_pct": safe(g.energia_atomowa_pct) if g else 0,

            "indeks_stabilnosci_gosp": safe(g.indeks_stabilnosci_gosp) if g else 0,
            "indeks_korupcji_gosp": safe(g.indeks_korupcji_gosp) if g else 0,
            "indeks_innowacji_gosp": safe(g.indeks_innowacji_gosp) if g else 0,
            "indeks_rozwoju_ludzkiego": safe(g.indeks_rozwoju_ludzkiego) if g else 0
        }

        # listy wskaźników, gdzie "niżej = lepiej"
        reverse_fields = [
            "bezrobocie",
            "import_wartosc",
            "dlug_pct_pkb",
            "indeks_korupcji_gosp",
            "sektor_rolnictwo_pct",
            "energia_nieodnawialne_pct"
        ]

        return jsonify({
            "id": pan.PANSTWO_ID,
            "nazwa": pan.panstwo_nazwa,
            "kontynent": pan.kontynent,
            "populacja": safe(pan.panstwo_populacja),
            "gospodarka": gospodarka,
            "reverse_fields": reverse_fields
        })



    
    

