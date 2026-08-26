import json
import threading
import time
import unittest

from bearer_proxy.auth import AuthResult
from bearer_proxy.errors import AuthenticationError
from bearer_proxy.token_manager import TokenManager
from tests.helpers import make_config


class FakeProvider(object):
    def __init__(self, tokens=None, validate_error=None):
        self.tokens = list(tokens or [AuthResult("TOKEN")])
        self.validate_error = validate_error
        self.auth_count = 0
        self.validated = []

    def authenticate(self):
        self.auth_count += 1
        item = self.tokens.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def validate_token(self, token):
        self.validated.append(token)
        if self.validate_error:
            raise self.validate_error
        return True


class TokenManagerTests(unittest.TestCase):
    def test_refresh_validates_before_installing_candidate(self):
        cfg = make_config()
        provider = FakeProvider([AuthResult("NEW_TOKEN")])
        manager = TokenManager(cfg, provider)
        manager.refresh(force=True)
        self.assertEqual(provider.validated, ["NEW_TOKEN"])
        self.assertEqual(manager.get_token(), "NEW_TOKEN")

    def test_failed_candidate_does_not_replace_good_token(self):
        cfg = make_config()
        provider = FakeProvider([AuthResult("OLD"), AuthResult("BAD")])
        manager = TokenManager(cfg, provider)
        manager.refresh(force=True)
        provider.validate_error = AuthenticationError("validation failed")
        with self.assertRaises(AuthenticationError):
            manager.refresh(force=True)
        self.assertEqual(manager.get_token(), "OLD")

    def test_regular_background_refresh(self):
        cfg = make_config({"runtime": {"fallback_refresh_interval_seconds": 0.05, "refresh_retry_seconds": 0.05, "min_refresh_interval_seconds": 0.01}})
        provider = FakeProvider([AuthResult("A"), AuthResult("B"), AuthResult("C")])
        manager = TokenManager(cfg, provider)
        manager.start()
        try:
            deadline = time.time() + 1
            while provider.auth_count < 3 and time.time() < deadline:
                time.sleep(0.02)
            self.assertGreaterEqual(provider.auth_count, 3)
            self.assertEqual(manager.get_token(), "C")
        finally:
            manager.stop()

    def test_failed_refresh_backoff_and_initial_failure(self):
        cfg = make_config({"runtime": {"refresh_retry_seconds": 10}})
        provider = FakeProvider([AuthenticationError("temporary")])
        manager = TokenManager(cfg, provider)
        with self.assertRaises(AuthenticationError):
            manager.refresh(force=False)
        self.assertFalse(manager.refresh(force=False))
        self.assertIsNone(manager.get_token())
        self.assertEqual(provider.auth_count, 1)

    def test_concurrent_401_refresh_installs_once(self):
        cfg = make_config()
        provider = FakeProvider([AuthResult("OLD"), AuthResult("NEW")])
        manager = TokenManager(cfg, provider)
        manager.refresh(force=True)
        barrier = threading.Barrier(2)
        results = []

        def recover():
            barrier.wait(timeout=2)
            results.append(manager.refresh_rejected_token("OLD"))

        threads = [threading.Thread(target=recover), threading.Thread(target=recover)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)
        self.assertEqual(manager.get_token(), "NEW")
        self.assertEqual(provider.auth_count, 2)
        self.assertEqual(results.count(True), 1)

    def test_health_snapshot_excludes_token_and_error_detail(self):
        cfg = make_config()
        provider = FakeProvider([AuthResult("SECRET_TOKEN"), AuthenticationError("sensitive outage detail")])
        manager = TokenManager(cfg, provider)
        manager.refresh(force=True)
        with self.assertRaises(AuthenticationError):
            manager.refresh(force=True)
        snapshot_text = json.dumps(manager.snapshot())
        self.assertNotIn("SECRET_TOKEN", snapshot_text)
        self.assertNotIn("sensitive outage detail", snapshot_text)
        self.assertIn("consecutive_refresh_failures", snapshot_text)
        self.assertIn("refresh_error_age_seconds", snapshot_text)

    def test_expires_in_scheduling_margin_and_minimum(self):
        cfg = make_config({"runtime": {"refresh_margin_seconds": 10, "min_refresh_interval_seconds": 2}})
        provider = FakeProvider([AuthResult("TOKEN", expires_in_seconds=20)])
        manager = TokenManager(cfg, provider)
        manager.refresh(force=True)
        self.assertLessEqual(manager.seconds_until_refresh(), 10)
        self.assertGreater(manager.seconds_until_refresh(), 7)

        provider2 = FakeProvider([AuthResult("TOKEN", expires_in_seconds=5)])
        manager2 = TokenManager(cfg, provider2)
        manager2.refresh(force=True)
        self.assertGreater(manager2.seconds_until_refresh(), 1)

    def test_fallback_interval_when_expiry_absent(self):
        cfg = make_config({"runtime": {"fallback_refresh_interval_seconds": 42}})
        manager = TokenManager(cfg, FakeProvider([AuthResult("TOKEN")]))
        manager.refresh(force=True)
        self.assertLessEqual(manager.seconds_until_refresh(), 42)
        self.assertGreater(manager.seconds_until_refresh(), 39)


if __name__ == "__main__":
    unittest.main()

