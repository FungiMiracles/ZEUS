# Salda i przesunięcia budżetowe — UAT, 2026-10-24

Wdrożono w ZEUS_UAT / entenda_uat_db. Produkcja bez zmian. Migracja `budget_transfers_entenda_uat_db.sql` dodaje tabelę historii przesunięć z identyfikatorem użytkownika, budżetem, kategoriami, dokładną kwotą, datą rzeczywistą i datą Entendy oraz kluczem zapobiegającym podwójnemu wykonaniu żądania.

Zatwierdzony formularz pokazuje wszystkie 17 sektorów: pierwotną kwotę, przydział po przesunięciach, wydatki/zobowiązania i pozostałe środki. Rozliczenia obejmują infrastrukturę (także wykorzystanie rezerwy), koszty baz, obrony przeciwrakietowej i utrzymanie wojskowe. Kwoty pozostałych sektorów nie mają obecnie osobnych mechanizmów wydatkowych.

Przesunięcia dotyczą wyłącznie własnego zatwierdzonego budżetu na bieżące półrocze. Możliwe są także przesunięcia z rezerwy i do rezerwy; aktualizują rachunek oraz saldo przenoszone na kolejne półrocze. Nie można przenieść wydanych lub zajętych środków. Przed przesunięciem z sektora wojskowego ustalane są zobowiązania jego utrzymania; wpływające środki są uwzględniane przed oceną konieczności redukcji garnizonów. Wszystkie operacje korzystają z blokady państwa i transakcji, zgodnej ze ścieżkami wydatków infrastrukturalnych i wojskowych. Kwoty są przeliczane jako Decimal, a w JSON przesyłane jako tekst. API wymaga autoryzacji i CSRF.

Pierwotne zatwierdzone przydziały, stawki podatkowe i historia planu pozostają niezmienne. Przesunięcia są osobnym rejestrem; bieżące finansowanie infrastruktury i wojska korzysta z przydziałów powiększonych lub pomniejszonych o te zapisy. Ponowienie identycznego żądania nie wykonuje drugiego przesunięcia.

Walidacja: 141 testów Python OK (9 nowych przypadków: salda i wydatki, zobowiązania wojskowe, rezerwa i kolejny okres, powtórzenia, kwoty i przekroczenia, obce/historyczne budżety, infrastruktura, API/CSRF, finansowanie utrzymania przed redukcją). Składnia JavaScript OK. Odczytowy test formularza zatwierdzonego planu, 17 sald, historii i CSRF na MySQL UAT OK; nie wykonywano przesunięć na danych graczy. Gunicorn łagodnie przeładowany; usługa aktywna, skrypt i CSS dostępne przez HTTP 200. Bez wizualnego testu przeglądarkowego.
