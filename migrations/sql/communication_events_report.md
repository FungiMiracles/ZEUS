# Poprawki interfejsu, powiadomienia generatora i komunikacja prywatna

Zmiany wykonano wyłącznie w ZEUS_UAT. Nie uruchomiono migracji, restartów ani publikacji.

## Pliki aplikacji

- `game/communication.py` — nowe API prywatnej poczty i sprawdzanie dostępu.
- `game/communication_models.py` — model prywatnej wiadomości, odpowiedzi i daty odczytu.
- `game/event_models.py` — trwała kopia zdarzenia niezależna od retencji.
- `game/event_notifications.py` — tworzenie powiadomień i plakietek skutków.
- `game/forum.py` — lista, kolory i szczegóły powiadomień generatora.
- `game/forum_models.py` — rozszerzenie powiadomień o zdarzenia generatora.
- `game/diplomacy.py` — flagi państw w danych mapy.
- `engine/generator.py` — dodanie powiadomień w obu ścieżkach tworzenia zdarzeń.
- `zeus_app.py` — rejestracja API prywatnej poczty i kontrola wejścia do modułu.

## Szablony i zasoby

- `templates/game/game_base_layout.html` — koperta, liczniki, modale i wspólne zasoby.
- `templates/game/dyplomacja.html` — modal działań dyplomatycznych.
- `templates/game/srodowisko.html` — mała flaga przed nazwą państwa w nagłówku.
- `templates/game/demografia.html` — mała flaga przed nazwą państwa w nagłówku.
- `static/css/game_ui.css` — wspólne nagłówki, kolory, modale i układ mobilny.
- `static/js/game_ui.js` — pozycjonowanie powiadomień i tooltipa w granicach ekranu.
- `static/js/game_communication.js` — skrzynka, odczyt, wysłanie i odpowiedzi.
- `static/js/game_diplomacy.js` — modal, flagi i przyciski okna państwa na mapie.
- `static/js/game_notifications.js` — ikony, kolory i modal zdarzeń ze skutkami.

## Testy

- `tests/game_features_support.py` — izolowana baza testowa w pamięci.
- `tests/test_game_communication.py` — nowe testy prywatności, limitu znaków, odpowiedzi i odczytu.
- `tests/test_game_event_notifications.py` — nowe testy skutków, właściciela, retencji, transakcji i obu ścieżek generatora.
- `tests/test_game_forum.py` — aktualizacja konfiguracji testów dla nowych tras i modeli.
- `tests/test_game_environment.py` — aktualizacja konfiguracji testów dla nowych tras.
- `tests/test_game_diplomacy.py` — aktualizacja konfiguracji testów dla nowych tras i modeli.

Wynik: 42 testy przeszły (`venv/bin/python -m unittest discover -s tests -p 'test_game_*.py' -q`).
Poprawna składnia Python i Jinja; modele i indeksy kompilują się do dialektu MySQL.
Nie wykonano testów wizualnych w przeglądarce ani migracji i testów na MySQL.

## Proponowana aktualizacja bazy

- `migrations/sql/communication_events_entenda_uat_db.sql`
- `migrations/sql/communication_events_entenda_db.sql`

Skrypt jest do jednokrotnego, ręcznego wykonania po wcześniejszej migracji dyplomacji.
Tworzy dwie nowe tabele i rozszerza `game_notifications` o wskazanie kopii zdarzenia.
Nie wysyła powiadomień o historycznych zdarzeniach. Kopia zdarzenia nie ma klucza obcego do tabeli źródłowej, aby zachować dotychczasową retencję.
