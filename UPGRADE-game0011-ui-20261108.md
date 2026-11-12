# ZEUS GAME UAT — poprawki GUI A–I, 8 listopada 2026

- Magazyn w Panelu państwa: liczby nie zawijają się, karty dopasowują szerokość; test także dla 29-cyfrowej ilości.
- Ikony żelaza i elektryczności pochodzą ze static/icons; wersjonowanie zasobów zapobiega korzystaniu ze starych ikon. Elektryczność oznacza moduł i bilans energetyczny.
- Bilans: produkcja i zużycie w osobnych wierszach, jedna cyfra po przecinku, jednostka e/dzień, dotychczasowe kolory.
- Budowa: osobne zakładki Fabryki, Kopalnie, Elektrownie. Katalogi w czterech kolumnach desktop / dwóch mobilnie. Karty z ikonami, poziomami fabryk, ceną i przyciskiem Buduj dla dostępnej technologii. Bez technologii: szara karta i tooltip z wymaganiem. Buduj uruchamia wskazanie lokalizacji i potwierdzenie, nie tworzy obiektu bez wybrania mapy.
- Likwidacja: rzeczywista kwota zwrotu przekazywana przez API na podstawie tego samego katalogu cen co rozliczenie; modal i przyciski z odstępami. Kwota widoczna również w potwierdzeniu likwidacji kopalni na ekranie surowców.
- Badania: promienista sieć z metodą w centrum, krótsze połączenia, dopasowanie do szerokości i wysokości ekranu, zapobieganie kolizjom ikon w mniejszych widokach. Przy bąblach tylko ikony; opisy i stan w tooltipie. Ikony surowców i chipów; lekki niebieski glow opracowanych technologii. Odstępy między przyciskami modalu i kontrolkami plus/minus.
- Handel: przygotowanie ładunku poziomo, na całą szerokość nad mapą; mniejsze pola towarów, nazwa i dostępna liczba bez zawijania (pełna informacja także w title). Mobilnie pionowo.

Bez migracji bazy i zmiany reguł gospodarczych. Zmieniono wyłącznie UAT. Pełny zestaw: 423 testy OK. Test Chromium na izolowanej bazie: 1440/390 px, duże liczby, zakładki i brakujące technologie, budowa na mapie, kwota zwrotu, format energii, 34 bąble bez kolizji, układ handlu i brak poziomego przepełnienia strony. Testy nie korzystają z sesji ani danych graczy działającej usługi.
