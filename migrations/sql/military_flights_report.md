# Pozycje baz i loty bojowe — UAT, 24.10.2026

## Lokalizacje i życie baz

Bazy mają trwałe współrzędne map_x/map_y oraz zdrowie 0–100, domyślnie 100. W panelu obrony przy każdej bazie można wskazać lub zmienić lokalizację. Kliknięcie jest sprawdzane na serwerze względem geometrii przypisanego regionu, z obsługą wysp i otworów w poligonach. Dla regionu zamorskiego tryb wskazywania pokazuje jego geometrię i kadruje mapę. Nowe i dotychczasowe bazy bez pozycji pozostają w panelu i czekają na wskazanie miejsca.

Ikona bazy ma stale widoczny pasek życia. Tooltip pokazuje garnizon i zdrowie. W panelu wojennym pokazane są również rozmieszczone bazy. Nie zdefiniowano obrażeń zadawanych bazom, dlatego ataki miast nie zmieniają ich zdrowia.

## Zapisana skala

W game_map_calibration zapisano odcinek Saint Adams (miasto 1, Ozilandia) — Pinst (852, Ozilandia) jako 100 km. Współrzędne odniesienia: (954.7510623012616, -1801.62366708549) oraz (952.4987942837062, -1776.1536230000308). Skala: 3.910919870403471 km na jednostkę mapy. Współrzędne i dystanse używają DOUBLE, aby uniknąć utraty precyzji. Każdy lot zapisuje dystans, punkty startu/celu i terminy; nie tworzy się zbędnej tabeli wszystkich par miejsc na świecie. Mapa ma metryczną podziałkę, a formularz ataku pokazuje odległość i czas lotu.

## Rakiety i miasta

Zgodnie z potwierdzeniem użytkownika podane trzy przedziały przyjęto jako rakiety krótkiego, średniego i dalekiego zasięgu: odpowiednio 0–500 km przy 100 km/h, 500–2000 km przy 200 km/h i 2000–10000 km przy 500 km/h. Czas jest liczony w godzinach Entendy, z istniejącym przyspieszeniem 12:1 (godzina Entendy = 5 minut rzeczywistych).

Kliknięcie miasta w panelu wojennym otwiera wariant ataku tego miasta z powietrza, terytorium lub okrętu. Należy wybrać własną zlokalizowaną bazę z wymaganym sprzętem: wyrzutnią, myśliwcem albo okrętem. Zachowano kontrolę stanu wojny, właściciela celu i nadmorskiego regionu dla ataku morskiego. Serwer sprawdza też zasięg. Jedna salwa może obejmować do 10000 rakiet; marker reprezentuje salwę i pokazuje jej liczebność.

Rakiety są odejmowane przy zatwierdzeniu wystrzału w tej samej transakcji, która zapisuje rozkaz i lot. Przy trafieniu miasta każda rakieta losuje 0–100 ofiar. Suma jest ograniczona liczbą mieszkańców, a ludność miasta oraz istniejąca suma ludności państwa są zmniejszane. Zmiana miasta trafia do miasto_state_history ze źródłem MILITARY_STRIKE. Trafienie i jego skutki są atomowe i nie powielają się po ponowieniu zadania. Dotychczasowe rozkazy fazy 1 nie uruchamiają lotów ani ofiar wstecznie. Ataki na infrastrukturę regionalną nadal nie zadają niezdefiniowanych obrażeń; przemarsze nie zmieniają kontroli regionów.

## Animacje i myśliwiec

Loty są odtwarzane z czasu i trasy zapisanej na serwerze, także po odświeżeniu i ponownym wejściu. Czerwony pulsujący punkt leci po prostej osi salwy. Myśliwiec ma dedykowaną ikonę MYŚLIWIEC.svg i potwierdzoną prędkość 900 km/h. Lecąc z bazy, dociera do celu szybciej od rakiety, oczekuje na bombardowanie salwą i wraca do tej samej bazy. Trasa i ikona obracają się odpowiednio do kierunku powrotu. Dostępny samolot jest rezerwowany na czas całej misji; nie można go ponownie wysłać, wycofać ręcznie ani przenieść jego bazy przed powrotem. Jeśli automatyczne ograniczenie budżetu wycofa przydział samolotu w locie, pozostaje on liczony w służbie i niedostępny dla innej bazy do czasu powrotu.

Zadanie serwera rozlicza loty co 5 sekund; panel odświeża stan również co 5 sekund i interpoluje ruch płynnie między odczytami. Przeglądarka nie nalicza ofiar ani nie decyduje o stanie zasobów. Lista lotów pokazuje dystanse, terminy i ofiary. Podgląd lotów ogranicza się do własnych oraz nadlatujących na własne państwo.

## Migracja i sprawdzenie

Wykonano military_flights_entenda_uat_db.sql na entenda_uat_db, zweryfikowano klucze obce, skalę i zgodność historii ludności. Początkowe zaokrąglanie typu FLOAT wykryto przy kontroli odcinka referencyjnego i skorygowano do DOUBLE przed uruchomieniem wersji. Produkcji nie zmieniano.

103 testy Python zaliczone. Nowe przypadki obejmują geometrię lokalizacji, odcinek 100 km, zasięgi i czasy trzech typów rakiet, zużycie zapasu, odrzucanie nieprawidłowej bazy i celu, ofiary 0–100 z ograniczeniem populacji, brak powielania, rollback, przylot i powrót, rezerwację samolotu, prywatność lotów i zadanie w tle. Osobne testy JavaScript sprawdzają pozycję rakiety, prędkość samolotu, oczekiwanie/powrót, przelicznik czasu i odtworzenie po odświeżeniu. Sprawdzono renderowanie paneli i API na rzeczywistej bazie UAT w lokalnej sesji testowej, z wyłączonymi skutkami i schedulerami na czas sprawdzenia, bez wystrzeliwania rakiet. Nie wykonano wizualnego testu przeglądarkowego.

Aktualizacja prędkości: nowe loty rakiet krótkiego zasięgu korzystają z 1200 km/h, średniego z 1000 km/h, dalekiego z 900 km/h (godziny Entendy). Zasięgi pozostają zgodne z wcześniejszymi ustawieniami. Terminy rozpoczętych misji pozostają zapisane według momentu wystrzału. Myśliwiec nadal leci 900 km/h; szybsza rakieta nie rozpoczyna jego powrotu przed dotarciem samolotu do celu. Zaktualizowano testy trzech czasów lotu i test animacji szybszej rakiety. 11 testów przelotów Python i testy osi JavaScript zaliczone. Bez migracji schematu; UAT przeładowano.

Kolejna aktualizacja: prędkości nowych rakiet wynoszą odpowiednio 1500 km/h (krótki zasięg), 1200 km/h (średni) i 1000 km/h (daleki), w godzinach Entendy. Zaktualizowano oczekiwane czasy trzech typów w testach; 11 testów przelotów zaliczonych. UAT przeładowano. Zapisane terminy misji już rozpoczętych pozostają bez zmian.
