"""Exercise real WIKI clock controls on an isolated Flask/SQLite application."""
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'tests'))
from test_simulation_clock import SimulationClockTests
from flask import render_template
from engine.clock import SimulationClock, get_clock_snapshot
from extensions import db
from routes_clock import clock_bp
from routes_auth import HASLA_ROLE

fixture = SimulationClockTests(); fixture.setUp()
try:
    app = fixture.app
    app.template_folder = str(ROOT / 'templates')
    app.static_folder = str(ROOT / 'static')
    app.url_build_error_handlers.append(lambda error, endpoint, values: '/fixture/' + endpoint)
    app.add_url_rule('/test/menu', 'test_menu', lambda: render_template('base_layout.html'))
    @app.context_processor
    def fixture_clock():
        snapshot = get_clock_snapshot()
        return dict(ENV_NAME='UAT', ENTENDA_DATETIME=snapshot['entenda'],
            ENTENDA_DATE='15.06.3000', ENTENDA_TIME_MULTIPLIER=snapshot['multiplier'],
            ENTENDA_CLOCK_REVISION=snapshot['revision'], E_WORLD_POP='8 000 000 000', E_WORLD_GDP='123,45 BLN', E_WORLD_GDP_PC='12 345,67',
            E_WORLD_INFRASTRUCTURE='65,00', E_WORLD_URBANIZATION='74,00',
            E_WORLD_POP_GROWTH='-0,25', E_WORLD_EVENTS='2 113')
    with fixture.client.session_transaction() as session:
        session['rola'] = 'wszechmocny'; session['clock_csrf'] = 'fixture-clock-token'
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
        page = browser.new_page(viewport={'width':1440, 'height':1000})
        page.set_default_timeout(7000)
        errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
        def isolated_request(route):
            request = route.request; url = urlsplit(request.url)
            headers = {'X-CSRF-Token':request.headers.get('x-csrf-token', '')}
            response = fixture.client.open(url.path + ('?' + url.query if url.query else ''),
                method=request.method, data=request.post_data, headers=headers,
                content_type=request.headers.get('content-type'), follow_redirects=True)
            route.fulfill(status=response.status_code, content_type=response.content_type, body=response.data)
        page.route('https://fixture.invalid/**', isolated_request)
        page.goto('https://fixture.invalid/test/menu')
        for speed in [0, 6, 12, 24, 36, 0]:
            page.locator(f'[data-clock-speed="{speed}"]').click()
            page.locator('#clock-speed-password').fill(HASLA_ROLE['wszechmocny'])
            page.locator('.clock-password-dialog button[type=submit]').click()
            page.wait_for_function('(speed)=>document.querySelector(`[data-clock-speed="${speed}"]`).getAttribute("aria-pressed")==="true"', arg=speed)
            assert get_clock_snapshot()['multiplier'] == speed
        before = page.locator('.entenda-clock').evaluate('(el)=>el.style.getPropertyValue("--day-progress")')
        page.wait_for_timeout(350)
        assert page.locator('.entenda-clock').evaluate('(el)=>el.style.getPropertyValue("--day-progress")') == before
        assert not page.locator('.world-stats-mobile').is_visible()
        assert page.locator('.entenda-stats > .world-stats-full').is_visible()
        page.locator('[data-clock-speed="6"]').click()
        page.locator('#clock-speed-password').fill('wrong')
        page.locator('.clock-password-dialog button[type=submit]').click()
        page.wait_for_function('document.querySelector(".entenda-speed-status").textContent.includes("Nieprawidłowe hasło")')
        assert get_clock_snapshot()['multiplier'] == 0
        page.locator('[data-clock-speed="6"]').click()
        assert page.locator('#clock-speed-password').input_value() == ''
        page.locator('[data-clock-cancel]').click()
        assert get_clock_snapshot()['multiplier'] == 0
        page.set_viewport_size({'width':390, 'height':844})
        assert page.locator('[data-clock-speed="36"]').is_visible()
        assert not page.locator('.entenda-stats > .world-stats-full').is_visible()
        assert page.locator('.entenda-stats .world-stat:visible').count() == 0
        assert '123,45 BLN' in page.locator('.world-stats-mobile summary').inner_text()
        page.locator('.world-stats-mobile summary').click()
        assert page.locator('.entenda-stats .world-stat:visible').count() == 5
        page.locator('.world-stats-mobile summary').click()
        for width in [320, 390, 768]:
            page.set_viewport_size({'width':width, 'height':844})
            box = page.locator('.entenda-clock').bounding_box()
            assert abs(box['x'] + box['width'] / 2 - width / 2) < 2, box
            assert page.locator('body').evaluate('(el)=>el.scrollWidth<=window.innerWidth')
        assert page.locator('.entenda-stats').evaluate('(el)=>el.scrollWidth<=el.clientWidth')
        assert not errors, errors
        browser.close()
        print('Isolated WIKI clock: all five buttons, pause and mobile controls verified.')
finally:
    fixture.tearDown()
