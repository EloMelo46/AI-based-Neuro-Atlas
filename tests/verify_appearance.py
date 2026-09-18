"""Real WebGL appearance/state regression and screenshots; no paid API calls."""
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
    output = PROJECT_ROOT / 'verification'
    output.mkdir(exist_ok=True)
    server = make_server('127.0.0.1', 0, app, threaded=True)
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        with patch('main.brain_assistant._api_key', side_effect=AssertionError('Live API disabled')), \
                sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='chrome', headless=True,
                                                 args=['--enable-unsafe-swiftshader'])
            page = browser.new_page(viewport={'width': 1600, 'height': 1000})
            page.set_default_timeout(120000)
            errors, mesh_requests = [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('console', lambda msg: errors.append(msg.text) if msg.type == 'error' else None)
            page.on('request', lambda req: mesh_requests.append(req.url) if '/mesh/' in req.url else None)
            page.on('requestfailed', lambda req: errors.append(f'{req.url}: {req.failure}'))
            source = (PROJECT_ROOT / 'static/brain_viewer.js').read_text(encoding='utf-8')
            page.route('**/static/brain_viewer.js', lambda route: route.fulfill(
                body=source + '\nexport { camera, controls, brain, renderer, caps, regions };\n',
                content_type='text/javascript'))
            page.route('**/api/assistant/config', lambda route: route.fulfill(json={'configured': True}))

            def load(detail='optimized'):
                page.goto(f'http://127.0.0.1:{server.server_port}/?detail={detail}')
                page.locator('#auto-rotate').uncheck()
                page.evaluate("""async () => {
                  window.view = await import('/static/brain_viewer.js');
                  window.viewer = view.assistantViewer;
                  window.surface = id => {
                    let mesh;
                    view.brain.getObjectByName(id + '.obj').traverse(o => { if (o.isMesh) mesh = o; });
                    return mesh;
                  };
                  window.materialColor = id => surface(id).material.color.getHexString();
                }""")
                page.wait_for_timeout(250)

            def select(style):
                page.locator('#appearance').select_option(style)
                page.wait_for_timeout(150)
                assert page.locator('body').get_attribute('data-appearance') == style

            def expect_style_state(expected, style):
                state = page.evaluate('viewer.getState()')
                assert state.pop('appearance') == style
                assert state == {key: value for key, value in expected.items() if key != 'appearance'}

            try:
                load()
            except Exception:
                print('Browser errors:', errors, flush=True)
                page.screenshot(path=str(output / 'appearance-error.png'))
                raise
            assert len(page.evaluate('viewer.getState().loaded')) == 38
            assert page.locator('#appearance').input_value() == 'learning'
            assert page.locator('#appearance').is_visible()
            assert page.locator('#appearance-description').count() == 0
            assert not errors, errors
            print('PASS: page loads, appearance selector and 38 regions render without browser errors.', flush=True)
            original_state = page.evaluate('viewer.getState()')
            original_colors = page.evaluate('view.regions.map(r => r.color.getHexString())')
            original_geometry = page.evaluate("view.regions.map(r => surface(r.object.name.slice(0,-4)).geometry.uuid)")
            original_calls = page.evaluate('view.renderer.info.render.calls')
            original_downloads = len(mesh_requests)
            captures = []
            for style in ('learning', 'natural', 'digital'):
                select(style)
                expect_style_state(original_state, style)
                assert page.evaluate("view.regions.map(r => surface(r.object.name.slice(0,-4)).geometry.uuid)") == original_geometry
                assert page.evaluate('view.renderer.info.render.calls') == original_calls
                assert len(mesh_requests) == original_downloads, 'Style changes must not download meshes'
                captures.append(page.locator('#scene').screenshot(path=str(output / f'appearance-{style}.png')))
                page.screenshot(path=str(output / f'appearance-{style}-panel.png'))
            assert len(set(captures)) == 3, 'Styles must visibly differ'
            assert page.evaluate("materialColor('Left-Cerebral-Cortex')") == '123c79'
            print('PASS: three distinct rendered styles reuse geometry/draw calls and preserve view state.', flush=True)

            # The style must survive focus, cuts, opacity, reset and narration.
            page.evaluate("viewer.execute({name:'isolate_regions',arguments:{region_ids:['Left-Hippocampus']}})")
            assert page.evaluate("materialColor('Left-Hippocampus')") == 'f2a060'
            assert page.evaluate("materialColor('Left-Cerebral-Cortex')") == '123c79'
            focused = page.evaluate('viewer.getState()')
            assert focused['opacities']['Left-Hippocampus'] == 1
            assert focused['opacities']['Left-Cerebral-Cortex'] == 0.4
            warm_pixels = page.evaluate("""() => {
              const {renderer, camera, brain} = view;
              renderer.render(brain.parent, camera);
              const gl = renderer.getContext();
              const pixels = new Uint8Array(gl.drawingBufferWidth * gl.drawingBufferHeight * 4);
              gl.readPixels(0, 0, gl.drawingBufferWidth, gl.drawingBufferHeight, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
              let warm = 0;
              for (let i = 0; i < pixels.length; i += 4) {
                const [r, g, b] = pixels.subarray(i, i + 3);
                if (r > 100 && r > g * 1.05 && r > b * 1.15) warm++;
              }
              return warm;
            }""")
            page.screenshot(path=str(output / 'appearance-digital-focus.png'))
            assert warm_pixels > 100, f'The selected region must look warm under blue lights: {warm_pixels}'
            select('natural')
            natural_focus = page.evaluate('viewer.getState()')
            assert natural_focus['highlighted'] == focused['highlighted']
            assert natural_focus['opacities']['Left-Hippocampus'] == 1
            assert natural_focus['opacities']['Left-Cerebral-Cortex'] == 0.03
            assert page.evaluate("materialColor('Left-Hippocampus') === materialColor('Left-Cerebral-Cortex')")
            select('learning')
            expect_style_state(natural_focus, 'learning')
            assert page.evaluate('view.regions.map(r => surface(r.object.name.slice(0,-4)).material.color.getHexString())') == original_colors
            select('digital')
            assert page.evaluate("materialColor('Left-Hippocampus')") == 'f2a060'
            assert page.evaluate('viewer.getState()') == focused
            # A manually chosen opacity must survive appearance changes.
            page.evaluate("viewer.execute({name:'set_opacity',arguments:{region_ids:['Left-Cerebral-Cortex'],opacity:0.5}})")
            select('natural')
            assert page.evaluate("viewer.getState().opacities['Left-Cerebral-Cortex']") == 0.5
            select('digital')
            assert page.evaluate("viewer.getState().opacities['Left-Cerebral-Cortex']") == 0.5

            page.evaluate("viewer.execute({name:'reset_view',arguments:{}})")
            assert page.locator('#appearance').input_value() == 'digital'
            assert page.evaluate("materialColor('Left-Hippocampus')") == '123c79'
            page.evaluate("viewer.execute({name:'set_cut',arguments:{axis:'x',min:0,max:55}})")
            cut_state = page.evaluate('viewer.getState()')
            camera_before = page.evaluate('view.camera.position.toArray()')
            for style in ('natural', 'digital', 'learning'):
                select(style)
                expect_style_state(cut_state, style)
                camera_after = page.evaluate('view.camera.position.toArray()')
                assert all(abs(a-b) < 1e-8 for a, b in zip(camera_before, camera_after))
                assert not page.locator('#auto-rotate').is_checked()
                page.screenshot(path=str(output / f'appearance-{style}-cut.png'))
                if style == 'natural':
                    assert page.evaluate("""() => {
                      const cortex = surface('Left-Cerebral-Cortex').material;
                      const white = surface('Left-Cerebral-White-Matter').material;
                      return cortex.color.equals(white.color) && !cortex.userData.cutColor.equals(white.userData.cutColor);
                    }""")
                    assert page.evaluate("""async () => {
                      const {Color} = await import('three');
                      return view.regions.every(r => new Color(r.swatch.style.backgroundColor).getHex()
                        === surface(r.id).material.userData.cutColor.getHex());
                    }""")
            select('digital')
            page.evaluate("viewer.execute({name:'reset_view',arguments:{}})")
            page.evaluate("viewer.glowRegions(['Left-Cerebral-Cortex'])")
            assert page.evaluate('viewer.getMentionedRegions()') == ['Left-Cerebral-Cortex']
            page.wait_for_timeout(200)
            page.screenshot(path=str(output / 'appearance-digital-narration.png'))
            page.evaluate('viewer.clearMentionGlow()')
            assert page.evaluate("materialColor('Left-Cerebral-Cortex')") == '123c79'
            page.locator('#auto-rotate').check()
            before = page.evaluate('view.camera.position.toArray()')
            select('natural')
            assert page.locator('#auto-rotate').is_checked()
            page.wait_for_timeout(200)
            assert page.evaluate('view.camera.position.toArray()') != before
            print('PASS: 40% digital / 3% other context, manual opacity, tissue cut palette/legend, camera, rotation and narration.', flush=True)

            select('digital')
            load()
            assert page.locator('#appearance').input_value() == 'digital'
            assert page.evaluate("materialColor('Left-Cerebral-Cortex')") == '123c79'
            if not page.locator('#mesh-detail option[value="full"]').is_disabled():
                load('full')
                assert page.locator('#appearance').input_value() == 'digital'
                for style in ('natural', 'digital'):
                    select(style)
                    page.locator('#scene').screenshot(path=str(output / f'appearance-{style}-full.png'))
                    if style == 'natural':
                        for axis in ('x', 'y', 'z'):
                            page.evaluate('(axis) => viewer.execute({name:"set_cut",arguments:{axis,min:0,max:55}})', axis)
                            page.locator('#scene').screenshot(path=str(output / f'appearance-natural-cut-{axis}-full.png'))
                            page.locator('#reset-cuts').click()
                        page.evaluate("viewer.execute({name:'reset_view',arguments:{}})")
                assert len(page.evaluate('viewer.getState().loaded')) == 38
                print('PASS: full-detail geometry also renders both new styles and retains the saved choice.', flush=True)
            page.set_viewport_size({'width': 390, 'height': 844})
            page.locator('[data-panel="regions"]').click()
            assert page.locator('#appearance').is_visible()
            select('natural')
            page.screenshot(path=str(output / 'appearance-mobile.png'))
            page.locator('#cuts').scroll_into_view_if_needed()
            page.screenshot(path=str(output / 'cut-planes-mobile.png'))
            page.set_viewport_size({'width': 1600, 'height': 1000})
            page.evaluate("localStorage.setItem('neuroatlas.appearance', 'invalid')")
            load()
            assert page.locator('#appearance').input_value() == 'learning'
            # Privacy settings must not prevent startup or switching styles.
            page.add_init_script("Object.defineProperty(window, 'localStorage', {get() {throw new Error('Storage blocked')}})")
            load()
            select('natural')
            assert page.evaluate("materialColor('Left-Cerebral-Cortex')") == 'c9a09e'
            assert not errors, errors
            print('PASS: saved choice, mobile control, invalid preference and blocked storage; no console or shader errors.', flush=True)
            browser.close()
    finally:
        server.shutdown()


if __name__ == '__main__':
    main()
