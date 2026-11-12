# Wywiad wojskowy i zniszczone bazy — UAT, 2026-10-24

Wdrożono w ZEUS_UAT / entenda_uat_db. Produkcja ZEUS bez zmian. Schemat: `intelligence_entenda_uat_db.sql`.

## Zniszczenie baz

Przy utracie całego życia baza jest fizycznie usuwana; właściciel otrzymuje powiadomienie systemowe. Garnizon oraz liczba dostępnych baz danego rodzaju są pomniejszane w zasobach państwa. Okręty na morzu pozostają aktywne, nadal są liczone jako zajęte zasoby i podlegają utrzymaniu; mogą strzelać bez bazy macierzystej i wrócić do innego własnego portu. Powrót do właśnie zniszczonego portu jest przerywany na aktualnej pozycji. Obrona przypisana do zniszczonej bazy jest usuwana.

Historia kosztów i lotów pozostaje zachowana: odwołania do usuniętej bazy/obrony stają się NULL. Trwały rodzaj celu zapobiega potraktowaniu kolejnego pocisku lecącego do usuniętej bazy jako ataku na infrastrukturę regionu. Rozliczenia zniszczenia, strat i powiadomień są transakcyjne.

Z osobną, wyraźną zgodą użytkownika usunięto również jedną istniejącą wcześniej bazę UAT z zerowym życiem, rozliczono garnizon i powiadomiono właściciela. Początkowa automatyczna kontrola wymagała potwierdzenia zastosowania reguły wstecz; po uzyskaniu zgody operację wykonano.

## Wywiad

- Nowa nawigacja „Wywiad wojskowy” z ikoną WYWIAD WOJSKOWY; ikony „Obrona państwa” i „Panel wojenny” zmienione odpowiednio na OBRONA PAŃSTWA i WOJNA.
- Agenci poziomów 1–7. Koszty rekrutacji: 17 050 000 / 27 800 000 / 34 200 000 / 45 000 000 / 65 500 000 / 72 300 000 / 105 900 000 ROI. Podstawowe szanse: 15/25/35/45/60/75/90%.
- Mapa świata z regionami i listą wyboru. Misję można skierować do regionu obcego państwa także poza wojną. Agent może wykonywać tylko jedną misję naraz. Po powodzeniu lub porażce jest ponownie dostępny.
- Sześć dostępnych celów: położenie zwykłych baz, obrona przeciwrakietowa, liczba głowic jądrowych, złoża regionu, infrastruktura regionu, silosy atomowe. Misja magazynowa jest niedostępna w interfejsie i odrzucana przez serwer. Poznanie zwykłych baz nie ujawnia automatycznie silosów ani obrony przeciwrakietowej.
- Każda misja trwa 7 dni Entendy i kosztuje 3 mld ROI. Koszt rekrutacji, misji i kontrwywiadu pokrywany jest wyłącznie z bieżącej puli security_services, z uwzględnieniem przesunięć budżetowych. Wydatki są widoczne w saldach sektorów i nie mogą być ponownie przesunięte.
- Kontrwywiad poziomu 1 jest bezpłatny i domyślny. Ochrona 5/10/20/35/50/65/75%; koszty kolejnych poziomów 2–7: 50 mln / 500 mln / 2 mld / 5 mld / 7 mld / 10 mld ROI.
- Zgodnie z odpowiedzią użytkownika ochrona zmniejsza szansę proporcjonalnie. Poziom 7 agenta przy poziomie 7 kontrwywiadu: 90% × 25% = 22,5%. Używany jest poziom ochrony w chwili rozliczania misji. Losowanie ma dokładność 0,01 punktu procentowego.
- Misje zamyka scheduler co 5 sekund, niezależnie od obecności gracza, oraz odczyt ekranu i panelu powiadomień. Zakończenie zapisuje raport i pojedyncze powiadomienie. Kliknięcie powiadomienia otwiera modal; raport jest dostępny także z listy misji. Uprawnienia do raportu sprawdzane są po stronie serwera.
- Rozkazy mają identyfikatory żądań, chroniące przed podwójnym naliczeniem przy ponowieniu transmisji.

## Ochrona danych mapy

API i konfiguracja HTML panelu wojennego udostępniają obce bazy/silosy oraz obronę tylko wtedy, gdy ich identyfikatory zostały ujawnione w udanej własnej misji. Samo podanie odgadniętego identyfikatora nie pozwala zaatakować nieodkrytej bazy. Misja położenia baz nie ujawnia garnizonów.

Ukryte lokalizacje nie są ujawniane przez trasę powrotu obcych okrętów ani przez współrzędne źródła lotów z nieodkrytych baz. Obce okręty pozostają widoczne zgodnie z poprzednią funkcjonalnością; ich pełne plany rejsów i baza macierzysta są ukryte. Przeszłe raporty zachowują dane z chwili misji, a odkryte obiekty na mapie są następnie aktualizowane do ich bieżącego stanu. Obiekty zniszczone znikają z mapy.

## Weryfikacja

- Pełny zestaw 160 testów Python — OK; 19 nowych przypadków dotyczących misji, szans i kosztów, prywatności raportów/mapy, usuwania baz, zachowania floty, historii i wycofania transakcji. Po ostatniej korekcie zgodności starszych rozkazów dodatkowo 5 testów usuwania baz — OK.
- Składnia JavaScript wywiadu, powiadomień i mapy wojennej — OK.
- Odczytowe renderowanie rzeczywistego ekranu wywiadu UAT, stan i polityka ujawniania danych, CSRF, sześć typów misji i siedem cen rekrutacji — OK. Bez testowych rekrutacji lub misji na danych graczy.
- Migracja MySQL i klucze obce sprawdzone; jedna zatwierdzona operacja usunięcia istniejącej bazy wykonana. Gunicorn łagodnie przeładowany; ekran i nowe pliki HTTP 200, usługa aktywna.
- Bez wizualnego testu w przeglądarce — środowisko przeglądarkowe nie jest dostępne.
