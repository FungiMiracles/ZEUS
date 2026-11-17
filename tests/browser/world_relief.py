"""Canvas relief regression with real Leaflet; local assets, no accounts or DB.

PYTHONPATH=/tmp/zeus-browser python3 tests/browser/world_relief.py
Optional --world uses /tmp/world_relief_metadata.json for a real-world preview.
"""
import json
import os
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
types = ['Wysokogórski', 'Górski', 'Pogórski', 'Wyżynny', 'Nizinny', 'Depresyjny']
features = []
for index in range(len(types)):
    x = index * 250
    rings = [[[x, 0], [x + 250, 0], [x + 250, -400], [x, -400], [x, 0]]]
    if index == 0:
        rings.append([[60, -60], [110, -60], [110, -110], [60, -110], [60, -60]])
    features.append({'type': 'Feature', 'properties': {'region_id': index}, 'geometry': {'type': 'Polygon', 'coordinates': rings}})
geo = {'type': 'FeatureCollection', 'features': features}
metadata = {str(i): {'terrain': name} for i, name in enumerate(types)}
world = '--world' in sys.argv
if world:
    geo = json.loads((ROOT / 'static/maps/entenda_regiony.geojson').read_text())
    metadata = json.loads(Path('/tmp/world_relief_metadata.json').read_text())

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=['--no-sandbox'],
                                **({'executable_path': os.environ['RELIEF_BROWSER']} if os.environ.get('RELIEF_BROWSER') else {}))
    page = browser.new_page(viewport={'width': 1400, 'height': 950}, device_scale_factor=1)
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.set_content('<div id="map" style="width:1380px;height:900px;background:#234864"></div>')
    page.add_style_tag(path='/tmp/industry-leaflet.css')
    page.add_script_tag(path='/tmp/industry-leaflet.js')
    page.add_script_tag(path=str(ROOT / 'static/js/world_relief.js'))
    result = page.evaluate('''({geo, metadata}) => {
        const started = performance.now();
        const map = window.map = L.map('map', {crs:L.CRS.Simple,minZoom:-8,maxZoom:5,zoomSnap:.25,fadeAnimation:false});
        const land = L.geoJSON(geo,{coordsToLatLng:p=>L.latLng(p[1],p[0]),style:{fillColor:'#b8c9b0',fillOpacity:1,color:'#667c63',weight:.7}}).addTo(map);
        map.createPane('worldRelief');map.getPane('worldRelief').style.zIndex='415';map.getPane('worldRelief').style.pointerEvents='none';
        map.fitBounds(land.getBounds(),{padding:[20,20]});
        window.relief=WorldRelief.createLayer(L,geo,metadata).addTo(map);
        return {ms:performance.now()-started,polygons:WorldRelief.prepare(geo,metadata).length};
    }''', {'geo': geo, 'metadata': metadata})
    page.screenshot(path='/tmp/world-relief-world.png' if world else '/tmp/world-relief-profiles.png')
    assert result['polygons'] > 0
    assert page.locator('.leaflet-worldRelief-pane canvas').count() > 0
    if not world:
        continuity = page.evaluate('''({geo,metadata})=>{
            const sample=WorldRelief.createModel(WorldRelief.prepare(geo,metadata));
            return {before:sample(249.99,200).height,after:sample(250.01,200).height,
                mountain:sample(150,200).height,lowland:sample(1125,200).height,
                shore:sample(200,0).height,nearShore:sample(200,10).height,
                inland:sample(200,120).height,sea:sample(200,-20).height,
                shared:WorldRelief.elevation(250,200,sample(250,200))};
        }''', {'geo':geo,'metadata':metadata})
        assert abs(continuity['before'] - continuity['after']) < .2, continuity
        assert continuity['mountain'] > continuity['lowland'] * 4, continuity
        assert continuity['shore'] < .1, continuity
        assert continuity['sea'] == 0, continuity
        assert continuity['nearShore'] < continuity['inland'] * .1, continuity
        ink = page.evaluate('''()=>{
            let maximum=0,colored=0,visible=0;
            for(const tile of Object.values(relief._tiles)) {
                const data=tile.el.getContext('2d').getImageData(0,0,tile.el.width,tile.el.height).data;
                for(let i=0;i<data.length;i+=4)if(data[i+3]){
                    maximum=Math.max(maximum,data[i+3]);visible++;
                    if(data[i]||data[i+1]||data[i+2])colored++;
                }
            }
            return{maximum,colored,visible};
        }''')
        assert ink['visible'] > 0 and ink['maximum'] <= 72, ink
        assert ink['colored'] == 0, ink
        # Holes and sea stay transparent. A map movement must produce new tiles.
        def alpha(x, y):
            return page.evaluate('''([x,y])=>{
                const point=map.project([y,x],relief._tileZoom);const size=256;
                const tx=Math.floor(point.x/size),ty=Math.floor(point.y/size);
                const tile=relief._tiles[`${tx}:${ty}:${relief._tileZoom}`]?.el;
                if(!tile)return 0;
                return tile.getContext('2d').getImageData(Math.floor((point.x-tx*size)*tile.width/size),Math.floor((point.y-ty*size)*tile.height/size),1,1).data[3];
            }''', [x, y])
        assert alpha(85, -85) == 0, 'lake hole painted'
        assert alpha(150, -150) > 0, 'mountain missing'
        page.evaluate('map.setView([-200,500],2,{animate:false})')
        assert page.locator('.leaflet-worldRelief-pane canvas').count() > 0
        page.evaluate('relief.remove()')
        assert page.locator('.leaflet-worldRelief-pane canvas').count() == 0
        page.evaluate('relief.addTo(map)')
        assert page.locator('.leaflet-worldRelief-pane canvas').count() > 0
    assert not errors, errors
    print('Relief browser checks passed:', result)
    if not world:
        # Exercise the production world screen, including all map modes and toggle.
        page = browser.new_page(viewport={'width': 1200, 'height': 850})
        page.on('pageerror', lambda error: errors.append(str(error)))
        config = dict(regions=metadata, countries={}, cities={}, occupied={}, continents={}, ships=[], vessels=[],
                      countriesUrl='https://fixture.invalid/countries', regionsUrl='https://fixture.invalid/regions',
                      citiesUrl='https://fixture.invalid/cities', gameNow='2990-01-01T00:00:00Z')
        page.set_content('<div id="world-map" style="width:1100px;height:700px"></div>'
                         '<div id="world-map-status" hidden></div><span class="legend-regional"></span>'
                         '<span class="legend-cities"></span><input type="checkbox" id="world-cities-toggle" checked>'
                         '<input type="checkbox" id="world-relief-toggle" checked><button id="world-map-reset"></button>'
                         + ''.join(f'<input type="radio" name="world-view" value="{name}">' for name in ('political', 'regional', 'continents'))
                         + '<script id="world-config" type="application/json">' + json.dumps(config) + '</script>')
        page.route('**/countries', lambda route: route.fulfill(json=geo))
        page.route('**/regions', lambda route: route.fulfill(json=geo))
        page.route('**/cities', lambda route: route.fulfill(json={'type': 'FeatureCollection', 'features': []}))
        page.add_style_tag(path='/tmp/industry-leaflet.css')
        page.add_script_tag(path='/tmp/industry-leaflet.js')
        page.add_script_tag(path=str(ROOT / 'static/js/world_relief.js'))
        page.add_script_tag(path=str(ROOT / 'static/js/game_world.js'))
        page.wait_for_selector('.leaflet-worldRelief-pane canvas')
        for view in ('political', 'regional', 'continents'):
            page.check(f'[name="world-view"][value="{view}"]')
            assert page.locator('.leaflet-worldRelief-pane canvas').count() > 0
        page.uncheck('#world-relief-toggle')
        assert page.locator('.leaflet-worldRelief-pane canvas').count() == 0
        page.check('#world-relief-toggle')
        page.wait_for_selector('.leaflet-worldRelief-pane canvas')
        assert page.evaluate("getComputedStyle(document.querySelector('.leaflet-worldRelief-pane')).pointerEvents") == 'none'
        assert not errors, errors
        print('Production world screen: all three views, terrain toggle and pointer pass-through passed.')
    browser.close()
