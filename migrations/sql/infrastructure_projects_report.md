# Rozbudowa infrastruktury — ZEUS_UAT

Mapa nie wyświetla kafelków. Kliknięcie regionu otwiera panel po prawej; lista regionów pozwala używać panelu także bez geometrii mapy. Modal wybiera dodatkowe poziomy przyciskami +/− i pokazuje koszt, czas, poziom docelowy oraz dostępny budżet i rezerwę.

Skomunikowanie pozostaje widoczne, ale jego rozbudowa jest wyłączona zgodnie z decyzją użytkownika. Każdy z pozostałych rodzajów korzysta z własnej kategorii budżetu na bieżące półrocze. Niedobór może pokryć rezerwa po zaznaczeniu zgody. Zlecenie przechowuje obie kwoty; historyczne zatwierdzone budżety pozostają niezmienne, a dostępne środki wyliczane są po odjęciu zleceń. Saldo rezerwy jest zmniejszane w tej samej transakcji. Następny budżet uwzględnia wydaną rezerwę.

Populacja to ludność pozamiejska i suma ludności miast. Koszt jednego poziomu: populacja / 10 mln × 2 mld dla dróg, kolei i energii; × 2,5 mld dla mieszkań i portów. Czas całego nowego zlecenia to 4 dni Entendy × liczba dodatkowych poziomów (1 pkt = 4 dni, 2 pkt = 8 dni). Zapisane wcześniej terminy istniejących zleceń pozostają bez zmian. Brak dodatniej populacji lub poprawnego poziomu blokuje zlecenie. Porty są dostępne przy położeniu innym niż śródlądowe (id 1), zgodnie z istniejącą logiką podsumowania państwa.

Zlecenia kończy cykliczne zadanie finansów lub wejście na ekran infrastruktury. Blokady transakcyjne zapobiegają podwójnemu wydaniu środków i podwójnemu zakończeniu. Limit 100 jest kontrolowany również na serwerze. Aktywna rozbudowa blokuje kolejne zlecenie tego samego rodzaju w tym regionie. Ekran z aktywnymi pracami odświeża się co minutę, jeśli modal jest zamknięty.

Przed uruchomieniem wersji należy wykonać `infrastructure_projects_entenda_uat_db.sql`, a następnie zrestartować aplikację. 24.10.2026 wykonano migrację w entenda_uat_db i zweryfikowano tabelę oraz trzy indeksy. Przeładowano procesy Gunicorna UAT sygnałem HUP (systemd wymagał uwierzytelnienia administratora). Potwierdzono dwa nowe procesy robocze, aktywną usługę i odpowiedzi HTTP: strona infrastruktury 302 do logowania, nowe API rozbudowy 401 bez sesji. Produkcji nie zmieniano. Testy izolowane korzystają z SQLite; nie przeprowadzono testów MySQL ani wizualnych w przeglądarce. Środowisko nie zawiera Node.js.


## Poprawki interfejsu 24.10.2026

Mniejsze przyciski rozbudowy znajdują się po prawej stronie wskaźników, obok których dodano ikony. Modal ma ikonę rodzaju infrastruktury, wyśrodkowany licznik oraz osobne karty kosztu, budżetu, rezerwy, czasu i poziomu docelowego, wzorowane na formularzu państwa WIKI. Anulowanie jest czerwone po lewej, a zatwierdzenie zielone po prawej. Regiony podświetlają się przy najechaniu. Miasta państwa widoczne na mapie mają markery i nazwy w tooltipach; kliknięcie otwiera panel ich regionu. Reguła czasu 4 dni za punkt obowiązuje zarówno w podglądzie, jak i zapisie zlecenia. Testy: 75 zaliczonych, w tym liniowy czas rozbudowy i izolacja miast między państwami. Nie wykonano testu wizualnego w przeglądarce. Aktualizacja nie wymaga migracji schematu.

Mapa infrastruktury pokazuje ikonę `PRACE BUDOWLANE.svg` w regionach z aktywnymi zleceniami. Jeden znacznik na region jest umieszczany wewnątrz jego geometrii, z obsługą wysp i wklęsłych granic. Kliknięcie otwiera panel regionu. Po zakończeniu ostatniego zlecenia znacznik znika przy odświeżeniu danych. Testy infrastruktury: 16 zaliczonych. Zmianę uruchomiono przez przeładowanie Gunicorna UAT.

Przyciski Rozbuduj otrzymały ikonę `PRACE BUDOWLANE 2.svg`. Czerwony komunikat w modalu odróżnia brak środków w kategorii budżetu (wymagana zgoda na rezerwę) od braku środków łącznie w budżecie i rezerwie. Ostrzeżenie aktualizuje się przy zmianie poziomów i zgody na rezerwę; serwer niezależnie kontroluje oba przypadki w transakcji. Testy infrastruktury: 17 zaliczonych, w tym brak obciążenia rachunku przy niewystarczających środkach. Uruchomiono na UAT przez przeładowanie Gunicorna; bez migracji schematu.
