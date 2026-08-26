import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

from bearer_proxy.config import parse_config
from bearer_proxy.http_client import HTTPResponse


class DummyHTTPClient(object):
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.requests = []

    def request(self, base_url, method, path, headers=None, body=None):
        record = {
            "base_url": base_url,
            "method": method,
            "path": path,
            "headers": dict(headers or {}),
            "body": body,
        }
        self.requests.append(record)
        response = self.responses.pop(0)
        if callable(response):
            return response(record)
        return response


class FakeTokenManager(object):
    def __init__(self, token="TOKEN_1", replacement="TOKEN_2"):
        self.token = token
        self.replacement = replacement
        self.refresh_count = 0

    def ensure_token(self):
        return self.token

    def get_token(self):
        return self.token

    def refresh_rejected_token(self, rejected_token):
        self.refresh_count += 1
        if self.token == rejected_token and self.replacement is not None:
            self.token = self.replacement
            return True
        return False

    def snapshot(self):
        return {
            "token_loaded": self.token is not None,
            "last_refresh_utc": "2026-08-26T00:00:00Z" if self.token else None,
            "seconds_until_refresh": 100,
            "last_refresh_error": False,
            "refresh_error_age_seconds": None,
            "seconds_since_last_success": 1,
            "consecutive_refresh_failures": 0,
        }


class FakeAPIClient(object):
    def __init__(self, responses=None):
        self.responses = list(responses or [HTTPResponse(200, b"{}", {"Content-Type": "application/json"})])
        self.requests = []

    def request_with_recovery(self, method, path, query, headers, body, token_manager):
        self.requests.append(
            {
                "method": method,
                "path": path,
                "query": query,
                "headers": dict(headers or {}),
                "body": body,
            }
        )
        return self.responses.pop(0)


def base_config_dict(auth_base="http://auth.example.invalid", upstream_base="http://api.example.invalid"):
    return {
        "schema_version": 1,
        "upstream": {
            "base_url": upstream_base,
            "route_prefix": "/proxy",
            "allowed_methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"],
            "allowed_paths": ["/api/*"],
            "tls_verify": True,
            "ca_bundle": "",
            "request_headers": ["Accept", "Content-Type", "X-Request-ID"],
            "response_headers": ["Content-Type", "ETag", "X-Upstream"],
        },
        "auth": {
            "base_url": auth_base,
            "request": {
                "method": "POST",
                "path": "/oauth/token",
                "headers": {"Accept": "application/json"},
                "body_type": "json",
                "body": {"client_id": "client", "client_secret": "secret"},
            },
            "token": {
                "source": "json",
                "json_pointer": "/access_token",
                "expires_in_json_pointer": "/expires_in",
                "header_name": "Authorization",
                "scheme": "Bearer",
            },
            "validation": {
                "enabled": True,
                "method": "GET",
                "path": "/api/validate",
                "expected_statuses": [200],
            },
        },
        "server": {
            "bind_host": "127.0.0.1",
            "bind_port": 8787,
            "proxy_api_key": "",
            "proxy_key_header": "X-Bearer-Proxy-Key",
            "allow_unauthenticated_nonloopback": False,
        },
        "runtime": {
            "http_timeout_seconds": 2,
            "max_request_bytes": 1024 * 1024,
            "max_response_bytes": 1024 * 1024,
            "refresh_interval_seconds": 36000,
            "fallback_refresh_interval_seconds": 36000,
            "refresh_margin_seconds": 300,
            "min_refresh_interval_seconds": 1,
            "refresh_retry_seconds": 300,
            "stale_token_warning_seconds": 900,
            "log_level": "INFO",
        },
    }


def deep_update(target, changes):
    for key, value in changes.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            deep_update(target[key], value)
        else:
            target[key] = value
    return target


def make_config(changes=None, auth_base="http://auth.example.invalid", upstream_base="http://api.example.invalid"):
    raw = base_config_dict(auth_base=auth_base, upstream_base=upstream_base)
    if changes:
        deep_update(raw, changes)
    return parse_config(raw)


class TestThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class CallbackHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _handle(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length) if length else b""
        record = {
            "method": self.command,
            "path": self.path,
            "headers": dict(self.headers.items()),
            "body": body,
        }
        status, headers, response_body = self.server.callback(record, self.server.state)
        response_body = response_body or b""
        self.send_response(status)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(response_body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(response_body)

    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def do_PUT(self):
        self._handle()

    def do_PATCH(self):
        self._handle()

    def do_DELETE(self):
        self._handle()

    def do_HEAD(self):
        self._handle()


def start_callback_server(callback, state=None):
    server = TestThreadingHTTPServer(("127.0.0.1", 0), CallbackHandler)
    server.callback = callback
    server.state = state if state is not None else {}
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    return server, thread


def stop_server(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def request(url, method="GET", headers=None, body=None, timeout=2):
    data = body
    if isinstance(data, str):
        data = data.encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, dict(response.headers.items()), response.read()
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, dict(exc.headers.items()), exc.read()
        finally:
            exc.close()


def json_response(payload, status=200, headers=None):
    all_headers = {"Content-Type": "application/json"}
    if headers:
        all_headers.update(headers)
    return HTTPResponse(status, json.dumps(payload, separators=(",", ":")).encode("utf-8"), all_headers)
