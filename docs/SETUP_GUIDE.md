# Setup Guide

## Requirements

- Python 3.6 or newer for native deployment.
- Docker Engine and Docker Compose plugin for container deployment.
- Network reachability from the proxy host to the authentication endpoint and upstream API.
- No Python third-party packages are required.

## Native Setup

```bash
sh scripts/setup.sh
cp config/proxy.env.example config/proxy.env
cp config/proxy.json.example config/proxy.json
chmod 600 config/proxy.env config/proxy.json
```

Edit `config/proxy.env` for secret and deployment values. Edit `config/proxy.json` for HTTP request shape, token extraction, route policy, and TLS behavior.

## Validate Configuration

```bash
./scripts/check-config.sh
```

Expected:

```text
configuration_ok=yes
```

## Test Authentication

```bash
./scripts/test-auth.sh
```

Expected:

```text
authentication_test=ok
validation=enabled
```

The command does not print the token or credential values.

## Start, Stop, Status

```bash
./scripts/start.sh
./scripts/status.sh
./scripts/stop.sh
```

Native runtime files:

```text
runtime/bearer-token-api-proxy.pid
logs/bearer-token-api-proxy.log
```

## Health and Readiness

```bash
curl http://127.0.0.1:8787/healthz
curl http://127.0.0.1:8787/readyz
curl http://127.0.0.1:8787/metrics
```

## Client Usage

Call the configured route prefix and allowed upstream path:

```text
GET http://127.0.0.1:8787/proxy/api/status
```

If `PROXY_API_KEY` is configured, send:

```http
X-Bearer-Proxy-Key: <configured value>
```

The client never sends the upstream bearer token.

## Docker Setup

Prepare runtime files:

```bash
cp config/proxy.env.example config/proxy.env
cp config/proxy.json.example config/proxy.json
chmod 600 config/proxy.env config/proxy.json
```

Build and run:

```bash
docker build -t bearer-token-api-proxy:latest .
docker compose -f compose.yml up -d
docker compose -f compose.yml ps
docker compose -f compose.yml logs -f bearer-token-api-proxy
```

Compose mounts configuration read-only:

```text
./config/proxy.env  -> /app/config/proxy.env:ro
./config/proxy.json -> /app/config/proxy.json:ro
./certs             -> /app/certs:ro
```

## Offline Docker Transfer

```bash
VERSION="$(tr -d '[:space:]' < TAG)"
docker build --build-arg APP_VERSION="$VERSION" \
  -t "bearer-token-api-proxy:$VERSION" \
  -t bearer-token-api-proxy:latest .
docker save -o "bearer-token-api-proxy_${VERSION}.tar" \
  "bearer-token-api-proxy:$VERSION" \
  bearer-token-api-proxy:latest
sha256sum "bearer-token-api-proxy_${VERSION}.tar" > "bearer-token-api-proxy_${VERSION}.tar.sha256"
printf '%s\n' "$VERSION" > IMAGE_VERSION.txt
```

## Troubleshooting

- `configuration_ok` fails: check missing `${ENV}` substitutions, invalid URLs, or unsafe bind settings.
- Authentication test fails: check auth path, body type, headers, credentials, token extraction, and auth TLS trust.
- Upstream calls fail: check allowed paths, method allowlist, upstream TLS trust, and network reachability.
- Request is 403: check route prefix, method policy, path policy, auth endpoint blocking, unsafe path, or request framing.

