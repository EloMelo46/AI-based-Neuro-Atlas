import unittest
from types import SimpleNamespace
from unittest.mock import patch

from main.gesture_control import IndexHold, PinchDrag
from main.gesture_service import GestureService


def pointing_hand(scale=1, mirror=False):
    points = [SimpleNamespace(x=0.5, y=0.6) for _ in range(21)]
    positions = {0:(.5,.8), 4:(.43,.64), 5:(.4,.55), 6:(.4,.35),
                 7:(.4,.24), 8:(.4,.15), 9:(.48,.54), 10:(.48,.5), 12:(.48,.67),
                 13:(.54,.54), 14:(.54,.52), 16:(.54,.69),
                 17:(.6,.55), 18:(.6,.55), 20:(.6,.7)}
    for i, (x,y) in positions.items():
        points[i] = SimpleNamespace(x=.5+(x-.5)*scale*(-1 if mirror else 1), y=.5+(y-.5)*scale)
    return points


class IndexHoldTests(unittest.TestCase):
    def test_continuous_half_second_then_immediate_release(self):
        gesture = IndexHold()
        hand = pointing_hand()
        self.assertFalse(gesture.update(hand,640,480,10))
        self.assertFalse(gesture.update(hand,640,480,10.49))
        self.assertTrue(gesture.update(hand,640,480,10.5))
        self.assertTrue(gesture.update(hand,640,480,12))
        self.assertFalse(gesture.update(None,640,480,12.05))
        self.assertFalse(gesture.update(hand,640,480,12.1))
        self.assertFalse(gesture.update(hand,640,480,12.59))
        self.assertTrue(gesture.update(hand,640,480,12.61))

    def test_interrupted_candidate_starts_delay_again(self):
        gesture = IndexHold()
        hand = pointing_hand()
        gesture.update(hand,640,480,0)
        gesture.update(None,640,480,.4)
        self.assertFalse(gesture.update(hand,640,480,.5))
        self.assertFalse(gesture.update(hand,640,480,.99))
        self.assertTrue(gesture.update(hand,640,480,1))

    def test_both_hands_and_scales(self):
        for mirror in (False,True):
            for scale in (.5,1,1.5):
                gesture = IndexHold()
                hand = pointing_hand(scale,mirror)
                gesture.update(hand,640,480,0)
                self.assertTrue(gesture.update(hand,640,480,.5))
                self.assertIsNone(PinchDrag().update(hand,640,480))

    def test_open_hand_pinch_downward_and_degenerate_are_rejected(self):
        candidates=[]
        hand=pointing_hand()
        for tip in (12,16,20): hand[tip].y=.1
        candidates.append(hand)
        hand=pointing_hand(); hand[4]=hand[8]; candidates.append(hand)
        hand=pointing_hand()
        for p in hand: p.y=1-p.y
        candidates.append(hand)
        candidates.append(pointing_hand(scale=0))
        for hand in candidates:
            gesture=IndexHold()
            self.assertFalse(gesture.update(hand,640,480,0))
            self.assertFalse(gesture.update(hand,640,480,1))

    def test_grab_blocks_and_resets_listen(self):
        gesture=IndexHold(); hand=pointing_hand()
        gesture.update(hand,640,480,0)
        self.assertTrue(gesture.update(hand,640,480,.5))
        self.assertFalse(gesture.update(hand,640,480,.6,blocked=True))
        self.assertFalse(gesture.update(hand,640,480,.7))

    def test_service_edges_staleness_and_stop(self):
        service=GestureService()
        with patch('main.gesture_service.time.monotonic',return_value=10):
            service.publish(None,False,listening=True)
            service.publish(None,False,listening=True)
            state=service.snapshot()
            self.assertTrue(state['listening'])
            self.assertEqual(state['listen_id'],1)
        with patch('main.gesture_service.time.monotonic',return_value=12.1):
            self.assertFalse(service.snapshot()['listening'])
        service.publish(None,False,listening=False)
        service.publish(None,False,listening=True)
        self.assertEqual(service.snapshot()['listen_id'],2)
        service.stop()
        self.assertFalse(service.snapshot()['listening'])


if __name__=='__main__':
    unittest.main()
