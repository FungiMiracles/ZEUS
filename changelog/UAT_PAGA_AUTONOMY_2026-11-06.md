# PAGA — etap 1.3: silnik decyzyjny i pamięć (UAT, 06.11.2026)

Korekta wiedzy o siłach przeciwnika: autonomia nie odczytuje garnizonów obcych baz, również gdy rozpoznanie ujawniło ich lokalizację. Obecne raporty dostępne graczowi podają lokalizację i poziom bazy, bez liczebności garnizonu. W takim przypadku PAGA zapisuje siłę przeciwnika jako nieznaną; zmiany jego rzeczywistego garnizonu nie wpływają na ocenę decyzji. Własne zasoby pozostają dostępne państwu.

Silnik działa na serwerze bez obecności graczy, bez modeli językowych i wyłącznie w UAT. Kwalifikują się aktywne, suwerenne państwa z zatwierdzoną konfiguracją PAGA i włączoną autonomią, bez jakiegokolwiek przypisania do konta gracza. Wersja robocza konfiguracji nie steruje decyzjami.

Analizy odbywają się co 1 dzień Entendy. Pierwszy termin jest rozłożony w ciągu najbliższego dnia i zapisany w bazie. Po przestoju wykonywana jest jedna zaległa analiza, bez odtwarzania serii działań z pominiętych miesięcy. Istotne wydarzenia mają niezależną kolejkę reakcji z opóźnieniem 6–18 godzin Entendy. Analiza może zakończyć się biernością.

Ocena kandydatów uwzględnia siedem cech, wszystkie aktywne interesy z malejącymi wagami, sąsiedztwo, sojusze, znaną siłę i zasoby oraz indywidualne oceny zaufania, zagrożenia i wiarygodności informacji. Losowość jest ograniczana przewidywalnością. Rzeczywiste zatwierdzone profile charakteru innych państw są znane zgodnie z wymaganiem i); tajne zapasy i nierozpoznane obiekty nie są źródłem wiedzy silnika.

Decyzje rzeczywiście korzystają ze wspólnych usług gry: propozycji relacji, partnerstw i sojuszy, wypowiadania wojny, akceptacji lub odrzucenia ofert, rekrutacji agentów, siedmiu rodzajów rozpoznania i pięciu operacji hybrydowych. Propozycje do ludzi pozostają do ich decyzji i używają zwykłych powiadomień. NPC nie otrzymują sztucznych kont użytkowników. Operacje agentów zachowują zwykłe koszty, dostępność, siedmiodniowy czas i prawdopodobieństwo powodzenia. Potrzebują istniejącego budżetu służb; ten etap nie tworzy autonomicznie budżetów ani dodatkowych środków.

Pamięć jest trwała i indywidualna. Zdarzenia publiczne są dostępne wszystkim obserwatorom, raporty wywiadu tylko uprawnionemu państwu. Niewykryty sprawca sabotażu nie jest ujawniany ofierze. Wpływ wspomnień maleje z czasem (okres połowicznego zaniku 120 dni Entendy), bez kasowania historii. Zbieranie nowych wydarzeń rozpoczyna się od uruchomienia etapu; starsze wydarzenia nie są odtwarzane wstecz.

W PAGA dostępny jest „Monitor autonomii”: globalne zatrzymanie, limity, harmonogramy, historia analiz i kandydatów, wyniki, błędy oraz pamięć i oceny wybranego kraju. Historia ma filtry państwa, dat Entendy i rodzaju decyzji. Dostęp zachowuje kontrolę roli Wszechmocny i potwierdzenia hasła.

Domyślny maksymalny limit wynosi 3 działania na 30 dni Entendy (charakter może go obniżyć), a ponowienie tego samego rodzaju działania wobec tego samego celu wymaga 7 dni. Reakcje współdzielą limit z analizami okresowymi; głębokość łańcucha reakcji jest ograniczona do 2. Globalne i indywidualne zatrzymanie blokuje nowe decyzje. Wcześniej rozpoczęte misje kończą się zgodnie ze zwykłymi zasadami gry, a pamięć nadal zbiera wydarzenia.

Harmonogramy, kolejka, pamięć, limity i historia pozostają w bazie po restarcie. Blokady transakcyjne i unikatowe identyfikatory analiz chronią przed podwójnym wykonaniem w wielu procesach. Nieudana decyzja wycofuje swoją transakcję, zapisuje błąd i pozwala innym państwom kontynuować. Rejestr adapterów umożliwia dodawanie kolejnych działań bez przebudowy harmonogramu i pamięci.

Zmiana częstotliwości obejmuje istniejące harmonogramy: odległe terminy miesięczne są automatycznie przenoszone w najbliższy dzień, z zachowaniem rozproszenia. Już bliskie i zaległe terminy pozostają do obsługi, a następne analizy mają rytm dobowy. Limity działań i okresy oczekiwania pozostają zgodne z ustawieniami PAGA. Reakcje są gotowe po 6–18 godzinach Entendy, z zapasem do doby na obsługę zadania w tle; globalne zatrzymanie, błędy i niedostępność serwera mogą opóźnić wykonanie.
