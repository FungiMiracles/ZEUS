# Diagnostyka i naprawa PAGA AI — 9 listopada 2026, wyłącznie ZEUS_UAT

## Zakres i bezpieczeństwo

Globalne AI wyłączono przez istniejący CLI: OFF, rewizja 12. Zadania oczekujące i uruchomione zostały anulowane przez standardowy mechanizm. Nie włączano globalnych zapisów na czas testów. Testy uruchamiają własne tożsamości AI i kontrolę ON wyłącznie w SQLite w pamięci, bez połączenia z bazą UAT ani PROD. Zmiany dotyczą adaptera, schematów, projekcji odpowiedzi i instrukcji Qwena. Nie zmieniono usług walidacji ani zasad ekonomii, wojska czy dyplomacji. Nowa tabela lub migracja bazy nie jest potrzebna.

## Wszystkie 65 historycznych zatwierdzeń

Źródło: pierwsze 251 wpisów audytu, identyfikatory 1–251. Szczegółowa lista parametrów, odpowiedzi i dodatkowych problemów każdego zatwierdzenia znajduje się w `paga-budget-original-65.json`.

| Bezpośrednia przyczyna odpowiedzi ZEUS | Liczba |
|---|---:|
| Brak roku lub półrocza przekazanego jako liczba całkowita | 39 |
| Brak tokenu podglądu o wymaganej długości 64 znaków | 26 |
| Udane zatwierdzenie | 0 |

Wszystkie 65 poleceń miały brakujący lub niepoprawny token. W 39 przypadkach wcześniejsza kontrola typu roku/półrocza zasłaniała ten problem. Nie były to błędy wygasania sesji ani potwierdzone kolizje prawidłowych tokenów. Żadne z tych poleceń nie dotarło do właściwego księgowania budżetu.

Dodatkowe problemy, częściowo nakładające się i zasłonięte przez wcześniejsze walidacje: 45 niekompletnych nowych planów, 8 błędnych lat gry, 4 błędne półrocza, 10 planów z nieznanymi kategoriami, 6 planów z sumą udziałów ponad 100%. „Nieprawidłowy rok lub półrocze” w tej próbie oznaczał głównie brak wymaganych pól; konkretny błędny rok 2024/2025 lub półrocze 3 mogły przejść kontrolę typu i zatrzymać się dopiero na tokenie.

PIT 0,05% jest dozwolony przez grę. Problem polegał na niejasnych jednostkach i braku rzetelnej oceny skutków, a nie na konieczności zakazania niskich podatków.

## Przyczyny integracyjne

1. Katalog traktował techniczny formularz jako decyzję gracza: rok, półrocze i token wystawiano modelowi do samodzielnego wytworzenia. Token zawiera aktualną podstawę ekonomiczną i rezerwę; nie wolno go zgadywać.
2. Finanse trafiały do modelu jako duży dokument HTML z uciętym początkiem. Istotne fakty nie miały gwarantowanego miejsca w pierwszym fragmencie. Adapter pokazuje teraz zwięzłą projekcję własnego stanu z odpowiedzi normalnej trasy gracza.
3. Schemat `shares` dopuszczał dowolne nazwy, co sprzyjało kategoriom nieistniejącym w grze. Obecny schemat podaje rzeczywiste kody. Standardowa walidacja nadal kontroluje sumę, dokładność i zakresy.
4. Automatyczne wydobywanie parametrów z całego pliku usługi błędnie wymagało `action` także w rozkazach wojennych i operacjach drogowych. Te trasy używają odpowiednio `kind` oraz parametru ścieżki `operation`/pola `decision`. Poprawiono schematy.
5. Pozostałe techniczne potwierdzenia również wymagają adaptera: cena punktu badań, koszt i przebieg drogi, wersja edytowanego wpisu, odczytany poziom kontrwywiadu. Pobierane są z własnych wcześniej odczytanych wyników; zmiana ceny/wersji nadal powoduje zwykły błąd gry.
6. Przekazanie środków do `social_policy` nie jest wypłatą świadczeń. Nowy plan zachowuje osobną decyzję o kwotach `benefits.children` i `benefits.seniors`; brak kwot oznacza jawnie pokazane wypłaty 0. Powtarzanie planu odczytuje poprzednie wypłaty przez własną historię gracza i zachowuje standardowe zasady powtórzenia.

## Nowy przebieg budżetu

`game_finance.page:GET` → decyzja o PIT, udziałach i kwotach świadczeń → `game_finance.preview:POST` → ocena wyliczonych skutków → `game_finance.approve:POST`.

