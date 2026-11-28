"""PAGA browser check, backed only by an isolated SQLite fixture."""
import sys,re,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from test_paga import PagaTests
from game.paga import TRAITS,PagaConfiguration,PagaRevision
from extensions import db
from jinja2 import FileSystemLoader
from flask import render_template
from playwright.sync_api import sync_playwright,expect

case=PagaTests();case.setUp();case.install_forum_control()
case.app.jinja_loader=FileSystemLoader(str(ROOT/'templates'))
case.app.url_build_error_handlers.append(lambda error,endpoint,values:'/stub/'+endpoint)
@case.app.context_processor
def context():return dict(ENV_NAME='UAT',ENTENDA_DATETIME='2990-01-01T00:00:00',ENTENDA_DATE='1 stycznia 2990',ENTENDA_TIME_MULTIPLIER=0)
case.app.add_url_rule('/wiki-test','wiki_test',lambda:render_template('base_layout.html'))
try:
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True,args=['--no-sandbox']);context=browser.new_context(viewport={'width':1440,'height':1000})
  def route(route):
   from urllib.parse import urlsplit,unquote
   request=route.request;parsed=urlsplit(request.url);path=parsed.path
   if path.startswith('/static/'):
    file=ROOT/unquote(path.lstrip('/'))
    if file.exists():route.fulfill(path=str(file))
    else:route.fulfill(status=404,body='')
   elif path.startswith('/admin/paga') or path=='/wiki-test':
    if request.method=='POST':
     if 'application/json' in request.headers.get('content-type',''):response=case.client.post(path,json=request.post_data_json,headers={k:v for k,v in request.headers.items() if k.lower().startswith('x-')})
     else:
      from urllib.parse import parse_qs
      response=case.client.post(path,data={k:v[0] for k,v in parse_qs(request.post_data or '').items()})
    else:response=case.client.get(path+('?' + parsed.query if parsed.query else ''),headers={k:v for k,v in request.headers.items() if k.lower().startswith('x-')})
    route.fulfill(status=response.status_code,content_type=response.content_type,body=response.data)
   elif path=='/wiki/zegar':route.fulfill(json={'entenda':'2990-01-01T00:00:00','multiplier':0,'revision':0,'can_control':False})
   else:route.fulfill(json={})
  context.route('http://test.local/**',route)
  page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto('http://test.local/wiki-test',wait_until='domcontentloaded')
  # 28 Nov 2026: PAGA jest pozycją rozwijanego menu ZEUS WIKI (bez osobnego przycisku)
  page.locator('.admin-hamburger-btn').click()
  expect(page.locator('#adminDropdown').get_by_role('link',name='PAGA',exact=True)).to_be_visible()
  page.get_by_role('link',name='PAGA',exact=True).click()
  page.wait_for_load_state('networkidle')
  assert not errors,errors
  page.locator('#paga-monitor summary').first.click()
  expect(page.locator('#paga-monitor-status')).to_contain_text('Silnik włączony')
  page.locator('#paga-engine-enabled').uncheck()
  page.locator('#paga-engine-control button[type=submit]').click()
  expect(page.locator('#paga-monitor-status')).to_contain_text('Silnik globalnie zatrzymany')
  page.locator('#paga-engine-enabled').check()
  page.locator('#paga-engine-control button[type=submit]').click()
  expect(page.locator('#paga-monitor-status')).to_contain_text('Silnik włączony')
  page.locator('#paga-monitor summary').first.click()
  expect(page.locator('#paga-country')).to_be_disabled()
  page.locator('#paga-continent').select_option('1')
  expect(page.locator('#paga-country')).to_be_enabled()
  page.locator('#paga-country').select_option('1')
  expect(page.locator('#paga-full-name')).to_have_text('Pełna nazwa kraju A')
  for key in TRAITS:expect(page.locator(f'[data-trait-value={key}]')).to_have_value('')
  expect(page.locator('#paga-autonomy')).to_have_value('false')
  expect(page.locator('#paga-approve')).to_be_disabled()
  page.locator('#paga-draft').click();expect(page.locator('#paga-status')).to_contain_text('Zapisano wersję roboczą')
  for key in TRAITS:page.locator(f'[data-trait-value={key}]').fill('0')
  page.locator('[data-trait-range=militarism]').focus();page.keyboard.press('ArrowRight')
  expect(page.locator('[data-trait-value=militarism]')).to_have_value('1')
  page.locator('[data-trait-value=militarism]').fill('37');expect(page.locator('[data-trait-range=militarism]')).to_have_value('37')
  survival=page.locator('[data-key=survival]');survival.locator('input').check()
  for i in range(5):survival.locator('[data-move=up]').click()
  expect(page.locator('#paga-interests li').first).to_have_attribute('data-key','survival')
  page.locator('[data-key=terrorism]').drag_to(page.locator('[data-key=world_hegemony]'))
  keys=page.locator('#paga-interests li').evaluate_all('nodes=>nodes.map(n=>n.dataset.key)')
  assert keys.index('terrorism')<8 and len(set(keys))==9,keys
  page.locator('#paga-autonomy').select_option('true')
  page.locator('#paga-approve').click();expect(page.locator('#paga-status')).to_have_text('Konfiguracja zatwierdzona.')
  db.session.expire_all();row=db.session.get(PagaConfiguration,1)
  assert row.autonomy_enabled is True
  expect(page.locator('#paga-autonomy-current')).to_have_text('Autonomia obowiązująca: Włączona.')
  assert row.approved_at and row.approved_character['militarism']==37 and row.approved_interests[0]['key']=='survival'
  page.locator('#paga-autonomy').select_option('false')
  page.locator('[data-trait-value=ambition]').fill('99');page.locator('#paga-draft').click()
  expect(page.locator('#paga-status')).to_contain_text('Zapisano wersję roboczą')
  db.session.expire_all();row=db.session.get(PagaConfiguration,1);assert row.approved_character['ambition']==0 and row.draft_character['ambition']==99
  assert row.autonomy_enabled is True and row.draft_autonomy_enabled is False
  expect(page.locator('#paga-autonomy-current')).to_have_text('Autonomia obowiązująca: Włączona.')
  page.set_viewport_size({'width':390,'height':844})
  assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
  page.screenshot(path='/tmp/paga-mobile.png',full_page=True)
  page.goto('http://test.local/admin/paga');expect(page.locator('#paga-password')).to_have_count(0);expect(page.locator('#paga-config')).to_have_count(1)
  with case.client.session_transaction() as session:session['rola']='obserwator'
  page.goto('http://test.local/wiki-test');expect(page.locator('.paga-entry-link')).to_have_count(0)
  assert not errors,errors
  browser.close()
 print('PAGA browser OK: red/white role-only button, no extra password (WIKI role only), continent/country, blanks and zero, slider sync, ranking buttons/drag, activation, draft/approval isolation and 390px layout.')
finally:case.tearDown()
