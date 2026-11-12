# Światowa struktura ludności i PKB w wiki

Dodano pod nagłówkiem struktury ludności trzykolorowy pasek grup 0–17, 18–64 i 65+ z procentowymi tooltipami, legendą oraz informacją o pokryciu danych. Agregacja jest ważona ludnością państw z zapisaną strukturą; brakujące struktury nie są zgadywane. Zaokrąglenie metodą największych reszt zapewnia sumę 100,00%. Pasek aktualizuje się po udanym zapisie struktury państwa.

W pasku statystyk wiki dodano sumę bieżącego PKB wszystkich państw w ROI. Porównanie obejmuje ostatni historyczny zapis każdego państwa w poprzednim roku Entendy; strzałka zielona/czerwona oznacza wzrost/spadek. Przy równości wyświetla się neutralna strzałka, a przy niepełnej historii brak porównania. Agregacja PKB i ludności stosuje ten sam zakres państw co dotychczasowe statystyki wiki.

Sprawdzono siedem izolowanych testów wiki i test JavaScript w V8 (renderowanie segmentów, tooltipów, pokrycia danych i aktualizacja po zapisie; dopełnianie formularza zachowane). Zweryfikowano agregaty na entenda_uat_db. W chwili sprawdzenia PKB świata było równe ostatniej sumie z roku 2999, dlatego poprawnie pokazywany jest znak neutralny. Nie zmieniano danych w bazie. Przeładowano wyłącznie UAT. Bez testu wizualnego w przeglądarce.
