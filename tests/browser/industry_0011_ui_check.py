import sys,json
from pathlib import Path
from urllib.parse import urlsplit,unquote
root=Path(__file__).resolve().parents[2];sys.path[:0]=[str(root),str(root/'tests')]
from test_industry_0011 import IndustryTests
from extensions import db
from game.research_models import ResearchAccount
from game.industry_models import PowerPlant
from playwright.sync_api import sync_playwright,expect
case=IndustryTests();case.setUp()
from models import Region
db.session.get(Region,1).region_polozenie_id=2;db.session.commit()
case.app.url_build_error_handlers.append(lambda error,endpoint,values:'/stub/'+endpoint)
case.app.context_processor(lambda:{'game_csrf_token':'token','ENV_NAME':'UAT'})
from flask import render_template
from game.models import GameUser
from models import Panstwo
from game.country_summary import country_summary
def dashboard():
    return render_template('game/game_main_page.html',game_user=db.session.get(GameUser,1),game_country={'id':1,'nazwa':'Państwo testowe','skrot':'T','flaga':'','populacja':None,'pkb':None,'pkb_per_capita':None,'infrastruktura':None},game_home_url='/test/game_main_page',game_logout_url='/stub/logout',game_region_names={},game_city_data={},warehouse_items=[{'label':'Żelazo','icon':'/static/icons/ŻELAZO.svg','quantity':10**29-1},*({'label':'Węgiel kamienny','icon':'/static/icons/WEGIEL.svg','quantity':123456789012345+i} for i in range(14))])
