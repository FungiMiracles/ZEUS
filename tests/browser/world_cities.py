"""Standalone Playwright regression for city/capital toggle transitions.

Uses public static geometry and synthetic metadata; no login or database.
"""
import sys,re,json
from pathlib import Path
from playwright.sync_api import sync_playwright
root=Path(__file__).resolve().parents[2];template=(root/'templates/mapy_swiata.html').read_text();base=(root/'templates/base_layout.html').read_text()
geo=json.loads((root/'static/maps/entenda_miasta.geojson').read_text())
meta={str(f['properties']['miasto_id']):dict(nazwa='City',populacja=100000,czy_stolica=i<2) for i,f in enumerate(geo['features'])}
functions=template[template.index('function loadCities()'):template.index('function selectCity(')]+template[template.index('function clearCityLabels()'):template.index('function loadRegionTypes()')]
functions=functions.replace('/api/miasta_meta','https://fixture.invalid/api/miasta_meta')
functions=re.sub(r'\{\{.*?\}\}','https://fixture.invalid/cities.geojson',functions)
listeners=template[template.index('document.getElementById("toggleCities").addEventListener'):template.index('document\n.getElementById("kontynentSelect")')]
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True,args=['--no-sandbox']);page=browser.new_page(viewport={'width':1200,'height':900});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 page.set_content('<div id="map" style="width:1100px;height:700px"></div><input type="checkbox" id="toggleCities"><input type="checkbox" id="toggleCapitalsOnly">')
 for text in [re.search(r'<style>(.*?)</style>',base,re.S)[1],re.search(r'<style>(.*?)</style>',template,re.S)[1]]:page.add_style_tag(content=text)
 page.add_style_tag(url='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css');page.add_script_tag(url='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js')
 page.route('**/cities.geojson',lambda route:route.fulfill(json=geo));page.route('**/api/miasta_meta',lambda route:route.fulfill(json=meta))
 page.add_script_tag(content="const map=L.map('map',{crs:L.CRS.Simple,minZoom:-5,maxZoom:4}).setView([-1700,1000],0);map.createPane('worldCities');map.getPane('worldCities').style.zIndex='460';let cityLayer=null,cityLoadRevision=0,selectedCityLayer=null,citiesVisible=false,capitalsOnly=false,cityMetaMap={};"+functions+listeners)
 page.check('#toggleCities');page.wait_for_function("document.querySelectorAll('.leaflet-worldCities-pane path').length > 2");print('all cities',page.locator('.leaflet-worldCities-pane path').count(),'errors',errors)
 page.check('#toggleCapitalsOnly');page.wait_for_function("document.querySelectorAll('.leaflet-worldCities-pane path').length === 2");print('capitals',page.locator('.leaflet-worldCities-pane path').count(),'errors',errors)
 page.uncheck('#toggleCities');assert page.locator('.leaflet-worldCities-pane path').count()==0;page.check('#toggleCities');page.wait_for_function("document.querySelectorAll('.leaflet-worldCities-pane path').length > 2");print('all again',page.locator('.leaflet-worldCities-pane path').count(),'errors',errors);assert page.locator('.leaflet-worldCities-pane path').count()==sum(1 for feature in geo['features'] if feature.get('geometry'));assert not page.is_checked('#toggleCapitalsOnly');assert not errors
 browser.close()
