# UAT — drogi, porty, finanse administratora i jasny motyw, 25.10.2026

## Poprawki

Karty kopalń mają ikonę kopalni 32 px i minerału 23 px, również po zakończeniu budowy. Przy postępie budowy kopalnia ma 28 px, minerał 21 px. Przywrócono rozmiar minerału na mapie surowców do 20 px.

Wspólna obsługa gestów zatrzymuje powiększanie strony wyłącznie przy gestach wielodotykowych rozpoczynanych na mapie. Leaflet nadal przybliża mapę; powiększanie strony poza mapami pozostaje dostępne. Pola formularzy na urządzeniach dotykowych mają co najmniej 16 px, co zapobiega automatycznemu zoomowi przy fokusie. Menu przewija się przy małej wysokości ekranu i na telefonie.

Dodano paski życia pod ikonami obrony przeciwrakietowej, kopalń i okrętów. Paski baz, kart oraz pozostałych obiektów wojskowych używają wspólnych progów: zielony 75–100%, pomarańczowy 26–74%, czerwony 0–25%. Postęp budowy pozostaje osobnym pomarańczowym paskiem.

Mapa infrastruktury filtruje własne regiony metropolitalne, wykluczając zarówno regiony oznaczone jako zamorskie, jak i regiony państw zależnych. Nie zmienia to własności ani zarządzania tymi regionami w pozostałych modułach.

## Porty

W oknie ustawień portów dodano blokadę udostępniania portów wszystkim obcym państwom lub wybranym państwom. Dostęp sprawdzany jest przy wystawieniu oferty i ponownie przy zakupie, dla państwa korzystającego z portu wysyłki lub odbioru. Blokada tranzytu nie staje się embargiem na własny import/eksport właściciela portu. Zakupione ładunki dopływają mimo późniejszej blokady; ponowienie tego samego zakupu zwraca istniejącą transakcję.

## Drogi

Zakładka „Budowa dróg” na ekranie infrastruktury i edytor „Drogi świata” w panelu administratora WIKI korzystają ze wspólnej mapy i formularza. Początek i koniec wybiera się na mapie lub z list miast. Wycena wykorzystuje istniejącą skalę mapy. Autostrada: 10 000 000 ROI/km, gruba pomarańczowa linia; droga krajowa: 250 000 ROI/km, cieńsza żółta linia. Odległość zapisywana jest do 0,001 km; koszt do 0,01 ROI.

Budowa jest natychmiastowa po wyraźnym zatwierdzeniu. Anulowanie lub sama wycena nie zapisują drogi i nie pobierają środków. Gracz korzysta ze wspólnej puli infrastruktury, a wydatki są widoczne w saldach sektorów i blokują ponowne wydanie środków. Administrator buduje za darmo. Weryfikowane są uprawnienia, CSRF, aktualny koszt, ponowienia żądań i istniejące odcinki (także przeciwny kierunek). Walidacja całej geometrii odcinka wyklucza przecinanie morza, otworów w poligonach i obcego terytorium.

## Finanse WIKI

Z danych gospodarczych państwa administrator przechodzi do „Zarządzaj budżetem gry i podatkami państwa”. Może dodać lub odjąć środki z rezerwy albo sektora aktualnego budżetu. Odjęcie nie może objąć wydanych lub zobowiązanych środków. Rezerwa może zostać zasilona także przed pierwszym budżetem.

Każda korekta ma administratora, uzasadnienie, kwotę, sektor i identyfikator operacji; ponowienia nie naliczają jej ponownie. Zmiany rezerwy uwzględniane są w kontroli salda i przeniesieniu na następne półrocza. Zatwierdzone historyczne plany i naliczenia nie są przepisywane.

Administrator może ustalić PIT i CIT obowiązujące przy kolejnych zatwierdzeniach budżetu, również automatycznych. Zmiana wersji polityki podatkowej unieważnia wcześniejszy podgląd budżetu. Gracz widzi informację o stawkach administratora. Bieżące środki można skorygować niezależnie.

## Wygląd

Wdrożono jasny motyw administracyjny: tło w kolorze papieru, białe karty, ciemny tekst i zgaszona zieleń. Uproszczono nagłówki, usunięto świetlne i wojskowe ozdobniki oraz siatki z map. Zachowano kolory sygnałowe powiadomień, wskaźników, zdrowia i relacji. Zmienione pliki mają nowe wersje do odświeżenia cache.

## Migracja i weryfikacja

Migracja `migrations/sql/civic_roads_ports_finance_20261025_migrate.py` działa wyłącznie na `entenda_uat_db`: dodaje trzy tabele oraz ustawienia dostępu do portów. Ponowne wykonanie sprawdzone; salda rezerw i stawki opłat pozostały bez zmian. Usługa UAT została łagodnie przeładowana.

Przeszło 218 testów unittest i 7 testów JavaScript. Sprawdzono składnię sześciu skryptów, renderowanie 13 ekranów gry i dwóch nowych paneli WIKI oraz zgodność wszystkich sald rezerw.

W Chromium sprawdzono wizualnie sześć ekranów gry i oba panele WIKI, brak błędów JavaScript, wybór punktów drogi, wycenę i anulowanie. W widoku mobilnym 390×844 sprawdzono przewijanie menu, mapy surowców, infrastruktury, handlu i obrony oraz zakładkę dróg. Gest szczypania zmienił zoom mapy z -0,25 do 1,5, przy niezmienionej skali strony 1. Sprawdzono też przewijanie menu przy ekranie 1024×400. To emulacja mobilna Chromium, bez testu na fizycznym iPhonie/Androidzie.

Kontrole przeglądarkowe blokowały zapisy poza odczytową wyceną drogi. Nie budowano testowych dróg, nie zmieniano blokad portów ani finansów i nie odczytywano powiadomień na kontach graczy. Testy zapisów wykonano na izolowanym SQLite. Zrzuty przeglądarkowe: `/tmp/zeus-uat-civic/`.
