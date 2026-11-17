"""Local Leaflet city-marker regression; no accounts, DB or remote assets.

Uses the same browser environment and Leaflet files as world_relief.py.
"""
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[2]
metadata={
    '1':dict(name='Capital',population=20000,capital=True),
    '2':dict(name='Metropolis',population=8000000),
    '3':dict(name='Large city',population=2000000),
    '4':dict(name='Eastfield',population=100000),
    '5':dict(name='Nearby town',population=30000),
    '6':dict(name='<img src=x onerror="window.badCity=true">',population=70000),
}
points=[(1,0,0),(2,250,0),(3,500,0),(4,750,0),(5,20,0),(6,850,-180),(99,100,0)]
geo={'type':'FeatureCollection','features':[
    dict(type='Feature',properties={'miasto_id':id},geometry={'type':'Point','coordinates':[x,y]}) for id,x,y in points
]}
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,args=['--no-sandbox'],
        **({'executable_path':os.environ['RELIEF_BROWSER']} if os.environ.get('RELIEF_BROWSER') else {}))
    page=browser.new_page(viewport={'width':1200,'height':850})
    errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    page.set_content('<div id="map" style="width:1100px;height:700px;background:#f9edb3"></div>')
    page.add_style_tag(path='/tmp/industry-leaflet.css')
    page.add_style_tag(path=str(ROOT/'static/css/game_world.css'))
    page.add_script_tag(path='/tmp/industry-leaflet.js')
    page.add_script_tag(path=str(ROOT/'static/js/world_city_markers.js'))
    page.route('**/map-city.svg',lambda route:route.fulfill(path=str(ROOT/'static/icons/map-city.svg')))
    page.route('**/map-capital.svg',lambda route:route.fulfill(path=str(ROOT/'static/icons/map-capital.svg')))
    page.evaluate('''({geo,metadata})=>{
        window.map=L.map('map',{crs:L.CRS.Simple,minZoom:-8,maxZoom:5,zoomSnap:.25,zoomAnimation:false}).setView([0,400],-2.5);
        map.createPane('worldCities');map.getPane('worldCities').style.zIndex='600';
        window.cities=WorldCityMarkers.createLayer(L,map,geo,metadata,{
            cityIcon:'https://fixture.invalid/map-city.svg',capitalIcon:'https://fixture.invalid/map-capital.svg',
            tooltip:city=>{const box=document.createElement('div');box.textContent=city.name+' — '+city.population;return box;}
        }).addTo(map);
    }''',{'geo':geo,'metadata':metadata})
    markers=page.locator('.world-city-marker')
    assert markers.count()==2, markers.count()
    assert page.locator('.world-city-marker[title="Capital — stolica"] img').get_attribute('src').endswith('map-capital.svg')
    page.evaluate('map.setZoom(-1.5,{animate:false})')
    assert markers.count()==3, markers.count()
    page.evaluate('map.setZoom(0,{animate:false})')
    assert markers.count()==5, markers.count()
    assert page.locator('.world-city-marker[title="Nearby town"]').count()==0
    labels=page.locator('.world-city-place.has-label .world-city-label')
    assert labels.count()>=2
    assert page.locator('.world-city-label').all_text_contents().count(metadata['6']['name'])==1
    assert not page.evaluate('!!window.badCity')
    assert page.locator('.world-city-marker img').count()==markers.count()
    capital=page.locator('.world-city-marker[title="Capital — stolica"]')
    capital.hover()
    assert 'Capital — 20000' in page.locator('.world-tooltip').inner_text()
    # Visible label rectangles must not overlap one another.
    boxes=labels.evaluate_all('nodes=>nodes.map(node=>{const r=node.getBoundingClientRect();return[r.left,r.top,r.right,r.bottom]})')
    for index,a in enumerate(boxes):
        for b in boxes[index+1:]:
            assert not (a[0]<b[2] and a[2]>b[0] and a[1]<b[3] and a[3]>b[1]), (a,b)
    page.screenshot(path='/tmp/world-city-pins.png')
    page.evaluate('cities.remove();map.setView([0,50],2,{animate:false})')
    assert markers.count()==0
    page.evaluate('cities.addTo(map)')
    assert page.locator('.world-city-marker[title="Nearby town"]').count()==1
    assert page.locator('.world-city-marker[title="Capital — stolica"]').count()==1
    assert not errors,errors
    print('City pins: capital priority, zoom detail, collision-free labels, tooltip, safe names and toggle passed.')
    browser.close()
