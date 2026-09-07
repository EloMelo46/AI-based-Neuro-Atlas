"""Unit tests for assistant routes and validation without live API calls."""
import json
import io
import os
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
    generate_speech, transcribe_audio, tools_for)
from main.realtime_assistant import create_realtime_secret


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
        isolate = next(item for item in definitions if item['name'] == 'isolate_regions')
        self.assertIn('1% opacity', isolate['description'])

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
        for text, voice in [('', 'marin'), ('x' * 2001, 'marin'), ('Hallo', 'fake')]:
            with self.assertRaises(ValueError): generate_speech(text, voice)

    def test_audio_model_request_defaults(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-only'}, clear=True), \
                patch('main.brain_assistant.urllib.request.urlopen',
                      return_value=io.BytesIO(b'ID3-test')) as urlopen:
            self.assertEqual(generate_speech('Hallo.', 'marin'), b'ID3-test')
            payload = json.loads(urlopen.call_args.args[0].data)
            self.assertEqual(payload, {
                'model': 'gpt-4o-mini-tts', 'voice': 'marin', 'input': 'Hallo.',
            'response_format': 'mp3', 'stream_format': 'audio', 'speed': 1.2,
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
        self.assertEqual(config['model'], 'gpt-5.6-luna')
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
        self.assertIn(f"816{chr(0x2019)}604 Dreiecke", page)
        self.assertIn(f"4{chr(0x2019)}045{chr(0x2019)}140 Dreiecke", page)
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
        ids = sorted(p.stem for p in MESH_DIR.glob('*.obj'))
        self.state = {'loaded': ids, 'visible': ids, 'highlighted': [], 'cuts': {a: [0, 100] for a in 'xyz'}}

    def test_acknowledged_tool_roundtrip(self):
        responses = [
            {'status': 'completed', 'output': [{'type': 'function_call', 'call_id': 'call_1',
                'name': 'highlight_regions', 'arguments': json.dumps({'region_ids': ['Left-Hippocampus']})}]},
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
            self.assertEqual(result['actions'][0]['name'], 'highlight_regions')
            self.assertEqual(api.call_count, 1)
            self.state['highlighted'] = ['Left-Hippocampus']
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
            self.assertEqual(payload['model'], 'gpt-5.6-luna')
            self.assertEqual(payload['reasoning'], {'effort': 'low'})
            self.assertEqual(payload['text'], {'verbosity': 'medium'})
            self.assertEqual(payload['max_output_tokens'], 1600)
            self.assertTrue(payload['parallel_tool_calls'])
            self.assertIn({'type': 'web_search'}, payload['tools'])

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
