# Flota, silosy atomowe i raporty trafień — UAT, 2026-10-24

Wdrożono wyłącznie w ZEUS_UAT. Migracja `military_navy_nuclear_entenda_uat_db.sql` dodaje nazwę i stan operacyjny bazy, rodzaj `nuclear`, trwałe rejsy oraz powiązanie pocisków z okrętem i znacznik głowicy atomowej. Istniejące bazy, rozkazy i loty zachowano. Produkcja ZEUS bez zmian.

## Zachowanie

- Bombardowanie pokazuje tylko myśliwiec. Trafienie następuje po dotarciu samolotu do celu; po powrocie znika samolot i oś lotu. Rakieta i jej oś znikają przy trafieniu, bez oczekiwania na kolejne odpytywanie serwera.
- Rozliczenie trafienia atomowo zapisuje straty i powiadomienia obu graczy. Powtórne wykonanie zadania nie powiela strat ani powiadomień. Zwykłe ataki w miasta nadal powodują 0–100 ofiar na rakietę, ograniczone populacją. Infrastruktura nie jest uszkadzana.
- Okręty wojenne i podwodne płyną 100 km/h Entendy. Wysyłanie: menu karty bazy morskiej, następnie punkt na mapie. Kliknięcie okrętu pozwala wybrać bazę powrotu lub ostrzał celu na panelu wojennym. Rejs i pozycja są odtwarzane po odświeżeniu. Okręty w rejsie są zarezerwowane; powrót do innej bazy rezerwuje jej pojemność i przenosi jednostkę dokładnie raz. Rakiety startują z bieżącej pozycji okrętu; cele nie muszą być nadmorskie.
- Budowa silosu: 25 mld ROI, wyłącznie z bieżącego budżetu sił zbrojnych. Poziomy 1–7: 100/200/500/1000/2000/3000/5000 głowic. Rozbudowa kosztuje dwa razy tyle co odpowiadający poziom zwykłej bazy.
- Utrzymanie silosu: 500 mln ROI za półrocze (1 mld rocznie). Utrzymanie całego krajowego zapasu głowic: 100 mln ROI za głowicę na półrocze, bez podwójnego naliczania głowic umieszczonych w silosach. Niewystarczający budżet wyłącza nieopłacone silosy z powiadomieniem; środki w kolejnym rozliczeniu przywracają ich działanie. Pozostałe koszty podlegają proporcjonalnej redukcji zasobów zgodnie z dotychczasową polityką utrzymania wojska.
- Ataki atomowe: z silosu, myśliwca lub wysłanego okrętu. Wymagają załadowanych głowic we własnym sprawnym silosie. Wystrzał odejmuje głowicę i rakietę; trafienie nie powoduje ofiar ani zniszczeń. Samolot pozostaje zajęty do powrotu.
- Bazy mają osobne karty, zmianę nazwy i menu działań w prawym górnym rogu. Kliknięcie własnej bazy na mapie obrony przewija do jej karty. Z panelu wojennego dostępny jest odnośnik do odpowiedniej karty.

## Weryfikacja

- Pełny zestaw: 112 testów Python — OK.
- Po ostatniej korekcie komunikatu i interakcji: 29 testów wojskowych — OK.
- Testy JavaScript matematyki lotów, w tym brak rakiety przy bombardowaniu — OK; składnia głównego skryptu — OK.
- Odczytowy test uwierzytelnionego renderowania obrony, panelu wojennego i stanu mapy na MySQL UAT — HTTP 200. Rozliczanie ataków, rejsów i utrzymania zostało wyłączone w tym teście.
- Migracja MySQL sprawdzona wraz z kluczami obcymi i zachowaniem liczby rekordów. Gunicorn UAT łagodnie przeładowany; usługa aktywna, nowe pliki JS/CSS dostępne przez HTTP 200.
- Bez testowych ataków lub zmian rozmieszczenia na danych graczy. Bez wizualnego testu w przeglądarce (brak dostępnego środowiska przeglądarki).
