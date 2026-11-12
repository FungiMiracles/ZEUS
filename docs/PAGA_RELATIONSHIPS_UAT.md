# Powiązania historyczne PAGA — ZEUS_UAT

Nowa sekcja w ZEUS WIKI → PAGA → **Powiązania między państwami** pozwala administratorowi wybrać dwa różne aktywne państwa i zapisać jedną sugestię dla pary:

- **Państwo satelickie** — dodatkowy wybór określa, które państwo jest satelitą, a które patronem. Qwen otrzymuje własną rolę, identyfikatory satelity i patrona oraz jednoznaczne zdanie opisujące kierunek zależności.
- **Historyczny sojusznik** — bardzo silna preferencja utrzymania przyjaźni; wojna, sabotaż i działania hybrydowe wobec sojusznika powinny być wyjątkowo rzadkie.
- **Historycznie nieprzyjazne** — bardzo silna preferencja utrzymania dystansu; inicjowanie lub akceptowanie poprawy stosunków powinno być wyjątkowo rzadkie, ale możliwe.
- **Brak sugestii** usuwa obowiązującą sugestię, zachowując historię zmian.

Są to wskazówki strategiczne. Nie ustanawiają traktatu, nie zmieniają aktualnych wpisów w `stosunki`, nie tworzą formalnej zależności ustrojowej i nie blokują działań wojennych lub dyplomatycznych. Wskazówka obowiązuje również wtedy, gdy drugim państwem zarządza człowiek, ale wpływa wyłącznie na decyzje Qwena. Nie narzuca decyzji graczowi ludzkiemu.

„Wyjątkowo rzadkie” jest instrukcją dla modelu, a nie określoną procentowo szansą. Nie dodano losowania ani zakazu w walidatorach działań gracza. Qwen może uzasadnić odstępstwo istotnymi wydarzeniami lub interesem narodowym; instrukcja prosi o zapisanie istotnego odstępstwa w jego pamięci strategicznej. Sama historyczna nieprzyjaźń nie nakazuje ataku.

## Integracja i zapis

`game/paga_relationships.py`: kanoniczna para identyfikatorów uniemożliwia zdublowanie A–B jako B–A. Kierunek satelicki jest zapisany jako osobny identyfikator, więc zmiana kolejności państw w formularzu nie odwraca zależności. Zapisy są transakcyjne, wersjonowane i rejestrowane wraz z administratorem/czasem. Równoczesna edycja w innym oknie daje błąd 409; należy wczytać konfigurację ponownie. Wycofanie sugestii nie resetuje wersji, więc starsze okno nie może jej przywrócić bez ponownego odczytu.

`routes_paga.py` udostępnia chronione dotychczasową rolą, hasłem wejścia, dowodem sesji i CSRF endpointy:

- `GET /admin/paga/powiazania/panstwa` — aktywne państwa do wyboru;
- `GET /admin/paga/powiazania?page=1` — zapisane sugestie, po 25 par na stronę;
- `GET/POST /admin/paga/powiazania/{pierwsze}/{drugie}` — odczyt/zapis pary.

`engine/paga_ai_scheduler.py` przekazuje modelowi wyłącznie powiązania dotyczące własnego państwa. Nie przekazuje konfiguracji obcych par, danych administratora ani historii edycji. Kontekst jest odświeżany przed każdym kolejnym krokiem analizy. Ustawienia zmienione podczas już trwającego generowania są widoczne od następnego kroku. Qwen nie ma operacji edycji tych ustawień administratora.

Migracja `migrations/sql/paga_relationships_20261108.py` została zastosowana wyłącznie w UAT. Tworzy `game_paga_relationships` i `game_paga_relationship_revisions`; nie dodaje przykładowych powiązań, nie zmienia stosunków i nie przełącza AI. Jest powtarzalna. PROD pozostaje bez zmian.

## Weryfikacja

- 501 testów pełnej regresji zakończonych powodzeniem (72,931 s).
- Dodatkowe testy dotyczą uprawnień, CSRF, niepoprawnych par/statusów, kierunku satelickiego, historii, usuwania, konfliktu wersji, izolacji własnego kontekstu i odświeżania sugestii pomiędzy decyzjami.
- Testy istniejących operacji potwierdzają możliwość wypowiedzenia wojny historycznemu sojusznikowi oraz zaproponowania poprawy stosunków historycznemu przeciwnikowi. Preferencja nie jest blokadą wykonawczą.
- Chromium: wszystkie statusy, odwrócona kolejność wyboru państw, zapis i usuwanie, walidacja tej samej pary, brak błędów JavaScript oraz brak poziomego przewijania przy szerokości 390 px.
- Rzeczywisty Qwen w pierwszym fikcyjnym scenariuszu wybrał współpracę zamiast ataku/sabotażu wobec sojusznika lub poprawy stosunków z przeciwnikiem. Po zauważeniu niejednoznacznego opisu kierunku dodano jawne identyfikatory i zdanie opisujące własną rolę. Kolejny test modelu przerwano po wykryciu aktywnego AI na UAT, aby nie uruchamiać dwóch analiz jednocześnie. Nie wykonano testowych działań modelu na rzeczywistej bazie.

## Stan wdrożenia — 9 listopada 2026

Po wyraźnej zgodzie użytkownika wykonano łagodne przeładowanie ZEUS_UAT w przerwie między analizami, po uzyskaniu wyłącznej blokady kolejki. Zweryfikowano master PID, katalog UAT i port 5001 przed wysłaniem sygnału. Nowe procesy 392166 i 392183 wczytały aktualny kod, w tym jawne doprecyzowanie kierunku zależności satelickiej. Uwierzytelnione odczyty HTTP listy państw i zapisanych sugestii zwróciły 200. Panel udostępnia 99 aktywnych państw. Nie dodawano przykładowych powiązań.

Podczas oczekiwania przełącznik AI został zmieniony zewnętrznie z WŁĄCZONE (rewizja 7) na WYŁĄCZONE (rewizja 8). Samo przeładowanie zachowało nowszą konfigurację i nie przełączyło AI. Po przeładowaniu użytkownik wyraźnie potwierdził pozostawienie AI wyłączonego. Wdrożenie zakończono z AI w stanie WYŁĄCZONE (końcowy odczyt: rewizja 10); nowe sugestie będą uwzględniane po ponownym włączeniu AI. Pozostały silnik gry działa. Potwierdzenie przeładowania i odpowiedzi HTTP zapisano w `runtime/qwen/relationships_reload.json` oraz `docs/paga-relationships-validation.json`.
