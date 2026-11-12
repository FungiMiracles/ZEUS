# UAT — handel, magazyn i wydobycie (25.10.2026)

Wdrożono ekran Handel, oferty pakietów ośmiu surowców, wykluczenia państw, rezerwację towaru i anulowanie ofert. Kupujący płaci z rezerwy. Sprzedający otrzymuje cenę pomniejszoną o opłatę obcego portu wysyłki; kupujący dopłaca za obcy port odbioru. Opłaty zasilają rezerwy właścicieli portów. Własne porty są bezpłatne; państwo bez własnego portu wybiera cudzy port z mapy lub listy. Stawka wysyłki jest utrwalana przy wystawieniu oferty, stawka odbioru jest sprawdzana przy zakupie.

Transport trwa zgodnie ze skalą mapy, z prędkością 100 km/h Entendy. Statek jest animowany na ekranie handlu. Towary trafiają do magazynu dopiero po zakończeniu rejsu i mogą być odsprzedawane. Powtórzone żądania nie pobierają ponownie towaru ani pieniędzy. Transakcje blokują państwa i zasoby; rozliczenia rezerwy są ujęte w historii sald sektorów oraz przenoszeniu rezerwy na kolejne półrocza.

Na ekranie Surowce naturalne dodano magazyn i budowę ośmiu rodzajów kopalń według wskazanych cen i terminów. Budżet ma nowy sektor „Infrastruktura wydobywcza”. W istniejących planach dodano zerowy przydział bez zmiany ich kwot. Wydobycie rozpoczyna się po budowie: pierwsza jednostka po kolejnych trzech dniach Entendy. Każda kopalnia wydobywa jedną jednostkę na trzy dni do wyczerpania regionalnego złoża; ilość złoża jest pomniejszana. Lokalizacja musi należeć do wybranego własnego regionu. Kopalnia bez odpowiedniego złoża pozostaje bezczynna.

Dodano misję wywiadowczą o położeniu kopalń. W panelu wojennym przeciwnik widzi kopalnie po udanej misji. Nieprzechwycona rakieta zadaje 4–15 punktów obrażeń; przy zerowym życiu kopalnia jest usuwana, przy zachowaniu historii kosztów i ataków. Ataki atomowe nadal nie powodują zniszczeń.

Migracja: `migrations/sql/commerce_entenda_uat_db.sql` — siedem tabel, odwołanie ataku do kopalni, rozszerzony rodzaj misji i osiemnasty sektor budżetu. Usługa `zeus_uat.service` została łagodnie przeładowana.

Weryfikacja: 174 testy unittest; składnia JavaScript handlu, surowców i panelu wojennego; odczyt rzeczywistego UAT (ekrany, ikony, CSRF, widoczność kopalń, 18 sektorów, spójność wszystkich rezerw); HTTP uruchomionej usługi. Kontrole UAT nie tworzyły ofert, zakupów ani kopalń na kontach graczy. Nie wykonywano wizualnego testu w przeglądarce.
