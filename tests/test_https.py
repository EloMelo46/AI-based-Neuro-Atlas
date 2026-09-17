"""Exercise HTTPS backend semantics over a real Waitress listener, without API calls."""
import argparse
import http.client
import unittest
from threading import Thread

from main.brain_viewer import app
from main.https_server import create_backend, host_address


class HTTPSBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_config = {key: app.config[key] for key in ('SESSION_COOKIE_SECURE', 'SESSION_COOKIE_NAME')}
        cls.server = create_backend(0)
        cls.thread = Thread(target=cls.server.run, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.task_dispatcher.shutdown()
        cls.server.close()
        cls.thread.join(timeout=3)
        app.config.update(cls.old_config)

    def request(self, origin, cookie=None, extra_headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.effective_port, timeout=5)
        headers = {'Host': '192.168.1.213:8443', 'Origin': origin, 'X-Brain-Viewer': '1'}
        if cookie:
            headers['Cookie'] = cookie
        headers.update(extra_headers or {})
        try:
            connection.request('POST', '/api/assistant/reset', headers=headers)
            response = connection.getresponse()
            response.read()
            return response.status, response.getheader('Set-Cookie')
        finally:
            connection.close()

    def test_https_origin_and_secure_session_roundtrip(self):
        self.assertEqual(self.server.effective_host, '127.0.0.1')
        status, cookie = self.request('https://192.168.1.213:8443')
        self.assertEqual(status, 200)
        for value in ('neuro_atlas_https=', 'Secure', 'HttpOnly', 'SameSite=Strict'):
            self.assertIn(value, cookie)
        status, next_cookie = self.request('https://192.168.1.213:8443', cookie.split(';')[0])
        self.assertEqual(status, 200)
        self.assertIsNone(next_cookie, 'Existing conversation should reuse its session')

    def test_other_origins_and_spoofed_proxy_headers_are_rejected(self):
        for origin in ('http://192.168.1.213:8443', 'https://other.example', 'https://192.168.1.213:5000'):
            with self.subTest(origin=origin):
                status, _ = self.request(origin, extra_headers={'X-Forwarded-Proto': 'http',
                                                               'X-Forwarded-Host': 'other.example'})
                self.assertEqual(status, 403)

    def test_host_rejects_wildcards_public_ips_and_config_injection(self):
        for value in ('0.0.0.0', '::', '8.8.8.8', 'example.com', 'localhost\n{', '192.168.1.1:8443', 'fe80::1%eth0\n{'):
            with self.subTest(host=value), self.assertRaises(argparse.ArgumentTypeError):
                host_address(value)


if __name__ == '__main__':
    unittest.main()
