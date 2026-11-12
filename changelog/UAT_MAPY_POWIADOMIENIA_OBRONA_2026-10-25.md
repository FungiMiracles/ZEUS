# UAT — mapy, powiadomienia i życie obrony przeciwrakietowej, 25.10.2026

Poprawiono odstępy sekcji infrastruktury wydobywczej i kart kopalń oraz zmniejszono ikony minerałów obok kopalń na mapach i przy postępie budowy. Podsumowanie handlu ma równe kolumny; na małych telefonach przechodzi w jedną kolumnę.

Menu boczne nie zawija pozycji w kolejne kolumny. Lista przewija się niezależnie, obsługuje dotyk i fokus klawiatury. Rozwinięte menu mobilne ma wysokość widocznego ekranu i przewijaną listę z miejscem na dolny obszar telefonu.

Otwarcie listy powiadomień oznacza odczyt wyświetlonej strony (20 pozycji); „Pokaż starsze” oznacza kolejną. Pobieranie licznika w tle nie oznacza odczytu. Zapis wymaga CSRF i dotyczy wyłącznie własnych powiadomień. Wojna i komunikaty wojskowe mają jasnoczerwone tło oraz czerwoną obwódkę, budowa — jasnożółte tło i pomarańczową obwódkę.

Obie mapy wojskowe mają sześć niezależnych przycisków filtrujących bazy powietrzne, morskie i lądowe, silosy, obronę przeciwrakietową oraz kopalnie. Można włączyć wiele rodzajów naraz lub wyłączyć wszystkie. Odświeżanie danych zachowuje wybór. Filtry nie zmieniają uprawnień do informacji wywiadowczych.

Obrona przeciwrakietowa ma 100% życia. Rozpoznaną obronę wrogiego państwa można wybrać jako cel ataku rakietowego. Działają dotychczasowe przechwycenia; każda nieprzechwycona rakieta konwencjonalna odbiera losowo 3–9% życia, do zera. Obrona z zerowym życiem nie przechwytuje i wymaga naprawy. Naprawa dodaje wskazaną liczbę punktów procentowych, kosztuje 10 000 ROI za punkt i obciąża budżet sił zbrojnych. Historia wydatków i ataków pozostaje zachowana. Dotychczasowa zasada braku szkód od głowic atomowych pozostaje w mocy.

Potwierdzono istniejącą misję „Położenie kopalń”: dotyczy wybranego regionu obcego państwa, a udany raport ujawnia jego kopalnie na mapie wojennej. Dodano ikonę wywiadu obok nazw agentów na kartach i w liście misji.

Migracja: `migrations/sql/missile_defense_health_20261025_migrate.py`. Wyłącznie `entenda_uat_db`; dodaje życie obrony z ograniczeniem 0–100 i powiązanie lotu z atakowaną obroną. Istniejąca obrona otrzymała 100% życia. Ponowne uruchomienie migracji sprawdzone. Usługa UAT łagodnie przeładowana.

Weryfikacja: 202 testy unittest; 3 testy JS filtrów i 2 odczytu powiadomień; renderowanie 13 ekranów UAT; uwierzytelniony HTTP pięciu zmienionych ekranów działającej usługi oraz zgodność serwowanych plików z lokalnymi. Poprawiono dwie wcześniejsze usterki środowiska testowego rejestracji/zarządzania zależnościami: BIGINT autoincrement w SQLite i niezadany losowy wynik przechwyceń. Bez testowych ataków, napraw, zakupów ani oznaczania powiadomień na kontach graczy. Nie wykonywano wizualnego testu w przeglądarce ani na fizycznym telefonie.
