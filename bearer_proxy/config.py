"""Configuration loading and validation."""

import json
import os
import re
import urllib.parse
from pathlib import Path

from .errors import ConfigError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = PROJECT_ROOT / "config" / "proxy.env"
DEFAULT_CONFIG_FILE = PROJECT_ROOT / "config" / "proxy.json"

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_METHODS = set(["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"])
_BODY_TYPES = set(["none", "json", "form", "raw"])
_TOKEN_SOURCES = set(["json", "header", "text"])


class TLSConfig(object):
    def __init__(self, verify=True, ca_bundle=None):
        self.verify = verify
        self.ca_bundle = ca_bundle


class AuthRequestConfig(object):
    def __init__(self, method, path, headers, body_type, body):
        self.method = method
        self.path = path
        self.headers = headers
        self.body_type = body_type
        self.body = body


class TokenConfig(object):
    def __init__(
        self,
        source,
        json_pointer=None,
        response_header_name=None,
        expires_in_json_pointer=None,
        header_name="Authorization",
        scheme="Bearer",
    ):
        self.source = source
        self.json_pointer = json_pointer
        self.response_header_name = response_header_name
        self.expires_in_json_pointer = expires_in_json_pointer
        self.header_name = header_name
        self.scheme = scheme

    def authorization_value(self, token):
        if self.scheme:
            return self.scheme + " " + token
        return token


class ValidationConfig(object):
    def __init__(self, enabled, method, path, headers, body_type, body, expected_statuses):
        self.enabled = enabled
        self.method = method
        self.path = path
        self.headers = headers
        self.body_type = body_type
        self.body = body
        self.expected_statuses = expected_statuses


class AuthConfig(object):
    def __init__(self, base_url, tls, request, token, validation):
        self.base_url = base_url
        self.tls = tls
        self.request = request
        self.token = token
        self.validation = validation


class UpstreamConfig(object):
    def __init__(
        self,
        base_url,
        tls,
        route_prefix,
        allowed_methods,
        allowed_paths,
        request_headers,
        response_headers,
    ):
        self.base_url = base_url
        self.tls = tls
        self.route_prefix = route_prefix
        self.allowed_methods = allowed_methods
        self.allowed_paths = allowed_paths
        self.request_headers = request_headers
        self.response_headers = response_headers


class ServerConfig(object):
    def __init__(
        self,
        bind_host,
        bind_port,
        proxy_api_key,
        proxy_key_header,
        allow_unauthenticated_nonloopback,
    ):
        self.bind_host = bind_host
        self.bind_port = bind_port
        self.proxy_api_key = proxy_api_key
        self.proxy_key_header = proxy_key_header
        self.allow_unauthenticated_nonloopback = allow_unauthenticated_nonloopback


class RuntimeConfig(object):
    def __init__(
        self,
        http_timeout_seconds,
        max_request_bytes,
        max_response_bytes,
        refresh_interval_seconds,
        fallback_refresh_interval_seconds,
        refresh_margin_seconds,
        min_refresh_interval_seconds,
        refresh_retry_seconds,
        stale_token_warning_seconds,
        log_level,
    ):
        self.http_timeout_seconds = http_timeout_seconds
        self.max_request_bytes = max_request_bytes
        self.max_response_bytes = max_response_bytes
        self.refresh_interval_seconds = refresh_interval_seconds
        self.fallback_refresh_interval_seconds = fallback_refresh_interval_seconds
        self.refresh_margin_seconds = refresh_margin_seconds
        self.min_refresh_interval_seconds = min_refresh_interval_seconds
        self.refresh_retry_seconds = refresh_retry_seconds
        self.stale_token_warning_seconds = stale_token_warning_seconds
        self.log_level = log_level


class ProxyConfig(object):
    def __init__(self, schema_version, auth, upstream, server, runtime):
        self.schema_version = schema_version
        self.auth = auth
        self.upstream = upstream
        self.server = server
        self.runtime = runtime


def resolve_project_path(value, project_root=None):
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return ((project_root or PROJECT_ROOT) / path).resolve()


