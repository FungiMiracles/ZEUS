# models.py
from sqlalchemy import BigInteger, DateTime
from extensions import db
from datetime import datetime
from sqlalchemy.orm import deferred, selectinload, Session, with_loader_criteria
from sqlalchemy import event


@event.listens_for(Session, 'do_orm_execute')
def _active_countries_only(state):
    """One visibility policy for lists, scalar projections, aggregates and joins.

    Maintenance/audit code may explicitly opt in to archived country records.
    Applies to Flask sessions and standalone scheduler/service sessions alike.
    """
    if state.is_select and not state.execution_options.get('include_deleted_countries'):
        state.statement = state.statement.options(with_loader_criteria(
            Panstwo, lambda country: country.status == 'aktywne', include_aliases=True,
        ))

class Panstwo(db.Model):
    __tablename__ = "panstwa"

    PANSTWO_ID = db.Column(db.Integer, primary_key=True)
    status = db.Column(db.String(16), nullable=False, default='aktywne', server_default='aktywne')
    __table_args__ = (db.CheckConstraint("status IN ('aktywne', 'usunięte')", name='ck_panstwa_status'),)
    panstwo_nazwa = db.Column(db.String(255))
    panstwo_kod = db.Column(db.String(255))
    panstwo_pelna_nazwa = db.Column(db.String(255))
    ustroj_id = db.Column(
        db.Integer,
        db.ForeignKey("dict_panstwo_ustroj.ustroj_id")
    )
    panstwo_populacja = db.Column(BigInteger)
    panstwo_PKB = db.Column(BigInteger)
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
    kadencja_przywodcy = db.Column(db.Integer)

    miasta = db.relationship("Miasto", backref="panstwo", lazy=True)
    regiony = db.relationship("Region", backref="panstwo", lazy=True)
    ustroj = db.relationship("DictPanstwoUstroj")

    zwierzch_panstwo_id = db.Column(
        db.Integer,
        db.ForeignKey("panstwa.PANSTWO_ID"),
        nullable=True
    )

    zwierzch_panstwo = db.relationship(
        "Panstwo",
        remote_side=[PANSTWO_ID],
        foreign_keys=[zwierzch_panstwo_id]
    )

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
    region_powierzchnia = db.Column(BigInteger)
    terytorium_zamorskie = db.Column(db.Boolean, nullable=False, default=False, server_default=db.text("0"))

    # USUNIĘTE:
    # region_populacja = db.Column(db.BigInteger)

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
    region_degradacja_srodowiska = db.Column(db.Integer)
    region_zanieczyszczenie_powietrza = db.Column(db.Integer)

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

    miasta = db.relationship(
        "Miasto",
        backref="region",
        lazy=True
    )

    region_teren_id = db.Column(
        db.Integer,
        db.ForeignKey("dict_region_tereny.id")
    )

    teren = db.relationship("DictRegionTeren")

    region_polozenie_id = db.Column(
        db.Integer,
        db.ForeignKey("dict_region_polozenia.id")
    )

    polozenie = db.relationship(
        "DictRegionPolozenie",
        foreign_keys=[region_polozenie_id]
    )

    region_typ_nadrz_id = db.Column(
        db.Integer,
        db.ForeignKey("dict_region_typy.id")
    )

    typ_nadrz = db.relationship(
        "DictRegionTyp",
        foreign_keys=[region_typ_nadrz_id]
    )

    region_typ_podrz_id = db.Column(
        db.Integer,
        db.ForeignKey("dict_region_typy.id")
    )

    typ_podrz = db.relationship(
        "DictRegionTyp",
        foreign_keys=[region_typ_podrz_id]
    )

    procreg_infra_drogowa = db.Column(db.Float)
    procreg_infra_kolejowa = db.Column(db.Float)
    procreg_infra_energetyczna = db.Column(db.Float)
    procreg_infra_mieszkaniowa = db.Column(db.Float)
    procreg_infra_portowa = db.Column(db.Float)

    polkula = db.Column(
        db.Enum("NORTH", "SOUTH", name="polkula_enum"),
        nullable=True
    )

    roczny_przyrost_miasto_pct = db.Column(
        db.Numeric(10, 4),
        nullable=True
    )

    roczny_przyrost_wies_pct = db.Column(
        db.Numeric(10, 4),
        nullable=True
    )

    roczna_urbanizacja_pct = db.Column(
        db.Numeric(10, 4),
        nullable=True
    )

    # =========================================================
    # POPULACJA REGIONU — WYLICZANA DYNAMICZNIE
    # =========================================================

    @property
    def region_populacja(self):

        miasta_pop = sum(
            (m.miasto_populacja or 0)
            for m in self.miasta
        )

        return (
            (self.region_ludnosc_pozamiejska or 0)
            + miasta_pop
        )

