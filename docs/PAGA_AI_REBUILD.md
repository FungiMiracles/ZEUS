# PAGA AI — architektura hybrydowa (ZEUS_UAT, listopad 2026)

**Zasada:** ZEUS zarządza procesem decyzyjnym, PAGA AI (Qwen3.5-4B) zarządza państwem. ZEUS nie wybiera strategii,
nie zmienia decyzji modelu i nie omija walidacji gracza. Model nie zajmuje się techniką (tokeny, okresy, wyceny, odczyty kontrolne).

```
zdarzenia gry ──► Event Detector ──► Task Manager ──► Context Builder ──► Qwen (1 decyzja, ≤3 działania)
przegląd strategiczny (gwarantowany) ┘   (deduplikacja,      (dane z tras gracza,     │
zamiary i plany modelu ──────────────┘    priorytety,         MLD, tylko operacje      ▼
                                          starzenie)          danej dziedziny)   Decision Runner + Guard
                                                                                  (sekwencje techniczne, rejestr zapisów,
                                                                                   klasyfikacja wyniku, ≤1–2 korekty)
                                                                                         │ executor = trasy gracza
                                                                                         ▼
                                                                    wynik, pamięć operacyjna, cele, metryki
```

## Moduły

| Moduł | Rola |
|---|---|
| `game/paga_ai_detector.py` | Wykrywanie sytuacji bez modelu: skrzynka powiadomień tożsamości AI (to samo, co widzi gracz), `AutonomyEvent`, forum (adresaci, odpowiedzi, wzmianki), wiadomości prywatne, sondy co 5 min (nowe półrocze, punkty badań, zamiary), harmonogram przeglądów. Powtarzające się fakty łączy w jedno otwarte zadanie. |
| `game/paga_ai_tasks.py` | Task Manager: rodzaje zadań, priorytety CRITICAL–LOW, starzenie (co 30 min oczekiwania +1 poziom), **gwarantowany przegląd strategiczny** (zaległy przegląd wyprzedza wszystko poza CRITICAL), wygaszanie, wykrywanie zadań już wykonanych, pamięć operacyjna (`journal`). Klucz `trigger` = znaczenie + stan gry, unikalny per państwo. |
| `game/paga_ai_context.py` | Context Builder: zwięzły JSON z odpowiedzi tras gracza, kwoty w MLD, tylko operacje dziedziny, budżet rozmiaru (kontekst ≤ 6600 znaków). |
| `game/paga_ai_runner.py` | Decision Runner: wywołanie modelu, wykonanie ≤3 działań, makrooperacja `budget.plan` (preview → kontrola → approve dokładnie tego planu), jedna runda korekty przy błędzie decyzji, plany warunkowe, metryki. |
| `game/paga_ai_guard.py` | Bezpieczeństwo zapisów: rejestr przed zapisem (`game_paga_ai_writes`), `request_id` z (zadanie, decyzja), klasyfikacja wyniku, duplikaty treści, jedna odpowiedź na wiadomość, automatyczne odczyty techniczne. |
| `game/paga_ai_strategy.py` | Cele (z rozbiciem `parent_id`), zamiary, plany warunkowe, monitoring kryteriów z białej listy wskaźników, strukturalna pamięć strategiczna (niezaufana). |
| `game/paga_ai_metrics.py` | Agregaty dla panelu. |
| `game/qwen_runtime.py` | `ModelSession` (jeden proces dla kilku wywołań, leniwy start, opcjonalne `cache_prompt`, parametry `-t/-b/-ub` z pomiarów), strażnicy RAM/czasu/anulowania. |
| `engine/paga_ai_scheduler.py` | `run_tick`: blokada pojedynczej instancji modelu, detekcja, wybór zadania, uruchomienie runnera. |

## Klasyfikacja wyników

