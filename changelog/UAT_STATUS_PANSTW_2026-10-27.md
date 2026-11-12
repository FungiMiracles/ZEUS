# Statusy państw — wyłącznie ZEUS UAT

Wyszukiwarka państw: dodano podstawowy filtr „Status państwa” z opcjami „aktywne” (domyślnie) i „usunięte”. Wyłącznie wyszukiwanie po statusie „usunięte” jawnie odczytuje archiwalne rekordy; pozostałe listy, statystyki i Generator Zdarzeń nadal je pomijają. Filtr łączy się z innymi kryteriami i pozostaje w linkach paginacji. Wyniki pokazują status, a usunięte państwa nie mają przycisków prowadzących do nieaktywnych formularzy. Osiem testów statusów potwierdziło także renderowanie filtra, paginację i domyślne zachowanie.

Dodano `panstwa.status`: `aktywne` (domyślny) oraz `usunięte`, z ograniczeniem dopuszczalnych wartości. Po ponownym przyłączeniu regionu państwo utworzone przez secesję otrzymuje status `usunięte`, jeśli nie pozostały w nim inne regiony ani miasta. Status nie zmienia suwerenności ani nie tworzy fikcyjnej zależności od państwa docelowego. Rekordy, ID, historia i grafiki pozostają zachowane.

Wspólna polityka odczytu ORM pomija usunięte państwa w listach, selektorach, wyszukiwaniu, rankingach, agregatach (w tym liczniku państw i sumach w base layout), zapytaniach z aliasami i relacjach. Obejmuje sesje Flask i samodzielne sesje usług. Odczyt przez `get` w sesji Flask i starszym Query sprawdza także obiekty już obecne w pamięci sesji. Narzędzia audytowe mogą jawnie użyć `include_deleted_countries=True`; żądania użytkownika nie przełączają tej opcji. Nazwy historycznych państw pozostają zarezerwowane.

Generator Zdarzeń wybiera wyłącznie regiony aktywnych państw; regeneracja infrastruktury i demografii również pomija regiony usuniętych państw. Roczne operacje na modelu państwa korzystają ze wspólnego filtra. Wykresy świata filtrują historię po aktywnych państwach, a bezpośrednie zapytania o wykres usuniętego państwa zwracają 404.

Mapy WIKI, rejestracji i paneli gry używają jednego endpointu `/wiki/mapa/panstwa.geojson`, który uwzględnia aktualną przynależność regionów i pomija usunięte państwa. Endpoint jest publiczny tak jak wcześniejsze statyczne granice dostępne na ekranie rejestracji. Migawka mapy usuniętego państwa zwraca 404.

Migracja `migrations/sql/country_status_20261027_migrate.py` sprawdza katalog ZEUS_UAT oraz nazwę bazy `entenda_uat_db`. Wykonana 27.10.2026: zachowano wszystkie 103 rekordy, 99 aktywnych, 4 usunięte (ID 165, 166, 167, 168). Skrypt można uruchomić ponownie. Produkcja nie była modyfikowana.

Walidacja: 299 testów unittest na izolowanych bazach SQLite zakończonych powodzeniem. Dodano 7 testów statusów obejmujących listy API, rankingi, agregaty, aliasy, odczyt z pamięci sesji, sesję samodzielną, Generator Zdarzeń, wykresy, mapy i przyłączenie z pozostawieniem innych regionów. Uzupełniono konfigurację izolowanych aplikacji testowych o wspólny endpoint mapy i funkcje/kolację MySQL używane przez SQLite.

Usługa UAT została przeładowana sygnałem HUP po sprawdzeniu ścieżki i właściciela procesu Gunicorn. Publiczne odczyty HTTP na porcie 5001 potwierdziły 99 aktywnych państw w API i 99 geometrii mapy, bez usuniętych ID. Próba testu HTTP z wygenerowaną sesją administratora została odrzucona przez automatyczną kontrolę i nie została wykonana; nie używano jej do dalszej weryfikacji.
