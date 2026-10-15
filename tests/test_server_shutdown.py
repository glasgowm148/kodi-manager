import http.client
from http.server import BaseHTTPRequestHandler
from pathlib import Path
import sys
import threading
import time
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
        # The blocked handler below holds its request for 10 s; stopping must not wait for it.
        stopped = threading.Thread(target=service.stop, daemon=True)
        stopped.start()
        stopped.join(3)
        self.assertFalse(stopped.is_alive(), 'Shutdown blocked on server thread')

    def test_stop_before_server_thread_starts(self):
        service = self.create_server(BaseHTTPRequestHandler)
        self.stop_without_waiting(service)
        service.start()
        service.join(3)
        self.assertFalse(service.is_alive())

    def test_stop_closes_only_the_listening_socket(self):
        service = self.create_server(BaseHTTPRequestHandler)
        self.assertFalse(service.httpd.block_on_close)
        with patch.object(service.httpd, 'server_close', side_effect=AssertionError('joined handlers')):
            self.stop_without_waiting(service)
        self.assertEqual(service.httpd.socket.fileno(), -1)
        self.assertTrue(service.stopping.is_set())

    def test_stop_interrupts_saturated_handler_admission(self):
        service = self.create_server(BaseHTTPRequestHandler)
        service.httpd.slot_wait = 30
        for _ in range(service.httpd.max_handlers):
            self.assertTrue(service.httpd._slots.acquire(blocking=False))
        waiting = threading.Event()
        original = service.httpd._slots.acquire

        def acquire(*args, **kwargs):
            waiting.set()
            return original(*args, **kwargs)

        port = service.httpd.server_address[1]
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
        try:
            with patch.object(service.httpd._slots, 'acquire', side_effect=acquire):
                service.start()
                connection.request('GET', '/')
                self.assertTrue(waiting.wait(3))
                self.stop_without_waiting(service)
                service.join(1)
                self.assertFalse(service.is_alive(), 'Admission still waits for an occupied handler slot')
                self.assertEqual(service.httpd._clients, {})
        finally:
            connection.close()
            service.stop()
            for _ in range(service.httpd.max_handlers):
                service.httpd._slots.release()

    def test_stop_while_request_waits_for_kodi(self):
        entered, release = threading.Event(), threading.Event()

        class WaitingHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                entered.set()
                release.wait(10)
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
            self.assertTrue(entered.wait(5))
            self.stop_without_waiting(service)
            service.join(3)
            self.assertFalse(service.is_alive())
            # A new profile can immediately bind the same service port.
            replacement = server.ThreadingHTTPServer(('127.0.0.1', port), BaseHTTPRequestHandler)
            replacement.server_close()
        finally:
            release.set()
            client.join(3)

    def test_port_can_be_rebound_immediately_after_stop(self):
        # Allow LAN toggles restart the server on the same port without joining the old
        # thread: a select() still polling the old socket must not keep the port bound.
        for attempt in range(10):
            service = self.create_server(BaseHTTPRequestHandler)
            port = service.httpd.server_address[1]
            service.start()
            time.sleep(0.02 + (attempt % 5) * 0.03)
            service.stop()
            try:
                replacement = server.BoundedThreadingHTTPServer(('127.0.0.1', port), BaseHTTPRequestHandler)
                replacement.server_close()
            finally:
                service.join(3)
            self.assertFalse(service.is_alive())


if __name__ == '__main__':
    unittest.main()
