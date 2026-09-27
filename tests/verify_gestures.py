"""Local browser + Flask + gesture state integration; no OpenAI calls or mouse events."""
import logging
import os
from pathlib import Path
from threading import Thread
from unittest.mock import patch

from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server
from main.brain_viewer import app, gestures

ROOT = Path(__file__).resolve().parent.parent


def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    server = make_server('127.0.0.1', 0, app, threaded=True)
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as playwright, patch('main.brain_assistant._api_key', return_value=''):
            browser = playwright.chromium.launch(
                executable_path=os.environ.get('CHROMIUM_PATH', '/usr/bin/chromium'),
                headless=True, args=['--enable-unsafe-swiftshader'])
            page = browser.new_page(viewport={'width': 1280, 'height': 900})
            errors, external = [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)
            def guard(route):
                if not route.request.url.startswith(f'http://127.0.0.1:{server.server_port}/'):
                    external.append(route.request.url)
                    route.abort()
                else:
                    route.continue_()
            page.route('**/*', guard)
            source = (ROOT / 'static/brain_viewer.js').read_text()
            page.route('**/static/brain_viewer.js', lambda route: route.fulfill(
                body=source + '\nexport { camera, controls };', content_type='text/javascript'))
            page.goto(f'http://127.0.0.1:{server.server_port}/')
            page.locator('#auto-rotate').uncheck()
            page.wait_for_function("!document.getElementById('reset').disabled", timeout=120000)
            page.evaluate("""async () => {
                window.view = await import('/static/brain_viewer.js');
                window.pose = () => view.camera.position.toArray();
            }""")
            assert page.evaluate('view.assistantViewer.getState().loaded.length') == 38
            assert not errors, errors
            assert not external, external
            output = ROOT / 'verification'
            output.mkdir(exist_ok=True)
            page.screenshot(path=str(output / 'gestures-ready.png'))
            print('PASS: viewer, 38 meshes and gesture controls load entirely locally.', flush=True)
            # The anterior RAS side (+Y) maps to world -Z; retain the oblique angle.
            def assert_front_view():
                assert page.evaluate('view.camera.position.z < view.controls.target.z')
                assert page.evaluate('view.camera.position.x > view.controls.target.x')
                assert page.evaluate('view.camera.position.y > view.controls.target.y')
            assert_front_view()
            page.locator('#reset').click()
            assert_front_view()
            page.evaluate("view.assistantViewer.execute({name:'reset_view', arguments:{}})")
            assert_front_view()
            print('PASS: initial view, reset button and assistant reset face the anterior side obliquely.', flush=True)
            before = page.evaluate('pose()')
            gestures.publish(None, True)
            page.wait_for_function("document.getElementById('gesture-status').textContent.includes('Sparmodus')")
            assert page.evaluate('pose()') == before
            gestures.publish(('grab_start', 0, 0), False)
            page.wait_for_function("document.getElementById('gesture-status').textContent.includes('Gegriffen')")
            target = page.evaluate('view.controls.target.toArray()')
            radius = page.evaluate('view.camera.position.distanceTo(view.controls.target)')
            gestures.publish(('grab_move', 0.08, -0.025), False)
            page.wait_for_function('(old) => JSON.stringify(pose()) !== JSON.stringify(old)', arg=before)
            gestures.publish(('grab_end', 0, 0), False)
            page.wait_for_function("document.getElementById('gesture-status').textContent.includes('Bereit')")
            assert page.locator('#auto-rotate').is_checked()
            released = page.evaluate('pose()')
            page.wait_for_function('(old) => JSON.stringify(pose()) !== JSON.stringify(old)', arg=released, timeout=2000)
            assert page.evaluate('view.controls.target.toArray()') == target
            assert abs(page.evaluate('view.camera.position.distanceTo(view.controls.target)') - radius) < 1e-6
            assert page.evaluate('view.controls.enabled')
            page.screenshot(path=str(output / 'gestures-rotated.png'))
            print('PASS: release immediately resumes rotation, preserving target and zoom.', flush=True)
            # Re-grab pauses immediately, the next release resumes without a timer.
            gestures.publish(('grab_start', 0, 0), False)
            page.wait_for_function("document.getElementById('gesture-status').textContent.includes('Gegriffen')")
            assert not page.locator('#auto-rotate').is_checked()
            grabbed = page.evaluate('pose()')
            page.wait_for_timeout(200)
            assert page.evaluate('pose()') == grabbed
            gestures.publish(('grab_end', 0, 0), False)
            page.wait_for_function("document.getElementById('gesture-status').textContent.includes('Bereit')")
            assert page.locator('#auto-rotate').is_checked()
            page.wait_for_function('(old) => JSON.stringify(pose()) !== JSON.stringify(old)', arg=grabbed, timeout=2000)
            page.locator('#auto-rotate').uncheck()
            print('PASS: re-grab pauses rotation; release resumes immediately; manual rotation toggle remains usable.', flush=True)
            # Test receiver lifecycle without polling/network timing dependencies.
            page.evaluate("""async () => {
                const { createGestureReceiver, rotateView } = await import('/static/gesture_control.js');
                const events = [];
                const receiver = createGestureReceiver({start:()=>events.push('start'), move:(x,y)=>events.push([x,y]), end:()=>events.push('end')});
                const base = {session:'a', connected:true, holding:false, grab_id:0, x:0, y:0};
                receiver.accept(base);
                receiver.accept({...base, grab_id:1, holding:true, x:0.1});
                receiver.accept({...base, grab_id:1, holding:true, x:0.1});
                receiver.accept({...base, grab_id:1, x:0.3});
                if (events.length !== 4 || events[0] !== 'start' || events[3] !== 'end' || Math.abs(events[2][0] - 0.2) > 1e-6) throw Error('lost/duplicate movement');
                receiver.reset();
                receiver.accept({...base, grab_id:1, holding:true, x:0.8});
                if (events.length !== 4) throw Error('replayed movement');
                receiver.accept({...base, grab_id:1, holding:true, x:0.9});
                receiver.accept({...base, connected:false});
                if (events.at(-1) !== 'end') throw Error('stale hold');
                const radius = view.camera.position.distanceTo(view.controls.target);
                rotateView(view.camera, view.controls, 0, 100);
                if (!view.camera.position.toArray().every(Number.isFinite) || Math.abs(view.camera.position.distanceTo(view.controls.target)-radius)>1e-6) throw Error('pole/zoom regression');
            }""")
            assert not errors, errors
            print('PASS: dropped/duplicate updates, reconnect, stale hold and pole clamping.', flush=True)
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
