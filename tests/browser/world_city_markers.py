"""Local Leaflet regression: overview dots and population-scaled urban plans.
Uses the same local browser environment and Leaflet files as world_relief.py.
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
    page.evaluate('''({geo,metadata})=>{
        window.map=L.map('map',{crs:L.CRS.Simple,minZoom:-8,maxZoom:5,zoomSnap:.25,zoomAnimation:false}).setView([0,400],-2.5);
        map.createPane('worldCities');map.getPane('worldCities').style.zIndex='600';
        window.cityTip=city=>{const box=document.createElement('div');box.textContent=city.name+' — '+city.population;return box;};
        window.cities=WorldCityMarkers.createLayer(L,map,geo,metadata,{tooltip:cityTip}).addTo(map);
    }''',{'geo':geo,'metadata':metadata})
    dots=page.locator('.world-city-dot');areas=page.locator('.world-city-footprint')
    assert dots.count()==5 and areas.count()==0, (dots.count(),areas.count())
    assert page.locator('.world-city-dot.is-capital').count()==1
    page.evaluate('map.setZoom(-1,{animate:false})')
    assert areas.count()==2 and dots.count()>0, (dots.count(),areas.count())
    page.evaluate('map.setZoom(0,{animate:false})')
    assert areas.count()==6 and dots.count()==0, (dots.count(),areas.count())
    labels=page.locator('.world-city-label')
    assert labels.count()>=2
    assert page.locator('.world-city-footprint[data-city-id="6"] title').text_content()==metadata['6']['name']
    assert not page.evaluate('!!window.badCity')
    assert page.locator('.world-city-footprint rect').count()>40
    page.locator('.world-city-footprint[data-city-id="1"]').hover()
    assert 'Capital — 20000' in page.locator('.world-tooltip').inner_text()
    sizes=page.evaluate('''()=>{
        const pops=[100000,101000,1000000,8000000];
        const forms=pops.map((pop,i)=>WorldCityMarkers.footprint('city-'+i,pop));
        const exact=forms.map(form=>Math.abs(form.outline.reduce((sum,p,i)=>{
            const next=form.outline[(i+1)%form.outline.length];return sum+p[0]*next[1]-next[0]*p[1];
        },0))/2*form.radius*form.radius);
        const perimeter=pop=>{const outline=WorldCityMarkers.footprint('same-city',pop).outline;
            return outline.reduce((sum,p,i)=>{const next=outline[(i+1)%outline.length];return sum+Math.hypot(p[0]-next[0],p[1]-next[1]);},0);};
        return{areas:forms.map(f=>f.area),exact,repeat:JSON.stringify(WorldCityMarkers.footprint('a',1e6))===JSON.stringify(WorldCityMarkers.footprint('a',1e6)),
            distinct:JSON.stringify(WorldCityMarkers.footprint('a',1e6).outline)!==JSON.stringify(WorldCityMarkers.footprint('b',1e6).outline),
            compact:perimeter(20000),sprawling:perimeter(8000000)};
    }''')
    assert all(a<b for a,b in zip(sizes['areas'],sizes['areas'][1:])),sizes
    assert all(abs(a-b)<1e-6 for a,b in zip(sizes['areas'],sizes['exact'])),sizes
    assert sizes['repeat'] and sizes['distinct'],sizes
    assert sizes['sprawling']>sizes['compact'],sizes
    boxes=labels.evaluate_all('nodes=>nodes.map(node=>{const r=node.getBoundingClientRect();return[r.left,r.top,r.right,r.bottom]})')
    for index,a in enumerate(boxes):
        for b in boxes[index+1:]:
            assert not (a[0]<b[2] and a[2]>b[0] and a[1]<b[3] and a[3]>b[1]),(a,b)
    page.screenshot(path='/tmp/world-city-footprints.png')
    page.evaluate('cities.remove();map.setView([0,50],2,{animate:false})')
    assert areas.count()==0 and dots.count()==0 and labels.count()==0
    page.evaluate('cities.addTo(map)')
    assert page.locator('.world-city-footprint[data-city-id="5"]').count()==1
    page.evaluate('map.setView([0,400],-2.5,{animate:false})')
    assert areas.count()==0 and dots.count()==5
    # An urban silhouette centered on a coastline must not paint the sea.
    page.evaluate('''({geo,metadata})=>{
        cities.remove();map.setView([0,750],2,{animate:false});
        const land={type:'FeatureCollection',features:[{type:'Feature',geometry:{type:'Polygon',
            coordinates:[[[0,150],[750,150],[750,-350],[0,-350],[0,150]]]},properties:{}}]};
        window.cities=WorldCityMarkers.createLayer(L,map,geo,metadata,{land,tooltip:cityTip}).addTo(map);
    }''',{'geo':geo,'metadata':metadata})
    clipping=page.evaluate('''async()=>{
        const original=document.querySelector('.world-city-footprint[data-city-id="4"]'),svg=original.cloneNode(true);
        svg.removeAttribute('style');const box=svg.viewBox.baseVal,w=256,h=Math.round(w*box.height/box.width),cut=-box.x/box.width*w;
        svg.setAttribute('width',w);svg.setAttribute('height',h);
        const image=new Image();image.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(new XMLSerializer().serializeToString(svg));await image.decode();
        const canvas=document.createElement('canvas');canvas.width=w;canvas.height=h;const ctx=canvas.getContext('2d');ctx.drawImage(image,0,0,w,h);
        const data=ctx.getImageData(0,0,w,h).data;let land=0,sea=0;
        for(let y=0;y<h;y++)for(let x=0;x<w;x++)if(data[(y*w+x)*4+3]){if(x<cut-3)land++;if(x>cut+3)sea++;}
        return{land,sea};
    }''')
    assert clipping['land']>0 and clipping['sea']==0,clipping
    assert not errors,errors
    print('Cities: overview dots, unique population-scaled footprints, street blocks, coastal clipping, labels, tooltip and toggle passed.')
    browser.close()
