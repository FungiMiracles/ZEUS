__Wydanie W3.MAR.26 (30.03.2026)__

Zmiany:

Z1.W3.MAR.26 [Państwa] Na formularzu państwa wprowadzono menu rozwijalne (hamburger), umożliwiające dostęp do kluczowych akcji i modułów systemu, takich jak: powrót do wyników wyszukiwania, edycja i usuwanie państwa, kalkulator demograficzny, dane ludnościowe, sojusze i bloki, dane gospodarcze oraz siły zbrojne.

Z2.W3.MAR.26 [Państwa] Przebudowano układ formularza państwa – dotychczasowe menu boczne zostało zastąpione systemem kafelków z granatowym obramowaniem, spójnym wizualnie z formularzem regionu.

Z3.W3.MAR.26 [Państwa] Dodano wskaźnik poziomu rozwoju infrastrukturalnego państwa, wyliczany jako średnia wartości infrastruktury we wszystkich regionach. Wskaźnik prezentowany jest pod PKB per capita i oznaczony kolorystycznie w zależności od poziomu (od czerwonego do ciemnozielonego).

Z4.W3.MAR.26 [Generator Zdarzeń] Rozszerzono model danych regionów o parametry regeneracji infrastruktury (drogi, kolej, energia, mieszkalnictwo, porty). Wartości te są widoczne na formularzu regionu jako dane systemowe.

Z5.W3.MAR.26 [Generator Zdarzeń] Dodano mechanizm inicjalizacji parametrów regeneracji infrastruktury na podstawie danych ekonomicznych (m.in. PKB), umożliwiający automatyczne wypełnienie nowych pól.

Z6.W3.MAR.26 [Generator Zdarzeń] Wprowadzono system konsekwencji zdarzeń oraz automatyczną regenerację infrastruktury regionalnej. Zdarzenia wpływają na stan infrastruktury oraz zmniejszają populację pozamiejską o liczbę ofiar.

Z7.W3.MAR.26 [Generator Zdarzeń] Wprowadzono ograniczenie wykluczające miasta techniczne z procesu generowania zdarzeń.

Z8.W3.MAR.26 [Generator Zdarzeń] Rozszerzono bazę szablonów opisów zdarzeń o nowe scenariusze dla katastrof kolejowych, zdarzeń drogowych, powodzi oraz fal mrozu.

Z9.W3.MAR.26 [Generator Zdarzeń] Dodano nowe typy zdarzeń: pożar lasu, pożar budynku, przerwa w dostawie prądu oraz katastrofa lotnicza wraz z pełnym wsparciem szablonów i logiki generowania.

Z10.W3.MAR.26 [Ludność i populacja] Na ekranie danych demograficznych państw dodano prezentację flagi państwa obok jego nazwy.

Z11.W3.MAR.26 [Organizacje międzynarodowe] Wprowadzono nowy moduł organizacji międzynarodowych, obejmujący słownik organizacji oraz relacje członkostwa państw.

Z12.W3.MAR.26 [Organizacje międzynarodowe] Dodano modele danych oraz backend obsługujący organizacje międzynarodowe i ich relacje z państwami.

Z13.W3.MAR.26 [Organizacje międzynarodowe] Udostępniono ekran organizacji międzynarodowych z możliwością przeglądania organizacji, ich członków oraz wyszukiwania powiązań państw z organizacjami.

Z14.W3.MAR.26 [Organizacje międzynarodowe] Dodano operacje zarządzania organizacjami: tworzenie, usuwanie, zawieszanie organizacji oraz zarządzanie członkostwem państw.

Z15.W3.MAR.26 [Strona Główna] Zaktualizowano wygląd paska wiadomości – dodano zaokrąglenia oraz obramowanie w kolorze jasnoszarym.

Z17.W3.MAR.26 [Religia] Wprowadzono słownik typów religii oraz powiązanie go z tabelą religii. Backend oraz formularze zostały dostosowane do obsługi nowej struktury.

Z18.W3.MAR.26 [Język] Wprowadzono słownik rodzin językowych oraz powiązanie z tabelą języków. Zaktualizowano modele, backend oraz formularze.

