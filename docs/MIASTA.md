# Obiekty miejskie — etap 1 (21 listopada 2026)

## Zasady gry

- Zakładka „Miasta” na ekranie „Infrastruktura i energetyka” (ikona `MIASTO.svg`): mapa państwa z miastami (ikona miasta i nazwa,
  bez kropek; stolica — kolor złoty). Po lewej kontenery: odsetek ludności miejskiej z dostępem do edukacji, ochrony zdrowia
  i komunikacji miejskiej (obsłużeni mieszkańcy w mieście nie więcej niż jego ludność).
- Kliknięcie miasta otwiera okno zarządzania: ikona miasta, budżety ochrony zdrowia, edukacji i infrastruktury (niewydane środki
  bieżącego okresu), katalog obiektów i plan 8 × 8 białych kratek. Obiekt przeciąga się na wolną kratkę (telefon: klik obiektu,
  potem kratki); okno potwierdzenia pokazuje ikonę obiektu, koszt budowy, roczne utrzymanie, czas budowy i finansowanie
  („Buduj” / „Anuluj”). Kliknięcie zbudowanego obiektu: szczegóły i „Zlikwiduj obiekt”.

| Obiekt | Ikona | Koszt | Czas | Utrzymanie / rok | Obsługuje | Sektor | Efekt |
|---|---|---|---|---|---|---|---|
| Klinika | CLINIC.svg | 25 mln | 14 dni | 5 mln | 25 000 | ochrona zdrowia | zdrowie publiczne +1 / 1 mln objętych opieką |
| Szpital | SZPITAL.svg | 400 mln | 30 dni | 50 mln | 1 250 000 | ochrona zdrowia | jw. |
| Żłobek | NURSERY.svg | 15 mln | 14 dni | 3 mln | — | polityka socjalna i prorodzinna | przyrost +0,01% / żłobek (max +0,20%) |
| Szkoła | SZKOŁA.svg | 50 mln | 28 dni | 12 mln | 50 000 | edukacja | poziom edukacji +1 / 1 mln objętych edukacją szkolną |
| Uniwersytet | UNIWERSYTET.svg | 500 mln | 90 dni | 70 mln | 500 000 | edukacja | poziom edukacji +1 / 1 mln objętych edukacją wyższą |
| Tramwaj | TRAMWAJ.svg | 250 mln | 60 dni | 30 mln | 300 000 | infrastruktura | zadowolenie +1 / 2 mln objętych komunikacją |
| Autobus | AUTOBUS.svg | 50 mln | 21 dni | 15 mln | 150 000 | infrastruktura | jw. |
| Metro | METRO.svg | 1,5 mld | 120 dni | 150 mln | 1 000 000 | infrastruktura | jw. |
| Monument | MONUMENT.svg | 200 mln | 60 dni | 5 mln | — | infrastruktura | spójność społeczna i tożsamość narodowa +1 / monument |

- Budowa: koszt z niewydanych środków sektora bieżącego okresu; brakującą część pokrywa rezerwa budżetowa (podział widoczny
  w oknie potwierdzenia); bez wystarczających środków budowa jest odrzucana.
- Utrzymanie: przy zatwierdzeniu budżetu pobierana jest część roczna za okres (kwartał ¼, półrocze ½) z budżetu sektora;
  brakującą część pokrywa rezerwa, a gdy i jej brakuje, obiekty sektora są likwidowane od najtańszego w utrzymaniu, aż koszt
  zmieści się w środkach. Efekty zlikwidowanych obiektów znikają; gracz dostaje powiadomienie.
- Likwidacja przez gracza: zwrot 25% kosztu budowy do budżetu sektora finansującego obiekt (bieżący okres; bez budżetu okresu —
  do rezerwy budżetowej).
- Efekty działają od ukończenia budowy. Do wskaźników społecznych (`spoleczenstwo`) dodawana jest tylko różnica względem efektu
  już naliczonego (`game_city_effects.applied`), więc likwidacja odejmuje dokładnie to, co obiekt dodał (z uwzględnieniem granic 0–100).
- Poziom edukacji powyżej 50 skraca czas rozwoju technologii o (poziom / 5)% (`game.research_timing.education_bonus`).
- Ekran „Podatki i budżet”: kontenery rocznego utrzymania (edukacja, ochrona zdrowia, komunikacja miejska) z częścią za bieżący okres.

## PAGA2

Adapter `game/paga2/cities.py` (ekran `cities` → `/game/miasta/stan`): jedna budowa na przebieg, najwyżej 2 budowy naraz,
koszt ≤ 50% środków sektora, utrzymanie sektora (z nowym obiektem) / 4 ≤ 35% środków sektora; miasto z największą liczbą
mieszkańców bez dostępu do usługi. Efekty opcji: welfare (ochrona zdrowia, żłobki, szkoły), infrastructure (komunikacja,
monumenty), production/research (szkoły, uniwersytety); cecha prospołeczności podnosi ocenę ochrony zdrowia, żłobków i szkół.
ZEUS WIKI → PAGA → „Stan państwa PAGA” → „Miasta i obiekty miejskie”.

## Implementacja

- `game/city_models.py` — tabele `game_city_buildings`, `game_city_expenses`, `game_city_effects`
  (migracja `migrations/sql/cities_20261121.py`, tylko nowe tabele).
- `game/cities.py` — zasady, blueprint `game_cities` (`/game/miasta/stan`, `/wycena`, `/zmien`; dopisany do strażnika w `zeus_app.py`).
- `game/budget_transfers.py` — wydatki miast w `sector_balances` i `infrastructure_balance`.
- `game/finance_service.py` — `charge_maintenance` po zaksięgowaniu budżetu (`approve_in_transaction`).
- `engine/infrastructure_scheduler.py` — co 30 s ukończone budowy (powiadomienia, efekty); także przy odczycie powiadomień.
- `engine/demography.py` — dodatek żłobków do rocznego przyrostu miast i wsi.
- Widok: `templates/game/_cities.html`, `static/js/game_cities.js`, `static/css/game_cities.css`; testy `tests/test_cities.py`.
