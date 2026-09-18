"""Reproduce cortex -> thalamus through the real UI/API with mocked model calls."""
import copy
import json
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


def assert_focus(state, targets):
    assert set(state['highlighted']) == set(targets), state
    assert set(state['visible']) == set(state['loaded']) - ({'CSF'} - set(targets)), state
    for region_id in state['visible']:
        context = 0.4 if state.get('appearance') == 'digital' else 0.03
        assert state['opacities'][region_id] == (1 if region_id in targets else context), state
    assert all(interval == [0, 100] for interval in state['cuts'].values()), state


def main():
    responses, payloads = [], []
    output = PROJECT_ROOT / 'verification'
    output.mkdir(exist_ok=True)

    def stream(payload, _entry):
        payloads.append(copy.deepcopy(payload))
        response = responses.pop(0)
        yield {'type': 'response.completed', 'response': response}

    server = make_server('127.0.0.1', 0, app, threaded=True)
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        with patch('main.brain_assistant.stream_openai', side_effect=stream), \
                patch('main.brain_assistant._api_key', side_effect=AssertionError('Live API disabled')), \
                sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='chrome', headless=True,
                                                 args=['--enable-unsafe-swiftshader'])
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)
            page.route('**/api/assistant/config', lambda route: route.fulfill(json={'configured': True}))
            page.goto(f'http://127.0.0.1:{server.server_port}/?detail=optimized')
            page.locator('#auto-rotate').uncheck()
            page.locator('#assistant-speak').uncheck()
            page.evaluate("async () => { window.viewer = (await import('/static/brain_viewer.js')).assistantViewer; }")
            loaded = page.evaluate('viewer.getState().loaded')
            assert len(loaded) == 38
            assert not set(loaded) & {'lh.pial', 'rh.pial', 'lh.white', 'rh.white', 'lh_hippo_mc'}
            assert 'CSF' not in page.evaluate('viewer.getState().visible')

            def ask(question, targets, name='isolate_regions', explanation='Anatomische Erklärung.'):
                responses.extend([
                    {'output': [{'type': 'function_call', 'call_id': 'focus', 'name': name,
                                 'arguments': json.dumps({'region_ids': targets})}]},
                    {'output': [{'type': 'message', 'content': [{'type': 'output_text',
                                 'text': explanation, 'annotations': []}]}]},
                ])
                page.locator('#assistant-input').fill(question)
                page.locator('#assistant-send').click()
                page.wait_for_function("document.getElementById('assistant-status').textContent === 'Bereit.' && !document.getElementById('assistant-send').disabled")
                state = page.evaluate('viewer.getState()')
                assert_focus(state, targets)
                receipt = next(json.loads(item['output']) for item in payloads[-1]['input']
                               if item.get('type') == 'function_call_output')
                assert receipt['ok'], receipt
                assert not receipt['error'], receipt
                assert receipt['state'] == state, receipt
                percent = 40 if state.get('appearance') == 'digital' else 3
                assert page.locator('.assistant-message.action').last.inner_text().startswith(f'Zielareale hervorgehoben (Umgebung {percent} %)')
                assert page.locator('.assistant-message.error').count() == 0
                assert page.locator('.assistant-message').last.inner_text() == explanation
                assert 'Beginne deine Antwort direkt mit der fachlichen Erklärung.' in payloads[-1]['instructions']
                print('PASS:', question, flush=True)
                return state

            cortex = ['Left-Cerebral-Cortex', 'Right-Cerebral-Cortex']
            thalamus = ['Left-Thalamus', 'Right-Thalamus']
            ask('Zeige die Grosshirnrinde.', cortex)
            page.wait_for_timeout(700)
            cortex_image = page.locator('#scene canvas').screenshot()

            # A new focus must also recover hidden targets/context and old cuts.
            page.evaluate("viewer.execute({name:'set_cut', arguments:{axis:'x', min:0, max:0}})")
            page.evaluate("viewer.execute({name:'set_visibility', arguments:{region_ids:['Left-Thalamus','Right-Hippocampus'], visible:false}})")
            ask('Zeige mir den Thalamus.', thalamus)
            page.wait_for_timeout(700)
            thalamus_image = page.locator('#scene canvas').screenshot()
            assert thalamus_image != cortex_image, 'Cortex -> thalamus must visibly change the model'

            # Even a legacy model response must apply visible focus, not selection only.
            ask('Markiere den Thalamus erneut.', thalamus, name='highlight_regions')
            page.wait_for_timeout(700)
            assert page.locator('#scene canvas').screenshot() == thalamus_image

            ask('Zeige ausdruecklich die Gehirnfluessigkeit CSF.', ['CSF'])
            ask('Zeige wieder den Thalamus.', thalamus)
            page.locator('#appearance').select_option('digital')
            assert_focus(page.evaluate('viewer.getState()'), thalamus)
            ask('Zeige den Hippocampus im digitalen Modus.', ['Left-Hippocampus', 'Right-Hippocampus'])
            page.locator('#appearance').select_option('natural')
            ask('Zeige den Thalamus im natürlichen Modus.', thalamus)
            page.locator('#appearance').select_option('learning')
            for style in ('learning', 'natural', 'digital'):
                page.locator('#appearance').select_option(style)
                ask('Zeige den Hippocampus und den Thalamus und erkläre sie.',
                    ['Left-Hippocampus', 'Right-Hippocampus', *thalamus],
                    explanation='Der Hippocampus ist wichtig für neue Erinnerungen. Der Thalamus verarbeitet und verteilt Informationen.')
            page.screenshot(path=str(output / 'focus-hippocampus-thalamus.png'))
            page.locator('#appearance').select_option('learning')
            page.evaluate("viewer.execute({name:'reset_view', arguments:{}})")
            reset = page.evaluate('viewer.getState()')
            assert set(reset['visible']) == set(reset['loaded']) - {'CSF'}
            assert reset['highlighted'] == []
            assert all(opacity == 1 for opacity in reset['opacities'].values())

            # The anatomical cortex can become transparent without an opaque pial duplicate.
            page.wait_for_timeout(700)
            opaque_image = page.locator('#scene canvas').screenshot()
            page.evaluate('(ids) => viewer.execute({name:"set_opacity", arguments:{region_ids:ids, opacity:0.1}})', cortex)
            state = page.evaluate('viewer.getState()')
            assert all(state['opacities'][region_id] == (0.1 if region_id in cortex else 1)
                       for region_id in state['visible'])
            assert 'CSF' not in state['visible']
            page.wait_for_timeout(700)
            transparent_image = page.locator('#scene canvas').screenshot()
            assert transparent_image != opaque_image
            assert not errors, errors
            assert not responses, responses
            (output / 'focus-cortex.png').write_bytes(cortex_image)
            (output / 'focus-thalamus.png').write_bytes(thalamus_image)
            (output / 'anatomical-cortex-opacity.png').write_bytes(transparent_image)
            browser.close()
            print('PASS: focus in all styles, 40%/3% context, CSF opt-in, old cuts, per-action acknowledgements, reset.')
    finally:
        server.shutdown()


if __name__ == '__main__':
    main()
