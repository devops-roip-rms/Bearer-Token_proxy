import os
import pathlib
import tempfile
import unittest
from unittest import mock

from bearer_proxy import config
from bearer_proxy.errors import ConfigError
from bearer_proxy.security import validate_bind_security
from tests.helpers import base_config_dict, deep_update


class ConfigTests(unittest.TestCase):
    def test_env_file_is_authoritative_and_preserves_equals_hash(self):
        with tempfile.TemporaryDirectory() as td:
            env_file = pathlib.Path(td) / "proxy.env"
            env_file.write_text("AUTH_USERNAME=file-user\nAUTH_PASSWORD=p@ss=word#123\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"AUTH_USERNAME": "shell-user"}, clear=True):
                config.load_env_file(env_file)
                self.assertEqual(os.environ["AUTH_USERNAME"], "file-user")
                self.assertEqual(os.environ["AUTH_PASSWORD"], "p@ss=word#123")

    def test_placeholder_required_value_is_rejected(self):
        with mock.patch.dict(os.environ, {"X": "CHANGE_ME"}, clear=True):
            with self.assertRaises(ConfigError):
                config.required_env("X")

    def test_auth_and_upstream_base_urls_are_separate(self):
        cfg = config.parse_config(base_config_dict("https://auth.example", "https://api.example"))
        self.assertEqual(cfg.auth.base_url, "https://auth.example")
        self.assertEqual(cfg.upstream.base_url, "https://api.example")

    def test_recursive_environment_substitution(self):
        raw = base_config_dict("${AUTH_HOST}", "${UPSTREAM_HOST}")
        raw["auth"]["request"]["body"]["client_secret"] = "${SECRET_A}"
        with mock.patch.dict(
            os.environ,
            {
                "AUTH_HOST": "https://auth.example",
                "UPSTREAM_HOST": "https://api.example",
                "SECRET_A": "${SECRET_B}",
                "SECRET_B": "synthetic",
            },
            clear=True,
        ):
            cfg = config.parse_config(config.substitute_env(raw))
        self.assertEqual(cfg.auth.base_url, "https://auth.example")
        self.assertEqual(cfg.auth.request.body["client_secret"], "synthetic")

    def test_missing_environment_substitution_fails_without_value_leak(self):
        raw = base_config_dict("${MISSING}", "https://api.example")
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ConfigError) as ctx:
                config.substitute_env(raw)
        self.assertIn("MISSING", str(ctx.exception))
        self.assertNotIn("secret", str(ctx.exception).lower())

    def test_invalid_json_fails_clearly(self):
        with tempfile.TemporaryDirectory() as td:
            path = pathlib.Path(td) / "proxy.json"
            path.write_text("{not-json", encoding="utf-8")
            with self.assertRaises(ConfigError):
                config.load_json_config(path)

    def test_schema_version_is_required(self):
        raw = base_config_dict()
        raw["schema_version"] = 2
        with self.assertRaises(ConfigError):
            config.parse_config(raw)

    def test_invalid_method_is_rejected(self):
        raw = base_config_dict()
        raw["auth"]["request"]["method"] = "TRACE"
        with self.assertRaises(ConfigError):
            config.parse_config(raw)

    def test_route_prefix_validation(self):
        raw = base_config_dict()
        raw["upstream"]["route_prefix"] = "proxy"
        cfg = config.parse_config(raw)
        self.assertEqual(cfg.upstream.route_prefix, "/proxy")

    def test_allowed_path_validation_rejects_url(self):
        raw = base_config_dict()
        raw["upstream"]["allowed_paths"] = ["https://api.example/data"]
        with self.assertRaises(ConfigError):
            config.parse_config(raw)

    def test_token_extraction_configuration_required(self):
        raw = base_config_dict()
        raw["auth"]["token"].pop("json_pointer")
        with self.assertRaises(ConfigError):
            config.parse_config(raw)

    def test_bind_security_rejects_non_loopback_without_key(self):
        raw = base_config_dict()
        raw["server"]["bind_host"] = "0.0.0.0"
        cfg = config.parse_config(raw)
        with self.assertRaises(ConfigError):
            validate_bind_security(cfg)

    def test_bind_security_allows_non_loopback_with_key(self):
        raw = base_config_dict()
        raw["server"]["bind_host"] = "0.0.0.0"
        raw["server"]["proxy_api_key"] = "synthetic-key"
        cfg = config.parse_config(raw)
        validate_bind_security(cfg)

    def test_tls_inheritance_and_independent_ca_bundles(self):
        raw = base_config_dict()
        deep_update(
            raw,
            {
                "upstream": {"tls_verify": True, "ca_bundle": "certs/upstream.pem"},
                "auth": {"tls_verify": False, "ca_bundle": "certs/auth.pem"},
            },
        )
        cfg = config.parse_config(raw, project_root=pathlib.Path("C:/project"))
        self.assertTrue(cfg.upstream.tls.verify)
        self.assertFalse(cfg.auth.tls.verify)
        self.assertTrue(cfg.upstream.tls.ca_bundle.endswith("certs\\upstream.pem") or cfg.upstream.tls.ca_bundle.endswith("certs/upstream.pem"))
        self.assertTrue(cfg.auth.tls.ca_bundle.endswith("certs\\auth.pem") or cfg.auth.tls.ca_bundle.endswith("certs/auth.pem"))

    def test_auth_tls_inherits_upstream_when_omitted(self):
        raw = base_config_dict()
        raw["upstream"]["tls_verify"] = False
        raw["upstream"]["ca_bundle"] = "certs/shared.pem"
        raw["auth"].pop("tls_verify", None)
        raw["auth"].pop("ca_bundle", None)
        cfg = config.parse_config(raw, project_root=pathlib.Path("C:/project"))
        self.assertFalse(cfg.auth.tls.verify)
        self.assertEqual(cfg.auth.tls.ca_bundle, cfg.upstream.tls.ca_bundle)

    def test_size_configuration(self):
        raw = base_config_dict()
        raw["runtime"]["max_request_bytes"] = 10
        raw["runtime"]["max_response_bytes"] = 2048
        cfg = config.parse_config(raw)
        self.assertEqual(cfg.runtime.max_request_bytes, 10)
        self.assertEqual(cfg.runtime.max_response_bytes, 2048)


if __name__ == "__main__":
    unittest.main()

