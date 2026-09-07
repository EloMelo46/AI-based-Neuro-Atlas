"""Live OpenAI integration check; uses the configured key and incurs API usage."""
import sys
from pathlib import Path
from threading import Thread
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if __package__ in (None, ''):
    sys.path.insert(0, str(PROJECT_ROOT))

from main.brain_viewer import app

server = make_server('127.0.0.1', 5052, app, threaded=True)
Thread(target=server.serve_forever, daemon=True).start()
try:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='chrome', headless=True, args=['--enable-unsafe-swiftshader'])
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto('http://127.0.0.1:5052')
        page.wait_for_function("!document.querySelector('#assistant-send').disabled", timeout=120000)
        page.locator('#assistant-input').fill('Markiere nur den linken Hippocampus und setze den X-Schnitt von 0 bis 50 Prozent.')
        page.locator('#assistant-send').click()
        page.wait_for_function("document.querySelector('#assistant-status').textContent === 'Bereit.' || document.querySelector('#assistant-status').textContent === 'Anfrage fehlgeschlagen.'", timeout=180000)
        assert page.locator('#assistant-status').inner_text() == 'Bereit.', page.locator('#assistant-messages').inner_text()
        state = page.evaluate("async () => (await import('/static/brain_viewer.js')).assistantViewer.getState()")
        assert len(state['visible']) == 43, state
        assert state['highlighted'] == ['Left-Hippocampus'], state
        assert state['opacities']['Left-Hippocampus'] == 1, state
        assert all(value == 0.01 for key, value in state['opacities'].items()
                   if key != 'Left-Hippocampus'), state
        assert state['cuts']['x'] == [0, 50], state
        page.locator('#assistant-input').fill('Setze nun die gesamte Ansicht zurück.')
        page.locator('#assistant-send').click()
        page.wait_for_function("!document.querySelector('#assistant-send').disabled", timeout=180000)
        state = page.evaluate("async () => (await import('/static/brain_viewer.js')).assistantViewer.getState()")
        assert len(state['visible']) == 43 and state['highlighted'] == [] and state['cuts']['x'] == [0,100], state
        output = PROJECT_ROOT / 'verification'
        output.mkdir(exist_ok=True)
        page.screenshot(path=str(output / 'assistant.png'))
        assert not errors, errors
        print('PASS: live OpenAI chat, 100%/1% focus, whole-brain view, cut, reset, no JS errors.')
        browser.close()
finally:
    server.shutdown()
