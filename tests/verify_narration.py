"""Real UI, glow rendering and audio playback with no billable API calls."""
import io
import json
import logging
import sys
import wave
from pathlib import Path
from threading import Event, Thread
from unittest.mock import patch

from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if __package__ in (None, ''):
    sys.path.insert(0, str(PROJECT_ROOT))

from main.brain_viewer import app


def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    responses, spoken = [], []
    speech_started, speech_release = Event(), Event()
    speech_release.set()
    partial_stream = [False]
    stream_waiting, stream_release = Event(), Event()
    stream_release.set()
    # MPEG-1 Layer III, mono, 128 kbit/s, 44.1 kHz, zero coefficient frames.
    # Local silence exercises the real MP3 decoder/MSE without a private recording.
    sample = (bytes.fromhex('fffb90c0') + bytes(413)) * 200

    def stream(_payload, _entry):
        text = responses.pop(0)
        yield {'type': 'response.completed', 'response': {'output': [{
            'type': 'message', 'content': [{'type': 'output_text', 'text': text, 'annotations': []}]}]}}

    class StreamingSample(io.BytesIO):
        def read(self, size=-1):
            if partial_stream[0] and self.tell() >= 16384:
                stream_waiting.set()
                assert stream_release.wait(15), 'Test did not release the audio stream'
            return super().read(size)

    def speech(text, voice):
        spoken.append((text, voice))
        speech_started.set()
        assert speech_release.wait(15), 'Test did not release speech preparation'
        return StreamingSample(sample)

    server = make_server('127.0.0.1', 0, app, threaded=True)
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        with patch('main.brain_assistant.stream_openai', side_effect=stream), \
                patch('main.brain_assistant.open_speech', side_effect=speech), \
                patch('main.brain_assistant._api_key', side_effect=AssertionError('Live API disabled')), \
                sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='chrome', headless=True, args=[
                '--enable-unsafe-swiftshader', '--autoplay-policy=no-user-gesture-required',
                '--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'])
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)
            page.route('**/api/assistant/config', lambda route: route.fulfill(json={'configured': True}))
            page.goto(f'http://127.0.0.1:{server.server_port}')
            page.locator('#auto-rotate').uncheck()
            page.locator('#assistant-speak').uncheck()
            page.evaluate("""async () => {
              window.viewer = (await import('/static/brain_viewer.js')).assistantViewer;
              window.mentions = await import('/static/region_mentions.js');
              window.timing = await import('/static/speech_timing.js');
            }""")
            assert len(page.evaluate('viewer.getState().loaded')) == 38
            assert page.locator('#info').is_visible() and page.locator('#assistant-panel').is_visible()
            assert not errors, errors
            output = PROJECT_ROOT / 'verification'
            output.mkdir(exist_ok=True)
            page.screenshot(path=str(output / 'narration-initial.png'))
            print('PASS: viewer loads, panels and controls render, no browser errors.', flush=True)

            def resolve(text):
                return page.evaluate('(text) => mentions.findRegionMentions(text, viewer.getState().loaded).map(m => m.regionIds)', text)

            thalamus = ['Left-Thalamus', 'Right-Thalamus']
            hippo = ['Left-Hippocampus', 'Right-Hippocampus']
            assert resolve('Der Thalamus und der rechte Hippocampus.') == [thalamus, ['Right-Hippocampus']]
            assert resolve('linker und rechter Thalamus') == [thalamus]
            assert resolve('Thalamus rechts') == [['Right-Thalamus']]
            assert resolve('Grosshirnrinde') == [['Left-Cerebral-Cortex', 'Right-Cerebral-Cortex']]
            assert resolve('Der vierte Ventrikel.') == [['4th-Ventricle']]
            assert resolve('beidseits des dritten Ventrikels') == [['3rd-Ventricle']]
            assert resolve('Die Thalami liegen beidseits des dritten Ventrikels.') == [thalamus, ['3rd-Ventricle']]
            for term in ('der dritte Ventrikel', 'den dritten Ventrikel', 'dem dritten Ventrikel',
                         'des dritten Ventrikels', 'drittem Ventrikel', 'des 3. Ventrikels'):
                assert resolve(term) == [['3rd-Ventricle']], term
            for term in ('der vierte Ventrikel', 'den vierten Ventrikel', 'dem vierten Ventrikel',
                         'des vierten Ventrikels', 'viertem Ventrikel', 'des 4. Ventrikels'):
                assert resolve(term) == [['4th-Ventricle']], term
            assert resolve('Der dritte Ventrikel enthält Liquor.') == [['3rd-Ventricle'], ['CSF']]
            assert resolve('Ventrikelsystem und Ventrikelfunktion') == [
                ['Left-Lateral-Ventricle', 'Right-Lateral-Ventricle', 'Left-Inf-Lat-Vent',
                 'Right-Inf-Lat-Vent', '3rd-Ventricle', '4th-Ventricle']]
            assert resolve('Hypothalamus, Hippocampusfunktion, lh.pial, lh_hippo_mc') == []
            assert resolve('Left-Hippocampus') == [['Left-Hippocampus']]
            assert resolve('Hippokampus und Mandelkern') == [hippo, ['Left-Amygdala', 'Right-Amygdala']]
            assert page.evaluate("viewer.getState().loaded.every(id => mentions.findRegionMentions(id, viewer.getState().loaded).some(m => m.regionIds.includes(id)))")
            cases = json.loads((PROJECT_ROOT / 'tests/region_mention_cases.json').read_text(encoding='utf-8'))
            page.evaluate("""cases => {
              for (const {text, expected, available} of cases) {
                const result = mentions.findRegionMentions(text, available ?? viewer.getState().loaded);
                const actual = result.map(mention => [...mention.regionIds].sort());
                if (JSON.stringify(actual) !== JSON.stringify(expected.map(ids => [...ids].sort()))) {
                  throw new Error(`Mention mismatch: ${text}: ${JSON.stringify(actual)}`);
                }
                // Offsets must continue to point into the untouched spoken text.
                for (const mention of result) {
                  if (mention.start < 0 || mention.end > text.length || mention.cueStart < mention.start || mention.cueStart >= mention.end) {
                    throw new Error(`Invalid text offsets: ${text}`);
                  }
                }
              }
              const text = '🧠 Der rechte Hippocampus und der III. Ventrikel.';
              const mentionsFound = mentions.findRegionMentions(text, viewer.getState().loaded);
              if (text.slice(mentionsFound[0].cueStart, mentionsFound[0].cueStart + 11) !== 'Hippocampus') {
                throw new Error('Hemisphere or Unicode text changed the spoken-name position');
              }
            }""", cases)
            print(f'PASS: {len(cases)} additional inflection, synonym, spelling, hemisphere and exclusion cases.', flush=True)
            assert page.evaluate("""() => {
              const part = {text: 'Der Thalamus. Hippocampus', citations: [{start_index: 14, end_index: 25}]};
              const segments = mentions.narrationSegments([part], viewer.getState().loaded);
              return segments.length === 1 && segments[0].mentions.length === 1 && !segments[0].text.includes('Hippocampus');
            }""")
            assert page.evaluate("""() => {
              const text = 'Der Thalamus arbeitet mit dem Hippocampus und der Grosshirnrinde zusammen.';
              const ids = viewer.getState().loaded;
              const parts = mentions.narrationSegments([{text, citations:[]}], ids);
              const longText = (text + ' ').repeat(120).trim();
              const longParts = mentions.narrationSegments([{text:longText, citations:[]}], ids);
              return parts.length === 1 && parts[0].text === text && parts[0].mentions.length === 3 &&
                longParts.length > 1 && longParts.every(part => part.text.length <= 3800 && part.text.endsWith('.')) &&
                longParts.map(part => part.text).join(' ') === longText;
            }""")
            print('PASS: canonical IDs, aliases, sides, boundaries, citations, removed meshes.', flush=True)

            # Check estimates and offsets independently from wall time. The clock
            # observer must not mutate any audio property, even on pause/seek.
            page.evaluate("""() => {
              const check = (ok, text) => { if (!ok) throw new Error(text); };
              const segmentFor = text => mentions.narrationSegments([{text, citations:[]}], viewer.getState().loaded)[0];
              const segment = segmentFor('Der Thalamus leitet Signale weiter. Der rechte Hippocampus hilft beim Lernen.');
              const base = timing.estimatedRegionMentions(segment, 12, 0);
              const delayed = timing.estimatedRegionMentions(segment, 12, 0.3);
              const advanced = timing.estimatedRegionMentions(segment, 12, -0.2);
              check(base.length === 2 && base[1].at > base[0].at, 'Mention order lost');
              check(delayed.every((cue, i) => Math.abs(cue.at - base[i].at - 0.3) < 1e-9), 'Positive offset must delay every cue equally');
              check(advanced.every((cue, i) => Math.abs(cue.at - base[i].at + 0.2) < 1e-9), 'Negative offset must advance cues');
              check(timing.estimatedRegionMentions(segment, 24, 0).every((cue, i) => Math.abs(cue.at - base[i].at * 2) < 1e-9), 'Full duration must scale timing');
              check(timing.estimatedRegionMentions(segment, Infinity).every(c => Number.isFinite(c.at)), 'Streaming needs finite initial estimates');
              check(timing.estimatedRegionMentions(segment, 0.2, 20).every(c => c.at >= 0 && c.at < 0.2), 'Large offset must remain inside recording');
              check(timing.estimatedRegionMentions(segment, 12, -20).every(c => c.at === 0), 'Negative offset went before audio start');
              check(timing.estimatedRegionMentions(segmentFor('Thalamus und Thalamus.'), 4).length === 2, 'Repeated names lost');
              check(timing.estimatedRegionMentions(segmentFor('Hallo.'), 4).length === 0, 'Invented an anatomical cue');
              const short = timing.estimatedRegionMentions(segmentFor('Der Thalamus.'), undefined, 0)[0].at;
              const long = timing.estimatedRegionMentions(segmentFor('Gedächtnisverarbeitung. Thalamus.'), undefined, 0)[0].at;
              check(long > short, 'Syllables and punctuation must affect estimates');

              const calls = [];
              const state = {paused:true, seeking:false, ended:false, readyState:4, currentTime:0};
              const audio = new EventTarget();
              for (const key of Object.keys(state)) Object.defineProperty(audio, key, {
                get:() => state[key], set:() => { throw new Error('Timing changed audio ' + key); },
              });
              const emit = name => audio.dispatchEvent(new Event(name));
              let timeline = [{at:1, regionIds:['Left-Thalamus']}, {at:4, regionIds:['Right-Hippocampus']}];
              const stop = timing.followSpeechMentions(audio, () => timeline, {onCue:ids => calls.push(ids)});
              state.currentTime = 1.05;
              emit('timeupdate');
              check(calls.length === 0, 'Paused/autoplay-blocked audio emitted a cue');
              state.paused = false;
              state.currentTime = 0.99;
              emit('playing');
              check(calls.length === 0, 'Cue preceded its offset time');
              state.currentTime = 1.05;
              emit('timeupdate');
              check(calls.length === 1 && calls[0][0] === 'Left-Thalamus', 'First cue missing');
              // Complete duration may update remaining cues, without replaying old ones.
              timeline = [{at:0.8, regionIds:['Left-Thalamus']}, {at:5, regionIds:['Right-Hippocampus']}];
              state.currentTime = 4.1;
              emit('timeupdate');
              check(calls.length === 1, 'Observer ignored the completed-duration correction');
              state.paused = true;
              emit('pause');
              state.currentTime = 5.05;
              emit('timeupdate');
              check(calls.length === 1, 'Paused playback advanced the cues');
              state.paused = false;
              emit('playing');
              check(calls.length === 2 && calls[1][0] === 'Right-Hippocampus', 'Resume did not follow audio position');
              state.seeking = true;
              emit('seeking');
              state.currentTime = 11;
              state.seeking = false;
              emit('seeked');
              check(calls.length === 2, 'Forward seek replayed stale cues');
              state.seeking = true;
              emit('seeking');
              state.currentTime = 0.85;
              state.seeking = false;
              emit('seeked');
              check(calls.length === 3 && calls[2][0] === 'Left-Thalamus', 'Backward seek failed to replay mention');
              stop();
              state.currentTime = 5.05;
              emit('timeupdate');
              check(calls.length === 3, 'Disposed playback still emitted cues');
            }""")
            print('PASS: estimated timing, adjustable offset, repeats, pause/seek and read-only audio clock.', flush=True)

            page.evaluate('(ids) => viewer.execute({name:"isolate_regions", arguments:{region_ids:ids}})', thalamus)
            persistent = page.evaluate('viewer.getState()')
            page.wait_for_timeout(250)
            baseline = page.locator('#scene canvas').screenshot()
            page.evaluate('(ids) => viewer.glowRegions(ids)', hippo)
            page.wait_for_timeout(450)
            assert page.evaluate('viewer.getMentionedRegions()') == hippo
            glow_image = page.locator('#scene canvas').screenshot()
            assert glow_image != baseline, 'Unselected hippocampus must visibly glow through context'
            assert page.evaluate('viewer.getState()') == persistent
            (output / 'narration-glow.png').write_bytes(glow_image)
            page.wait_for_function('viewer.getMentionedRegions().length === 0', timeout=3000)
            page.wait_for_timeout(150)
            assert page.locator('#scene canvas').screenshot() == baseline, 'Glow must expire without residue'
            page.evaluate('(ids) => viewer.glowRegions(ids)', thalamus)
            page.wait_for_timeout(300)
            assert page.locator('#scene canvas').screenshot() != baseline
            page.evaluate('viewer.clearMentionGlow()')
            assert page.evaluate('viewer.getState()') == persistent
            page.evaluate("viewer.glowRegions(['CSF', 'lh.pial'])")
            assert page.evaluate('viewer.getMentionedRegions()') == []
            # A ventricle mention is eligible even while the separate CSF mesh is hidden.
            page.evaluate("""() => {
              const segments = mentions.narrationSegments([{text:'Er liegt beidseits des dritten Ventrikels.'}], viewer.getState().loaded);
              const timeline = timing.estimatedRegionMentions(segments[0], 4);
              if (timeline.length !== 1 || timeline[0].regionIds.join() !== '3rd-Ventricle') throw new Error('Genitive ventricle cue missing');
              viewer.glowRegions(timeline[0].regionIds);
            }""")
            assert page.evaluate('viewer.getMentionedRegions()') == ['3rd-Ventricle']
            assert page.evaluate('viewer.getState()') == persistent
            page.evaluate('viewer.clearMentionGlow()')
            page.evaluate("""() => {
              viewer.execute({name:'set_visibility', arguments:{region_ids:['CSF'], visible:true}});
              viewer.glowRegions(['CSF']);
            }""")
            assert page.evaluate('viewer.getMentionedRegions()') == ['CSF']
            page.evaluate("viewer.execute({name:'set_visibility', arguments:{region_ids:['CSF'], visible:false}})")
            page.wait_for_function('viewer.getMentionedRegions().length === 0')
            page.emulate_media(reduced_motion='reduce')
            # Use explicit animation times: screenshot latency can cross the fade-out
            # boundary of an effect, even when reduced motion is steady.
            assert page.evaluate("""async () => {
              const THREE = await import('three');
              const { createMentionGlow } = await import('/static/mention_glow.js');
              const scene = new THREE.Scene();
              const object = new THREE.Mesh(new THREE.BufferGeometry());
              const glow = createMentionGlow(THREE, scene, new Map([['test', {object}]]), [], () => {});
              const start = performance.now();
              glow.glow(['test']);
              glow.update(start + 250);
              const initial = scene.children[0].material.uniforms.strength.value;
              glow.update(start + 500);
              const steady = initial > 0 && scene.children[0].material.uniforms.strength.value === initial;
              glow.update(start + 1500);
              const stillActive = glow.getActiveIds().length === 1;
              glow.update(start + 2050);
              const expired = glow.getActiveIds().length === 0 && scene.children.length === 0;
              glow.clear();
              object.geometry.dispose();
              object.material.dispose();
              return steady && stillActive && expired;
            }"""), 'Glow must remain steady in reduced motion, last beyond one second and expire after two'
            page.emulate_media(reduced_motion='no-preference')

            # Changes made while glowing must survive expiry; no stale-state restoration.
            page.evaluate("""() => {
              viewer.glowRegions(['Left-Hippocampus']);
              viewer.execute({name:'set_opacity', arguments:{region_ids:['Left-Hippocampus'], opacity:0.2}});
              viewer.execute({name:'set_cut', arguments:{axis:'x', min:20, max:80}});
            }""")
            changed = page.evaluate('viewer.getState()')
            page.wait_for_function('viewer.getMentionedRegions().length === 0', timeout=3000)
            assert page.evaluate('viewer.getState()') == changed
            page.evaluate('(ids) => viewer.execute({name:"isolate_regions", arguments:{region_ids:ids}})', thalamus)
            print('PASS: visible selected/unselected glow, two-second expiry, preserved state and CSF opt-in.', flush=True)

            def ask(text):
                responses.append(text)
                page.locator('#assistant-input').fill('Erkläre diese Areale.')
                page.locator('#assistant-send').click()
                page.wait_for_function("document.getElementById('assistant-status').textContent === 'Bereit.' && !document.getElementById('assistant-send').disabled")

            ask('Der Thalamus leitet Signale weiter. Der rechte Hippocampus hilft beim Lernen.')
            assert page.evaluate('viewer.getMentionedRegions()') == thalamus
            page.wait_for_function("viewer.getMentionedRegions().includes('Right-Hippocampus')", timeout=1500)
            assert page.evaluate('viewer.getState()') == persistent
            page.locator('#assistant-new').click()
            page.wait_for_function('viewer.getMentionedRegions().length === 0')
            page.wait_for_function("!document.getElementById('assistant-send').disabled")

            # Multiple mentions must share one synthesis request and one audio source.
            page.evaluate("""() => {
              window.cues = [];
              const audio = document.getElementById('assistant-audio');
              const transitions = [];
              for (const event of ['pause', 'ended', 'emptied', 'loadstart', 'ratechange']) {
                audio.addEventListener(event, () => transitions.push(event));
              }
              const glow = viewer.glowRegions.bind(viewer);
              viewer.glowRegions = ids => {
                if (ids.length) cues.push({ ids, time: performance.now(), playing: !audio.paused,
                  source:audio.currentSrc, position:audio.currentTime, transitions:[...transitions] });
                glow(ids);
              };
            }""")
            page.locator('#assistant-speak').check()
            partial_stream[0] = True
            stream_release.clear()
            ask('Der Thalamus leitet Signale weiter. Der rechte Hippocampus hilft beim Lernen.')
            assert stream_waiting.wait(3)
            page.wait_for_function('cues.length > 0', timeout=10000)
            assert not stream_release.is_set(), 'Playback must start before the download finishes'
            assert page.evaluate('cues.length') == 1, 'A partial buffer must not compress all cues into its duration'
            stream_release.set()
            partial_stream[0] = False
            assert not page.locator('#assistant-speech-status').is_visible()
            assert page.evaluate('cues[0].ids') == thalamus
            assert page.evaluate('cues.every(c => c.playing)')
            page.locator('#assistant-input').fill('Entwurf bleibt erhalten')
            page.locator('#fullscreen-toggle').click()
            page.wait_for_function('!!document.fullscreenElement')
            assert not page.locator('#info').is_visible()
            assert not page.locator('#assistant-panel').is_visible()
            assert page.locator('#fullscreen-toggle').inner_text() == '×'
            assert page.locator('#fullscreen-toggle').get_attribute('aria-label') == 'Vollbild beenden'
            assert page.locator('.app-caption').count() == 0
            assert page.locator('#scene').bounding_box()['width'] == page.viewport_size['width']
            page.wait_for_function('cues.length === 2', timeout=10000)
            assert page.evaluate('cues[1].ids') == ['Right-Hippocampus']
            assert page.evaluate("""() => {
              const segment = mentions.narrationSegments([{text:'Der Thalamus leitet Signale weiter. Der rechte Hippocampus hilft beim Lernen.'}], viewer.getState().loaded)[0];
              const duration = document.getElementById('assistant-audio').duration;
              const estimated = timing.estimatedRegionMentions(segment, duration);
              return cues[0].position >= 0.3 && Math.abs(cues[1].position - estimated[1].at) < 0.35;
            }""")
            assert page.evaluate('cues.every(c => c.playing)')
            assert page.evaluate('cues[0].source === cues[1].source && cues[1].position > cues[0].position')
            assert page.evaluate('JSON.stringify(cues[0].transitions) === JSON.stringify(cues[1].transitions)')
            assert page.evaluate('viewer.getState()') == persistent
            page.screenshot(path=str(output / 'fullscreen-glow.png'))
            page.locator('#fullscreen-toggle').click()
            page.wait_for_function('!document.fullscreenElement')
            assert page.locator('#info').is_visible() and page.locator('#assistant-panel').is_visible()
            assert page.locator('#assistant-input').input_value() == 'Entwurf bleibt erhalten'
            assert spoken == [('Der Thalamus leitet Signale weiter. Der rechte Hippocampus hilft beim Lernen.', 'marin')], spoken
            page.wait_for_function("document.getElementById('assistant-audio').hidden", timeout=10000)
            # A cue expires independently of audio playback completion.
            page.wait_for_function('viewer.getMentionedRegions().length === 0', timeout=3000)
            print('PASS: MP3 playback starts before download ends, estimated cues, one synthesis/source, fullscreen continuity.', flush=True)

            # A cancelled answer must never start playing when its audio arrives late.
            page.evaluate('cues.length = 0')
            speech_started.clear()
            speech_release.clear()
            ask('Der Thalamus.')
            assert speech_started.wait(3)
            page.locator('#assistant-new').click()
            page.wait_for_function("!document.getElementById('assistant-send').disabled")
            speech_release.set()
            page.wait_for_timeout(500)
            assert page.evaluate('cues.length') == 0
            assert page.locator('#assistant-audio').evaluate('a => a.paused && !a.hasAttribute("src")')
            assert not page.locator('#assistant-speech-status').is_visible()
            print('PASS: cancellation discards late audio and cues.', flush=True)

            # Autoplay rejection cannot trigger glow before the user's Play gesture.
            page.evaluate("""() => {
              window.originalPlay = HTMLMediaElement.prototype.play;
              HTMLMediaElement.prototype.play = function() { return Promise.reject(new DOMException('Gesture required', 'NotAllowedError')); };
              cues.length = 0;
            }""")
            ask('Der Hippocampus hilft beim Lernen.')
            page.wait_for_function("document.getElementById('assistant-audio').readyState >= 2")
            assert page.evaluate('cues.length') == 0
            page.evaluate("() => { HTMLMediaElement.prototype.play = originalPlay; }")
            page.evaluate("document.getElementById('assistant-audio').play()")
            page.wait_for_function('cues.length === 1')
            assert page.evaluate('cues[0].playing')
            page.locator('#assistant-mic').click()
            page.wait_for_function("document.getElementById('assistant-mic').getAttribute('aria-pressed') === 'true'")
            assert page.evaluate('viewer.getMentionedRegions()') == []
            assert page.locator('#assistant-audio').evaluate('a => a.paused && !a.hasAttribute("src")')
            page.locator('#fullscreen-toggle').click()
            page.wait_for_function('!!document.fullscreenElement')
            assert page.locator('#assistant-mic').get_attribute('aria-pressed') == 'true'
            page.locator('#fullscreen-toggle').click()
            page.wait_for_function('!document.fullscreenElement')
            page.route('**/api/assistant/transcribe', lambda route: route.fulfill(json={'text': 'Aufnahme beendet'}))
            responses.append('Die Aufnahme ist beendet.')
            page.locator('#assistant-mic').click()
            page.wait_for_function("document.getElementById('assistant-status').textContent === 'Bereit.' && !document.getElementById('assistant-send').disabled")
            print('PASS: blocked autoplay waits for Play; microphone interrupts audio/glow and survives fullscreen.', flush=True)

            # Each repeated source mention still receives a glow, with no ASR dependency.
            page.evaluate('cues.length = 0')
            ask('Der Thalamus leitet Signale weiter. Auch der Thalamus filtert diese Signale.')
            page.wait_for_function('cues.length === 2', timeout=10000)
            assert page.evaluate('cues.every(c => c.ids.includes("Left-Thalamus") && c.playing)')
            assert page.locator('.assistant-message.error').count() == 0
            page.locator('#assistant-new').click()
            page.wait_for_function("!document.getElementById('assistant-send').disabled")
            print('PASS: repeated anatomy mentions glow without any transcription request.', flush=True)

            # Browser fallback without MSE uses the same actual-playback cue contract.
            wav = io.BytesIO()
            with wave.open(wav, 'wb') as file:
                file.setnchannels(1)
                file.setsampwidth(2)
                file.setframerate(8000)
                file.writeframes(bytes(16000))
            page.route('**/api/assistant/speech', lambda route: route.fulfill(body=sample, content_type='audio/mpeg'))
            page.evaluate('window.MediaSource = undefined; cues.length = 0')
            ask('Der Thalamus leitet Signale weiter.')
            page.wait_for_function('cues.length === 1')
            assert page.evaluate('cues[0].playing')
            page.locator('#assistant-speak').uncheck()
            page.wait_for_timeout(500)
            assert page.evaluate('viewer.getMentionedRegions()') == []
            assert page.evaluate('viewer.getState()') == persistent
            # No-name answers still work without alignment or MSE (plain audio response).
            page.unroute('**/api/assistant/speech')
            page.route('**/api/assistant/speech', lambda route: route.fulfill(body=wav.getvalue(), content_type='audio/wav'))
            page.evaluate('cues.length = 0')
            page.locator('#assistant-speak').check()
            ask('Hallo.')
            page.wait_for_function("!document.getElementById('assistant-audio').paused")
            assert page.evaluate('cues.length') == 0
            page.locator('#assistant-speak').uncheck()
            assert not errors, errors
            assert not responses
            assert page.locator('.assistant-message.error').count() == 0
            browser.close()
            print('PASS: non-MSE playback, cancellation, persistent selection, no browser/API errors.', flush=True)
    finally:
        speech_release.set()
        stream_release.set()
        server.shutdown()


if __name__ == '__main__':
    main()
