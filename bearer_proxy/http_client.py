"""Standard-library HTTP transport helpers."""

import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .errors import ResponseTooLargeError, TransportError


class HTTPResponse(object):
    def __init__(self, status, body, headers):
        self.status = int(status)
        self.body = body
        self.headers = headers

    def header(self, name, default=None):
        wanted = name.lower()
        for key, value in self.headers.items():
            if key.lower() == wanted:
                return value
        return default


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HTTPClient(object):
    def __init__(self, timeout, max_response_bytes, context=None):
        self.timeout = timeout
        self.max_response_bytes = max_response_bytes
        self.context = context
        if context is None:
            self.opener = urllib.request.build_opener(NoRedirectHandler)
        else:
            self.opener = urllib.request.build_opener(
                NoRedirectHandler,
                urllib.request.HTTPSHandler(context=context),
            )

    def request(self, base_url, method, path, headers=None, body=None):
        url = base_url.rstrip("/") + path
        request = urllib.request.Request(
            url=url,
            data=body,
            headers=headers or {},
            method=method,
        )
        try:
            response = self.opener.open(request, timeout=self.timeout)
            try:
                return self._read_response(response)
            finally:
                response.close()
        except urllib.error.HTTPError as exc:
            try:
                return self._read_response(exc)
            finally:
                exc.close()
        except urllib.error.URLError:
            raise TransportError("HTTP transport failure")
        except (TimeoutError, socket_timeout_error()):
            raise TransportError("HTTP transport timeout")

    def _read_response(self, response):
        body = response.read(self.max_response_bytes + 1)
        if len(body) > self.max_response_bytes:
            raise ResponseTooLargeError("HTTP response exceeded configured maximum size")
        headers = {}
        for key, value in response.headers.items():
            headers[key] = value
        status = getattr(response, "status", None)
        if status is None:
            status = response.code
        return HTTPResponse(status, body, headers)


def socket_timeout_error():
    import socket

    return socket.timeout


def build_ssl_context(tls_config):
    if not tls_config.verify:
        return ssl._create_unverified_context()
    if tls_config.ca_bundle:
        if not Path(tls_config.ca_bundle).is_file():
            raise TransportError("Configured CA bundle file does not exist")
        return ssl.create_default_context(cafile=tls_config.ca_bundle)
    return ssl.create_default_context()
