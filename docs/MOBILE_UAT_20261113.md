# ZEUS GAME UAT — przegląd mobilny, 13 listopada 2026

Punkt odniesienia: `1b8dc4e`. Zmiany w lokalnym kodzie UAT; nie wykonywano restartu ani wdrożenia usługi i nie zmieniano bazy działającej gry.

## Ustalenia i poprawki

Nowe ekrany zachowują granat #1E3A5F, jasne tło #F0F4FA, białe karty, ikony, obramowania oraz dotychczasowe kolory poszczególnych modułów. Osobny arkusz `static/css/game_mobile.css`, ładowany po motywach, zmienia głównie geometrię poniżej 900 px.

| Obszar | Problem | Poprawka |
|---|---|---|
| Nagłówek | Dane państwa zajmowały znaczną część pierwszego ekranu telefonu. | Wskaźniki rozwijane przyciskiem z nazwą państwa; bez JavaScript pozostają widoczne. Konto i narzędzia w jednym wierszu. |
| Nawigacja | Mały przycisk menu, długa rozwijana lista. | Minimum 44 px, lista ograniczona wysokością okna i przewijana niezależnie, obsługa Escape zachowana. |
| Panel państwa i Świat | Małe filtry i reset; duże minimalne wysokości map. | Większe pola dotykowe i mapy 280–520 px zależnie od wysokości ekranu, zawijanie pasków narzędzi. |
| Infrastruktura | Katalogi ściskające wiele obiektów w wierszu, małe przyciski i selektory. | Responsywna siatka katalogów, przyciski i selektory ≥44 px, detale pod mapą. |
| Badania | Węzły zmniejszane do 22 px na telefonie. | Węzły 44 px i przeliczanie odstępów, sieć przewijana poziomo w swoim panelu. Informacja dotykowa i dostępna z klawiatury strefa przewijania. |
| Formularze i okna | Drobne pola, możliwość obcięcia treści w małym oknie. | Pola 16 px, szerokość ograniczona do panelu; okna ograniczone do widocznej wysokości i przewijane. |
| Środki modułu i tabele | Długie kwoty i szerokie dane. | Zawijanie kart środków i lokalne przewijanie tabel zamiast rozciągania strony. |
| Ruch | Animowany pasek wiadomości. | Zatrzymanie animacji przy systemowym ograniczeniu ruchu. |

## Weryfikacja

Test `tests/browser/mobile_layout_check.py` przeszedł dla **9 ekranów × 5 rozmiarów = 45 kombinacji**:

- Panel państwa, Badania i rozwój, Infrastruktura i energetyka, Świat, Dyplomacja, Handel, Forum, Środowisko, Obrona państwa.
- Rozmiary: 320×740, 390×844, 768×1024, 900×700 i 1440×1000.
- W każdym przypadku szerokość dokumentu nie przekraczała szerokości okna.
- Na mobilnych szerokościach sprawdzono rozwinięcie/zamknięcie menu przez Escape, rozwijanie wskaźników, wysokości głównych map, węzły badań ≥44 px i otwarcie/zamknięcie okna badań bez wyjścia poza szerokość okna.
- Ręcznie obejrzano zrzuty mobilne infrastruktury i badań. Zrzuty: [Badania 390 px](mobile-20261113/badania-390.png), [Infrastruktura 390 px](mobile-20261113/infrastruktura-390.png).
- `git diff --check`, kompilacja skryptów Python oraz 4 istniejące testy punktacji PAGA2: OK.

Test korzysta z izolowanej bazy SQLite. Dla panelu państwa i Świata renderuje rzeczywiste szablony z podstawionymi danymi; pozostałe ekrany korzystają z tras testowej aplikacji. Geometrie map są zastąpione pustymi kolekcjami GeoJSON, więc sprawdzono układ map i kontrolek, ale nie rozmieszczenie rzeczywistych obiektów świata ani działanie produkcyjnych danych. Test desktopu potwierdza brak poziomego przepełnienia, nie zgodność każdego piksela.

Finanse, rejestracja, demografia, społeczeństwo, poczta i pozostałe moduły przejrzano w kodzie wspólnych stylów/szablonów; nie objęto ich osobną kontrolą przeglądarkową. Nie wykonano testu na fizycznym telefonie ani Safari/iOS. Nie zmieniono reguł gry i mechanizmu PAGA2.

## PAGA2

Analiza i pełne schematy: [PAGA2_ALGORYTMY.md](PAGA2_ALGORYTMY.md). Wersja do otwarcia offline, ze schematami SVG i drukiem do PDF: [PAGA2_ALGORYTMY.html](PAGA2_ALGORYTMY.html).
