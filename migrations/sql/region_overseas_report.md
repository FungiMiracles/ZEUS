# Terytoria zamorskie i skala infrastruktury — UAT, 24.10.2026

Dodano `Region.terytorium_zamorskie` (BOOLEAN NOT NULL DEFAULT 0), pole Tak/Nie na dodawaniu i edycji regionu WIKI oraz wartość na stronie regionu. Formularze sprawdzają wartości TAK/NIE, zachowują wybór przy błędach i korzystają z istniejących uprawnień WIKI.

Panel główny oraz mapy infrastruktury, demografii, środowiska i surowców naturalnych rysują tylko regiony metropolitalne. Zasięg widoku wynika z geometrii tych regionów; usunięto zależność od pełnego obrysu państwa, zawierającego odległe terytoria. Miasta na mapach również ograniczono do regionów metropolitalnych. Przy braku takich regionów nie stosuje się powrotu do mapy całego świata lub pełnego państwa. Wskaźniki i dane państwa nadal uwzględniają wszystkie jego regiony; w panelu infrastruktury pozostają one dostępne z listy.

Wartości infrastruktury w panelu regionu są pogrubione i mają kolory według progów: 90–100 ciemnozielony, 75–89 zielony, 60–74 żółty, 40–59 pomarańczowy, 0–39 czerwony. Zaktualizowano kolory tabeli i legendę.

Migrację `region_overseas_entenda_uat_db.sql` wykonano w entenda_uat_db i zweryfikowano kolumnę. Wszystkie 634 istniejące regiony zachowały domyślną wartość Nie — właściwe terytoria należy oznaczyć w WIKI. Nie zmieniano produkcji. Gunicorn UAT przeładowano i potwierdzono aktywną usługę, dwa nowe procesy robocze oraz dostępność zasobów HTTP.

Walidacja: 80 testów zaliczonych; składnia Python i Jinja poprawna. Testy obejmują progi kolorów, zakres mapy po zmianie znacznika, dodawanie i edycję w WIKI, odrzucanie nieprawidłowej wartości i kontrolę uprawnień. Nie przeprowadzono wizualnego testu przeglądarkowego.
