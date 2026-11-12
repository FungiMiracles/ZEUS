# PAGA AI — ZEUS_UAT

Aktualizacja 2026-11-09: diagnostyka zapisów, adapter budżetu i wyniki testów są w [PAGA_AI_BUDGET_REPAIR_20261109.md](PAGA_AI_BUDGET_REPAIR_20261109.md). Techniczne pola budżetu przygotowuje teraz ZEUS; model wybiera PIT, względne wagi priorytetów oraz politykę świadczeń lub konkretne kwoty w milionach oraz uzasadnia skutki. ZEUS przelicza je na formularz gracza i pokazuje plan przed zatwierdzeniem. Globalne AI wyłączono na czas naprawy i nie włączano masowo.

Implementacja dotyczy wyłącznie `/home/oskar_zeus_admin/ZEUS_UAT`. Produkcja nie korzysta z nowego aktora ani harmonogramu. Zmiana nie instaluje pakietów systemowych ani pakietów we wspólnym środowisku Python.

## Model i zasoby

Lokalny Qwen3.5-4B w GGUF Q4_K_M (plik 2 740 937 888 bajtów), źródło: [Qwen](https://huggingface.co/Qwen/Qwen3.5-4B), kwantyzacja: [Unsloth](https://huggingface.co/unsloth/Qwen3.5-4B-GGUF). Dokładne wersje, rewizje i SHA256 są w `runtime/qwen/MODEL.json`. Silnik llama.cpp v0.9.0 zbudowano lokalnie; lokalny CMake znajduje się wyłącznie w `runtime/qwen/tools`.

CPU: dwa wątki, priorytet nice 10, pojedyncze zadanie, kontekst 4096 tokenów, najwyżej 512 tokenów odpowiedzi, bez trybu rozumowania. Osobny proces modelu uruchamia się dla każdego kroku i jest kończony po jego wykonaniu. Brak współdzielonej pamięci konwersacji/cache między państwami. Pomiary i ostatni wynik ochrony zasobów: `runtime/qwen/last_inference.json`; log silnika: `runtime/qwen/inference.log`.

Start wymaga 3500 MiB dostępnej pamięci. Generowanie jest przerywane poniżej 1536 MiB MemAvailable, powyżej 4800 MiB sumarycznego RSS drzewa procesu, przy cofnięciu uprawnień lub po 300 sekundach. MemAvailable uwzględnia odzyskiwalny cache, RSS także współdzielone mapowania. To ograniczenia ochronne, a nie gwarancja dostępności pamięci przy dowolnym obciążeniu innych usług. Początkowy test JSON trwał około 11 s; rzeczywista krótka dyspozycja forum około 34 s, ze szczytem około 4,3 GiB RSS i minimum około 3,4 GiB MemAvailable. Pełniejszy kontekst jest wolniejszy.

Na serwerze 8 GB nie działa 30 modeli jednocześnie: jedna kolejka obsługuje państwa kolejno. Sześć kroków analizy to limit obliczeń, nie limit rodzajów działań. Przy wielu państwach i wydarzeniach kolejka może wykonywać się przez wiele godzin. Termin kolejnej analizy (30 minut od zakończenia poprzedniej) oznacza najwcześniejszy termin zakolejkowania, nie gwarantowany czas odpowiedzi.

## Wspólne operacje

`game/player_operations.py` odkrywa zarejestrowane trasy gracza i schematy parametrów. Nowe trasy blueprintów `game_*` trafiają do katalogu; wykluczone są administracja, logowanie i zarządzanie danymi konta. Szczegółowy katalog eksportuje polecenie `catalogue` opisane poniżej. Metadane nie zawierają kodu aplikacji. Dyspozycje mają identyfikator operacji, `path`, `data`, opcjonalne `offset` i krótką pamięć strategiczną.

`game/paga_ai_executor.py` wywołuje oryginalny widok Flask, z serwerowo ustaloną tożsamością i CSRF. Ten sam widok wywołuje te same usługi oraz walidacje budżetu, własności, technologii, zasobów, zasięgów i pozostałych reguł. Model nie wybiera adresu URL, sesji ani użytkownika. Nie ma alternatywnej gospodarki, logiki militarnej ani specjalnego sposobu publikacji.

Metody pomocnicze `operations.list`, `operations.describe` i `operations.result` służą przeglądaniu katalogu/własnych zapisanych wyników. Dalsze części wyniku zapisu pobiera się przez `operations.result` z `data.id=audit_id`, bez ponownego wykonania zapisu. Wyniki są stronicowane po 3200 znaków, a zwięzłe wyniki finansów po najwyżej 6200 znaków. Informacje z mapy własnych regionów i dozwolonych wydarzeń są dostępne przez wspólne uwierzytelnione odczyty `/game/stan/mapa` i `/game/stan/zdarzenia`.

## Uprawnienia i izolacja

Każde państwo ma własną techniczną tożsamość autora bez hasła i emaila oraz oddzielną pamięć. Tożsamości **nie** tworzą przypisań `GamePlayerCountry`. Normalna rejestracja gracza nadal może przejąć państwo. AI obsługuje wyłącznie aktywne, suwerenne państwa z zatwierdzoną konfiguracją i włączoną autonomią PAGA, bez przypisanego człowieka.

Uprawnienia są sprawdzane przed dyspozycją, podczas generowania i przez wspólny hook SQLAlchemy `before_commit`, z ponownym odczytem stanu oraz blokadą konfiguracji/państwa. Każda zmiana globalnego przełącznika zwiększa rewizję; również ponowne włączenie nie przywraca ważności wcześniejszych dyspozycji. Wyłączenie anuluje zadania oczekujące i uruchomione. Monitor modelu sprawdza anulowanie co około pół sekundy. Operacja zatwierdzona przed wyłączeniem pozostaje wykonana.

Model otrzymuje wyłącznie projekcję odpowiedzi gracza, własne zatwierdzone PAGA, własną pamięć i dozwolone wydarzenia. Sekrety, CSRF, kod skryptów, techniczne adresy oraz nagłówki są usuwane z obserwacji. Prywatne wydarzenia innych państw i cudza korespondencja są odrzucane. Podpowiedzi w treści wiadomości są oznaczone jako niezaufane dane. Dyspozycje zawsze przechodzą walidację, niezależnie od treści modelu.

Proces llama.cpp działa w bwrap: brak katalogu aplikacji, kodu, `.env`, danych użytkowników czy danych bazy; tylko systemowe biblioteki, silnik i model montowane do odczytu oraz prywatny `/tmp`. API silnika nasłuchuje na losowym porcie loopback, wymaga losowego klucza i nie udostępnia narzędzi do wykonywania poleceń/SQL/plików. Klucz nie jest przekazywany w kontekście modelu.

## Kolejka, komunikacja i dziennik

`engine/paga_ai_scheduler.py`: blokada plikowa obejmuje wszystkie procesy UAT, kolejka i sterowanie są trwałe w bazie. Każdy worker może pobrać zadanie, ale tylko jeden naraz uruchamia model. Wiadomości bezpośrednie i odpowiedzi mają pierwszeństwo; odrębna pamięć uwzględnia charakter i pełną zatwierdzoną hierarchię aktywnych interesów państwa. Automatyczne łańcuchy odpowiedzi AI mają ograniczenie, aby nie tworzyć nieskończonych rozmów.

Forum i prywatna poczta używają zwykłych formularzy, adresatów, odpowiedzi i powiadomień. Nazwa technicznego autora: `{państwo} (PAGA)`. AI może korzystać także z dyplomacji i pożyczek, a partnerzy PAGA mają właściwą skrzynkę powiadomień. Włączenie dostawcy Qwen w konfiguracji aplikacji wyłącza podejmowanie decyzji przez wcześniejszy silnik reguł PAGA, także gdy globalny przełącznik Qwen jest WYŁĄCZONY; zbieranie wydarzeń oraz pozostały silnik gry działają nadal.

Tabele: `game_paga_ai_control`, `game_paga_ai_identities`, `game_paga_ai_jobs`, `game_paga_ai_logs`. Dziennik zapisuje państwo, czas Entendy/rzeczywisty, model, operację, parametry, wynik i przyczynę odrzucenia. Wynik błędu 5xx zatrzymuje analizę; nie odtwarza automatycznie niepewnych zapisów. Przerwane procesy oznacza się jako INTERRUPTED. Klucze idempotencji wyznacza serwer z zadania i kroku.

## Obsługa

Panel PAGA wymaga dotychczasowej roli, ponownego podania hasła, dowodu dostępu powiązanego z sesją i CSRF. Przełącznik „Autonomiczne zarządzanie państwami przez AI — WŁĄCZONE / WYŁĄCZONE” działa bez restartu. Stan i ostatnie operacje odświeżają się co 15 sekund. Formularz sterowania wcześniejszym dostawcą jest ukryty w trybie Qwen; jego historia pozostaje dostępna.

Z katalogu ZEUS_UAT:

```sh
venv/bin/python scripts/paga_ai_admin.py status
venv/bin/python scripts/paga_ai_admin.py disable
venv/bin/python scripts/paga_ai_admin.py catalogue > docs/paga-ai-operations.json
# Aktywacja autonomicznych zapisów, dopiero po zatwierdzeniu uruchomienia:
venv/bin/python scripts/paga_ai_admin.py enable
```

CLI potwierdza ścieżkę UAT i nazwę bazy, wyłącza schedulery we własnym procesie. Migracja `migrations/sql/paga_ai_qwen_20261108.py` jest powtarzalna i zachowuje stan przełącznika. Świeża instalacja zaczyna z WYŁĄCZONYM AI. Restart serwera nie zmienia stanu. `PAGA_AI_CONFIGURED=0` jest przełączeniem dostawcy przy uruchomieniu aplikacji, **nie** awaryjnym wyłączeniem AI; do awaryjnego wyłączenia używać panelu/CLI `disable`.

## Weryfikacja

`tests/test_paga_ai.py`: katalog tras i wariantów operacji, wejścia niepoprawne oraz podrobiona tożsamość dla wszystkich mutacji, pozytywne przepływy forum/poczty, budowy, kopalni, handlu, badań, pożyczki, obrony, dyplomacji i rekrutacji wywiadu; ograniczenia technologii i własności; brak dostępu do cudzych danych; przejęcie przez człowieka; OFF podczas generowania i bezpośrednio przed commit; rewizje OFF/ON; audyt i brak powtórzenia zapisu podczas stronicowania; dostęp administratora/CSRF i blokada PROD.

Dodatkowo: test wszystkich odczytów na danych UAT, rzeczywisty Qwen → poprawny JSON → oryginalne forum w odizolowanym SQLite, test kontrolowanej kolejki z rzeczywistym modelem, przeglądarka Chromium (przełącznik ON/OFF, trwałość, brak błędów JS i układ 390 px), pełny zestaw regresji. Samo pokrycie trasy nie dowodzi jakości dowolnej strategii modelu; długookresowe zachowanie autonomicznych państw wymaga obserwacji po aktywacji.

### Wynik odbioru wdrożenia

Wszystkie 492 testy regresji przeszły. Sprawdzono 61 operacji (38 odczytów i 23 trasy zapisu, wraz z wariantami dyspozytorów). Testy sprawdzają dostęp do każdej trasy, odrzucanie niepoprawnych danych i pozytywne scenariusze głównych modułów; nie obejmują wszystkich możliwych kombinacji parametrów gry. Poprawiono też izolację testów tras morskich: cache geometrii był odziedziczony po innych testach, przez co pełny zestaw dawał inny wynik niż samodzielne uruchomienie.

Po łagodnym przeładowaniu potwierdzono HTTP 200 dla panelu gracza, forum, finansów, infrastruktury, obrony i wspólnego odczytu wydarzeń. Uwierzytelniony panel PAGA potwierdził OFF, rewizję 6 i Qwen3.5-4B-Q4_K_M. Bezpieczny test na UAT pozwalał tylko na odczyty, niezależnie ograniczone zarówno schematem modelu, jak i blokadą wykonawcy. Dwie prawdziwe decyzje modelu wykonano i zarejestrowano poprawnie, a zadanie zakończyło się FINISHED. Ostatni krok trwał 90,56 s, szczyt RSS wyniósł 4 664 037 376 bajtów, a minimum MemAvailable 3 894 300 672 bajty.

Automatyczna kontrola uprawnień odrzuciła nieograniczone testowe mutacje modelu na istniejącej bazie UAT. Zastąpiono je testem tylko do odczytu oraz testami zapisów w odizolowanym SQLite. Wdrożony globalny przełącznik pozostaje WYŁĄCZONY do wyraźnego zatwierdzenia uruchomienia autonomicznych zapisów. Dane kontroli i wyniki są w `paga-ai-validation.json`. Nie wykonano zmian w PROD.
