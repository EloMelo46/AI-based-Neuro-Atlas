"""Real local TLS/proxy + fake microphone/model: no real recording or API usage.

Python verifies the generated CA and hostname. The isolated browser context
accepts the test certificate without installing a CA in the system trust store.
"""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import socket
import ssl
import tempfile
from threading import Event, Thread
from unittest.mock import patch
from urllib.request import HTTPSHandler, ProxyHandler, build_opener

from playwright.sync_api import sync_playwright

from main.brain_viewer import app
from main.https_server import PROJECT_ROOT, create_backend, find_caddy, start_process, stop_process, wait_ready


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


captured = []
release_stream = Event()
stream_started = Event()
release_audio = Event()


class AudioStream:
    def __init__(self):
        self.reads = 0
        self.closed = False

    def read(self, _size):
        self.reads += 1
        if self.reads == 1:
            return b'ID3' + b'\0' * 4093
        if self.reads == 2:
            if not release_audio.wait(10):
                raise AssertionError('Proxy buffered audio instead of streaming it')
            return b'\0' * 4096
        return b''

    def close(self):
        self.closed = True


def transcription(audio, mime):
    assert len(audio) > 100 and mime == 'audio/webm'
    captured.append(len(audio))
    return 'Erkläre mir den Thalamus.'


def response_stream(*_args):
    text = 'Die Aufnahme über HTTPS wurde empfangen.'
    yield {'type': 'response.output_text.delta', 'delta': text}
    stream_started.set()
    if not release_stream.wait(10):
        raise AssertionError('Proxy buffered the response instead of streaming it')
    yield {'type': 'response.completed', 'response': {'status': 'completed', 'output': [
        {'type': 'message', 'content': [{'type': 'output_text', 'text': text, 'annotations': []}]}]}}


