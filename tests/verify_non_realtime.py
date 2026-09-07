"""Non-Realtime browser regression with mocked OpenAI streaming; no billable calls."""
import json
import os
import sys
from pathlib import Path
from threading import Thread
from unittest.mock import patch

from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if __package__ in (None, ''):
    sys.path.insert(0, str(PROJECT_ROOT))

from main.brain_viewer import app


HTML = """
<main>
  <p id="assistant-status"></p><div id="assistant-messages"></div>
  <form id="assistant-form">
    <textarea id="assistant-input" required></textarea>
    <input id="assistant-speak" type="checkbox">
    <select id="assistant-voice"><option value="marin">Marin</option><option value="cedar">Cedar</option></select>
    <button id="assistant-send">Senden</button>
    <button id="assistant-mic" type="button"></button><button id="assistant-new" type="button"></button>
  </form>
  <audio id="assistant-audio"></audio>
</main>
"""


def main():
    server = make_server('127.0.0.1', 5054, app, threaded=True)
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-only'}), sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='chrome', headless=True)
            page = browser.new_page(viewport={'width': 800, 'height': 700})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('**/api/assistant/chat', lambda route: route.fulfill(
                status=200, content_type='application/x-ndjson', body='\n'.join([
                    json.dumps({'type': 'start'}),
                    json.dumps({'type': 'delta', 'text': 'Der Hippocampus '}),
                    json.dumps({'type': 'delta', 'text': 'unterstützt Gedächtnisprozesse.'}),
                    json.dumps({'type': 'result', 'data': {'messages': [{
                        'text': 'Der Hippocampus unterstützt Gedächtnisprozesse.', 'citations': [],
                    }], 'actions': []}}),
                    '',
                ])))
            page.goto('http://127.0.0.1:5054/api/assistant/config')
            page.set_content(HTML)
            page.evaluate("""async () => {
              const { initAssistant } = await import('/static/assistant.js');
              const ids = ['Left-Hippocampus'];
              await initAssistant({
                getState() { return { loaded: ids, visible: ids, highlighted: [],
                  opacities: { 'Left-Hippocampus': 1 }, cuts: { x: [0,100], y: [0,100], z: [0,100] } }; },
                execute() {}, describe() { return 'Aktion ausgeführt.'; },
              });
            }""")
            page.wait_for_function("!document.querySelector('#assistant-send').disabled")
            assert page.locator('#assistant-status').inner_text() == 'Bereit.'
            page.locator('#assistant-input').fill('Was macht der Hippocampus?')
            page.locator('#assistant-send').click()
            page.wait_for_function("document.querySelector('#assistant-status').textContent === 'Bereit.'")
            assert 'Gedächtnisprozesse' in page.locator('#assistant-messages').inner_text()

            # Replace fetch with a deliberately unfinished stream to verify that
            # Escape aborts it immediately and calls the separate cancel route.
            page.unroute('**/api/assistant/chat')
            page.evaluate(r"""() => {
              const realFetch = window.fetch.bind(window);
              window.fetch = (resource, options = {}) => {
                const url = typeof resource === 'string' ? resource : resource.url;
                if (url === '/api/assistant/cancel') return Promise.resolve(new Response(
                  JSON.stringify({ ok: true, active: true, completed: true }),
                  { status: 200, headers: { 'Content-Type': 'application/json' } }));
                if (url !== '/api/assistant/chat') return realFetch(resource, options);
                const encoder = new TextEncoder();
                const stream = new ReadableStream({ start(controller) {
                  controller.enqueue(encoder.encode(
                    '{"type":"start"}\n{"type":"delta","text":"Teilantwort"}\n'));
                  options.signal?.addEventListener('abort', () => controller.error(
                    new DOMException('Antwort unterbrochen', 'AbortError')), { once: true });
                }});
                return Promise.resolve(new Response(stream, { status: 200,
                  headers: { 'Content-Type': 'application/x-ndjson' } }));
              };
            }""")
            page.locator('#assistant-input').fill('Lange Antwort bitte')
            page.locator('#assistant-send').click()
            page.wait_for_function("document.querySelector('#assistant-messages').textContent.includes('Teilantwort')")
            page.keyboard.press('Escape')
            page.wait_for_function("document.querySelector('#assistant-status').textContent === 'Antwort unterbrochen.'")
            assert not errors, errors
            output = PROJECT_ROOT / 'verification'
            output.mkdir(exist_ok=True)
            page.screenshot(path=str(output / 'non_realtime.png'))
            browser.close()
            print('PASS: clean non-Realtime UI, NDJSON deltas, Escape cancellation, and JS modules.')
    finally:
        server.shutdown()


if __name__ == '__main__':
    main()
