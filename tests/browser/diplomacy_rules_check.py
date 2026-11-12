"""Real diplomacy UI/services on an isolated SQLite world; no live UAT actions."""
import sys
from pathlib import Path
from urllib.parse import urlsplit,parse_qs,unquote
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from test_diplomacy_rules import DiplomacyRuleTests
from game.diplomacy_models import DiplomaticAction
from extensions import db
from sqlalchemy import select
from models import Stosunki
from playwright.sync_api import sync_playwright,expect

case=DiplomacyRuleTests();case.setUp();case.pair(1,9)
case.app.url_build_error_handlers.append(lambda error,endpoint,values:'/stub/'+endpoint)
case.app.context_processor(lambda:{'game_csrf_token':'token'})
try:
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
        context=browser.new_context(viewport={'width':390,'height':844})
        def route(route):
            request=route.request;url=urlsplit(request.url);path=url.path
            if url.hostname!='test.local':route.abort();return
            if path.startswith('/static/'):
                file=ROOT/unquote(path.lstrip('/'))
                if file.is_file():route.fulfill(path=str(file))
                else:route.fulfill(status=404,body='')
            elif path.startswith('/game/dyplomacja'):
                if request.method=='POST':
                    # Browser FormData is multipart; Werkzeug parses its original body.
                    response=case.client.post(path,data=request.post_data_buffer,content_type=request.headers.get('content-type'))
                else:response=case.client.get(path)
                route.fulfill(status=response.status_code,content_type=response.content_type,body=response.data)
            else:route.fulfill(json={'items':[],'count':0,'unread_count':0})
        context.route('**/*',route)
        page=context.new_page();page.goto('http://test.local/game/dyplomacja',wait_until='domcontentloaded')
        page.locator('#diplomacy-country').select_option('2')
        expect(page.locator('#diplomacy-kind option[value=WAR]')).to_be_disabled()
        page.locator('#diplomacy-relation').select_option('9')
        expect(page.locator('#diplomacy-action-help')).to_contain_text('Jednostronne')
        page.once('dialog',lambda dialog:dialog.dismiss())
        page.get_by_role('button',name='Wypowiedz porozumienie',exact=True).click()
        assert db.session.query(DiplomaticAction).count()==0
        page.once('dialog',lambda dialog:dialog.accept())
        page.get_by_role('button',name='Wypowiedz porozumienie',exact=True).click()
        expect(page.locator('#diplomacy-actions-dialog')).not_to_be_visible()
        page.locator('#diplomacy-country').select_option('2')
        expect(page.locator('#diplomacy-kind option[value=WAR]')).to_be_enabled()
        page.locator('#diplomacy-kind').select_option('WAR')
        page.screenshot(path='/tmp/diplomacy-war-rules-mobile.png',full_page=True)
        page.once('dialog',lambda dialog:dialog.accept())
        page.get_by_role('button',name='Wyślij',exact=True).click()
        expect(page.locator('#diplomacy-actions-dialog')).not_to_be_visible()
        db.session.expire_all()
        assert db.session.scalar(select(Stosunki.stan_id))==8
        assert db.session.query(DiplomaticAction).filter_by(status='APPLIED').count()==2
        print('Diplomacy browser OK: alliance blocks war, unilateral break with cancel/confirm, immediate tense relation, information-war escalation, mobile form; isolated data only.')
        browser.close()
finally:case.tearDown()
