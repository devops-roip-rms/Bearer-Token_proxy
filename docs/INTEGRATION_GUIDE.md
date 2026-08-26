# Customer Integration Guide

Use this guide to adapt Bearer Token API Proxy to an arbitrary compatible HTTP API.

## 1. Identify Authentication Endpoint

Example:

```text
POST https://auth.example.internal/login
```

Set:

```ini
AUTH_BASE_URL=https://auth.example.internal
```

Configure the path in `auth.request.path`.

## 2. Identify Authentication Body Format

Supported body types:

```text
none
json
form
raw
```

For JSON credentials:

```json
"body_type": "json",
"body": {
  "username": "${AUTH_USERNAME}",
  "password": "${AUTH_PASSWORD}"
}
```

The variable names are customer-defined; use whatever names match your environment.

## 3. Identify Required Authentication Headers

Examples:

```text
Accept
Content-Type
X-Custom-Header
```

Configure them in `auth.request.headers`.

## 4. Identify Where The Token Is Returned

Supported token sources:

```text
JSON response
response header
plain response text
```

JSON example:

```json
"token": {
  "source": "json",
  "json_pointer": "/access_token",
  "header_name": "Authorization",
  "scheme": "Bearer"
}
```

Header example:

```json
"token": {
  "source": "header",
  "response_header_name": "X-Access-Token",
  "header_name": "Authorization",
  "scheme": "Bearer"
}
```

## 5. Configure JSON Pointer

JSON Pointer follows RFC 6901.

Examples:

```text
/access_token
/response/token
/a~1b       key named a/b
/m~0n       key named m~n
```

## 6. Determine Token Expiry

If the authentication response includes an expiry:

```json
"expires_in_json_pointer": "/expires_in"
```

If no expiry is returned, configure a fallback refresh interval:

```json
"fallback_refresh_interval_seconds": "${TOKEN_REFRESH_SECONDS}"
```

## 7. Configure Upstream API URL

Example:

```ini
UPSTREAM_BASE_URL=https://api.example.internal
```

The client cannot override this host at request time.

## 8. Configure Token Injection

Typical protected API header:

```http
Authorization: Bearer <token>
```

Both the header name and scheme are configurable.

## 9. Configure Allowed Methods

Supported methods:

```text
GET
POST
PUT
PATCH
DELETE
HEAD
```

Only methods listed in `upstream.allowed_methods` are accepted.

## 10. Configure Allowed Paths

Allowed paths are a security boundary. Use exact paths or prefix patterns:

```json
"allowed_paths": ["/api/status", "/api/v1/*"]
```

The authentication path is never exposed through the proxy route.

## 11. Configure TLS

Authentication and upstream API endpoints can use separate trust chains:

```ini
AUTH_CA_BUNDLE=certs/auth-ca.pem
UPSTREAM_CA_BUNDLE=certs/upstream-ca.pem
```

TLS verification is enabled by default.

## 12. Validate

```bash
python -B app.py --env-file config/proxy.env --config-file config/proxy.json --check-config
python -B app.py --env-file config/proxy.env --config-file config/proxy.json --test-auth
```

## 13. Test A Proxied Request

Example:

```text
GET http://127.0.0.1:8787/proxy/api/status
```

If local proxy authentication is configured, send:

```http
X-Bearer-Proxy-Key: <configured value>
```