# =====================================================
# ZŁOŻA ZASOBÓW
# =====================================================

class RegionZasob(db.Model):
    __tablename__ = "regiony_zasoby"

    id = db.Column(db.Integer, primary_key=True)

    region_id = db.Column(
        db.Integer,
        db.ForeignKey("regiony.region_id", ondelete="CASCADE"),
        nullable=False
    )

    zasob_id = db.Column(
        db.Integer,
        db.ForeignKey("dict_zasoby.zasob_id", ondelete="CASCADE"),
        nullable=False
    )

    zloze_ilosc = db.Column(db.BigInteger, default=0)

    region = db.relationship("Region")
    zasob = db.relationship("DictZasob")

    __table_args__ = (
        db.UniqueConstraint("region_id", "zasob_id", name="uq_region_resource"),
    )


class CountryMiningSettings(db.Model):
    __tablename__ = "country_mining_settings"

    panstwo_id = db.Column(
        db.Integer, db.ForeignKey("panstwa.PANSTWO_ID", ondelete="CASCADE"), primary_key=True,
    )
    technology = db.Column(db.SmallInteger, nullable=False, default=0, server_default="0")
    version = db.Column(db.Integer, nullable=False, default=1, server_default="1")

    __mapper_args__ = {"version_id_col": version}
    __table_args__ = (
        db.CheckConstraint("technology BETWEEN 0 AND 100", name="ck_mining_technology"),
    )

# =====================================================
# INFRASTRUKTURA REGIONALNA
# =====================================================

class RegionInfrastruktura(db.Model):
    __tablename__ = "regiony_infrastruktura"

    id = db.Column(db.Integer, primary_key=True)

    region_id = db.Column(
        db.Integer,
        db.ForeignKey("regiony.region_id", ondelete="CASCADE"),
        nullable=False
    )

    budynek_id = db.Column(
        db.Integer,
        db.ForeignKey("dict_infrastruktura.budynek_id", ondelete="CASCADE"),
        nullable=False
    )

    budynek_poziom = db.Column(db.Integer, default=1)
    budynek_sprawnosc = db.Column(db.Integer, default=100)

    region = db.relationship("Region")
    budynek = db.relationship("DictInfrastruktura")

# =====================================================
# MAGAZYNY REGIONALNE
# =====================================================

class RegionMagazyn(db.Model):
    __tablename__ = "regiony_magazyny"

    id = db.Column(db.Integer, primary_key=True)

    region_id = db.Column(
        db.Integer,
        db.ForeignKey("regiony.region_id", ondelete="CASCADE"),
        nullable=False
    )

    zasob_id = db.Column(
        db.Integer,
        db.ForeignKey("dict_zasoby.zasob_id", ondelete="CASCADE"),
        nullable=False
    )

    zasob_ilosc = db.Column(db.BigInteger, default=0)

    region = db.relationship("Region")
    zasob = db.relationship("DictZasob")

# =====================================================
# BUDŻETY REGIONALNE
# =====================================================

class RegionBudzet(db.Model):
    __tablename__ = "region_budzet"

    id = db.Column(db.Integer, primary_key=True)

    region_id = db.Column(
        db.Integer,
        db.ForeignKey("regiony.region_id", ondelete="CASCADE"),
        nullable=False
    )

    rok = db.Column(db.Integer, nullable=False)

    budzet_roczny = db.Column(db.BigInteger, default=0)

    region = db.relationship("Region")

# =====================================================
# PRODUKCJA BUDYNKÓW
# =====================================================

class BudynekProdukcja(db.Model):
    __tablename__ = "budynki_produkcja"

    id = db.Column(db.Integer, primary_key=True)

    budynek_id = db.Column(
        db.Integer,
        db.ForeignKey("dict_infrastruktura.budynek_id"),
        nullable=False
    )

    zasob_wejsciowy_id = db.Column(
        db.Integer,
        db.ForeignKey("dict_zasoby.zasob_id"),
        nullable=False
    )

    ilosc_wejsciowa = db.Column(db.Numeric(18, 2))

    zasob_wyjsciowy_id = db.Column(
        db.Integer,
        db.ForeignKey("dict_zasoby.zasob_id"),
        nullable=False
    )

    ilosc_wyjsciowa = db.Column(db.Numeric(18, 2))

    max_produkcja_miesieczna = db.Column(db.Numeric(18, 2))

    budynek = db.relationship("DictInfrastruktura")

    zasob_wejsciowy = db.relationship(
        "DictZasob",
        foreign_keys=[zasob_wejsciowy_id]
    )

    zasob_wyjsciowy = db.relationship(
        "DictZasob",
        foreign_keys=[zasob_wyjsciowy_id]
    )

