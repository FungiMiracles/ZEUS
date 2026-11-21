# Transport lotniczy (20 listopada 2026)

## Zasady gry

| Element | Reguła |
|---|---|
| Technologia | „Transport lotniczy” — 400 pkt rozwoju, 28 dni Entendy, wymaga „Transportu kolejowego” („Transport i komunikacja” → „Transport kolejowy” → „Transport lotniczy”). |
| Gdzie | Ekran „Infrastruktura i energetyka”, mapa regionów: kliknięcie / najechanie na miasto → tooltip z przyciskiem „Zbuduj port lotniczy”. |
| Miasta | Miasta własnego państwa powyżej 100 000 mieszkańców. Państwo bez takich miast — tylko jego największe miasto. Jedno lotnisko na miasto. |
| Koszt | 1400 kamienia, 200 żelaza, 5 chipów kerbitowych, 3 chipy natsytowe (z magazynu) + ludność miasta × 100 ROI (z niewydanych środków budżetu infrastruktury bieżącego okresu). |
| Czas budowy | 14 dni Entendy. Region okupowany i strefa skażenia jądrowego blokują budowę. |
| Nazwa | Najwyżej 60 znaków. Domyślnie (i zawsze w PAGA2): „Port lotniczy {nazwa miasta} – {kod miasta}”. Przycisk „Zmień nazwę” w tooltipie lotniska (i w oknie „Zarządzaj”): zmiana najwyżej raz na rok Entendy — kolejna możliwa rok po poprzedniej (29 lutego → 28 lutego); nadanie nazwy przy budowie się nie liczy. |
| Połączenia | Automatyczne między wszystkimi czynnymi lotniskami świata (ukończone, życie > 0). Właściciel lotniska może czasowo zawiesić połączenie z wybranym lotniskiem (okno „Zarządzaj”) i je wznowić; połączenie nie działa, gdy zawiesi je którakolwiek strona. |
| Dochód | W każdym cyklu budżetowym: dla każdego czynnego połączenia, w którym uczestniczy lotnisko państwa, (ludność miasta A + ludność miasta B) × 10 ROI. Przykład: 5 mln + 3 mln → 80 mln ROI. Połączenie dwóch własnych lotnisk liczy się raz; połączenia lotnisk innych państw nie zwiększają budżetu państwa. Pozycja „Dochody z lotnictwa” w budżecie. |
| Mapa „Świat” | Gdy istnieją co najmniej 2 lotniska: samoloty latają tam i z powrotem po każdym czynnym połączeniu (1000 km/h czasu gry), dziobem w kierunku lotu, bez rysowania trajektorii; tooltip — lotnisko docelowe. Filtr „Samoloty”; ikony lotnisk w warstwie „Znaczniki miast”. |
| Obrona | Panel obrony państwa: własne lotniska na mapie (filtr „Lotniska”) i w panelu regionu; obrona przeciwrakietowa na poziomach 1–7 (jak dla innych obiektów: najpierw obrona regionu, potem lotniska). |
| Wojna | Panel wojenny: lotniska państw, z którymi trwa wojna, są widoczne i można je bombardować / ostrzelać rakietami bez rozpoznania wywiadu. Trafienie: 4–15 pkt życia na nieprzechwyconą rakietę. Życie 0 — lotnisko zniszczone (znika, traci obronę i połączenia; w mieście można zbudować nowe). Wybuch jądrowy niszczy lotniska w promieniu skażenia. |
| Handel | Oferta „Lotniczy (lotnisko)”: wysyłka z własnego czynnego lotniska sprzedającego, odbiór na własnym czynnym lotnisku kupującego (wybór z listy lub na mapie, jak port). Bez opłat portowych i limitów infrastruktury portowej. Samolot towarowy: 1000 km/h, nie może zostać zaatakowany. |

## PAGA2

- Planer: cel `tech:air_transport` w priorytetach `infrastructure` i `trade` (cała ścieżka technologii od korzenia).
- Adapter `airports` (`game/paga2/airports.py`, tryb CYCLIC): jedna budowa naraz, najwyżej 3 lotniska, najludniejsze dozwolone miasto bez lotniska, komplet surowców i chipów, koszt ≤ 60% środków infrastruktury, zwrot z dochodów z połączeń w liczbie cykli zależnej od konserwatyzmu fiskalnego (pierwsze lotnisko świata — tylko przy koszcie ≤ 20% środków).
- Adapter `trade`: kupuje oferty lotnicze, gdy państwo ma czynne lotnisko. Adapter `war`: lotniska przeciwników są celami uderzeń.
- PAGA2 nie zawiesza połączeń.

## Implementacja

| Plik | Zakres |
|---|---|
| `game/airports.py` | Zasady, wycena, budowa, zawieszanie połączeń, dochody, dane ekranów; endpointy `/game/lotniska/stan`, `/game/lotniska/wycena`, `/game/lotniska/zmien` (`build`, `suspend`, `resume`). |
| `game/airport_models.py` | `game_airports`, `game_airport_expenses`, `game_air_route_suspensions`. |
| `game/finance_service.py` | `air_income` w `calculate_budget`, podglądzie i zatwierdzeniu budżetu (transakcja `AIR_INCOME`). |
| `game/budget_transfers.py` | Wydatki na lotniska w saldzie infrastruktury. |
| `game/trade_service.py`, `game/commerce.py` | Oferty i dostawy `transport='air'`. |
| `game/missile_defense.py`, `game/military_service.py`, `game/military_flights.py`, `game/nuclear.py`, `game/military.py` | Obrona, cele ataku (`target_airport_id`), skutki trafień, mapy paneli. |
| `static/js/game_airports.js`, `templates/game/_airports.html` | Tooltip miasta, okna budowy i zarządzania, ikony lotnisk. |
| `static/js/game_air_traffic.js` | Animacja samolotów na mapie świata. |
| `migrations/sql/airports_20261120.py` | Migracja schematu (UAT, PREPROD); kolumna `game_airports.renamed_at` dodana w tym samym skrypcie. |
| `migrations/sql/airports_uat_seed_20261120.py` | Dane startowe UAT: Ozilandia i Findehalia (technologie, lotniska w Saint Adams i Delin, oferta lotnicza Findehalii). |
| `tests/test_airports.py` | Testy zasad, budowy, połączeń, dochodów, obrony, handlu i PAGA2. |

## Wygląd

Tooltipy lotniska i miasta oraz okna budowy, zarządzania i zmiany nazwy mają styl ekranu „Infrastruktura i energetyka”: biała karta z granatowym akcentem (#1E3A5F), granatowe przyciski główne, jasne karty z granatową lewą krawędzią, ciemne rozmyte tło okien (`static/css/game_airports.css`).

## Zmiana 21 listopada 2026

- Budowa i zarządzanie portami lotniczymi odbywa się w osobnej zakładce „Transport lotniczy” ekranu „Infrastruktura i energetyka”
  (`templates/game/_airport_tab.html`, mapa `#airport-map` tworzona przy pierwszym otwarciu zakładki w `static/js/game_airports.js`).
  Mapa regionów (zakładka „Infrastruktura regionów”) nie pokazuje już lotnisk ani przycisku budowy w tooltipie miasta.
- Stan lotnisk (`/game/lotniska/stan`) zwraca położenie miast (`cities[].point`).
- Samolot na mapie „Świat” jest pomarańczowy (kształt `SAMOLOT.svg` jako maska CSS, `.world-plane-shape`).

