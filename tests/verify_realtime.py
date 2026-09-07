"""Live OpenAI/WebRTC smoke test. Uses synthetic microphone; incurs API usage."""
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
server = make_server('127.0.0.1', 5055, app, threaded=True)
Thread(target=server.serve_forever, daemon=True).start()
try:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True, args=[
            '--enable-unsafe-swiftshader', '--autoplay-policy=no-user-gesture-required',
            '--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'])
        page = browser.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.add_init_script('''
          const Original = window.RTCPeerConnection;
          window.RTCPeerConnection = class extends Original {
            constructor(...args) { super(...args); window.testPeer = this; }
            createDataChannel(...args) {
              const channel = super.createDataChannel(...args);
              window.testChannel = channel;
              channel.addEventListener('open', () => {
                this.getSenders().forEach(sender => { if (sender.track) sender.track.enabled = false; });
              });
              return channel;
            }
          };
        ''')
        page.goto('http://127.0.0.1:5055')
        page.wait_for_function("!document.querySelector('#realtime-start').disabled", timeout=120000)
        page.locator('#realtime-start').click()
        page.wait_for_function("document.querySelector('#realtime-status').textContent.includes('Verbunden') || document.querySelector('#realtime-start').getAttribute('aria-pressed') === 'false'", timeout=60000)
        assert 'Verbunden' in page.locator('#realtime-status').inner_text(), page.locator('#realtime-status').inner_text()
        assert page.locator('#assistant-send').is_disabled()
        page.evaluate('''() => {
          testChannel.send(JSON.stringify({type:'conversation.item.create',item:{type:'message',role:'user',content:[{type:'input_text',text:'Zeige ausschließlich den linken Hippocampus und setze seine Deckkraft auf 30 Prozent. Führe beide Aktionen aus und bestätige kurz auf Deutsch.'}]}}));
          testChannel.send(JSON.stringify({type:'response.create'}));
        }''')
        page.wait_for_function("document.querySelector('#assistant-messages').textContent.includes('Left-Hippocampus')", timeout=90000)
        page.wait_for_function("document.querySelector('#realtime-audio').currentTime > 0", timeout=60000)
        page.wait_for_function("async () => { const s = (await import('/static/brain_viewer.js')).assistantViewer.getState(); return s.visible.length === 1 && s.visible[0] === 'Left-Hippocampus' && s.opacities['Left-Hippocampus'] === 0.3; }", timeout=90000)
        page.wait_for_function("Array.from(document.querySelectorAll('.assistant-message')).some(e => !e.classList.contains('action') && /30|dreißig/i.test(e.textContent))", timeout=60000)
        assert page.evaluate('''async () => {
          const stats = await testPeer.getStats();
          return [...stats.values()].some(s => s.type === 'inbound-rtp' && s.kind === 'audio' && s.bytesReceived > 0);
        }''')
        page.screenshot(path=str(OUTPUT_DIR / 'realtime.png'))
        page.locator('#realtime-interrupt').click()
        assert page.locator('#realtime-audio').evaluate('a => a.muted')
        assert page.evaluate("testPeer.connectionState === 'connected'")
        page.wait_for_timeout(1000)
        page.evaluate('''() => {
          testChannel.send(JSON.stringify({type:'conversation.item.create',item:{type:'message',role:'user',content:[{type:'input_text',text:'Sage bitte nur: Hallo noch einmal.'}]}}));
          testChannel.send(JSON.stringify({type:'response.create'}));
        }''')
        page.wait_for_function("!document.querySelector('#realtime-audio').muted", timeout=60000)
        page.evaluate('window.testTracks = testPeer.getSenders().map(s => s.track).filter(Boolean)')
        page.locator('#realtime-start').click()
        assert page.evaluate("testTracks.every(t => t.readyState === 'ended') && testPeer.connectionState === 'closed'")
        assert not page.locator('#assistant-send').is_disabled()
        page.evaluate("() => { navigator.mediaDevices.getUserMedia = async () => { throw new DOMException('Denied', 'NotAllowedError'); }; }")
        page.locator('#realtime-start').click()
        page.wait_for_function("document.querySelector('#realtime-status').textContent.includes('verweigert')")
        assert not page.locator('#assistant-send').is_disabled()
        assert not errors, errors
        browser.close()
        print('PASS: live WebRTC, audio packets, tool acknowledgement, transcript, stop cleanup, microphone denial.')
finally:
    server.shutdown()
