# Wspólny motyw gry i menu boczne — UAT, 25.10.2026

Wszystkie moduły gracza otrzymały wspólną granatową oprawę na wzór ekranu Obrona państwa. Zachowano układy i funkcje modułów, a ujednolicono tło, paski gracza i statystyk, karty, formularze, tabele, mapy oraz okna modalne. Kolory oznaczające dane (relacje dyplomatyczne, konflikty, progi infrastruktury i wykresy) nadal pełnią swoje funkcje.

Menu ekranów przeniesiono na lewą stronę, do pionowego panelu. Wskazuje bieżący moduł i przewija się niezależnie od zawartości. Przy szerokości do 900 px menu jest rozwijane; Escape je zamyka i przywraca fokus przyciskowi. Dodano odnośnik klawiaturowy „Przejdź do treści”. Układy z mapami dostosowują liczbę kolumn do miejsca pozostającego obok menu.

Wspólne style: `static/css/game_navy.css`. Układ: `templates/game/game_base_layout.html`. Granatową oprawę dodano też do wyboru państwa. Zmiana nie wymaga migracji bazy ani zmian stanu gry.

Weryfikacja: 174 testy unittest; renderowanie 13 ekranów gracza i wyboru państwa na rzeczywistej bazie UAT; sprawdzenie kolejności arkuszy, układu menu i jednoznaczności kontrolek; test JavaScript otwierania i zamykania menu, aria-expanded i klawisza Escape; składnia skryptów wojskowych i handlowych. Nie wykonano wizualnego testu w przeglądarce.
