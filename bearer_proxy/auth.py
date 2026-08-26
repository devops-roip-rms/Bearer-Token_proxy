"""Configurable bearer-token authentication."""

import json
import urllib.parse

from .errors import AuthenticationError, ConfigError


class JsonPointerError(AuthenticationError):
    pass


class AuthResult(object):
    def __init__(self, token, expires_in_seconds=None):
        self.token = token
        self.expires_in_seconds = expires_in_seconds


def json_pointer_get(document, pointer):
    if pointer == "":
        return document
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise JsonPointerError("Invalid JSON Pointer")
    current = document
    for raw_part in pointer.split("/")[1:]:
        part = _decode_pointer_part(raw_part)
        if isinstance(current, dict):
            if part not in current:
                raise JsonPointerError("JSON Pointer did not match")
            current = current[part]
        elif isinstance(current, list):
            if part == "-" or not part.isdigit():
                raise JsonPointerError("JSON Pointer did not match")
            index = int(part)
            if index >= len(current):
                raise JsonPointerError("JSON Pointer did not match")
            current = current[index]
        else:
            raise JsonPointerError("JSON Pointer did not match")
    return current


def _decode_pointer_part(part):
    index = 0
    decoded = []
    while index < len(part):
        char = part[index]
        if char != "~":
            decoded.append(char)
            index += 1
            continue
        if index + 1 >= len(part) or part[index + 1] not in ("0", "1"):
            raise JsonPointerError("Invalid JSON Pointer escape")
        decoded.append("~" if part[index + 1] == "0" else "/")
        index += 2
    return "".join(decoded)


def build_request_body(body_type, body, headers):
    body_type = body_type.lower()
    if body_type == "none":
        return None
    if body_type == "json":
        if "content-type" not in _case_insensitive_keys(headers):
            headers["Content-Type"] = "application/json"
        return json.dumps(body, separators=(",", ":")).encode("utf-8")
    if body_type == "form":
        if "content-type" not in _case_insensitive_keys(headers):
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        pairs = []
        if body:
            for key, value in body.items():
                pairs.append((key, value))
        return urllib.parse.urlencode(pairs).encode("utf-8")
    if body_type == "raw":
        return (body or "").encode("utf-8")
    raise ConfigError("Unsupported request body type")


def _case_insensitive_keys(mapping):
    return set(key.lower() for key in mapping.keys())


class AuthProvider(object):
    def __init__(self, cfg, auth_http_client, validation_http_client):
        self.cfg = cfg
        self.auth_http_client = auth_http_client
        self.validation_http_client = validation_http_client

    def authenticate(self):
        request_cfg = self.cfg.auth.request
        headers = dict(request_cfg.headers)
        body = build_request_body(request_cfg.body_type, request_cfg.body, headers)
        response = self.auth_http_client.request(
            self.cfg.auth.base_url,
            request_cfg.method,
            request_cfg.path,
            headers=headers,
            body=body,
        )
        if response.status < 200 or response.status >= 300:
            raise AuthenticationError("Authentication endpoint returned HTTP {0}".format(response.status))
        token, expires = self._extract_token(response)
        return AuthResult(token, expires)

    def validate_token(self, token):
        validation = self.cfg.auth.validation
        if not validation.enabled:
            return True
        headers = dict(validation.headers)
        headers[self.cfg.auth.token.header_name] = self.cfg.auth.token.authorization_value(token)
        body = build_request_body(validation.body_type, validation.body, headers)
        response = self.validation_http_client.request(
            self.cfg.upstream.base_url,
            validation.method,
            validation.path,
            headers=headers,
            body=body,
        )
        if response.status not in validation.expected_statuses:
            raise AuthenticationError("Candidate token validation failed")
        return True

    def _extract_token(self, response):
        token_cfg = self.cfg.auth.token
        expires = None
        if token_cfg.source == "json":
            try:
                payload = json.loads(response.body.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                raise AuthenticationError("Authentication response was not valid JSON")
            token = json_pointer_get(payload, token_cfg.json_pointer)
            if token_cfg.expires_in_json_pointer:
                expires_value = json_pointer_get(payload, token_cfg.expires_in_json_pointer)
                expires = _coerce_expires_in(expires_value)
        elif token_cfg.source == "header":
            token = response.header(token_cfg.response_header_name)
        elif token_cfg.source == "text":
            try:
                token = response.body.decode("utf-8")
            except UnicodeDecodeError:
                raise AuthenticationError("Authentication response text was not UTF-8")
        else:
            raise AuthenticationError("Unsupported token source")
        if not isinstance(token, str) or not token.strip():
            raise AuthenticationError("Authentication response did not contain a usable token")
        return token.strip(), expires


def _coerce_expires_in(value):
    if isinstance(value, bool):
        raise AuthenticationError("Token expiry value is invalid")
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise AuthenticationError("Token expiry value is invalid")
    if result <= 0:
        raise AuthenticationError("Token expiry value is invalid")
    return result
