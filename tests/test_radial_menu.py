"""25 Nov 2026: opcje obiektów na mapie obrony i w panelu wojennym w kole dookoła obiektu (game_radial_menu.js)."""
import json
import re
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote
from test_game_military import MilitaryFixture

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {'defense': 'OBRONA PRZECIWRAKIETOWA.svg', 'defensePlus': 'OBRONA PRZECIWRAKIETOWA PLUS.svg', 'rename': 'ZMIEŃ NAZWĘ.svg',
            'move': 'PRZENIEŚ.svg', 'reorganize': 'REORGANIZUJ.svg', 'withdraw': 'WYCOFAJ.svg', 'liquidate': 'ZLIKWIDUJ.svg', 'upgrade': 'ROZBUDUJ.svg'}


class RadialMenuPageTests(MilitaryFixture):
    def config(self, url):
        with patch('game.military.land_targets', return_value=[]):
            page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        text = page.get_data(as_text=True)
        self.assertIn('js/game_radial_menu.js', text)
        self.assertIn('css/game_radial_menu.css', text)
        self.assertLess(text.index('js/game_radial_menu.js'), text.index('js/game_military.js'))
        raw = re.search(r'<script type="application/json" id="military-config">(.*?)</script>', text, re.S).group(1)
        return json.loads(raw)

    def test_menu_icons_are_the_requested_files_and_exist(self):
        icons = self.config('/game/obrona-panstwa')['menuIcons']
        for code, name in REQUIRED.items():
            self.assertTrue(unquote(icons[code]).endswith('/icons/' + name), (code, icons[code]))
        for url in icons.values():
            path = ROOT / unquote(url.split('?')[0]).lstrip('/')
            self.assertTrue(path.is_file(), path)


class RadialMenuScriptTests(MilitaryFixture):
    def test_object_options_open_in_the_radial_menu(self):
        military = (ROOT / 'static/js/game_military.js').read_text()
        radial = (ROOT / 'static/js/game_radial_menu.js').read_text()
        css = (ROOT / 'static/css/game_radial_menu.css').read_text()
        # etykiety operacji → ikony z zamówienia
        for pattern, code in (('Dodaj obronę przeciwrakietową', 'defense'), ('Wzmocnij obronę', 'defensePlus'), ('Zmień nazwę', 'rename'), ('Zmień lokalizację', 'move'),
                              ('Reorganizuj', 'reorganize'), ('(Wycofaj|Anuluj przemarsz)', 'withdraw'), ('Zlikwiduj', 'liquidate'), ('Rozbuduj', 'upgrade')):
            self.assertIn(f"[/^{pattern}/,'{code}']", military)
        self.assertIn("label='Wzmocnij obronę przeciwrakietową'", military)
        # bazy, kopalnie, fabryki, elektrownie, lotniska, okręty, obrona, miasta
        for kind in ("objectMenu('mine',mine)", "objectMenu('factory',factory)", "objectMenu('power',plant)", "objectMenu('airport',airport)", "objectMenu('base',base)",
                     "objectMenu('vessel',vessel", "objectMenu('defense'", "objectMenu('city'", "if(menu)objectMenu(kind,item)"):
            self.assertIn(kind, military)
        self.assertNotIn('marker.bindPopup(content).openPopup()', military)
        # zamykanie kliknięciem poza obiektem i opcjami, Esc; animacja otwarcia
        self.assertIn("document.addEventListener('click',outsideClick,true)", radial)
        self.assertIn("event.key==='Escape'", radial)
        self.assertIn('.radial-menu.is-open', css)
        self.assertIn('transition:transform', css)
        self.assertIn('color:#000', css)
        self.assertIn('-1px -1px 0 #fff', css)
        land = (ROOT / 'static/js/game_land_war.js').read_text()
        self.assertIn("api.menu?.(`army:${army.id}`", land)
        self.assertIn('window.GameRadialMenu?.follow(`army:${army.id}`', land)
