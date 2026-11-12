"""Browser check against an isolated Flask/SQLite fixture, never the UAT DB."""
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from test_global_economic_crisis import GlobalEconomicCrisisTests, NOW

fixture = GlobalEconomicCrisisTests()
fixture.setUp()
try:
    with fixture.client.session_transaction() as browser_session:
        browser_session['rola'] = 'wszechmocny'
    with patch('routes_zdarzenia.get_current_entenda_datetime', return_value=NOW), sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        page.set_default_timeout(7000)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        def isolated_request(route):
            request = route.request
            url = urlsplit(request.url)
            response = fixture.client.open(url.path + ('?' + url.query if url.query else ''),
                method=request.method, data=request.post_data,
                content_type=request.headers.get('content-type'), follow_redirects=True)
            route.fulfill(status=response.status_code, content_type=response.content_type, body=response.data)
        page.route('https://fixture.invalid/**', isolated_request)
        page.goto('https://fixture.invalid/zdarzenia')
        for width, height in [(1440, 1000), (390, 844)]:
            page.set_viewport_size({'width': width, 'height': height})
            panel_box = page.locator('[aria-labelledby="global-crisis-title"]').bounding_box()
            filter_box = page.locator('.zeus-filter-box').bounding_box()
            assert panel_box['y'] + panel_box['height'] <= filter_box['y']
        page.locator('#global-crisis-level').select_option('medium')
        page.on('dialog', lambda dialog: dialog.accept())
        page.get_by_role('button', name='Wygeneruj globalny kryzys').click()
        try:
            page.locator('#global-crisis-banner').wait_for(state='visible')
        except Exception:
            print('Browser fixture response:', page.locator('body').inner_text()[:1800], flush=True)
            raise
        assert 'trwa średni globalny kryzys gospodarczy' in page.locator('#global-crisis-banner').inner_text()
        assert page.locator('#global-crisis-level').count() == 0
        assert fixture.growths()[1] == 2
        assert not errors, errors
        browser.close()
        print('Isolated browser: admin panel, confirmation, crisis event and persistent banner verified.')
finally:
    fixture.tearDown()
