import socket
import threading
import unittest

from bearer_proxy.http_client import HTTPResponse
from bearer_proxy.security import is_loopback_bind, validate_bind_security
from bearer_proxy.server import ProxyApplication, ProxyHTTPServer
from tests.helpers import FakeAPIClient, FakeTokenManager, make_config, request


class ServerTests(unittest.TestCase):
    def _start_proxy(self, cfg=None, api_client=None, manager=None):
        app = ProxyApplication(cfg or make_config(), api_client or FakeAPIClient(), manager or FakeTokenManager())
        server = ProxyHTTPServer(("127.0.0.1", 0), app)
        thread = threading.Thread(target=server.serve_forever)
        thread.daemon = True
        thread.start()
        return server, thread, app

    def _stop(self, server, thread):
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    def test_health_ready_metrics_do_not_expose_token(self):
        server, thread, app = self._start_proxy(manager=FakeTokenManager("SECRET_TOKEN"))
        try:
            base = "http://127.0.0.1:{0}".format(server.server_port)
            for path in ["/healthz", "/readyz", "/metrics"]:
                status, headers, body = request(base + path)
                self.assertEqual(status, 200)
                self.assertNotIn(b"SECRET_TOKEN", body)
        finally:
            self._stop(server, thread)

    def test_local_proxy_key_required_when_configured(self):
        cfg = make_config({"server": {"proxy_api_key": "KEY"}})
        server, thread, app = self._start_proxy(cfg=cfg)
        try:
            base = "http://127.0.0.1:{0}/proxy/api/data".format(server.server_port)
            self.assertEqual(request(base)[0], 401)
            self.assertEqual(request(base, headers={"X-Bearer-Proxy-Key": "BAD"})[0], 401)
            self.assertEqual(request(base, headers={"X-Bearer-Proxy-Key": "KEY"})[0], 200)
        finally:
            self._stop(server, thread)

    def test_non_loopback_protection_and_loopback_detection(self):
        self.assertTrue(is_loopback_bind("127.0.0.1"))
        self.assertTrue(is_loopback_bind("::1"))
        self.assertTrue(is_loopback_bind("localhost"))
        self.assertFalse(is_loopback_bind("0.0.0.0"))
        cfg = make_config({"server": {"bind_host": "0.0.0.0", "proxy_api_key": ""}})
        with self.assertRaises(Exception):
            validate_bind_security(cfg)

    def test_proxy_path_methods_query_and_headers(self):
        api = FakeAPIClient([HTTPResponse(201, b"created", {"Content-Type": "text/plain", "X-Upstream": "yes", "Connection": "close"})])
        server, thread, app = self._start_proxy(api_client=api)
        try:
            status, headers, body = request(
                "http://127.0.0.1:{0}/proxy/api/jobs?a=1".format(server.server_port),
                method="POST",
                headers={"Content-Type": "text/plain", "Authorization": "client-token", "X-Request-ID": "rid", "X-Blocked": "no"},
                body=b"payload",
            )
            self.assertEqual(status, 201)
            self.assertEqual(body, b"created")
            self.assertEqual(headers.get("X-Upstream"), "yes")
            self.assertNotIn("Connection", headers)
            self.assertEqual(api.requests[0]["path"], "/api/jobs")
            self.assertEqual(api.requests[0]["query"], "a=1")
            self.assertEqual(api.requests[0]["body"], b"payload")
            self.assertIn("x-request-id", [key.lower() for key in api.requests[0]["headers"].keys()])
            self.assertNotIn("Authorization", api.requests[0]["headers"])
            self.assertNotIn("X-Blocked", api.requests[0]["headers"])
        finally:
            self._stop(server, thread)

    def test_disallowed_method_path_and_auth_endpoint_blocking(self):
        cfg = make_config({"upstream": {"allowed_methods": ["GET"], "allowed_paths": ["/api/allowed"]}})
        server, thread, app = self._start_proxy(cfg=cfg)
        try:
            base = "http://127.0.0.1:{0}".format(server.server_port)
            self.assertEqual(request(base + "/proxy/api/allowed", method="POST", body=b"x")[0], 403)
            self.assertEqual(request(base + "/proxy/api/other")[0], 403)
            self.assertEqual(request(base + "/proxy/oauth/token")[0], 403)
        finally:
            self._stop(server, thread)

    def test_oversized_request_and_response(self):
        cfg = make_config({"runtime": {"max_request_bytes": 3}})
        server, thread, app = self._start_proxy(cfg=cfg)
        try:
            status = request("http://127.0.0.1:{0}/proxy/api/data".format(server.server_port), method="POST", body=b"1234")[0]
            self.assertEqual(status, 413)
        finally:
            self._stop(server, thread)

        api = FakeAPIClient([HTTPResponse(200, b"012345", {"Content-Type": "text/plain"})])
        cfg2 = make_config({"runtime": {"max_response_bytes": 2048}})
        server2, thread2, app2 = self._start_proxy(cfg=cfg2, api_client=api)
        try:
            status, headers, body = request("http://127.0.0.1:{0}/proxy/api/data".format(server2.server_port))
            self.assertEqual(status, 200)
            self.assertEqual(body, b"012345")
        finally:
            self._stop(server2, thread2)

    def test_malformed_unsafe_paths_and_arbitrary_urls(self):
        server, thread, app = self._start_proxy()
        try:
            base = "http://127.0.0.1:{0}".format(server.server_port)
            self.assertEqual(request(base + "/proxy/api/%2e%2e/secret")[0], 403)
            self.assertEqual(request(base + "/proxy/api/./data")[0], 403)
            raw = self._raw_http(server.server_port, "GET http://evil.example/api/data HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
            self.assertIn("403", raw.split("\r\n", 1)[0])
        finally:
            self._stop(server, thread)

    def test_transfer_encoding_and_content_length_rejections(self):
        server, thread, app = self._start_proxy()
        try:
            port = server.server_port
            self.assertIn("403", self._raw_http(port, "POST /proxy/api/data HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n").split("\r\n", 1)[0])
            self.assertIn("403", self._raw_http(port, "POST /proxy/api/data HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\nContent-Length: 0\r\n\r\n").split("\r\n", 1)[0])
            self.assertIn("403", self._raw_http(port, "POST /proxy/api/data HTTP/1.1\r\nHost: x\r\nContent-Length: abc\r\n\r\n").split("\r\n", 1)[0])
            self.assertIn("403", self._raw_http(port, "POST /proxy/api/data HTTP/1.1\r\nHost: x\r\nContent-Length: 1\r\nContent-Length: 2\r\n\r\nxx").split("\r\n", 1)[0])
        finally:
            self._stop(server, thread)

    def test_head_response_suppresses_body(self):
        api = FakeAPIClient([HTTPResponse(200, b"SHOULD_NOT_SEND", {"Content-Type": "text/plain"})])
        server, thread, app = self._start_proxy(api_client=api)
        try:
            status, headers, body = request("http://127.0.0.1:{0}/proxy/api/data".format(server.server_port), method="HEAD")
            self.assertEqual(status, 200)
            self.assertEqual(body, b"")
            self.assertEqual(headers.get("Content-Length"), "0")
        finally:
            self._stop(server, thread)

    def _raw_http(self, port, payload):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        try:
            sock.connect(("127.0.0.1", port))
            sock.sendall(payload.encode("iso-8859-1"))
            chunks = []
            while True:
                try:
                    data = sock.recv(4096)
                except socket.timeout:
                    break
                if not data:
                    break
                chunks.append(data)
            return b"".join(chunks).decode("iso-8859-1", "replace")
        finally:
            sock.close()


if __name__ == "__main__":
    unittest.main()
