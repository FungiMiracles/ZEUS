"""Real pending-proposal cards and decisions on isolated fixture data."""
import sys
from pathlib import Path
from urllib.parse import urlsplit,unquote
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from test_diplomacy_proposals import DiplomacyProposalTests
from game.diplomacy_models import DiplomaticAction
from game.forum_models import GameNotification
from extensions import db
from playwright.sync_api import sync_playwright,expect

case=DiplomacyProposalTests();case.setUp();outgoing=case.offer(1,2);incoming=case.offer(3,1)
case.app.url_build_error_handlers.append(lambda error,endpoint,values:'/stub/'+endpoint)
case.app.context_processor(lambda:{'game_csrf_token':'token'})
try:
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--no-sandbox']);context=browser.new_context(viewport={'width':390,'height':844})
        def route(route):
            request=route.request;url=urlsplit(request.url);path=url.path
            if url.hostname!='test.local':route.abort();return
            if path.startswith('/static/'):
                file=ROOT/unquote(path.lstrip('/'))
                if file.is_file():route.fulfill(path=str(file))
                else:route.fulfill(status=404,body='')
            elif path.startswith('/game/dyplomacja') or path.startswith('/game/forum/powiadomienia'):
                if request.method=='POST':response=case.client.post(path,data=request.post_data_buffer,content_type=request.headers.get('content-type'))
                else:response=case.client.get(path)
                route.fulfill(status=response.status_code,content_type=response.content_type,body=response.data)
            else:route.fulfill(json={'items':[],'count':0,'unread_count':0})
        context.route('**/*',route);page=context.new_page()
        page.goto('http://test.local/game/dyplomacja',wait_until='domcontentloaded')
        panel=page.locator('#diplomacy-proposals');panel.scroll_into_view_if_needed()
        expect(panel).to_contain_text('Oczekuje na odpowiedź od Państwo 2')
        expect(panel).to_contain_text('Państwo 3 oczekuje na Twoją odpowiedź')
        expect(panel.get_by_role('button',name='Akceptuj',exact=True)).to_have_count(1)
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        panel.screenshot(path='/tmp/diplomacy-proposals-mobile.png')
        panel.get_by_role('button',name='Odrzuć',exact=True).click()
        expect(page.locator(f'[data-proposal-id="{incoming}"]')).to_have_count(0)
        db.session.expire_all();assert db.session.get(DiplomaticAction,incoming).status=='REJECTED'
        incoming=case.offer(3,1);page.reload(wait_until='domcontentloaded')
        page.locator('#diplomacy-proposals').get_by_role('button',name='Akceptuj',exact=True).click()
        expect(page.locator(f'[data-proposal-id="{incoming}"]')).to_have_count(0)
        db.session.expire_all();assert db.session.get(DiplomaticAction,incoming).status=='ACCEPTED'
        expect(page.locator(f'[data-proposal-id="{outgoing}"]')).to_have_count(1)
        assert db.session.query(GameNotification).filter_by(user_id=1,read_at=None).count()==2
        page.set_viewport_size({'width':1280,'height':900});page.reload(wait_until='domcontentloaded')
        assert page.locator('#diplomacy-proposals').bounding_box()['y']>page.locator('#diplomacy-map').bounding_box()['y']+page.locator('#diplomacy-map').bounding_box()['height']
        print('Proposal cards browser OK: exact outgoing/incoming statuses, reject/accept, pending removal, placement under map, mobile layout and unchanged general notifications; isolated data only.')
        browser.close()
finally:case.tearDown()