Model wybiera ekonomię i podaje uzasadnienie. Polityka `available_proportional` jest jawną decyzją: pokryć oczekiwania proporcjonalnie, najwyżej do dostępnego przydziału wraz z przeniesieniem. `expected` żąda pełnych kwot, `none` oznacza brak wypłat, a konkretne kwoty w milionach są alternatywnym trybem. Nie łączy się polityki z kwotami. Konkretna niewypłacalna dyspozycja nadal jest odrzucana, a polityka częściowego pokrycia wymaga potwierdzenia niedoboru przed zatwierdzeniem. Końcowy kontrakt używa `allocation_weights` (względne wagi priorytetów) oraz jawnej polityki świadczeń (`benefit_policy`) albo `benefits_millions` (konkretnych kwot w milionach). ZEUS przelicza proporcje na udziały z dokładnością do dwóch miejsc, a zwykły kalkulator gry kieruje resztę zaokrągleń do rezerwy. Nie jest to ciche naprawianie błędnych procentów: jawny stary plan `shares` przekraczający 100% nadal jest odrzucany. Przeliczone udziały i kwoty są pokazane modelowi przed zatwierdzeniem. Tę zmianę uzasadniły rzeczywiste testy: Qwen błędnie sumował udziały i podawał 100 jednostek, opisując je jako 100 milionów. ZEUS przechowuje ostatni udany podgląd dla własnego państwa i zadania. Wewnętrzny zapis obejmuje dokładny plan oraz okres i token zwrócone przez prawdziwą trasę podglądu. Zatwierdzenie uzupełnia je po stronie serwera; model nie podaje tokenu ani ukrytych pól. Nie przelicza się po cichu innego planu podczas zatwierdzania. Zmieniona podstawa lub półrocze są odrzucane przez istniejące usługi.

Podgląd pokazuje stawkę w procentach, zmianę dochodów, przydziały, oczekiwania społeczne, dostępne środki z przeniesieniem oraz faktycznie zaplanowane wypłaty. Po błędnej sumie udziałów adapter podaje obliczoną sumę i wielkość przekroczenia. Nie normalizuje po cichu błędnych udziałów i nie zmienia priorytetów AI.

Spadek dochodów i niezaspokojenie oczekiwań społecznych wymagają świadomej decyzji modelu (`accept_revenue_decline`, `accept_social_shortfall`) wraz z uzasadnieniem. Te potwierdzenia dotyczą kontraktu AI, nie reguł gry. Nadal można zatwierdzić radykalnie niski PIT; kontrolowany test zatwierdza 0,05%. Wypłaty ponad dostępne środki pozostają odrzucane przez standardową grę.

## Powtarzanie błędów

Trwały audyt przechowuje skrót decyzji i zaobserwowanego stanu. Identyczna odrzucona dyspozycja jest blokowana przed ponownym wywołaniem widoku. Zmiana samego uzasadnienia lub zapisu liczby `10` na `10.0` nie stanowi poprawy. Ponowne odczytanie tych samych danych/wyceny nie resetuje blokady. Mechanizm działa także między zadaniami tego samego państwa w tej samej rewizji uprawnień. Nowa decyzja albo zmieniony, odczytany stan pozwalają na korektę. Kontrole uprawnień i blokada zatwierdzania transakcji pozostają aktywne.

## Weryfikacja zapisów

Polecenia odtwarzające:

```sh
PYTHONPATH=tests:. venv/bin/python -m unittest discover -s tests -q
venv/bin/python scripts/paga_ai_write_verification.py
venv/bin/python scripts/paga_ai_budget_acceptance.py
venv/bin/python scripts/paga_ai_budget_acceptance.py --correct-invalid
```

Pierwsze dwa polecenia nie uruchamiają modelu. Dwa ostatnie uruchamiają rzeczywisty Qwen3.5-4B przez dotychczasowy bwrap i limity zasobów, z katalogiem ograniczonym do finansów na czas kontrolowanego testu. To test wykonawczy wybranego modułu, a nie dowód jakości wszystkich autonomicznych strategii.

Zestaw zapisu sprawdza m.in. budowę i własność fabryki, brak wymaganych technologii, produkcję amunicji wraz ze zużyciem wejść, ofertę handlową, kopalnię, pożyczkę, zakup punktów badań, budowę i modernizację drogi, rozmieszczenie i lokalizację bazy, rzeczywisty zapis rozkazu i zużycie rakiet, stan wojny, dyplomację, rekrutację i kontrwywiad, edycję forum z kontrolą wersji oraz księgowanie budżetu i świadczeń. W testach mapy i zegar są syntetycznymi danymi scenariusza; nie zmienia się walidatorów produkcyjnych.

SQLite używa zgodnych natywnych identyfikatorów zamiast specyficznych dla MySQL definicji kolumn i części ograniczeń DDL. Właściwe trasy i domenowe walidacje są prawdziwe. Nie wykonano autonomicznych zapisów modelu na współdzielonej bazie UAT.

