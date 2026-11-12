# ZEUS_UAT — drogi, rozmieszczenie baz i struktura ludności

Zmiany wyłącznie w UAT:

- Widoczne końcówki istniejących dróg pozwalają rozpocząć kolejny odcinek dokładnie z końca lub początku drogi. Miasta pozostają nad liniami.
- Modernizacja własnej drogi krajowej do autostrady: 800 000 ROI/km, z zachowaniem przebiegu. Wydatek trafia do bieżącego półrocza; historyczny koszt budowy pozostaje zachowany.
- Dwa przesuwane punkty krzywizny w 1/3 i 2/3 odcinka oraz suwaki. Serwer przelicza długość i koszt z zaakceptowanego przebiegu.
- Widoczne sąsiednie kraje, miasta i drogi. Wspólna budowa wymaga akceptacji sąsiada; każdy finansuje odcinek na swoim terytorium z infrastruktury. Odmowa udostępnia osobną wycenę i potwierdzenie budowy tylko do granicy. Brak częściowych obciążeń przy błędzie lub niewystarczających środkach.
- Rozmieszczenie bazy zaczyna się od modalu garnizonu. Wymagani żołnierze i sprzęt (dla silosu głowice), kontrola pojemności i zasobów. Akceptacja uruchamia obowiązkowe wskazanie miejsca na mapie; przeładowanie strony zachowuje ten krok.
- Ikony kopalni bez tła. Szczegóły podziału budżetu domyślnie zamknięte. Ikony przesunięcia środków i pożyczki przy nagłówkach. Stonowane kolory kondycji infrastruktury.
- WIKI: Demografia → istniejący kafelek Struktura ludności. Tylko wszechmocny edytuje udziały 0–17, 18–64, 65+ po wyborze państwa na mapie lub liście. Walidacja sumy 100%, dokładność dwóch miejsc, kontrola równoległej edycji. Liczby osób sumują się do aktualnej populacji. Dane widoczne również w demografii gracza; brak konfiguracji jest jawnie oznaczony.

Migracja: `migrations/sql/roads_population_deployment_20261025_migrate.py`, ograniczona do bazy UAT. Dodaje tabele modernizacji, wspólnych projektów i struktury wieku oraz dane identyfikacji rozmieszczenia baz. Bez zmian istniejących populacji i rezerw.

Weryfikacja: 244 testy Python, testy JavaScript (w tym geometria krzywizny i skrzyżowań), renderowanie ekranów oraz przeglądarka desktop/mobile. Testy przeglądarkowe nie wykonują rzeczywistych inwestycji ani zapisów struktury ludności. Kontrola rezerw i księgi pożyczek bez niezgodności.
