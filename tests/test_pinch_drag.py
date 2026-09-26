import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from main import gesture_control as gc


def hand(gap=0.02, x=0.5, y=0.4, scale=1):
    points = [SimpleNamespace(x=x, y=y) for _ in range(21)]
    points[4].x = x - gap * scale / 2
    points[8].x = x + gap * scale / 2
    points[5].x = x - 0.1 * scale
    points[17].x = x + 0.1 * scale
    return points


class PinchTests(unittest.TestCase):
    def test_hold_hysteresis_and_release(self):
        drag = gc.PinchDrag()
        self.assertIsNone(drag.update(hand(gap=0.12), 640, 480))
        self.assertEqual(drag.update(hand(), 640, 480)[0], 'grab_start')
        self.assertEqual(drag.update(hand(gap=0.09), 640, 480)[0], 'grab_move')
        self.assertTrue(drag.holding)
        self.assertEqual(drag.update(hand(gap=0.12), 640, 480)[0], 'grab_end')
        self.assertIsNone(drag.update(hand(gap=0.09), 640, 480))
        self.assertFalse(drag.holding)

    def test_open_hand_never_rotates(self):
        drag = gc.PinchDrag()
        self.assertIsNone(drag.update(hand(gap=0.12), 640, 480))
        self.assertIsNone(drag.update(hand(gap=0.12, x=0.3), 640, 480))

    def test_threshold_independent_of_hand_size(self):
        for scale in (0.5, 1, 2):
            drag = gc.PinchDrag()
            self.assertEqual(drag.update(hand(scale=scale), 640, 480)[0], 'grab_start')
            self.assertEqual(drag.update(hand(gap=0.12, scale=scale), 640, 480)[0], 'grab_end')

    def test_mirrored_drag_and_loss_without_reacquisition_jump(self):
        drag = gc.PinchDrag()
        drag.update(hand(), 640, 480)
        action, dx, dy = drag.update(hand(x=0.4, y=0.5), 640, 480)
        self.assertEqual(action, 'grab_move')
        self.assertGreater(dx, 0)
        self.assertGreater(dy, 0)
        self.assertEqual(drag.update(None, 640, 480)[0], 'grab_end')
        self.assertIsNone(drag.update(None, 640, 480))
        self.assertIsNone(drag.update(hand(gap=0.12, x=0.8), 640, 480))

    def test_degenerate_hand_releases_button(self):
        drag = gc.PinchDrag()
        drag.update(hand(), 640, 480)
        self.assertEqual(drag.update(hand(scale=0), 640, 480)[0], 'grab_end')



class WorkerTimingTests(unittest.TestCase):
    def test_idle_rate_timeout_reset_and_camera_cleanup(self):
        import numpy as np
        clock = [0.0]
        published = []
        service = MagicMock()
        service.stop_event.is_set.side_effect = lambda: clock[0] >= 115
        service.stop_event.wait.side_effect = lambda seconds: clock.__setitem__(0, clock[0] + max(seconds, 0.001))
        service.wants_preview.return_value = False
        service.publish.side_effect = lambda event, idle: published.append((clock[0], event, idle))
        camera = MagicMock()
        camera.capture_array.return_value = np.zeros((480, 640, 3), dtype=np.uint8)
        landmarker = MagicMock()
        landmarker.detect_for_video.side_effect = lambda *args: SimpleNamespace(
            hand_landmarks=[hand()] if 1 <= clock[0] < 2 or 40 <= clock[0] < 41 or 110 <= clock[0] < 111 else [])
        context = MagicMock()
        context.__enter__.return_value = landmarker
        with patch.object(gc, 'Picamera2', return_value=camera), \
                patch.object(gc.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(gc.vision.HandLandmarker, 'create_from_options', return_value=context), \
                patch.object(gc.mp, 'Image'):
            gc.run(service)
        def intervals(start, end):
            times = [time for time, _, _ in published if start <= time < end]
            return [b - a for a, b in zip(times, times[1:])]
        self.assertGreaterEqual(min(intervals(0, 1)), 1 / gc.IDLE_FPS - 1e-8)
        self.assertLessEqual(max(intervals(3, 39)), 1 / gc.ACTIVE_FPS + 1e-8)
        self.assertTrue(all(not idle for time, _, idle in published if 65 <= time < 100))
        self.assertGreaterEqual(min(intervals(102, 109)), 1 / gc.IDLE_FPS - 1e-8)
        self.assertLessEqual(max(intervals(112, 114)), 1 / gc.ACTIVE_FPS + 1e-8)
        camera.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
