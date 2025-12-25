# models.py
from sqlalchemy import BigInteger
from extensions import db
from datetime import datetime
from extensions import db

class Panstwo(db.Model):
    __tablename__ = "panstwa"

    PANSTWO_ID = db.Column(db.Integer, primary_key=True)
    panstwo_nazwa = db.Column(db.String(255))
    panstwo_kod = db.Column(db.String(255))
    panstwo_pelna_nazwa = db.Column(db.String(255))
    panstwo_ustroj = db.Column(db.String(255))
    panstwo_stolica = db.Column(db.String(255))
    panstwo_populacja = db.Column(BigInteger)
    panstwo_PKB = db.Column(BigInteger)
    panstwo_PKB_per_capita = db.Column(BigInteger)
    panstwo_waluta = db.Column(db.String(255))
    panstwo_jezyk = db.Column(db.String(255))
    panstwo_religia = db.Column(db.String(255))
    kontynent = db.Column(db.String(255))
    panstwo_powierzchnia = db.Column(BigInteger)

    # 🆕 STATUS SUWERENNOŚCI
    czy_suwerenny = db.Column(
        db.Enum("TAK", "NIE", name="czy_suwerenny_enum"),
        nullable=False,
        default="TAK"
    )

    miasta = db.relationship("Miasto", backref="panstwo", lazy=True)
    regiony = db.relationship("Region", backref="panstwo", lazy=True)


class Region(db.Model):
    __tablename__ = "regiony"

    region_id = db.Column(db.Integer, primary_key=True)
    panstwo_id = db.Column(db.Integer, db.ForeignKey("panstwa.PANSTWO_ID"))
    region_nazwa = db.Column(db.String(255))
    region_populacja = db.Column(BigInteger)
    region_ludnosc_pozamiejska = db.Column(BigInteger, nullable=False, default=0)

    # Relacja do miast
    miasta = db.relationship("Miasto", backref="region", lazy=True)


class Miasto(db.Model):
    __tablename__ = "miasta"

    miasto_id = db.Column(db.Integer, primary_key=True)
    panstwo_id = db.Column(db.Integer, db.ForeignKey("panstwa.PANSTWO_ID"))
    miasto_nazwa = db.Column(db.String(255))
    miasto_kod = db.Column(db.String(4))
    miasto_populacja = db.Column(db.Integer)
    miasto_typ = db.Column(db.String(255))
    region_id = db.Column(db.Integer, db.ForeignKey("regiony.region_id"))
    czy_na_mapie = db.Column(db.Enum("TAK", "NIE", name="czy_na_mapie_enum"), nullable=False, default="TAK")

class Wojsko(db.Model):
    __tablename__ = "wojsko"

    ID = db.Column(db.Integer, primary_key=True, autoincrement=True)
    panstwo_id = db.Column(db.Integer, db.ForeignKey("panstwa.PANSTWO_ID"), nullable=False, unique=True)

    wojska_ladowe_ilosc = db.Column(db.BigInteger)
    wojska_morskie_ilosc = db.Column(db.BigInteger)
    wojska_powietrzne_ilosc = db.Column(db.BigInteger)

    procent_PKB = db.Column(db.Float)

    liczba_baz_ladowych = db.Column(db.Integer)
    liczba_baz_morskich = db.Column(db.Integer)
    liczba_baz_powietrznych = db.Column(db.Integer)

    czolgi_ilosc = db.Column(db.Integer)
    mysliwce_ilosc = db.Column(db.Integer)
    wozy_opancerzone_ilosc = db.Column(db.Integer)
    wyrzutnie_rakiet_ilosc = db.Column(db.Integer)
    okrety_wojenne_ilosc = db.Column(db.Integer)
    lotniskowce_ilosc = db.Column(db.Integer)
    okrety_podwodne_ilosc = db.Column(db.Integer)
    drony_ilosc = db.Column(db.Integer)
    bron_atomowa_ilosc = db.Column(db.Integer)

    # relacja do państwa
    panstwo = db.relationship("Panstwo", backref="wojsko", lazy=True)

