"""Voice/text -> mocked model -> real tool execution and cursor idle behavior."""
import json
import logging
import os
from pathlib import Path
from threading import Thread
from unittest.mock import patch
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server
from main.brain_viewer import app
from main.viewer_settings import FOCUS_CONTEXT_OPACITIES

ROOT=Path(__file__).resolve().parent.parent

def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    requested=['natural']; acknowledgements=[]; questions=[]
    def transcribe(audio,mime):
        assert len(audio)>100
        return 'Wechsle zum natürlichen Design.'
    def stream(payload,*_):
        assert any(t.get('name')=='set_appearance' for t in payload['tools'])
        results=[i for i in payload['input'] if i.get('type')=='function_call_output']
        if not results:
            questions.append(payload['input'][-1])
            output=[{'type':'function_call','call_id':'design','name':'set_appearance','arguments':json.dumps({'appearance':requested[0]})}]
        else:
            result=json.loads(results[-1]['output']);acknowledgements.append(result)
            output=[{'type':'message','content':[{'type':'output_text','text':'Das Design wurde geändert.','annotations':[]}]}]
        yield {'type':'response.completed','response':{'status':'completed','output':output}}
    server=make_server('127.0.0.1',0,app,threaded=True)
    Thread(target=server.serve_forever,daemon=True).start()
    try:
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test-only'}), patch('main.brain_assistant.transcribe_audio',side_effect=transcribe), \
                patch('main.brain_assistant.stream_openai',side_effect=stream),sync_playwright() as p:
            browser=p.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH','/usr/bin/chromium'),headless=True,
                args=['--enable-unsafe-swiftshader','--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream'])
            page=browser.new_page(viewport={'width':1440,'height':1000})
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            source=(ROOT/'static/brain_viewer.js').read_text()
            page.route('**/static/brain_viewer.js',lambda route:route.fulfill(body=source+'\nexport { camera, controls };',content_type='text/javascript'))
            page.goto(f'http://127.0.0.1:{server.server_port}/')
            page.wait_for_function("!document.querySelector('#reset').disabled",timeout=120000)
            page.wait_for_function("!document.querySelector('#assistant-send').disabled")
            page.locator('#auto-rotate').uncheck();page.locator('#assistant-speak').uncheck()
            page.evaluate("""async () => {
                window.view=await import('/static/brain_viewer.js'); window.viewer=view.assistantViewer;
                viewer.execute({name:'isolate_regions',arguments:{region_ids:['Left-Hippocampus']}});
                viewer.execute({name:'set_opacity',arguments:{region_ids:['Left-Hippocampus'],opacity:0.6}});
                viewer.execute({name:'set_cut',arguments:{axis:'z',min:0,max:70}});
                window.cameraPose=()=>({position:view.camera.position.toArray(),target:view.controls.target.toArray()});
            }""")
            before=page.evaluate('viewer.getState()');pose=page.evaluate('cameraPose()')
            for i,style in enumerate(('natural','digital','learning')):
                requested[0]=style
                if i==0:
                    page.locator('#assistant-mic').click()
                    page.wait_for_function("document.querySelector('#assistant-mic').getAttribute('aria-pressed')==='true'")
                    page.wait_for_timeout(1100)
                    page.locator('#assistant-mic').click()
                else:
                    page.locator('#assistant-input').fill('Wechsle zu '+style)
                    page.locator('#assistant-send').click()
                page.wait_for_function('(style)=>document.body.dataset.appearance===style',arg=style)
                page.wait_for_function("!document.querySelector('#assistant-send').disabled")
                assert acknowledgements[-1]['ok'],acknowledgements
                assert acknowledgements[-1]['state']['appearance']==style
                assert page.locator('#appearance').input_value()==style
                assert page.evaluate("localStorage.getItem('neuroatlas.appearance')")==style
                state=page.evaluate('viewer.getState()')
                for field in ('loaded','visible','highlighted','cuts'):
                    assert state[field]==before[field],field
                assert state['opacities']['Left-Hippocampus']==.6
                assert state['opacities']['Right-Hippocampus']==FOCUS_CONTEXT_OPACITIES[style]
                actual_pose=page.evaluate('cameraPose()')
                assert all(abs(a-b)<1e-6 for field in pose for a,b in zip(actual_pose[field],pose[field])), (pose,actual_pose)
            assert len(acknowledgements)==3
            print('PASS: voice and text tool roundtrips, all designs, selector/storage, camera/cuts/selection/manual opacity preserved.',flush=True)
            # Manual selector still uses the same code after tool execution.
            page.locator('#appearance').select_option('natural')
            assert page.evaluate('viewer.getState().appearance')=='natural'
            page.reload()
            page.wait_for_function("!document.querySelector('#reset').disabled",timeout=120000)
            assert page.locator('#appearance').input_value()=='natural'
            # Real mouse events and computed CSS, including interactive descendants.
            page.locator('#reset').hover()
            assert not page.evaluate("document.body.classList.contains('cursor-idle')")
            page.wait_for_function("document.body.classList.contains('cursor-idle')",timeout=5000)
            for selector in ('#reset','#scene canvas','#assistant-input'):
                assert page.locator(selector).evaluate('(e)=>getComputedStyle(e).cursor')=='none'
            page.mouse.move(700,420)
            assert not page.evaluate("document.body.classList.contains('cursor-idle')")
            page.locator('#fullscreen-toggle').click()
            page.wait_for_function("document.body.classList.contains('cursor-idle')",timeout=5000)
            assert page.locator('#scene canvas').evaluate('(e)=>getComputedStyle(e).cursor')=='none'
            page.mouse.move(701,421)
            assert not page.evaluate("document.body.classList.contains('cursor-idle')")
            page.wait_for_timeout(300)
            output=ROOT/'verification';output.mkdir(exist_ok=True)
            page.screenshot(path=str(output/'design-command-natural.png'))
            assert not errors,errors
            print('PASS: manual selector and persistence; cursor hides after 3 s and reappears on movement in normal/fullscreen views; no JS errors.',flush=True)
            browser.close()
    finally:
        server.shutdown();server.server_close()

if __name__=='__main__':main()
