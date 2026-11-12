"""Browser trade workflow against isolated SQLite fixtures; no live game access."""
import sys,json
from pathlib import Path
from datetime import timedelta
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from test_game_trade_extensions import TradeExtensionTests
from test_game_military import NOW
from extensions import db
from models import Stosunki
from game.finance_models import StateFinancialAccount
from game.commerce_models import TradeOffer
from game.research_models import ResearchAccount
from game.forum_models import GameNotification
from playwright.sync_api import sync_playwright,expect

case=TradeExtensionTests();case.setUp()
point=patch('game.commerce.city_point',side_effect=lambda id:[(id-101)*100,0]);point.start()
try:
 db.session.get(StateFinancialAccount,2).reserve_balance=1000000000000
 db.session.add(Stosunki(PANSTWO_ID=1,PANSTWO_ID2=3,relacja_id=case.relations['Sojusznicze'],stan_id=1));db.session.commit()
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True,args=['--no-sandbox']);context=browser.new_context(viewport={'width':1440,'height':1000},ignore_https_errors=True)
  def route(route):
   from urllib.parse import urlsplit,unquote
   request=route.request;path=urlsplit(request.url).path
   if path.startswith('/static/'):
    file=ROOT/unquote(path.lstrip('/'))
    if path.endswith('entenda_regiony.geojson'):route.fulfill(json={'type':'FeatureCollection','features':[]})
    elif file.exists():route.fulfill(path=str(file))
    else:route.fulfill(status=404,body='')
   elif path in ['/game/handel','/game/handel/stan','/game/handel/zmien']:
    if request.method=='POST':response=case.client.post(path,json=request.post_data_json,headers={'X-CSRF-Token':'token'})
    else:response=case.client.get(path)
    route.fulfill(status=response.status_code,content_type=response.content_type,body=response.data)
   else:route.fulfill(json={})
  context.route('http://test.local/**',route)
  page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
  page.goto('http://test.local/game/handel',wait_until='networkidle')
  ammo=page.locator('[data-cargo="interceptor_ammunition"]');expect(ammo).to_have_attribute('max','100')
  ammo.fill('20');page.locator('#trade-offer-form [name=price]').fill('1')
  page.locator('#trade-offer-form button[type=submit]').click()
  expect(page.locator('#trade-status')).to_contain_text('Oferta wystawiona')
  expect(ammo).to_have_attribute('max','80')
  page.locator('#trade-port-fees-open').click()
  expect(page.locator('#trade-port-blocked-countries input[value="3"]')).to_be_disabled()
  page.locator('#trade-port-fees-close').click()
  case.login(2)
  page.goto('http://test.local/game/handel',wait_until='networkidle')
  page.get_by_role('button',name='Kup pakiet',exact=True).click()
  page.locator('#trade-buy-form button[type=submit]').click()
  expect(page.locator('#trade-status')).to_contain_text('Zakup opłacony')
  db.session.expire_all();assert db.session.query(GameNotification).count()==1
  with patch('game.commerce.game_now',return_value=NOW+timedelta(hours=2)):
   page.goto('http://test.local/game/handel',wait_until='networkidle')
  expect(page.locator('#trade-shipments')).to_contain_text('Dostarczono (Entenda):')
  expect(page.locator('#trade-shipments')).to_contain_text('2990')
  expect(page.locator('[data-cargo="interceptor_ammunition"]')).to_have_attribute('max','20')
  page.set_viewport_size({'width':390,'height':844})
  assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
  page.screenshot(path='/tmp/zeus-trade-extensions-mobile.png',full_page=True)
  assert not errors,errors
  browser.close()
 print('Trade browser OK: ammunition escrow/sale/delivery, protected allied port control, delivered simulation date, 390px layout; isolated test database.')
finally:point.stop();case.tearDown()