Z19.W3.MAR.26 [Religia] Ujednolicono wygląd przycisków w module religijnym (m.in. „usuń” i „szukaj”).

Poprawki:

P1.W3.MAR.26 [System] Naprawiono błędy oznaczone numerami 036, 038, 039, 040 oraz 041 zgodnie z listą błędów.

__Wydanie W2.MAR.26 (13.03.2026)__

Zmiany:

Z1.W2.MAR.26 [Generator Zdarzeń] Usunięcie przycisku „Generuj zdarzenia” z ekranu Generatora Zdarzeń.

Z2.W2.MAR.26 [Generator Zdarzeń] Implementacja nowych typów wydarzeń w Generatorze Zdarzeń: powódź, lawina, wybuch wulkanu, mróz oraz fala upałów.

Z3.W2.MAR.26 [Generator Zdarzeń] Wprowadzenie mechanizmu generowania opisów wydarzeń na podstawie szablonów zapisanych w bazie danych. Generator zdarzeń zapisuje w kolumnie „OPIS” treść zdarzenia wygenerowaną z szablonu oraz identyfikator wykorzystanego szablonu.

Z4.W2.MAR.26 [Generator Zdarzeń] Implementacja systemu szablonów opisów dla istniejących wydarzeń w Generatorze Zdarzeń.

Z5.W2.MAR.26 [Strona Główna] Dodanie paska „Wiadomości ze świata”, wyświetlającego przesuwające się z prawej do lewej informacje o ostatnich wydarzeniach. Pasek prezentuje 10 najnowszych zdarzeń w formacie: [DATA] [OPIS ZDARZENIA].

Z6.W2.MAR.26 [Regiony] Na formularzu regionu dodano listę wydarzeń, które miały miejsce w danym regionie. Domyślnie wyświetlane są 3 najnowsze wydarzenia z możliwością rozwinięcia listy.

Z7.W2.MAR.26 [Regiony] Na formularzu regionu obok nazwy państwa wyświetlana jest flaga państwa, do którego należy region.

Z8.W2.MAR.26 [Regiony] Na liście miast w formularzu regionu dodano przycisk „Przejdź”, umożliwiający bezpośrednie przejście do formularza danego miasta.

Z9.W2.MAR.26 [Regiony] Formularz regionu został dostosowany do poprawnego działania na urządzeniach mobilnych.

Z10.W2.MAR.26 [Miasta] Na formularzu miasta obok nazwy państwa wyświetlana jest flaga państwa, do którego należy dane miasto.

Z11.W2.MAR.26 [Państwa] Na liście wyników wyszukiwania państw dodano wyświetlanie flag państw obok nazwy każdego wyniku.

Z12.W2.MAR.26 [Państwa] Dodanie zaawansowanego filtra wyszukiwania państw. Możliwe jest filtrowanie po: kontynencie, ustroju politycznym, populacji, powierzchni, języku urzędowym, religii dominującej, PKB, PKB per capita oraz statusie suwerenności.

Z13.W2.MAR.26 [Strona Główna] Aktualizacja opisu systemu ZEUS na stronie głównej. System został opisany jako system administracyjny, symulacyjny i encyklopedia świata Entendy.

Z14.W2.MAR.26 [Generator Zdarzeń] Strona Generatora Zdarzeń została dostosowana do widoku mobilnego.

Z15.W2.MAR.26 [Państwa] Wprowadzenie słownika kontynentów (dict_kontynent). Do tabeli panstwa dodano kolumnę kontynent_id, a formularze oraz backend zostały dostosowane do korzystania z nowego słownika.

Z16.W2.MAR.26 [Państwa] Wprowadzenie słownika ustrojów politycznych (dict_panstwo_ustroj). Do tabeli panstwa dodano kolumnę ustroj_id, a modele danych oraz formularze zostały dostosowane do nowej struktury.

Z17.W2.MAR.26 [Miasta] Wprowadzenie słownika typów miast (dict_miasto_typ). Do tabeli miasta dodano kolumnę miasto_typ_id, a backend i formularze miast zostały dostosowane do korzystania ze słownika.