W 22 kontrolowanych scenariuszach zapisów odnotowano 42 udane odpowiedzi operacji, 27 celowych odrzuceń oraz 3 blokady duplikatów. Zatwierdzenia budżetu: 9 udanych i 9 celowo odrzuconych. Pełna regresja: 553 uruchomione testy, bez błędów. Dokładne liczby i przyczyny zawiera `paga-write-verification.json`. Próby negatywne są celowo błędne; nie należy interpretować ich odsetka jako skuteczności modelu.

## Wyniki rzeczywistego modelu i ograniczenia

`paga-budget-real-initial-diagnostic.json` dokumentuje pierwszą próbę: budżet i naliczenie podatku powstały, ale skrypt raportujący miał błąd odczytu stawki z niewłaściwego modelu ORM. Naprawiono skrypt. W tej próbie Qwen również błędnie opisywał skalę dochodów i wystarczalność świadczeń; doprowadziło to do dodania obliczeń porównawczych i jawnych decyzji o niedoborze.

`paga-budget-real-percentages-diagnostic.json` zachowuje próbę pośredniego kontraktu z surowymi procentami i kwotami. Jej wynik nie jest odbiorem końcowego kontraktu intencji.

`paga-budget-real-legacy-correction.json` dokumentuje rzeczywistą korektę po odrzuceniu: model ponownie przekroczył limit udziałów, następnie poprawił plan do 100%, uzyskał podgląd i zapisał budżet z PIT 10%. Ta próba poprzedza rozszerzenie adaptera o jawne kwoty świadczeń i potwierdzenia skutków. Nie jest przedstawiana jako pełny odbiór końcowej wersji.

Próbę wag z ręcznymi kwotami przerwano po wprowadzeniu jawnej polityki świadczeń; zachowano ją jako `paga-budget-real-weights-amounts-diagnostic.json`.

Odbiór końcowej wersji obejmuje także reakcję rzeczywistego modelu na celowo odrzucony plan i blokadę duplikatu. Wynik znajduje się w `paga-budget-real-acceptance.json`. Dalsze obserwacje jakości strategii są konieczne: poprawne wykonanie operacji nie dowodzi prawidłowości każdej wypowiedzi ani optymalności decyzji małego modelu. Globalne AI pozostaje wyłączone; raport nie jest zgodą na masowe włączenie państw.


## Ostateczny wynik odbioru

Wersja końcowa: PASS, rzeczywisty Qwen, kod niezmieniony w trakcie próby (SHA256 w artefakcie). Na SQLite w pamięci wywołano początkowy odczyt finansów, celowo błędny plan procentowy (odrzucony), jego duplikat (zablokowany), następnie model sam wybrał nowy plan i go zatwierdził: dwa poprawne polecenia modelu, zero odrzuconych poleceń modelu w końcowej próbie. Zapisano jeden budżet, jedno naliczenie podatku, PIT 5%, wypłaty children=100 mln i seniors=100 mln. Model świadomie zaakceptował 40% pokrycia oczekiwań 500 mln i wskazał priorytety edukacji, badań i bezpieczeństwa. Nie wymuszano konkretnych wartości jego decyzji.

Łącznie w kontrolowanych testach: 27 udanych operacji zmiany stanu gry i 15 udanych podglądów/wycen, 27 oczekiwanych odrzuceń, 3 blokady duplikatów. Są to scenariusze integracyjne, a nie statystyka autonomicznej gry 44 państw. Końcowy model został sprawdzony w module budżetu; pozostałe moduły sprawdzono wykonawczo przez wspólne trasy i walidacje, bez deklarowania jakości wszystkich możliwych strategii Qwena.

Podsumowanie maszynowe: `paga-budget-repair-validation.json`. Pełny ślad końcowego modelu: `paga-budget-real-acceptance.json` (ta sama końcowa próba co `paga-budget-real-correction.json`). UAT przeładowano łagodnie. Końcowy stan globalnego AI: OFF, rewizja 14. Nie uruchomiono autonomicznych zapisów na współdzielonej bazie UAT ani w PROD.


### Zewnętrzne przełączenie pod koniec odbioru

Po pozytywnym teście końcowa kontrola wykazała ON w rewizji 13. Skrypty naprawy nie wywoływały enable na UAT; tożsamość osoby lub procesu przełączającego nie jest zapisywana w tabeli kontroli i nie została ustalona. Przywrócono OFF w rewizji 14 i anulowano 41 zadań tej rewizji. Ograniczony audyt rewizji 13 wykazał wyłącznie operations.list (1) i odczyt finansów (1), bez operacji zapisu gry. Nie należy mylić tego z testowymi zapisami w odizolowanym SQLite.
