# Usuwanie konta i przekazanie państwa do PAGA — UAT, 06.11.2026

Na ekranie „Panel państwa” dodano przycisk „Usuń konto”. Najpierw pojawia się pytanie „Czy jesteś pewien, że chcesz usunąć konto?”. Dopiero po wybraniu „Tak” gracz podaje hasło do swojego konta i zatwierdza przyciskiem „Usuń konto”. Można anulować oba etapy. Formularz chroni token CSRF; błędne hasło nie zmienia danych. Operacja jest dostępna wyłącznie w ZEUS UAT.

Usunięcie konta trwale usuwa wartości e-maila, znormalizowanego e-maila i skrótu hasła z `game_users`, usuwa przypisanie gracza do państwa i wylogowuje go. Pozostaje nieaktywna tożsamość historyczna z identyfikatorem i nazwą autora, potrzebna do zachowania powiązań decyzji, transakcji i wiadomości. Usunięte konto nie może ponownie się zalogować; stare sesje nie mają uprawnień. Adres e-mail jest zwalniany do ponownej rejestracji.

Wpisy na forum, wiadomości, wykonane decyzje oraz stan państwa pozostają zachowane. Oczekujące propozycje dyplomatyczne należące do odchodzącego gracza zostają zapisane jako wygasłe, bez usuwania ich historii. Nie są wykonywane w imieniu byłego gracza.

Jeżeli państwo ma zatwierdzoną konfigurację PAGA, usunięcie przypisania przekazuje je do autonomii i włącza znacznik autonomii. Zmiana wyłączonego znacznika ma własną rewizję `handover`; nie zatwierdza ani nie usuwa wersji roboczej. Harmonogram otrzymuje termin w ciągu najbliższej doby Entendy. Sama wersja robocza lub brak konfiguracji nie wystarczają do uruchomienia autonomii. Globalne zatrzymanie i limity PAGA pozostają w mocy.

Przekazanie nie resetuje gospodarki, budżetów, uzbrojenia, regionów, infrastruktury, relacji ani trwających misji. PAGA korzysta ze stanu pozostawionego przez gracza. Zwolnione państwo pozostaje dostępne dla przyszłej rejestracji, która ponownie wykluczy je z autonomii.

Usunięcie danych logowania, zwolnienie państwa i przekazanie do PAGA odbywają się w jednej transakcji z blokadą państwa. Błąd wycofuje całą operację. Migracja `migrations/sql/account_delete_20261106_migrate.py` dopuszcza wartości NULL w trzech kolumnach danych logowania; sama nie usuwa kont ani danych graczy i sprawdza nazwę bazy UAT.