Z18.W2.MAR.26 [Stosunki międzynarodowe] Wprowadzenie słownika relacji dyplomatycznych (dict_stosunki_relacja). Do tabeli stosunki dodano kolumnę relacja_id, a backend został dostosowany do obsługi relacji opartych na słowniku.

Z19.W2.MAR.26 [Stosunki międzynarodowe] Wprowadzenie słownika stanów dyplomatycznych (dict_stosunki_stan). Do tabeli stosunki dodano kolumnę stan_id, a modele danych oraz backend zostały dostosowane do nowej struktury.

Poprawki:

P1.W2.MAR.26 [Generator Zdarzeń] Poprawiono sortowanie listy wydarzeń w Generatorze Zdarzeń – rekordy są wyświetlane malejąco według identyfikatora zdarzenia.

Parametry:

PAR1.W2.MAR.26 [Generator Zdarzeń] Zmniejszono zakres liczby ofiar dla wielu typów zdarzeń generowanych przez Generator Zdarzeń.

__Wydanie W1.MAR.26 (07.03.2026)__

Zmiany:

Z1-Z3.W1.MAR.26 [Generator Zdarzeń]
Utworzenie nowych tabel potrzebnych do generowania zdarzeń w systemie ZEUS.

Z4-Z6.W1.MAR.26 [Generator Zdarzeń]
Powstanie ekranu Generatora Zdarzeń oraz odnoszącego się do niego przycisku obok daty w Entendzie.

Z7.W1.MAR.26 [Generator Zdarzeń]
Cofnięcie czasu w Entendzie do roku 2993 CE.

Z8.W1.MAR.26 [Generator Zdarzeń]
Implementacja trzech zdarzeń do Generatora Zdarzeń: trzęsienia ziemi, katastrofy w ruchu lądowym i katastrofy kolejowej.

Z9.W1.MAR.26 [Regiony]
Usunięcie nieużywanych kolumn w tabeli regiony po zmianach w W3.LUT.26.

Z10-Z11.W1.MAR.26 [Regiony, Państwa]
Dodanie informacji o ilości wyświetlanych wyników wyszukiwania.

Z12.W1.MAR.26 [Regiony, Państwa]
Dodanie paginacji dla wyników wyszukiwania państw i regionów.

Z13.W1.MAR.26 [Regiony]
Dodanie zaawansowanych filtrów wyszukiwania regionów.

Z15.W1.MAR.26 [Regiony]
Ograniczenie domyślnego wyświetlania listy miast regionu do 5. Dodany przycisk umożliwiający rozwinięcie listy.

Z16.W1.MAR.26 [Regiony]
Na formularzu regionu zostały dodane informacje o ilości miast w regionie oraz procencie urbanizacji regionu.

Poprawki:

P1.W1.MAR.26 [Dane Gospodarcze]
Poprawione wyświetlanie procentu wzrostu PKB.

P2.W1.MAR.26 [Filtry wyszukiwań]
Uspójniono wygląd filtrów wyszukiwań miast i regionów.

P3.W1.MAR.26 [Regiony]
Naciśnięcie przycisku "Wróć do wyszukiwania" nie powoduje usunięcia kryteriów wyszukiwania.

P4.W1.MAR.26 [Miasta]
Naciśnięcie przycisku "Wróć do wyszukiwania" nie powoduje usunięcia kryteriów wyszukiwania.

__Wydanie W3.LUT.26 (14.02.2026)__

Zmiany:

Z1-Z4.W3.LUT.26 [Regiony]
Zostały wprowadzone słowniki dla regionów.

__Wydanie W2.LUT.26 (08.02.2026)__

Zmiany:

Z1.W2.LUT.26 [Regiony]
Dodana została możliwość filtrowania wyników wyszukiwania regionów.

Z2.W2.LUT.26 [Moduł kulturowy]
Wszystkie ekrany sekcji religijnej zostały dostosowane do widoku mobilnego.

