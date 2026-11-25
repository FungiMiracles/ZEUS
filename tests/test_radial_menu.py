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

    def test_region_row_and_red_attack_options(self):
        """Region — opcje w rzędzie; panel wojenny — opcje ataku w kole (czerwone ikony) dla miasta, bazy, okrętu, lotniskowca, statku handlowego i armii wroga."""
        military = (ROOT / 'static/js/game_military.js').read_text()
        radial = (ROOT / 'static/js/game_radial_menu.js').read_text()
        css = (ROOT / 'static/css/game_radial_menu.css').read_text()
        land = (ROOT / 'static/js/game_land_war.js').read_text()
        radar = (ROOT / 'static/js/game_radar.js').read_text()
        self.assertIn("{layout:'row'}", military)
        self.assertIn("if(!regionMenu(id,event.latlng))revealManagement();", military)
        for text in ("defenseActions('region',Number(id),sink)", "button('Rozmieść bazę',()=>deployDialog(id),sink", 'window.GameRadar?.buildButton?.(id,sink)', 'else attackButtons(String(id),sink)'):
            self.assertIn(text, military)
        self.assertIn('buildButton(regionId,actions)', radar)
        self.assertIn("const ATTACK_TARGETS=['base','vessel','shipment'];", military)
        self.assertIn("if(config.mode==='war'&&!mine&&(ATTACK_TARGETS.includes(kind)||kind==='city'))attackButtons(String(selected),sink);", military)
        self.assertIn("objectMenu('shipment'", military)
        self.assertIn("objectMenu('vessel',{...vessel,regionId}", military)
        self.assertIn("tone:'attack'", military)
        self.assertIn("'Wystrzel rakiety z głowicą nuklearną z silosu':'Wystrzel rakietę nuklearną'", military)
        self.assertIn("api.menu?.(`army:${army.id}`,marker.getLatLng(),parent=>attackMethods(army,parent)", land)
        self.assertIn("button.classList.add('is-'+item.tone)", radial)
        self.assertIn("layout==='row'", radial)
        self.assertIn('background-color:#c62828', css)
        self.assertIn('mask:var(--glyph)', css)

    def test_infrastructure_and_industry_options_on_the_map(self):
        """Infrastruktura: rząd jasnoniebieskich ikon po kliknięciu regionu, bez prawego panelu, widok na kraj gracza;
        fabryki, kopalnie, elektrownie: przyciski z dymków w kole dookoła obiektu."""
        template = (ROOT / 'templates/game/infrastructure.html').read_text()
        infra = (ROOT / 'static/js/game_infrastructure.js').read_text()
        industry = (ROOT / 'static/js/game_industry.js').read_text()
        css = (ROOT / 'static/css/game_radial_menu.css').read_text()
        self.assertNotIn('infrastructure-details', template)
        self.assertNotIn('infrastructure-region-select', template)
        self.assertIn('data-infrastructure-region="{{ id }}"', template)
        self.assertLess(template.index('js/game_radial_menu.js'), template.index('js/game_infrastructure.js'))
        self.assertIn("tone: 'infra'", infra)
        self.assertIn("layout: 'row'", infra)
        self.assertIn('for (const id of metropolitanIds)', infra)
        self.assertIn('.is-infra .radial-menu-glyph{background-color:#3fa7e6}', css)
        self.assertNotIn('.bindPopup(objectActions(object)', industry)
        self.assertIn('bindObject(marker,object)', industry)
        self.assertIn('window.GameRadialMenu.open(map,marker.getLatLng(),items', industry)
        self.assertIn('function homeBounds()', industry)
        self.assertIn("pending.count=n", industry)
