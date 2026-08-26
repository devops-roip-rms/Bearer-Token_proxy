"""Inbound HTTP server for the Bearer Token API Proxy."""

import json
import logging
import signal
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

from .api_client import UpstreamAPIClient
from .auth import AuthProvider
from .errors import AuthorizationPolicyError, ProxyError, RequestTooLargeError, ResponseTooLargeError
from .http_client import HTTPClient, build_ssl_context
from .security import ProxyAuthenticator, SecurityPolicy, validate_bind_security
from .token_manager import TokenManager

LOG = logging.getLogger("bearer-token-api-proxy")


class ProxyApplication(object):
    def __init__(self, cfg, api_client, token_manager):
        self.cfg = cfg
        self.api_client = api_client
        self.token_manager = token_manager
        self.authenticator = ProxyAuthenticator(cfg.server.proxy_api_key)
        self.security = SecurityPolicy(cfg)


class ProxyHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address, app):
        self.app = app
        HTTPServer.__init__(self, server_address, ProxyRequestHandler)


class ProxyRequestHandler(BaseHTTPRequestHandler):
    server_version = "BearerTokenAPIProxy/0.1"

    @property
    def app(self):
        return self.server.app

    def log_message(self, fmt, *args):
        LOG.debug("HTTP %s - %s", self.client_address[0], fmt % args)

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

    def do_OPTIONS(self):
        self._send_json(405, {"error": "method_not_allowed"})

    def _handle(self):
        path = self.path.split("?", 1)[0]
        if self.command == "GET" and path == "/healthz":
            self._send_json(200, {"status": "ok"})
            return
        if self.command == "GET" and path == "/readyz":
            self._handle_readyz()
            return
        if self.command == "GET" and path == "/metrics":
            self._handle_metrics()
            return
        self._handle_proxy()

    def _handle_readyz(self):
        snapshot = self.app.token_manager.snapshot()
        stale = (
            snapshot["refresh_error_age_seconds"] is not None
            and snapshot["refresh_error_age_seconds"] >= self.app.cfg.runtime.stale_token_warning_seconds
        )
        status = 200 if snapshot["token_loaded"] and not stale else 503
        snapshot["status"] = "ready" if status == 200 else "not_ready"
        self._send_json(status, snapshot)

    def _handle_metrics(self):
        snapshot = self.app.token_manager.snapshot()
        self._send_json(
            200,
            {
                "token_loaded": snapshot["token_loaded"],
                "seconds_since_last_success": snapshot["seconds_since_last_success"],
                "consecutive_refresh_failures": snapshot["consecutive_refresh_failures"],
                "last_refresh_error": snapshot["last_refresh_error"],
            },
        )

    def _handle_proxy(self):
        supplied_key = self.headers.get(self.app.cfg.server.proxy_key_header)
        if not self.app.authenticator.authorized(supplied_key):
            self._send_json(401, {"error": "unauthorized"})
            return
        try:
            upstream_path, query = self.app.security.inbound_to_upstream(self.command, self.path)
            body = self._read_request_body()
            request_headers = self.app.security.filter_request_headers(self.headers)
            response = self.app.api_client.request_with_recovery(
                self.command,
                upstream_path,
                query,
                request_headers,
                body,
                self.app.token_manager,
            )
            self._send_upstream(response)
        except AuthorizationPolicyError as exc:
            self._send_json(403, {"error": "forbidden"})
        except RequestTooLargeError:
            self._send_json(413, {"error": "request_too_large"})
        except ResponseTooLargeError:
            self._send_json(502, {"error": "response_too_large"})
        except ProxyError:
            LOG.error("Proxy request failed")
            self._send_json(502, {"error": "upstream_unavailable"})
        except Exception:
            LOG.exception("Unexpected error while serving proxy request")
            self._send_json(500, {"error": "internal_error"})

    def _read_request_body(self):
        transfer_values = self.headers.get_all("Transfer-Encoding") or []
        content_lengths = self.headers.get_all("Content-Length") or []
        if transfer_values and content_lengths:
            raise AuthorizationPolicyError("Ambiguous transfer framing")
        if transfer_values:
            raise AuthorizationPolicyError("Unsupported Transfer-Encoding")
        if not content_lengths:
            return b""
        normalized = [item.strip() for item in content_lengths]
        if len(set(normalized)) != 1:
            raise AuthorizationPolicyError("Conflicting Content-Length")
        try:
            length = int(normalized[0])
        except ValueError:
            raise AuthorizationPolicyError("Malformed Content-Length")
        if length < 0:
            raise AuthorizationPolicyError("Malformed Content-Length")
        if length > self.app.cfg.runtime.max_request_bytes:
            # Drain a bounded amount so small over-limit requests can receive
            # the 413 response cleanly without storing the body.
            self.rfile.read(min(length, self.app.cfg.runtime.max_request_bytes + 1))
            raise RequestTooLargeError("Request body exceeded configured maximum size")
        return self.rfile.read(length)

    def _send_json(self, status, payload):
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body) if self.command != "HEAD" else 0))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_upstream(self, response):
        body = response.body if self.command != "HEAD" else b""
        self.send_response(response.status)
        for key, value in self.app.security.filter_response_headers(response.headers).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)


def build_application(cfg):
    auth_context = build_ssl_context(cfg.auth.tls)
    upstream_context = build_ssl_context(cfg.upstream.tls)
    auth_http = HTTPClient(cfg.runtime.http_timeout_seconds, cfg.runtime.max_response_bytes, auth_context)
    upstream_http = HTTPClient(cfg.runtime.http_timeout_seconds, cfg.runtime.max_response_bytes, upstream_context)
    provider = AuthProvider(cfg, auth_http, upstream_http)
    manager = TokenManager(cfg, provider)
    api_client = UpstreamAPIClient(cfg, upstream_http)
    return ProxyApplication(cfg, api_client, manager)


def check_configuration(cfg):
    validate_bind_security(cfg)
    build_ssl_context(cfg.auth.tls)
    build_ssl_context(cfg.upstream.tls)
    return True


def test_authentication(cfg):
    app = build_application(cfg)
    result = app.token_manager.auth_provider.authenticate()
    app.token_manager.auth_provider.validate_token(result.token)
    return result


def run_server(cfg):
    check_configuration(cfg)
    app = build_application(cfg)
    server = ProxyHTTPServer((cfg.server.bind_host, cfg.server.bind_port), app)
    stopping = threading.Event()

    def request_stop(signum, _frame):
        if stopping.is_set():
            return
        stopping.set()
        LOG.info("Received signal %s; stopping", signum)
        thread = threading.Thread(target=server.shutdown)
        thread.daemon = True
        thread.start()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    app.token_manager.start()
    LOG.info(
        "Bearer Token API Proxy listening on http://%s:%d%s/",
        cfg.server.bind_host,
        cfg.server.bind_port,
        cfg.upstream.route_prefix,
    )
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
        app.token_manager.stop()
    return 0
