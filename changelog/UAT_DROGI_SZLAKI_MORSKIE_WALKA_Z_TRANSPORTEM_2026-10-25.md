# ZEUS_UAT — środki na drogi i morski transport handlowy

## Drogi i wspólny budżet infrastruktury

Koszt budowy oraz modernizacji pozostaje zapisany w budżecie właściwego półrocza. Usunięto przyczynę nieodświeżania widocznego salda po operacji AJAX: odpowiedź stanu dróg zwraca aktualne dostępne środki sektorów. Nagłówek budżetu, wycena infrastruktury regionów oraz panel fabryk aktualizują się po budowie, modernizacji i decyzji o współfinansowaniu bez przeładowania strony. Historyczny zatwierdzony podział pozostaje zachowany; pomniejszane są środki dostępne do wydania. Audyt potwierdza powiązania płatnych dróg i modernizacji z budżetami.

## Trasy morskie

Dodano geometrię lądów opartą na aktualnej mapie i wyszukiwanie drogi po wodzie (A*, skracanie widocznymi odcinkami oraz dopasowanie do wybrzeża). Każdy odcinek trasy jest sprawdzany pod kątem przecięcia lądu; brak bezpiecznej trasy blokuje zakup bez obciążenia rezerwy. Współrzędne portowe znajdujące się na lądzie są przenoszone na najbliższą stronę morską wybrzeża; zamknięte jeziora nie są traktowane jako szlak morski.

Długość rejsu i czas dostawy wynikają z rzeczywistej trasy przy prędkości 100 km/h Entendy. Animacja pokonuje kolejne odcinki ze stałą prędkością, zamiast interpolować prostą przez ląd. Dotychczasowy bieżący rejs otrzymał poprawną trasę; zakończonego tranzytu nie opóźniano. Ikona statku: CARGO SHIP.

## Fabryki

Mapa ma teraz wysokość do 76% ekranu (minimum 520 px na komputerze, 460 px na telefonie). Przyciski zakładek Budowa dróg i Fabryki zawierają odpowiednie ikony. Automatyczne odświeżanie infrastruktury nie przerywa pracy na mapie fabryk.

## Statki handlowe jako cele wojenne

Panel wojenny pokazuje szlaki, ruchome znaczniki CARGO SHIP, życie i flagę państwa portu wypłynięcia. Kliknięcie wrogiego transportu otwiera istniejące rozkazy ataku lotniczego, rakietowego lub z okrętu. Uderzenie jest kierowane na przewidywane położenie statku w chwili trafienia. Nie można zaatakować własnego transportu, statku bez związku z wrogim państwem, transportu dostarczonego ani celu, którego pocisk nie zdąży dosięgnąć przed wpłynięciem do portu. Neutralny port tranzytowy nie uniemożliwia ataku na wrogi ładunek na morzu.

Standardowe trafienie odbiera 4–15 pkt życia, analogicznie do pozostałych obiektów. Przy 0% statek tonie i ładunek nie jest dostarczany. Rozliczone płatności i opłaty portowe nie są przepisywane. Nadawca i odbiorca otrzymują informację o skutkach ataku. Przed zaksięgowaniem dostawy rozliczane są wcześniejsze trafienia, więc późniejsze otwarcie ekranu handlu nie może dostarczyć zatopionego ładunku. Powtórne odświeżenie nie nalicza drugi raz obrażeń ani dostawy.

## Weryfikacja i migracja

`migrations/sql/trade_sea_combat_20261025_migrate.py` jest ograniczona do UAT: dodaje trasę, życie, pochodzenie i znacznik zatopienia statku oraz cel lotu bojowego. Uzupełnia niezakończone rejsy; nie zmienia towarów, płatności ani rezerw. Zależność geometrii: Shapely 2.2.0.

266 testów Python; testy JavaScript i składni; renderowanie ekranów; przeglądarka desktop/mobile z zablokowanymi rzeczywistymi operacjami. Nowe testy obejmują wodne obejście lądu, portowe punkty startu, ruch po długości trasy, przechwycenie ruchomego transportu z neutralnego portu, odrzucanie nieuprawnionych celów, zatopienie przed dostawą i odświeżanie budżetu modernizacji. Audyt rzeczywistej trasy potwierdził brak przecięć z lądem i zgodność długości ze skalą. Rezerwy oraz księga pożyczek pozostają zgodne.