def load_env_file(path):
    """Load a simple KEY=VALUE file; file values intentionally override env."""
    path = Path(path)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ConfigError("Cannot read configuration file {0}: {1}".format(path, exc))

    for lineno, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ConfigError(
                "Invalid configuration line {0} in {1}: expected KEY=VALUE".format(
                    lineno, path
                )
            )
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or not all(ch.isalnum() or ch == "_" for ch in key) or key[0].isdigit():
            raise ConfigError("Invalid configuration key on line {0} in {1}".format(lineno, path))
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        os.environ[key] = value


def looks_like_placeholder(value):
    upper = value.upper()
    return (
        "CHANGE_ME" in upper
        or "<" in value
        or ">" in value
        or upper.startswith("YOUR_")
        or upper.startswith("REPLACE_")
    )


def required_env(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError("Required environment variable is missing: {0}".format(name))
    if looks_like_placeholder(value):
        raise ConfigError("Required environment variable still contains a placeholder: {0}".format(name))
    return value


def env_bool(name, default):
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return coerce_bool(raw, default, name)


def env_float(name, default):
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return coerce_float(raw, name)


def env_int(name, default):
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return coerce_int(raw, name)


def coerce_bool(value, default, field):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("1", "true", "yes", "on"):
            return True
        if text in ("0", "false", "no", "off"):
            return False
    raise ConfigError("{0} must be true/false".format(field))


def coerce_float(value, field):
    if isinstance(value, bool):
        raise ConfigError("{0} must be numeric".format(field))
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ConfigError("{0} must be numeric".format(field))
    return result


def coerce_int(value, field):
    if isinstance(value, bool):
        raise ConfigError("{0} must be an integer".format(field))
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise ConfigError("{0} must be an integer".format(field))
    return result


def normalize_path(value, field="path"):
    if not isinstance(value, str):
        raise ConfigError("{0} must be a string".format(field))
    value = value.strip()
    if not value:
        raise ConfigError("{0} cannot be empty".format(field))
    raw_parsed = urllib.parse.urlsplit(value)
    if raw_parsed.scheme or raw_parsed.netloc or raw_parsed.query or raw_parsed.fragment:
        raise ConfigError("{0} must be a path, not a URL".format(field))
    if not value.startswith("/"):
        value = "/" + value
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise ConfigError("{0} must be a path, not a URL".format(field))
    return parsed.path


def validate_base_url(value, field):
    if not isinstance(value, str):
        raise ConfigError("{0} must be a string".format(field))
    value = value.strip().rstrip("/")
    if not value:
        raise ConfigError("{0} is required".format(field))
    if looks_like_placeholder(value):
        raise ConfigError("{0} still contains a placeholder".format(field))
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ConfigError("{0} must be a valid http:// or https:// URL".format(field))
    if parsed.query or parsed.fragment:
        raise ConfigError("{0} must not contain a query string or fragment".format(field))
    if parsed.path not in ("", "/"):
        raise ConfigError("{0} must contain only scheme and host[:port]".format(field))
    return value


def _require_mapping(value, field):
    if not isinstance(value, dict):
        raise ConfigError("{0} must be a JSON object".format(field))
    return value


def _dict_of_strings(value, field):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError("{0} must be a JSON object".format(field))
    result = {}
    for key, val in value.items():
        if not isinstance(key, str) or not isinstance(val, str):
            raise ConfigError("{0} must contain only string keys and values".format(field))
        result[key] = val
    return result


def _string_list(value, default, field):
    if value is None:
        return list(default)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError("{0} must be a list of strings".format(field))
    return list(value)


def _status_list(value, default, field):
    if value is None:
        return list(default)
    if not isinstance(value, list):
        raise ConfigError("{0} must be a list of HTTP status integers".format(field))
    result = []
    for item in value:
        status = coerce_int(item, field)
        if status < 100 or status > 599:
            raise ConfigError("{0} contains an invalid HTTP status".format(field))
        result.append(status)
    return result


def _substitute_string(value, env, field):
    current = value
    for _unused in range(20):
        missing = []

        def replace(match):
            name = match.group(1)
            if name not in env:
                missing.append(name)
                return ""
            return env[name]

        replaced = _ENV_PATTERN.sub(replace, current)
        if missing:
            raise ConfigError("Missing environment substitution for {0} at {1}".format(missing[0], field))
        if replaced == current:
            return replaced
        current = replaced
    raise ConfigError("Recursive environment substitution did not converge at {0}".format(field))


def substitute_env(value, env=None, field="$"):
    env = env or os.environ
    if isinstance(value, str):
        return _substitute_string(value, env, field)
    if isinstance(value, list):
        return [substitute_env(item, env, "{0}[{1}]".format(field, index)) for index, item in enumerate(value)]
    if isinstance(value, dict):
        return {
            key: substitute_env(val, env, "{0}.{1}".format(field, key))
            for key, val in value.items()
        }
    return value


def load_json_config(path):
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError("Cannot read JSON configuration file {0}: {1}".format(path, exc))
    try:
        parsed = json.loads(text)
    except ValueError as exc:
        raise ConfigError("Invalid JSON configuration file {0}: {1}".format(path, exc))
    return substitute_env(parsed)


def _field(mapping, key, default=None):
    return mapping[key] if key in mapping else default


def _tls_config(raw, defaults, field, project_root):
    if raw is None:
        raw = {}
    verify = coerce_bool(_field(raw, "tls_verify", defaults.verify), defaults.verify, field + ".tls_verify")
    raw_ca = _field(raw, "ca_bundle", defaults.ca_bundle)
    if raw_ca is None or (isinstance(raw_ca, str) and raw_ca.strip() == ""):
        ca_bundle = None
    elif isinstance(raw_ca, str):
        ca_bundle = str(resolve_project_path(raw_ca.strip(), project_root))
    else:
        raise ConfigError("{0}.ca_bundle must be a string".format(field))
    return TLSConfig(verify=verify, ca_bundle=ca_bundle)


def _request_config(raw, default_method, default_path, field):
    raw = _require_mapping(raw, field)
    method = str(_field(raw, "method", default_method)).upper()
    if method not in _METHODS:
        raise ConfigError("{0}.method is not allowed".format(field))
    path = normalize_path(_field(raw, "path", default_path), field + ".path")
    headers = _dict_of_strings(_field(raw, "headers", {}), field + ".headers")
    body_type = str(_field(raw, "body_type", "none")).lower()
    if body_type not in _BODY_TYPES:
        raise ConfigError("{0}.body_type is not supported".format(field))
    body = _field(raw, "body", None)
    if body_type == "none" and body not in (None, "", {}, []):
        raise ConfigError("{0}.body must be empty when body_type is none".format(field))
    if body_type == "raw" and body is not None and not isinstance(body, str):
        raise ConfigError("{0}.body must be a string when body_type is raw".format(field))
    if body_type == "form" and body is not None and not isinstance(body, dict):
        raise ConfigError("{0}.body must be an object when body_type is form".format(field))
    return AuthRequestConfig(method, path, headers, body_type, body)


def _token_config(raw):
    raw = _require_mapping(raw, "auth.token")
    source = str(_field(raw, "source", "json")).lower()
    if source not in _TOKEN_SOURCES:
        raise ConfigError("auth.token.source is not supported")
    json_pointer = _field(raw, "json_pointer", None)
    expires_pointer = _field(raw, "expires_in_json_pointer", None)
    response_header_name = _field(raw, "response_header_name", None)
    header_name = _field(raw, "header_name", "Authorization")
    scheme = _field(raw, "scheme", "Bearer")
    if not isinstance(header_name, str) or not header_name.strip():
        raise ConfigError("auth.token.header_name must be a non-empty string")
    if scheme is None:
        scheme = ""
    if not isinstance(scheme, str):
        raise ConfigError("auth.token.scheme must be a string")
    if source == "json":
        if not isinstance(json_pointer, str) or (json_pointer and not json_pointer.startswith("/")):
            raise ConfigError("auth.token.json_pointer must be a JSON Pointer")
    if source == "header":
        if response_header_name is None:
            response_header_name = header_name
        if not isinstance(response_header_name, str) or not response_header_name.strip():
            raise ConfigError("auth.token.response_header_name must be a non-empty string")
    if expires_pointer is not None:
        if not isinstance(expires_pointer, str) or (expires_pointer and not expires_pointer.startswith("/")):
            raise ConfigError("auth.token.expires_in_json_pointer must be a JSON Pointer")
    return TokenConfig(
        source=source,
        json_pointer=json_pointer,
        response_header_name=response_header_name,
        expires_in_json_pointer=expires_pointer,
        header_name=header_name.strip(),
        scheme=scheme.strip(),
    )


def _validation_config(raw):
    if raw is None:
        raw = {}
    raw = _require_mapping(raw, "auth.validation")
    enabled = coerce_bool(_field(raw, "enabled", False), False, "auth.validation.enabled")
    method = str(_field(raw, "method", "GET")).upper()
    if method not in _METHODS:
        raise ConfigError("auth.validation.method is not allowed")
    path = normalize_path(_field(raw, "path", "/"), "auth.validation.path")
    headers = _dict_of_strings(_field(raw, "headers", {}), "auth.validation.headers")
    body_type = str(_field(raw, "body_type", "none")).lower()
    if body_type not in _BODY_TYPES:
        raise ConfigError("auth.validation.body_type is not supported")
    body = _field(raw, "body", None)
    expected = _status_list(_field(raw, "expected_statuses", None), [200], "auth.validation.expected_statuses")
    return ValidationConfig(enabled, method, path, headers, body_type, body, expected)


def _runtime_config(raw):
    raw = raw or {}
    retry_seconds = coerce_float(_field(raw, "refresh_retry_seconds", env_float("REFRESH_RETRY_SECONDS", 300.0)), "runtime.refresh_retry_seconds")
    if retry_seconds <= 0:
        raise ConfigError("runtime.refresh_retry_seconds must be greater than 0")
    refresh_interval = _field(raw, "refresh_interval_seconds", None)
    if refresh_interval is None:
        refresh_interval = env_float("TOKEN_REFRESH_SECONDS", env_float("TOKEN_REFRESH_HOURS", 10.0) * 3600.0)
    refresh_interval = coerce_float(refresh_interval, "runtime.refresh_interval_seconds")
    if refresh_interval <= 0:
        raise ConfigError("runtime.refresh_interval_seconds must be greater than 0")
    fallback = coerce_float(
        _field(raw, "fallback_refresh_interval_seconds", refresh_interval),
        "runtime.fallback_refresh_interval_seconds",
    )
    margin = coerce_float(_field(raw, "refresh_margin_seconds", env_float("REFRESH_MARGIN_SECONDS", 300.0)), "runtime.refresh_margin_seconds")
    minimum = coerce_float(_field(raw, "min_refresh_interval_seconds", 1.0), "runtime.min_refresh_interval_seconds")
    timeout = coerce_float(_field(raw, "http_timeout_seconds", env_float("HTTP_TIMEOUT_SECONDS", 30.0)), "runtime.http_timeout_seconds")
    max_request = coerce_int(_field(raw, "max_request_bytes", env_int("MAX_REQUEST_BYTES", 1024 * 1024)), "runtime.max_request_bytes")
    max_response = coerce_int(_field(raw, "max_response_bytes", env_int("MAX_RESPONSE_BYTES", 10 * 1024 * 1024)), "runtime.max_response_bytes")
    stale = coerce_float(
        _field(raw, "stale_token_warning_seconds", env_float("STALE_TOKEN_WARNING_SECONDS", max(3.0 * retry_seconds, 900.0))),
        "runtime.stale_token_warning_seconds",
    )
    if timeout <= 0 or max_request < 0 or max_response < 1024 or fallback <= 0 or margin < 0 or minimum <= 0 or stale <= 0:
        raise ConfigError("runtime size, timeout, and refresh values must be positive and safe")
    return RuntimeConfig(
        http_timeout_seconds=timeout,
        max_request_bytes=max_request,
        max_response_bytes=max_response,
        refresh_interval_seconds=refresh_interval,
        fallback_refresh_interval_seconds=fallback,
        refresh_margin_seconds=margin,
        min_refresh_interval_seconds=minimum,
        refresh_retry_seconds=retry_seconds,
        stale_token_warning_seconds=stale,
        log_level=str(_field(raw, "log_level", os.getenv("LOG_LEVEL", "INFO"))).strip().upper() or "INFO",
    )


def parse_config(raw, project_root=None):
    project_root = project_root or PROJECT_ROOT
    root = _require_mapping(raw, "configuration")
    schema_version = root.get("schema_version")
    if schema_version != 1:
        raise ConfigError("schema_version must be 1")

    upstream_raw = _require_mapping(root.get("upstream"), "upstream")
    auth_raw = _require_mapping(root.get("auth"), "auth")

    upstream_base = validate_base_url(
        _field(upstream_raw, "base_url", os.getenv("UPSTREAM_BASE_URL", "")),
        "upstream.base_url",
    )
    upstream_tls = _tls_config(upstream_raw, TLSConfig(True, None), "upstream", project_root)
    route_prefix = normalize_path(_field(upstream_raw, "route_prefix", "/proxy"), "upstream.route_prefix")
    allowed_methods = [method.upper() for method in _string_list(_field(upstream_raw, "allowed_methods", None), ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"], "upstream.allowed_methods")]
    for method in allowed_methods:
        if method not in _METHODS:
            raise ConfigError("upstream.allowed_methods contains an unsupported method")
    allowed_paths = [
        normalize_path(item[:-1] if item.endswith("*") else item, "upstream.allowed_paths") + ("*" if item.endswith("*") else "")
        for item in _string_list(_field(upstream_raw, "allowed_paths", None), ["/"], "upstream.allowed_paths")
    ]
    request_headers = _string_list(
        _field(upstream_raw, "request_headers", _field(upstream_raw, "request_header_allowlist", None)),
        ["Accept", "Content-Type", "User-Agent", "X-Request-ID", "If-None-Match", "If-Modified-Since"],
        "upstream.request_headers",
    )
    response_headers = _string_list(
        _field(upstream_raw, "response_headers", _field(upstream_raw, "response_header_allowlist", None)),
        ["Content-Type", "Content-Disposition", "ETag", "Last-Modified", "Cache-Control"],
        "upstream.response_headers",
    )
    upstream = UpstreamConfig(
        upstream_base,
        upstream_tls,
        route_prefix,
        allowed_methods,
        allowed_paths,
        request_headers,
        response_headers,
    )

    auth_base = validate_base_url(_field(auth_raw, "base_url", upstream_base), "auth.base_url")
    auth_tls = _tls_config(auth_raw, upstream_tls, "auth", project_root)
    auth_request = _request_config(auth_raw.get("request"), "POST", "/", "auth.request")
    token = _token_config(auth_raw.get("token"))
    validation = _validation_config(auth_raw.get("validation"))
    auth = AuthConfig(auth_base, auth_tls, auth_request, token, validation)

    runtime = _runtime_config(root.get("runtime", {}))

    server_raw = root.get("server", {})
    proxy_key = _field(server_raw, "proxy_api_key", os.getenv("PROXY_API_KEY", "")).strip()
    if looks_like_placeholder(proxy_key):
        raise ConfigError("server.proxy_api_key still contains a placeholder")
    server = ServerConfig(
        bind_host=str(_field(server_raw, "bind_host", os.getenv("PROXY_BIND_HOST", "127.0.0.1"))).strip() or "127.0.0.1",
        bind_port=coerce_int(_field(server_raw, "bind_port", env_int("PROXY_PORT", 8787)), "server.bind_port"),
        proxy_api_key=proxy_key or None,
        proxy_key_header=str(_field(server_raw, "proxy_key_header", "X-Bearer-Proxy-Key")).strip() or "X-Bearer-Proxy-Key",
        allow_unauthenticated_nonloopback=coerce_bool(
            _field(server_raw, "allow_unauthenticated_nonloopback", env_bool("ALLOW_UNAUTHENTICATED_NONLOOPBACK", False)),
            False,
            "server.allow_unauthenticated_nonloopback",
        ),
    )
    if server.bind_port < 1 or server.bind_port > 65535:
        raise ConfigError("server.bind_port must be between 1 and 65535")
    return ProxyConfig(schema_version, auth, upstream, server, runtime)


def load_config(env_file=None, config_file=None, project_root=None):
    if env_file is not None:
        load_env_file(env_file)
    raw = load_json_config(config_file or DEFAULT_CONFIG_FILE)
    return parse_config(raw, project_root=project_root)
