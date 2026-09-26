"""Start the local viewer and a dedicated Chromium kiosk from the desktop."""
import fcntl
import json
from pathlib import Path
import shutil
import signal
import subprocess
import time
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parent.parent
URL = 'http://localhost:5000'
STATE = ROOT / '.local'


def viewer_ready():
    try:
        with build_opener(ProxyHandler({})).open(URL + '/api/assistant/config', timeout=1) as response:
            config = json.load(response)
        return isinstance(config, dict) and {'configured', 'model', 'transcribe_model', 'speech_model'} <= config.keys()
    except (OSError, ValueError):
        return False


def stop_process(process):
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def launch():
    python = ROOT / '.venv' / 'bin' / 'python'
    chromium = shutil.which('chromium') or shutil.which('chromium-browser')
    if not python.is_file() or not chromium:
        raise RuntimeError('Python-Umgebung oder Chromium fehlt. Bitte das Pi-Setup in README.md ausführen.')
    STATE.mkdir(exist_ok=True, mode=0o700)
    # One launcher owns the dedicated browser profile and, if needed, the server.
    with (STATE / 'desktop.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        server = browser = None
        with (STATE / 'desktop.log').open('w') as log:
            try:
                if not viewer_ready():
                    server = subprocess.Popen([
                        str(python), '-m', 'main.brain_viewer', '--gestures',
                        '--host', '127.0.0.1', '--port', '5000',
                    ], cwd=ROOT, stdout=log, stderr=log)
                    deadline = time.monotonic() + 30
                    while not viewer_ready():
                        if server.poll() is not None:
                            raise RuntimeError('Der lokale Server konnte nicht starten. Details: .local/desktop.log')
                        if time.monotonic() >= deadline:
                            raise RuntimeError('Der lokale Server antwortet nicht. Details: .local/desktop.log')
                        time.sleep(0.2)
                    # Do not mistake a different listener for the child we own.
                    if server.poll() is not None:
                        raise RuntimeError('Port 5000 ist bereits belegt. Details: .local/desktop.log')
                browser = subprocess.Popen([
                    chromium, '--kiosk', '--no-first-run', '--no-default-browser-check',
                    '--user-data-dir=' + str(STATE / 'chromium-kiosk'), URL,
                ], cwd=ROOT, stdout=log, stderr=log)
                if browser.wait() != 0:
                    raise RuntimeError('Chromium konnte nicht starten. Details: .local/desktop.log')
            finally:
                stop_process(browser)
                # Never shut down a server started separately by the user.
                stop_process(server)


def main():
    def interrupted(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    try:
        launch()
        return 0
    except KeyboardInterrupt:
        return 0
    except (OSError, RuntimeError) as error:
        message = str(error)
        print(message, flush=True)
        if shutil.which('zenity'):
            subprocess.run(['zenity', '--error', '--title=Neuro Atlas', '--text=' + message], check=False)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
