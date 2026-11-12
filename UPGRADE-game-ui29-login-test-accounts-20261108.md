# ZEUS UAT — pasek gry, logowanie i usunięcie kont testowych

Z paska gry usunięto logo ZEUS i odnośnik „Informacje o zmianach”. Strona informacji pozostaje dostępna pod dotychczasowym adresem. Zmniejszono czcionkę etykiety zalogowanego gracza do 10 px, nazwy do 12 px i Wyloguj do 10 px (minimalna wysokość przycisku 28 px). CSS ui29.

Na ekranie logowania tytuł sekcji administracyjnej to „Panel administratora”. Przycisk „Zaloguj jako administrator” ma zielone tło, biały tekst i pogrubienie 700; zachowuje rozwijanie panelu.

Konta Testowy (ID 4, Tersa ID 128) i Testowo (ID 5, Pobelia ID 136): usunięto przypisania państw, dane logowania i kontaktowe; konta wyłączono i zastąpiono ich nazwy anonimowymi nazwami technicznymi. Pod nazwami testowy/testowo nie pozostały konta. Zachowano same identyfikatory historyczne, ponieważ konto Testowo jest autorem zatwierdzonego budżetu i przesunięcia środków, a oba konta są adresatami historycznych wpisów i powiadomień. Nie usuwano ani nie przeliczano budżetów, zasobów i historii państw. Nie zmieniano ustawień PAGA państw.

Operację wykonano transakcyjnie, z blokadami państw i użytkowników. Kopia rekordów sprzed usunięcia: backups/test_users_20261108_before_erasure.json, uprawnienia 0600. Po operacji sprawdzono brak nazw docelowych, brak przypisań i brak aktywności/hasła/e-maila dla obu historycznych identyfikatorów.

Weryfikacja: 17 testów paneli WIKI i strony informacji (zaktualizowane oczekiwanie braku linku/logo), izolowany Chromium 1440/390 px dla paska, rozmiarów czcionek, kolorów/pogrubienia przycisku i tytułu panelu administratora.
