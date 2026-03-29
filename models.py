# models.py
from sqlalchemy import BigInteger, DateTime
from extensions import db
from datetime import datetime
from sqlalchemy.orm import deferred, selectinload

class Panstwo(db.Model):
    __tablename__ = "panstwa"

    PANSTWO_ID = db.Column(db.Integer, primary_key=True)
    panstwo_nazwa = db.Column(db.String(255))
    panstwo_kod = db.Column(db.String(255))
    panstwo_pelna_nazwa = db.Column(db.String(255))
    ustroj_id = db.Column(
        db.Integer,
        db.ForeignKey("dict_panstwo_ustroj.ustroj_id")
    )
    panstwo_stolica = db.Column(db.String(255))
    panstwo_populacja = db.Column(BigInteger)
    panstwo_PKB = db.Column(BigInteger)
    panstwo_PKB_per_capita = db.Column(BigInteger)
    panstwo_waluta = db.Column(db.String(255))
    panstwo_jezyk = db.Column(db.String(255))
    panstwo_religia = db.Column(db.String(255))
    kontynent_id = db.Column(
        db.Integer,
        db.ForeignKey("dict_kontynent.kontynent_id")
    )
    panstwo_powierzchnia = db.Column(BigInteger)
    panstwo_opis = deferred(db.Column(db.Text))
    opis_updated_at = db.Column(db.DateTime)
    panstwo_populacja_audit = db.Column(DateTime)
    panstwo_opis_audit = db.Column(DateTime)
    czy_suwerenny = db.Column(
        db.String(3),
        nullable=False,
        default="TAK"
    )

    miasta = db.relationship("Miasto", backref="panstwo", lazy=True)
    regiony = db.relationship("Region", backref="panstwo", lazy=True)
    ustroj = db.relationship("DictPanstwoUstroj")


class Region(db.Model):
    __tablename__ = "regiony"

    # ===== KLUCZE =====
    region_id = db.Column(db.Integer, primary_key=True)
    panstwo_id = db.Column(
        db.Integer,
        db.ForeignKey("panstwa.PANSTWO_ID"),
        nullable=False
    )

    # ===== PODSTAWOWE DANE =====
    region_nazwa = db.Column(db.String(255), nullable=False)

    region_populacja = db.Column(db.BigInteger)

    region_ludnosc_pozamiejska = db.Column(
        db.BigInteger,
        nullable=False,
        default=0
    )

    # ===== WSKAŹNIKI (0–100) =====

    region_poziom_skomunikowania = db.Column(db.SmallInteger)
    region_sejsmicznosc = db.Column(db.SmallInteger)
    region_ryzyko_powodzi = db.Column(db.SmallInteger)
    region_ryzyko_lawin = db.Column(db.SmallInteger)
    region_ryzyko_upalu = db.Column(db.SmallInteger)
    region_ryzyko_mrozu = db.Column(db.SmallInteger)
    region_aktywny_wulkan = db.Column(db.SmallInteger)

    # ===== STAN INFRASTRUKTURY (0–100) =====

    region_stan_infra_kolejowej = db.Column(db.SmallInteger)
    region_stan_infra_drogowej = db.Column(db.SmallInteger)
    region_stan_infra_energetycznej = db.Column(db.SmallInteger)
    region_stan_infra_mieszkalnej = db.Column(db.SmallInteger)
    region_stan_infra_portowej = db.Column(db.SmallInteger)

    # ===== MAPA =====
    region_mapa = deferred(db.Column(db.LargeBinary, nullable=True))
    region_mapa_mime = db.Column(db.String(50), nullable=True)

    # ===== RELACJE =====
    miasta = db.relationship("Miasto", backref="region", lazy=True)

    region_teren_id = db.Column(db.Integer, db.ForeignKey("dict_region_tereny.id"))
    teren = db.relationship("DictRegionTeren")

    region_polozenie_id = db.Column(db.Integer, db.ForeignKey("dict_region_polozenia.id"))
    polozenie = db.relationship("DictRegionPolozenie", foreign_keys=[region_polozenie_id])

    region_typ_nadrz_id = db.Column(db.Integer, db.ForeignKey("dict_region_typy.id"))
    typ_nadrz = db.relationship("DictRegionTyp", foreign_keys=[region_typ_nadrz_id])

    region_typ_podrz_id = db.Column(db.Integer, db.ForeignKey("dict_region_typy.id"))
    typ_podrz = db.relationship("DictRegionTyp", foreign_keys=[region_typ_podrz_id])

    procreg_infra_drogowa = db.Column(db.Float)
    procreg_infra_kolejowa = db.Column(db.Float)
    procreg_infra_energetyczna = db.Column(db.Float)
    procreg_infra_mieszkaniowa = db.Column(db.Float)
    procreg_infra_portowa = db.Column(db.Float)

