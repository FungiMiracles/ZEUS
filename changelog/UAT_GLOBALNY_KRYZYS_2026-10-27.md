# Globalny kryzys gospodarczy — ZEUS UAT WIKI

Na ekranie Generatora Zdarzeń (`/zdarzenia`) rola `wszechmocny` ma panel ręcznego wygenerowania kryzysu: głęboki (75%), średni (50%) lub niewielki (25%). POST wymaga tej roli, tokena CSRF oraz aktualnego roku Entendy. Panel pokazuje ostrzeżenie i potwierdzenie skutku przed wysłaniem.

Wzrost PKB aktywnych państw jest jednorazowo obniżany według `nowy = stary − abs(stary) × procent`, z zaokrągleniem do dwóch miejsc po przecinku. Przykład głębokiego kryzysu: 4 → 1, −4 → −7. Zero pozostaje zerem. Państwa usunięte oraz brakujące wskaźniki nie są zmieniane; liczby zmienionych państw i braków są zapisane w opisie i payloadzie. Nie zmienia się bezpośrednio nominalnego PKB ani nie tworzy fikcyjnych danych gospodarczych.

Transakcja zapisuje jeden globalny rekord w `zdarzenia`, stan przed/po dla każdego wskaźnika w payloadzie i istniejącej tabeli `procent_wzrostu_state_history` (source `GLOBAL_CRISIS`), oraz roczny rejestr `wiki_global_economic_crises`. Klucz główny roku chroni przed dwoma żądaniami z różnych procesów. Zapis rejestru jest wymuszony przed zmianą wskaźników; błędy wycofują całość. Państwa i gospodarki są blokowane w ustalonej kolejności. Rok oblicza serwer z kalendarza Entendy; stary formularz z poprzedniego roku jest odrzucany.

Wszyscy użytkownicy Generatora Zdarzeń widzą czerwony, stały komunikat „trwa [głęboki/średni/niewielki] globalny kryzys gospodarczy” przez pozostałą część roku Entendy. Komunikat nie zależy od filtrów listy zdarzeń. W nowym roku znika i ponownie dostępne jest wywołanie kryzysu. Nie przywraca się automatycznie poprzednich wskaźników; pozostają one wejściem do zwykłych obliczeń gospodarczych.

Zdarzenie kryzysu pozostaje w historii (wyłączono jego usuwanie z WIKI i automatycznej retencji), aby zachować audyt i roczną blokadę. Eksport zdarzeń uwzględnia rekordy globalne bez państwa, regionu i szablonu.

Migracja `migrations/sql/global_economic_crisis_20261027_migrate.py` sprawdza katalog ZEUS_UAT i bazę `entenda_uat_db`. Utworzono wyłącznie tabelę rocznego rejestru. Przed i po migracji było 2113 zdarzeń; liczba wygenerowanych kryzysów wynosiła 0. Nie wywołano kryzysu na rzeczywistych danych, nie zmieniano wskaźników i nie modyfikowano produkcji.

Walidacja: 309 testów unittest przeszło, w tym siedem nowych testów kryzysu: trzy poziomy i znaki wzrostu, NULL i status państwa, historia, równoczesne zgłoszenia, limit roczny i zmiana roku, rollback, rola/CSRF, komunikat niezależny od filtrów oraz eksport/ochrona historii. Izolowany test Playwright `tests/browser/global_economic_crisis.py` potwierdził wybór poziomu, potwierdzenie, wysłanie formularza i czerwony komunikat na sztucznej bazie SQLite.
