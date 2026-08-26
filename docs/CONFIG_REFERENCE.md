# Configuration Reference

Configuration uses JSON with environment substitution. `config/proxy.env` is loaded first, then `${NAME}` placeholders in `config/proxy.json` are resolved recursively from the effective environment.

Missing substitutions fail validation without printing secret values.

## Top Level

- `schema_version`: required, currently `1`.
- `upstream`: protected API configuration.
- `auth`: authentication endpoint and token extraction configuration.
- `server`: local proxy listener and caller authentication.
- `runtime`: timeouts, size limits, refresh behavior, and logging.

## upstream

- `base_url`: required `http://` or `https://` origin for protected API calls. Must not include path, query, or fragment.
- `route_prefix`: local route prefix, default `/proxy`.
- `allowed_methods`: list of allowed client methods. Supported: `GET`, `POST`, `PUT`, `PATCH`, `DELETE`, `HEAD`.
- `allowed_paths`: exact paths or prefix patterns ending in `/*`.
- `tls_verify`: defaults to `true`.
- `ca_bundle`: optional CA bundle path. Empty means platform trust.
- `request_headers`: request header allowlist. `Authorization`, `Host`, `Content-Length`, `Transfer-Encoding`, and hop-by-hop headers are never forwarded.
- `response_headers`: response header allowlist. Hop-by-hop headers are never returned.

## auth

- `base_url`: authentication origin. If omitted, inherits `upstream.base_url`.
- `tls_verify`: if omitted, inherits `upstream.tls_verify`.
- `ca_bundle`: if omitted, inherits `upstream.ca_bundle`; if set to an empty string, platform trust is used.

Authentication and upstream TLS settings are independent when auth-specific values are explicitly configured. This supports separate trust chains for `auth.example.internal` and `api.example.internal`.

## auth.request

- `method`: HTTP method for authentication.
- `path`: authentication path.
- `headers`: string header map.
- `body_type`: `none`, `json`, `form`, or `raw`.
- `body`: request body structure. `form` encodes as `application/x-www-form-urlencoded` unless `Content-Type` is explicitly set.

## auth.token

- `source`: `json`, `header`, or `text`.
- `json_pointer`: required when `source` is `json`.
- `response_header_name`: response header used when `source` is `header`.
- `expires_in_json_pointer`: optional JSON Pointer for token lifetime seconds.
- `header_name`: upstream injection header, default `Authorization`.
- `scheme`: upstream injection scheme, default `Bearer`.

JSON Pointer follows RFC 6901. Use `~1` for `/` inside a key and `~0` for `~`.

## auth.validation

- `enabled`: validates a candidate token before installation.
- `method`: validation method.
- `path`: validation path on the upstream API.
- `headers`: additional validation headers.
- `body_type`: validation body type.
- `body`: validation body.
- `expected_statuses`: statuses that prove the candidate is usable.

If validation fails, the old token remains active.

## server

- `bind_host`: default `127.0.0.1`.
- `bind_port`: default `8787`.
- `proxy_api_key`: optional local shared key. Required for non-loopback binds unless explicitly overridden.
- `proxy_key_header`: default `X-Bearer-Proxy-Key`.
- `allow_unauthenticated_nonloopback`: dangerous override for explicitly accepted insecure deployments.

## runtime

- `http_timeout_seconds`: outbound HTTP timeout.
- `max_request_bytes`: maximum inbound request body.
- `max_response_bytes`: maximum upstream response body.
- `refresh_interval_seconds`: configured refresh interval.
- `fallback_refresh_interval_seconds`: refresh interval when auth response has no `expires_in`.
- `refresh_margin_seconds`: safety margin subtracted from `expires_in`.
- `min_refresh_interval_seconds`: minimum scheduled refresh delay.
- `refresh_retry_seconds`: backoff after failed refresh.
- `stale_token_warning_seconds`: readiness staleness threshold.
- `log_level`: Python logging level.

