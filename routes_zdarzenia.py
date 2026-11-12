from flask import render_template, request, redirect, url_for, flash, session, abort
import hmac
import secrets
from sqlalchemy.exc import SQLAlchemyError
from engine.clock import get_current_entenda_datetime
from services.global_economic_crisis import GlobalEconomicCrisis, CrisisError, LEVELS, EVENT_TYPE, current_crisis, generate_crisis
from extensions import db
from models import Zdarzenie, Panstwo, Region, Miasto, ZdarzenieSzablon
from engine.generator import generate_events
from sqlalchemy import extract
from datetime import datetime, timedelta
import pandas as pd
from flask import send_file
from io import BytesIO
from permissions import wymaga_roli


def init_zdarzenia_routes(app):

    # =====================================================
    # LISTA ZDARZEŃ + FILTROWANIE
    # =====================================================
    @app.route("/zdarzenia")
    def zdarzenia_list():

        crisis_year = get_current_entenda_datetime().year
        crisis = current_crisis(crisis_year)
        if session.get('rola') == 'wszechmocny':
            session.setdefault('global_crisis_csrf', secrets.token_urlsafe(32))

        zdarzenie_id = request.args.get("zdarzenie_id")
        region_id = request.args.get("region_id")
        panstwo_id = request.args.get("panstwo_id")
        typ = request.args.get("typ")
        data_od = request.args.get("data_od")
        data_do = request.args.get("data_do")
        skala = request.args.get("skala", type=int)
        szablon_id = request.args.get("szablon_id", type=int)
        miasto_id = request.args.get("miasto_id", type=int)

        ofiary_od = request.args.get("ofiary_od", type=int)
        ofiary_do = request.args.get("ofiary_do", type=int)

        data_usuniecia = request.args.get("data_usuniecia")

        status = request.args.get("status")
        wariant = request.args.get("wariant")

        # NAJPIERW TWORZYMY QUERY
        query = (
            db.session.query(Zdarzenie, Region, Panstwo, ZdarzenieSzablon)
            .outerjoin(Region, Zdarzenie.region_id == Region.region_id)
            .outerjoin(Panstwo, Region.panstwo_id == Panstwo.PANSTWO_ID)
                .outerjoin(ZdarzenieSzablon, Zdarzenie.opis_szablon_id == ZdarzenieSzablon.szablon_id)
        )

        # FILTRY
        if zdarzenie_id and zdarzenie_id.isdigit():
            query = query.filter(Zdarzenie.zdarzenie_id == int(zdarzenie_id))

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

        if skala:
            query = query.filter(Zdarzenie.skala == skala)

        if szablon_id:
            query = query.filter(Zdarzenie.opis_szablon_id == szablon_id)

        if miasto_id:
            query = query.filter(Zdarzenie.miasto_id == miasto_id)

        if ofiary_od is not None:
            query = query.filter(Zdarzenie.ilosc_ofiar >= ofiary_od)

        if ofiary_do is not None:
            query = query.filter(Zdarzenie.ilosc_ofiar <= ofiary_do)

        if status:
            query = query.filter(Zdarzenie.status == status)

        if wariant:
            query = query.filter(ZdarzenieSzablon.wariant == wariant)
        
        liczba_wynikow = query.count()

        zdarzenia = (
            query
            .order_by(Zdarzenie.zdarzenie_id.desc())
            .all()
        )

        typy = [
            t[0]
            for t in (
                db.session.query(Zdarzenie.zdarzenie_typ)
                .distinct()
                .order_by(Zdarzenie.zdarzenie_typ.asc())
                .all()
            )
        ]

        return render_template(
            "zdarzenia_list.html",
            zdarzenia=zdarzenia,
            typy=typy,
            liczba_wynikow=liczba_wynikow,
            crisis=crisis, crisis_year=crisis_year, crisis_levels=LEVELS
        )

    @app.post('/zdarzenia/globalny-kryzys')
    @wymaga_roli('wszechmocny')
    def global_economic_crisis():
        expected = session.get('global_crisis_csrf', '')
        supplied = request.form.get('csrf_token', '')
        if not expected or not hmac.compare_digest(expected.encode(), supplied.encode()):
            abort(403, description='Sesja formularza wygasła. Odśwież Generator Zdarzeń.')
        db.session.rollback()
        try:
            event_id = generate_crisis(request.form.get('level'), request.form.get('year'),
                session.get('username') or session.get('user_id') or 'Administrator WIKI')
            flash(f'Wygenerowano globalny kryzys gospodarczy. Zdarzenie ID {event_id}.', 'success')
        except CrisisError as error:
            flash(str(error), 'error')
        except SQLAlchemyError:
            app.logger.exception('Global economic crisis transaction failed')
            flash('Nie udało się wygenerować kryzysu. Zmiany zostały wycofane.', 'error')
        return redirect(url_for('zdarzenia_list'), code=303)

    @app.route("/export_zdarzenia_excel")
    @wymaga_roli("wszechmocny")
    def export_zdarzenia_excel():

        query = (
            db.session.query(Zdarzenie, Region, Panstwo, ZdarzenieSzablon)
            .outerjoin(Region, Zdarzenie.region_id == Region.region_id)
            .outerjoin(Panstwo, Region.panstwo_id == Panstwo.PANSTWO_ID)
            .outerjoin(ZdarzenieSzablon, Zdarzenie.opis_szablon_id == ZdarzenieSzablon.szablon_id)
        )

        region_id = request.args.get("region_id", type=int)
        panstwo_id = request.args.get("panstwo_id", type=int)
        typ = request.args.get("typ")

        skala = request.args.get("skala", type=int)
        szablon_id = request.args.get("szablon_id", type=int)
        miasto_id = request.args.get("miasto_id", type=int)

        ofiary_od = request.args.get("ofiary_od", type=int)
        ofiary_do = request.args.get("ofiary_do", type=int)

        status = request.args.get("status")
        wariant = request.args.get("wariant")

        if region_id:
            query = query.filter(Zdarzenie.region_id == region_id)

        if panstwo_id:
            query = query.filter(Panstwo.PANSTWO_ID == panstwo_id)

        if typ:
            query = query.filter(Zdarzenie.zdarzenie_typ == typ)

        if skala:
            query = query.filter(Zdarzenie.skala == skala)

        if szablon_id:
            query = query.filter(Zdarzenie.opis_szablon_id == szablon_id)

        if miasto_id:
            query = query.filter(Zdarzenie.miasto_id == miasto_id)

        if ofiary_od is not None:
            query = query.filter(Zdarzenie.ilosc_ofiar >= ofiary_od)

        if ofiary_do is not None:
            query = query.filter(Zdarzenie.ilosc_ofiar <= ofiary_do)

        if status:
            query = query.filter(Zdarzenie.status == status)

        if wariant:
            query = query.filter(ZdarzenieSzablon.wariant == wariant)

        wyniki = query.all()

        rows = []

        for z, r, p, s in wyniki:

            rows.append({
                "ID": z.zdarzenie_id,
                "Typ": z.zdarzenie_typ,
                "Państwo": p.PANSTWO_ID if p else 'Globalne',
                "Region": r.region_id if r else '',
                "Miasto": z.miasto_id,
                "Skala": z.skala,
                "Ofiary": z.ilosc_ofiar,
                "Status": z.status,
                "Wariant": s.wariant if s is not None else "",
                "Szablon": z.opis_szablon_id,
                "Opis": z.opis_wygenerowany,
                "Data CE": z.data_entenda,
                "Data wygenerowania": z.data_rzeczywista,
                "Data usunięcia" : z.data_usuniecia
            })

        df = pd.DataFrame(rows)

        output = BytesIO()

        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Zdarzenia")

        output.seek(0)

        return send_file(
            output,
            as_attachment=True,
            download_name="zdarzenia.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    @app.route("/zdarzenia/usun/<int:zdarzenie_id>", methods=["POST"])
    @wymaga_roli("wszechmocny")
    def usun_zdarzenie(zdarzenie_id):

        zdarzenie = Zdarzenie.query.get_or_404(zdarzenie_id)

        if zdarzenie.zdarzenie_typ == EVENT_TYPE:
            flash('Zapis globalnego kryzysu jest zachowywany w historii i nie może być usunięty.', 'error')
            return redirect(url_for('zdarzenia_list'), code=303)

        db.session.delete(zdarzenie)
        db.session.commit()

        flash(
            f"Zdarzenie o ID {zdarzenie_id} zostało usunięte.",
            "success"
        )

        return redirect(request.referrer or url_for("zdarzenia_list"))
