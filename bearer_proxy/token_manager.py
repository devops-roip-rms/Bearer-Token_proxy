"""In-memory bearer token lifecycle management."""

import logging
import threading
import time

from .errors import AuthenticationError, ProxyError

LOG = logging.getLogger("bearer-token-api_proxy")


class TokenManager(object):
    """Owns the bearer token in RAM and refreshes it safely."""

    def __init__(self, cfg, auth_provider):
        self.cfg = cfg
        self.auth_provider = auth_provider
        self._state_lock = threading.Lock()
        self._refresh_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = None
        self._token = None
        self._last_success_epoch = None
        self._next_refresh_monotonic = 0.0
        self._last_error = False
        self._last_error_started_epoch = None
        self._consecutive_refresh_failures = 0
        self._next_attempt_monotonic = 0.0

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._refresh_loop,
            name="bearer-token-refresh",
        )
        self._thread.daemon = True
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def get_token(self):
        with self._state_lock:
            return self._token

    def _compute_refresh_delay(self, auth_result):
        runtime = self.cfg.runtime
        if auth_result.expires_in_seconds is None:
            delay = runtime.fallback_refresh_interval_seconds
        else:
            delay = auth_result.expires_in_seconds - runtime.refresh_margin_seconds
            if delay <= 0:
                delay = runtime.min_refresh_interval_seconds
        if delay < runtime.min_refresh_interval_seconds:
            delay = runtime.min_refresh_interval_seconds
        return delay

    def _perform_refresh_locked(self):
        try:
            auth_result = self.auth_provider.authenticate()
            candidate = auth_result.token
            self.auth_provider.validate_token(candidate)
        except Exception:
            now_epoch = time.time()
            now_mono = time.monotonic()
            with self._state_lock:
                if self._last_error_started_epoch is None:
                    self._last_error_started_epoch = now_epoch
                self._last_error = True
                self._consecutive_refresh_failures += 1
                self._next_attempt_monotonic = now_mono + self.cfg.runtime.refresh_retry_seconds
            raise

        refresh_delay = self._compute_refresh_delay(auth_result)
        now_epoch = time.time()
        now_mono = time.monotonic()
        with self._state_lock:
            self._token = candidate
            self._last_success_epoch = now_epoch
            self._next_refresh_monotonic = now_mono + refresh_delay
            self._next_attempt_monotonic = self._next_refresh_monotonic
            self._last_error = False
            self._last_error_started_epoch = None
            self._consecutive_refresh_failures = 0
        LOG.info("New bearer token validated and installed in memory")
        return True

    def refresh(self, force=False):
        with self._refresh_lock:
            now_mono = time.monotonic()
            with self._state_lock:
                if not force and now_mono < self._next_attempt_monotonic:
                    return False
                if not force and self._token is not None and now_mono < self._next_refresh_monotonic:
                    return False
            return self._perform_refresh_locked()

    def refresh_rejected_token(self, rejected_token):
        with self._refresh_lock:
            now_mono = time.monotonic()
            with self._state_lock:
                if self._token != rejected_token:
                    return False
                if self._last_error and now_mono < self._next_attempt_monotonic:
                    return False
            return self._perform_refresh_locked()

    def ensure_token(self):
        token = self.get_token()
        if token is not None:
            return token
        self.refresh(force=False)
        token = self.get_token()
        if token is None:
            raise AuthenticationError("No bearer token is available")
        return token

    def seconds_until_refresh(self):
        with self._state_lock:
            if self._token is None:
                return 0.0
            return max(0.0, self._next_refresh_monotonic - time.monotonic())

    def snapshot(self):
        now_epoch = time.time()
        with self._state_lock:
            last_success = self._last_success_epoch
            token_loaded = self._token is not None
            last_error = self._last_error
            last_error_started = self._last_error_started_epoch
            consecutive_failures = self._consecutive_refresh_failures
            next_seconds = max(0.0, self._next_refresh_monotonic - time.monotonic()) if token_loaded else 0.0
        return {
            "token_loaded": token_loaded,
            "last_refresh_utc": (
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(last_success))
                if last_success is not None
                else None
            ),
            "seconds_until_refresh": int(next_seconds),
            "last_refresh_error": bool(last_error),
            "refresh_error_age_seconds": (
                int(max(0.0, now_epoch - last_error_started))
                if last_error_started is not None
                else None
            ),
            "seconds_since_last_success": (
                int(max(0.0, now_epoch - last_success))
                if last_success is not None
                else None
            ),
            "consecutive_refresh_failures": consecutive_failures,
        }

    def _refresh_loop(self):
        delay = 0.0
        while not self._stop_event.wait(delay):
            try:
                changed = self.refresh(force=False)
                if changed:
                    delay = self.seconds_until_refresh()
                else:
                    delay = max(
                        self.cfg.runtime.min_refresh_interval_seconds,
                        self.seconds_until_refresh(),
                    )
            except Exception:
                LOG.error("Scheduled token refresh failed")
                delay = self.cfg.runtime.refresh_retry_seconds
