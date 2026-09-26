import unittest
from unittest.mock import patch

from main.gesture_service import GestureService
from main.brain_viewer import app


class GestureStateTests(unittest.TestCase):
    def test_cumulative_movement_and_release(self):
        service = GestureService()
        service.publish(('grab_start', 0, 0), False)
        service.publish(('grab_move', 0.1, -0.1), False)
        service.publish(('grab_move', 0.2, 0.05), False)
        service.publish(('grab_end', 0, 0), False)
        state = service.snapshot()
        self.assertAlmostEqual(state['x'], 0.3)
        self.assertAlmostEqual(state['y'], -0.05)
        self.assertFalse(state['holding'])
        self.assertEqual(state['grab_id'], 1)
        service.publish(('grab_start', 0, 0), False)
        self.assertEqual(service.snapshot()['x'], 0)
        self.assertEqual(service.snapshot()['grab_id'], 2)

    def test_open_movement_ignored_and_stale_hand_released(self):
        service = GestureService()
        service.publish(('grab_move', 0.5, 0.5), True)
        self.assertEqual(service.snapshot()['x'], 0)
        with patch('main.gesture_service.time.monotonic', return_value=10):
            service.publish(('grab_start', 0, 0), False)
        with patch('main.gesture_service.time.monotonic', return_value=12.1):
            self.assertFalse(service.snapshot()['connected'])
            self.assertFalse(service.snapshot()['holding'])

    def test_preview_is_on_demand_and_expires(self):
        service = GestureService()
        with patch('main.gesture_service.time.monotonic', return_value=10):
            self.assertFalse(service.wants_preview())
            self.assertIsNone(service.preview())
            self.assertTrue(service.wants_preview())
        with patch('main.gesture_service.time.monotonic', return_value=12.1):
            self.assertFalse(service.wants_preview())

    def test_routes_never_start_camera_and_do_not_cache(self):
        service = GestureService()
        with patch('main.brain_viewer.gestures', service):
            client = app.test_client()
            result = client.get('/api/gestures/state')
            self.assertEqual(result.json['status'], 'disabled')
            self.assertEqual(result.headers['Cache-Control'], 'no-store')
            self.assertEqual(client.get('/api/gestures/preview').status_code, 204)
            service.set_preview(b'jpeg')
            self.assertEqual(client.get('/api/gestures/preview').data, b'jpeg')
            self.assertIsNone(service.thread)
            self.assertEqual(client.post('/api/gestures/state').status_code, 405)

    def test_worker_failure_visible_without_crashing_viewer(self):
        service = GestureService()
        with patch('main.gesture_control.run', side_effect=RuntimeError('camera busy')):
            service._run()
        self.assertEqual(service.snapshot()['error'], 'camera busy')
        self.assertFalse(service.snapshot()['holding'])


if __name__ == '__main__':
    unittest.main()
