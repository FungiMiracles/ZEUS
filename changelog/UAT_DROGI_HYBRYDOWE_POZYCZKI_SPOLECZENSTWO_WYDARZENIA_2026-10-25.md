# UAT — drogi, działania hybrydowe, pożyczki i nowe ekrany, 25.10.2026

## Drogi

Miasta są rysowane w osobnej warstwie nad liniami dróg. Początek lub koniec odcinka można wskazać na istniejącej autostradzie, drodze krajowej albo skrzyżowaniu. Przyciąganie uwzględnia najbliższy fragment i dokładne przecięcia różnych dróg; nie traktuje kolejnych punktów jednej krzywej jako skrzyżowań.

Nowe odcinki otrzymują łagodny łuk, uwzględniony w zapisywanej geometrii, długości i cenie. Sprawdzany jest przebieg każdego fragmentu krzywej. Gdy łuk wychodzi poza dozwolony teren, zmniejszane jest wygięcie; w skrajnym przypadku pozostaje odcinek prosty. Administrator może prowadzić połączenie przez ląd różnych państw; gracz buduje we własnej części metropolitalnej. Istniejącym drogom dodano łuki bez zmiany historycznych długości i kosztów.

Naprawiono minutowe przeładowanie infrastruktury, które zamykało edytor. Podczas pracy w zakładce dróg przeładowanie jest pomijane. Wybrana zakładka jest zachowywana również po ręcznym odświeżeniu.

## Wywiad i mapy wojskowe

Dodano pięć misji hybrydowych: cyberatak na energetykę, kolej i porty po -3 punkty właściwej infrastruktury, podpalenie -1 do mieszkań oraz ładunek na kolei -2 do energetyki, zgodnie z podaną specyfikacją. Wartości nie spadają poniżej zera. Zmiany trafiają do historii regionu, a ponowne rozliczenie nie zadaje kolejnych szkód. Misje używają dotychczasowego kosztu 3 mld ROI, siedmiu dni Entendy i tej samej szansy powodzenia zależnej od poziomu agenta oraz kontrwywiadu.

Nieudana misja hybrydowa może zakończyć się schwytaniem: ryzyko na tym etapie odpowiada procentowi ochrony kontrwywiadowczej celu. Schwytany agent nie wraca i nie można go wysłać ponownie; jego rekord i raporty pozostają w historii. Oba państwa otrzymują komunikaty wyniku i ewentualnego schwytania. Rozliczenie może zostać uruchomione także przy odczycie powiadomień państwa sabotowanego. Zwykłe misje wywiadowcze zachowują dotychczasowe działanie.

Obie mapy wojskowe mają przycisk „Odznacz wszystkie” / „Zaznacz wszystkie”, sterujący sześcioma niezależnymi filtrami obiektów.

## Pożyczki

W budżecie dodano wnioski do innych aktywnych graczy, akceptację i odrzucenie przez wierzyciela, wycofanie oczekującego wniosku i pełną spłatę przez dłużnika. Bez dodawania automatycznych odsetek lub terminów, których nie określono.

Środki przepływają pomiędzy rezerwami państw w jednej transakcji. Gdy rezerwa płacącego nie wystarcza, formularz proponuje jawne przesunięcie dokładnej brakującej kwoty z wybranego sektora aktualnego półrocza. Brak wyboru, niewystarczające niewydane środki lub zmiana kwoty brakującej od podglądu blokują wypłatę bez częściowego obciążenia. Uwzględniane są wydatki, zobowiązania i utrzymanie wojska.

Dwustronny rejestr ruchów obejmuje wypłatę i spłatę, zachowuje zerową sumę i jest uwzględniany w saldach sektorów oraz przenoszeniu rezerwy na kolejne półrocze, także przed pierwszym budżetem. Akceptacja i spłata są idempotentne; strony sprawdzane są po stronie serwera. Kwoty zachowują grosze także powyżej zakresu bezpiecznych liczb JavaScript. Powiadomienia o pożyczkach prowadzą do odpowiedniej sekcji budżetu.

## Społeczeństwo i wydarzenia

Odblokowano dwie pozycje głównego menu gry. Społeczeństwo pokazuje 18 aktualnych wskaźników państwa i pełne opisy skopiowane z WIKI. Tooltipy działają myszą, klawiaturą i dotykiem oraz nie są przycinane przez karty.

Wydarzenia pokazują dane Generatora Zdarzeń bez przycisków i tras usuwania. Dostępne są filtry WIKI, nazwy państw i regionów z podpowiedziami oraz „Pokaż wydarzenia z mojego kraju” (wraz z zarządzanymi państwami). Rekord zawiera ofiary i zapisane skutki dla ludności, infrastruktury, środowiska i wskaźników społecznych, z historii zmian i snapshotów. Wskazywany jest brak zastosowanych lub zapisanych skutków, zamiast wymyślania wartości. Wyniki są stronicowane, a niepoprawne filtry obsługiwane komunikatem.

## Migracja i weryfikacja

`migrations/sql/roads_hybrid_loans_20261025_migrate.py` działa tylko na `entenda_uat_db`. Dodaje geometrię dróg, czas schwytania agenta, rozszerza słownik misji i tworzy dwie tabele pożyczek. Nie zmienia historycznych kosztów ani sald rezerw. Ponowne wykonanie i zapis geometrii sprawdzone.

Przeszły 233 testy Pythona oraz 13 testów JavaScript. Kontrole obejmują autoryzację, CSRF, idempotencję, brak częściowych wypłat, finansowanie różnicy, spłatę, przenoszenie rezerw, skutki i schwytanie agentów, łuki i przecięcia dróg, filtry wydarzeń oraz zgodność tooltipów.

Sprawdzono renderowanie 15 ekranów gry i dwóch paneli WIKI. W Chromium, jako zwykły gracz bez roli WIKI, sprawdzono nowe ekrany, oba przyciski filtrów wojskowych, warstwy mapy, przyciąganie do istniejącej drogi, brak przeładowania podczas pracy i zachowanie zakładki. Formularz uzupełnienia rezerwy sprawdzono na atrapach odpowiedzi, bez przekazywania pożyczek na kontach graczy. Sprawdzono widok mobilny 390×844, dotykowe tooltipy i brak poziomego przepełnienia. Osobno sprawdzono w przeglądarce edytor WIKI, wybór miast z innych państw oraz warstwy miast nad drogami. Nie wykonywano testów na fizycznym telefonie.

Kontrole działającej bazy potwierdziły obecność geometrii wszystkich dróg, zgodność rezerw i brak niezbilansowanych ruchów pożyczek. Nie tworzono testowych pożyczek, misji ani dróg w UAT; zapisy testowano na izolowanym SQLite. Usługa została łagodnie przeładowana; pliki klienta mają nowe wersje cache. Zrzuty kontroli: `/tmp/zeus-uat-round3/`.
