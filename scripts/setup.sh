#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

if ! command -v python >/dev/null 2>&1; then
    echo "ERROR: python is not installed or not in PATH" >&2
    exit 1
fi

if ! python -c 'import sys; sys.exit(0 if sys.version_info >= (3, 6) else 1)'; then
    echo "ERROR: Python 3.6 or newer is required" >&2
    python --version >&2 || true
    exit 1
fi

echo "python=$(python --version 2>&1)"
mkdir -p "$ROOT/logs" "$ROOT/runtime" "$ROOT/certs"
chmod +x "$ROOT"/scripts/*.sh
chmod 600 "$ROOT/config/proxy.env" 2>/dev/null || true
chmod 600 "$ROOT/config/proxy.json" 2>/dev/null || true

# Verify shell syntax before doing anything network-related.
for script in "$ROOT"/scripts/*.sh; do
    sh -n "$script"
done

echo "scripts_ok=yes"
echo "setup_ok=yes"
if [ ! -f "$ROOT/config/proxy.json" ]; then
    echo "config_json_missing=yes"
    echo "Next: copy an example proxy.json into config/proxy.json, then run ./scripts/check-config.sh"
else
    echo "Next: edit config/proxy.env and config/proxy.json if needed, then run ./scripts/check-config.sh"
fi
