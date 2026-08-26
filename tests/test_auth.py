import json
import unittest

from bearer_proxy.auth import AuthProvider, json_pointer_get
from bearer_proxy.errors import AuthenticationError
from bearer_proxy.http_client import HTTPResponse
from tests.helpers import DummyHTTPClient, json_response, make_config


class AuthTests(unittest.TestCase):
    def _provider(self, cfg, auth_responses, validation_responses=None):
        return AuthProvider(
            cfg,
            DummyHTTPClient(auth_responses),
            DummyHTTPClient(validation_responses or [json_response({"ok": True})]),
        )

    def test_json_authentication_request(self):
        cfg = make_config()
        auth_client = DummyHTTPClient([json_response({"access_token": "TOKEN", "expires_in": 3600})])
        provider = AuthProvider(cfg, auth_client, DummyHTTPClient([json_response({"ok": True})]))
        result = provider.authenticate()
        self.assertEqual(result.token, "TOKEN")
        self.assertEqual(json.loads(auth_client.requests[0]["body"].decode("utf-8"))["client_secret"], "secret")

    def test_form_urlencoded_authentication(self):
        cfg = make_config({"auth": {"request": {"body_type": "form", "body": {"grant_type": "client_credentials", "client_id": "id"}}}})
        auth_client = DummyHTTPClient([json_response({"access_token": "TOKEN", "expires_in": 3600})])
        AuthProvider(cfg, auth_client, DummyHTTPClient()).authenticate()
        self.assertEqual(auth_client.requests[0]["headers"]["Content-Type"], "application/x-www-form-urlencoded")
        self.assertIn(b"grant_type=client_credentials", auth_client.requests[0]["body"])

    def test_raw_body_authentication(self):
        cfg = make_config({"auth": {"request": {"body_type": "raw", "body": "raw-secret-body"}}})
        auth_client = DummyHTTPClient([json_response({"access_token": "TOKEN", "expires_in": 3600})])
        AuthProvider(cfg, auth_client, DummyHTTPClient()).authenticate()
        self.assertEqual(auth_client.requests[0]["body"], b"raw-secret-body")

    def test_no_body_authentication(self):
        cfg = make_config({"auth": {"request": {"body_type": "none", "body": None}}})
        auth_client = DummyHTTPClient([json_response({"access_token": "TOKEN", "expires_in": 3600})])
        AuthProvider(cfg, auth_client, DummyHTTPClient()).authenticate()
        self.assertIsNone(auth_client.requests[0]["body"])

    def test_custom_auth_headers(self):
        cfg = make_config({"auth": {"request": {"headers": {"X-Auth": "synthetic"}}}})
        auth_client = DummyHTTPClient([json_response({"access_token": "TOKEN", "expires_in": 3600})])
        AuthProvider(cfg, auth_client, DummyHTTPClient()).authenticate()
        self.assertEqual(auth_client.requests[0]["headers"]["X-Auth"], "synthetic")

    def test_json_pointer_data_and_access_token_extraction(self):
        cfg = make_config({"auth": {"token": {"json_pointer": "/data", "expires_in_json_pointer": None}}})
        self.assertEqual(self._provider(cfg, [json_response({"data": "DATA_TOKEN"})]).authenticate().token, "DATA_TOKEN")
        cfg2 = make_config()
        self.assertEqual(self._provider(cfg2, [json_response({"access_token": "ACCESS_TOKEN", "expires_in": 3600})]).authenticate().token, "ACCESS_TOKEN")

    def test_nested_json_pointer_and_rfc6901_escaping(self):
        payload = {"response": {"auth": {"a/b": "SLASH", "m~n": "TILDE"}}}
        self.assertEqual(json_pointer_get(payload, "/response/auth/a~1b"), "SLASH")
        self.assertEqual(json_pointer_get(payload, "/response/auth/m~0n"), "TILDE")

    def test_invalid_json_pointer_fails_safely(self):
        with self.assertRaises(AuthenticationError):
            json_pointer_get({"a": 1}, "/a~2b")

    def test_token_from_header(self):
        cfg = make_config({"auth": {"token": {"source": "header", "response_header_name": "X-Token", "json_pointer": None, "expires_in_json_pointer": None}}})
        response = HTTPResponse(200, b"", {"X-Token": "HEADER_TOKEN"})
        self.assertEqual(self._provider(cfg, [response]).authenticate().token, "HEADER_TOKEN")

    def test_token_from_text(self):
        cfg = make_config({"auth": {"token": {"source": "text", "json_pointer": None, "expires_in_json_pointer": None}}})
        response = HTTPResponse(200, b"TEXT_TOKEN\n", {"Content-Type": "text/plain"})
        self.assertEqual(self._provider(cfg, [response]).authenticate().token, "TEXT_TOKEN")

    def test_missing_or_invalid_token_fails(self):
        cfg = make_config()
        with self.assertRaises(AuthenticationError):
            self._provider(cfg, [json_response({"access_token": ""})]).authenticate()
        with self.assertRaises(AuthenticationError):
            self._provider(cfg, [json_response({"access_token": {"not": "string"}})]).authenticate()

    def test_expires_in_extraction(self):
        cfg = make_config()
        result = self._provider(cfg, [json_response({"access_token": "TOKEN", "expires_in": "42"})]).authenticate()
        self.assertEqual(result.expires_in_seconds, 42.0)

    def test_validation_enabled_disabled_and_failed(self):
        cfg = make_config()
        provider = self._provider(cfg, [json_response({"access_token": "TOKEN", "expires_in": 3600})], [HTTPResponse(200, b"", {})])
        result = provider.authenticate()
        self.assertTrue(provider.validate_token(result.token))

        disabled = make_config({"auth": {"validation": {"enabled": False}}})
        self.assertTrue(self._provider(disabled, []).validate_token("TOKEN"))

        failed = make_config()
        with self.assertRaises(AuthenticationError):
            self._provider(failed, [], [HTTPResponse(401, b"", {})]).validate_token("TOKEN")

    def test_no_secret_leakage_on_failed_auth(self):
        cfg = make_config()
        provider = self._provider(cfg, [HTTPResponse(401, b'{"error":"bad secret"}', {"Content-Type": "application/json"})])
        with self.assertRaises(AuthenticationError) as ctx:
            provider.authenticate()
        self.assertNotIn("secret", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()

