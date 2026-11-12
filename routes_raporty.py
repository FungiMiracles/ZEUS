# routes_raporty.py

import io
import pandas as pd
from flask import render_template, send_file
from sqlalchemy import or_

from extensions import db
from models import (
    Region,
    Miasto,
    Panstwo,
    Gospodarka,
    Zdarzenie,
    Spoleczenstwo,
    RegionStateHistory,
    HistoriaPopulacjiPanstw,
    PKBStateHistory,
    PKBPCStateHistory,
    SpoleczenstwoStateHistory,
    ProcentWzrostuStateHistory,
    RocznyPrzyrostStateHistory
)


def init_raporty_routes(app):

    @app.route("/raporty/stan_tabel")
    def raporty_stan_tabel():

        # =====================================================
        # TOTALS
        # =====================================================

        total_regiony = Region.query.count()
        total_panstwa = Panstwo.query.count()
        total_miasta = Miasto.query.count()

        # =====================================================
        # REGIONY — KLASYFIKACJA
        # =====================================================

        regiony_bez_klasyfikacji = Region.query.filter(
            or_(
                Region.region_polozenie_id.is_(None),
                Region.region_typ_nadrz_id.is_(None),
                Region.region_typ_podrz_id.is_(None)
            )
        ).count()

        # =====================================================
        # REGIONY — RYZYKA
        # =====================================================

        regiony_bez_ryzyk = Region.query.filter(
            or_(
                Region.region_sejsmicznosc.is_(None),
                Region.region_ryzyko_powodzi.is_(None),
                Region.region_ryzyko_lawin.is_(None),
                Region.region_ryzyko_upalu.is_(None),
                Region.region_ryzyko_mrozu.is_(None),
                Region.region_aktywny_wulkan.is_(None)
            )
        ).count()

        # =====================================================
        # REGIONY — INFRASTRUKTURA
        # =====================================================

        regiony_bez_infra = Region.query.filter(
            or_(
                Region.region_poziom_skomunikowania.is_(None),
                Region.region_stan_infra_kolejowej.is_(None),
                Region.region_stan_infra_drogowej.is_(None),
                Region.region_stan_infra_energetycznej.is_(None),
                Region.region_stan_infra_mieszkalnej.is_(None)
            )
        ).count()

        # =====================================================
        # REGIONY — BRAK MAPY
        # =====================================================

        regiony_bez_mapy = Region.query.filter(
            Region.region_mapa.is_(None)
        ).count()

        # =====================================================
        # REGIONY — BRAK MIAST
        # =====================================================

        regiony_bez_miast = Region.query.filter(
            ~Region.miasta.any()
        ).count()

        # =====================================================
        # SPOŁECZEŃSTWO
        # =====================================================

        panstwa_bez_spoleczenstwa = Panstwo.query.filter(
            or_(
                ~Panstwo.spoleczenstwo.has(),

                Spoleczenstwo.stabilnosc_spoleczna.is_(None),
                Spoleczenstwo.zadowolenie_spoleczne.is_(None),
                Spoleczenstwo.nierownosci_spoleczne.is_(None),
                Spoleczenstwo.poziom_edukacji.is_(None),
                Spoleczenstwo.swiadomosc_spoleczna.is_(None),
                Spoleczenstwo.zaufanie_do_wladzy.is_(None),
                Spoleczenstwo.napiecia_religijne.is_(None),
                Spoleczenstwo.napiecia_etniczne.is_(None),
                Spoleczenstwo.napiecia_klasowe.is_(None),
                Spoleczenstwo.przestepczosc.is_(None),
                Spoleczenstwo.radykalizacja_spoleczna.is_(None),
                Spoleczenstwo.spojnosc_spoleczna.is_(None),
                Spoleczenstwo.tozsamosc_narodowa.is_(None),
                Spoleczenstwo.konserwatyzm_spoleczny.is_(None),
                Spoleczenstwo.otwartosc_spoleczna.is_(None),
                Spoleczenstwo.spozycie_alkoholu.is_(None),
                Spoleczenstwo.spozycie_narkotykow.is_(None),
                Spoleczenstwo.zdrowie_publiczne.is_(None)
            )
        ).outerjoin(Spoleczenstwo).count()

        # =====================================================
        # MIASTA TECHNICZNE
        # =====================================================

        miasta_techniczne = Miasto.query.filter(
            Miasto.miasto_nazwa.ilike("%techniczne%")
        ).count()

        # =====================================================
        # GOSPODARKA — PKB
        # =====================================================

        panstwa_bez_wzrostu_pkb = Panstwo.query.filter(
            or_(
                ~Panstwo.gospodarka.has(),
                Gospodarka.wzrost_pkb.is_(None)
            )
        ).outerjoin(Gospodarka).count()

        # =====================================================
        # GOSPODARKA — BEZROBOCIE
        # =====================================================

        panstwa_bez_bezrobocia = Panstwo.query.filter(
            or_(
                ~Panstwo.gospodarka.has(),
                Gospodarka.bezrobocie.is_(None)
            )
        ).outerjoin(Gospodarka).count()

        # =====================================================
        # HELPER
        # =====================================================

        def pct(count, total):
            if total == 0:
                return 0

            return round((count / total) * 100, 1)

        # =====================================================
        # RAPORT
        # =====================================================

        raport = [

            {
                "label": "Regiony bez klasyfikacji",
                "count": regiony_bez_klasyfikacji,
                "percent": pct(regiony_bez_klasyfikacji, total_regiony)
            },

            {
                "label": "Regiony bez ryzyk",
                "count": regiony_bez_ryzyk,
                "percent": pct(regiony_bez_ryzyk, total_regiony)
            },

            {
                "label": "Regiony bez infrastruktury i skomunikowania",
                "count": regiony_bez_infra,
                "percent": pct(regiony_bez_infra, total_regiony)
            },

            {
                "label": "Regiony bez mapy",
                "count": regiony_bez_mapy,
                "percent": pct(regiony_bez_mapy, total_regiony)
            },

            {
                "label": "Regiony bez miast",
                "count": regiony_bez_miast,
                "percent": pct(regiony_bez_miast, total_regiony)
            },

            {
                "label": "Państwa bez danych o społeczeństwie",
                "count": panstwa_bez_spoleczenstwa,
                "percent": pct(panstwa_bez_spoleczenstwa, total_panstwa)
            },

            {
                "label": "Miasta techniczne bez zmodyfikowanej nazwy",
                "count": miasta_techniczne,
                "percent": pct(miasta_techniczne, total_miasta)
            },

            {
                "label": "Państwa bez danych o wzroście PKB",
                "count": panstwa_bez_wzrostu_pkb,
                "percent": pct(panstwa_bez_wzrostu_pkb, total_panstwa)
            },

            {
                "label": "Państwa bez danych o bezrobociu",
                "count": panstwa_bez_bezrobocia,
                "percent": pct(panstwa_bez_bezrobocia, total_panstwa)
            }

        ]

        return render_template(
            "raporty_stan_tabel.html",
            raport=raport
        )

    @app.route("/raporty/export/region_state_history")
    def export_region_state_history():

        rows = (
            db.session.query(
                RegionStateHistory,
                Zdarzenie.zdarzenie_typ
            )
            .outerjoin(
                Zdarzenie,
                RegionStateHistory.event_id == Zdarzenie.zdarzenie_id
            )
            .order_by(
                RegionStateHistory.data_entenda.desc()
            )
            .all()
        )

        data = []

        for r, zdarzenie_typ in rows:

            data.append({

                "ID": r.id,

                "Region ID": r.region_id,

                "Event ID": r.event_id,

                "Źródło": r.source,

                "Typ zdarzenia": zdarzenie_typ,

                "Data Entenda": r.data_entenda,

                "Data rzeczywista": r.data_rzeczywista,

                # LUDNOŚĆ
                "Ludność OLD": r.old_ludnosc,
                "Ludność NEW": r.new_ludnosc,

                # DROGI
                "Drogi OLD": r.old_drogi,
                "Drogi NEW": r.new_drogi,

                # KOLEJ
                "Kolej OLD": r.old_kolej,
                "Kolej NEW": r.new_kolej,

                # ENERGIA
                "Energia OLD": r.old_energia,
                "Energia NEW": r.new_energia,

                # MIESZKANIA
                "Mieszkania OLD": r.old_mieszkania,
                "Mieszkania NEW": r.new_mieszkania,

                # PORTY
                "Porty OLD": r.old_porty,
                "Porty NEW": r.new_porty,

                                # PORTY
                "Porty OLD": r.old_porty,
                "Porty NEW": r.new_porty,

                # ŚRODOWISKO
                "Degradacja środowiska OLD": r.old_degradacja_srodowiska,
                "Degradacja środowiska NEW": r.new_degradacja_srodowiska,

                "Zanieczyszczenie powietrza OLD": r.old_zanieczyszczenie_powietrza,
                "Zanieczyszczenie powietrza NEW": r.new_zanieczyszczenie_powietrza
            })

        df = pd.DataFrame(data)

        output = io.BytesIO()

        with pd.ExcelWriter(
            output,
            engine="openpyxl"
        ) as writer:

            df.to_excel(
                writer,
                index=False,
                sheet_name="region_state_history"
            )

        output.seek(0)

        return send_file(
            output,
            as_attachment=True,
            download_name="region_state_history.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    
    @app.route("/raporty/export/historia_populacji_panstw")
    def export_historia_populacji_panstw():

        rows = (
            HistoriaPopulacjiPanstw.query
            .order_by(
                HistoriaPopulacjiPanstw.data_entenda.desc()
            )
            .all()
        )

        data = []

        for r in rows:

            data.append({

                "ID": r.id,
                "Państwo ID": r.panstwo_id,
                "Populacja": r.panstwo_populacja,

                "Data Entenda": r.data_entenda,
                "Data rzeczywista": r.data_rzeczywista
            })

        df = pd.DataFrame(data)

        output = io.BytesIO()

        with pd.ExcelWriter(
            output,
            engine="openpyxl"
        ) as writer:

            df.to_excel(
                writer,
                index=False,
                sheet_name="historia_populacji"
            )

        output.seek(0)

        return send_file(
            output,
            as_attachment=True,
            download_name="historia_populacji_panstw.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    
    @app.route("/raporty/export/pkb_state_history")
    def export_pkb_state_history():

        rows = (
            PKBStateHistory.query
            .order_by(
                PKBStateHistory.data_entenda.desc()
            )
            .all()
        )

        data = []

        for r in rows:

            data.append({

                "ID": r.id,
                "Państwo ID": r.panstwo_id,
                "Event ID": r.event_id,
                "Źródło": r.source,

                "Data Entenda": r.data_entenda,
                "Data rzeczywista": r.data_rzeczywista,

                "PKB OLD": r.old_pkb,
                "PKB NEW": r.new_pkb,
                "Delta": r.change_delta
            })

        df = pd.DataFrame(data)

        output = io.BytesIO()

        with pd.ExcelWriter(
            output,
            engine="openpyxl"
        ) as writer:

            df.to_excel(
                writer,
                index=False,
                sheet_name="pkb_state_history"
            )

        output.seek(0)

        return send_file(
            output,
            as_attachment=True,
            download_name="pkb_state_history.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    @app.route("/raporty/export/pkbpc_state_history")
    def export_pkbpc_state_history():

        rows = (
            PKBPCStateHistory.query
            .order_by(
                PKBPCStateHistory.data_entenda.desc()
            )
            .all()
        )

        data = []

        for r in rows:

            data.append({

                "ID": r.id,
                "Państwo ID": r.panstwo_id,
                "Event ID": r.event_id,
                "Źródło": r.source,

                "Data Entenda": r.data_entenda,
                "Data rzeczywista": r.data_rzeczywista,

                "PKB per capita OLD": r.old_pkbpc,
                "PKB per capita NEW": r.new_pkbpc,
                "Delta": r.change_delta
            })

        df = pd.DataFrame(data)

        output = io.BytesIO()

        with pd.ExcelWriter(
            output,
            engine="openpyxl"
        ) as writer:

            df.to_excel(
                writer,
                index=False,
                sheet_name="pkbpc_state_history"
            )

        output.seek(0)

        return send_file(
            output,
            as_attachment=True,
            download_name="pkbpc_state_history.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    
    @app.route("/raporty/export/spoleczenstwo_state_history")
    def export_spoleczenstwo_state_history():

        rows = (
            SpoleczenstwoStateHistory.query
            .order_by(
                SpoleczenstwoStateHistory.data_entenda.desc()
            )
            .all()
        )

        data = []

        for r in rows:

            data.append({

                "ID": r.id,
                "Państwo ID": r.panstwo_id,
                "Event ID": r.event_id,
                "Źródło": r.source,

                "Data Entenda": r.data_entenda,
                "Data rzeczywista": r.data_rzeczywista,

                "OLD stabilność": r.old_stabilnosc,
                "NEW stabilność": r.new_stabilnosc,

                "OLD zadowolenie": r.old_zadowolenie,
                "NEW zadowolenie": r.new_zadowolenie,

                "OLD nierówności": r.old_nierownosci,
                "NEW nierówności": r.new_nierownosci,

                "OLD edukacja": r.old_edukacja,
                "NEW edukacja": r.new_edukacja,

                "OLD świadomość": r.old_swiadomosc,
                "NEW świadomość": r.new_swiadomosc,

                "OLD zaufanie": r.old_zaufanie,
                "NEW zaufanie": r.new_zaufanie,

                "OLD napięcia religijne": r.old_napiecia_religijne,
                "NEW napięcia religijne": r.new_napiecia_religijne,

                "OLD napięcia etniczne": r.old_napiecia_etniczne,
                "NEW napięcia etniczne": r.new_napiecia_etniczne,

                "OLD napięcia klasowe": r.old_napiecia_klasowe,
                "NEW napięcia klasowe": r.new_napiecia_klasowe,

                "OLD przestępczość": r.old_przestepczosc,
                "NEW przestępczość": r.new_przestepczosc,

                "OLD radykalizacja": r.old_radykalizacja,
                "NEW radykalizacja": r.new_radykalizacja,

                "OLD spójność": r.old_spojnosc,
                "NEW spójność": r.new_spojnosc,

                "OLD tożsamość": r.old_tozsamosc,
                "NEW tożsamość": r.new_tozsamosc,

                "OLD konserwatyzm": r.old_konserwatyzm,
                "NEW konserwatyzm": r.new_konserwatyzm,

                "OLD otwartość": r.old_otwartosc,
                "NEW otwartość": r.new_otwartosc,

                "OLD alkohol": r.old_spozycie_alkoholu,
                "NEW alkohol": r.new_spozycie_alkoholu,

                "OLD narkotyki": r.old_spozycie_narkotykow,
                "NEW narkotyki": r.new_spozycie_narkotykow,

                "OLD zdrowie": r.old_zdrowie_publiczne,
                "NEW zdrowie": r.new_zdrowie_publiczne
            })

        df = pd.DataFrame(data)

        output = io.BytesIO()

        with pd.ExcelWriter(
            output,
            engine="openpyxl"
        ) as writer:

            df.to_excel(
                writer,
                index=False,
                sheet_name="spoleczenstwo_state_history"
            )

        output.seek(0)

        return send_file(
            output,
            as_attachment=True,
            download_name="spoleczenstwo_state_history.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    
    @app.route("/raporty/export/procent_wzrostu_state_history")
    def export_procent_wzrostu_state_history():

        rows = (
            ProcentWzrostuStateHistory.query
            .order_by(
                ProcentWzrostuStateHistory.data_entenda.desc()
            )
            .all()
        )

        data = []

        for r in rows:

            data.append({

                "ID": r.id,
                "Państwo ID": r.panstwo_id,
                "Event ID": r.event_id,
                "Źródło": r.source,

                "Data Entenda": r.data_entenda,
                "Data rzeczywista": r.data_rzeczywista,

                "Wzrost PKB OLD": r.old_wzrost,
                "Wzrost PKB NEW": r.new_wzrost,
                "Delta": r.change_delta
            })

        df = pd.DataFrame(data)

        output = io.BytesIO()

        with pd.ExcelWriter(
            output,
            engine="openpyxl"
        ) as writer:

            df.to_excel(
                writer,
                index=False,
                sheet_name="procent_wzrostu"
            )

        output.seek(0)

        return send_file(
            output,
            as_attachment=True,
            download_name="procent_wzrostu_state_history.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    
    @app.route("/raporty/export/roczny_przyrost_state_history")
    def export_roczny_przyrost_state_history():

        rows = (
            RocznyPrzyrostStateHistory.query
            .order_by(
                RocznyPrzyrostStateHistory.data_entenda.desc()
            )
            .all()
        )

        data = []

        for r in rows:

            data.append({

                "ID": r.id,
                "Państwo ID": r.panstwo_id,

                "Data Entenda": r.data_entenda,
                "Data rzeczywista": r.data_rzeczywista,

                "OLD roczny przyrost": r.old_roczny_przyrost,
                "NEW roczny przyrost": r.new_roczny_przyrost

            })

        df = pd.DataFrame(
            data,
            columns=[
                "ID",
                "Państwo ID",
                "Data Entenda",
                "Data rzeczywista",
                "OLD roczny przyrost",
                "NEW roczny przyrost",
            ]
        )

        output = io.BytesIO()

        with pd.ExcelWriter(
            output,
            engine="openpyxl"
        ) as writer:

            df.to_excel(
                writer,
                index=False,
                sheet_name="roczny_przyrost"
            )

        output.seek(0)

        return send_file(
            output,
            as_attachment=True,
            download_name="roczny_przyrost_state_history.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )