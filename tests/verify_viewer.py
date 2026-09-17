"""Manual browser regression check; uses the locally installed Chrome."""
import sys
from pathlib import Path
from threading import Thread
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if __package__ in (None, ''):
    sys.path.insert(0, str(PROJECT_ROOT))

from main.brain_viewer import app

server = make_server('127.0.0.1', 5051, app, threaded=True)
Thread(target=server.serve_forever, daemon=True).start()
try:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='chrome', headless=True,
            args=['--enable-unsafe-swiftshader'])
        page = browser.new_page(viewport={'width': 1280, 'height': 900})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)
        page.add_init_script("""
          window.framesDrawn = 0;
          const original = WebGL2RenderingContext.prototype.drawElements;
          WebGL2RenderingContext.prototype.drawElements = function(...args) {
            window.framesDrawn++;
            return original.apply(this, args);
          };
        """)
        page.goto('http://127.0.0.1:5051')
        page.wait_for_function("document.querySelector('#status').textContent === '38 von 38 Regionen geladen'", timeout=120000)
        for name in ('lh.pial', 'rh.pial', 'lh.white', 'rh.white', 'lh_hippo_mc'):
            assert page.locator(f'.region-row[title="{name}.obj"]').count() == 0
        csf = page.locator('.region-row[title="CSF.obj"] input')
        assert not csf.is_checked(), 'CSF must be opt-in at startup'
        page.locator('#show-regions').click()
        assert not csf.is_checked(), 'Show all must leave CSF disabled'
        csf.check()
        assert csf.is_checked(), 'CSF must remain explicitly selectable'
        page.locator('#show-regions').click()
        assert not csf.is_checked(), 'Show all must restore the default CSF state'
        assert page.locator('#mesh-detail').input_value() == 'optimized'
        page.locator('#auto-rotate').uncheck()
        page.wait_for_timeout(2000)
        before = page.evaluate('window.framesDrawn')
        page.wait_for_timeout(500)
        assert page.evaluate('window.framesDrawn') == before, 'Renderer did not become idle'
        output = PROJECT_ROOT / 'verification'
        output.mkdir(exist_ok=True)
        page.screenshot(path=str(output / 'whole.png'))
        for axis in 'xyz':
            page.locator(f'#{axis}-max').evaluate("el => { el.value = 55; el.dispatchEvent(new Event('input', {bubbles:true})); }")
        page.wait_for_timeout(1000)
        assert page.evaluate('window.framesDrawn') > before
        page.screenshot(path=str(output / 'cuts-filled.png'))
        page.locator('#fill-cuts').uncheck()
        page.wait_for_timeout(500)
        page.screenshot(path=str(output / 'cuts-open.png'))
        page.locator('#fill-cuts').check()
        page.locator('#hide-regions').click()
        assert page.locator('#region-count').inner_text().startswith('0 von 38')
        page.wait_for_timeout(500)
        page.screenshot(path=str(output / 'hidden.png'))
        page.locator('#show-regions').click()
        page.locator('#reset-cuts').click()
        for axis in 'xyz':
            assert page.locator(f'#{axis}-max').input_value() == '100'
        page.locator('#resolution').select_option('0.75')
        page.wait_for_timeout(500)
        canvas_width, css_width = page.locator('canvas').evaluate('el => [el.width, el.clientWidth]')
        assert abs(canvas_width - round(css_width * 0.75)) <= 1
        before = page.evaluate('window.framesDrawn')
        page.mouse.move(900, 400)
        page.mouse.down()
        page.mouse.move(1000, 480, steps=8)
        page.mouse.up()
        page.wait_for_timeout(2000)
        assert page.evaluate('window.framesDrawn') > before, 'Rotation did not render'
        page.wait_for_function("""() => {
          if (window.lastDrawCount !== window.framesDrawn) {
            window.lastDrawCount = window.framesDrawn;
            window.lastDrawTime = performance.now();
          }
          return performance.now() - window.lastDrawTime > 600;
        }""", polling=200, timeout=20000)
        page.locator('#mesh-detail').select_option('full')
        page.wait_for_function("document.querySelector('#status').textContent === '38 von 38 Regionen geladen'", timeout=180000)
        assert page.url.endswith('?detail=full')
        assert page.locator('#mesh-detail').input_value() == 'full'
        assert not page.locator('.region-row[title="CSF.obj"] input').is_checked()
        assert not errors, errors
        print('PASS: optimized/full mesh details, CSF opt-in, 38 structures, idle rendering, cuts, visibility, resolution, no console errors.')
        browser.close()
finally:
    server.shutdown()
