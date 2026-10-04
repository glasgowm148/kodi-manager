import http.client
from http.server import BaseHTTPRequestHandler
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'kodi_manager'))
import server


class ServerShutdownTests(unittest.TestCase):
    def create_server(self, handler):
        config = {'host': '127.0.0.1', 'port': 0}
        with patch.object(server, 'AdminState', return_value=Mock(config=config)), patch.object(server, 'make_handler', return_value=handler):
            return server.ServerThread(Mock(), config, '')

    def stop_without_waiting(self, service):
        stopped = threading.Thread(target=service.stop, daemon=True)
        stopped.start()
        stopped.join(0.8)
        self.assertFalse(stopped.is_alive(), 'Shutdown blocked on server thread')

    def test_stop_before_server_thread_starts(self):
        service = self.create_server(BaseHTTPRequestHandler)
        self.stop_without_waiting(service)
        service.start()
        service.join(0.8)
        self.assertFalse(service.is_alive())

    def test_stop_while_request_waits_for_kodi(self):
        entered, release = threading.Event(), threading.Event()

        class WaitingHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                entered.set()
                release.wait(2)
                self.send_response(204)
                self.end_headers()

            def log_message(self, *args):
                pass

        service = self.create_server(WaitingHandler)
        port = service.httpd.server_address[1]
        service.start()

        def request():
            connection = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
            try:
                connection.request('GET', '/')
                connection.getresponse().read()
            finally:
                connection.close()

        client = threading.Thread(target=request, daemon=True)
        client.start()
        try:
            self.assertTrue(entered.wait(1))
            self.stop_without_waiting(service)
            service.join(0.8)
            self.assertFalse(service.is_alive())
            # A new profile can immediately bind the same service port.
            replacement = server.ThreadingHTTPServer(('127.0.0.1', port), BaseHTTPRequestHandler)
            replacement.server_close()
        finally:
            release.set()
            client.join(3)


if __name__ == '__main__':
    unittest.main()