zasoby = db.relationship("RegionZasob", backref="region_obj", lazy=True)
infrastruktura = db.relationship("RegionInfrastruktura", backref="region_obj", lazy=True)
magazyny = db.relationship("RegionMagazyn", backref="region_obj", lazy=True)
budzety = db.relationship("RegionBudzet", backref="region_obj", lazy=True)

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
    czy_portowe = db.Column(db.Enum("TAK", "NIE", name="czy_portowe_enum"), nullable=False, default="NIE")

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
    rakiety_krotkiego_zasiegu = db.Column(db.BigInteger, nullable=False, default=0, server_default=db.text("0"))
    rakiety_sredniego_zasiegu = db.Column(db.BigInteger, nullable=False, default=0, server_default=db.text("0"))
    rakiety_dalekiego_zasiegu = db.Column(db.BigInteger, nullable=False, default=0, server_default=db.text("0"))
    # Poziom wyszkolenia (0–1000); w bitwie mnożnik = poziom / 100 (100 = ×1).
    wyszkolenie_ladowe = db.Column(db.Integer, nullable=False, default=100, server_default=db.text("100"))
    wyszkolenie_morskie = db.Column(db.Integer, nullable=False, default=100, server_default=db.text("100"))
    wyszkolenie_powietrzne = db.Column(db.Integer, nullable=False, default=100, server_default=db.text("100"))

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
    wzrost_pkb = db.Column(db.DECIMAL(10, 2))
    bezrobocie = db.Column(db.Float)

    # SEKTORY
    sektor_uslugi_pct = db.Column(db.Float)
    sektor_przemysl_pct = db.Column(db.Float)
    sektor_rolnictwo_pct = db.Column(db.Float)

    # HANDEL
    eksport_wartosc = db.Column(db.BigInteger)
    import_wartosc = db.Column(db.BigInteger)
    
    # BUDŻET
    dlug_pct_pkb = db.Column(db.Float)

    # ENERGIA
    energia_nieodnawialne_pct = db.Column(db.Float)
    energia_odnawialne_pct = db.Column(db.Float)
    energia_atomowa_pct = db.Column(db.Float)

    indeks_korupcji_gosp = db.Column(db.Float)
    indeks_innowacji_gosp = db.Column(db.Float)

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

class AudytStosunki(db.Model):
    __tablename__ = "audyt_stosunki"

    id = db.Column(
        db.Integer,
        primary_key=True,
        autoincrement=True
    )

    panstwo_id = db.Column(
        db.Integer,
        db.ForeignKey("panstwa.PANSTWO_ID"),
        nullable=False
    )

    panstwo_id2 = db.Column(
        db.Integer,
        db.ForeignKey("panstwa.PANSTWO_ID"),
        nullable=False
    )

    relacja_id = db.Column(
        db.Integer,
        nullable=False
    )

    stan_id = db.Column(
        db.Integer,
        nullable=False
    )

    data_zmiany_entenda = db.Column(
        db.DateTime,
        nullable=False
    )

    data_zmiany_rzeczywista = db.Column(
        db.DateTime,
        nullable=False
    )

    panstwo = db.relationship(
        "Panstwo",
        foreign_keys=[panstwo_id]
    )

    panstwo2 = db.relationship(
        "Panstwo",
        foreign_keys=[panstwo_id2]
    )


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

    przyklad_polski = db.Column(db.Text)
    przyklad_docelowy = db.Column(db.Text)

    jezyk_id = db.Column(db.Integer, primary_key=True)

    jezyk_rodzina_id = db.Column(
        db.Integer,
        db.ForeignKey("dict_jezyk_rodzina.jezyk_rodzina_id")
    )

    jezyk_rodzina = db.relationship("DictJezykRodzina")

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

    religia_id = db.Column(db.Integer, primary_key=True)

    religia_typ_id = db.Column(
        db.Integer,
        db.ForeignKey("dict_religia_typ.religia_typ_id")
    )

    religia_typ = db.relationship("DictReligiaTyp")

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

    effect_applied = db.Column(db.Boolean, default=False)

    status = db.Column(
        db.Enum("aktywne", "zakonczone", "archiwalne"),
        default="aktywne"
    )

    wariant = db.Column(db.String(20))

    created_at = db.Column(db.DateTime, default=db.func.now())

    payload_json = db.Column(db.JSON)

    data_archiwizacji = db.Column(
        db.DateTime,
        nullable=True
    )

    data_usuniecia = db.Column(
        db.DateTime,
        nullable=True
    )

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
    delta_degradacja_srodowiska = db.Column(db.Float, default=0)
    delta_zanieczyszczenie_powietrza = db.Column(db.Float, default=0)

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
        cascade="all, delete-orphan",
        passive_deletes=True
    )

    siedziba = db.Column(db.String(255))

