"""Unit tests for assistant routes and validation without live API calls."""
import copy
import json
import io
import os
import re
import sys
import urllib.error
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if __package__ in (None, ''):
    sys.path.insert(0, str(PROJECT_ROOT))

from main.brain_viewer import app, MESH_DIR
from main.brain_assistant import (validate_action, validate_state, APIError,
    generate_speech, transcribe_audio, tools_for, focus_result_error, DEFAULT_MODEL)
from main.realtime_assistant import create_realtime_secret
from main.mesh_catalog import EXCLUDED_MESH_FILES, available_region_ids


class AssistantTests(unittest.TestCase):
    @staticmethod
    def stream_events(response):
        return [json.loads(line) for line in response.get_data(as_text=True).splitlines() if line]

    @classmethod
    def stream_result(cls, response):
        events = cls.stream_events(response)
        error = next((event.get('error') for event in events if event.get('type') == 'error'), None)
        if error:
            raise APIError(error)
        return next(event['data'] for event in events if event.get('type') == 'result')

    def test_realtime_secret_reports_precise_failures_and_retries_network(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-key'}), \
                patch('main.realtime_assistant.time.sleep') as sleep, \
                patch('main.realtime_assistant.urllib.request.urlopen', side_effect=[
                    urllib.error.URLError('temporary DNS failure'),
                    io.BytesIO(b'{"value":"temporary-test"}'),
                ]) as urlopen:
            self.assertEqual(create_realtime_secret({'type': 'realtime'}), 'temporary-test')
            self.assertEqual(urlopen.call_count, 2)
            sleep.assert_called_once_with(0.5)

        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-key'}), \
                patch('main.realtime_assistant.time.sleep'), \
                patch('main.realtime_assistant.urllib.request.urlopen',
                    side_effect=urllib.error.URLError('certificate verify failed')):
            with self.assertRaisesRegex(APIError, 'Netzwerk, DNS oder TLS.*certificate verify failed'):
                create_realtime_secret({'type': 'realtime'})

        http_error = urllib.error.HTTPError('https://api.openai.com', 400, 'Bad Request', {},
            io.BytesIO(json.dumps({'error': {'message': 'Invalid session option.',
                'code': 'invalid_value'}}).encode()))
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-key'}), \
                patch('main.realtime_assistant.urllib.request.urlopen', side_effect=http_error):
            with self.assertRaisesRegex(APIError, r'HTTP 400.*Invalid session option.*invalid_value'):
                create_realtime_secret({'type': 'realtime'})

    def test_opacity(self):
        for opacity in [0, 0.3, 1]:
            action = validate_action('set_opacity',
                {'region_ids': ['Left-Hippocampus'], 'opacity': opacity}, self.state['loaded'])
            self.assertEqual(action['arguments']['opacity'], opacity)
        for opacity in [-1, 1.1, True, '0.5', float('nan')]:
            with self.assertRaises(ValueError):
                validate_action('set_opacity', {'region_ids': ['Left-Hippocampus'], 'opacity': opacity}, self.state['loaded'])
        self.state['opacities'] = {'Left-Hippocampus': 0.3}
        clean = validate_state(self.state, self.state['loaded'])
        self.assertEqual(clean['opacities']['Left-Hippocampus'], 0.3)
        self.assertEqual(clean['opacities']['Right-Hippocampus'], 1)
        definitions = tools_for(self.state['loaded'])
        self.assertNotIn('focus_regions', [item['name'] for item in definitions])
        self.assertNotIn('highlight_regions', [item['name'] for item in definitions])
        isolate = next(item for item in definitions if item['name'] == 'isolate_regions')
        self.assertIn('3% opacity', isolate['description'])

    def test_realtime_routes_are_disabled(self):
        self.assertEqual(self.client.post('/api/assistant/realtime/session',
            headers=self.headers, json={'state': self.state}).status_code, 404)
        self.assertEqual(self.client.post('/api/assistant/realtime/tool',
            headers=self.headers, json={'state': self.state}).status_code, 404)

    def test_speech_endpoint(self):
        with patch('main.brain_assistant.open_speech', return_value=io.BytesIO(b'ID3-test')) as speech:
            response = self.client.post('/api/assistant/speech', headers=self.headers,
                json={'text': 'Hallo.', 'voice': 'cedar'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, 'audio/mpeg')
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            speech.assert_called_once_with('Hallo.', 'cedar')
        for text, voice in [('', 'marin'), ('x' * 4097, 'marin'), (' ' * 4096 + 'x', 'marin'), ('Hallo', 'fake')]:
            with self.assertRaises(ValueError): generate_speech(text, voice)

        with patch('main.brain_assistant._api_key', return_value='test-only'), \
                patch('main.brain_assistant.urllib.request.urlopen', return_value=io.BytesIO(b'ID3-test')) as upstream:
            text = 'Der Thalamus. ' * 200
            self.assertEqual(generate_speech(text, 'marin'), b'ID3-test')
            self.assertEqual(json.loads(upstream.call_args.args[0].data)['input'], text)

    def test_speech_streams_mentions_without_transcription(self):
        audio = b'mp3-test' * 2000
        recording = io.BytesIO(audio)
        with patch('main.brain_assistant._api_key', return_value='test-only'), \
                patch('main.brain_assistant.urllib.request.urlopen', return_value=recording) as upstream:
            response = self.client.post('/api/assistant/speech', headers=self.headers,
                json={'text': 'Der Thalamus und der Hippocampus.', 'voice': 'marin'}, buffered=False)
            self.assertEqual(response.mimetype, 'audio/mpeg')
            self.assertTrue(response.is_streamed)
            self.assertEqual(recording.tell(), 4096, 'Playback must not wait for the whole download')
            self.assertEqual(response.get_data(), audio)
            self.assertTrue(recording.closed)
            self.assertEqual(upstream.call_count, 1, 'Narration must not request transcription')
            self.assertEqual(upstream.call_args.args[0].full_url, 'https://api.openai.com/v1/audio/speech')

    def test_audio_model_request_defaults(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-only'}, clear=True), \
                patch('main.brain_assistant.urllib.request.urlopen',
                      return_value=io.BytesIO(b'ID3-test')) as urlopen:
            self.assertEqual(generate_speech('Hallo.', 'marin'), b'ID3-test')
            payload = json.loads(urlopen.call_args.args[0].data)
            self.assertEqual(payload, {
                'model': 'gpt-4o-mini-tts', 'voice': 'marin', 'input': 'Hallo.',
                'response_format': 'mp3', 'stream_format': 'audio', 'speed': 1.1,
                'instructions': ('Sprich natürliches, klares Hochdeutsch mit warmer, ruhiger und kompetenter Stimme. '
                    'Nutze ein entspanntes Erklärtempo, dezente lebendige Betonung und kurze sinnvolle Pausen '
                    'zwischen Gedankengängen. Sprich anatomische sowie lateinische Fachbegriffe besonders '
                    'deutlich aus. Vermeide monotones Ablesen und übertriebene Theatralik.'),
            })
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-only'}, clear=True), \
                patch('main.brain_assistant.urllib.request.urlopen',
                      return_value=io.BytesIO(b'{"text":"Hippocampus"}')) as urlopen:
            self.assertEqual(transcribe_audio(b'audio', 'audio/webm'), 'Hippocampus')
            body = urlopen.call_args.args[0].data
            self.assertIn(b'gpt-4o-mini-transcribe', body)
            self.assertIn(b'name="language"\r\n\r\nde', body)
            self.assertIn(b'name="response_format"\r\n\r\njson', body)

    def test_audio_network_error_is_diagnosable(self):
        failure = urllib.error.URLError(PermissionError(13, 'socket access denied'))
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-only'}, clear=True), \
                patch('main.brain_assistant.urllib.request.urlopen', side_effect=failure), \
                self.assertLogs('main.brain_assistant', level='WARNING') as logs:
            with self.assertRaisesRegex(APIError, 'Netzwerkzugriff des Python-Servers'):
                transcribe_audio(b'audio', 'audio/webm')
        self.assertIn('OpenAI transcription network failure', '\n'.join(logs.output))
        self.assertIn('socket access denied', '\n'.join(logs.output))

    def test_audio_upload(self):
        with patch('main.brain_assistant.transcribe_audio', return_value='Zeige den Hippocampus.') as transcribe:
            response = self.client.post('/api/assistant/transcribe', headers=self.headers,
                data={'audio': (io.BytesIO(b'audio-test'), 'speech.webm', 'audio/webm')})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()['text'], 'Zeige den Hippocampus.')
            transcribe.assert_called_once_with(b'audio-test', 'audio/webm')
        self.assertEqual(self.client.post('/api/assistant/transcribe', headers=self.headers).status_code, 400)
        self.assertEqual(self.client.post('/api/assistant/transcribe', headers=self.headers,
            data={'audio': (io.BytesIO(b''), 'speech.webm')}).status_code, 400)
        self.assertEqual(self.client.post('/api/assistant/transcribe', headers=self.headers,
            data={'audio': (io.BytesIO(b'bad'), 'bad.txt', 'text/plain')}).status_code, 400)

    def test_non_realtime_config_and_page(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-only'}, clear=True):
            config = self.client.get('/api/assistant/config').get_json()
        self.assertEqual(config['model'], DEFAULT_MODEL)
        self.assertEqual(config['transcribe_model'], 'gpt-4o-mini-transcribe')
        self.assertEqual(config['speech_model'], 'gpt-4o-mini-tts')
        self.assertFalse(config['realtime'])
        self.assertEqual(config['settings']['reasoning_effort'], 'low')
        self.assertEqual(config['settings']['verbosity'], 'medium')
        self.assertEqual(config['settings']['max_output_tokens'], 1600)
        self.assertEqual(config['settings']['tool_choice'], 'auto')
        self.assertTrue(config['settings']['stream'])
        page = self.client.get('/').get_data(as_text=True)
        self.assertIn('src="/static/assistant_bridge.js"', page)
        self.assertNotIn('id="realtime-start"', page)
        for removed in ('assistant-web', 'assistant-interrupt', 'clear-highlight',
                        'speech-stop', 'speech-status'):
            self.assertNotIn(f'id="{removed}"', page)
        self.assertNotIn('Spracheingabe: gpt-4o-mini-transcribe', page)
        self.assertNotIn('Nicht-Realtime: Mikrofon starten', page)
        self.assertNotIn('Ziehen: drehen · Zwei Finger:', page)
        self.assertNotIn('Je Achse bleibt der Bereich', page)
        self.assertIn('id="mesh-detail"', page)
        self.assertIn(f"576{chr(0x2019)}008 Dreiecke", page)
        self.assertIn(f"2{chr(0x2019)}842{chr(0x2019)}152 Dreiecke", page)
        csf_start = page.index('title="CSF.obj"')
        csf_row = page[csf_start:page.index('</label>', csf_start)]
        self.assertNotIn(' checked', csf_row)

    def test_mesh_detail_routes(self):
        optimized = self.client.get('/mesh/CC_Central.obj?detail=optimized')
        full = self.client.get('/mesh/CC_Central.obj?detail=full')
        self.assertEqual(optimized.status_code, 200)
        self.assertEqual(full.status_code, 200)
        self.assertGreater(len(full.data), len(optimized.data))
        optimized.close()
        full.close()
        self.assertEqual(self.client.get('/mesh/CC_Central.obj?detail=invalid').status_code, 400)
        page = self.client.get('/?detail=full').get_data(as_text=True)
        self.assertIn('<option value="full" selected', page)

    def setUp(self):
        self.client = app.test_client()
        self.headers = {'X-Brain-Viewer': '1'}
        ids = available_region_ids(MESH_DIR)
        self.state = {'loaded': ids, 'visible': ids, 'highlighted': [], 'cuts': {a: [0, 100] for a in 'xyz'}}

    def test_removed_meshes_are_absent_from_page_downloads_and_ai(self):
        page = self.client.get('/').get_data(as_text=True)
        names = json.loads(re.search(r'<script id="mesh-list"[^>]*>(.*?)</script>', page).group(1))
        self.assertEqual(len(names), 38)
        self.assertEqual({name[:-4] for name in names}, set(self.state['loaded']))
        for name in EXCLUDED_MESH_FILES:
            with self.subTest(name=name):
                self.assertTrue((MESH_DIR / name).is_file(), 'Source assets must be retained')
                self.assertNotIn(name, page)
                for detail in ('optimized', 'full'):
                    self.assertEqual(self.client.get(f'/mesh/{name}?detail={detail}').status_code, 404)
                with self.assertRaises(ValueError):
                    validate_action('set_opacity', {'region_ids': [name[:-4]], 'opacity': 1}, self.state['loaded'])
        for name in ('Left-Hippocampus', 'Right-Hippocampus', 'Left-Cerebral-Cortex',
                     'Right-Cerebral-Cortex', 'Left-Cerebral-White-Matter', 'Right-Cerebral-White-Matter', 'CSF'):
            self.assertIn(name, self.state['loaded'])
        response = {'output': [{'type': 'message', 'content': [
            {'type': 'output_text', 'text': 'Hallo.', 'annotations': []}]}]}
        with patch('main.brain_assistant.stream_openai', return_value=iter([
                {'type': 'response.completed', 'response': response}])) as api:
            self.stream_result(self.client.post('/api/assistant/chat', headers=self.headers,
                json={'message': 'Hallo.', 'state': self.state}))
            payload = api.call_args.args[0]
            context = json.loads(payload['instructions'].split('\nKontext: ', 1)[1])
            self.assertEqual(context['regions'], self.state['loaded'])
            self.assertEqual(context['view']['loaded'], self.state['loaded'])
            for definition in payload['tools']:
                properties = definition.get('parameters', {}).get('properties', {})
                if 'region_ids' in properties:
                    self.assertEqual(properties['region_ids']['items']['enum'], self.state['loaded'])
            for name in EXCLUDED_MESH_FILES:
                self.assertNotIn(name[:-4], payload['instructions'])
        stale = copy.deepcopy(self.state)
        stale['loaded'].append('lh.pial')
        self.assertEqual(self.client.post('/api/assistant/chat', headers=self.headers,
            json={'message': 'Hallo.', 'state': stale}).status_code, 400)

    def test_acknowledged_tool_roundtrip(self):
        responses = [
            {'status': 'completed', 'output': [{'type': 'function_call', 'call_id': 'call_1',
                'name': 'isolate_regions', 'arguments': json.dumps({'region_ids': ['Left-Hippocampus']})}]},
            {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text',
                'text': 'Der linke Hippocampus ist markiert.', 'annotations': []}]}]},
        ]
        def events(*_args):
            response = responses.pop(0)
            for item in response.get('output', []):
                for part in item.get('content', []):
                    if part.get('type') == 'output_text':
                        yield {'type': 'response.output_text.delta', 'delta': part['text']}
            yield {'type': 'response.completed', 'response': response}
        with patch('main.brain_assistant.stream_openai', side_effect=events) as api:
            result = self.stream_result(self.client.post('/api/assistant/chat', headers=self.headers,
                json={'message': 'Markiere den linken Hippocampus', 'state': self.state}))
            self.assertEqual(result['actions'][0]['name'], 'isolate_regions')
            self.assertEqual(api.call_count, 1)
            self.state = self.focus_state(['Left-Hippocampus'])
            response = self.client.post('/api/assistant/chat', headers=self.headers, json={
                'turn_id': result['turn_id'], 'results': [{'call_id': 'call_1', 'ok': True}], 'state': self.state})
            self.assertTrue(any(event.get('type') == 'delta' for event in self.stream_events(response)))
            reply = self.stream_result(response)
            self.assertEqual(response.status_code, 200)
            self.assertIn('markiert', reply['messages'][0]['text'])
            payload = api.call_args.args[0]
            tool_output = next(i for i in payload['input'] if i.get('type') == 'function_call_output')
            self.assertTrue(json.loads(tool_output['output'])['ok'])
            self.assertFalse(payload['store'])
            self.assertEqual(payload['model'], DEFAULT_MODEL)
            self.assertEqual(payload['reasoning'], {'effort': 'low'})
            self.assertEqual(payload['text'], {'verbosity': 'medium'})
            self.assertEqual(payload['max_output_tokens'], 1600)
            self.assertTrue(payload['parallel_tool_calls'])
            self.assertIn({'type': 'web_search'}, payload['tools'])

    def focus_state(self, targets):
        state = copy.deepcopy(self.state)
        state['visible'] = [region_id for region_id in state['loaded']
                            if region_id != 'CSF' or region_id in targets]
        state['highlighted'] = targets[:]
        state['opacities'] = {region_id: 1 if region_id in targets or region_id == 'CSF' else 0.03
                              for region_id in state['loaded']}
        return state

    def test_focus_result_rejects_invisible_or_incomplete_emphasis(self):
        targets = ['Left-Thalamus', 'Right-Thalamus']
        action = validate_action('highlight_regions', {'region_ids': targets}, self.state['loaded'])
        self.assertEqual(action['name'], 'isolate_regions')
        state = self.focus_state(targets)
        self.assertEqual(focus_result_error(action, state), '')
        for failure in ['selection', 'target_opacity', 'context_opacity', 'hidden_target',
                        'hidden_context', 'csf', 'cut', 'unloaded_target']:
            with self.subTest(failure=failure):
                broken = copy.deepcopy(state)
                if failure == 'selection':
                    broken['highlighted'] = ['Left-Cerebral-Cortex']
                elif failure == 'target_opacity':
                    broken['opacities']['Left-Thalamus'] = 0.03
                elif failure == 'context_opacity':
                    broken['opacities']['Left-Cerebral-Cortex'] = 1
                elif failure == 'hidden_target':
                    broken['visible'].remove('Right-Thalamus')
                elif failure == 'hidden_context':
                    broken['visible'].remove('Right-Hippocampus')
                elif failure == 'csf':
                    broken['visible'].append('CSF')
                elif failure == 'cut':
                    broken['cuts']['x'] = [0, 50]
                else:
                    broken['loaded'].remove('Left-Thalamus')
                self.assertIn('nicht bestätigt', focus_result_error(action, broken))
        csf_action = validate_action('isolate_regions', {'region_ids': ['CSF']}, self.state['loaded'])
        self.assertEqual(focus_result_error(csf_action, self.focus_state(['CSF'])), '')
        with self.assertRaises(ValueError):
            validate_action('highlight_regions', {'region_ids': []}, self.state['loaded'])

    def test_focus_context_opacity_matches_appearance(self):
        targets = ['Left-Thalamus', 'Right-Thalamus']
        action = validate_action('isolate_regions', {'region_ids': targets}, self.state['loaded'])
        # Validate the same configuration actually delivered to the renderer.
        page = self.client.get('/').get_data(as_text=True)
        settings = json.loads(re.search(r'<script id="focus-context-opacities"[^>]*>(.*?)</script>', page).group(1))
        self.assertEqual(settings, {'learning': 0.03, 'natural': 0.03, 'digital': 0.4})
        for style, opacity in [('learning', 0.03), ('natural', 0.03), ('digital', 0.4)]:
            with self.subTest(style=style):
                state = self.focus_state(targets)
                state['appearance'] = style
                for region_id in state['visible']:
                    if region_id not in targets:
                        state['opacities'][region_id] = settings[style]
                clean = validate_state(state, self.state['loaded'])
                self.assertEqual(clean['appearance'], style)
                self.assertEqual(focus_result_error(action, clean), '')
                clean['opacities']['Left-Cerebral-Cortex'] = 0.03 if style == 'digital' else 0.4
                self.assertIn('nicht bestätigt', focus_result_error(action, clean))
        for invalid in ['invalid', None, {}, True]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_state({**self.state, 'appearance': invalid}, self.state['loaded'])

    def test_false_browser_success_is_reported_to_model_as_failure(self):
        targets = ['Left-Thalamus', 'Right-Thalamus']
        responses = [
            {'output': [{'type': 'function_call', 'call_id': 'focus', 'name': 'highlight_regions',
                         'arguments': json.dumps({'region_ids': targets})}]},
            {'output': [{'type': 'message', 'content': [{'type': 'output_text',
                         'text': 'Die Hervorhebung wurde nicht bestätigt.', 'annotations': []}]}]},
        ]
        def events(*_args):
            yield {'type': 'response.completed', 'response': responses.pop(0)}
        with patch('main.brain_assistant.stream_openai', side_effect=events) as api:
            first = self.stream_result(self.client.post('/api/assistant/chat', headers=self.headers,
                json={'message': 'Zeige den Thalamus.', 'state': self.state}))
            self.assertEqual(first['actions'][0]['name'], 'isolate_regions')
            # Reproduce the old client: only the selection changes; cortex stays opaque.
            stale = self.focus_state(['Left-Cerebral-Cortex', 'Right-Cerebral-Cortex'])
            stale['highlighted'] = targets
            self.stream_result(self.client.post('/api/assistant/chat', headers=self.headers, json={
                'turn_id': first['turn_id'], 'results': [{'call_id': 'focus', 'ok': True}], 'state': stale}))
            output = next(item for item in api.call_args.args[0]['input']
                          if item.get('type') == 'function_call_output')
            receipt = json.loads(output['output'])
            self.assertFalse(receipt['ok'])
            self.assertIn('Deckkraft', receipt['error'])
            self.assertEqual(receipt['state']['opacities']['Left-Thalamus'], 0.03)

    def test_each_action_keeps_its_own_state_before_a_requested_cut(self):
        responses = [
            {'output': [
                {'type': 'function_call', 'call_id': 'focus', 'name': 'isolate_regions',
                 'arguments': json.dumps({'region_ids': ['Left-Thalamus']})},
                {'type': 'function_call', 'call_id': 'cut', 'name': 'set_cut',
                 'arguments': json.dumps({'axis': 'x', 'min': 0, 'max': 50})}]},
            {'output': [{'type': 'message', 'content': [{'type': 'output_text',
                         'text': 'Thalamus hervorgehoben und Schnitt gesetzt.', 'annotations': []}]}]},
        ]
        def events(*_args):
            yield {'type': 'response.completed', 'response': responses.pop(0)}
        with patch('main.brain_assistant.stream_openai', side_effect=events) as api:
            first = self.stream_result(self.client.post('/api/assistant/chat', headers=self.headers,
                json={'message': 'Zeige den Thalamus mit X-Schnitt 0 bis 50.', 'state': self.state}))
            focus = self.focus_state(['Left-Thalamus'])
            cut = copy.deepcopy(focus)
            cut['cuts']['x'] = [0, 50]
            self.stream_result(self.client.post('/api/assistant/chat', headers=self.headers, json={
                'turn_id': first['turn_id'], 'results': [
                    {'call_id': 'focus', 'ok': True, 'state': focus},
                    {'call_id': 'cut', 'ok': True, 'state': cut}], 'state': cut}))
            receipts = [json.loads(item['output']) for item in api.call_args.args[0]['input']
                        if item.get('type') == 'function_call_output']
            self.assertEqual([receipt['ok'] for receipt in receipts], [True, True])
            self.assertEqual(receipts[0]['state']['cuts']['x'], [0, 100])
            self.assertEqual(receipts[1]['state']['cuts']['x'], [0, 50])

    def test_invalid_actions_and_origin(self):
        for name, args in [('eval', {}), ('highlight_regions', {'region_ids': ['fake']}),
                           ('set_cut', {'axis': 'x', 'min': 90, 'max': 10}),
                           ('set_cut', {'axis': 'x', 'min': float('nan'), 'max': 10})]:
            with self.assertRaises(ValueError): validate_action(name, args, self.state['loaded'])
        self.assertEqual(self.client.post('/api/assistant/chat', json={}).status_code, 403)
        self.assertEqual(self.client.post('/api/assistant/chat', json={},
            headers={**self.headers, 'Origin': 'https://example.org'}).status_code, 403)

    def test_api_failure_and_forged_result(self):
        with patch('main.brain_assistant.stream_openai', side_effect=APIError('Verbindung fehlgeschlagen.')):
            reply = self.client.post('/api/assistant/chat', headers=self.headers,
                json={'message': 'Hallo', 'state': self.state})
            self.assertEqual(reply.status_code, 200)
            self.assertIn('Verbindung fehlgeschlagen.',
                next(event['error'] for event in self.stream_events(reply) if event['type'] == 'error'))
        reply = self.client.post('/api/assistant/chat', headers=self.headers,
            json={'turn_id': 'invented', 'results': [], 'state': self.state})
        self.assertEqual(reply.status_code, 400)


if __name__ == '__main__':
    unittest.main()
