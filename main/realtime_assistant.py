"""Realtime session credentials and allowlisted tools for the local viewer."""
import json
import os
import time
import urllib.request
import urllib.error
from flask import request, jsonify


def _openai_error_detail(error):
    """Return a bounded OpenAI error description without exposing credentials."""
    try:
        payload = json.loads(error.read().decode('utf-8', errors='replace'))
        detail = payload.get('error', {}) if isinstance(payload, dict) else {}
        message = detail.get('message') if isinstance(detail, dict) else None
        code = detail.get('code') if isinstance(detail, dict) else None
        if isinstance(message, str) and message.strip():
            suffix = f' ({code})' if isinstance(code, str) and code else ''
            return message.strip()[:1200] + suffix
    except (OSError, UnicodeError, ValueError, AttributeError):
        pass
    finally:
        error.close()
    return ''


def create_realtime_secret(config):
    from .brain_assistant import APIError
    key = os.environ.get('OPENAI_API_KEY', '').strip()
    if not key:
        raise APIError('OPENAI_API_KEY fehlt auf dem Server.')
    req = urllib.request.Request('https://api.openai.com/v1/realtime/client_secrets',
        data=json.dumps({'session': config}).encode(),
        headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}, method='POST')
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                payload = json.load(response)
            value = payload.get('value') if isinstance(payload, dict) else None
            if not isinstance(value, str) or not value:
                raise ValueError('Client-Secret fehlt')
            return value
        except urllib.error.HTTPError as error:
            detail = _openai_error_detail(error)
            if error.code in (401, 403):
                raise APIError('Realtime-Zugriff fehlt. API-Key und Realtime-Berechtigung prüfen.' +
                    (f' OpenAI: {detail}' if detail else '')) from None
            if error.code == 429:
                raise APIError('OpenAI-Kontingent oder Realtime-Limit erreicht.' +
                    (f' OpenAI: {detail}' if detail else '')) from None
            raise APIError(f'Realtime-Sitzung abgelehnt (HTTP {error.code}).' +
                (f' OpenAI: {detail}' if detail else ' Modellzugriff und OPENAI_REALTIME_MODEL prüfen.')) from None
        except (urllib.error.URLError, OSError) as error:
            if attempt == 0:
                time.sleep(0.5)
                continue
            reason = getattr(error, 'reason', error)
            detail = str(reason).strip()[:500]
            raise APIError('OpenAI ist für Realtime nicht erreichbar (Netzwerk, DNS oder TLS).' +
                (f' Technisches Detail: {detail}' if detail else '')) from None
        except (ValueError, KeyError, TypeError):
            raise APIError('OpenAI hat beim Erstellen der Realtime-Sitzung eine unerwartete Antwort geliefert.') from None


def register_realtime(bp, mesh_dir):
    from .brain_assistant import APIError, INSTRUCTIONS, tools_for, tool, validate_state, validate_action

    def context():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise ValueError('JSON-Anfrage erwartet.')
        ids = sorted(p.stem for p in mesh_dir.glob('*.obj'))
        return body, ids, validate_state(body.get('state'), ids)

    @bp.post('/api/assistant/realtime/session')
    def realtime_session():
        try:
            body, ids, state = context()
            voice = body.get('voice', 'marin')
            if voice not in ('marin', 'cedar'):
                raise ValueError('Unbekannte Stimme.')
            # Keep the complete region enums in every viewer tool so the model
            # can ground multi-action requests in the exact available IDs.
            available = tools_for(ids, include_region_enum=True)
            available.append(tool('get_view_state', 'Read current viewer state before planning viewer actions.', {}))
            if body.get('web_search') is True:
                available.append(tool('search_web', 'Research a brain-related question with cited sources. May take time.',
                    {'query': {'type': 'string'}}))
            available = [{k: v for k, v in t.items() if k != 'strict'} for t in available]
            config = {'type': 'realtime', 'model': os.environ.get('OPENAI_REALTIME_MODEL', 'gpt-realtime-2.1-mini'),
                'output_modalities': ['audio'], 'max_output_tokens': 4000,
                'reasoning': {'effort': 'low'},
                'instructions': INSTRUCTIONS + '\nSprich natürliches Deutsch, kurz und freundlich. '
                    'Antworte normalerweise in höchstens drei kurzen Sätzen; nur auf ausdrücklichen Wunsch ausführlicher. '
                    'Lies vor Vieweraktionen mit get_view_state die aktuelle Ansicht. '
                    'Führe bei kombinierten Anweisungen alle angeforderten Vieweränderungen vollständig aus. '
                    'Beende die Aufgabe erst, wenn für jeden angeforderten Teil ein Werkzeugergebnis vorliegt. '
                    'Webrecherche ausschließlich über search_web. Quellen stehen im Chat; URLs nicht vorlesen.\nKontext: '
                    + json.dumps({'regions': ids, 'view': state}),
                'tools': available, 'tool_choice': 'auto',
                'truncation': {'type': 'retention_ratio', 'retention_ratio': 0.8,
                    'token_limits': {'post_instructions': 8000}},
                'audio': {'input': {'transcription': {'model': 'gpt-4o-mini-transcribe', 'language': 'de'},
                    'turn_detection': {'type': 'semantic_vad', 'eagerness': 'low',
                        'create_response': True, 'interrupt_response': True}},
                    'output': {'voice': voice}}}
            return jsonify(value=create_realtime_secret(config)), 200, {'Cache-Control': 'no-store'}
        except ValueError as error:
            return jsonify(error=str(error)), 400
        except APIError as error:
            return jsonify(error=str(error)), 502

    @bp.post('/api/assistant/realtime/tool')
    def realtime_tool():
        try:
            body, ids, state = context()
            name, args = body.get('name'), body.get('arguments')
            if name == 'get_view_state' and args == {}:
                return jsonify(state=state)
            if name == 'search_web':
                from .brain_assistant import call_openai
                if body.get('web_search') is not True:
                    raise ValueError('Websuche ist deaktiviert.')
                if not isinstance(args, dict) or set(args) != {'query'} or not isinstance(args['query'], str) or not 0 < len(args['query'].strip()) <= 1000:
                    raise ValueError('Ungültige Suchanfrage.')
                response = call_openai({'model': os.environ.get('OPENAI_MODEL', 'gpt-4.1-mini'),
                    'instructions': INSTRUCTIONS + '\nRecherchiere nur Informationen, keine Vieweraktionen.',
                    'input': args['query'], 'tools': [{'type': 'web_search'}],
                    'tool_choice': 'required', 'store': False, 'max_output_tokens': 1200})
                messages = [{'text': part['text'], 'citations': part.get('annotations', [])}
                    for item in response.get('output', []) if item.get('type') == 'message'
                    for part in item.get('content', []) if part.get('type') == 'output_text']
                if not messages:
                    raise APIError('Websuche hat keine Antwort geliefert.')
                return jsonify(messages=messages)
            return jsonify(action=validate_action(name, args, ids))
        except ValueError as error:
            return jsonify(error=str(error)), 400
        except APIError as error:
            return jsonify(error=str(error)), 502
