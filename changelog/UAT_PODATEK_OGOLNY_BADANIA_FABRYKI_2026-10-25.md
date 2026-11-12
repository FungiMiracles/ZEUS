# ZEUS_UAT — podatek ogólny, badania i fabryki amunicji

## Podatek ogólny

Usunięto edycję CIT z formularzy gracza i WIKI oraz żądań formularza finansów. Nowe plany korzystają z jednej stawki podatku ogólnego. Roczna suma wpływów:

1. Rzeczywista liczba osób 18–64 × 10 000 ROI × stawka / 100.
2. Średni stan infrastruktury × 2 000 000 000 ROI (portowa tylko w regionach przybrzeżnych, tak jak w podsumowaniu kraju).
3. Zadowolenie społeczne × 500 000 000 ROI.
4. Stabilność społeczna × 100 000 000 ROI.
5. Poziom edukacji × 200 000 000 ROI.

Zachowano dotychczasowe rozliczanie roczne: połowa wpływów trafia do każdego półrocza. Stawka dotyczy pierwszego składnika; pozostałe są dodawane niezależnie od stawki. PKB pozostaje informacją historyczną, bez wpływu na nowy wzór. Obliczenia używają Decimal. Stan wieku, infrastruktury i społeczeństwa zapisuje się w migawce rozliczenia; zmiana podstaw unieważnia wcześniejszy podgląd. Brak struktury wieku lub kompletnych danych społecznych wymaga ich uzupełnienia w WIKI, zamiast przyjmowania fikcyjnych wartości.

Nowe wpływy księgowane jako TAX_GENERAL. Historyczne plany, rezerwy i wpisy PIT/CIT pozostają zachowane. Reguły walidacji bazy rozróżniają historyczne obliczenia od wersji 4.

## Badania i rozwój

Nowy przycisk w menu i ekran z ikoną BADANIA, aktualnym budżetem sektora oraz liczbą punktów. Zakup punktu kosztuje 200 000 000 ROI z bieżącego półrocza badań. Punkty pozostają do wykorzystania w kolejnych półroczach.

Sieć z centralną metodą badawczą i pięcioma kierunkami. Kliknięcie aktywnego koła otwiera interaktywny tooltip: opis, postęp, wybór punktów przyciskami +/− i zatwierdzenie. Można inwestować częściowo. Koszty kolejnych poziomów metody: 10, 15, 30, 50, 100, 200 i 500 punktów. Okrągły wskaźnik pokazuje postęp do kolejnego poziomu.

Metoda poziomu 1 odblokowuje produkcję amunicji przeciwrakietowej w kierunku militarnym, koszt 20 punktów. Budownictwo, informatyka, medycyna i wydobycie są widoczne jako czasowo niedostępne. Serwer wymusza kolejność, progi poziomów i dostępne punkty; operacje zakupu i inwestowania mają identyfikatory chroniące przed podwójnym zapisem.

## Fabryki i amunicja

Infrastruktura → Fabryki: mapa własnych regionów metropolitalnych, wybór miejsca, potwierdzenie lub anulowanie. Po odblokowaniu technologii gracz buduje fabrykę z ikonami FABRYKA i AMMO za 2 000 000 000 ROI z infrastruktury. Budowa kończy się od razu.

Poziom 1 produkuje 10 sztuk na pełne 24 godziny Entendy od chwili budowy. Rozliczenie na podstawie trwałego znacznika czasu uwzględnia okres nieobecności i nie nalicza produkcji ponownie przy odświeżeniu. Magazyn amunicji widoczny na ekranie sił zbrojnych. W istniejącym oknie obrony przeciwrakietowej można wybrać zakup pocisków lub własny magazyn; własna amunicja jest zużywana bez opłaty wojskowej.

## Walidacja

Migracja `migrations/sql/research_general_tax_20261025_migrate.py` działa wyłącznie na ZEUS_UAT; tworzy tabele badań/fabryk, dodaje migawkę podatku i rozszerza reguły walidacji historycznych rozliczeń. Nie przelicza zatwierdzonych planów ani istniejących rezerw.

258 testów Python, testy JavaScript i kontrola składni skryptów. Testy obejmują podgląd i zatwierdzenie nowego podatku, nieaktualny podgląd, zapis podstaw i księgi, progi i częściowe inwestycje, brak środków, idempotencję, autoryzację/CSRF, budowę i produkcję fabryki oraz darmowe uzupełnienie z magazynu. Przeglądarka desktop/mobile sprawdza sieć, tooltipy, wybór miejsca fabryki, formularz podatku i źródła amunicji; wszystkie inwestycyjne POST w tych testach są blokowane. Audyt porównuje punkty z księgą inwestycji oraz weryfikuje rezerwy i migawki podatku.
