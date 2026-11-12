"""Browser account removal against an isolated fixture, never a real player's account."""
import sys
from pathlib import Path
from urllib.parse import urlsplit,parse_qs,unquote
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from test_game_account import AccountTests,PASSWORD
from game.paga import save_configuration
from game.models import GameUser
from game.country_summary import country_summary
from models import Panstwo
from extensions import db
from flask import render_template
from sqlalchemy import select
from sqlalchemy.orm import lazyload
from playwright.sync_api import sync_playwright,expect

case=AccountTests();case.setUp()
case.app.url_build_error_handlers.append(lambda error,endpoint,values:'/stub/'+endpoint)
case.app.view_functions['wejscie']=lambda:'Konto zostało usunięte.'
case.app.view_functions['game_main_page']=lambda:render_template('game/game_main_page.html',game_user=db.session.get(GameUser,1),game_country=country_summary(db.session.scalar(select(Panstwo).where(Panstwo.PANSTWO_ID==1).options(lazyload('*')))),game_region_names={},game_city_data={},game_events=[])
save_configuration(db.session,1,case.payload,'Browser fixture');db.session.commit()
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
            elif path.startswith('/game/konto') or path.startswith('/test/'):
                if request.method=='POST':response=case.client.post(path,data={key:values[0] for key,values in parse_qs(request.post_data or '',keep_blank_values=True).items()})
                else:response=case.client.get(path+('?' + url.query if url.query else ''))
                # Resolve fixture redirects without sending the browser to a real server.
                if response.status_code==303:response=case.client.get(response.headers['Location'])
                route.fulfill(status=response.status_code,content_type=response.content_type,body=response.data)
            else:route.fulfill(json={'items':[],'notifications':[],'count':0,'unread_count':0})
        context.route('**/*',route)
        page=context.new_page()
        page.goto('http://test.local/test/game_main_page',wait_until='domcontentloaded')
        page.get_by_role('link',name='Usuń konto',exact=True).click()
        expect(page.get_by_role('heading',name='Czy jesteś pewien, że chcesz usunąć konto?',exact=True)).to_be_visible()
        expect(page.locator('input[name=password]')).to_have_count(0)
        page.get_by_role('button',name='Tak',exact=True).click()
        expect(page.get_by_label('Hasło do konta')).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        assert page.get_by_role('button',name='Usuń konto',exact=True).evaluate('e=>getComputedStyle(e).backgroundColor')=='rgb(181, 43, 43)'
        page.get_by_label('Hasło do konta').fill('wrong')
        page.get_by_role('button',name='Usuń konto',exact=True).click()
        expect(page.get_by_role('alert')).to_contain_text('Nieprawidłowe hasło')
        page.screenshot(path='/tmp/game-account-delete-mobile.png',full_page=True)
        page.get_by_label('Hasło do konta').fill(PASSWORD)
        page.get_by_role('button',name='Usuń konto',exact=True).click()
        expect(page.get_by_text('Konto zostało usunięte.',exact=True)).to_be_visible()
        db.session.expire_all();user=db.session.get(GameUser,1)
        assert user.email is None and user.password_hash is None and not user.is_active
        print('Account browser OK: Panel entry, confirmation, password verification, 390px layout, deletion and logout on isolated data.')
        browser.close()
finally:case.tearDown()
