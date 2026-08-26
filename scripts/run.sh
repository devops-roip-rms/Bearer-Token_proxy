#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
exec python3 "$ROOT/app.py" --env-file "$ROOT/config/proxy.env" --config-file "$ROOT/config/proxy.json" "$@"
