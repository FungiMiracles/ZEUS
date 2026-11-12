"""Standalone Playwright regression: real Leaflet + WIKI CSS, synthetic roads.

Run with a Python environment containing Playwright and installed Chromium.
No application login, database connection or production changes are required.
"""
import re
from pathlib import Path
from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parents[2]
base_css = re.search(r'<style>(.*?)</style>', (root / 'templates/base_layout.html').read_text(), re.S)[1]
map_css = re.search(r'<style>(.*?)</style>', (root / 'templates/mapy_swiata.html').read_text(), re.S)[1]
roads = {'type': 'FeatureCollection', 'features': [{
    'type': 'Feature', 'geometry': {'type': 'LineString', 'coordinates': [[1000, -1700], [1010, -1710], [1020, -1700]]},
    'properties': {'kind': 'motorway', 'id': 1, 'distanceKm': '25', 'country': 'Test'},
}]}

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
    page = browser.new_page(viewport={'width': 1200, 'height': 900})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.set_content('''<div id="map" style="width:90vw;height:70vh"></div>
        <input type="checkbox" id="toggleRoads"><div id="worldRoadsLegend" hidden></div>
        <div id="worldRoadsStatus"></div>''')
    page.add_style_tag(content=base_css)
    page.add_style_tag(url='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css')
    page.add_style_tag(content=map_css)
    page.add_script_tag(url='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js')
    page.add_script_tag(path=str(root / 'static/js/world_roads.js'))
    page.route('https://fixture.invalid/roads', lambda route: route.fulfill(json=roads))
    page.evaluate("""window.map = L.map('map', {crs:L.CRS.Simple,minZoom:-5,maxZoom:4})
        .setView([-1705,1010],3);
        window.addWorldRoadsOverlay(map,'https://fixture.invalid/roads');""")
    for width, height in [(1200, 900), (390, 844)]:
        page.set_viewport_size({'width': width, 'height': height})
        page.evaluate('map.invalidateSize()')
        page.check('#toggleRoads')
        line = page.locator('.leaflet-worldRoads-pane path')
        line.wait_for(state='visible')
        box = page.locator('.leaflet-worldRoads-pane svg').bounding_box()
        assert box['width'] > 0 and box['height'] > 0, box
        assert line.get_attribute('d') != 'M0 0'
        page.uncheck('#toggleRoads')
        assert line.count() == 0
    assert not errors, errors
    browser.close()
    print('Road overlay visible with WIKI CSS on desktop/mobile; toggling verified.')