class OrganizacjaPanstwo(db.Model):
    __tablename__ = "organizacja_per_panstwo"

    ID = db.Column(db.Integer, primary_key=True)

    org_id = db.Column(
        db.Integer,
        db.ForeignKey("dict_org_miedzy.ORG_ID", ondelete="CASCADE"),
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

    panstwo = db.relationship(
        "Panstwo",
        backref="organizacje",
        lazy=True
    )

class AudytOrganizacje(db.Model):
    __tablename__ = "audyt_organizacje"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

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

    data_zmiany_entenda = db.Column(db.DateTime, nullable=False)
    data_zmiany_rzeczywista = db.Column(db.DateTime, nullable=False)

    organizacja = db.relationship("OrganizacjaMiedzynarodowa")
    panstwo = db.relationship("Panstwo")

class Artykul(db.Model):
    __tablename__ = "artykuly"

    artykul_id = db.Column(db.Integer, primary_key=True)

    artykul_tytul = db.Column(db.Text, nullable=False)
    artykul_tresc = db.Column(db.Text, nullable=False)
    artykul_autor = db.Column(db.Text, nullable=False)

    data_utworzenia = db.Column(db.DateTime, default=datetime.now)
    data_publikacji = db.Column(db.Date)
    data_ostatniej_modyfikacji = db.Column(
        db.DateTime,
        default=datetime.now,
        onupdate=datetime.now
    )

    artykul_obraz = db.Column(db.LargeBinary)
    artykul_obraz_mime = db.Column(db.String(100))

class Flora(db.Model):
    __tablename__ = "flora"

    flora_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    nazwa = db.Column(db.String(50))
    opis = db.Column(db.Text)

    data_utworzenia = db.Column(db.DateTime, default=db.func.now())
    data_ostatniej_modyfikacji = db.Column(
        db.DateTime,
        default=db.func.now(),
        onupdate=db.func.now()
    )

    flora_obraz = db.Column(db.LargeBinary)
    flora_obraz_mime = db.Column(db.String(50))

    flora_panstwo = db.Table(
        "flora_panstwo",
        db.Column("flora_id", db.Integer, db.ForeignKey("flora.flora_id"), primary_key=True),
        db.Column("panstwo_id", db.Integer, db.ForeignKey("panstwa.PANSTWO_ID"), primary_key=True)
    )

    flora_kontynent = db.Table(
        "flora_kontynent",
        db.Column("flora_id", db.Integer, db.ForeignKey("flora.flora_id"), primary_key=True),
        db.Column("kontynent_id", db.Integer, db.ForeignKey("dict_kontynent.kontynent_id"), primary_key=True)
    )

    panstwa = db.relationship(
        "Panstwo",
        secondary=flora_panstwo,
        backref="flora_list",
        lazy="select"
    )

    kontynenty = db.relationship(
        "DictKontynent",
        secondary=flora_kontynent,
        backref="flora_list",
        lazy="select"
    )

# ================================
# Tabele pośrednie (M:N)
# ================================

fauna_panstwo = db.Table(
    "fauna_panstwo",
    db.Column("fauna_id", db.Integer, db.ForeignKey("fauna.fauna_id"), primary_key=True),
    db.Column("panstwo_id", db.Integer, db.ForeignKey("panstwa.PANSTWO_ID"), primary_key=True)
)

fauna_kontynent = db.Table(
    "fauna_kontynent",
    db.Column("fauna_id", db.Integer, db.ForeignKey("fauna.fauna_id"), primary_key=True),
    db.Column("kontynent_id", db.Integer, db.ForeignKey("dict_kontynent.kontynent_id"), primary_key=True)
)

# ================================
# MODEL
# ================================

class Fauna(db.Model):
    __tablename__ = "fauna"

    fauna_id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    nazwa = db.Column(db.String(100), nullable=False)
    opis = db.Column(db.Text)

    data_utworzenia = db.Column(
        db.DateTime,
        default=db.func.now()
    )

    data_ostatniej_modyfikacji = db.Column(
        db.DateTime,
        default=db.func.now(),
        onupdate=db.func.now()
    )

    fauna_obraz = db.Column(db.LargeBinary)
    fauna_obraz_mime = db.Column(db.String(50))

    # ================================
    # RELACJE M:N
    # ================================

    panstwa = db.relationship(
        "Panstwo",
        secondary=fauna_panstwo,
        lazy="selectin",
        backref=db.backref("fauna", lazy="selectin")
    )

    kontynenty = db.relationship(
        "DictKontynent",
        secondary=fauna_kontynent,
        lazy="selectin",
        backref=db.backref("fauna", lazy="selectin")
    )

    # ================================
    # HELPERY (do templatek)
    # ================================

    @property
    def panstwa_names(self):
        if not self.panstwa:
            return None
        return ", ".join(p.panstwo_nazwa for p in self.panstwa)

    @property
    def kontynenty_names(self):
        if not self.kontynenty:
            return None
        return ", ".join(k.kontynent_nazwa for k in self.kontynenty)

    @property
    def panstwa_names(self):
        return ", ".join(p.panstwo_nazwa for p in self.panstwa) if self.panstwa else None

    @property
    def kontynenty_names(self):
        return ", ".join(k.kontynent_nazwa for k in self.kontynenty) if self.kontynenty else None

    def __repr__(self):
        return f"<Fauna {self.fauna_id} | {self.nazwa}>"

class Droga(db.Model):
    __tablename__ = "drogi"

    droga_id = db.Column(
        db.Integer,
        primary_key=True,
        autoincrement=True
    )

    droga_kod = db.Column(
        db.String(20),
        unique=True,
        nullable=False
    )

    droga_rodzaj = db.Column(
        db.String(30),
        nullable=False
    )

class Spoleczenstwo(db.Model):
    __tablename__ = "spoleczenstwo"

    spoleczenstwo_id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    panstwo_id = db.Column(
        db.Integer,
        db.ForeignKey("panstwa.PANSTWO_ID", ondelete="CASCADE"),
        nullable=False,
        unique=True
    )

    panstwo = db.relationship(
        "Panstwo",
        backref=db.backref("spoleczenstwo", uselist=False)
    )

    stabilnosc_spoleczna = db.Column(db.Integer)
    zadowolenie_spoleczne = db.Column(db.Integer)
    nierownosci_spoleczne = db.Column(db.Integer)
    poziom_edukacji = db.Column(db.Integer)
    swiadomosc_spoleczna = db.Column(db.Integer)
    zaufanie_do_wladzy = db.Column(db.Integer)
    napiecia_religijne = db.Column(db.Integer)
    napiecia_etniczne = db.Column(db.Integer)
    napiecia_klasowe = db.Column(db.Integer)
    przestepczosc = db.Column(db.Integer)
    radykalizacja_spoleczna = db.Column(db.Integer)
    spojnosc_spoleczna = db.Column(db.Integer)
    tozsamosc_narodowa = db.Column(db.Integer)
    konserwatyzm_spoleczny = db.Column(db.Integer)
    otwartosc_spoleczna = db.Column(db.Integer)
    spozycie_alkoholu = db.Column(db.Integer)
    spozycie_narkotykow = db.Column(db.Integer)
    zdrowie_publiczne = db.Column(db.Integer)

class Przywodztwo(db.Model):
    __tablename__ = "przywodztwo"

    przywodca_id = db.Column(db.Integer, primary_key=True)

    przywodca_typ_id = db.Column(
        db.Integer,
        db.ForeignKey("dict_przywodca_typ.id"),
        nullable=False
    )

    panstwo_id = db.Column(
        db.Integer,
        db.ForeignKey("panstwa.PANSTWO_ID"),
        nullable=False
    )

    przywodca_imie = db.Column(db.String(55))
    przywodca_nazwisko = db.Column(db.String(55))

    data_entenda_od = db.Column(db.Date)
    data_entenda_do = db.Column(db.Date)

    panstwo = db.relationship("Panstwo")
    typ = db.relationship("DictPrzywodcaTyp")

class RegionStateHistory(db.Model):
    __tablename__ = "region_state_history"

    id = db.Column(db.BigInteger().with_variant(db.Integer, "sqlite"), primary_key=True, autoincrement=True)

    region_id = db.Column(
        db.Integer,
        db.ForeignKey("regiony.region_id"),  # ✅ poprawna nazwa tabeli
        nullable=False
    )

    data_entenda = db.Column(db.DateTime, nullable=False)
    data_rzeczywista = db.Column(db.DateTime, nullable=False)

    source = db.Column(db.String(20), nullable=False)  # EVENT / REGEN / ADMIN / SYSTEM
    event_id = db.Column(db.Integer, nullable=True)

    # ================= POPULACJA =================
    old_ludnosc = db.Column(db.BigInteger)
    new_ludnosc = db.Column(db.BigInteger)

    # ================= INFRA =================
    old_drogi = db.Column(db.SmallInteger)
    new_drogi = db.Column(db.SmallInteger)

    old_kolej = db.Column(db.SmallInteger)
    new_kolej = db.Column(db.SmallInteger)

    old_energia = db.Column(db.SmallInteger)
    new_energia = db.Column(db.SmallInteger)

    old_mieszkania = db.Column(db.SmallInteger)
    new_mieszkania = db.Column(db.SmallInteger)

    old_porty = db.Column(db.SmallInteger)
    new_porty = db.Column(db.SmallInteger)

    old_zanieczyszczenie_powietrza = db.Column(db.Integer)
    new_zanieczyszczenie_powietrza = db.Column(db.Integer)

    old_degradacja_srodowiska = db.Column(db.Integer)
    new_degradacja_srodowiska = db.Column(db.Integer)

    # ================= RELACJA =================
    region = db.relationship("Region", backref="state_history")

    # ================= INDEKSY =================
    __table_args__ = (
        db.Index("idx_region_state_history_region", "region_id"),
        db.Index("idx_region_state_history_entenda", "data_entenda"),
    )

class HistoriaPopulacjiPanstw(db.Model):
    __tablename__ = "historia_populacji_panstw"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    panstwo_id = db.Column(
        db.Integer,
        db.ForeignKey("panstwa.PANSTWO_ID", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    panstwo_populacja = db.Column(
        db.BigInteger,
        nullable=False
    )

    data_entenda = db.Column(
        db.Date,
        nullable=False,
        index=True
    )

    data_rzeczywista = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now(),
        index=True
    )

    panstwo = db.relationship(
        "Panstwo",
        backref=db.backref(
            "historia_populacji",
            lazy=True,
            cascade="all, delete-orphan"
        )
    )

    __table_args__ = (
        db.Index(
            "idx_hpp_panstwo_data",
            "panstwo_id",
            "data_entenda"
        ),
    )

class MiastoStateHistory(db.Model):
    __tablename__ = "miasto_state_history"

    id = db.Column(
        db.BigInteger,
        primary_key=True,
        autoincrement=True
    )

    miasto_id = db.Column(
        db.Integer,
        db.ForeignKey("miasta.miasto_id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    data_entenda = db.Column(
        db.Date,
        nullable=False,
        index=True
    )

    data_rzeczywista = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now(),
        index=True
    )

    source = db.Column(
        db.String(100),
        nullable=False,
        index=True
    )

    event_id = db.Column(
        db.BigInteger,
        nullable=True,
        index=True
    )

    old_miasto_populacja = db.Column(
        db.BigInteger,
        nullable=True
    )

    new_miasto_populacja = db.Column(
        db.BigInteger,
        nullable=True
    )

    change_delta = db.Column(
        db.BigInteger,
        nullable=False,
        default=0
    )

    miasto = db.relationship(
        "Miasto",
        backref=db.backref(
            "state_history",
            lazy=True,
            cascade="all, delete-orphan"
        )
    )

    __table_args__ = (
        db.Index(
            "idx_msh_miasto_data",
            "miasto_id",
            "data_entenda"
        ),
    )

class ZdarzeniaSystemowe(db.Model):
    __tablename__ = "zdarzenia_systemowe"

    id = db.Column(
        db.BigInteger,
        primary_key=True,
        autoincrement=True
    )

    zdarzenie_systemowe_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "dict_zdarzenia_systemowe.zdarzenie_systemowe_id"
        ),
        nullable=False,
        index=True
    )

    data_entenda = db.Column(
        db.Date,
        nullable=False,
        index=True
    )

    data_rzeczywista = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now(),
        index=True
    )

    opis = db.Column(
        db.Text,
        nullable=True
    )

    zdarzenie = db.relationship(
        "DictZdarzeniaSystemowe",
        backref=db.backref(
            "logi",
            lazy=True
        )
    )

    __table_args__ = (
        db.UniqueConstraint(
            "zdarzenie_systemowe_id",
            "data_entenda",
            name="uq_zs_event_data"
        ),
        db.Index(
            "idx_zs_event_data",
            "zdarzenie_systemowe_id",
            "data_entenda"
        ),
    )

