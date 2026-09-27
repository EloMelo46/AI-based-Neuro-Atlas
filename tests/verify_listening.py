"""Real viewer + gesture HTTP polling + fake audio; no camera or paid API calls."""
import logging
import os
from pathlib import Path
from threading import Event, Thread
from unittest.mock import patch
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server
from main.brain_viewer import app
from main.gesture_service import GestureService

ROOT=Path(__file__).resolve().parent.parent

def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    service=GestureService()
    raised=Event(); stop=Event()
    def heartbeat():
        while not stop.is_set():
            service.publish(None,False,listening=raised.is_set())
            stop.wait(.04)
    worker=Thread(target=heartbeat,daemon=True); worker.start()
    server=make_server('127.0.0.1',0,app,threaded=True)
    Thread(target=server.serve_forever,daemon=True).start()
    uploads=[]
    def transcribe(audio,mime):
        assert len(audio)>100 and mime=='audio/webm'
        uploads.append(len(audio)); return 'Zeige den Hippocampus.'
    def response_stream(*_args):
        yield {'type':'response.completed','response':{'status':'completed','output':[{'type':'message','content':[
            {'type':'output_text','text':'Testantwort.','annotations':[]}]}]}}
    try:
        with patch('main.brain_viewer.gestures',service), patch.dict(os.environ,{'OPENAI_API_KEY':'test-only'}), \
                patch('main.brain_assistant.transcribe_audio',side_effect=transcribe), \
                patch('main.brain_assistant.stream_openai',side_effect=response_stream), sync_playwright() as p:
            browser=p.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH','/usr/bin/chromium'),headless=True,
                args=['--enable-unsafe-swiftshader','--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream'])
            page=browser.new_page(viewport={'width':1440,'height':1000})
            errors=[]; page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}/')
            page.wait_for_function("!document.querySelector('#reset').disabled",timeout=120000)
            page.wait_for_function("!document.querySelector('#assistant-mic').disabled")
            page.locator('#auto-rotate').uncheck(); page.locator('#assistant-speak').uncheck()
            page.wait_for_function("document.querySelector('#gesture-status').textContent.startsWith('Bereit')")
            def recording(value):
                page.wait_for_function("v => document.querySelector('#assistant-mic').getAttribute('aria-pressed')===String(v)",arg=value)
                assert page.evaluate("document.body.classList.contains('assistant-listening')")==value
            def ready():
                page.wait_for_function("!document.querySelector('#assistant-send').disabled")
            def neutral():
                raised.clear()
                page.wait_for_function("document.querySelector('#gesture-status').textContent.startsWith('Bereit')")
            # Fullscreen real media recording: visible indication and exactly one submission.
            page.locator('#fullscreen-toggle').click()
            raised.set(); recording(True)
            page.wait_for_timeout(1100)
            output=ROOT/'verification'; output.mkdir(exist_ok=True)
            page.screenshot(path=str(output/'listening-fullscreen.png'))
            assert 'drop-shadow' in page.locator('#scene canvas').evaluate('(e)=>getComputedStyle(e).filter')
            neutral(); recording(False); ready()
            page.wait_for_function("document.querySelector('#assistant-messages').textContent.includes('Testantwort.')")
            assert len(uploads)==1
            page.keyboard.press('Escape')
            print('PASS: full viewer, HTTP hold/release, actual fake recording, white shimmer and one automatic submission.',flush=True)
            # Pausing gestures discards audio and requires another neutral pose.
            raised.set(); recording(True); page.wait_for_timeout(300)
            page.locator('#gesture-enabled').uncheck(); recording(False); ready()
            page.locator('#gesture-enabled').check(); page.wait_for_timeout(350)
            assert page.locator('#assistant-mic').get_attribute('aria-pressed')=='false'
            neutral(); assert len(uploads)==1
            # Connection loss cancels, without submitting captured sound.
            raised.set(); recording(True); page.wait_for_timeout(300)
            page.route('**/api/gestures/state',lambda route:route.fulfill(json={'connected':False,'status':'stopped'}))
            recording(False); ready(); assert len(uploads)==1
            raised.clear(); page.unroute('**/api/gestures/state')
            neutral()
            print('PASS: gesture pause and disconnection discard audio, reconnect cannot restart an old hold.',flush=True)
            # Manual microphone ownership survives gesture start/release.
            page.locator('#assistant-mic').click(); recording(True)
            raised.set(); page.wait_for_function("document.querySelector('#gesture-status').textContent.includes('Sprechgeste')")
            neutral(); recording(True)
            page.locator('#assistant-mic').click(); recording(False); ready()
            assert len(uploads)==2
            # Release while getUserMedia permission is pending. Late stream is stopped.
            page.evaluate("""() => {
                window.realGetUserMedia=navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
                navigator.mediaDevices.getUserMedia=()=>new Promise(resolve=>{window.grantMic=resolve;});
            }""")
            raised.set()
            page.wait_for_function("document.querySelector('#assistant-status').textContent.includes('angefragt')")
            assert not page.evaluate("document.body.classList.contains('assistant-listening')")
            neutral(); ready()
            page.evaluate("""async () => {
                window.lateStream=await realGetUserMedia({audio:true});
                grantMic(lateStream);
            }""")
            page.wait_for_function("lateStream.getTracks().every(t=>t.readyState==='ended')")
            recording(False); assert len(uploads)==2
            page.evaluate("() => { navigator.mediaDevices.getUserMedia=realGetUserMedia; }")
            # Denial should happen once per pose, and leave text input usable.
            page.evaluate("""() => {
                window.denials=0;
                navigator.mediaDevices.getUserMedia=async()=>{denials++;throw new DOMException('denied','NotAllowedError');};
            }""")
            raised.set()
            page.wait_for_function("document.querySelector('#assistant-messages').textContent.includes('Mikrofonzugriff verweigert')")
            ready(); page.wait_for_timeout(300); assert page.evaluate('denials')==1
            recording(False); neutral()
            page.evaluate('() => { navigator.mediaDevices.getUserMedia=realGetUserMedia; }')
            print('PASS: manual ownership, release during permission prompt, late stream cleanup and denial without retries.',flush=True)
            # Deterministic time-limit check without a one-minute test delay.
            page.evaluate('window.realNow=Date.now')
            raised.set(); recording(True)
            page.wait_for_timeout(250)
            page.evaluate('Date.now=()=>realNow()+61000')
            recording(False); ready(); page.wait_for_timeout(300)
            assert page.locator('#assistant-mic').get_attribute('aria-pressed')=='false'
            assert len(uploads)==3
            neutral(); page.evaluate('Date.now=realNow')
            # Receiver tests missed release/reconnect and duplicate snapshots.
            page.evaluate("""async () => {
                const {createListenReceiver}=await import('/static/gesture_control.js');
                const events=[];
                const r=createListenReceiver({start:()=>events.push('start'),end:()=>events.push('end'),cancel:()=>events.push('cancel')});
                const s={session:'a',connected:true,listening:true,listen_id:1};
                r.accept(s);r.accept(s);
                if(events.length) throw Error('replayed held pose');
                r.accept({...s,listening:false});r.accept(s);r.accept(s);
                r.accept({...s,listen_id:2});
                r.accept({...s,connected:false});
                if(JSON.stringify(events)!==JSON.stringify(['start','cancel','start','cancel'])) throw Error(JSON.stringify(events));
            }""")
            assert not errors,errors
            print('PASS: 60-second cap, no restart while held, receiver duplicate/missed state handling, no JS errors.',flush=True)
            browser.close()
    finally:
        stop.set();worker.join(timeout=2)
        server.shutdown();server.server_close()

if __name__=='__main__':main()
