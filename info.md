ZEUS jest autorskim systemem worldbuildingowym klasy administracyjno-encyklopedycznej, zaprojektowanym do centralnego zarządzania danymi dotyczącymi fikcyjnego uniwersum Entendy.
System łączy funkcje rozbudowanej bazy wiedzy, panelu administracyjnego, narzędzia symulacyjnego oraz środowiska operacyjnego do modelowania państw, regionów, społeczeństw, gospodarek i relacji geopolitycznych.

ZEUS został zbudowany w architekturze webowej w oparciu o framework Flask oraz relacyjną bazę danych SQL.
Warstwa backendowa odpowiada za logikę biznesową, routing, autoryzację, walidację danych oraz komunikację z modułami symulacyjnymi.
Frontend systemu wykorzystuje renderowanie szablonów Jinja2, rozszerzone o własne komponenty JavaScript oraz responsywny styling CSS dostosowany zarówno do środowisk desktopowych, jak i mobilnych.

System został podzielony na wyspecjalizowane moduły funkcjonalne odpowiadające poszczególnym obszarom świata Entendy, w tym między innymi:

administracji państwami;
zarządzaniu regionami i miastami;
gospodarce i produkcji przemysłowej;
społeczeństwu i demografii;
dyplomacji i organizacjom międzynarodowym;
historii i kulturze;
siłom zbrojnym;
geografii i naturze;
generowaniu zdarzeń globalnych.

Architektura ZEUS oparta jest o modularny system route’ów Flask, oddzielających logikę poszczególnych domen funkcjonalnych.
Każdy moduł posiada własne formularze administracyjne, widoki list, systemy filtrowania oraz mechanizmy walidacji danych.

Istotnym elementem systemu jest warstwa symulacyjna odpowiedzialna za dynamiczne generowanie zdarzeń (Generator Zdarzeń — GZ).
Mechanizm ten umożliwia automatyczne tworzenie wydarzeń geopolitycznych, społecznych, militarnych i naturalnych na podstawie parametrów regionów, państw oraz relacji międzynarodowych.

ZEUS wykorzystuje rozbudowany model relacyjny obejmujący między innymi:

państwa;
regiony;
miasta;
społeczeństwa;
dane gospodarcze;
relacje dyplomatyczne;
organizacje międzynarodowe;
historię zmian;
zdarzenia globalne.

System posiada również mechanizmy:

kontroli dostępu opartej o role;
logowania zmian;
filtrowania wielopoziomowego;
eksportu danych;
dynamicznych endpointów API;
renderowania dokumentacji Markdown;
walidacji integralności danych;
responsywnego interfejsu administracyjnego.

Początek tworzenia uniwersum Entendy: data nieznana
Początek tworzenia systemu ZEUS: listopad 2025

--- ROLE I UPRAWNIENIA ---

Rola: Wszechmocny
Uprawnienia:

wyświetlanie danych;
dodawanie rekordów;
edytowanie rekordów;
usuwanie rekordów;
zarządzanie relacjami systemowymi;
dostęp do funkcji administracyjnych.

Rola: Tworzyciel
Uprawnienia:

wyświetlanie danych;
dodawanie rekordów;
częściowa edycja wybranych modułów.

Rola: Obserwator
Uprawnienia:

wyświetlanie danych w trybie tylko do odczytu.

--- GLOBALNE PROCESY ROCZNE ---

27 GRUDNIA
Roczna regeneracja przyrostu naturalnego (run_annual_population_growth_regeneration)
System przelicza dla wszystkich regionów współczynniki rocznego procentu zmiany populacji.

28 GRUDNIA 
Roczna regeneracja infrastruktury regionów (apply_yearly_regeneration_if_needed)
System odnawia stan infrastruktury regionów (drogi, kolej, energia, mieszkalnictwo, porty).

29 GRUDNIA
Roczna regeneracja współczynnika wzrostu PKB (run_annual_growth_regeneration)
System przelicza wskaźnik wzrostu gospodarczego każdego państwa.

30 GRUDNIA
Roczne przeliczenie PKB państw (run_annual_pkb_regeneration)
System aktualizuje nominalne PKB państw na podstawie wskaźnika wzrostu.

31 GRUDNIA
Roczne przeliczenie populacji państw (apply_global_population_regeneration)
System aktualizuje liczbę ludności wszystkich państw według modelu demograficznego.

1 STYCZNIA
Roczny snapshot PKB per capita (run_annual_pkbpc_snapshot)
System zapisuje historyczny stan wskaźnika PKB per capita dla każdego państwa.
