"""Responsive regression on isolated SQLite; no running server or UAT DB.

Requires Playwright and Chromium, plus local Leaflet assets cached as
/tmp/industry-leaflet.js and /tmp/industry-leaflet.css (same browser fixture
as industry_0011_ui_check.py). Set PYTHONPATH/PLAYWRIGHT_BROWSERS_PATH as
appropriate for the environment. Screenshots go to /tmp/mobile-*.png.
"""
import sys,json
from pathlib import Path
from urllib.parse import urlsplit,unquote
root=Path(__file__).resolve().parents[2];sys.path[:0]=[str(root),str(root/'tests')]
from test_industry_0011 import IndustryTests
from playwright.sync_api import sync_playwright
case=IndustryTests();case.setUp()
case.app.url_build_error_handlers.append(lambda error,endpoint,values:'/stub/'+endpoint)
case.app.context_processor(lambda:{'game_csrf_token':'token','ENV_NAME':'UAT'})
from flask import render_template
from extensions import db
from game.models import GameUser
def dashboard():
 return render_template('game/game_main_page.html',game_user=db.session.get(GameUser,1),game_country={'id':1,'nazwa':'Państwo testowe','skrot':'T','flaga':'','populacja':None,'pkb':None,'pkb_per_capita':None,'infrastruktura':None},game_home_url='/test/game_main_page',game_logout_url='/stub/logout',game_region_names={},game_city_data={},warehouse_items=[],game_panel={'dashboard':{'alerts':[], 'energy':None,'international':None,'industry':None},'filters':[], 'regions':{},'objects':[]})
case.app.view_functions['game_main_page']=dashboard
@case.app.route('/test/world')
def world():
 return render_template('game/world.html',game_country={'id':1,'nazwa':'Test','flaga':'','populacja':None,'pkb':None,'pkb_per_capita':None,'infrastruktura':None},game_logout_url='/stub/logout',world_config={'countries':{},'regions':{},'cities':[]})
