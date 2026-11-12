# UAT — przebudowa PAGA AI (architektura hybrydowa), 10.11.2026

Wyłącznie ZEUS_UAT. Szczegóły: `docs/PAGA_AI_REBUILD.md`.

- Event Detector, Task Manager (deduplikacja znaczeniowa, priorytety CRITICAL–LOW ze starzeniem, gwarantowany przegląd strategiczny), Context Builder (dane z tras gracza, MLD), Decision Runner (≤3 działania na decyzję, sekwencje techniczne bez modelu, budżet jedną decyzją).
- Bezpieczeństwo zapisów: rejestr przed zapisem, brak podwójnego wykonania, weryfikacja stanu po nieznanym wyniku, ochrona przed duplikatami wiadomości.
- Cele strategiczne z rozbiciem, zamiary, plany warunkowe (jednorazowe, ograniczone czasem), strukturalna pamięć strategiczna.
- Metryki w panelu PAGA, ustawienia częstotliwości przeglądu i limitu wywołań.
- Runtime: `-t 6 -b 512 -ub 256`, `cache_prompt`, sesja modelu na tick, restart procesu przed limitem RSS (pomiary w dokumentacji).
- Panel PAGA bez dodatkowego hasła (token 12 h), poprawka samozamykających się rekordów dziennika.
- Migracja: `migrations/sql/paga_ai_rebuild_20261110.py` (addytywna, z kopią, `--rollback`).
- Testy: 586 (w tym 25 scenariuszowych przez run_tick i executor, 5 runtime).
