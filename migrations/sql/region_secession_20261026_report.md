# Secesja i ponowne przyłączenie regionu — ZEUS WIKI UAT

Wdrożenie wyłącznie w ZEUS_UAT. Funkcje dostępne dla roli Wszechmocny na formularzu regionu. Ogłoś niepodległość otwiera modal z edytowalną nazwą państwa. Nowe ID otrzymuje państwo; ID regionu pozostaje niezmienione, aby zachować historię i powiązania. Region i jego miasta przechodzą do nowego państwa, stolica regionalna (typ 2) staje się stolicą kraju (typ 1). Przy braku stolicy nie jest wybierane przypadkowe miasto; niejednoznaczne dane o kilku stolicach blokują operację.

Flaga kopiowana jest pod nową nazwę, mapa kraju powstaje z binarnej mapy regionu albo pozostaje nieustawiona. Żaden istniejący plik flagi/mapy nie jest nadpisywany. Brak flagi w źródle pozostaje brakiem danych. Transakcja zapisuje migawki grafik i aktora operacji. Błąd zapisu pliku lub zatwierdzenia transakcji wycofuje zmianę i usuwa nowe pliki.

Po secesji pojawia się opcja Przyłącz do państwa w menu oraz przycisk na formularzu, otwierające modal z listą innych suwerennych państw. Przyłączenie przenosi region i miasta, zachowuje ID regionu i usuwa aktywny status secesji. Regionalna stolica wraca do typu 2; zapobiega się powstaniu dwóch stolic kraju. Państwo pozbawione ostatniego regionu po przyłączeniu zostaje zachowane jako niesuwerenne, podległe państwu docelowemu. Nie usuwa się jego rekordu ani historycznych grafik.

Populacja i powierzchnia krajów są ponownie wyliczane z regionów i miast; PKB nowego państwa pozostaje NULL, a istniejące PKB nie jest arbitralnie dzielone. Przynależność zamorska regionu jest przywracana przy powrocie do pierwotnego państwa; po secesji region jest metropolitalny.

Ochrona: rola administratora, CSRF, kontrola spodziewanego właściciela, blokady rekordów i serializacja secesji między procesami MySQL, unikalne identyfikatory operacji i idempotentne ponowienie. Istniejące pliki map politycznych nie są modyfikowane: nowy endpoint buduje odpowiedź GeoJSON na podstawie historii zmian i aktualnego właściciela regionu. Odczyt respektuje dostęp wiki i dotychczasowy dostęp gracza do mapy świata; działania zapisu pozostają dostępne tylko administratorowi wiki.

Migracja: region_secession_20261026_migrate.py tworzy wyłącznie tabelę wiki_region_secessions w entenda_uat_db. W chwili migracji zachowano 99 państw i 634 regiony, tabela operacji była pusta. Nie wykonywano secesji żadnego rzeczywistego regionu. Produkcja nie jest objęta wdrożeniem.

Walidacja: osiem testów test_region_secession.py oraz dwanaście testów test_wiki_areas.py. Sprawdzono secesję, grafiki/NULL, stolicę, przyłączenie, uprawnienia/CSRF, odrzucanie niepoprawnych i nieaktualnych danych, idempotencję, przenoszenie geometrii oraz wycofanie po błędach zapisu plików i commit. Przeglądarka na odizolowanej bazie SQLite potwierdziła pełny przepływ menu -> modal -> secesja -> modal mobilny -> przyłączenie do wybranego państwa. Żadne testy nie zmieniały rzeczywistych państw ani regionów.