Z3.W2.LUT.26 [Moduł kulturowy]
Z wyników wyszukiwania religii zostały usunięte kolumny "państwo" oraz "kontynent", a zamiast tego została dodana kolumne "religia nadrzędna".

Z4.W2.LUT.26 [Regiony]
Powstały nowe kolumny w bazie danych dla tabeli z regionami.

Z5.W2.LUT.26 [Regiony]
Formularz regionu wyświetla nowe dane o regionie.

Z6.W2.LUT.26 [Regiony]
Formularz edycji regionu pozwala na edytowanie nowych danych o regionie.

Z7.W2.LUT.26 [Regiony]
Formularz dodawania regionu pozwala na dodanie regionu z nowymi danymi.

Z8.W2.LUT.26 [Moduł kulturowy]
Został dodany dynamiczny filtr do wyszukiwania religii per kontynent i państwo.

Z9.W2.LUT.26 [Miasto]
Została wdrożona reguła R7: "Każde państwo ma tylko jedną stolicę państwa."

Z10.W2.LUT.26 [Miasto]
Została wdrożona reguła R8: "Każdy region ma tylko jedną stolicę regionu."

Z11.W2.LUT.26 [Państwo]
Została wdrożona reguła R11: "Każde państwo powinno mieć status: "czy-suwerenny"="TAK/NIE".

Poprawki błędów:

P1.W2.LUT.26 [Moduł kulturowy]	
Krawędzie na poszczególnych wynikach wyszukiwania zostaną zaokrąglone.

P2.W2.LUT.26 [Moduł historyczny]
Formularz edycji i formularz dodawania wyświetlają tylko regiony podlegające pod wybrane państwo i tylko miasta podlegające pod wybrany region.

P3.W2.LUT.26 [Moduł historyczny]
Zostały ujednolicone hovery na na wszystkich przyciskach w module historycznym - brak podkreślenia przycisku, brak zmiany koloru tekstu na przycisku.

P4.W2.LUT.26 [Moduł kulturowy]	
Zostały usunięte podkreślenia przycisków w sekcji religijnej modułu kulturowego na wszystkich ekranach.

P5.W2.LUT.26 [Regiony]	
Zostały zwężony pasek powiadomienia w sekcji regionów.

P6.W2.LUT.26 [Moduł kulturowy]	
Zostały nadane walidacje roli na funkcjonalnościach edycji i dodawania religii w sekcji religijnej w module kulturowym.

P7.W2.LUT.26 [Moduł gospodarczy]	
Został naprawiony widok listy w wynikach wyszukiwania danych gospodarczych państw w widoku mobilnym.

P8.W2.LUT.26 [Moduł dyplomatyczny]	
Został naprawiony formularz edycji stosunków międzynarodowych tak, by formularz zapamiętywał obecnie wprowadzone dane.

P9.W2.LUT.26 [Moduł dyplomatyczny]	
Zostało naprawione ułożenie przycisków formularza edycji stosunków międzynarodowych tak, by nie nachodziły na siebie w widoku mobilnym.

__Wydanie W1.LUT.26 (01.02.2026)__

Zmiany:

Z1.W1.LUT.26 [Audytowalność] 
ZEUS zapisuje datę ostatniej zmiany populacji danego kraju w kalkulatorze demograficznym w kolumnie panstwo_populacja_audit.

Z2.W1.LUT.26 [Audytowalność] 
ZEUS zapisuje datę ostatniej zmiany szczegółowego opisu państwa na formularzu państwa w kolumnie panstwo_opis_audit.

Z3.W1.LUT.26 [Audytowalność]
Kalkulator demograficzny wyświetla datę ostatniej zmiany populacji państwa.

Z4.W1.LUT.26 [Audytowalność]
Na formularzu państwa wyświetlana jest teraz data ostatniej zmiany opisu państwa.

Z5.W1.LUT.26 [Changelog] 
ZEUS informuje o zmianach jakie zostały wdrożone w systemie z poziomu przycisku "Informacje o wersjach".

Z6.W1.LUT.26 [Moduł językowy]
Usunięty został przycisk "Edytuj przypisanie języka" z listy wyników wyszukiwania języków.

