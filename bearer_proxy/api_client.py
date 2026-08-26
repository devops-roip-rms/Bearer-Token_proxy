"""Bearer-authenticated upstream API forwarding."""


class UpstreamAPIClient(object):
    def __init__(self, cfg, http_client):
        self.cfg = cfg
        self.http_client = http_client

    def forward(self, method, path, query, headers, body, token):
        if query:
            path = path + "?" + query
        headers = dict(headers or {})
        headers[self.cfg.auth.token.header_name] = self.cfg.auth.token.authorization_value(token)
        return self.http_client.request(
            self.cfg.upstream.base_url,
            method,
            path,
            headers=headers,
            body=body,
        )

    def request_with_recovery(self, method, path, query, headers, body, token_manager):
        token = token_manager.ensure_token()
        response = self.forward(method, path, query, headers, body, token)
        if response.status != 401:
            return response
        token_manager.refresh_rejected_token(token)
        replacement = token_manager.get_token()
        if replacement is None or replacement == token:
            return response
        return self.forward(method, path, query, headers, body, replacement)