| Klasa | Przykład | Reakcja ZEUS |
|---|---|---|
| OK | zapis wykonany | zadanie kontynuowane / zakończone |
| ALREADY_DONE | istniejący budżet, ta sama decyzja już wykonana | zakończenie bez ponawiania i bez wywołania modelu |
| TECHNICAL | brak odczytu/wyceny, nieaktualny token | ZEUS sam wykonuje odczyt; model nie jest angażowany |
| SITUATION_CHANGED | zmiana ceny, wersji, podstaw budżetu | odświeżenie danych, ta sama decyzja może zostać ponowiona |
| DECISION | brak środków, technologii, niedozwolona operacja | jedna zwięzła informacja do modelu, limit prób |
| UNKNOWN | przerwany proces | najpierw stan gry, potem decyzja modelu; ten sam `request_id`, zapis nigdy nie jest odtwarzany automatycznie |
| PERMISSION | przejęcie przez gracza, wyłączenie AI | anulowanie zadania |

## Wdrożenie na UAT

1. Wyłączyć globalne AI w panelu PAGA.
2. `venv/bin/python migrations/sql/paga_ai_rebuild_20261110.py` (kopia w `backups/`, zmiany addytywne; wycofanie: `--rollback`).
3. Łagodne przeładowanie `zeus_uat.service` (HUP gunicorn).
4. W panelu: ustawić „Przegląd strategiczny co najmniej co … minut” i „Maks. wywołań modelu na zadanie”.
5. Włączyć globalne AI w panelu (decyzja użytkownika).

Parametry runtime (po pomiarach): zob. sekcja „Wydajność”.

## Wydajność (pomiary 9 listopada 2026, `docs/paga-ai-benchmark.json`)

Ten sam prompt przeglądu strategicznego (~2850 tokenów), izolowana baza, jedna instancja modelu:

| Ustawienia | Prompt | Generowanie | Wywołanie | Strona UAT (mediana/maks.) |
|---|---|---|---|---|
| `-t 2 -b 64 -ub 32` (poprzednie) | 19,5 tok/s | 4,5 tok/s | 175–187 s | 35/63 ms |
| `-t 6 -b 512 -ub 256` | 62,5 tok/s | 5,4 tok/s | 71–79 s | 57/66 ms |
| j.w. + `cache_prompt` | 61 tok/s, 974 tok. z cache | 5,3 tok/s | 83 s, kolejne 65,5 s | 58/66 ms |

Konfiguracje `-t 4` i `-b 256/-ub 128` nie zostały zmierzone (blokada startu przy < 3,5 GB wolnej pamięci zadziałała tuż po poprzedniej sesji).
Przyjęte: `-t 6 -b 512 -ub 256`, `cache_prompt`, jedna sesja modelu na tick (do 3 zadań), proces zamykany z końcem ticku.
W jednej sesji RSS rośnie (~4,32 → 4,60 → do 5,14 GiB przy 3. wywołaniu); proces jest restartowany przed wywołaniem po przekroczeniu 4,45 GiB.
Start modelu czeka do 90 s na zwolnienie pamięci; brak pamięci odkłada zadanie bez zużycia próby.
Uwaga: podczas pracy modelu część pamięci MySQL trafia do swapu (swap ~3,3 GB); nie utrzymywać modelu w pamięci na stałe.

## Rzeczywisty Qwen (izolowany SQLite, `docs/paga-ai-real-session-*.json`)

| Sesja | Wynik |
|---|---|
| Etapy 2–5, ustawienia poprzednie | budżet zatwierdzony po 1 korekcie (2 wywołania); przegląd bez danych w uproszczonym fixture; atak — 3 odrzucone, zgadywane parametry obrony; brak pętli; 133–164 s/wywołanie |
| Etap 6, nowe ustawienia | budżet: 1 wywołanie, 74 s, pokrycie świadczeń 100%; kolejne zadanie w tej samej sesji 37 s (cache); przegląd i atak przerwane strażnikiem RSS przy 3. wywołaniu → dodano restart procesu |
| Etap 6, weryfikacja restartu | przegląd: 1 wywołanie, cel + zamiar utworzone; atak: 3 wywołania, odrzucenie gry → zablokowane powtórzenie → model sam pobrał dane wojskowe; brak przerwań pamięci |

Wnioski: mechanizm (deduplikacja, ograniczone próby, zakończenie zadań, brak ponownego zatwierdzania, izolacja) działa z rzeczywistym modelem.
Jakość decyzji małego modelu jest ograniczona (zgadywanie parametrów bez danych, powtarzanie odrzuconej akcji, zachowawcze decyzje budżetowe) — testy nie dowodzą jakości strategii.
