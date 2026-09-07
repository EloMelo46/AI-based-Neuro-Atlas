"""Responsive layout smoke check, no OpenAI calls."""
import sys
from pathlib import Path
from threading import Thread
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if __package__ in (None, ''):
    sys.path.insert(0, str(PROJECT_ROOT))

from main.brain_viewer import app

OUTPUT_DIR = PROJECT_ROOT / 'verification'
OUTPUT_DIR.mkdir(exist_ok=True)
server = make_server('127.0.0.1', 5058, app, threaded=True)
Thread(target=server.serve_forever, daemon=True).start()
try:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True, args=['--enable-unsafe-swiftshader'])
        page = browser.new_page(viewport={'width':390, 'height':844}, is_mobile=True, has_touch=True)
        errors=[]
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto('http://127.0.0.1:5058')
        page.wait_for_function("document.querySelector('#reset').disabled === false",timeout=120000)
        assert not page.locator('#info').is_visible()
        assert not page.locator('#assistant-panel').is_visible()
        page.locator('#fullscreen-toggle').click()
        page.wait_for_function('!!document.fullscreenElement')
        assert page.locator('#fullscreen-toggle').get_attribute('aria-pressed') == 'true'
        page.locator('#fullscreen-toggle').click()
        page.wait_for_function('!document.fullscreenElement')
        page.screenshot(path=str(OUTPUT_DIR / 'mobile-scene.png'))
        for panel, selector in [('regions','#info'),('assistant','#assistant-panel')]:
            page.locator(f'[data-panel="{panel}"]').click()
            assert page.locator(selector).is_visible()
            page.wait_for_timeout(200)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert page.locator('#scene').bounding_box()['height'] > 200
            page.screenshot(path=str(OUTPUT_DIR / f'mobile-{panel}.png'))
        page.locator('#assistant-input').fill('Was macht der Hippocampus?')
        page.locator('[data-panel="regions"]').click()
        page.locator('#hide-regions').click()
        assert '0 von' in page.locator('#region-count').inner_text()
        assert page.evaluate("""async () => {
          const viewer = (await import('/static/brain_viewer.js')).assistantViewer;
          const loaded = viewer.getState().loaded;
          const targets = loaded.filter(id => id.endsWith('Thalamus'));
          const background = loaded.filter(id => !targets.includes(id) && id !== 'CSF');
          viewer.execute({name: 'isolate_regions', arguments: {region_ids: targets}});
          const focused = viewer.getState();
          const focusCorrect = focused.visible.length === loaded.length - 1 && !focused.visible.includes('CSF') &&
            background.every(id => focused.opacities[id] === 0.01) &&
            targets.every(id => focused.opacities[id] === 1);
          viewer.execute({name: 'set_opacity', arguments: {region_ids: background, opacity: 0.05}});
          const state = viewer.getState();
          return focusCorrect && state.visible.length === loaded.length - 1 && !state.visible.includes('CSF') &&
            background.every(id => state.opacities[id] === 0.05) &&
            targets.every(id => state.opacities[id] === 1);
        }"""), 'Setting opacity did not reactivate hidden background regions'
        page.evaluate("""async () => {
          const viewer = (await import('/static/brain_viewer.js')).assistantViewer;
          viewer.execute({name: 'reset_view', arguments: {}});
        }""")
        page.locator('#show-regions').click()
        page.set_viewport_size({'width':844,'height':390})
        page.wait_for_timeout(200)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(OUTPUT_DIR / 'mobile-landscape.png'))
        page.set_viewport_size({'width':1440,'height':1000})
        page.wait_for_timeout(300)
        assert page.locator('#info').is_visible() and page.locator('#assistant-panel').is_visible()
        page.screenshot(path=str(OUTPUT_DIR / 'desktop-design.png'))
        assert not errors, errors
        browser.close()
        print('PASS: mobile navigation, 1% focus context, opacity reactivates hidden regions, portrait/landscape, no horizontal overflow, no JS errors.')
finally:
    server.shutdown()
