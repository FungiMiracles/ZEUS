import sys,re,json,copy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from test_game_military import MilitaryFixture
from playwright.sync_api import sync_playwright,expect
root=ROOT
case=MilitaryFixture();case.setUp()
try:
 response=case.client.get('/game/obrona-panstwa');assert response.status_code==200
 html=response.text
 match=re.search(r'(<script type="application/json" id="military-config">)(.*?)(</script>)',html,re.S);assert match
 cfg=json.loads(match[2]);cfg.update(metropolitanRegionIds=['1','2'],controlledCountryIds=[1],timeMultiplier=0)
 cfg['regions']={'1':{'name':'Region testowy z wyspą','countryId':1,'coastal':True},'2':{'name':'Drugi region','countryId':1,'coastal':True}}
 cfg['cities']={'1':{'name':'Miasto testowe','countryId':1,'regionId':'1','point':[45,45]}}
 base={'id':1,'name':'Baza testowa','kind':'land','label':'Baza lądowa','level':1,'garrison':{'soldiers':100},'capacity':{'soldiers':10000},'upgradeCost':'100','position':[35,50],'health':80,'busyVessels':{},'busyFighters':0,'operational':True,'regionId':'1','countryId':1}
 cfg['bases']=[base];cfg['visibleBases']=[base]
 cfg['visibleFactories']=[{'id':11,'name':'Fabryka testowa','health':75,'position':[65,50],'regionId':'1','countryId':1,'dailyProduction':10}]
 cfg['visibleMines']=[{'id':21,'name':'Kopalnia testowa','health':25,'position':[85,50],'regionId':'1','countryId':1,'resource':next(iter(cfg['mineralIcons'])),'ready':False,'progress':50}]
 cfg['defenses']=[{'id':i,'targetKind':kind,'targetId':id,'position':pos,'regionId':'1','countryId':1,'health':100,'level':1,'ammunition':100,'capacity':100,'efficiency':30,'upgradeCost':100} for i,kind,id,pos in [(1,'base',1,[35,50]),(2,'factory',11,[65,50]),(3,'mine',21,[85,50])]]
 cfg['vessels']=[];cfg['flights']=[];cfg['tradeShips']=[]
 html=html[:match.start(2)]+json.dumps(cfg)+html[match.end(2):]
 polygon=lambda x:{'type':'Polygon','coordinates':[[[x,0],[x+100,0],[x+100,100],[x,100],[x,0]]]}
 geometry={'type':'FeatureCollection','features':[{'type':'Feature','properties':{'region_id':1},'geometry':{'type':'MultiPolygon','coordinates':[polygon(0)['coordinates'],[[[110,30],[120,30],[120,40],[110,40],[110,30]]]]}},{'type':'Feature','properties':{'region_id':2},'geometry':polygon(300)}]}
 cities={'type':'FeatureCollection','features':[{'type':'Feature','properties':{'miasto_id':1},'geometry':{'type':'Point','coordinates':[45,45]}}]}
 state={'factories':cfg['visibleFactories'],'mines':cfg['visibleMines'],'bases':cfg['visibleBases'],'defenses':cfg['defenses'],'vessels':[],'flights':[],'tradeShips':[],'gameNow':cfg['gameNow'],'timeMultiplier':0,'missiles':cfg['missiles']}
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True,args=['--no-sandbox']);context=browser.new_context(viewport={'width':1440,'height':1000},ignore_https_errors=True)
  context.add_init_script("""(()=>{let lib;Object.defineProperty(window,'L',{configurable:true,get(){return lib},set(value){lib=value;if(value?.Map)value.Map.addInitHook(function(){this.getContainer().__testMap=this;});}});})();""")
  def route(request):
   path=request.request.url.split('test.local')[-1].split('?')[0]
   if request.request.method not in ('GET','HEAD'):raise AssertionError('Unexpected write')
   if path=='/game/obrona-panstwa':request.fulfill(status=200,content_type='text/html',body=html)
   elif path==cfg['regionsUrl']:request.fulfill(json=geometry)
   elif path==cfg['citiesUrl']:request.fulfill(json=cities)
   elif path==cfg['countriesUrl']:request.fulfill(json={'type':'FeatureCollection','features':[]})
   elif path==cfg['stateUrl']:request.fulfill(json=state)
   elif path==cfg['ammunitionStockUrl']:request.fulfill(json={'ammunition':0})
   elif path.startswith('/static/'):
    from urllib.parse import unquote
    file=root/unquote(path.lstrip('/'))
    if file.exists():request.fulfill(path=str(file))
    else:request.fulfill(status=404,body='')
   else:request.fulfill(status=200,content_type='application/json',body='{}')
  context.route('http://test.local/**',route)
  page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto('http://test.local/game/obrona-panstwa',wait_until='networkidle')
  page.wait_for_function("document.getElementById('military-map').__testMap && Object.values(document.getElementById('military-map').__testMap._layers).some(l=>l.feature?.properties?.region_id)")
  assert not errors,errors
  page.evaluate("Object.values(document.getElementById('military-map').__testMap._layers).find(l=>l.feature?.properties?.region_id===1).fire('click')")
  def bounds_check():
   return page.evaluate("""()=>{const map=document.getElementById('military-map').__testMap,b=L.latLngBounds([0,0],[100,120]);return {contains:map.getBounds().contains(b),zoom:map.getZoom(),expected:map.getBoundsZoom(b,false,[24,24])}}""")
  result=bounds_check();assert result['contains'] and result['zoom']==result['expected'],result
  # Attached base defense keeps its current 22px size and touches the parent at the bottom right.
  placement=page.evaluate("""()=>{const a=document.querySelector('.military-base-symbol>img').getBoundingClientRect(),b=document.querySelector('.military-defense-symbol-compact').getBoundingClientRect();return {gap:b.left-a.right,bottom:b.bottom-a.bottom,width:b.width}}""")
  assert abs(placement['gap'])<1 and abs(placement['bottom'])<1 and placement['width']==22,placement
  for selector in ['.military-base-symbol','.military-factory-symbol','.military-mine-symbol']:
   placement=page.evaluate("""selector=>{const map=document.getElementById('military-map').__testMap,layers=Object.values(map._layers),parent=layers.find(l=>l.getElement?.()?.querySelector(selector)),point=parent.getLatLng(),defense=layers.find(l=>l.getElement?.()?.querySelector('.military-defense-symbol-compact')&&l.getLatLng().equals(point)),a=parent.getElement().querySelector(selector+'>img:first-child').getBoundingClientRect(),b=defense.getElement().querySelector('.military-defense-symbol-compact').getBoundingClientRect();return {gap:b.left-a.right,bottom:b.bottom-a.bottom,width:b.width}}""",selector)
   assert abs(placement['gap'])<1 and abs(placement['bottom'])<1 and placement['width']==22,(selector,placement)
  for kind,selector,id in [('base','.military-base-symbol',1),('factory','.military-factory-symbol',11),('mine','.military-mine-symbol',21)]:
   page.evaluate("""selector=>Object.values(document.getElementById('military-map').__testMap._layers).find(l=>l.getElement?.()?.querySelector(selector)).fire('click')""",selector)
   expect(page.locator(f'#military-{kind}-{id}')).to_have_class(re.compile('military-object-selected'))
  # The periodic state refresh rebuilds cards, retaining the current highlight without scrolling again.
  with page.expect_request('**'+cfg['stateUrl'],timeout=10000):
   page.wait_for_timeout(5100)
  expect(page.locator('#military-mine-21')).to_have_class(re.compile('military-object-selected'))
  page.locator('#military-map').scroll_into_view_if_needed()
  page.evaluate("Object.values(document.getElementById('military-map').__testMap._layers).find(l=>l.getElement?.()?.querySelector('.military-base-symbol')).openTooltip()")
  overlap=page.evaluate("""()=>{const a=document.querySelector('.military-base-symbol').getBoundingClientRect(),b=document.querySelector('.leaflet-tooltip.military-wrapping-tooltip').getBoundingClientRect();return a.left<b.right&&a.right>b.left&&a.top<b.bottom&&a.bottom>b.top}""")
  assert not overlap,'Tooltip covers its object'
  bars=page.locator('#military-map .map-health-bar').evaluate_all("nodes=>nodes.map(n=>{const s=getComputedStyle(n);return [s.borderTopWidth,s.borderTopColor,s.height]})")
  assert bars and all(b==['1px','rgb(255, 255, 255)','7px'] for b in bars),bars
  page.screenshot(path='/tmp/zeus-defense-desktop.png',full_page=True)
  page.set_viewport_size({'width':390,'height':844})
  page.locator('#military-region-select').select_option('2');page.locator('#military-region-select').select_option('1')
  result=bounds_check();assert result['contains'] and result['zoom']==result['expected'],result
  assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
  page.screenshot(path='/tmp/zeus-defense-mobile.png',full_page=True)
  assert not errors,errors
  browser.close()
 print('Defense browser OK: full multipart region bounds, 22px attached icon alignment, white health outlines, selected base/factory/mine cards, tooltip clearance and mobile width.')
finally:case.tearDown()
