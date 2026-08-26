#!/usr/bin/env python3
"""Bearer Token API Proxy."""

import argparse
import logging
import os
import sys

from bearer_proxy.config import DEFAULT_CONFIG_FILE, DEFAULT_ENV_FILE, load_config
from bearer_proxy.errors import ProxyError
from bearer_proxy.server import check_configuration, run_server, test_authentication

LOG = logging.getLogger("bearer-token-api-proxy")


def configure_logging(level):
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description="Bearer Token API Proxy")
    parser.add_argument(
        "--env-file",
        default=str(DEFAULT_ENV_FILE),
        help="Path to proxy.env (default: <project>/config/proxy.env)",
    )
    parser.add_argument(
        "--config-file",
        default=str(DEFAULT_CONFIG_FILE),
        help="Path to proxy.json (default: <project>/config/proxy.json)",
    )
    parser.add_argument("--check-config", action="store_true", help="Validate local configuration and exit")
    parser.add_argument("--test-auth", action="store_true", help="Authenticate once, validate if configured, and exit")
    parser.add_argument("--test-upstream", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    try:
        cfg = load_config(env_file=args.env_file, config_file=args.config_file)
        configure_logging(cfg.runtime.log_level)
        if args.check_config:
            check_configuration(cfg)
            print("configuration_ok=yes")
            return 0
        if args.test_auth or args.test_upstream:
            result = test_authentication(cfg)
            print("authentication_test=ok")
            print("validation={0}".format("enabled" if cfg.auth.validation.enabled else "disabled"))
            if result.expires_in_seconds is not None:
                print("expires_in_seconds={0}".format(int(result.expires_in_seconds)))
            return 0
        return run_server(cfg)
    except ProxyError as exc:
        configure_logging(os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO")
        LOG.error("%s", exc)
        return 1
    except Exception:
        configure_logging(os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO")
        LOG.exception("Unexpected fatal failure")
        return 1


if __name__ == "__main__":
    sys.exit(main())