class PKBStateHistory(db.Model):
    __tablename__ = "pkb_state_history"

    id = db.Column(
        db.BigInteger,
        primary_key=True,
        autoincrement=True
    )

    panstwo_id = db.Column(
        db.Integer,
        db.ForeignKey("panstwa.PANSTWO_ID", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    data_entenda = db.Column(
        db.Date,
        nullable=False,
        index=True
    )

    data_rzeczywista = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now(),
        index=True
    )

    source = db.Column(
        db.String(100),
        nullable=False,
        index=True
    )

    event_id = db.Column(
        db.BigInteger,
        nullable=True,
        index=True
    )

    old_pkb = db.Column(
        db.BigInteger,
        nullable=True
    )

    new_pkb = db.Column(
        db.BigInteger,
        nullable=True
    )

    change_delta = db.Column(
        db.BigInteger,
        nullable=False,
        default=0
    )

    panstwo = db.relationship(
        "Panstwo",
        backref=db.backref(
            "pkb_history",
            lazy=True,
            cascade="all, delete-orphan"
        )
    )

    __table_args__ = (
        db.Index(
            "idx_psh_panstwo_data",
            "panstwo_id",
            "data_entenda"
        ),
    )

class ProcentWzrostuStateHistory(db.Model):
    __tablename__ = "procent_wzrostu_state_history"

    id = db.Column(
        db.BigInteger,
        primary_key=True,
        autoincrement=True
    )

    panstwo_id = db.Column(
        db.Integer,
        db.ForeignKey("panstwa.PANSTWO_ID", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    data_entenda = db.Column(
        db.Date,
        nullable=False,
        index=True
    )

    data_rzeczywista = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now(),
        index=True
    )

    source = db.Column(
        db.String(100),
        nullable=False,
        index=True
    )

    event_id = db.Column(
        db.BigInteger,
        nullable=True,
        index=True
    )

    old_wzrost = db.Column(
        db.Numeric(10, 4),
        nullable=True
    )

    new_wzrost = db.Column(
        db.Numeric(10, 4),
        nullable=True
    )

    change_delta = db.Column(
        db.Numeric(10, 4),
        nullable=False,
        default=0
    )

    panstwo = db.relationship(
        "Panstwo",
        backref=db.backref(
            "wzrost_history",
            lazy=True,
            cascade="all, delete-orphan"
        )
    )

    __table_args__ = (
        db.Index(
            "idx_pwsh_panstwo_data",
            "panstwo_id",
            "data_entenda"
        ),
    )

class RocznyPrzyrostStateHistory(db.Model):
    __tablename__ = "roczny_przyrost_state_history"

    id = db.Column(db.Integer, primary_key=True)

    panstwo_id = db.Column(
        db.Integer,
        db.ForeignKey("panstwa.PANSTWO_ID"),
        nullable=False
    )

    data_entenda = db.Column(db.DateTime, nullable=False)

    data_rzeczywista = db.Column(db.DateTime, nullable=False)

    event_id = db.Column(
        db.Integer,
        db.ForeignKey("zdarzenia.zdarzenie_id"),
        nullable=True
    )

    old_roczny_przyrost = db.Column(db.Float)

    new_roczny_przyrost = db.Column(db.Float)

    panstwo = db.relationship("Panstwo")
    event = db.relationship("Zdarzenie")

class PKBPCStateHistory(db.Model):
    __tablename__ = "pkbpc_state_history"

    id = db.Column(
        db.BigInteger,
        primary_key=True,
        autoincrement=True
    )

    panstwo_id = db.Column(
        db.Integer,
        db.ForeignKey("panstwa.PANSTWO_ID", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    data_entenda = db.Column(
        db.Date,
        nullable=False,
        index=True
    )

    data_rzeczywista = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now(),
        index=True
    )

    source = db.Column(
        db.String(100),
        nullable=False,
        index=True
    )

    event_id = db.Column(
        db.BigInteger,
        nullable=True,
        index=True
    )

    old_pkbpc = db.Column(
        db.BigInteger,
        nullable=True
    )

    new_pkbpc = db.Column(
        db.BigInteger,
        nullable=True
    )

    change_delta = db.Column(
        db.BigInteger,
        nullable=False,
        default=0
    )

    panstwo = db.relationship(
        "Panstwo",
        backref=db.backref(
            "pkbpc_history",
            lazy=True,
            cascade="all, delete-orphan"
        )
    )

    __table_args__ = (
        db.Index(
            "idx_pkbpcsh_panstwo_data",
            "panstwo_id",
            "data_entenda"
        ),
    )

class SpoleczenstwoStateHistory(db.Model):
    __tablename__ = "spoleczenstwo_state_history"

    id = db.Column(
        db.BigInteger,
        primary_key=True,
        autoincrement=True
    )

    panstwo_id = db.Column(
        db.Integer,
        db.ForeignKey("panstwa.PANSTWO_ID", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    data_entenda = db.Column(
        db.Date,
        nullable=False,
        index=True
    )

    data_rzeczywista = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now(),
        index=True
    )

    source = db.Column(
        db.String(100),
        nullable=False,
        index=True
    )

    event_id = db.Column(
        db.BigInteger,
        nullable=True,
        index=True
    )

    # =========================
    # OLD VALUES
    # =========================

    old_stabilnosc = db.Column(db.Numeric(10, 4))
    old_zadowolenie = db.Column(db.Numeric(10, 4))
    old_nierownosci = db.Column(db.Numeric(10, 4))
    old_edukacja = db.Column(db.Numeric(10, 4))
    old_swiadomosc = db.Column(db.Numeric(10, 4))
    old_zaufanie = db.Column(db.Numeric(10, 4))

    old_napiecia_religijne = db.Column(db.Numeric(10, 4))
    old_napiecia_etniczne = db.Column(db.Numeric(10, 4))
    old_napiecia_klasowe = db.Column(db.Numeric(10, 4))

    old_przestepczosc = db.Column(db.Numeric(10, 4))
    old_radykalizacja = db.Column(db.Numeric(10, 4))

    old_spojnosc = db.Column(db.Numeric(10, 4))
    old_tozsamosc = db.Column(db.Numeric(10, 4))
    old_konserwatyzm = db.Column(db.Numeric(10, 4))
    old_otwartosc = db.Column(db.Numeric(10, 4))

    # OLD
    old_spozycie_alkoholu = db.Column(db.Numeric(10, 4))
    old_spozycie_narkotykow = db.Column(db.Numeric(10, 4))
    old_zdrowie_publiczne = db.Column(db.Numeric(10, 4))

    # =========================
    # NEW VALUES
    # =========================

    new_stabilnosc = db.Column(db.Numeric(10, 4))
    new_zadowolenie = db.Column(db.Numeric(10, 4))
    new_nierownosci = db.Column(db.Numeric(10, 4))
    new_edukacja = db.Column(db.Numeric(10, 4))
    new_swiadomosc = db.Column(db.Numeric(10, 4))
    new_zaufanie = db.Column(db.Numeric(10, 4))

    new_napiecia_religijne = db.Column(db.Numeric(10, 4))
    new_napiecia_etniczne = db.Column(db.Numeric(10, 4))
    new_napiecia_klasowe = db.Column(db.Numeric(10, 4))

    new_przestepczosc = db.Column(db.Numeric(10, 4))
    new_radykalizacja = db.Column(db.Numeric(10, 4))

    new_spojnosc = db.Column(db.Numeric(10, 4))
    new_tozsamosc = db.Column(db.Numeric(10, 4))
    new_konserwatyzm = db.Column(db.Numeric(10, 4))
    new_otwartosc = db.Column(db.Numeric(10, 4))

    new_spozycie_alkoholu = db.Column(db.Numeric(10, 4))
    new_spozycie_narkotykow = db.Column(db.Numeric(10, 4))
    new_zdrowie_publiczne = db.Column(db.Numeric(10, 4))

    panstwo = db.relationship(
        "Panstwo",
        backref=db.backref(
            "spoleczenstwo_history",
            lazy=True,
            cascade="all, delete-orphan"
        )
    )

    __table_args__ = (
        db.Index(
            "idx_ssh_panstwo_data",
            "panstwo_id",
            "data_entenda"
        ),
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

class DictReligiaTyp(db.Model):
    __tablename__ = "dict_religia_typ"

    religia_typ_id = db.Column(db.Integer, primary_key=True)
    nazwa = db.Column(db.String(100), unique=True, nullable=False)


class DictJezykRodzina(db.Model):
    __tablename__ = "dict_jezyk_rodzina"

    jezyk_rodzina_id = db.Column(db.Integer, primary_key=True)
    nazwa = db.Column(db.String(100), unique=True, nullable=False)

class DictZdarzeniaSystemowe(db.Model):
    __tablename__ = "dict_zdarzenia_systemowe"

    zdarzenie_systemowe_id = db.Column(
        db.Integer,
        primary_key=True
    )

    zdarzenie_systemowe_nazwa = db.Column(
        db.String(255),
        nullable=False,
        unique=True
    )

    zdarzenie_systemowe_opis = db.Column(
        db.Text,
        nullable=True
    )

class DictZasob(db.Model):
    __tablename__ = "dict_zasoby"

    zasob_id = db.Column(db.Integer, primary_key=True)
    zasob_kod = db.Column(db.String(50), unique=True, nullable=False)
    zasob_nazwa = db.Column(db.String(255), nullable=False)
    zasob_kategoria = db.Column(db.String(100), nullable=False)
    zasob_jednostka = db.Column(db.String(50), nullable=False)

    cena_bazowa = db.Column(db.Numeric(18, 2), default=0)

    czy_strategiczny = db.Column(db.String(3), default="NIE")
    czy_wydobywalny = db.Column(db.String(3), default="NIE")

# =====================================================
# INFRASTRUKTURA
# =====================================================

class DictInfrastruktura(db.Model):
    __tablename__ = "dict_infrastruktura"

    budynek_id = db.Column(db.Integer, primary_key=True)

    budynek_kod = db.Column(db.String(50), unique=True, nullable=False)
    budynek_nazwa = db.Column(db.String(255), nullable=False)

    budynek_kategoria = db.Column(db.String(100))
    budynek_funkcja = db.Column(db.Text)

    czy_strategiczny = db.Column(db.String(3), default="NIE")

    budynek_koszt = db.Column(db.BigInteger, default=0)
    utrzymanie_koszt = db.Column(db.BigInteger, default=0)

class DictPrzywodcaTyp(db.Model):
    __tablename__ = "dict_przywodca_typ"

    id = db.Column(db.Integer, primary_key=True)

    przywodca_typ = db.Column(db.String(55))
