import unittest

from bearer_proxy.api_client import UpstreamAPIClient
from bearer_proxy.http_client import HTTPClient, HTTPResponse
from tests.helpers import DummyHTTPClient, FakeTokenManager, make_config, start_callback_server, stop_server


class APIClientTests(unittest.TestCase):
    def test_methods_query_body_and_token_injection(self):
        for method in ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"]:
            http = DummyHTTPClient([HTTPResponse(200, b"ok", {"Content-Type": "text/plain"})])
            client = UpstreamAPIClient(make_config(), http)
            response = client.request_with_recovery(method, "/api/data", "a=1", {"Accept": "text/plain"}, b"BODY", FakeTokenManager("TOKEN"))
            self.assertEqual(response.status, 200)
            self.assertEqual(http.requests[0]["method"], method)
            self.assertEqual(http.requests[0]["path"], "/api/data?a=1")
            self.assertEqual(http.requests[0]["headers"]["Authorization"], "Bearer TOKEN")
            self.assertEqual(http.requests[0]["body"], b"BODY")

    def test_status_and_response_type_pass_through(self):
        for status in [404, 409, 422, 429, 500]:
            body = b"\x00\x01binary" if status == 500 else b'{"same":true}'
            http = DummyHTTPClient([HTTPResponse(status, body, {"Content-Type": "application/octet-stream"})])
            response = UpstreamAPIClient(make_config(), http).request_with_recovery("GET", "/api/data", "", {}, b"", FakeTokenManager("TOKEN"))
            self.assertEqual(response.status, status)
            self.assertEqual(response.body, body)

    def test_401_refresh_replays_once(self):
        http = DummyHTTPClient([HTTPResponse(401, b"no", {}), HTTPResponse(200, b"yes", {})])
        manager = FakeTokenManager("OLD", "NEW")
        response = UpstreamAPIClient(make_config(), http).request_with_recovery("POST", "/api/jobs", "", {}, b"payload", manager)
        self.assertEqual(response.status, 200)
        self.assertEqual(manager.refresh_count, 1)
        self.assertEqual(len(http.requests), 2)
        self.assertEqual(http.requests[1]["headers"]["Authorization"], "Bearer NEW")
        self.assertEqual(http.requests[1]["body"], b"payload")

    def test_second_401_stops(self):
        http = DummyHTTPClient([HTTPResponse(401, b"first", {}), HTTPResponse(401, b"second", {})])
        response = UpstreamAPIClient(make_config(), http).request_with_recovery("GET", "/api/data", "", {}, b"", FakeTokenManager("OLD", "NEW"))
        self.assertEqual(response.status, 401)
        self.assertEqual(len(http.requests), 2)

    def test_non_401_does_not_refresh(self):
        manager = FakeTokenManager("TOKEN", "NEW")
        response = UpstreamAPIClient(make_config(), DummyHTTPClient([HTTPResponse(403, b"", {})])).request_with_recovery("GET", "/api/data", "", {}, b"", manager)
        self.assertEqual(response.status, 403)
        self.assertEqual(manager.refresh_count, 0)

    def test_redirect_not_followed_automatically(self):
        state = {"calls": []}

        def callback(record, state):
            state["calls"].append(record["path"])
            if record["path"] == "/redirect":
                return 302, {"Location": "/target"}, b""
            return 200, {}, b"followed"

        server, thread = start_callback_server(callback, state)
        try:
            http = HTTPClient(2, 1024, None)
            response = http.request("http://127.0.0.1:{0}".format(server.server_port), "GET", "/redirect", {}, None)
            self.assertEqual(response.status, 302)
            self.assertEqual(state["calls"], ["/redirect"])
        finally:
            stop_server(server, thread)


if __name__ == "__main__":
    unittest.main()

