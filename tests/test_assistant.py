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
from main.brain_assistant import validate_action, validate_state, APIError, generate_speech
from main.realtime_assistant import create_realtime_secret


class AssistantTests(unittest.TestCase):
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
            response = self.client.post('/api/assistant/realtime/tool', headers=self.headers,
                json={'state': self.state, 'name': 'set_opacity', 'arguments': {'region_ids': ['Left-Hippocampus'], 'opacity': opacity}})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json['action']['arguments']['opacity'], opacity)
        for opacity in [-1, 1.1, True, '0.5', float('nan')]:
            with self.assertRaises(ValueError):
                validate_action('set_opacity', {'region_ids': ['Left-Hippocampus'], 'opacity': opacity}, self.state['loaded'])
        self.state['opacities'] = {'Left-Hippocampus': 0.3}
        clean = validate_state(self.state, self.state['loaded'])
        self.assertEqual(clean['opacities']['Left-Hippocampus'], 0.3)
        self.assertEqual(clean['opacities']['Right-Hippocampus'], 1)

    def test_realtime_session_and_tools(self):
        with patch('main.realtime_assistant.create_realtime_secret', return_value='temporary-test') as create:
            response = self.client.post('/api/assistant/realtime/session', headers=self.headers,
                json={'state': self.state, 'voice': 'cedar', 'web_search': True})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            config = create.call_args.args[0]
            self.assertEqual(config['audio']['output']['voice'], 'cedar')
            self.assertEqual(config['audio']['input']['turn_detection'], {
                'type': 'semantic_vad', 'eagerness': 'low',
                'create_response': True, 'interrupt_response': True})
            self.assertEqual(config['max_output_tokens'], 4000)
            self.assertEqual(config['reasoning'], {'effort': 'low'})
            self.assertEqual(config['truncation']['retention_ratio'], 0.8)
            self.assertEqual(config['truncation']['token_limits']['post_instructions'], 8000)
            self.assertIn('search_web', [t['name'] for t in config['tools']])
            region_tools = [t for t in config['tools']
                if 'region_ids' in t['parameters']['properties']]
            self.assertEqual(len(region_tools), 5)
            for item in region_tools:
                self.assertEqual(item['parameters']['properties']['region_ids']['items']['enum'], self.state['loaded'])
            opacity = next(t for t in config['tools'] if t['name'] == 'set_opacity')
            self.assertIn('makes every specified region visible', opacity['description'])
            self.assertIn('höchstens drei kurzen Sätzen', config['instructions'])
            self.assertIn('alle angeforderten Vieweränderungen vollständig', config['instructions'])
        response = self.client.post('/api/assistant/realtime/tool', headers=self.headers,
            json={'state': self.state, 'name': 'highlight_regions', 'arguments': {'region_ids': ['Left-Hippocampus']}})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['action']['name'], 'highlight_regions')
        for name, args in [('eval', {}), ('set_cut', {'axis': 'x', 'min': 90, 'max': 10}),
                           ('search_web', {'query': 'brain'})]:
            response = self.client.post('/api/assistant/realtime/tool', headers=self.headers,
                json={'state': self.state, 'name': name, 'arguments': args})
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.post('/api/assistant/realtime/session', json={'state': self.state}).status_code, 403)
        with patch('main.brain_assistant.call_openai', return_value={'output': [
            {'type': 'message', 'content': [{'type': 'output_text', 'text': 'Rechercheantwort.',
                'annotations': [{'type': 'url_citation', 'url': 'https://example.org',
                    'start_index': 0, 'end_index': 17}]}]}]}) as api:
            response = self.client.post('/api/assistant/realtime/tool', headers=self.headers,
                json={'state': self.state, 'name': 'search_web', 'arguments': {'query': 'Hippocampus'}, 'web_search': True})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json['messages'][0]['citations'][0]['url'], 'https://example.org')
            self.assertEqual(api.call_args.args[0]['tools'], [{'type': 'web_search'}])

    def test_speech_endpoint(self):
        with patch('main.brain_assistant.generate_speech', return_value=b'ID3-test') as speech:
            response = self.client.post('/api/assistant/speech', headers=self.headers,
                json={'text': 'Hallo.', 'voice': 'cedar'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, 'audio/mpeg')
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            speech.assert_called_once_with('Hallo.', 'cedar')
        for text, voice in [('', 'marin'), ('x' * 2001, 'marin'), ('Hallo', 'fake')]:
            with self.assertRaises(ValueError): generate_speech(text, voice)

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
        with patch('main.brain_assistant.call_openai', side_effect=responses) as api:
            result = self.client.post('/api/assistant/chat', headers=self.headers,
                json={'message': 'Markiere den linken Hippocampus', 'state': self.state}).get_json()
            self.assertEqual(result['actions'][0]['name'], 'highlight_regions')
            self.assertEqual(api.call_count, 1)
            self.state['highlighted'] = ['Left-Hippocampus']
            reply = self.client.post('/api/assistant/chat', headers=self.headers, json={
                'turn_id': result['turn_id'], 'results': [{'call_id': 'call_1', 'ok': True}], 'state': self.state})
            self.assertEqual(reply.status_code, 200)
            self.assertIn('markiert', reply.get_json()['messages'][0]['text'])
            payload = api.call_args.args[0]
            tool_output = next(i for i in payload['input'] if i.get('type') == 'function_call_output')
            self.assertTrue(json.loads(tool_output['output'])['ok'])
            self.assertFalse(payload['store'])

    def test_invalid_actions_and_origin(self):
        for name, args in [('eval', {}), ('highlight_regions', {'region_ids': ['fake']}),
                           ('set_cut', {'axis': 'x', 'min': 90, 'max': 10}),
                           ('set_cut', {'axis': 'x', 'min': float('nan'), 'max': 10})]:
            with self.assertRaises(ValueError): validate_action(name, args, self.state['loaded'])
        self.assertEqual(self.client.post('/api/assistant/chat', json={}).status_code, 403)
        self.assertEqual(self.client.post('/api/assistant/chat', json={},
            headers={**self.headers, 'Origin': 'https://example.org'}).status_code, 403)

    def test_api_failure_and_forged_result(self):
        with patch('main.brain_assistant.call_openai', side_effect=APIError('Verbindung fehlgeschlagen.')):
            reply = self.client.post('/api/assistant/chat', headers=self.headers,
                json={'message': 'Hallo', 'state': self.state})
            self.assertEqual(reply.status_code, 502)
        reply = self.client.post('/api/assistant/chat', headers=self.headers,
            json={'turn_id': 'invented', 'results': [], 'state': self.state})
        self.assertEqual(reply.status_code, 400)


if __name__ == '__main__':
    unittest.main()
