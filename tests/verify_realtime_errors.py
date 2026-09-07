"""Offline browser regression: API response failures must not close WebRTC."""
import sys
from pathlib import Path
from threading import Thread
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if __package__ in (None, ''):
    sys.path.insert(0, str(PROJECT_ROOT))

from main.brain_viewer import app

server = make_server('127.0.0.1', 5057, app, threaded=True)
Thread(target=server.serve_forever, daemon=True).start()
try:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page()
        page.route('**/api/assistant/realtime/session', lambda r: r.fulfill(json={'value': 'fake-test'}))
        page.route('https://api.openai.com/**', lambda r: r.fulfill(body='fake-sdp'))
        page.route('http://127.0.0.1:5057/', lambda r: r.fulfill(content_type='text/html', body='''
          <button id="realtime-start">Start</button><button id="realtime-interrupt"></button>
          <p id="realtime-status"></p><audio id="realtime-audio"></audio>
          <p id="realtime-usage"></p><div id="realtime-limits"></div>
          <input id="assistant-web" type="checkbox"><select id="assistant-voice"><option>marin</option></select>
          <script type="module">
            import {initRealtime} from '/static/realtime.js';
            window.messages = []; window.sent = [];
            window.track = {stop() {this.stopped = true;}};
            navigator.mediaDevices.getUserMedia = async () => ({getTracks: () => [track]});
            window.RTCPeerConnection = class {
              constructor() {window.peer = this; this.connectionState = 'connected';}
              addTrack() {}
              createDataChannel() {return window.channel = {readyState:'open',send(value){sent.push(JSON.parse(value));},close(){this.readyState='closed';this.onclose();}};}
              async createOffer() {return {type:'offer',sdp:'test'};}
              async setLocalDescription() {}
              async setRemoteDescription() {channel.onopen();}
              close() {this.connectionState='closed';}
            };
            initRealtime({viewer:{getState:()=>({})},message:t=>messages.push(t),answer(){},onActive:v=>window.active=v}).setAvailable(true);
            window.emit = event => channel.onmessage({data:JSON.stringify(event)});
          </script>'''))
        page.goto('http://127.0.0.1:5057/')
        page.locator('#realtime-start').click()
        page.wait_for_function("document.querySelector('#realtime-status').textContent.includes('Verbunden')")
        page.evaluate("peer.connectionState='disconnected'; peer.onconnectionstatechange()")
        page.wait_for_function("document.querySelector('#realtime-status').textContent.includes('Wiederverbindung')")
        assert page.evaluate('active && !track.stopped')
        page.evaluate("peer.connectionState='connected'; peer.onconnectionstatechange()")
        assert page.evaluate('active && !track.stopped')
        page.evaluate("emit({type:'rate_limits.updated',rate_limits:[{name:'tokens',limit:40000,remaining:1200,reset_seconds:60}]})")
        page.wait_for_function("document.querySelector('#realtime-limits').textContent.includes('60 s')")
        page.evaluate("() => { const e = {type:'response.done',response:{id:'counted',status:'cancelled',usage:{input_tokens:100,output_tokens:20,input_token_details:{cached_tokens:50}}}}; emit(e); emit(e); }")
        page.wait_for_function("document.querySelector('#realtime-usage').textContent.includes('120 Tokens gesamt')")
        assert 'Cache 50' in page.locator('#realtime-usage').inner_text()
        for code in ['server_error', 'insufficient_quota']:
            page.evaluate("code => emit({type:'response.done',response:{id:'test',status:'failed',status_details:{error:{code}}}})", code)
            page.wait_for_function("code => messages.at(-1).includes(code)", arg=code)
            assert page.evaluate("active && peer.connectionState === 'connected' && !track.stopped")
        page.evaluate("emit({type:'rate_limits.updated',rate_limits:[{name:'tokens',limit:40000,remaining:0,reset_seconds:0.05}]})")
        page.evaluate("emit({type:'response.done',response:{id:'limited',status:'failed',status_details:{error:{code:'rate_limit_exceeded',message:'Testdetail von OpenAI'}}}})")
        page.wait_for_function("messages.at(-1).includes('Testdetail von OpenAI') && messages.at(-1).includes('Tokens:')")
        page.wait_for_function("sent.some(e => e.type === 'response.create')", timeout=3000)
        assert 'automatisch erneut gesendet' in page.locator('#realtime-status').inner_text()
        page.evaluate("emit({type:'error',error:{code:'invalid_event',message:'Testdetail'}})")
        page.wait_for_function("messages.at(-1).includes('Testdetail')")
        page.evaluate("emit({type:'output_audio_buffer.stopped'})")
        assert 'Testdetail' in page.locator('#realtime-status').inner_text()
        page.evaluate("emit({type:'input_audio_buffer.speech_started'}); emit({type:'response.created',response:{id:'next'}}); emit({type:'output_audio_buffer.started'})")
        assert page.evaluate('active && !track.stopped')
        page.evaluate("peer.connectionState='failed'; peer.onconnectionstatechange()")
        page.wait_for_function('!active && track.stopped')
        assert '120 Tokens gesamt' in page.locator('#realtime-usage').inner_text()
        assert 'Sitzung beendet' in page.locator('#realtime-limits').inner_text()
        browser.close()
        print('PASS: transient disconnect recovery, response failures preserve connection, later speech accepted, final failure releases mic.')
finally:
    server.shutdown()
