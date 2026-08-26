import json
import threading
import unittest

from bearer_proxy.server import ProxyHTTPServer, build_application
from tests.helpers import make_config, request, start_callback_server, stop_server


class EndToEndTests(unittest.TestCase):
    def _start_proxy(self, cfg):
        app = build_application(cfg)
        app.token_manager.refresh(force=True)
        server = ProxyHTTPServer(("127.0.0.1", 0), app)
        thread = threading.Thread(target=server.serve_forever)
        thread.daemon = True
        thread.start()
        return server, thread, app

    def _stop_proxy(self, server, thread):
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    def test_json_login_profile_401_reauthentication_and_replay(self):
        state = {"auth_count": 0, "data_requests": [], "valid_token": None}

        def upstream(record, state):
            if record["path"] == "/api/login" and record["method"] == "POST":
                payload = json.loads(record["body"].decode("utf-8"))
                if payload != {"username": "test-user", "password": "test-password"}:
                    return 401, {"Content-Type": "application/json"}, b"{}"
                state["auth_count"] += 1
                token = "TOKEN_A" if state["auth_count"] == 1 else "TOKEN_B"
                state["valid_token"] = token
                return 200, {"Content-Type": "application/json"}, json.dumps({"access_token": token}).encode("utf-8")
            if record["path"] == "/api/data" and record["method"] == "GET":
                state["data_requests"].append(record)
                if record["headers"].get("Authorization") != "Bearer {0}".format(state["valid_token"]):
                    return 401, {"Content-Type": "application/json"}, b'{"error":"invalid"}'
                return 200, {"Content-Type": "application/json"}, b'{"records":[1,2,3]}'
            return 404, {"Content-Type": "application/json"}, b"{}"

        upstream_server, upstream_thread = start_callback_server(upstream, state)
        try:
            base = "http://127.0.0.1:{0}".format(upstream_server.server_port)
            cfg = make_config(
                {
                    "auth": {
                        "base_url": base,
                        "request": {
                            "method": "POST",
                            "path": "/api/login",
                            "headers": {"Accept": "application/json"},
                            "body_type": "json",
                            "body": {
                                "username": "test-user",
                                "password": "test-password",
                            },
                        },
                        "token": {"source": "json", "json_pointer": "/access_token", "expires_in_json_pointer": None},
                        "validation": {"enabled": True, "method": "GET", "path": "/api/data", "expected_statuses": [200]},
                    },
                    "upstream": {"base_url": base, "allowed_paths": ["/api/data"]},
                },
                auth_base=base,
                upstream_base=base,
            )
            cfg.auth.request.body = {"username": "test-user", "password": "test-password"}
            proxy, proxy_thread, app = self._start_proxy(cfg)
            try:
                url = "http://127.0.0.1:{0}/proxy/api/data".format(proxy.server_port)
                self.assertEqual(json.loads(request(url)[2].decode("utf-8"))["records"], [1, 2, 3])
                state["valid_token"] = "SERVER_INVALIDATED_TOKEN"
                self.assertEqual(json.loads(request(url)[2].decode("utf-8"))["records"], [1, 2, 3])
                self.assertEqual(state["auth_count"], 2)
                self.assertEqual(app.token_manager.get_token(), "TOKEN_B")
                self.assertEqual(state["data_requests"][-1]["path"], "/api/data")
            finally:
                self._stop_proxy(proxy, proxy_thread)
        finally:
            stop_server(upstream_server, upstream_thread)

    def test_oauth_client_credentials_profile_without_python_changes(self):
        state = {"auth_count": 0, "valid_token": None, "jobs": []}

        def upstream(record, state):
            if record["path"] == "/oauth/token" and record["method"] == "POST":
                state["auth_count"] += 1
                token = "TOKEN_{0}".format(state["auth_count"])
                state["valid_token"] = token
                return 200, {"Content-Type": "application/json"}, json.dumps({"access_token": token, "expires_in": 3600}).encode("utf-8")
            if record["path"] in ("/api/v1/data", "/api/v1/jobs", "/api/v1/plain-text"):
                if record["headers"].get("Authorization") != "Bearer {0}".format(state["valid_token"]):
                    return 401, {"Content-Type": "application/json"}, b'{"error":"invalid"}'
                if record["path"] == "/api/v1/jobs":
                    state["jobs"].append(record["body"])
                    return 202, {"Content-Type": "application/json"}, b'{"queued":true}'
                if record["path"] == "/api/v1/plain-text":
                    return 200, {"Content-Type": "text/plain"}, b"plain response"
                return 200, {"Content-Type": "application/json"}, b'{"value":1}'
            return 404, {}, b""

        upstream_server, upstream_thread = start_callback_server(upstream, state)
        try:
            base = "http://127.0.0.1:{0}".format(upstream_server.server_port)
            cfg = make_config(
                {
                    "auth": {
                        "base_url": base,
                        "request": {
                            "method": "POST",
                            "path": "/oauth/token",
                            "headers": {"Accept": "application/json"},
                            "body_type": "form",
                            "body": {"grant_type": "client_credentials", "client_id": "client", "client_secret": "secret"},
                        },
                        "token": {"source": "json", "json_pointer": "/access_token", "expires_in_json_pointer": "/expires_in"},
                        "validation": {"enabled": True, "method": "GET", "path": "/api/v1/data", "expected_statuses": [200]},
                    },
                    "upstream": {"base_url": base, "allowed_paths": ["/api/v1/*"]},
                },
                auth_base=base,
                upstream_base=base,
            )
            proxy, proxy_thread, app = self._start_proxy(cfg)
            try:
                base_url = "http://127.0.0.1:{0}".format(proxy.server_port)
                self.assertEqual(json.loads(request(base_url + "/proxy/api/v1/data")[2].decode("utf-8"))["value"], 1)
                status, headers, body = request(base_url + "/proxy/api/v1/jobs", method="POST", headers={"Content-Type": "application/json"}, body=b'{"job":1}')
                self.assertEqual(status, 202)
                self.assertEqual(state["jobs"], [b'{"job":1}'])
                self.assertEqual(request(base_url + "/proxy/api/v1/plain-text")[2], b"plain response")
                state["valid_token"] = "INVALIDATED"
                self.assertEqual(json.loads(request(base_url + "/proxy/api/v1/data")[2].decode("utf-8"))["value"], 1)
                self.assertEqual(state["auth_count"], 2)
                self.assertEqual(app.token_manager.get_token(), "TOKEN_2")
            finally:
                self._stop_proxy(proxy, proxy_thread)
        finally:
            stop_server(upstream_server, upstream_thread)


if __name__ == "__main__":
    unittest.main()
