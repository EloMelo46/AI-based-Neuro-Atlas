"""Fake microphone browser regression; no real microphone or billable API calls."""
import os
import sys
from pathlib import Path
from threading import Thread
from unittest.mock import patch
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if __package__ in (None, ''):
    sys.path.insert(0, str(PROJECT_ROOT))

from main.brain_viewer import app

server = make_server('127.0.0.1', 5053, app, threaded=True)
Thread(target=server.serve_forever, daemon=True).start()
captured = []
def transcription(audio, mime):
    assert len(audio) > 100 and mime == 'audio/webm'
    captured.append(len(audio))
    return 'Erkläre mir den Hippocampus.'
try:
    with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-only'}), patch('main.brain_assistant.transcribe_audio', side_effect=transcription), patch('main.brain_assistant.call_openai', return_value={
        'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text',
        'text': 'Die Mikrofoneingabe wurde empfangen.', 'annotations': []}]}]}), sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='chrome', headless=True,
            args=['--enable-unsafe-swiftshader', '--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'])
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto('http://127.0.0.1:5053')
        page.wait_for_function("!document.querySelector('#assistant-mic').disabled", timeout=120000)
        page.locator('#assistant-speak').uncheck()
        page.locator('#assistant-mic').click()
        page.wait_for_function("document.querySelector('#assistant-mic').getAttribute('aria-pressed') === 'true'")
        assert page.locator('#assistant-send').is_disabled()
        page.wait_for_timeout(1300)
        page.locator('#assistant-mic').click()
        page.wait_for_function("document.querySelector('#assistant-messages').textContent.includes('Die Mikrofoneingabe wurde empfangen.')")
        assert captured
        assert not page.locator('#assistant-mic').is_disabled()
        assert 'Erkläre mir den Hippocampus.' in page.locator('#assistant-messages').inner_text()
        # Permission rejection must leave text chat usable.
        page.evaluate("() => { navigator.mediaDevices.getUserMedia = async () => { throw new DOMException('denied', 'NotAllowedError'); }; }")
        page.locator('#assistant-mic').click()
        page.wait_for_function("document.querySelector('#assistant-messages').textContent.includes('Mikrofonzugriff verweigert')")
        assert not page.locator('#assistant-send').is_disabled()
        assert not errors, errors
        print('PASS: fake microphone capture/upload, automatic chat submission, mic reset, permission denial, no JS errors.')
        browser.close()
finally:
    server.shutdown()