class Gospodarka(db.Model):
    __tablename__ = "gospodarka"

    gospodarka_id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    panstwo_id = db.Column(
        db.Integer,
        db.ForeignKey("panstwa.PANSTWO_ID", ondelete="CASCADE"),
        nullable=False
    )

    panstwo = db.relationship(
        "Panstwo",
        backref=db.backref("gospodarka", uselist=False)
    )

    # MAKRO
    wzrost_pkb = db.Column(db.Float)
    bezrobocie = db.Column(db.Float)

    # SEKTORY
    sektor_uslugi_pct = db.Column(db.Float)
    sektor_przemysl_pct = db.Column(db.Float)
    sektor_rolnictwo_pct = db.Column(db.Float)

    # HANDEL
    eksport_wartosc = db.Column(db.BigInteger)
    import_wartosc = db.Column(db.BigInteger)

    # SUROWCE
    ropa_wydobycie = db.Column(db.BigInteger)
    gaz_wydobycie = db.Column(db.BigInteger)
    wegiel_wydobycie = db.Column(db.BigInteger)
    uran_wydobycie = db.Column(db.BigInteger)
    zloto_wydobycie = db.Column(db.BigInteger)

    kerbit_wydobycie = db.Column(db.BigInteger)
    natsyt_wydobycie = db.Column(db.BigInteger)
    cemium_wydobycie = db.Column(db.BigInteger)

    # PRODUKCJA
    technologie_wartosc_prod = db.Column(db.BigInteger)
    uzbrojenie_wartosc_prod = db.Column(db.BigInteger)
    budownictwo_wartosc_prod = db.Column(db.BigInteger)
    przemysl_ciezki_wartosc_prod = db.Column(db.BigInteger)
    przemysl_lekki_wartosc_prod = db.Column(db.BigInteger)
    produkcja_zywnosci_wartosc_prod = db.Column(db.BigInteger)
    uslugi_finansowe_wartosc_prod = db.Column(db.BigInteger)
    przemysl_farmaceut_wartosc_prod = db.Column(db.BigInteger)
    przemysl_samochodowy_wartosc_prod = db.Column(db.BigInteger)
    przemysl_rozrywkowy_wartosc_prod = db.Column(db.BigInteger)

    # BUDŻET
    dlug_pct_pkb = db.Column(db.Float)

    # ENERGIA
    energia_nieodnawialne_pct = db.Column(db.Float)
    energia_odnawialne_pct = db.Column(db.Float)
    energia_atomowa_pct = db.Column(db.Float)

    # INDEKSY
    indeks_stabilnosci_gosp = db.Column(db.Float)
    indeks_korupcji_gosp = db.Column(db.Float)
    indeks_innowacji_gosp = db.Column(db.Float)
    indeks_rozwoju_ludzkiego = db.Column(db.Float)

    data_aktualizacji = db.Column(db.DateTime, default=db.func.now())

    from datetime import datetime
from extensions import db


from extensions import db
from datetime import date


class Historia(db.Model):
    __tablename__ = "historia"

    # =========================================================
    #  KLUCZ GŁÓWNY
    # =========================================================
    HISTORIA_ID = db.Column(db.Integer, primary_key=True)

    # =========================================================
    #  OŚ CZASU (ENTENDA)
    # =========================================================
    data_od = db.Column(db.Date, nullable=False)
    data_do = db.Column(db.Date, nullable=True)

    # =========================================================
    #  KLASYFIKACJA HISTORYCZNA
    # =========================================================
    epoka = db.Column(
        db.Enum(
            "starozytna",
            "sredniowieczna",
            "wspolczesna",
            name="epoka_enum"
        ),
        nullable=False
    )

    kontynent = db.Column(db.String(100), nullable=True)

    # =========================================================
    #  POWIĄZANIA GEOGRAFICZNE (OPCJONALNE)
    # =========================================================
    panstwo_id = db.Column(
        db.Integer,
        db.ForeignKey("panstwa.PANSTWO_ID", ondelete="SET NULL"),
        nullable=True
    )

    region_id = db.Column(
        db.Integer,
        db.ForeignKey("regiony.region_id", ondelete="SET NULL"),
        nullable=True
    )

    miasto_id = db.Column(
        db.Integer,
        db.ForeignKey("miasta.miasto_id", ondelete="SET NULL"),
        nullable=True
    )

    # =========================================================
    #  TREŚĆ
    # =========================================================
    nazwa_wydarzenia = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(255), nullable=False, unique=True)

    # =========================================================
    #  AUDYT
    # =========================================================
    created_at = db.Column(
        db.DateTime,
        server_default=db.func.current_timestamp()
    )

    updated_at = db.Column(
        db.DateTime,
        server_default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp()
    )

    # =========================================================
    #  RELACJE (opcjonalnie, ale zalecane)
    # =========================================================
    panstwo = db.relationship("Panstwo", lazy="joined")
    region = db.relationship("Region", lazy="joined")
    miasto = db.relationship("Miasto", lazy="joined")

    # =========================================================
    #  WŁAŚCIWOŚCI POMOCNICZE (LOGIKA)
    # =========================================================

    @property
    def zakres_dat_label(self) -> str:
        """
        Zwraca czytelny zakres dat:
        - DD-MM-RRRR
        - DD-MM-RRRR – DD-MM-RRRR
        """
        if self.data_do:
            return (
                f"{self.data_od.strftime('%d-%m-%Y')} – "
                f"{self.data_do.strftime('%d-%m-%Y')}"
            )
        return self.data_od.strftime('%d-%m-%Y')

    @property
    def epoka_label(self) -> str:
        """
        Czytelna nazwa epoki (do template)
        """
        return {
            "starozytna": "Starożytna",
            "sredniowieczna": "Średniowieczna",
            "wspolczesna": "Współczesna",
        }.get(self.epoka, self.epoka)

    def __repr__(self) -> str:
        return (
            f"<Historia {self.HISTORIA_ID} | "
            f"{self.nazwa_wydarzenia} | "
            f"{self.zakres_dat_label}>"
        )




