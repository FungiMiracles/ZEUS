# Powierzchnie w wiki — UAT

Dodano ranking powierzchni państw (km², oba kierunki sortowania, państwa suwerenne zgodnie z pozostałymi rankingami, brak danych na końcu), metryczną skalę na mapie świata i pole `Region.region_powierzchnia` wyświetlane na formularzu regionu.

Skala korzysta z bieżącego `game_map_calibration.km_per_unit`. Powierzchnie obliczono jako pole sumy geometrii regionu pomnożone przez kwadrat tego przelicznika, z uwzględnieniem wysp i otworów, po zaokrągleniu do pełnych km². Naprawiono w pamięci 20 geometrii z samoprzecięciami; zmiany pola mieściły się w tolerancji numerycznej. Plik mapy nie został zmieniony.

W `entenda_uat_db` dodano kolumnę `regiony.region_powierzchnia BIGINT NULL` i zapisano 630 powierzchni. Cztery regiony nie mają geometrii: Port Loyab (612), Region testowy (623), Region testowy 2 (624), Region testowy 3 (625). Ich pole pozostaje NULL, a formularz pokazuje „Brak danych”. Nie wyznaczano powierzchni na podstawie arbitralnych założeń.

Wyniki, kopia poprzednich wartości i skrypt cofnięcia: `region_areas_20261026T210117Z/`. Migracja: `region_areas_20261026_migrate.py`, uruchamiana Pythonem środowiska UAT. Kopia zawiera również kalibrację, skrót źródła i szczegóły napraw geometrii.

Walidacja: trzy izolowane testy `tests/test_wiki_areas.py` przeszły (ranking ASC/DESC, NULL i suwerenność; renderowanie mapy z kalibracją; zapis pola regionu i kompilacja szablonów). Zweryfikowano wartości po zatwierdzeniu transakcji. Przeładowano wyłącznie Gunicorn UAT; usługa aktywna, dwa nowe procesy robocze. Żądania HTTP bez sesji do mapy, rankingu i regionu poprawnie przekierowują do logowania. Nie wykonywano wizualnego testu w przeglądarce ani pełnego testu HTTP z zalogowaną sesją.