class Miasto(db.Model):
    __tablename__ = "miasta"

    miasto_id = db.Column(db.Integer, primary_key=True)
    panstwo_id = db.Column(db.Integer, db.ForeignKey("panstwa.PANSTWO_ID"))
    miasto_nazwa = db.Column(db.String(255))
    miasto_kod = db.Column(db.String(4))
    miasto_populacja = db.Column(db.Integer)
    miasto_typ_id = db.Column(
        db.Integer,
        db.ForeignKey("dict_miasto_typ.miasto_typ_id")
    )

    typ = db.relationship("DictMiastoTyp")
    region_id = db.Column(db.Integer, db.ForeignKey("regiony.region_id"))
    czy_na_mapie = db.Column(db.Enum("TAK", "NIE", name="czy_na_mapie_enum"), nullable=False, default="TAK")
    czy_generowane = db.Column(db.Enum("TAK", "NIE", name="czy_generowane_enum"), nullable=False, default="TAK")

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

    kontynent_id = db.Column(
        db.Integer,
        db.ForeignKey("dict_kontynent.kontynent_id"),
        nullable=True
    )

    kontynent_rel = db.relationship("DictKontynent")

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
    wydarzenie_opis = deferred(db.Column(db.Text))

    # =========================================================
    #  RELACJE (opcjonalnie, ale zalecane)
    # =========================================================
    panstwo = db.relationship("Panstwo", lazy="joined")
    region = db.relationship("Region", lazy="joined")
    miasto = db.relationship("Miasto", lazy="joined")

# =========================================================
#  COMPUTED / PRESENTATION PROPERTIES
# =========================================================
    @property
    def lokalizacja_label(self):
        parts = []
        if self.miasto:
            parts.append(self.miasto.miasto_nazwa)
        if self.region:
            parts.append(self.region.region_nazwa)
        if self.panstwo:
            parts.append(self.panstwo.panstwo_nazwa)

        return " → ".join(parts) if parts else "Brak lokalizacji"
    
    @property
    def zakres_dat_label(self) -> str:
        """
        Zwraca zakres dat w formacie:
        - 1200
        - 1200–1250
        """
        if not self.data_od:
            return "—"
    
        if self.data_do and self.data_do != self.data_od:
            return f"{self.data_od.year}–{self.data_do.year}"
    
        return str(self.data_od.year)
    
    
    @property
    def epoka_label(self) -> str:
        """
        Mapowanie ENUM → label UI
        """
        MAPA_EPOK = {
            "starozytna": "Starożytność",
            "sredniowieczna": "Średniowiecze",
            "wspolczesna": "Współczesność",
        }
    
        return MAPA_EPOK.get(self.epoka, "Nieznana epoka")
    
    @property
    def status_label(self):
        return "AKTYWNA" if self.aktywna else "NIEAKTYWNA"


    # =========================================================
    #  WŁAŚCIWOŚCI POMOCNICZE (LOGIKA)
    # =========================================================

class Stosunki(db.Model):
    __tablename__ = "stosunki"

    PANSTWO_ID = db.Column(
        db.Integer,
        db.ForeignKey("panstwa.PANSTWO_ID"),
        primary_key=True
    )
    PANSTWO_ID2 = db.Column(
        db.Integer,
        db.ForeignKey("panstwa.PANSTWO_ID"),
        primary_key=True
    )
    
    relacja_id = db.Column(
    db.Integer,
    db.ForeignKey("dict_stosunki_relacja.relacja_id")
    )

    stan_id = db.Column(
        db.Integer,
        db.ForeignKey("dict_stosunki_stan.stan_id")
    )

    panstwo = db.relationship(
    "Panstwo",
    foreign_keys=[PANSTWO_ID],
    lazy="joined"
    )

    panstwo2 = db.relationship(
        "Panstwo",
        foreign_keys=[PANSTWO_ID2],
        lazy="joined"
    )

    relacja = db.relationship("DictStosunkiRelacja")

    stan = db.relationship("DictStosunkiStan")


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

