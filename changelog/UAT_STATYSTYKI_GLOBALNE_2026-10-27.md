# Rozszerzony pasek statystyk WIKI — UAT

Do base layout dodano dynamiczne globalne PKB per capita, średnią infrastrukturę, urbanizację, roczny procent zmiany populacji oraz liczbę zapisanych zdarzeń. Dane są liczone przy renderowaniu strony, bez migracji lub zmiany danych. Dotychczasowe statystyki pozostają widoczne. Dodatkowe elementy zawijają się w kolejne wiersze; dymki opisują metodę liczenia. Wartości mają dwa miejsca po przecinku, spacje grupujące tysiące i polski separator dziesiętny. Brak danych oznaczany jest kreską.

- PKB per capita: suma PKB aktywnych państw / suma ich ludności, w ROI na osobę.
- Infrastruktura: średnia dostępnych wskaźników drogowego, kolejowego, energetycznego i mieszkaniowego regionów aktywnych państw, plus portowego dla regionów z położeniem innym niż śródlądowe. Skala 0–100; NULL pomijane, zero zachowane.
- Urbanizacja: ludność miast aktywnych państw / łączna ludność aktywnych państw × 100.
- Zmiana populacji: średnia bieżących regionalnych rocznych wskaźników miejskich i wiejskich, ważona odpowiadającą im liczbą mieszkańców. Brakujące wskaźniki pomijane; ujemne wartości zachowane.
- Zdarzenia: wszystkie rekordy aktualnie zapisane w `zdarzenia`, włącznie z zakończonymi i archiwalnymi. Zgodnie z ustaleniem licznik maleje po fizycznym usunięciu zdarzenia.

Walidacja: 17 testów WIKI/map przeszło, w tym nowe testy ważenia, NULL, zera, statusu państw, zmian danych i liczenia zdarzeń. Agregaty sprawdzono odczytem na UAT. Test przeglądarkowy rzeczywistego base layout sprawdza pięć nowych pól i brak poziomego przepełnienia paska na telefonie. Produkcja nie jest objęta zmianą.
