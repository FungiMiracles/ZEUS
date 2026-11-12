# Struktura ludności w WIKI

Zmiany wyłącznie w ZEUS_UAT: ekran otrzymał responsywny układ białych kart, formularz, przyciski i typografię zgodne z pozostałymi ekranami wiki. Legenda rozróżnia brak struktury, zapisane dane i wybrane państwo.

Mapa korzysta z entenda_panstwa.geojson i panstwo_id, bez granic regionalnych. Identyfikatory zapisanych struktur są odczytywane z country_population_structures. Kolor aktualizuje się po wczytaniu danych i po udanym zapisie. Nieprzypisane geometrie pomijane są przy rysowaniu mapy.

Formularz dopełnia trzeci udział do 100% po wprowadzeniu dwóch wartości, na liczbach całkowitych oznaczających setne części procenta. Dopełniana wartość pozostaje edytowalna. Przy dalszej zmianie jednego z dwóch udziałów wynik jest przeliczany ponownie. Suma powyżej 100% blokuje zapis; zachowano kontrolę sumy po stronie serwera, CSRF i kontrolę wersji. Samo dopełnienie nie zapisuje danych.

Walidacja: pięć testów tests/test_wiki_areas.py przeszło. Wykonano również test kodu JavaScript w V8 z atrapami DOM/fetch/Leaflet: dopełnianie, ponowna edycja, przekroczenie 100%, wartości dziesiętne i zerowe, wybór danych krajowych i zmiana koloru po zapisie. Starszy zestaw test_game_roads_population_deployment.py nie uruchamia się z powodu istniejącego błędu fixture: brak rejestracji tabeli game_ammunition_factories dla klucza game_military_flights.target_factory_id. Nie wykonywano testu wizualnego w przeglądarce.
