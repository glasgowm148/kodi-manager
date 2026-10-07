import http.client
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "kodi_manager"))
import server


class WidgetEndpointTests(unittest.TestCase):
    def test_readonly_blocks_install_restore_and_remote_windows(self):
        for path in ('/api/addons/install', '/api/stack/restore', '/api/addons/plugin.test/restore', '/api/addons/plugin.test/open-settings'):
            self.assertEqual(self.request('POST', path, {})[0], 403)
        self.state.index.refresh.assert_not_called()

    def setUp(self):
        self.players = []
        self.state = SimpleNamespace(kodi=SimpleNamespace(jsonrpc=lambda method, params=None: {"result": self.players}, open_install_from_zip=Mock(return_value={"opened": True, "next_step": "Choose the ZIP"})), index=SimpleNamespace(refresh=Mock()), config={"auth_token": "test-session", "host": "127.0.0.1", "write_enabled": False}, log=lambda *_: None)
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(self.state))
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()

    def request(self, method, path, body=None, auth=True):
        connection = http.client.HTTPConnection(*self.http.server_address)
        headers = {"Content-Type": "application/json"}
        if auth:
            headers["Authorization"] = "Bearer test-session"
        connection.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
        response = connection.getresponse()
        status, payload = response.status, json.loads(response.read())
        connection.close()
        return status, payload

    def test_widget_read_endpoints_require_existing_auth(self):
        for method, path in (("GET", "/api/widgets/sources"), ("GET", "/api/widgets/layout"), ("POST", "/api/widgets/browse"), ("POST", "/api/widgets/suggestions"), ("POST", "/api/widgets/layout/preview"), ("POST", "/api/widgets/layout/apply"), ("POST", "/api/widgets/layout/rebuild")):
            self.assertEqual(self.request(method, path, body={} if method == "POST" else None, auth=False)[0], 401)
        self.state.index.refresh.assert_not_called()

    def test_sources_and_suggestions_dispatch_with_refreshed_index(self):
        with patch.object(server, "list_sources", return_value={"sources": [{"addon_id": "plugin.video.pov"}]}) as sources:
            status, payload = self.request("GET", "/api/widgets/sources")
            self.assertEqual(status, 200)
            self.assertEqual(payload["data"]["sources"][0]["addon_id"], "plugin.video.pov")
            sources.assert_called_once_with(self.state.kodi, self.state.index)
        with patch.object(server, "suggest_kids_rows", return_value={"rows": [], "recommendations": ["Family movies"]}) as suggestions:
            self.assertEqual(self.request("POST", "/api/widgets/suggestions", {})[0], 200)
            suggestions.assert_called_once_with(self.state.kodi, self.state.index)
        self.assertEqual(self.state.index.refresh.call_count, 2)

    def test_browse_family_preview_keeps_paths_and_excludes_unknown_ratings(self):
        items = [{"label": "Family", "path": "plugin://plugin.video.pov/?id=1", "mpaa": "PG", "genre": ["Family"]}, {"label": "Unknown", "path": "plugin://plugin.video.pov/?id=2", "genre": ["Family"]}]
        with patch.object(server, "browse_directory", return_value={"items": items}) as browse:
            status, payload = self.request("POST", "/api/widgets/browse", {"path": "plugin://plugin.video.pov/", "start": 2, "limit": 10, "family_preview": True, "max_rating": "12A"})
            browse.assert_called_once_with(self.state.kodi, self.state.index, "plugin://plugin.video.pov/", 2, 10, refresh=False)
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["data"]["items"]), 2)
        self.assertEqual([item["label"] for item in payload["data"]["family_preview"]["files"]], ["Family"])
        self.assertEqual(payload["data"]["family_preview"]["files"][0]["path"], "plugin://plugin.video.pov/?id=1")

    def test_inspection_and_preview_disable_apply_when_writes_disabled(self):
        for method, path, function in (("GET", "/api/widgets/layout", "inspect_layout"), ("POST", "/api/widgets/layout/preview", "preview_layout")):
            with patch.object(server, function, return_value={"can_apply": True, "reasons": [], "exports": [], "sections": [{"id": "movies", "editable": True}], "new_section_available": True}):
                status, payload = self.request(method, path, {} if method == "POST" else None)
                self.assertEqual(status, 200)
                self.assertFalse(payload["data"]["can_apply"])
                self.assertFalse(payload["data"]["new_section_available"])
                self.assertFalse(payload["data"]["sections"][0]["editable"])
                self.assertTrue(any("Write Mode is disabled" in reason for reason in payload["data"]["reasons"]))

    def test_apply_write_gate_and_enabled_dispatch_do_not_write_in_test(self):
        body = {"label": "Kids", "expected_revision": "reviewed", "rows": []}
        with patch.object(server, "apply_layout", return_value={"backup_id": "mock-only"}) as apply:
            self.assertEqual(self.request("POST", "/api/widgets/layout/apply", body)[0], 403)
            apply.assert_not_called()
            self.state.config["write_enabled"] = True
            status, payload = self.request("POST", "/api/widgets/layout/apply", body)
            self.assertEqual(status, 200)
            self.assertEqual(payload["data"]["backup_id"], "mock-only")
            apply.assert_called_once_with(self.state.kodi, self.state.index, body, True)

    def test_invalid_preview_type_and_rating_fail_without_action(self):
        with patch.object(server, "browse_directory", return_value={"items": []}) as browse:
            self.assertEqual(self.request("POST", "/api/widgets/browse", {"family_preview": "true"})[0], 400)
            browse.assert_not_called()
            self.assertEqual(self.request("POST", "/api/widgets/browse", {"family_preview": True, "max_rating": "R"})[0], 400)
        with patch.object(server, "preview_layout") as preview:
            self.assertEqual(self.request("POST", "/api/widgets/layout/preview", ["wrong shape"])[0], 400)
            preview.assert_not_called()

    def test_rebuild_requires_write_mode_and_dispatches_once_when_enabled(self):
        with patch.object(server, "request_rebuild", return_value={"requested": True}) as rebuild, patch.object(server, "apply_layout") as apply:
            status, payload = self.request("POST", "/api/widgets/layout/rebuild", {})
            self.assertEqual(status, 403)
            self.assertIn("Write Mode is disabled", payload["error"]["message"])
            rebuild.assert_not_called()
            self.state.config["write_enabled"] = True
            status, payload = self.request("POST", "/api/widgets/layout/rebuild", {})
            self.assertEqual(status, 200)
            self.assertTrue(payload["data"]["requested"])
            rebuild.assert_called_once_with(self.state.kodi, self.state.index)
            apply.assert_not_called()

    def test_rebuild_is_refused_during_playback(self):
        self.state.config["write_enabled"] = True
        self.players = [{"playerid": 1}]
        with patch.object(server, "request_rebuild") as rebuild:
            status, payload = self.request("POST", "/api/widgets/layout/rebuild", {})
        self.assertEqual(status, 400)
        self.assertIn("Stop playback", payload["error"]["message"])
        rebuild.assert_not_called()

    def test_install_opens_kodi_zip_dialog_only_when_idle(self):
        self.state.config["write_enabled"] = True
        self.players = [{"playerid": 1}]
        self.assertEqual(self.request("POST", "/api/addons/install", {})[0], 400)
        self.state.kodi.open_install_from_zip.assert_not_called()
        self.players = []
        status, payload = self.request("POST", "/api/addons/install", {"source_path": "ignored.zip"})
        self.assertEqual(status, 200)
        self.assertTrue(payload["data"]["opened"])
        self.state.kodi.open_install_from_zip.assert_called_once_with()

    def test_non_ascii_bearer_header_is_rejected_cleanly(self):
        connection = http.client.HTTPConnection(*self.http.server_address)
        connection.putrequest("GET", "/api/status")
        connection.putheader("Authorization", "Bearer t\xf6ken".encode("latin-1"))
        connection.endheaders()
        response = connection.getresponse()
        self.assertEqual(response.status, 401)
        connection.close()

    def test_fix_checks_require_auth_and_repairs_require_idle_write_mode(self):
        for method, path in [('GET', '/api/fixes'), ('POST', '/api/fixes/repair')]:
            self.assertEqual(self.request(method, path, {} if method == 'POST' else None, auth=False)[0], 401)
        protection = Mock()
        protection.status.return_value = {'healthy': True}
        protection.repair.return_value = {'restored_files': 1}
        with patch.object(server, 'protection_for_kodi', return_value=protection):
            self.assertEqual(self.request('GET', '/api/fixes')[0], 200)
            self.assertEqual(self.request('POST', '/api/fixes/repair', {})[0], 403)
            protection.repair.assert_not_called()
            self.state.config['write_enabled'] = True
            self.state.kodi = Mock()
            self.state.kodi.jsonrpc.return_value = {'result': [{'playerid': 1}]}
            self.assertEqual(self.request('POST', '/api/fixes/repair', {})[0], 400)
            protection.repair.assert_not_called()
            self.state.kodi.jsonrpc.return_value = {'result': []}
            self.assertEqual(self.request('POST', '/api/fixes/repair', {})[0], 200)
            protection.repair.assert_called_once()


if __name__ == "__main__":
    unittest.main()