try:
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
  page=browser.new_page()
  def serve(route):
   req=route.request;u=urlsplit(req.url);path=unquote(u.path)
   if u.hostname=='unpkg.com':return route.fulfill(path='/tmp/industry-'+path.rsplit('/',1)[-1])
   if u.hostname!='mobile.test':return route.abort()
   if path.startswith('/static/maps/') or path=='/wiki/mapa/panstwa.geojson':return route.fulfill(json={'type':'FeatureCollection','features':[]})
   if path.startswith('/static/'):
    f=root/path.lstrip('/');return route.fulfill(path=str(f)) if f.is_file() else route.fulfill(status=404,body='')
   if path.startswith('/stub/'):return route.fulfill(json={'items':[]})
   response=case.client.open(path+('?' + u.query if u.query else ''),method=req.method,data=req.post_data,headers={k:v for k,v in req.headers.items() if k.lower() in ['content-type','x-csrf-token']})
   return route.fulfill(status=response.status_code,body=response.data,content_type=response.content_type)
  page.route('**/*',serve)
  for path in ['/test/game_main_page','/game/badania','/game/infrastruktura','/test/world','/game/dyplomacja','/game/handel','/game/forum','/game/srodowisko','/game/obrona-panstwa']:
   for w,h in [(320,740),(390,844),(768,1024),(900,700),(1440,1000)]:
    page.set_viewport_size({'width':w,'height':h});response=page.goto('https://mobile.test'+path);assert response.status==200,(path,response.status);page.wait_for_timeout(250)
    overflow=page.evaluate('''() => ({width:innerWidth,scroll:document.documentElement.scrollWidth,offenders:[...document.querySelectorAll('body *')].filter(e=>{const r=e.getBoundingClientRect();return r.width&&r.right>innerWidth+2&&getComputedStyle(e).position!=='absolute'}).slice(0,10).map(e=>e.tagName+'.'+e.className)})''')
    print(path,w,json.dumps(overflow),flush=True)
    assert overflow['scroll']<=w,overflow
    if w<=900:
     # 13 Nov 2026: pasek państwa jako szuflada z zakładką; zegar po lewej stronie przycisku MENU
     tab=page.locator('#sidebar-drawer-tab');assert tab.is_visible();assert not page.locator('#game-sidebar').is_visible()
     assert not page.locator('.game-topbar').is_visible() and not page.locator('#game-summary-toggle').is_visible()
     clock=page.locator('#game-entenda-clock').bounding_box();menu=page.locator('#game-nav-toggle').bounding_box()
     assert clock['x']+clock['width']<=menu['x'] and abs((clock['y']+clock['height']/2)-(menu['y']+menu['height']/2))<6,(clock,menu)
     tab.click();page.wait_for_timeout(350);bar=page.locator('#game-sidebar').bounding_box();assert bar['x']>=-1 and bar['x']+bar['width']<=w+1,bar
     # szuflada ma wysokość ekranu (przewija się), a nie wysokość treści
     dims=page.evaluate("()=>{const s=document.querySelector('#game-sidebar');return [s.getBoundingClientRect().height,s.clientHeight,getComputedStyle(s).overflowY]}")
     assert dims[0]<=h+1 and dims[2]=='auto',dims
     assert page.locator('#game-sidebar #game-notifications-toggle').is_visible() and page.locator('#game-sidebar #game-mail-toggle').is_visible()
     page.locator('#game-notifications-toggle').click();page.wait_for_timeout(100)
     drop=page.locator('#game-notifications .game-notification-dropdown').bounding_box();assert drop['x']>=0 and drop['x']+drop['width']<=w+1,drop
     page.locator('#game-notifications-toggle').click()
     # zakładka szuflady leży pod paskiem (lista powiadomień jej nie przykrywa od spodu)
     assert page.evaluate("()=>Number(getComputedStyle(document.querySelector('#sidebar-drawer-tab')).zIndex)<Number(getComputedStyle(document.querySelector('#game-sidebar')).zIndex)")
     tab.click();page.wait_for_timeout(350);assert not page.locator('#game-sidebar').is_visible()
     if path=='/game/handel':
      assert not page.locator('#trade-shipments').is_visible();page.locator('#trade-shipments-open').click();assert page.locator('#trade-shipments-dialog').is_visible()
      box=page.locator('#trade-shipments-dialog').bounding_box();assert box['x']>=0 and box['x']+box['width']<=w+1,box;page.locator('#trade-shipments-close').click()
     if path=='/test/game_main_page':
      boxes=page.locator('.panel-filter-group button').evaluate_all('(ns)=>ns.map(n=>{const r=n.getBoundingClientRect();return [r.x,r.width,r.height]})')
      assert all(b[2]<=44 for b in boxes),boxes
     mld=page.locator('.module-funds-mld')
     if mld.count():assert mld.first.is_visible() and 'MLD' in mld.first.inner_text() and not page.locator('.module-funds-full').first.is_visible()
     if path=='/game/badania':
      assert page.locator('[data-node=method]').bounding_box()['width']>=44
      page.locator('[data-node=method]').click()
      box=page.locator('#research-dialog').bounding_box();assert box['x']>=0 and box['x']+box['width']<=w+1,box
      page.locator('#research-close').click()
     page.locator('#game-nav-toggle').click();assert page.locator('#game-nav-toggle').get_attribute('aria-expanded')=='true'
     assert page.locator('#game-nav-links').bounding_box()['height']<=h-119
     page.locator('#game-nav-links').press('Escape')
    if w<=900:
     for box in page.locator('#infrastructure-map, #game-country-map, #world-map').evaluate_all('(ns)=>ns.map(n=>n.getBoundingClientRect().height)'):
      assert 280<=box<=520,box
    if w==1440:
     # Treść obok lewego paska (nie pod nim)
     side=page.locator('#game-sidebar').bounding_box();main=page.locator('#main-content').bounding_box()
     assert main['x']>=side['x']+side['width']-1 and main['y']<side['y']+200,(side,main)
     # Lista powiadomień na prawo od ikony i nad mapą / kontenerami
     page.locator('#game-notifications-toggle').click();page.wait_for_timeout(150)
     icon=page.locator('#game-notifications-toggle').bounding_box();drop=page.locator('#game-notifications .game-notification-dropdown').bounding_box()
     assert drop['x']>=icon['x']+icon['width'] and abs(drop['y']-icon['y'])<4,(icon,drop)
     top=page.evaluate('''() => {const d=document.querySelector('#game-notifications .game-notification-dropdown').getBoundingClientRect();return [[d.left+d.width/2,d.top+20],[d.left+d.width/2,d.bottom-10],[d.right-10,d.top+d.height/2]].every(([x,y])=>document.elementFromPoint(x,y)?.closest('.game-notification-dropdown'))}''')
     assert top,'lista powiadomien przykryta'
     page.locator('#game-notifications-toggle').click()
     if page.locator('.module-funds-full').count():assert page.locator('.module-funds-full').first.is_visible() and not page.locator('.module-funds-mld').first.is_visible()
    if w==390:page.evaluate('document.activeElement.blur(); window.scrollTo(0,0)');page.screenshot(path='/tmp/mobile-'+path.rsplit('/',1)[-1]+'.png',full_page=True)
  browser.close()
finally:
 case.tearDown();case.doCleanups()
