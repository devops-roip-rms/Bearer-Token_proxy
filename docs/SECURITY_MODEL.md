# Security Model

Bearer Token API Proxy is designed to hold upstream credentials and bearer tokens away from clients.

## Token Handling

- Tokens are kept in RAM only.
- Tokens are not written to `proxy.env`, `proxy.json`, logs, readiness, metrics, or test artifacts.
- Candidate tokens are validated before installation when validation is enabled.
- A failed candidate never replaces the last good token.

## Request Control

- Clients cannot choose the upstream host.
- The upstream base URL is fixed by configuration.
- The proxy strips client `Authorization`.
- The proxy injects the configured bearer header.
- The authentication endpoint is blocked from `/proxy`.
- Methods and paths are allowlisted.
- Unsafe path traversal, encoded `..`, `.` path segments, backslashes, and arbitrary absolute-form URLs are rejected.

## Header and Framing Safety

- Hop-by-hop headers are removed.
- Request and response headers use allowlists.
- Unsupported `Transfer-Encoding` is rejected.
- Chunked request bodies are rejected because chunked decoding is not implemented.
- Requests with both `Transfer-Encoding` and `Content-Length` are rejected.
- Malformed or conflicting `Content-Length` is rejected.
- Maximum request and response sizes are enforced.
- Downstream `HEAD` responses do not include a body.

## TLS

- TLS verification is enabled by default.
- Empty CA bundle values use the platform trust store.
- Authentication and upstream TLS verification can be configured independently.
- Authentication TLS settings inherit upstream TLS settings only when auth-specific fields are omitted.
- Custom CA bundle paths are not printed with secret values or used as a diagnostic file readout.

## Local Proxy Authentication

- Loopback-only use may omit `PROXY_API_KEY`.
- Non-loopback binds require `PROXY_API_KEY` unless the operator explicitly enables the unsafe override.
- Proxy key comparison uses `hmac.compare_digest`.
- The local caller header is `X-Bearer-Proxy-Key` by default.

## HTTP 401 Recovery

- Upstream HTTP 401 triggers one reauthentication attempt.
- The original request is replayed once with the replacement token.
- A second 401 is returned without infinite retry.
- Concurrent 401s for the same rejected token share the refresh lock and avoid an authentication stampede.

## Redirects

The HTTP transport does not follow redirects automatically. This prevents bearer tokens from being sent to arbitrary redirected destinations.

## Secret Files

`config/proxy.env`, `config/proxy.json`, private CA material, logs, runtime files, and offline archives are excluded from Git and Docker image layers.

