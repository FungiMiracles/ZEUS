# Budżet, agenci, surowce i handel — UAT, 25.10.2026

Scalono wydatki infrastrukturalne i kopalnie w jeden sektor „Infrastruktura”. Wszystkie rodzaje rozbudowy i kopalń odejmują swoje koszty od wspólnej dostępnej kwoty. Polityka socjalna i prorodzinna tworzą jeden sektor. Dyplomacja i ambasady nie występują w nowych formularzach. W budżecie jest 11 aktywnych kategorii. Złagodzono kolor etykiet i kwot wydatków.

Historyczne przydziały i udziały pozostały niezmienione w bazie; interfejs i powtarzanie planu agregują je do nowych kategorii. Wycofane rekordy słownika pozostawiono dla historii. Niewydaną pulę dyplomacji zwrócono przez jednorazowe, identyfikowalne przesunięcia do rezerw: 5 rachunków, łącznie 70 476 044 002,48 ROI. Sprawdzono zgodność rezerw przed i po migracji oraz niezmienność zatwierdzonych przydziałów. Wersja obliczeń nowych budżetów: 2.

Panel wojenny ma przycisk „Mój kraj”, dopasowujący mapę do regionów metropolitalnych gracza. Karty agentów pokazują nazwę, stan dostępności, państwo i region misji, jej rodzaj, planowany koniec i pozostały czas Entendy. Gracz może bez opłaty zmienić imię i nazwisko własnego agenta, także na misji.

Na ekranie surowców tooltip regionu pokazuje dostępne złoża z ikonami i ilościami, wyłącznie dla własnych regionów. Dodano białe tła ikon, ikony w magazynie i przewijany poziomo kontener tabeli. Budowa kopalni ma ikony przy postępie oraz pomarańczowy pasek przy znaczniku kopalni na mapie. Poprawiono czytelność cyfr łącznej ceny pakietu. Ustawienia opłat portowych otwiera przycisk w nagłówku handlu; formularz znajduje się w oknie modalnym.

Migracja UAT: `migrations/sql/budget_consolidation_20261025_migrate.py`. Dodaje kolumnę nazwy agenta, rozszerza zakres kolejności słownika, porządkuje aktywne sektory i wykonuje idempotentne zwroty dyplomacji w jednej transakcji. Nie usuwa historii.

Weryfikacja: 179 testów unittest, w tym wspólne wydatki kopalni i rozbudowy, ochrona już wydanych środków, zachowanie historycznych udziałów, idempotencja zwrotu oraz autoryzacja zmiany nazwy agenta; składnia czterech skryptów JS; odczyt 13 ekranów UAT; zgodność wszystkich historycznych planów i rezerw; uwierzytelniony odczyt formularza finansów przez HTTP działającej usługi. Bez nowych zakupów, rozkazów, rekrutacji ani budów na kontach graczy w ramach kontroli. Nie wykonywano wizualnych testów w przeglądarce.