class Jezyk(db.Model):
    __tablename__ = "jezyki"

    jezyk_id = db.Column(db.Integer, primary_key=True)

    jezyk_nazwa = db.Column(db.Text, nullable=False)
    jezyk_kod = db.Column(db.String(2))
    jezyk_rodzina = db.Column(db.Text)

    przyklad_polski = db.Column(db.Text)
    przyklad_docelowy = db.Column(db.Text)

    opis = db.Column(db.Text)

    def __repr__(self):
        return f"<Jezyk {self.jezyk_nazwa}>"

class JezykiPerPanstwo(db.Model):
    __tablename__ = "jezyki_per_panstwo"

    id = db.Column(db.Integer, primary_key=True)

    panstwo_id = db.Column(
        db.Integer,
        db.ForeignKey("panstwa.PANSTWO_ID", ondelete="CASCADE"),
        nullable=False,
        unique=True
    )

    jezyk_urzedowy1 = db.Column(db.Integer, db.ForeignKey("jezyki.jezyk_id"))
    jezyk_urzedowy2 = db.Column(db.Integer, db.ForeignKey("jezyki.jezyk_id"))
    jezyk_urzedowy3 = db.Column(db.Integer, db.ForeignKey("jezyki.jezyk_id"))

    jezyk_urzedowy1_rel = db.relationship(
        "Jezyk",
        foreign_keys=[jezyk_urzedowy1],
        lazy="joined"
    )

    jezyk_mniejszosciowy1 = db.Column(db.Integer, db.ForeignKey("jezyki.jezyk_id"))
    jezyk_mniejszosciowy2 = db.Column(db.Integer, db.ForeignKey("jezyki.jezyk_id"))
    jezyk_mniejszosciowy3 = db.Column(db.Integer, db.ForeignKey("jezyki.jezyk_id"))
    jezyk_mniejszosciowy4 = db.Column(db.Integer, db.ForeignKey("jezyki.jezyk_id"))
    jezyk_mniejszosciowy5 = db.Column(db.Integer, db.ForeignKey("jezyki.jezyk_id"))

    panstwo = db.relationship(
        "Panstwo",
        backref=db.backref("profil_jezykowy", uselist=False)
    )

    def get_jezyki_urzedowe(self):
        return [
            self.jezyk_urzedowy1,
            self.jezyk_urzedowy2,
            self.jezyk_urzedowy3,
        ]

    def get_jezyki_mniejszosciowe(self):
        return [
            self.jezyk_mniejszosciowy1,
            self.jezyk_mniejszosciowy2,
            self.jezyk_mniejszosciowy3,
            self.jezyk_mniejszosciowy4,
            self.jezyk_mniejszosciowy5,
        ]

    def __repr__(self):
        return f"<JezykiPerPanstwo panstwo_id={self.panstwo_id}>"

