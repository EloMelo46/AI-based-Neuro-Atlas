"""Shared local gesture state. Camera dependencies load only when enabled."""
import threading
import time
import uuid


class GestureService:
    def __init__(self):
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None
        self.session = uuid.uuid4().hex
        self.status = 'disabled'
        self.error = None
        self.holding = False
        self.grab_id = 0
        self.listening = False
        self.listen_id = 0
        self.x = self.y = 0.0
        self.updated = None
        self.idle = True
        self.preview_until = 0.0
        self.jpeg = None

    def start(self):
        if self.thread is not None:
            return
        self.status = 'starting'
        self.thread = threading.Thread(target=self._run, name='hand-landmarks', daemon=True)
        self.thread.start()

    def _run(self):
        try:
            from .gesture_control import run
            run(self)
        except Exception as error:
            with self.lock:
                self.status = 'error'
                self.error = str(error)
                self.holding = False
                self.listening = False
            print(f'Gestenerkennung: {error}', flush=True)
        finally:
            with self.lock:
                self.holding = False
                self.listening = False
                self.jpeg = None
                if self.status != 'error':
                    self.status = 'stopped'

    def publish(self, event, idle, listening=False):
        with self.lock:
            self.updated = time.monotonic()
            self.status = 'running'
            self.idle = idle
            if listening and not self.listening:
                self.listen_id += 1
            self.listening = listening
            if event:
                action, dx, dy = event
                if action == 'grab_start':
                    self.grab_id += 1
                    self.x = self.y = 0.0
                    self.holding = True
                elif action == 'grab_move' and self.holding:
                    # Cumulative movement survives skipped HTTP responses.
                    self.x += dx
                    self.y += dy
                elif action == 'grab_end':
                    self.holding = False

    def snapshot(self):
        with self.lock:
            fresh = self.updated is not None and time.monotonic() - self.updated < 2
            connected = self.status == 'running' and fresh
            return dict(session=self.session, status=self.status, error=self.error,
                        connected=connected, holding=self.holding and connected,
                        grab_id=self.grab_id, x=self.x, y=self.y, idle=self.idle,
                        listening=self.listening and connected, listen_id=self.listen_id)

    def wants_preview(self):
        with self.lock:
            return time.monotonic() < self.preview_until

    def set_preview(self, jpeg):
        with self.lock:
            self.jpeg = jpeg

    def preview(self):
        with self.lock:
            self.preview_until = time.monotonic() + 2
            return self.jpeg

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)
        with self.lock:
            self.holding = False
            self.listening = False
            if self.status != 'error':
                self.status = 'stopped'