server = create_backend(0)
thread = Thread(target=server.run, daemon=True)
thread.start()
proxy = None
try:
    with tempfile.TemporaryDirectory(prefix='neuro-https-test-') as temp, ExitStack() as cleanup, \
            patch.dict(os.environ, {'OPENAI_API_KEY': 'test-only'}), \
            patch('main.brain_assistant.transcribe_audio', side_effect=transcription), \
            patch('main.brain_assistant.stream_openai', side_effect=response_stream), \
            patch('main.brain_assistant.open_speech', return_value=AudioStream()) as audio_mock, \
            sync_playwright() as playwright:
        port = free_port()
        storage = Path(temp) / 'caddy'
        env = dict(os.environ, NEURO_TLS_STORAGE=storage.as_posix(), NEURO_BACKEND_PORT=str(server.effective_port),
                   NEURO_HTTPS_SITES=', '.join(f'https://{host}:{port}' for host in ('localhost', '127.0.0.1')))
        env.pop('OPENAI_API_KEY', None)
        proxy = start_process([str(find_caddy()), 'run', '--config', str(PROJECT_ROOT / 'Caddyfile'),
                               '--adapter', 'caddyfile'], env)
        cleanup.callback(stop_process, proxy)
        root = storage / 'pki' / 'authorities' / 'local' / 'root.crt'
        wait_ready(f'https://localhost:{port}/api/assistant/config', [proxy], root)
        verified = build_opener(ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context(cafile=str(root))))
        with verified.open(f'https://127.0.0.1:{port}/api/assistant/config') as response:
            assert response.status == 200 and json.load(response)['configured']
        print('PASS: real TLS certificate chain and localhost/IP SAN verification.', flush=True)

        browser = playwright.chromium.launch(channel='chrome', headless=True, args=[
            '--enable-unsafe-swiftshader', '--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream',
            '--host-resolver-rules=MAP neuro-atlas.test 127.0.0.1', '--no-proxy-server'])
        context = browser.new_context(ignore_https_errors=True, viewport={'width': 1440, 'height': 1000})
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        base = f'https://localhost:{port}'
        page.goto(base, wait_until='domcontentloaded')
        page.wait_for_function("!document.querySelector('#assistant-mic').disabled", timeout=15000)
        page.wait_for_function("document.querySelector('#status').textContent === '38 von 38 Regionen geladen'", timeout=30000)
        assert page.evaluate('window.isSecureContext && !!navigator.mediaDevices?.getUserMedia')
        assert not page.locator('#assistant-mic-hint').is_visible()
        page.locator('#assistant-speak').uncheck()
        page.locator('#assistant-mic').click()
        page.wait_for_function("document.querySelector('#assistant-mic').getAttribute('aria-pressed') === 'true'")
        page.wait_for_timeout(1200)
        page.locator('#assistant-mic').click()
        page.wait_for_function("document.querySelector('#assistant-messages').textContent.includes('Die Aufnahme über HTTPS wurde empfangen.')", timeout=8000)
        assert stream_started.is_set() and not release_stream.is_set()
        assert page.locator('#assistant-send').is_disabled(), 'Model stream is deliberately still open'
        release_stream.set()
        page.wait_for_function("!document.querySelector('#assistant-send').disabled", timeout=10000)
        assert captured and not page.locator('#assistant-mic').is_disabled()
        cookie = next(cookie for cookie in context.cookies() if cookie['name'] == 'neuro_atlas_https')
        assert cookie['secure'] and cookie['httpOnly'] and cookie['sameSite'] == 'Strict'
        assert (context.request.post(base + '/api/assistant/reset', headers={
            'Origin': 'https://other.example', 'X-Brain-Viewer': '1'})).status == 403
        assert (context.request.post(base + '/api/assistant/reset', headers={
            'Origin': base, 'X-Brain-Viewer': '1'})).status == 200
        page.evaluate('''() => {
            window.audioProbe = (async () => {
                const response = await fetch('/api/assistant/speech', {method: 'POST',
                    headers: {'Content-Type': 'application/json', 'X-Brain-Viewer': '1'},
                    body: JSON.stringify({text: 'Hallo.', voice: 'marin'})});
                if (!response.ok) throw new Error('Speech request failed');
                const reader = response.body.getReader();
                const first = await reader.read();
                window.audioFirstBytes = first.value.length;
                let total = first.value.length;
                while (true) {
                    const chunk = await reader.read();
                    if (chunk.done) return total;
                    total += chunk.value.length;
                }
            })();
        }''')
        page.wait_for_function('window.audioFirstBytes > 0', timeout=8000)
        assert not release_audio.is_set()
        release_audio.set()
        assert page.evaluate('window.audioProbe') == 8192
        assert audio_mock.return_value.closed
        print('PASS: 38 meshes over HTTPS, microphone upload, incremental chat/audio, secure session and Origin guard.', flush=True)

        page.set_viewport_size({'width': 390, 'height': 844})
        page.locator('.mobile-nav [data-panel="assistant"]').click()
        assert page.locator('#assistant-mic').is_visible() and page.locator('#assistant-mic').is_enabled()
        page.locator('#assistant-mic').scroll_into_view_if_needed()
        Path('verification').mkdir(exist_ok=True)
        page.screenshot(path='verification/https-mobile.png')
        # This non-localhost HTTP origin resolves locally only inside this browser.
        # Its page is insecure even though the underlying test listener is loopback.
        page.goto(f'http://neuro-atlas.test:{server.effective_port}', wait_until='domcontentloaded')
        page.wait_for_function("document.querySelector('#assistant-status').textContent === 'Bereit.'")
        page.locator('.mobile-nav [data-panel="assistant"]').click()
        assert not page.evaluate('window.isSecureContext')
        assert page.locator('#assistant-mic').is_disabled()
        assert page.locator('#assistant-mic-hint').is_visible()
        assert 'HTTPS' in page.locator('#assistant-mic-hint').inner_text()
        assert page.locator('#assistant-send').is_enabled()
        page.locator('#assistant-mic-hint').scroll_into_view_if_needed()
        page.screenshot(path='verification/http-microphone-hint.png')
        assert not errors, errors
        print('PASS: mobile HTTPS microphone enabled; HTTP microphone disabled with visible explanation; no JS errors.', flush=True)
        browser.close()
finally:
    release_stream.set()
    release_audio.set()
    if proxy:
        stop_process(proxy)
    server.task_dispatcher.shutdown()
    server.close()
    thread.join(timeout=3)