class Religia(db.Model):
    __tablename__ = "religia"

    religia_id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    religia_nazwa = db.Column(db.String(255), unique=True, nullable=False)

    religia_typ = db.Column(
        db.Enum(
            "monoteistyczna",
            "politeistyczna",
            "henoteistyczna",
            "panteistyczna",
            "nonteistyczna",
            name="religia_typ_enum"
        ),
        nullable=False
    )

    opis = db.Column(db.Text)

    religia_obraz = deferred(db.Column(db.LargeBinary))
    religia_obraz_mime = db.Column(db.String(100))

    # Self-FK: religia nadrzędna (NULL = religia główna)
    religia_nadrzedna_id = db.Column(
        db.Integer,
        db.ForeignKey("religia.religia_id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True
    )

    # Relacja do religii nadrzędnej
    religia_nadrzedna = db.relationship(
        "Religia",
        remote_side=[religia_id],
        backref=db.backref("odlamy", lazy=True)
    )

    przypisania = db.relationship(
        "ReligiaPerPanstwo",
        cascade="all, delete-orphan",
        passive_deletes=True,
        back_populates="religia"
    )

    def __repr__(self):
        return f"<Religia {self.religia_nazwa}>"

class ReligiaPerPanstwo(db.Model):
    __tablename__ = "religia_per_panstwo"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    panstwo_id = db.Column(
        db.Integer,
        db.ForeignKey("panstwa.PANSTWO_ID", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False
    )

    religia_id = db.Column(
        db.Integer,
        db.ForeignKey("religia.religia_id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False
    )

    udzial_proc = db.Column(db.Float, nullable=True)

    status = db.Column(
        db.Enum(
            "dominujaca",
            "oficjalna",
            "mniejszosciowa",
            "historyczna",
            name="religia_status_enum"
        ),
        nullable=False
    )

    __table_args__ = (
        db.UniqueConstraint(
            "panstwo_id",
            "religia_id",
            name="uq_religia_per_panstwo"
        ),
    )

    # Relacje ORM
    panstwo = db.relationship("Panstwo", backref=db.backref("religie", lazy=True))
    religia = db.relationship(
        "Religia",
        back_populates="przypisania"
    )

    def __repr__(self):
        return (
            f"<ReligiaPerPanstwo panstwo_id={self.panstwo_id}, "
            f"religia_id={self.religia_id}, udzial={self.udzial_proc}%>"
        )
    
class Zdarzenie(db.Model):
    __tablename__ = "zdarzenia"

    zdarzenie_id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    zdarzenie_typ = db.Column(db.String(64), nullable=False)
    zdarzenie_kategoria = db.Column(db.String(64))

    panstwo_id = db.Column(db.Integer, db.ForeignKey("panstwa.PANSTWO_ID"))
    region_id = db.Column(db.Integer, db.ForeignKey("regiony.region_id"))
    miasto_id = db.Column(db.Integer, db.ForeignKey("miasta.miasto_id"))

    ilosc_ofiar = db.Column(db.Integer)
    skala = db.Column(db.Integer)

    opis_szablon_id = db.Column(db.Integer)
    opis_wygenerowany = db.Column(db.Text)

    data_entenda = db.Column(db.DateTime)
    data_rzeczywista = db.Column(db.DateTime)

    status = db.Column(
        db.Enum("aktywne", "zakonczone", "archiwalne"),
        default="aktywne"
    )

    created_at = db.Column(db.DateTime, default=db.func.now())

    payload_json = db.Column(db.JSON)

    # relacje
    panstwo = db.relationship("Panstwo", backref="zdarzenia", lazy=True)
    region = db.relationship("Region", backref="zdarzenia", lazy=True)
    miasto = db.relationship("Miasto", backref="zdarzenia", lazy=True)

class ZdarzenieSzablon(db.Model):
    __tablename__ = "zdarzenia_szablony"

    szablon_id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    zdarzenie_typ = db.Column(db.String(32), nullable=False)

    skala = db.Column(db.Integer, nullable=False)

    tresc = db.Column(db.Text, nullable=False)

    aktywny = db.Column(db.Boolean, default=True)

    waga = db.Column(db.Integer, default=1)

    wariant = db.Column(db.String(32))

    created_at = db.Column(db.DateTime, default=db.func.now())

class RegionalDataChange(db.Model):
    __tablename__ = "regional_data_change"

    id = db.Column(db.Integer, primary_key=True)

    region_id = db.Column(db.Integer, db.ForeignKey("regiony.region_id"), nullable=False)

    data_entenda = db.Column(db.Date, nullable=False)
    data_rzeczywista = db.Column(db.DateTime, nullable=False)

    source = db.Column(db.String(20), nullable=False)
    event_id = db.Column(db.Integer, nullable=True)

    delta_ludnosc_pozamiejska = db.Column(db.Integer, default=0)

    delta_infra_drogowa = db.Column(db.Float, default=0)
    delta_infra_kolejowa = db.Column(db.Float, default=0)
    delta_infra_energetyczna = db.Column(db.Float, default=0)
    delta_infra_mieszkaniowa = db.Column(db.Float, default=0)
    delta_infra_portowa = db.Column(db.Float, default=0)

class OrganizacjaMiedzynarodowa(db.Model):
    __tablename__ = "dict_org_miedzy"

    ORG_ID = db.Column(db.Integer, primary_key=True)

    org_nazwa = db.Column(db.String(255), nullable=False)
    org_skrot = db.Column(db.String(50))
    org_typ = db.Column(db.String(100))
    org_opis = db.Column(db.Text)

    czy_aktywna = db.Column(db.Boolean, default=True)

    data_utworzenia = db.Column(db.DateTime, default=db.func.now())

    # 🔗 relacja do państw
    czlonkowie = db.relationship(
        "OrganizacjaPanstwo",
        backref="organizacja",
        lazy=True
    )

    siedziba = db.Column(db.String(255))

class OrganizacjaPanstwo(db.Model):
    __tablename__ = "organizacja_per_panstwo"

    ID = db.Column(db.Integer, primary_key=True)

    org_id = db.Column(
        db.Integer,
        db.ForeignKey("dict_org_miedzy.ORG_ID"),
        nullable=False
    )

    panstwo_id = db.Column(
        db.Integer,
        db.ForeignKey("panstwa.PANSTWO_ID"),
        nullable=False
    )

    status_czlonkostwa = db.Column(db.String(50), nullable=False)

    data_dolaczenia = db.Column(db.DateTime, default=db.func.now())
    data_opuszczenia = db.Column(db.DateTime, nullable=True)

    czy_aktywny = db.Column(db.Boolean, default=True)

    # 🔗 relacja do państwa
    panstwo = db.relationship(
        "Panstwo",
        backref="organizacje",
        lazy=True
    )

#------------------------------------------------#
# SŁOWNIKI #
#------------------------------------------------#

class DictRegionTeren(db.Model):
    __tablename__ = "dict_region_tereny"

    id = db.Column(db.Integer, primary_key=True)
    kod = db.Column(db.String(50), unique=False)
    nazwa = db.Column(db.String(100))
    opis = db.Column(db.Text)

class DictRegionPolozenie(db.Model):
    __tablename__ = "dict_region_polozenia"
    id = db.Column(db.Integer, primary_key=True)
    kod = db.Column(db.String(50))
    nazwa = db.Column(db.String(100))
    opis = db.Column(db.Text)

class DictRegionTyp(db.Model):
    __tablename__ = "dict_region_typy"
    id = db.Column(db.Integer, primary_key=True)
    kod = db.Column(db.String(50))
    nazwa = db.Column(db.String(100))
    poziom = db.Column(db.Enum("NADRZ", "PODRZ"))
    opis = db.Column(db.Text)

class DictKontynent(db.Model):
    __tablename__ = "dict_kontynent"

    kontynent_id = db.Column(db.Integer, primary_key=True)
    kontynent_nazwa = db.Column(db.String(100), unique=True, nullable=False)

    panstwa = db.relationship("Panstwo", backref="kontynent_rel", lazy=True)

class DictPanstwoUstroj(db.Model):
    __tablename__ = "dict_panstwo_ustroj"

    ustroj_id = db.Column(db.Integer, primary_key=True)
    ustroj_nazwa = db.Column(db.String(100), nullable=False, unique=True)

class DictMiastoTyp(db.Model):
    __tablename__ = "dict_miasto_typ"

    miasto_typ_id = db.Column(db.Integer, primary_key=True)
    miasto_typ_nazwa = db.Column(db.String(100), nullable=False, unique=True)

class DictStosunkiRelacja(db.Model):
    __tablename__ = "dict_stosunki_relacja"

    relacja_id = db.Column(db.Integer, primary_key=True)
    relacja_nazwa = db.Column(db.String(50), nullable=False)

class DictStosunkiStan(db.Model):
    __tablename__ = "dict_stosunki_stan"

    stan_id = db.Column(db.Integer, primary_key=True)
    stan_nazwa = db.Column(db.String(50), nullable=False)
