# ZEUS_UAT — obrona kopalń i ujednolicenie interfejsu

- Ikony minerałów na mapach i przy kopalniach: białe, okrągłe tło. Ikony samych kopalń pozostają bez tła.
- Ochrona przeciwrakietowa kopalń: wybór kopalni na mapie obrony, budowa i zarządzanie jak dla bazy (100 mln ROI, wspólny budżet wojskowy). Regionalna osłona działa pierwsza, osłona konkretnej kopalni druga. Pozycja osłony odpowiada kopalni. Zniszczenie kopalni usuwa jej osłonę z zachowaniem historii kosztów.
- Jasne kontenery zarządzania obroną, jaśniejsza zieleń zdrowych obiektów, przycisk „Reorganizuj”.
- Górny pasek gry pokazuje wolne środki wszystkich 11 sektorów bieżącego półrocza. Uwzględnia wydatki, przesunięcia i korekty; poprzedni plan nie jest prezentowany jako bieżący. Zestawienie można zwinąć.
- Ikona PODSUMOWANIE w podsumowaniu planu; stonowane liczby w planowaniu rozbudowy infrastruktury.
- Jasne okna na mapie dyplomacji, zgodne z motywem gry.
- Flagi państw po lewej stronie rekordów wydarzeń, także przy państwie ustalonym przez region wydarzenia.
- Powiadomienia otrzymały właściwe ikony: WYWIAD WOJSKOWY, PRACE BUDOWLANE 2, POŻYCZKA. Raporty wywiadu i wiadomości o działaniach hybrydowych mają wspólną ikonę wywiadu.

Migracja ograniczona do UAT: `migrations/sql/mine_missile_defense_20261025_migrate.py` rozszerza walidację celu obrony o kopalnie. Istniejące rekordy pozostają niezmienione.

Weryfikacja: 249 testów Python, testy JavaScript, renderowanie ekranów gry, kontrola przeglądarkowa na komputerze i telefonie. Testy nie wykonują prawdziwych inwestycji ani operacji budżetowych na UAT.
