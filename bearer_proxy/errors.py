"""Safe exception types for the Bearer Token API Proxy."""


class ProxyError(RuntimeError):
    """Base error for safe, user-visible operational failures."""


class ConfigError(ProxyError):
    """Configuration is missing, invalid, or unsafe."""


class TransportError(ProxyError):
    """The proxy could not communicate with an HTTP peer."""


class RequestTooLargeError(ProxyError):
    """The inbound client request exceeded configured limits."""


class ResponseTooLargeError(ProxyError):
    """The upstream response exceeded configured limits."""


class AuthenticationError(ProxyError):
    """Authentication failed or returned an unusable token."""


class AuthorizationPolicyError(ProxyError):
    """A client request was rejected by the local proxy security policy."""

