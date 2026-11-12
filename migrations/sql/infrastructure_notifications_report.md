# Powiadomienia o zakończeniu rozbudowy infrastruktury — UAT

Zakończenie zlecenia tworzy powiadomienie w istniejącym panelu systemowym. Treść zawiera rodzaj infrastruktury i nazwę regionu: „Zakończyła się rozbudowa infrastruktury drogowej w regionie Mazowsze”. Nazwa regionu jest zapamiętywana przy zakończeniu prac. Powiadomienie otrzymuje gracz przypisany do państwa w chwili zakończenia. Kliknięcie oznacza je jako przeczytane i otwiera ekran infrastruktury. Dostęp chroni istniejąca kontrola właściciela i CSRF.

Podniesienie poziomu, oznaczenie zlecenia jako zakończonego i utworzenie powiadomienia są jedną transakcją. Blokady wierszy oraz unikalny indeks użytkownik/zlecenie zabezpieczają przed powieleniem przy kilku procesach aplikacji. Dotychczas zakończone zlecenia nie są powiadamiane ponownie.

Dodano niezależne zadanie infrastruktury uruchamiane w UAT co 30 sekund, również bez obecności gracza. Nie włącza ono automatycznego księgowania budżetów. Odczyt panelu powiadomień dodatkowo rozlicza zakończone prace danego państwa, zapewniając aktualne dane przy pobraniu powiadomień.

Migrację `infrastructure_notifications_entenda_uat_db.sql` wykonano w entenda_uat_db. Zweryfikowano kolumny, indeks unikalny, klucz obcy i rozszerzony CHECK. Gunicorn UAT przeładowano. Nie zmieniano produkcji.

Testy: 83 zaliczone. Nowe przypadki obejmują treść, prywatność, odczyt, brak duplikatów, wycofanie całej transakcji i zakończenie przez zadanie w tle bez otwierania ekranu. Składnia Python poprawna. Bez testu wizualnego w przeglądarce.
