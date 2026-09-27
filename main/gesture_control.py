#!/usr/bin/env python3
"""MediaPipe-Gesten für die direkte Steuerung des lokalen Three.js-Viewers."""

from pathlib import Path
from math import hypot
import time

import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from picamera2 import Picamera2

MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "hand_landmarker.task"
IDLE_FPS = 3                    # Maximale Bildrate, wenn keine Hand erkannt wird.
IDLE_TIMEOUT_SECONDS = 60       # Sekunden ohne Hand erkannt, bevor die Bildrate reduziert wird.
PINCH_CLOSE = 0.30              # Abstand 4–8 relativ zur Handbreite (5–17).
PINCH_OPEN = 0.5               # Unterschiedliche Schwellen verhindern Flackern.
POINTER_SMOOTHING = 0.4         # Glättung der Cursorbewegung, 0 = keine Glättung, 1 = keine Bewegung.
ACTIVE_FPS = 20                 # Maximale Bildrate, wenn eine Hand erkannt wird.
LISTEN_HOLD_SECONDS = 0.6       # 0.6 Sekunden halten, um Push-to-Talk zu aktivieren.


class PinchDrag:
    """Erzeugt grab_start/move/end; Bewegungen relativ zur Bildgröße."""

    def __init__(self):
        self.holding = False
        self.cursor = None
        self.origin = None
        self.ratio = None

    def update(self, hand, width, height):
        if not hand:
            was_holding = self.holding
            self.holding = False
            self.cursor = self.origin = self.ratio = None
            return ("grab_end", 0, 0) if was_holding else None

        def pixel(index):
            point = hand[index]
            return ((1 - point.x) * (width - 1), point.y * (height - 1))

        thumb, index = pixel(4), pixel(8)
        palm_left, palm_right = pixel(5), pixel(17)
        palm_width = hypot(palm_left[0] - palm_right[0], palm_left[1] - palm_right[1])
        if palm_width < 1:
            return self.update(None, width, height)
        self.ratio = hypot(thumb[0] - index[0], thumb[1] - index[1]) / palm_width
        position = ((thumb[0] + index[0]) / 2, (thumb[1] + index[1]) / 2)

        previous = self.cursor
        self.cursor = position if previous is None else tuple(
            old + POINTER_SMOOTHING * (new - old)
            for old, new in zip(previous, position)
        )
        if not self.holding:
            if self.ratio <= PINCH_CLOSE:
                self.holding = True
                self.cursor = position
                self.origin = self.cursor
                return ("grab_start", 0, 0)
        elif self.ratio >= PINCH_OPEN:
            self.holding = False
            self.origin = None
            return ("grab_end", 0, 0)

        if previous is None or not self.holding:
            return None
        return ("grab_move", (self.cursor[0] - previous[0]) / (width - 1),
                (self.cursor[1] - previous[1]) / (height - 1))


class IndexHold:
    """Only an upright index finger, held continuously, enables push-to-talk."""

    def __init__(self):
        self.since = None
        self.listening = False

    def update(self, hand, width, height, now, blocked=False):
        pointing = False
        if hand and not blocked:
            points = [(p.x * width, p.y * height) for p in hand]
            def distance(a, b):
                return hypot(points[a][0] - points[b][0], points[a][1] - points[b][1])
            palm = distance(5, 17)
            if palm >= 1:
                # Screen-up direction and extension relative to the wrist.
                # Ratios make this independent of distance to the camera.
                pointing = (
                    points[5][1] - points[8][1] > palm * 0.65
                    and points[6][1] - points[8][1] > palm * 0.25
                    and distance(0, 8) > distance(0, 6) * 1.15
                    and distance(4, 8) > palm * PINCH_OPEN
                    and all(distance(0, tip) < distance(0, pip) * 1.1
                            for pip, tip in ((10, 12), (14, 16), (18, 20)))
                )
        if not pointing:
            self.since = None
            self.listening = False
        else:
            if self.since is None:
                self.since = now
            self.listening = now - self.since >= LISTEN_HOLD_SECONDS
        return self.listening


