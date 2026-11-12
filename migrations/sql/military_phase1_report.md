# Infrastruktura, obrona państwa i panel wojenny — faza 1 (UAT)

## Infrastruktura

Po najechaniu na znacznik prac budowlanych tooltip pokazuje oddzielny wiersz dla każdej rozbudowy: ikonę prac, ikonę rodzaju infrastruktury i „Ukończono: X%”. Usunięto legendę kolorów. Wybór regionu znajduje się w prawym panelu ponad nazwą regionu.

## Ekrany i uprawnienia

„Obrona państwa” jest zawsze dostępna w nawigacji gracza. „Panel wojenny” pokazuje się przy aktywnej wojnie, według istniejącego słownika stanu stosunków. Bez wojny wejście do panelu jest odrzucane. Mapy korzystają z regionów i miast; regiony mają nazwy i podświetlenie. Obrona kadruje obszar metropolitalny, zgodnie z wcześniejszą zmianą, i pokazuje sąsiadów jako państwa. Terytoria zamorskie pozostają dostępne w wyborze regionu. Panel wojenny pokazuje świat z regionami i miastami.

## Bazy, garnizony i budżet

Gracz rozmieszcza dostępne bazy lądowe, powietrzne i morskie (morskie tylko przy wybrzeżu). Każda zaczyna na poziomie 1; są łącznie 7 poziomów. Pojemności i ceny zgodne z załącznikiem, z potwierdzoną poprawką: baza powietrzna poziomu 1 mieści 25 myśliwców. Rozbudowa jest natychmiastowa; nie podano czasu budowy baz. Płatność jest wyłącznie z kategorii armed_forces bieżącego półrocznego budżetu. Brakujące środki nie są pobierane z rezerwy.

Garnizony kontrolują zarówno pojemność, jak i zasoby już rozmieszczone w pozostałych bazach. Żołnierze baz lądowych, powietrznych i morskich korzystają odpowiednio z puli wojsk lądowych, powietrznych i morskich. Sprzęt korzysta ze wspólnych narodowych pul. Wycofanie całego lub części garnizonu zwalnia jego zasoby. Siły zbrojne pokazują liczby „W służbie czynnej” oraz kwotę budżetu zamiast procenta PKB.

Utrzymanie obejmuje wyłącznie zasoby w garnizonach: żołnierz 4000, czołg/wyrzutnia/wóz 8000, myśliwiec 25000, okręt wojenny 600000, podwodny 650000 ROI na półrocze. Aktualny koszt jest rozliczany jedną pozycją na państwo i półrocze, korygowaną przy zmianie garnizonu. Budżet dostępny na rozbudowę uwzględnia utrzymanie; nie jest ono pobierane podwójnie. Zadanie co 30 sekund rozlicza bieżący okres także bez obecności gracza. Przy braku zatwierdzonego budżetu dostępna pula wynosi zero.

Jeśli budżet po opłaceniu rozbudów nie pokrywa utrzymania, system skaluje ilości wszystkich garnizonów tym samym współczynnikiem; jednostki całkowite zaokrągla w dół, a ewentualne reszty rozdziela według największych części ułamkowych w granicach budżetu. Tworzy powiadomienie o niedoborze i proporcjonalnym wycofaniu. Blokada państwa oraz garnizonów zabezpiecza przed podwójnym wydaniem zasobów i pieniędzy. Wycofanie i powiadomienie są jedną transakcją.

## Rozkazy bez skutków walki

Cztery czerwone przyciski z ikonami: bombardowanie, rakiety z terytorium, atak z okrętu i armia lądowa. Modal pozwala wybrać rakiety i cel infrastrukturalny albo żołnierzy/czołgi/wozy. Dodano trzy osobne zapasy rakiet (krótki, średni, daleki zasięg), domyślnie 0, edytowane na dodawaniu/edycji wojska WIKI i widoczne w podglądzie.

Zgodnie z decyzją użytkownika faza 1 wyłącznie zapisuje rozkazy. Nie zużywa rakiet ani sprzętu, nie wywołuje strat, uszkodzeń, przemarszu ani przejęcia regionu. Kontrole: stan wojny, właściwy przeciwnik, własne zasoby, przybrzeżny cel i posiadanie okrętu dla ataku morskiego, dodatniej długości wspólna granica dla wejścia lądowego. Sąsiedztwo obliczane jest na serwerze z geometrii, z obsługą granic podzielonych na odcinki; samo zetknięcie rogami nie wystarcza. W tej fazie nie określono kilometrów zasięgu typów rakiet i nie wprowadzono dodatkowych limitów odległości.

## Migracja i walidacja

Wykonano `military_phase1_entenda_uat_db.sql` w entenda_uat_db: tabele baz, wydatków, utrzymania i rozkazów; trzy kolumny rakiet; ogólne powiadomienia systemowe. Produkcji nie zmieniono. Przeładowano Gunicorna UAT.

92 testy zaliczone, w tym limity, pojemności, koszty, poziom 7, ochrona budżetu utrzymania, proporcjonalne wycofanie, jedno powiadomienie, zmiana półrocza, rollback, CSRF, własność, stan wojny, brak efektów rozkazu i granice. Poprawna składnia JavaScript, Python i Jinja. Sprawdzono renderowanie czterech ekranów na rzeczywistej bazie UAT w lokalnej sesji testowej (HTTP 200), bez rozmieszczania baz lub zmiany zasobów; procesy schedulerów były wyłączone w tym sprawdzeniu. Nie wykonano wizualnego testu przeglądarkowego.
