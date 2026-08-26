"""Local proxy authorization and request policy."""

import hmac
import ipaddress
import urllib.parse

from .errors import AuthorizationPolicyError, ConfigError


HOP_BY_HOP_HEADERS = set(
    [
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "host",
        "content-length",
    ]
)


def is_loopback_bind(host):
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def validate_bind_security(cfg):
    if is_loopback_bind(cfg.server.bind_host) or cfg.server.proxy_api_key is not None:
        return
    if not cfg.server.allow_unauthenticated_nonloopback:
        raise ConfigError(
            "PROXY_API_KEY is required when PROXY_BIND_HOST is non-loopback; "
            "set allow_unauthenticated_nonloopback only for an explicitly accepted insecure deployment"
        )


class ProxyAuthenticator(object):
    def __init__(self, proxy_api_key):
        self.proxy_api_key = proxy_api_key

    def authorized(self, supplied):
        if self.proxy_api_key is None:
            return True
        if supplied is None:
            return False
        return hmac.compare_digest(supplied, self.proxy_api_key)


class SecurityPolicy(object):
    def __init__(self, cfg):
        self.cfg = cfg
        self._request_header_allowlist = set(h.lower() for h in cfg.upstream.request_headers)
        self._response_header_allowlist = set(h.lower() for h in cfg.upstream.response_headers)

    def inbound_to_upstream(self, method, raw_target):
        method = method.upper()
        if method not in self.cfg.upstream.allowed_methods:
            raise AuthorizationPolicyError("HTTP method is not allowed")
        parsed = urllib.parse.urlsplit(raw_target)
        if parsed.scheme or parsed.netloc:
            raise AuthorizationPolicyError("Arbitrary upstream URLs are not allowed")
        path = parsed.path or "/"
        if not path.startswith(self.cfg.upstream.route_prefix + "/"):
            raise AuthorizationPolicyError("Path is outside the proxy route")
        upstream_path = path[len(self.cfg.upstream.route_prefix):]
        upstream_path = upstream_path or "/"
        self._reject_unsafe_path(upstream_path)
        if upstream_path == self.cfg.auth.request.path:
            raise AuthorizationPolicyError("Authentication endpoint is not exposed through the proxy")
        if not self._path_allowed(upstream_path):
            raise AuthorizationPolicyError("Upstream path is not allowed")
        return upstream_path, parsed.query

    def _reject_unsafe_path(self, path):
        if "\\" in path or "\x00" in path:
            raise AuthorizationPolicyError("Unsafe path")
        decoded = urllib.parse.unquote(path)
        if "\\" in decoded or "\x00" in decoded:
            raise AuthorizationPolicyError("Unsafe path")
        for part in decoded.split("/"):
            if part in (".", ".."):
                raise AuthorizationPolicyError("Unsafe path")

    def _path_allowed(self, path):
        for allowed in self.cfg.upstream.allowed_paths:
            if allowed == "/":
                return True
            if allowed.endswith("/*"):
                prefix = allowed[:-1]
                if path.startswith(prefix):
                    return True
            elif path == allowed:
                return True
        return False

    def filter_request_headers(self, headers):
        result = {}
        for key in headers.keys():
            lower = key.lower()
            if lower in HOP_BY_HOP_HEADERS or lower == "authorization":
                continue
            if lower in self._request_header_allowlist:
                result[key] = headers.get(key)
        return result

    def filter_response_headers(self, headers):
        result = {}
        for key, value in headers.items():
            lower = key.lower()
            if lower in HOP_BY_HOP_HEADERS:
                continue
            if lower in self._response_header_allowlist:
                result[key] = value
        return result

