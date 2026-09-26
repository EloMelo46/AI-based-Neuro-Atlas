import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from main import desktop_launcher as launcher


class DesktopLauncherTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        python = root / '.venv/bin/python'
        python.parent.mkdir(parents=True)
        python.touch()
        for attribute, value in [('ROOT', root), ('STATE', root / '.local')]:
            mocked = patch.object(launcher, attribute, value)
            mocked.start()
            self.addCleanup(mocked.stop)
        mocked = patch.object(launcher.shutil, 'which', return_value='/usr/bin/chromium')
        mocked.start()
        self.addCleanup(mocked.stop)
        self.browser = MagicMock()
        self.browser.wait.return_value = 0
        self.browser.poll.return_value = 0
        self.server = MagicMock()
        self.server.poll.return_value = None

    def test_existing_server_is_reused_and_never_terminated(self):
        with patch.object(launcher, 'viewer_ready', return_value=True), \
                patch.object(launcher.subprocess, 'Popen', return_value=self.browser) as spawn:
            launcher.launch()
        self.assertEqual(spawn.call_count, 1)
        self.assertIn('--kiosk', spawn.call_args.args[0])
        self.browser.terminate.assert_not_called()

    def test_owned_server_starts_with_gestures_and_is_stopped(self):
        with patch.object(launcher, 'viewer_ready', side_effect=[False, True]), \
                patch.object(launcher.subprocess, 'Popen', side_effect=[self.server, self.browser]) as spawn:
            launcher.launch()
        self.assertIn('--gestures', spawn.call_args_list[0].args[0])
        self.assertEqual(spawn.call_count, 2)
        self.server.terminate.assert_called_once()

    def test_browser_failure_stops_owned_server(self):
        with patch.object(launcher, 'viewer_ready', side_effect=[False, True]), \
                patch.object(launcher.subprocess, 'Popen', side_effect=[self.server, OSError('browser failed')]):
            with self.assertRaises(OSError):
                launcher.launch()
        self.server.terminate.assert_called_once()

    def test_second_launcher_does_not_spawn_anything(self):
        with patch.object(launcher.fcntl, 'flock', side_effect=BlockingIOError), \
                patch.object(launcher.subprocess, 'Popen') as spawn:
            launcher.launch()
        spawn.assert_not_called()


if __name__ == '__main__':
    unittest.main()
