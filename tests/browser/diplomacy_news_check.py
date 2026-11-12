"""Diplomacy news dropdown and main war notices on isolated SQLite data."""
import sys
from pathlib import Path
from urllib.parse import urlsplit,unquote
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from test_diplomacy_news import DiplomacyNewsTests,NOW
from game.diplomacy_service import create_action,decide_action
from extensions import db
from playwright.sync_api import sync_playwright,expect

case=DiplomacyNewsTests();case.setUp();case.war()
peace=create_action(db.session,1,2,'PEACE',None,NOW,sender_user_id=1);db.session.flush();decide_action(db.session,peace.id,2,True,NOW,user_id=2)
proposal=create_action(db.session,1,2,'RELATION',1,NOW,sender_user_id=1);db.session.flush();decide_action(db.session,proposal.id,2,False,NOW,user_id=2);db.session.commit()
case.app.url_build_error_handlers.append(lambda error,endpoint,values:'/stub/'+endpoint)
case.app.context_processor(lambda:{'game_csrf_token':'token'})
try:
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--no-sandbox']);context=browser.new_context(viewport={'width':1440,'height':1000})
        def route(route):
            request=route.request;url=urlsplit(request.url);path=url.path
            if url.hostname!='test.local':route.abort();return
            if path.startswith('/static/'):
                file=ROOT/unquote(path.lstrip('/'))
                if path.startswith('/static/flags/') and not file.is_file():file=next((ROOT/'static/flags').glob('*.jpg'))
                if file.is_file():route.fulfill(path=str(file))
                else:route.fulfill(status=404,body='')
            elif path.startswith('/game/dyplomacja') or path.startswith('/game/forum/powiadomienia'):
                target=path+('?' + url.query if url.query else '')
                if request.method=='POST':response=case.client.post(target,data=request.post_data_buffer,content_type=request.headers.get('content-type'))
                else:response=case.client.get(target)
                route.fulfill(status=response.status_code,content_type=response.content_type,body=response.data)
            else:route.fulfill(json={'items':[],'count':0,'unread_count':0})
        context.route('**/*',route);page=context.new_page()
        page.goto('http://test.local/game/dyplomacja',wait_until='domcontentloaded')
        root=page.locator('#diplomacy-world-news')
        expect(root.locator('[data-news-count]')).to_have_text('3')
        expect(page.locator('#game-notification-count')).to_have_text('2')
        assert root.locator('summary img').get_attribute('src')==page.locator('#game-notifications summary img').get_attribute('src')
        root.locator('summary').click()
        expect(root.locator('.game-notification-item')).to_have_count(3)
        expect(root.locator('.diplomacy-news-flags img')).to_have_count(6)
        expect(root.locator('[data-news-list]')).to_contain_text('odrzucono propozycję')
        expect(root.locator('[data-news-count]')).to_be_hidden()
        def anchored():
            return root.evaluate('''root=>{
                const button=root.querySelector('summary').getBoundingClientRect();
                const panel=root.querySelector('.game-notification-dropdown').getBoundingClientRect();
                return panel.left>=11&&panel.right<=innerWidth-11&&
                    Math.min(Math.abs(panel.top-button.bottom-10),Math.abs(button.top-panel.bottom-10))<2;
            }''')
        assert anchored(),'Desktop dropdown must be anchored beside its own button'
        button=root.locator('summary').bounding_box();panel=root.locator('.game-notification-dropdown').bounding_box()
        assert abs((panel['x']+panel['width'])-(button['x']+button['width']))<2
        page.set_viewport_size({'width':390,'height':844})
        page.wait_for_function('''()=>{
            const root=document.getElementById('diplomacy-world-news');
            const b=root.querySelector('summary').getBoundingClientRect(),p=root.querySelector('.game-notification-dropdown').getBoundingClientRect();
            return p.left>=11&&p.right<=innerWidth-11&&Math.min(Math.abs(p.top-b.bottom-10),Math.abs(b.top-p.bottom-10))<2;
        }''')
        assert anchored(),'Mobile dropdown must follow its own button after resize'
        root.locator('summary').evaluate('e=>window.scrollTo(0,scrollY+e.getBoundingClientRect().top-80)')
        page.wait_for_function('''()=>{
            const r=document.getElementById('diplomacy-world-news');
            return Math.abs(r.querySelector('.game-notification-dropdown').getBoundingClientRect().top-r.querySelector('summary').getBoundingClientRect().bottom-10)<2;
        }''')
        main_end=page.locator('#game-notification-list button').filter(has_text='została zakończona')
        local_end=root.locator('.game-notification-item').filter(has_text='została zakończona')
        assert main_end.evaluate('e=>getComputedStyle(e).backgroundColor')==local_end.evaluate('e=>getComputedStyle(e).backgroundColor')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        page.screenshot(path='/tmp/diplomacy-news-mobile.png',full_page=True)
        assert case.client.get('/game/forum/powiadomienia').json['unread_count']==2
        assert case.client.get('/game/dyplomacja/wiadomosci-swiatowe').json['unread_count']==0
        # Reproduce overlap regardless of fixture text length: the general dropdown covers
        # the diplomacy trigger, and hit testing must select the dropdown, not that trigger.
        root.locator('summary').click()
        general=page.locator('#game-notifications')
        general.locator('summary').click()
        general.evaluate('''general=>{
            const button=document.querySelector('#diplomacy-world-news summary').getBoundingClientRect();
            const panel=general.querySelector('.game-notification-dropdown');
            Object.assign(panel.style,{position:'fixed',left:`${button.left}px`,top:`${button.top}px`,width:'250px',height:'180px'});
        }''')
        assert page.evaluate('''()=>{
            const button=document.querySelector('#diplomacy-world-news summary').getBoundingClientRect();
            return !!document.elementFromPoint(button.left+10,button.top+10)?.closest('#game-notifications .game-notification-dropdown');
        }'''),'General notifications must cover the diplomacy trigger when their bounds overlap'
        general.evaluate("e=>{e.open=false;e.querySelector('.game-notification-dropdown').removeAttribute('style');}")
        print('Diplomacy news browser OK: desktop/right alignment, mobile anchoring after resize and scrolling, same icon, two flags, independent read counters; isolated world only.')
        browser.close()
finally:case.tearDown()