def draw_gesture(image, gesture, hand, idle, listen):
    height, width = image.shape[:2]
    color = (0, 220, 0) if gesture.holding else (0, 200, 255)
    state = "GREIFEN - Modell drehen" if gesture.holding else "OFFEN - keine Drehung"
    if listen.since is not None:
        color = (255, 255, 255)
        state = "SPRECHGESTE - Finger senken zum Senden" if listen.listening else "ZEIGEFINGER - 0.5 s halten"
    if not hand:
        state = "KEINE HAND - keine Drehung"
    cv2.rectangle(image, (0, 0), (width, 65), (25, 25, 25), -1)
    cv2.putText(image, state, (12, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
    mode = f"SPARSAM: {IDLE_FPS} FPS" if idle else "AKTIV"
    ratio = f" | Abstand: {gesture.ratio:.2f}" if gesture.ratio is not None else ""
    cv2.putText(image, mode + ratio, (12, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    if hand and gesture.cursor is not None:
        tips = [
            (round((1 - hand[i].x) * (width - 1)), round(hand[i].y * (height - 1)))
            for i in (4, 8)
        ]
        cv2.line(image, tips[0], tips[1], color, 2)
        cursor = tuple(round(value) for value in gesture.cursor)
        cv2.circle(image, cursor, 10, color, 2)
        if gesture.origin is not None:
            origin = tuple(round(value) for value in gesture.origin)
            cv2.circle(image, origin, 5, color, -1)
            cv2.arrowedLine(image, origin, cursor, color, 2, tipLength=0.15)


def run(service):
    """Camera worker; service owns stop signal, state and optional JPEG preview."""
    if not MODEL_PATH.is_file():
        raise FileNotFoundError(f"MediaPipe-Modell fehlt: {MODEL_PATH}")
    options = vision.HandLandmarkerOptions(
        base_options=python.BaseOptions(
            model_asset_path=str(MODEL_PATH),
            delegate=python.BaseOptions.Delegate.CPU,
        ),
        running_mode=vision.RunningMode.VIDEO,
        num_hands=1,
        min_hand_detection_confidence=0.55,
        min_hand_presence_confidence=0.55,
        min_tracking_confidence=0.5,
    )
    gesture = PinchDrag()
    listen = IndexHold()
    with vision.HandLandmarker.create_from_options(options) as landmarker:
        camera = Picamera2(0)
        try:
            camera.configure(camera.create_video_configuration(
                # Picamera2 BGR888 produces RGB bytes for MediaPipe.
                main={"size": (640, 480), "format": "BGR888"},
                controls={"FrameRate": 30}, buffer_count=4, queue=False,
            ))
            camera.start()
            previous_ms = -1
            last_hand_seen = None
            while not service.stop_event.is_set():
                started = time.monotonic()
                rgb = camera.capture_array("main")
                now = time.monotonic()
                timestamp_ms = max(previous_ms + 1, int(now * 1000))
                previous_ms = timestamp_ms
                result = landmarker.detect_for_video(
                    mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), timestamp_ms,
                )
                hand = result.hand_landmarks[0] if result.hand_landmarks else None
                if hand:
                    last_hand_seen = now
                idle = last_hand_seen is None or now - last_hand_seen >= IDLE_TIMEOUT_SECONDS
                height, width = rgb.shape[:2]
                event = gesture.update(hand, width, height)
                listening = listen.update(hand, width, height, now, blocked=gesture.holding)
                service.publish(event, idle, listening=listening)
                if service.wants_preview():
                    image = cv2.flip(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), 1)
                    for number, point in enumerate(hand or []):
                        if 0 <= point.x <= 1 and 0 <= point.y <= 1:
                            x, y = round((1 - point.x) * (width - 1)), round(point.y * (height - 1))
                            cv2.circle(image, (x, y), 4, (0, 200, 255), -1)
                            cv2.putText(image, str(number), (x + 5, y - 5),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
                    draw_gesture(image, gesture, hand, idle, listen)
                    ok, jpeg = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 75])
                    if ok:
                        service.set_preview(jpeg.tobytes())
                # Actually wait, instead of spinning through unused camera frames.
                fps = IDLE_FPS if idle else ACTIVE_FPS
                service.stop_event.wait(max(0, 1 / fps - (time.monotonic() - started)))
        finally:
            service.publish(("grab_end", 0, 0), True)
            camera.close()


if __name__ == "__main__":
    # The integrated launcher owns camera and web server in a single process.
    from pathlib import Path
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from main.brain_viewer import main
    main(["--gestures", *sys.argv[1:]])
