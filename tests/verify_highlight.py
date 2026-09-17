"""Browser check for visible 3D highlights; no OpenAI requests."""
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
server = make_server('127.0.0.1', 5056, app, threaded=True)
Thread(target=server.serve_forever, daemon=True).start()
try:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True, args=['--enable-unsafe-swiftshader'])
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto('http://127.0.0.1:5056')
        page.evaluate("async () => { window.viewer = (await import('/static/brain_viewer.js')).assistantViewer; }")
        assert 'CSF' not in page.evaluate('viewer.getState().visible')
        page.evaluate("viewer.execute({name:'highlight_regions', arguments:{region_ids:['Left-Cerebral-Cortex']}})")
        assert len(page.evaluate('viewer.getState().visible')) == 37
        assert page.locator('.is-highlighted').count() == 0
        legacy_state = page.evaluate('viewer.getState()')
        assert legacy_state['opacities']['Left-Cerebral-Cortex'] == 1
        assert legacy_state['opacities']['Left-Thalamus'] == 0.01
        # Visual isolation keeps the whole brain visible as a 1% context shell.
        page.evaluate("viewer.execute({name:'isolate_regions', arguments:{region_ids:['Left-Cerebral-Cortex']}})")
        focus_state = page.evaluate('viewer.getState()')
        assert len(focus_state['visible']) == 37 and 'CSF' not in focus_state['visible']
        assert focus_state['highlighted'] == ['Left-Cerebral-Cortex']
        assert focus_state['opacities']['Left-Cerebral-Cortex'] == 1
        assert all(value == 0.01 for key, value in focus_state['opacities'].items()
                   if key not in ('Left-Cerebral-Cortex', 'CSF'))
        before = page.locator('#scene canvas').screenshot()
        page.wait_for_timeout(700)
        assert page.locator('#scene canvas').screenshot() != before, 'Isolated model should rotate'
        page.locator('#auto-rotate').uncheck()
        page.wait_for_timeout(700)
        before = page.locator('#scene canvas').screenshot()
        page.wait_for_timeout(300)
        assert page.locator('#scene canvas').screenshot() == before, 'Rotation should stop'
        page.evaluate("viewer.execute({name:'set_cut', arguments:{axis:'x', min:0, max:50}})")
        page.wait_for_timeout(200)
        opaque = page.locator('#scene canvas').screenshot()
        page.evaluate("viewer.execute({name:'set_opacity', arguments:{region_ids:['Left-Cerebral-Cortex'], opacity:0.3}})")
        page.wait_for_timeout(200)
        assert page.evaluate("viewer.getState().opacities['Left-Cerebral-Cortex']") == 0.3
        assert page.locator('#scene canvas').screenshot() != opaque
        page.screenshot(path=str(OUTPUT_DIR / 'opacity.png'))
        page.evaluate("viewer.execute({name:'set_opacity', arguments:{region_ids:['Left-Cerebral-Cortex'], opacity:1}})")
        page.wait_for_timeout(200)
        assert page.locator('#scene canvas').screenshot() == opaque
        page.wait_for_timeout(500)
        page.screenshot(path=str(OUTPUT_DIR / 'highlight.png'))
        page.evaluate("viewer.execute({name:'highlight_regions', arguments:{region_ids:['Left-Hippocampus']}})")
        assert len(page.evaluate('viewer.getState().visible')) == 37
        page.evaluate("viewer.execute({name:'highlight_regions', arguments:{region_ids:[]}})")
        assert len(page.evaluate('viewer.getState().visible')) == 37
        page.evaluate("viewer.execute({name:'highlight_regions', arguments:{region_ids:['Left-Hippocampus']}})")
        page.locator('#show-regions').click()
        page.evaluate("viewer.execute({name:'highlight_regions', arguments:{region_ids:[]}})")
        assert len(page.evaluate('viewer.getState().visible')) == 37
        page.evaluate("viewer.execute({name:'set_visibility', arguments:{region_ids:['CSF'], visible:true}})")
        assert 'CSF' in page.evaluate('viewer.getState().visible')
        page.locator('#show-regions').click()
        assert 'CSF' not in page.evaluate('viewer.getState().visible')
        page.evaluate("viewer.execute({name:'highlight_regions', arguments:{region_ids:['Left-Hippocampus']}}); viewer.execute({name:'reset_view', arguments:{}})")
        assert len(page.evaluate('viewer.getState().visible')) == 37
        assert 'CSF' not in page.evaluate('viewer.getState().visible')
        assert page.evaluate('viewer.getState().highlighted') == []
        assert all(value == 1 for value in page.evaluate('viewer.getState().opacities').values())
        assert not errors, errors
        browser.close()
        print('PASS: 100%/1% visual focus, whole-brain visibility, highlight/clear, opacity, reset.')
finally:
    server.shutdown()
