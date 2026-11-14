"""Render the PAGA2 review as a standalone offline HTML document with SVG diagrams.

Run from the repository: venv/bin/python scripts/render_paga2_algorithms.py
"""
from pathlib import Path
from html import escape
import re
import textwrap
import markdown

ROOT = Path(__file__).resolve().parents[1]
FLOWS = [
    ('Harmonogram PAGA2', [
        ('Kontrola co 30 s', 'Czas rzeczywisty; tylko UAT'),
        ('Sprawdzenie konfiguracji i blokady', 'Wyłączone lub zajęta blokada → koniec'),
        ('Wybór uprawnionych państw', 'Autonomia, brak gracza; silnik sprawdza suwerenność'),
        ('BUDGET: jeśli brakuje budżetu', 'Błąd → ponowienie za 2 godziny'),
        ('IMMEDIATE: jeśli są nowe wyzwalacze', 'Bezpieczeństwo ma pierwszeństwo'),
        ('CYCLIC: jeśli upłynął termin', 'Domyślny interwał: 60 minut'),
        ('Następne państwo', 'Błąd państwa nie przerywa całej listy'),
    ]),
    ('Silnik decyzji', [
        ('Uprawnienia i request_key', 'Istniejąca decyzja → zwróć jej ID'),
        ('Kontekst państwa', 'Profil, sytuacja, relacje, pamięć, środki, mapa'),
        ('Opcje adapterów + PASSIVE', 'Punktacja i kontrola wykonalności'),
        ('Wymagane decyzje', 'Najlepszy wariant w grupie, poza zwykłym limitem'),
        ('Zwykła opcja powyżej progu', 'Różnica od najlepszej <2 pkt → losowanie'),
        ('Endpoint gracza', 'Sukces → koszty i blokada grupy; błąd → odrzucenie'),
        ('Kolejna próba do limitu', 'Wróć do wyboru zwykłej opcji'),
        ('Zapis historii', 'EXECUTED / REJECTED / PASSIVE / ERROR'),
    ]),
    ('Planowanie rozwoju', [
        ('Przeliczenie aktywnych planów', 'Każdy cykl korzysta z aktualnego stanu'),
        ('Zgodność priorytetów i możliwość celu', 'Brak zgodności → ABANDONED; niemożliwy → IMPOSSIBLE'),
        ('Technologie → zasoby → energia → budowa', 'Zakończone, w budowie lub zewnętrzne → DONE'),
        ('Pierwszy gotowy etap przed blokadą', 'Brak etapu → oczekiwanie; >720 bez postępu → porzucenie'),
        ('Propozycja etapu do wspólnego silnika', 'Pierwszy proponowany etap jest required'),
        ('Nowe cele przy wolnym limicie planów', 'Brak aktywnych planów → wymagany start planu'),
        ('Kolejny cykl: ponowne przeliczenie', 'Etapy nie są bezwarunkowo wykonywaną kolejką'),
    ]),
    ('Ustalanie budżetu', [
        ('Brak budżetu bieżącego okresu', 'Od 1 października 3001: kwartały'),
        ('Podgląd finansów gracza', 'Podatki, dochody, wskaźniki i świadczenia'),
        ('Wagi sektorów', 'Profil + sytuacja + potrzeby i poprzednie wykorzystanie'),
        ('Wygładzenie poprzednim planem', 'Stopień zależy od przewidywalności państwa'),
        ('Warianty podatku i świadczeń', 'Podgląd gry i ocena każdego wariantu'),
        ('Wybór przez silnik', 'BUDGET: jedna zwykła próba, bez progu PASSIVE'),
        ('Zatwierdzenie operacją gracza', '/game/finanse/zatwierdz'),
    ]),
]

def diagram(index):
    title, stages = FLOWS[index]
    height = len(stages)*112+12
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 720 {height}" role="img" aria-labelledby="diagram-{index}">',
           f'<title id="diagram-{index}">{escape(title)} — schemat przeglądowy; warunki opisano pod krokami</title>',
           f'<defs><marker id="arrow-{index}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10Z" fill="#1e3a5f"/></marker></defs>']
    for n, (label, note) in enumerate(stages):
        y = n*112+8
        out.append(f'<rect x="10" y="{y}" width="700" height="86" rx="10" fill="#fff" stroke="#1e3a5f"/>')
        out.append(f'<text x="28" y="{y+28}" font-size="18" font-weight="700" fill="#1e3a5f">{n+1}. {escape(label)}</text>')
        for i, line in enumerate(textwrap.wrap(note, 77)):
            out.append(f'<text x="28" y="{y+52+i*18}" font-size="14" fill="#4d5f78">{escape(line)}</text>')
        if n < len(stages)-1:
            out.append(f'<path d="M360 {y+86} V{y+110}" stroke="#1e3a5f" stroke-width="2" marker-end="url(#arrow-{index})"/>')
    return '\n'.join(out+['</svg>'])

source = (ROOT/'docs/PAGA2_ALGORYTMY.md').read_text()
counter = iter(range(len(FLOWS)))
def replace(match):
    index = next(counter)
    return f'\n<div class="flow">{diagram(index)}</div>\n<details><summary>Pełny schemat warunków w Mermaid</summary><pre>{escape(match.group(1))}</pre></details>\n'
source = re.sub(r'```mermaid\n(.*?)```', replace, source, flags=re.S)
body = markdown.markdown(source, extensions=['tables', 'fenced_code', 'toc'])
html = '''<!doctype html><html lang="pl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PAGA2 — algorytmy i schematy</title><style>
*{box-sizing:border-box}body{margin:0;background:#f0f4fa;color:#24324a;font:16px/1.6 system-ui,sans-serif}main{max-width:1060px;margin:auto;padding:24px}h1,h2,h3{color:#1e3a5f;line-height:1.25}h1{border-bottom:4px solid #1e3a5f;padding-bottom:20px}h2{margin-top:44px}a{color:#1e3a5f}code{font-size:.88em;overflow-wrap:anywhere}pre{white-space:pre-wrap;font-size:13px;padding:16px;background:#fff;border:1px solid #d3dce9;border-radius:8px}table{border-collapse:collapse;width:100%;background:white;font-size:14px}th,td{border:1px solid #d3dce9;padding:10px;text-align:left}th{background:#1e3a5f;color:white}.flow{max-width:760px;margin:20px auto;overflow-x:auto}.flow svg{display:block;width:100%;min-width:560px;font-family:system-ui,sans-serif}summary{cursor:pointer;padding:10px;font-weight:600;color:#1e3a5f}details{border:1px solid #d3dce9;border-radius:8px}button{padding:10px 18px;background:#1e3a5f;color:white;border:0;border-radius:8px;cursor:pointer;font:inherit} @media(max-width:600px){main{padding:16px}table{font-size:12px}th,td{padding:6px}}@media print{body{background:white}main{padding:0}button,details{display:none}.flow{break-inside:avoid}.flow svg{min-width:0}h2{break-after:avoid}table{font-size:11px}}
</style><main><button onclick="window.print()">Drukuj / zapisz jako PDF</button>'''+body+'</main></html>'
(ROOT/'docs/PAGA2_ALGORYTMY.html').write_text(html)
print('Wygenerowano docs/PAGA2_ALGORYTMY.html (4 schematy SVG).')
