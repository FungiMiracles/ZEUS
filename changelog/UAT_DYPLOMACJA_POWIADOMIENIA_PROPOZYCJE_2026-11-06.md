# Dyplomacja: wiadomości świata i oczekujące propozycje — UAT, 06.11.2026

W module dyplomatycznym dodano odrębną rozwijaną listę „Dyplomacja państw trzecich”. Przycisk używa tej samej ikony co ogólne powiadomienia. Każdy wpis zawiera flagi obu państw, opis oraz datę Entendy. Lista ma osobny licznik i trwały stan przeczytania; nie oznacza jako odczytanych wpisów w ogólnym panelu. Zachowuje istniejące kolory kart, w tym czerwone oznaczenie rozpoczęcia wojny. Starsze wpisy są stronicowane.

Do listy trafiają faktyczne zmiany relacji i stanów stosunków oraz odrzucone propozycje zmiany relacji pomiędzy innymi państwami. Samo wysłanie nierozpatrzonej propozycji nie jest ogłaszane. Państwa będące stronami zdarzenia nadal otrzymują dotychczasowe bezpośrednie powiadomienia; nie są odbiorcami wiadomości o sobie jako państwach trzecich.

Rozpoczęcie wojny (w tym eskalacja do wojny kinetycznej) i zakończenie konfliktu przejściem do pokoju tworzą ponadto wpis w ogólnym panelu powiadomień pozostałych graczy. Zawieszenie broni i zamrożenie wojny pozostają zmianami stanu widocznymi na liście dyplomatycznej, bez przedstawiania ich jako definitywnego pokoju. Kliknięcie ogólnej wiadomości świata prowadzi do dyplomacji.

Zdarzenia graczy i PAGA są zapisywane razem z decyzją w jednej transakcji. Niezależne zadanie w tle uzupełnia zmiany zapisane przez administrację WIKI. Unikatowe źródła i blokada kolektora chronią przed duplikatami w wielu procesach i po restarcie. Dostarczenie obejmuje aktywne konta z państwem także wtedy, gdy użytkownik jest wylogowany. Migracja zapisuje punkt początkowy i stan relacji; nie rozsyła całej dawnej historii.

Pod mapą dodano „Oczekujące propozycje zmiany relacji”, z sekcjami otrzymanych i wysłanych propozycji. Wysłane mają status „Oczekuje na odpowiedź od {państwo}”, a otrzymane „{państwo} oczekuje na Twoją odpowiedź” oraz przyciski „Akceptuj” i „Odrzuć”. Widoczne są również wysłane propozycje do NPC. Odpowiedź korzysta z dotychczasowego API, kontroli gracza, tokenu CSRF i sprawdzenia aktualności. Po odpowiedzi karta znika z listy oczekujących.

Dodanie listy propozycji nie zmienia ogólnych powiadomień o tych propozycjach: nie tworzy dodatkowych wpisów ani nie oznacza istniejących jako przeczytane. Wykonane i odrzucone propozycje pozostają w historii.

Zmiana wdrożona wyłącznie w ZEUS UAT. Testy obejmują obu odbiorców bezpośrednich i obserwatorów, graczy i NPC, odrzucenia, zmiany przez WIKI, deduplikację, rollback, autoryzację, osobne odczyty, stronicowanie, układ mobilny, flagi oraz akceptowanie i odrzucanie spod mapy.