Z7.W1.LUT.26 [Moduł kulturowy]
Został stworzony formularz dodawania nowej religii.

Z08.W1.LUT.26 [Moduł kulturowy]
Została dodana możliwość filtrowania wyników wyszukiwania religii po nazwie religii.

Z09.W1.LUT.26 [Moduł kulturowy]
Został dodany przycisk "Przypisz religię do państwa".

Z10.W1.LUT.26 [Moduł kulturowy]
Zostały dodane przyciski akcji do wyników wyszukiwania religii.

Z11.W1.LUT.26 [Moduł kulturowy]
Został dodany formularz edycji religii.

Z12.W1.LUT.26 [Moduł kulturowy]
Został dodanny formularz religii.

Z13.W1.LUT.26 [Region]
Została dodana kolumna region_teren do tabeli "regiony".

Z14.W1.LUT.26 [Region]
Do formularza regionu została dodana zmienna "region_teren".

Poprawki błędów:

P1.W1.LUT.26 [Moduł wojskowy]
Naprawiony został wygląd filtra danych wojskowych.

P2.W1.LUT.26 [Formularz państwa]
Naprawione zostało wyświetlanie opisu szczegółówego państwa.

P3.W1.LUT.26 [Moduł historyczny]
Naprawione zostały wszystkie przyciski w module historycznym, by tekst na przyciskach nie podświetlał się przy najeżdżaniu na niego.

P4.W1.LUT.26 [Moduł wojskowy]
Dodano brakujące powiadomienie podczas edycji danych o siłach zbrojnych.

P5.W1.LUT.26 [Moduł kulturowy]
Został zmieniony tekst na prawym kafelku sekcji religijnej z "Edytuj lub dodaj religię" na "Dodaj religię" oraz przycisk "Wejdź" na "Dodaj".

__Wydanie W2.STY.26 (31.01.2026)__

Zmiany:

Z1.W2.STY.26 – [Formularz państwa]
Formularz państwa jako źródło informacji na temat języków urzędowych poszczególnych państw przyjmuje dane z tabeli „jezyki_per_panstwo” zamiast dotychczasowej tabeli „panstwa”.

Z2.W2.STY.26 – [Formularz państwa]
Z formularza dodawania państwa została usunięta możliwość dodania języka urzędowego danego państwa.

Z3.W2.STY.26 – [Formularz państwa]
Dodano formularz edycji państwa, dostępny z poziomu wyników wyszukiwania państwa, bez możliwości edycji języków urzędowych i populacji danego państwa.
Wprowadzono również informacje wskazujące, gdzie można te dane modyfikować.

Z5.W2.STY.26 – [Moduł językowy]
Opis języka został usunięty z poziomu wyników wyszukiwania języka. Pozostał dostępny jedynie z poziomu formularza języka.

Z6.W2.STY.26 – [Moduł demograficzny]
Do kalkulatora demograficznego dodano pole „Bieżąca populacja:”, wyświetlające obecną liczbę ludności (przed przeliczeniem) pod nazwą państwa.

Z7.W2.STY.26 – [Strona główna]
Na dole strony głównej pojawiło się oznaczenie ostatniego wydania systemu ZEUS.

Poprawki błędów:

P1.W2.STY.26 – [Moduł językowy]
Ujednolicono efekt hover na przyciskach akcji w wynikach wyszukiwania, a także na przyciskach „Dodaj nowy język” oraz „Przypisz język do państwa”. Usunięto również podkreślenia pod wyrazami przy najeżdżaniu na przyciski.

P2.W2.STY.26 – [Moduł językowy]
Wyrównano tabele na poszczególnych wynikach wyszukiwania.

P3.W2.STY.26 – [Moduł językowy]
Naprawiono działanie filtrów wyszukiwania języka — po naciśnięciu przycisku „Szukaj” zachowują one wybrane wcześniej kryteria wyszukiwania.

P5.W2.STY.26 – [Moduł plików]
Dodano brakujące powiadomienie podczas przesyłania plików do systemu ZEUS.