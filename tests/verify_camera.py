"""Real viewer camera regression; no billable OpenAI requests."""
import logging
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


def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    server = make_server('127.0.0.1', 0, app, threaded=True)
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        with patch('main.brain_assistant._api_key', side_effect=AssertionError('Live API disabled')), \
                sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='chrome', headless=True,
                                                 args=['--enable-unsafe-swiftshader'])
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('console', lambda msg: errors.append(msg.text) if msg.type == 'error' else None)
            # Expose references only in this test's served module, without adding
            # camera controls or internal geometry to the production AI interface.
            source = (PROJECT_ROOT / 'static/brain_viewer.js').read_text(encoding='utf-8')
            page.route('**/static/brain_viewer.js', lambda route: route.fulfill(
                body=source + '\nexport { camera, controls, brain, cutBounds };\n',
                content_type='text/javascript'))
            page.route('**/api/assistant/config', lambda route: route.fulfill(json={'configured': True}))
            page.goto(f'http://127.0.0.1:{server.server_port}')
            page.locator('#auto-rotate').uncheck()
            page.evaluate("""async () => {
              window.view = await import('/static/brain_viewer.js');
              window.THREE = await import('three');
              window.viewer = view.assistantViewer;
              window.cameraState = () => ({position:view.camera.position.toArray(),
                target:view.controls.target.toArray(), quaternion:view.camera.quaternion.toArray(),
                zoom:view.camera.zoom, rotating:document.getElementById('auto-rotate').checked});
              window.cameraPose = () => {
                const {rotating, ...pose} = cameraState();
                return JSON.stringify(pose);
              };
            }""")
            assert len(page.evaluate('viewer.getState().loaded')) == 38
            assert page.locator('#info').is_visible() and page.locator('#assistant-panel').is_visible()
            assert not errors, errors
            output = PROJECT_ROOT / 'verification'
            output.mkdir(exist_ok=True)
            page.screenshot(path=str(output / 'camera-initial.png'))
            print('PASS: viewer loads and all camera controls render without browser errors.', flush=True)

            # Preserve perspective, zoom and pan, including during automatic rotation.
            page.evaluate("""() => {
              const target = view.controls.target.clone().add(new THREE.Vector3(9, 4, -7));
              const distance = view.camera.position.distanceTo(view.controls.target) * 0.85;
              view.controls.target.copy(target);
              view.camera.position.copy(target).add(new THREE.Vector3(-1, 0.2, -0.7).normalize().multiplyScalar(distance));
              view.controls.update();
            }""")
            for rotating in (False, True):
                page.locator('#auto-rotate').set_checked(rotating)
                page.wait_for_timeout(150)
                assert page.evaluate("""() => {
                  const before = JSON.stringify(cameraState());
                  viewer.execute({name:'isolate_regions', arguments:{region_ids:['Left-Thalamus', 'Right-Thalamus']}});
                  const after = JSON.stringify(cameraState());
                  viewer.execute({name:'highlight_regions', arguments:{region_ids:['Left-Hippocampus']}});
                  return before === after && before === JSON.stringify(cameraState());
                }"""), 'A highlight changed the current camera or rotation setting'
            position = page.evaluate('view.camera.position.toArray()')
            page.wait_for_timeout(300)
            assert page.evaluate('view.camera.position.toArray()') != position, 'Rotation did not continue'
            print('PASS: focus and legacy highlight preserve camera, zoom, pan and ongoing rotation.', flush=True)

            # Projection checks include every corner of the complete cut face.
            page.evaluate("""() => {
              window.checkCut = (axis, bound) => {
                const {camera, controls, brain, cutBounds} = view;
                const outward = new THREE.Vector3();
                outward[axis] = bound === 'max' ? 1 : -1;
                outward.transformDirection(brain.matrixWorld);
                const direction = camera.position.clone().sub(controls.target).normalize();
                if (direction.dot(outward) < 0.99999) throw new Error('Camera faces wrong axis/side: ' + axis + bound);
                if (camera.getWorldDirection(new THREE.Vector3()).dot(outward) > -0.99999) throw new Error('Camera is not looking into the cut');
                if (document.getElementById('auto-rotate').checked) throw new Error('Rotation still active');
                const cuts = viewer.getState().cuts;
                const face = cutBounds.clone();
                for (const name of ['x','y','z']) {
                  const size = cutBounds.max[name] - cutBounds.min[name];
                  face.min[name] = cutBounds.min[name] + size * cuts[name][0] / 100;
                  face.max[name] = cutBounds.min[name] + size * cuts[name][1] / 100;
                }
                face.min[axis] = face.max[axis] = face[bound][axis];
                for (const x of [face.min.x,face.max.x]) for (const y of [face.min.y,face.max.y]) for (const z of [face.min.z,face.max.z]) {
                  const projected = new THREE.Vector3(x,y,z).applyMatrix4(brain.matrixWorld).project(camera);
                  if (Math.abs(projected.x) > 1.001 || Math.abs(projected.y) > 1.001 || Math.abs(projected.z) > 1.001) {
                    throw new Error('Cut face extends outside viewport: ' + axis + ' ' + projected.toArray());
                  }
                }
              };
            }""")
            for axis in ('x', 'y', 'z'):
                for bound, lower, upper in (('min', 20, 100), ('max', 0, 80)):
                    page.evaluate("viewer.execute({name:'reset_view',arguments:{}})")
                    page.locator('#auto-rotate').check()
                    page.evaluate("""({axis,min,max,bound}) => {
                      viewer.execute({name:'set_cut',arguments:{axis,min,max}});
                      checkCut(axis,bound);
                    }""", {'axis': axis, 'min': lower, 'max': upper, 'bound': bound})
                    before = page.evaluate('cameraState()')
                    page.wait_for_timeout(200)
                    after = page.evaluate('cameraState()')
                    assert all(abs(a - b) < 1e-6 for key in ('position', 'target', 'quaternion')
                               for a, b in zip(before[key], after[key])), (axis, bound, before, after)
                    page.evaluate('({axis,bound}) => checkCut(axis,bound)', {'axis': axis, 'bound': bound})
                    if bound == 'max':
                        page.screenshot(path=str(output / f'camera-cut-{axis}.png'))
                    # Highlighting clears cuts, preserves the pose and resumes rotation.
                    assert page.evaluate("""() => {
                      const before = cameraPose();
                      viewer.execute({name:'isolate_regions',arguments:{region_ids:['Right-Thalamus']}});
                      return before === cameraPose() && cameraState().rotating &&
                        Object.values(viewer.getState().cuts).every(([min,max]) => min === 0 && max === 100);
                    }""")
            print('PASS: X/Y/Z cuts face both exposed sides, fit the full section and stay steady.', flush=True)

            # Slabs choose the nearby face; editing a slider chooses that boundary.
            page.evaluate("""() => {
              viewer.execute({name:'reset_view',arguments:{}});
              viewer.execute({name:'set_cut',arguments:{axis:'x',min:0,max:80}});
              viewer.execute({name:'set_cut',arguments:{axis:'x',min:20,max:70}});
              checkCut('x','max');
              const input = document.getElementById('x-min');
              input.value = '30';
              input.dispatchEvent(new Event('input',{bubbles:true}));
              checkCut('x','min');
              viewer.execute({name:'set_cut',arguments:{axis:'x',min:25,max:65}});
              checkCut('x','min');
              viewer.execute({name:'set_cut',arguments:{axis:'y',min:0,max:60}});
              checkCut('y','max');
              const before = JSON.stringify(cameraState());
              viewer.execute({name:'set_cut',arguments:{axis:'y',min:0,max:100}});
              if (JSON.stringify(cameraState()) !== before) throw new Error('Removing a cut moved camera');
              const poseBeforeReset = cameraPose();
              document.getElementById('reset-cuts').click();
              if (cameraPose() !== poseBeforeReset) throw new Error('Resetting cuts moved camera');
              if (!cameraState().rotating) throw new Error('Resetting the last cut did not resume rotation');
            }""")
            # Pauses survive repeated edits and multiple axes, for both slider
            # and assistant changes. Explicitly disabled rotation remains off.
            for rotating in (False, True):
                for removal in ('slider', 'assistant', 'reset'):
                    page.locator('#auto-rotate').set_checked(rotating)
                    page.evaluate("""({rotating, removal}) => {
                      const edit = (id,value) => {
                        const input = document.getElementById(id);
                        input.value = value;
                        input.dispatchEvent(new Event('input',{bubbles:true}));
                      };
                      edit('x-max',80);
                      edit('x-max',70);
                      viewer.execute({name:'set_cut',arguments:{axis:'y',min:10,max:100}});
                      if (cameraState().rotating) throw new Error('Cut did not pause rotation');
                      edit('x-max',100);
                      if (cameraState().rotating) throw new Error('Rotation resumed with another cut active');
                      const pose = cameraPose();
                      if (removal === 'slider') edit('y-min',0);
                      else if (removal === 'assistant') viewer.execute({name:'set_cut',arguments:{axis:'y',min:0,max:100}});
                      else document.getElementById('reset-cuts').click();
                      if (cameraPose() !== pose) throw new Error('Removing cuts reset the camera');
                      if (cameraState().rotating !== rotating) throw new Error('Prior rotation choice was not restored');
                    }""", {'rotating': rotating, 'removal': removal})
            before_rotation = page.evaluate('view.camera.position.toArray()')
            page.wait_for_timeout(300)
            assert page.evaluate('view.camera.position.toArray()') != before_rotation, 'Resumed rotation did not render'
            # Turning rotation on and then off while inspecting a cut is an
            # explicit user choice; clearing that cut must not override it.
            page.evaluate("viewer.execute({name:'set_cut',arguments:{axis:'z',min:0,max:70}})")
            page.locator('#auto-rotate').check()
            page.locator('#auto-rotate').uncheck()
            page.locator('#reset-cuts').click()
            assert not page.locator('#auto-rotate').is_checked()
            page.locator('#reset-cuts').click()
            assert not page.locator('#auto-rotate').is_checked()
            print('PASS: last cut removal resumes actual rotation; repeated edits, multi-axis cuts and manual overrides preserve user intent.', flush=True)
            # An axis change must also consume any residual mouse-drag damping.
            canvas = page.locator('#scene canvas').bounding_box()
            x, y = canvas['x'] + canvas['width'] / 2, canvas['y'] + canvas['height'] / 2
            page.mouse.move(x, y)
            page.mouse.down()
            page.mouse.move(x + 110, y + 30, steps=3)
            page.mouse.up()
            page.evaluate("""() => {
              viewer.execute({name:'set_cut',arguments:{axis:'y',min:0,max:50}});
              checkCut('y','max');
            }""")
            page.wait_for_timeout(400)
            page.evaluate("checkCut('y','max')")
            page.set_viewport_size({'width': 700, 'height': 1000})
            page.wait_for_timeout(300)
            page.evaluate("""() => {
              viewer.execute({name:'set_cut',arguments:{axis:'x',min:0,max:50}});
              checkCut('x','max');
            }""")
            page.screenshot(path=str(output / 'camera-cut-portrait.png'))
            assert not errors, errors
            browser.close()
            print('PASS: slab sides, manual sliders, combined cuts, damping and narrow viewport.', flush=True)
    finally:
        server.shutdown()


if __name__ == '__main__':
    main()
