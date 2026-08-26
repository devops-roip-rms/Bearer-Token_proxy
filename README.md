# Bearer Token API Proxy

Bearer Token API Proxy is a configurable HTTP proxy for APIs that use bearer-style access tokens. It sends one configured authentication request, extracts the token from the authentication response, keeps that token in memory, and injects it into allowed protected API requests.

The customer normally edits only:

```text
config/proxy.env
config/proxy.json
```

Python source changes are not required for a new compatible API.

## Architecture

```text
Customer / Application
  -> Proxy Server
  -> Request Security Policy
  -> Token Manager
  -> Auth Provider
  -> Bearer API Client
  -> Customer Protected API
```

One running proxy instance manages one authentication profile and one upstream API.

## Supported Authentication Scope

Version 1 supports authentication patterns that can be represented as:

```text
one configurable HTTP authentication request
  -> token returned in response
  -> token extracted
  -> token injected into protected API requests
```

Supported authentication request body types:

```text
none
json
form
raw
```

Supported token sources:

```text
JSON response
response header
plain response text
```

Out of scope for v1:

```text
interactive browser login
SAML browser flows
MFA interaction
OAuth authorization-code redirect flow
Kerberos/NTLM negotiation
multi-step login sequences requiring arbitrary scripting
```

## Configuration

Setup flow:

1. Copy `config/proxy.env.example` to `config/proxy.env`.
2. Copy `config/proxy.json.example` to `config/proxy.json`.
3. Set the authentication server.
4. Set the upstream API server.
5. Describe the authentication HTTP request.
6. Define where the token is returned.
7. Define how the token is injected.
8. Optionally define token validation.
9. Define refresh behavior.
10. Define allowed API methods.
11. Define allowed API path prefixes.
12. Configure TLS trust.
13. Configure the local proxy key.
14. Run `--check-config`.
15. Run `--test-auth`.
16. Start the proxy.

`proxy.env` may contain arbitrary variable names. `proxy.json` decides how those variables are used with `${VARIABLE_NAME}` substitutions.

## Token Lifecycle

```text
startup/on demand
  -> authenticate
  -> validate candidate if enabled
  -> install only after validation succeeds

background
  -> refresh before expiry or by fallback interval
  -> retry failed refresh after backoff

upstream HTTP 401
  -> authenticate once
  -> replay the original request once
```

The active token is stored only in process memory.

## API Forwarding

Clients call the configured route prefix:

```text
GET http://127.0.0.1:8787/proxy/api/status
```

The proxy forwards only configured methods and allowed paths. Client `Authorization` is stripped, hop-by-hop headers are removed, and the configured token header is injected.

## Examples

Neutral examples are provided in:

```text
examples/json-login/
examples/oauth-client-credentials/
examples/header-token/
```

All examples use fictional hosts such as:

```text
https://auth.example.internal
https://api.example.internal
```

## Security

See [docs/SECURITY_MODEL.md](docs/SECURITY_MODEL.md). Important defaults:

- callers cannot choose the upstream host
- authentication endpoint is blocked from the proxy route
- methods and paths are allowlisted
- TLS verification is enabled by default
- authentication and upstream TLS can use separate CA bundles
- non-loopback binds require a local proxy key unless explicitly overridden
- redirects are not followed automatically
- ambiguous request framing is rejected
- readiness and metrics do not expose tokens

## Deployment

Native:

```bash
sh scripts/setup.sh
./scripts/check-config.sh
./scripts/test-auth.sh
./scripts/start.sh
```

Docker:

```bash
docker build -t bearer-token-api-proxy:latest .
docker compose -f compose.yml up -d
```

Offline artifacts use `docker save` with the image name `bearer-token-api-proxy`.

## Documentation

- [Integration Guide](docs/INTEGRATION_GUIDE.md)
- [Configuration Reference](docs/CONFIG_REFERENCE.md)
- [Security Model](docs/SECURITY_MODEL.md)
- [Setup Guide](docs/SETUP_GUIDE.md)
- [Build Report](docs/BUILD_REPORT.md)

## Versioning

`TAG` is the plain-text image version source. Editing `TAG` does not create a Git tag.

Current development version:

```text
v0.1.0
```