case.app.view_functions['game_main_page']=dashboard
geo={'type':'FeatureCollection','features':[{'type':'Feature','properties':{'region_id':1,'panstwo_id':1},'geometry':{'type':'Polygon','coordinates':[[[0,0],[100,0],[100,100],[0,100],[0,0]]]}}]}
try:
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
        page=browser.new_page(viewport={'width':1440,'height':1000});errors=[];bad=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        def serve(route):
            request=route.request;url=urlsplit(request.url);path=unquote(url.path)
            if url.hostname=='unpkg.com':
                return route.fulfill(path='/tmp/industry-'+path.rsplit('/',1)[-1])
            if url.hostname!='industry.test':return route.abort()
            if path.startswith('/static/maps/') or path=='/wiki/mapa/panstwa.geojson':
                return route.fulfill(json=geo if 'regiony' in path or 'panstwa' in path else {'type':'FeatureCollection','features':[]})
            if path.startswith('/static/'):
                file=root/path.lstrip('/')
                return route.fulfill(path=str(file)) if file.is_file() else route.fulfill(status=404,body='')
            if path.startswith('/game/obrona-panstwa/wybrzeze/'):
                return route.fulfill(json={'segments':[[[0,0],[100,0]]],'widthKm':3})
            if path.startswith('/stub/'):return route.fulfill(json={'items':[]})
            try:
                response=case.client.open(path+('?' + url.query if url.query else ''),method=request.method,data=request.post_data,headers={k:v for k,v in request.headers.items() if k.lower() in ['content-type','x-csrf-token']})
            except Exception as e:
                bad.append((path,str(e)));raise
            if response.status_code>=500:bad.append((path,response.status_code))
            route.fulfill(status=response.status_code,body=response.data,content_type=response.content_type)
        page.route('**/*',serve)
        page.goto('https://industry.test/test/game_main_page')
        for width in [1440,390]:
            page.set_viewport_size({'width':width,'height':1000});page.wait_for_timeout(200)
            cards=page.locator('.warehouse-item').evaluate_all('(nodes)=>nodes.map(n=>({w:n.getBoundingClientRect().width,h:n.getBoundingClientRect().height}))')
            assert max(n['w'] for n in cards)-min(n['w'] for n in cards)<1,(width,cards)
            assert max(n['h'] for n in cards)-min(n['h'] for n in cards)<1,(width,cards)
            numbers=page.locator('.warehouse-item strong').evaluate_all('(nodes)=>nodes.map(n=>({nowrap:getComputedStyle(n).whiteSpace,overflow:n.scrollWidth>n.clientWidth+1}))')
            assert all(n['nowrap']=='nowrap' and not n['overflow'] for n in numbers),(width,numbers)
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),('warehouse overflow',width)
        row=db.session.get(ResearchAccount,1);saved=dict(row.nodes);row.nodes={**saved,'method':7};db.session.commit()
        page.goto('https://industry.test/game/badania')
        page.locator('[data-node=method]').click();expect(page.locator('#research-count')).to_have_value('18');expect(page.locator('#research-description img')).to_have_attribute('src','/static/icons/PUNKT%20ROZWOJU.svg');page.locator('#research-close').click()
        page.locator('[data-node=mine_iron]').hover();expect(page.locator('#research-hover-tooltip')).to_contain_text('Opracowano');expect(page.locator('#research-hover-tooltip img')).to_have_count(0)
        row=db.session.get(ResearchAccount,1);row.nodes=saved;db.session.commit();page.reload()
        expect(page.locator('.research-node[data-node]')).to_have_count(35)
        page.locator('[data-node="mine_iron"]').click();expect(page.locator('#research-dialog-title')).to_have_text('Wydobycie żelaza');expect(page.locator('#research-description')).to_contain_text('75');page.locator('#research-close').click()
        page.set_viewport_size({'width':1440,'height':1000})
        mine_id=case.mine();case.operation(kind='tanks');case.add_stock('zelazo',7);case.add_stock('ropa_naftowa',9);db.session.expire_all()
        page.goto('https://industry.test/game/infrastruktura')
        page.locator('#infrastructure-tab-factories').click()
        expect(page.locator('#industry-build-cards .industry-build-card')).to_have_count(8);expect(page.locator('#industry-build-cards .industry-product-badge')).to_have_count(8)
        boxes=page.locator('#industry-build-cards .industry-build-card').evaluate_all('(nodes)=>nodes.map(n=>{const b=n.getBoundingClientRect();return {y:b.y,w:b.width}})')
        assert len(boxes)==8 and max(b['y'] for b in boxes)-min(b['y'] for b in boxes)<1,boxes
        gridwidth=page.locator('#industry-build-cards').bounding_box()['width']
        assert all(b['w']<=gridwidth/10 for b in boxes),boxes
        page.locator('#industry-records .industry-card').hover()
        shortage=page.locator('#industry-records .industry-shortage-tooltip');expect(shortage).to_be_visible();expect(shortage.locator('img')).to_have_count(2);expect(shortage.get_by_alt_text('Żelazo').locator('..').locator('strong')).to_have_text('3');expect(shortage.get_by_alt_text('Prosty chip').locator('..').locator('strong')).to_have_text('1')
        page.locator('#factory-map .industry-map-symbol').hover()
        expect(page.locator('.industry-object-popup .industry-missing-inputs img')).to_have_count(2)
        expect(page.locator('.industry-object-popup .industry-missing-inputs').get_by_alt_text('Żelazo').locator('..').locator('strong')).to_have_text('3')
        page.locator('.leaflet-popup-close-button').click()
        page.locator('.industry-build-card[data-kind=shipyard] button',has_text='Buduj').click()
        expect(page.locator('#factory-map .game-coast-band')).to_have_count(1)
        page.locator('#factory-map path.leaflet-interactive').click();expect(page.locator('#industry-confirm')).not_to_be_visible();expect(page.locator('#industry-placement')).to_contain_text('tylko na zielonym pasie')
        bounds=page.locator('#factory-map path.leaflet-interactive').bounding_box();page.mouse.click(bounds['x']+bounds['width']/2,bounds['y']+bounds['height']*.99)
        expect(page.locator('#industry-confirm')).to_be_visible();page.locator('#industry-close').click();page.locator('#industry-cancel').click();expect(page.locator('#factory-map .game-coast-band')).to_have_count(0)

        page.locator('#infrastructure-tab-mines').click();expect(page.locator('#industry-build-cards .industry-build-card')).to_have_count(10);expect(page.locator('.mine-build-symbol')).to_have_count(10);expect(page.locator('.industry-build-card[data-kind=wegiel_kamienny] .industry-build-parameters')).to_be_visible();expect(page.locator('.industry-build-card[data-kind=wegiel_kamienny] .industry-build-time img')).to_have_attribute('src','/static/icons/CZAS.svg?v=20261108-ui2');page.locator('#factory-map path.leaflet-interactive').hover();expect(page.locator('.industry-deposit-tooltip')).to_contain_text('Węgiel kamienny3')
        expect(page.locator('#industry-records .industry-build-progress progress')).to_have_count(1);expect(page.locator('#industry-records .industry-product-badge')).to_have_count(1)
        page.locator('#infrastructure-tab-power').click();expect(page.locator('#industry-build-cards .industry-build-card')).to_have_count(4)
        row=db.session.get(ResearchAccount,1);complete_nodes=dict(row.nodes);row.nodes={key:value for key,value in row.nodes.items() if key!='power_nuclear'};db.session.commit()
        page.reload()
        locked=page.locator('.industry-build-card[data-kind=nuclear]');expect(locked).to_have_class('industry-build-card technology-locked');expect(locked.get_by_role('button',name='Buduj')).to_have_count(0)
        locked.hover();expect(locked.locator('[role=tooltip]')).to_be_visible();expect(locked.locator('[role=tooltip]')).to_contain_text('najpierw rozwiń technologię Elektrownia atomowa')
        row=db.session.get(ResearchAccount,1);row.nodes=complete_nodes;db.session.commit()
        expect(page.locator('.energy-summary-row')).to_have_count(2);expect(page.locator('#industry-budget')).to_contain_text('MLD')
        expect(page.locator('.energy-summary-row').first).to_contain_text('0,0 e/dzień')
        page.locator('.industry-build-card[data-kind=solar] button',has_text='Buduj').click()
        expect(page.locator('#industry-confirm')).not_to_be_visible()
        page.locator('#factory-map path.leaflet-interactive').click();expect(page.locator('#industry-confirm')).to_be_visible();expect(page.locator('#industry-confirm-icon')).to_have_attribute('src','/static/icons/ELEKTROWNIA%20S%C5%81ONECZNA.svg');page.locator('#industry-apply').click()
        expect(page.locator('#industry-records')).to_contain_text('Elektrownia słoneczna')
        expect(page.locator('#industry-energy')).to_contain_text('12,0')
        expect(page.locator('#industry-stability')).to_contain_text('Dzienna produkcja: 12,0 e');expect(page.locator('#industry-stability')).not_to_contain_text('Dzienne zużycie')
        panels=page.locator('.industry-energy-panels>.game-panel').evaluate_all('(nodes)=>nodes.map(n=>n.getBoundingClientRect().height)');assert abs(panels[0]-panels[1])<1
        cards=page.locator('.industry-build-card').evaluate_all('(nodes)=>nodes.map(n=>n.getBoundingClientRect().y)');assert max(cards)-min(cards)<1
        page.locator('#factory-map .industry-map-symbol').hover();expect(page.locator('.industry-object-popup')).to_be_visible();expect(page.locator('.industry-object-popup button',has_text='Rozbuduj')).to_be_visible();page.locator('.industry-object-popup button',has_text='Likwiduj').click()
        expect(page.locator('#industry-confirm-text')).to_contain_text('12,5')
        page.locator('#industry-close').click()
        for width in [1440,390]:
            page.set_viewport_size({'width':width,'height':1000});page.screenshot(path=f'/tmp/industry-ui2-{width}.png',full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),('infrastructure overflow',width)
        page.goto('https://industry.test/game/badania')
        for width in [1440,390]:
            page.set_viewport_size({'width':width,'height':1000})
            page.wait_for_timeout(200)
            boxes=page.locator('.technology-radial [data-node]').evaluate_all('(nodes)=>nodes.map(n=>{const b=n.getBoundingClientRect();return {x:b.x,y:b.y,w:b.width,h:b.height,key:n.dataset.node}})')
            for i,a in enumerate(boxes):
                for b in boxes[i+1:]:assert not(a['x']<b['x']+b['w']-1 and a['x']+a['w']>b['x']+1 and a['y']<b['y']+b['h']-1 and a['y']+a['h']>b['y']+1),(width,a,b)
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),('research overflow',width)
            expect(page.locator('.technology-complete')).to_have_count(33)
            page.screenshot(path=f'/tmp/research-ui2-{width}.png',full_page=True)
        page.goto('https://industry.test/game/handel')
        for width in [1440,390]:
            page.set_viewport_size({'width':width,'height':1000})
            expect(page.locator('#trade-cargo-fields label')).to_have_count(23)
            box=page.locator('.trade-sell-panel').bounding_box();mapbox=page.locator('.trade-map-panel').bounding_box()
            assert box['y']+box['height']<=mapbox['y']+1
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),('trade overflow',width)
            page.screenshot(path=f'/tmp/trade-ui2-{width}.png',full_page=True)
        # The 'Surowce naturalne' module was removed (10 Nov 2026); mines are built in Infrastruktura i energetyka.
        assert page.goto('https://industry.test/game/surowce-naturalne').status==404
        page.goto('https://industry.test/game/obrona-panstwa');expect(page.locator('[data-map-filter=power]')).to_contain_text('Elektrownie')
        page.locator('[data-map-filter=power]').click();page.locator('[data-map-filter=power]').click();expect(page.locator('.military-power-symbol>.map-health-bar')).to_have_count(1);expect(page.locator('.military-power-symbol .military-health')).to_have_count(0);assert page.locator('.military-power-symbol').evaluate('(el)=>getComputedStyle(el).borderTopColor')=='rgb(0, 0, 0)'
        page.locator('.military-power-symbol').click()
        expect(page.locator('#military-power-1')).to_be_visible();expect(page.locator('#military-power-1')).to_have_class('military-base military-power-card military-object-selected')
        expect(page.locator('#military-power-1 .military-health span')).to_have_count(0)
        page.locator('#military-power-1').get_by_role('button',name='Dodaj obronę przeciwrakietową').click()
        expect(page.locator('#military-dialog')).to_be_visible();page.locator('#military-dialog-confirm').click()
        expect(page.locator('#military-power-1')).to_contain_text('Obrona: poziom 1')
        assert not errors,errors
        assert not bad,bad
        browser.close()
    print('PASS: coastal shipyard band+placement rejection, map action popup, compact cards, power selection+missile-defense installation, warehouse/research/trade desktop+mobile')
finally:case.tearDown()
