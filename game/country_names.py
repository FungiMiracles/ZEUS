"""Odmiana nazw państw (15 Nov 2026) — dopełniacz do komunikatów, np. „Zostałeś przywódcą Ozilandii”.

Nazwy są fikcyjne: typowe końcówki odmieniają reguły, nazwy nieregularne (liczba mnoga, kilka wyrazów,
przymiotniki) są w słowniku wyjątków. Nieznaną nazwę wielowyrazową zwracamy jako „państwa X”, żeby nie zgadywać.
"""

GENITIVE = {
    'Czymony': 'Czymonów',
    'Małpiony': 'Małpionów',
    'Kalepary': 'Kaleparów',
    'Iskalia i Wyspy': 'Iskalii i Wysp',
    'Piris i Kafert': 'Pirisu i Kafertu',
    'Kosliw Północny': 'Kosliwu Północnego',
    'Kosliw Południowy': 'Kosliwu Południowego',
    'Kosliw Wschodni': 'Kosliwu Wschodniego',
    'Kosliw Zachodni': 'Kosliwu Zachodniego',
    'Lantania Północna': 'Lantanii Północnej',
    'Republika Zontyjska': 'Republiki Zontyjskiej',
    'Strefa Kaskurska': 'Strefy Kaskurskiej',
    'Ungran Tungavi': 'Ungranu Tungavi',
    'Wschodnie Sesmefen': 'Wschodniego Sesmefenu',
    'Wyspy Świętego Walezego': 'Wysp Świętego Walezego',
    'Wyspy Wężowe': 'Wysp Wężowych',
}
VOWELS = 'aąeęioóuy'


def _word(word):
    lower = word.lower()
    if lower.endswith('ja'):return word[:-1] + 'i'            # Maurycja → Maurycji, Hasja → Hasji
    if lower.endswith(('ia', 'ea')):return word[:-1] + 'i'     # Ozilandia → Ozilandii, Irea → Irei
    if lower.endswith(('ka', 'ga')):return word[:-1] + 'i'
    if lower.endswith('a'):return word[:-1] + 'y'              # Alata → Alaty
    if lower[-1:] in VOWELS:return word                        # Ikko, Nuveco, Cicirici — nieodmienne
    return word + 'u'                                          # Sajstan → Sajstanu, Mostol → Mostolu


def genitive(name):
    """Dopełniacz nazwy państwa; dla nieznanej nazwy wielowyrazowej — „państwa {nazwa}”."""
    name = (name or '').strip()
    if not name:return 'państwa'
    if name in GENITIVE:return GENITIVE[name]
    if ' ' in name:return f'państwa {name}'
    return _word(name)
