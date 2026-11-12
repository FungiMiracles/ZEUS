"""Przydział złóż i technologii wydobywczych, bez własnego commit."""
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import lazyload

from extensions import db
from models import CountryMiningSettings, DictZasob, Panstwo, Region, RegionZasob

RESOURCES = (
    ("wegiel_kamienny", "Węgiel kamienny"),
    ("ropa_naftowa", "Ropa naftowa"),
    ("zloto", "Złoto"), ("srebro", "Srebro"), ("kamien", "Kamień"),
    ("natsyt", "Natsyt"), ("kerbit", "Kerbit"), ("cemium", "Cemium"), ("uran", "Uran"), ("zelazo", "Żelazo"),
)
MAX_QUANTITY = 9223372036854775807


class ResourceError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def normalized(value):
    return ''.join(char for char in unicodedata.normalize('NFKD', value.casefold().replace('ł', 'l'))
                   if char.isascii() and char.isalnum())


def resource_dictionary():
    rows = db.session.execute(select(DictZasob.zasob_id, DictZasob.zasob_kod, DictZasob.zasob_nazwa)).all()
    result = {}
    for code, name in RESOURCES:
        candidates = [row for row in rows if normalized(row.zasob_kod) == normalized(code)
                      or normalized(row.zasob_nazwa) == normalized(name)]
        if len(candidates) != 1:
            raise ResourceError(
                f"Słownik surowców wymaga przygotowania: {name}. Wykonaj przegląd skryptu SQL; oczekiwano jednej pozycji, znaleziono {len(candidates)}.", 409,
            )
        result[code] = candidates[0].zasob_id
    if len(set(result.values())) != len(RESOURCES):
        raise ResourceError("Jedna pozycja słownika odpowiada kilku surowcom. Uporządkuj słownik przed zapisem.", 409)
    return result


def field_name(region_id, code):
    return f"quantity_{region_id}_{code}"


def integer_value(value, maximum, label):
    text = value.strip()
    if not text or not text.isascii() or not text.isdecimal() or len(text) > 19:
        raise ResourceError(f"{label}: wpisz nieujemną liczbę całkowitą.")
    result = int(text)
    if result > maximum:
        raise ResourceError(f"{label}: maksymalna wartość to {maximum}.")
    return result


def deposits_for_country(country_id, dictionary, lock=False):
    query = select(RegionZasob).join(Region, Region.region_id == RegionZasob.region_id).where(
        Region.panstwo_id == country_id, RegionZasob.zasob_id.in_(dictionary.values()),
    ).options(lazyload("*"))
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    rows = db.session.scalars(query).all()
    by_pair = {}
    for row in rows:
        pair = (row.region_id, row.zasob_id)
        if pair in by_pair:
            raise ResourceError("Istnieją powielone przydziały tego samego surowca do regionu. Zapis zablokowany do wyjaśnienia duplikatów.", 409)
        by_pair[pair] = row
    return by_pair


def save_allocations(country_id, form):
    # Wspólna blokada kraju serializuje również pierwszy zapis parametrów.
    country = db.session.scalar(select(Panstwo.PANSTWO_ID).where(Panstwo.PANSTWO_ID == country_id).with_for_update())
    if country is None:
        raise ResourceError("Nie znaleziono państwa.", 404)
    settings = db.session.scalar(select(CountryMiningSettings).where(
        CountryMiningSettings.panstwo_id == country_id,
    ).with_for_update().execution_options(populate_existing=True))
    expected_version = str(settings.version if settings else 0)
    if form.get("version") != expected_version:
        raise ResourceError("Dane zmieniły się w innej sesji. Zachowano wpisane wartości; odśwież panel przed ponowną edycją.", 409)
    action = form.get("action", "all")
    if action not in {"all", "technology", "region", "bulk"}:
        raise ResourceError("Nieprawidłowa operacja.")
    if len(form.getlist("technology")) != 1 or len(form.getlist("version")) != 1:
        raise ResourceError("Nieprawidłowe parametry formularza.")
    if action == "technology":
        technology = integer_value(form.get("technology", ""), 100, "Technologie wydobywcze")
        if settings is None:
            db.session.add(CountryMiningSettings(panstwo_id=country_id, technology=technology))
        else:
            settings.technology = technology
            settings.version += 1
        return
    dictionary = resource_dictionary()
    regions = db.session.execute(select(Region.region_id, Region.region_nazwa).where(
        Region.panstwo_id == country_id,
    ).order_by(Region.region_id).with_for_update()).all()
    if action == "region":
        region_id = integer_value(form.get("region_id", ""), 2147483647, "Region")
        regions = [region for region in regions if region.region_id == region_id]
        if not regions:
            raise ResourceError("Region nie należy do wybranego państwa.")
    expected = {field_name(region.region_id, code) for region in regions for code, _ in RESOURCES}
    submitted = {name for name in form if name.startswith("quantity_")}
    if expected != submitted or any(len(form.getlist(name)) != 1 for name in expected):
        raise ResourceError("Nieprawidłowa lista regionów lub surowców. Sprawdź, czy regiony należą do wybranego państwa i czy przesłano wszystkie pola.")
    if len(form.getlist("technology")) != 1 or len(form.getlist("version")) != 1:
        raise ResourceError("Nieprawidłowe parametry formularza.")
    technology = integer_value(form.get("technology", ""), 100, "Technologie wydobywcze") if action == "all" else (settings.technology if settings else 0)
    # Walidacja całego formularza poprzedza zmiany któregokolwiek rekordu.
    parsed = {}
    for region in regions:
        for code, label in RESOURCES:
            parsed[(region.region_id, dictionary[code])] = integer_value(
                form[field_name(region.region_id, code)], MAX_QUANTITY,
                f"{region.region_nazwa} — {label}",
            )
    existing = deposits_for_country(country_id, dictionary, lock=True)
    for pair, amount in parsed.items():
        row = existing.get(pair)
        if row is None:
            row = RegionZasob(region_id=pair[0], zasob_id=pair[1])
            db.session.add(row)
        row.zloze_ilosc = amount
    if settings is None:
        db.session.add(CountryMiningSettings(panstwo_id=country_id, technology=technology))
    else:
        settings.technology = technology
        # Wersja obejmuje również edycję samych złóż.
        settings.version += 1
