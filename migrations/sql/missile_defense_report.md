# Obrona przeciwrakietowa i cele wojskowe — UAT, 2026-10-24

Wdrożono w ZEUS_UAT; schemat `entenda_uat_db`. Produkcja ZEUS bez zmian. Migracja: `missile_defense_entenda_uat_db.sql`.

## Zakres

- Nowe umieszczenie lub przeniesienie bazy morskiej wymaga położenia wewnątrz własnego nadmorskiego regionu, najwyżej 3 km od rzeczywistego wybrzeża. Wspólne granice lądowe, także podzielone na krótsze odcinki i między częściami tego samego regionu, są odejmowane z geometrii wybrzeża. Serwer sprawdza odległość według utrwalonej skali mapy. Zielony pas ma szerokość 3 km w głąb wybranego regionu; pozostałe terytorium kraju jest czerwone. Wizualizacja SVG przycina pas do regionu i aktualizuje szerokość przy zmianie przybliżenia. Dotychczasowe lokalizacje baz nie są samoczynnie przenoszone.
- Zmiana nazwy okrętu z jego menu na mapie. Nazwa i życie pozostają zapisane po powrocie oraz ponownym wysłaniu tej samej jednostki.
- Panel wojenny pokazuje również cudze okręty, z małą flagą państwa. Atak możliwy wyłącznie przeciwko państwom, z którymi trwa wojna. Zarządzanie cudzym okrętem jest odrzucane przez serwer.
- Kliknięcie wrogiej bazy albo okrętu wybiera obiekt jako cel dla bombardowania z powietrza, wyrzutni lądowej lub wysłanego okrętu. Cel morski uwzględnia przewidywany ruch do momentu trafienia. Każda nieprzechwycona rakieta odbiera 4–15 punktów życia (skala 0–100). Przy zerowym życiu okręt tonie i dokładnie raz znika z garnizonu oraz krajowego zasobu jednostek. Baza ma dolny limit życia 0.
- Obrona przypisywana do własnego regionu, miasta albo bazy. Poziom 1 kosztuje 100 mln ROI, zawiera 100 pocisków. Poziomy 1–7: pojemności 100/500/1000/2000/4500/6000/10000; skuteczności 30/45/55/65/75/85/95%. Ceny rozbudowy poziomów 2–7: 500/750/1000/1250/1500/2000 mln ROI.
- Najpierw działa obrona regionu, następnie obrona miasta/bazy, na pozostałe rakiety. Skuteczność jest szansą przechwycenia każdej rakiety; jedno skuteczne przechwycenie zużywa jeden pocisk obrony. Liczba przechwyceń nie może przekroczyć dostępnej amunicji. Pusta wyrzutnia nie przechwytuje. Regionalna obrona bazy macierzystej nie chroni okrętu znajdującego się na morzu.
- Rozbudowa zwiększa pojemność i dodaje pociski odpowiadające różnicy pojemności poziomów, zachowując wcześniej zużytą amunicję. Uzupełnianie po 15 000 ROI za sztukę, najwyżej do pojemności bieżącego poziomu. Wszystkie wydatki korzystają z bieżącego budżetu wojskowego i pomniejszają środki dostępne na bazy oraz utrzymanie.
- Mniejsza ikona obrony przy mieście, regionie lub bazie, z oznaczeniem poziomu; tooltip zawiera poziom, skuteczność i pozostałą amunicję. Właściciel może rozbudować lub uzupełnić obronę z jej ikony.
- Trafienia w infrastrukturę odejmują 1 punkt na nieprzechwyconą rakietę, z dolnym limitem 0. Trafienie miasta nalicza ofiary wyłącznie od nieprzechwyconych rakiet. Pociski atomowe podlegają przechwyceniu, ale nadal nie powodują ofiar ani zniszczeń.
- Powiadomienia obu stron i historia lotów zawierają przechwycenia oraz rzeczywiste skutki trafienia. Rozliczenie amunicji, szkód, strat i powiadomień następuje w jednej transakcji; ponowne zadanie nie nalicza ich drugi raz.
- Tooltip prac budowlanych infrastruktury ma ograniczoną szerokość, zawijanie tekstu i stałe rozmiary ikon.

## Walidacja

- Pełny zestaw: 132 testy Python — OK, w tym wszystkie platformy ataku na bazy i okręty, granice pasa przybrzeżnego, ceny/pojemności obrony, kolejność przechwyceń, brak amunicji, wycofanie transakcji i idempotencja strat.
- Składnia obu zmienionych skryptów JavaScript — OK.
- Migracja MySQL UAT sprawdzona: nowe tabele i klucze obce, stan `sunk`, nazwy i życie okrętów, pola celu i raportu lotu.
- Uwierzytelniony test renderowania obrony, panelu wojennego, stanu mapy i endpointu wybrzeża — HTTP 200. W testowym kliencie rozliczanie skutków i rejsów było wyłączone; nie wykonywano ataków ani zakupów na danych graczy.
- Gunicorn UAT łagodnie przeładowany. Usługa aktywna; nowe pliki JS/CSS i ikona obrony dostępne przez HTTP 200.
- Brak wizualnego testu w przeglądarce; środowisko przeglądarki nie jest dostępne.
